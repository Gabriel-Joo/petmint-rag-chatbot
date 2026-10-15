"""
customers.py
샘플 고객 로드 + 검증 + pet → SearchScope 변환(09 6-1).

로더가 검증하는 이유: section_name에 오타가 나면 검색 필터가 조용히 0건이 된다. 하나라도 어긋나면 예외를 던져
기동(lifespan)을 실패시킨다. 약관 식별자(doc_id·product_name·policy_version)와 가입일(약관 effective_date 이후)도
청크 메타와 대조한다. SearchScope는 data/search_scope.py를 그대로 쓴다 — 08 평가와 같은 필터여야 한다(3-3).
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from data.rag_context import CHUNK_FILES
from data.search_scope import MEDICAL_SECTIONS, SearchScope

from app.schemas import Customer, Pet

EXCLUSION_SECTION = "반려동물 특정 질병 보장제한부 인수 특별약관"   # 부담보가 붙는 특약


class CustomerDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class PolicyDoc:
    """약관 문서 하나의 청크 메타. 날짜는 고객 레코드에 복사하지 않고 여기서 조회한다"""
    doc_id: str
    species: str
    product_name: str
    policy_version: str
    effective_date: date
    expiry_date: date | None
    section_names: frozenset[str]                  # null(보통약관) 제외


def load_policy_docs(species: str) -> dict[str, PolicyDoc]:
    """그 종 청크 파일에 든 약관 문서들(doc_id → 메타). 한 doc_id 안에서 메타가 갈리면 청크 쪽 오류다"""
    with open(CHUNK_FILES[species], encoding="utf-8") as f:
        chunks = json.load(f)
    groups: dict[str, list[dict]] = {}
    for c in chunks:
        groups.setdefault(c["doc_id"], []).append(c)
    docs = {}
    for doc_id, cs in groups.items():
        metas = {(c["product_name"], c["policy_version"], c["effective_date"], c["expiry_date"]) for c in cs}
        if len(metas) != 1:
            raise CustomerDataError(f"{species} 청크의 {doc_id} 메타가 하나가 아니다: {metas}")
        product, version, eff, exp = metas.pop()
        docs[doc_id] = PolicyDoc(doc_id, species, product, version, date.fromisoformat(eff),
                                 date.fromisoformat(exp) if exp else None,
                                 frozenset(c["section_name"] for c in cs if c.get("section_name")))
    return docs


def scope_for(pet: Pet) -> SearchScope:
    return SearchScope.for_policies(pet.species, [{"section_name": p.section_name, "coverage_type": p.coverage_type}
                                                  for p in pet.policies])


def _validate(customers: list[Customer], docs: dict[str, dict[str, PolicyDoc]]) -> list[str]:
    errors = []
    seen_customers, seen_pets = set(), set()
    for c in customers:
        if c.customer_id in seen_customers:
            errors.append(f"{c.customer_id}: customer_id 중복")
        seen_customers.add(c.customer_id)
        for pet in c.pets:
            where = f"{c.customer_id}/{pet.pet_id}"
            if pet.pet_id in seen_pets:
                errors.append(f"{where}: pet_id 중복")
            seen_pets.add(pet.pet_id)
            for p in pet.policies:
                doc = docs[pet.species].get(p.doc_id)
                if doc is None:
                    errors.append(f"{where}: {pet.species} 청크에 없는 doc_id: {p.doc_id!r}")
                    continue
                if (p.product_name, p.policy_version) != (doc.product_name, doc.policy_version):
                    errors.append(f"{where}: {p.doc_id} 상품명·버전이 청크와 다르다: "
                                  f"{(p.product_name, p.policy_version)} != {(doc.product_name, doc.policy_version)}")
                if p.contract_date < doc.effective_date:
                    errors.append(f"{where}: 가입일 {p.contract_date}이 약관 시행일 {doc.effective_date}보다 앞선다: "
                                  f"{p.section_name}")
                if p.section_name not in doc.section_names:
                    errors.append(f"{where}: {p.doc_id} 청크에 없는 section_name: {p.section_name!r}")
                    continue
                medical = p.section_name in MEDICAL_SECTIONS[pet.species]
                if medical and p.coverage_type is None:
                    errors.append(f"{where}: 의료비 특약에 등급이 없다: {p.section_name}")
                if not medical and p.coverage_type is not None:
                    errors.append(f"{where}: 의료비 특약이 아닌데 등급이 있다: {p.section_name}")
                if p.excluded_conditions and p.section_name != EXCLUSION_SECTION:
                    errors.append(f"{where}: 부담보는 {EXCLUSION_SECTION}에만 둔다: {p.section_name}")
            try:
                scope_for(pet)
            except ValueError as e:
                errors.append(f"{where}: SearchScope 생성 실패: {e}")
    return errors


class CustomerStore:
    def __init__(self, customers: list[Customer], docs: dict[str, dict[str, PolicyDoc]]):
        self._by_id = {c.customer_id: c for c in customers}
        self._docs = {d.doc_id: d for per_species in docs.values() for d in per_species.values()}

    @classmethod
    def load(cls, path: Path) -> "CustomerStore":
        """JSON 로드 + 청크 메타 대조. 어긋나면 CustomerDataError(기동 실패)"""
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        try:
            customers = [Customer.model_validate(r) for r in raw]
        except ValueError as e:
            raise CustomerDataError(f"{path}: 스키마 오류\n{e}") from e
        docs = {sp: load_policy_docs(sp) for sp in {p.species for c in customers for p in c.pets}}
        errors = _validate(customers, docs)
        if errors:
            raise CustomerDataError(f"{path}: 고객 데이터 검증 실패 {len(errors)}건\n" + "\n".join(errors))
        return cls(customers, docs)

    def policy_doc(self, doc_id: str) -> PolicyDoc | None:
        """화면에 약관 시행일 등을 띄울 때 — 고객 레코드가 아니라 청크 메타에서 조회"""
        return self._docs.get(doc_id)

    def all(self) -> list[Customer]:
        return list(self._by_id.values())

    def get(self, customer_id: str) -> Customer | None:
        return self._by_id.get(customer_id)

    def pet_of(self, customer_id: str, pet_id: str) -> Pet | None:
        """그 고객의 반려동물이면 Pet, 아니면 None — 메시지의 pet_id가 세션 고객의 것인지 검증(6-2)"""
        c = self._by_id.get(customer_id)
        return next((p for p in c.pets if p.pet_id == pet_id), None) if c else None

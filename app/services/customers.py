"""
customers.py
고객 원장 읽기 + 검증 + pet → SearchScope 변환(09 6-1).

고객은 보험사 기간계(insurance_core)에 있고 챗봇은 읽기만 한다(SELECT 계정). 원장은 앱 밖에서 바뀌므로 캐시하지 않고
요청마다 읽는다 — 등급이 바뀌면 다음 턴부터 새 등급이 scope에 들어가고, 지난 턴은 turn_scope 스냅샷 그대로다(12번 2-2절).

검증하는 이유: section_name에 오타가 나면 검색 필터가 조용히 0건이 된다. 기동 때 전체를 검증해 하나라도 어긋나면
기동(lifespan)을 실패시키고, 읽을 때마다 같은 검증을 다시 건다(기동 뒤에 원장이 바뀌었을 수 있다). 약관 식별자
(doc_id·product_name·policy_version)와 가입일(약관 effective_date 이후)도 청크 메타와 대조한다.
SearchScope는 data/search_scope.py를 그대로 쓴다 — 08 평가와 같은 필터여야 한다(3-3).
"""

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Engine, text

from data.search_scope import MEDICAL_SECTIONS, SearchScope

from app.schemas import Customer, Pet

EXCLUSION_SECTION = "반려동물 특정 질병 보장제한부 인수 특별약관"   # 부담보가 붙는 특약


class CustomerDataError(RuntimeError):
    """원장 데이터가 깨졌다 — 요청 쪽 문제가 아니라 상담원이 할 수 있는 일이 없다. 메시지에 어느 고객의 어느 값인지 담는다
    (서버 로그용). 화면에는 USER_MESSAGE만 보인다"""


USER_MESSAGE = "고객 정보를 불러올 수 없습니다. 관리자에게 문의하세요."


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


def load_policy_docs(species: str, chunks: list[dict]) -> dict[str, PolicyDoc]:
    """그 종 청크에 든 약관 문서들(doc_id → 메타). 한 doc_id 안에서 메타가 갈리면 청크 쪽 오류다"""
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


def _fetch(engine: Engine, customer_id: str | None = None) -> list[Customer]:
    """원장 세 테이블 → Customer(09 6-1 JSON 모양). customer_id를 주면 그 고객만. 순서는 seq(픽스처 순서)"""
    where, params = ("WHERE customer_id = :cid", dict(cid=customer_id)) if customer_id else ("", {})
    with engine.connect() as c:
        cs = c.execute(text(f"SELECT customer_id, name, phone FROM customers {where} ORDER BY customer_id"), params).all()
        ps = c.execute(text(f"SELECT pet_id, customer_id, name, species, breed, age FROM pets {where}"
                            " ORDER BY customer_id, seq"), params).all()
        pol_where = "WHERE p.customer_id = :cid" if customer_id else ""
        pols = c.execute(text("SELECT pol.* FROM policies pol JOIN pets p USING (pet_id) "
                              f"{pol_where} ORDER BY pol.pet_id, pol.seq"), params).all()
    by_pet: dict[str, list[dict]] = {}
    for r in pols:
        excl = r.excluded_conditions
        by_pet.setdefault(r.pet_id, []).append(dict(
            doc_id=r.doc_id, product_name=r.product_name, policy_version=r.policy_version, section_name=r.section_name,
            coverage_type=r.coverage_type, copay=r.copay, contract_date=r.contract_date, renewal=r.renewal,
            excluded_conditions=json.loads(excl) if isinstance(excl, str) else (excl or [])))
    by_customer: dict[str, list[dict]] = {}
    for r in ps:
        by_customer.setdefault(r.customer_id, []).append(dict(
            pet_id=r.pet_id, name=r.name, species=r.species, breed=r.breed, age=r.age, policies=by_pet.get(r.pet_id, [])))
    out, errors = [], []
    for r in cs:
        try:
            out.append(Customer.model_validate(dict(customer_id=r.customer_id, name=r.name, phone=r.phone,
                                                    pets=by_customer.get(r.customer_id, []))))
        except ValueError as e:                    # 어느 고객인지 남긴다 — pydantic 메시지에는 값만 있다
            errors.append(f"{r.customer_id}: {e}")
    if errors:
        raise CustomerDataError(f"고객 원장 스키마 오류 {len(errors)}건\n" + "\n".join(errors))
    return out


class CustomerStore:
    def __init__(self, engine: Engine, docs: dict[str, dict[str, PolicyDoc]]):
        self.engine = engine
        self._docs = {d.doc_id: d for per_species in docs.values() for d in per_species.values()}
        self._docs_by_species = docs

    @classmethod
    def load(cls, engine: Engine, chunks: dict[str, list[dict]]) -> "CustomerStore":
        """원장 전체를 한 번 읽어 청크 메타와 대조한다. 어긋나면 CustomerDataError(기동 실패).
        chunks는 policy_data.load()가 읽은 것 — 약관 문서 메타(doc_id·시행일·section_name)를 여기서 만든다"""
        docs = {sp: load_policy_docs(sp, chunks[sp]) for sp in ("강아지", "고양이")}
        store = cls(engine, docs)
        customers = _fetch(engine)
        if not customers:
            raise CustomerDataError("고객 원장(insurance_core)이 비어 있다 — python -m db.seed_insurance_core")
        store._check(customers)
        return store

    def _check(self, customers: list[Customer]) -> list[Customer]:
        errors = _validate(customers, self._docs_by_species)
        if errors:
            raise CustomerDataError(f"고객 원장 검증 실패 {len(errors)}건\n" + "\n".join(errors))
        return customers

    def policy_doc(self, doc_id: str) -> PolicyDoc | None:
        """화면에 약관 시행일 등을 띄울 때 — 고객 레코드가 아니라 청크 메타에서 조회"""
        return self._docs.get(doc_id)

    def all(self) -> list[Customer]:
        return self._check(_fetch(self.engine))

    def get(self, customer_id: str) -> Customer | None:
        found = self._check(_fetch(self.engine, customer_id))
        return found[0] if found else None

    def pet_of(self, customer_id: str, pet_id: str) -> Pet | None:
        """그 고객의 반려동물이면 Pet, 아니면 None — 메시지의 pet_id가 세션 고객의 것인지 검증(6-2).
        턴마다 원장을 다시 읽는다 — 이 값이 그 턴의 스냅샷(turn_scope)이 된다"""
        c = self.get(customer_id)
        return next((p for p in c.pets if p.pet_id == pet_id), None) if c else None

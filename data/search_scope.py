"""
search_scope.py
펫퍼민트 약관 검색 범위(메타데이터 필터) — search_engine(dense·BM25), rag_context, 09 UI, 08 평가가 공통으로 쓰는 "진실의 원천" 모듈.

의미: "가입하지 않은 특약·등급만 빼고 나머지는 전부 남긴다".
예전에는 질문에 '고급형'·'Ⅱ'가 있으면 coverage_type == / type == 를 컬렉션 전체에 걸어, 등급·유형이 없는(null) 청크
— 보통약관·일반조항·별표·안내·법규·의료비 제2조 이후 — 가 전부 빠졌다("고급형인데 해지하면 환급금?"에 보통약관 제35조가 안 나옴).
질문에 등급을 쓸 때만 켜져서 드러나지 않았고, 09 UI가 가입 정보로 필터를 항상 채우면 모든 질문에서 터진다(2026-10-13).

species는 '종 또는 코퍼스' 키다(강아지/고양이/인사규정). 인사규정은 등급·특약이 없어 unrestricted만 쓴다 —
필드 이름은 09 구현 때 corpus로 바꿀 예정(KNOWN_ISSUES).
Milvus 식과 BM25 술어를 이 한 객체에서 만든다 — 둘을 손으로 따로 쓰면 dense와 BM25 후보가 서로 다른 범위가 된다.
null 주의: 보통약관은 section_name이 null이고, Milvus에서 null은 `not in`을 통과하지 못한다 → 반드시 `IS NULL or not in`.
"""

import re
from dataclasses import dataclass, field

GRADES = ("고급형", "기본형", "실속형")

# 등급(①고급형 ②기본형 ③실속형)으로 나뉜 의료비 특약 → 유형. section_name이 유형을 정하므로 type 필드는 필터하지 않는다
MEDICAL_SECTIONS = {
    "강아지": {
        "펫퍼민트 반려견 통원의료비보장 특별약관": "Ⅰ",
        "펫퍼민트 반려견 입원의료비보장 특별약관": "Ⅰ",
        "펫퍼민트 반려견 통원의료비Ⅱ보장 특별약관": "Ⅱ",
        "펫퍼민트 반려견 입원의료비Ⅱ보장 특별약관": "Ⅱ",
        "펫퍼민트 반려견 통원의료비Ⅲ보장 특별약관": "Ⅲ",
        "펫퍼민트 반려견 입원의료비Ⅲ보장 특별약관": "Ⅲ",
    },
    "고양이": {
        "펫퍼민트 반려묘 통원의료비보장 특별약관": "Ⅰ",
        "펫퍼민트 반려묘 입원의료비보장 특별약관": "Ⅰ",
        "펫퍼민트 반려묘 통원의료비Ⅱ보장 특별약관": "Ⅱ",
        "펫퍼민트 반려묘 입원의료비Ⅱ보장 특별약관": "Ⅱ",
        "펫퍼민트 반려묘 통원의료비Ⅲ보장 특별약관": "Ⅲ",
        "펫퍼민트 반려묘 입원의료비Ⅲ보장 특별약관": "Ⅲ",
    },
    "인사규정": {},      # 등급으로 나뉜 섹션이 없다
}

# 가입해야 적용되는 비의료비 특약 → 그 특약에만 딸린 일반조항(미가입이면 함께 뺀다).
# 보통약관·비용손해 일반조항·기타_제도성·자동갱신·별표·별첨·안내·법규는 늘 포함한다. 고양이 약관엔 배상책임이 없다
OPTIONAL_SECTIONS = {
    "강아지": {
        "민사소송법률비용Ⅱ보장 특별약관": (),
        "갱신형 펫퍼민트 반려견 배상책임보장 특별약관": ("배상책임 관련 특별약관 일반조항",),
        "반려동물 특정 질병 보장제한부 인수 특별약관": (),
    },
    "고양이": {
        "민사소송법률비용Ⅱ보장 특별약관": (),
        "반려동물 특정 질병 보장제한부 인수 특별약관": (),
    },
    "인사규정": {},
}


def mentioned_grade(query: str) -> str | None:
    """질문에 적힌 등급(예전 SearchEngine._extract_coverage_type_filter 규칙 그대로)"""
    for g in ("기본형", "고급형", "실속형"):
        if g in query:
            return g
    return None


def mentioned_type(query: str) -> str | None:
    """질문에 적힌 유형 — Ⅰ/Ⅱ/Ⅲ 또는 'N단계'(예전 SearchEngine._extract_type_filter 규칙 그대로)"""
    if "Ⅲ" in query or "3단계" in query:
        return "Ⅲ"
    if "Ⅱ" in query or "2단계" in query:
        return "Ⅱ"
    if "Ⅰ" in query or "1단계" in query:
        return "Ⅰ"
    return None


# 검색 문장에서 지울 등급·유형 표현(+ 바로 붙은 조사). 유형 숫자(Ⅰ/Ⅱ/Ⅲ)는 앞이 낱말에 붙어 있으면 지우지 않는다
# — '민사소송법률비용Ⅱ', '통원의료비Ⅱ'처럼 특약명의 일부다(특약명은 청크 머리말과 맞아 검색에 도움이 된다).
_PARTICLE = r"(?:인데|이면|으로|에서|은|는|이|가|도|의|로|에|만)?"
_GRADE_TERM = re.compile(r"(?:고급형|기본형|실속형)" + _PARTICLE)
_TYPE_TERM = re.compile(r"(?<![가-힣A-Za-z0-9])(?:(?:Ⅰ|Ⅱ|Ⅲ)\s*유형|유형\s*(?:Ⅰ|Ⅱ|Ⅲ)|[123]단계|Ⅰ|Ⅱ|Ⅲ)" + _PARTICLE)


def strip_scope_terms(query: str) -> str:
    """등급·유형 표현을 뺀 검색 문장. 청크 머리말에 등급이 붙어 있어(build_embedding_text) 질문 속 등급 단어가
    dense·BM25·리랭커 모두에서 그 등급의 의료비 제1조 행을 끌어올렸다 — "실속형은 몇 살까지 가입되나요?"가
    일반조항 제2조 대신 실속형 한도표 5개를 가져옴. 2026-10-13 회귀 세트: hit@5 75→78, MRR 0.677→0.707,
    한도 대조군 5/5 유지("고급형 수술 한도?" → "수술 한도?"여도 등급은 필터가 보장). 다 지워지면 원문을 쓴다."""
    out = _TYPE_TERM.sub(" ", _GRADE_TERM.sub(" ", query))
    out = re.sub(r"\s+", " ", out).strip()
    return out or query


def _lit(s: str) -> str:
    assert '"' not in s and "\\" not in s, f"Milvus 문자열 리터럴에 쓸 수 없는 문자: {s}"
    return f'"{s}"'


@dataclass(frozen=True)
class Subscription:
    section_name: str
    coverage_type: str | None = None   # None = 그 특약의 등급 무관(모든 등급)


@dataclass(frozen=True)
class SearchScope:
    species: str
    medical: tuple[Subscription, ...] | None = None   # None = 의료비 제한 없음 / () = 의료비 전부 제외
    excluded: frozenset[str] = field(default_factory=frozenset)   # 빼는 section_name(미가입 선택 특약 등)

    def __post_init__(self):
        if self.species not in MEDICAL_SECTIONS:
            raise ValueError(f"알 수 없는 종: {self.species}")
        for s in self.medical or ():
            if s.section_name not in MEDICAL_SECTIONS[self.species]:
                raise ValueError(f"{self.species} 의료비 특약이 아님: {s.section_name}")
            if s.coverage_type is not None and s.coverage_type not in GRADES:
                raise ValueError(f"알 수 없는 등급: {s.coverage_type}")

    # ----- 생성 -----
    @classmethod
    def unrestricted(cls, species: str) -> "SearchScope":
        """필터 없음(전 등급·유형이 후보) — 등급·특약이 없는 코퍼스(인사규정), 고객 없는 질문(07 방해 발췌·04 재현용 from_query)"""
        return cls(species)

    @classmethod
    def for_policies(cls, species: str, policies) -> "SearchScope":
        """09 고객 데이터의 가입 특약 목록(dict 또는 Subscription). 가입한 의료비 특약만 남기고(그 등급만),
        미가입 선택 특약과 그것에 딸린 일반조항은 뺀다. 그 밖의 이름(자동갱신·제도성 등)은 늘 포함이라 무시한다."""
        if not MEDICAL_SECTIONS[species]:
            raise ValueError(f"{species}: 가입 정보로 거를 섹션이 없는 코퍼스 — SearchScope.unrestricted를 쓸 것")
        subs = [p if isinstance(p, Subscription) else Subscription(p["section_name"], p.get("coverage_type"))
                for p in policies]
        names = {s.section_name for s in subs}
        medical = tuple(s for s in subs if s.section_name in MEDICAL_SECTIONS[species])
        excluded = set()
        for name, attached in OPTIONAL_SECTIONS[species].items():
            if name not in names:
                excluded.add(name)
                excluded.update(attached)
        return cls(species, medical, frozenset(excluded))

    @classmethod
    def from_query(cls, query: str, species: str) -> "SearchScope":
        """질문에 적힌 등급·유형으로 의료비 특약만 좁힌다(04 노트북·가정 질문용). 다른 섹션은 그대로 둔다."""
        grade, type_ = mentioned_grade(query), mentioned_type(query)
        if (grade is None and type_ is None) or not MEDICAL_SECTIONS[species]:   # 등급 없는 코퍼스(인사규정)는 늘 무제한
            return cls.unrestricted(species)
        return cls(species, tuple(Subscription(name, grade) for name, t in MEDICAL_SECTIONS[species].items()
                                  if type_ is None or t == type_))

    # ----- 적용 -----
    def _medical_map(self) -> dict[str, Subscription]:
        return {s.section_name: s for s in self.medical or ()}

    def retrieval_query(self, query: str) -> str:
        """검색(dense·BM25·리랭커)에 쓸 문장. 등급·유형을 필터가 맡을 때(medical이 있을 때)만 그 표현을 지운다 —
        필터가 없으면(unrestricted·고객 없는 질문) 질문 속 등급이 유일한 단서라 그대로 둔다."""
        return query if self.medical is None else strip_scope_terms(query)

    def grade_for(self, section_name: str | None) -> str | None:
        """그 섹션에 가입한 등급(참조 조문을 자기 등급 한 벌만 붙이는 힌트). 모르면 None"""
        s = self._medical_map().get(section_name)
        return s.coverage_type if s else None

    def allows(self, c: dict) -> bool:
        """청크 하나가 범위 안인가 — BM25 후보 필터. milvus_expr()과 같은 의미여야 한다"""
        name = c.get("section_name")
        if name in self.excluded:
            return False
        if self.medical is None or name not in MEDICAL_SECTIONS[self.species]:
            return True
        sub = self._medical_map().get(name)
        if sub is None:
            return False
        return sub.coverage_type is None or c.get("coverage_type") in (None, sub.coverage_type)

    def milvus_expr(self) -> str | None:
        """dense 검색 필터. 제한이 없으면 None"""
        if self.medical is None and not self.excluded:
            return None
        out = set(self.excluded)
        if self.medical is not None:
            out |= set(MEDICAL_SECTIONS[self.species])
        names = ", ".join(_lit(n) for n in sorted(out))
        parts = [f"(section_name IS NULL or section_name not in [{names}])"]   # null(보통약관)을 살리는 부분
        for s in self.medical or ():
            if s.section_name in self.excluded:
                continue
            cond = f"section_name == {_lit(s.section_name)}"
            if s.coverage_type is not None:
                cond += f" and (coverage_type IS NULL or coverage_type == {_lit(s.coverage_type)})"
            parts.append(f"({cond})")
        return " or ".join(parts)

    def describe(self) -> dict:
        """로그·회귀 결과에 남길 직렬화 형태"""
        return {"species": self.species,
                "medical": None if self.medical is None else [[s.section_name, s.coverage_type] for s in self.medical],
                "excluded": sorted(self.excluded)}

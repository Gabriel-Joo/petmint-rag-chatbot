"""
named_cover.py
병명이 있는 보장 질문(2026-10-29, PETMINT_NAMED_COVER) — "감기도 보장되나요?"를 모델이 3/3 거절했다(운영). 제1조·제2조가 발췌에 와도
면책 목록(제2조)과 질문의 병명을 대조하지 못한다. 코드가 그 반려동물 가입 의료비 특약의 제2조 목록과 대조해 답한다.

- 낱말은 닫힌 목록 둘이다. 목록에 없는 말이면 발동하지 않는다(모델) — 아무 말이나 "면책 목록에 없다"로 답하지 않는다
  EXCLUDED: 제2조 면책 항목(약관 글 그대로 — tests/test_named_cover가 특약 원문에 있는지, 어느 특약 유형에 있는지 확인한다)
  COMMON: 약관에 없는 흔한 병명·증상(감기·장염…) — 사람이 보면 "면책 목록에 없어 원칙 보상"인 것. 원인이 면책 감염병·기생충일 수 있는
          말에는 그 단서를 붙인다(감기 → 파라인플루엔자·인플루엔자는 1년 이내 접종 기록). eval220에서 뽑지 않았다
- 발동(좁게): 지금 질문에 목록 낱말이 정확히 한 항목 · 보장을 묻는 말(또는 병명 되묻기 바로 뒤의 짧은 답 "감기예요") · 금액·숫자·한도·
  횟수 없음 · 면책 사실(태풍·해외·가입 전) 없음 · 상해 낱말 없음 · 그 반려동물 부담보에 안 걸림(exclusion이 먼저 답한다)
- 치과(⑲)는 proviso(구강질환 단서)가, 접종 시기를 말한 감염병은 proviso가 먼저 답한다 — 여기서는 치과 낱말을 두지 않고, 접종 말이 있으면 넘긴다
- 특약 유형마다 목록이 다르다: Ⅱ·Ⅲ 특약에는 서혜부허니아(⑩)·치과(⑲)·아포퀠(⑳)이 없다
"""

import re
from dataclasses import dataclass

from app.schemas import Pet
from app.services import payout
from app.services.lexicon import (AMOUNT_UPSELL, ASKED_MARK, COVERAGE_Q_STRICT, EXEMPT_FACT, INJURY)


@dataclass(frozen=True)
class Term:
    key: str
    pattern: str
    name: str                       # 답에 쓰는 이름
    clause: str = ""                # EXCLUDED: 약관 조항 표기
    quote: str = ""                 # EXCLUDED: 약관 글(원문 대조 — 공백 무시)
    species: tuple = ("강아지", "고양이")
    type1_only: bool = False        # Ⅱ·Ⅲ 특약에는 없는 항목
    note: str = ""                  # 덧붙일 단서 키(NOTES)
    procedure: bool = False         # 처치·수술 — 제2조 ③(같이 한 다른 진료는 보상, 이 처치·마취만 빠진다)


_VAC = "파보 바이러스 감염, 디스템퍼 바이러스 감염, 파라 인플루엔자 감염, 전염성 간염, 아데노 바이러스 2형 감염, 광견병, 코로나 바이러스 감염, 렙토스피라 감염, 필라리아(심장사상충) 감염, 인플루엔자 감염"
EXCLUDED = [
    Term("파보", r"파보", "파보 바이러스 감염", "제2조 제2항 ②", "파보 바이러스 감염", note="vaccine"),
    Term("디스템퍼", r"디스템퍼", "디스템퍼 바이러스 감염", "제2조 제2항 ②", "디스템퍼 바이러스 감염", note="vaccine"),
    Term("파라인플루엔자", r"파라\s*인플루엔자", "파라 인플루엔자 감염", "제2조 제2항 ②", "파라 인플루엔자 감염", note="vaccine"),
    Term("전염성간염", r"전염성\s*간염", "전염성 간염", "제2조 제2항 ②", "전염성 간염", note="vaccine"),
    Term("아데노", r"아데노", "아데노 바이러스 2형 감염", "제2조 제2항 ②", "아데노 바이러스 2 형 감염", note="vaccine"),
    Term("광견병", r"광견병", "광견병", "제2조 제2항 ②", "광견병", note="vaccine"),
    Term("코로나", r"코로나", "코로나 바이러스 감염", "제2조 제2항 ②", "코로나 바이러스 감염", note="vaccine"),
    Term("렙토", r"렙토스피라", "렙토스피라 감염", "제2조 제2항 ②", "렙토스피라 감염", note="vaccine"),
    Term("심장사상충", r"필라리아|심장\s*사상충", "필라리아(심장사상충) 감염", "제2조 제2항 ②", "필라리아(심장사상충) 감염", note="vaccine"),
    Term("인플루엔자", r"(?<!파라)(?<!파라 )인플루엔자|독감", "인플루엔자 감염", "제2조 제2항 ②", "인플루엔자 감염", note="vaccine"),
    Term("범백", r"범백", "고양이범백혈구감소증", "제2조 제2항 ②", "고양이범백혈구감소증", ("고양이",), note="vaccine"),
    Term("칼리시", r"칼리시", "고양이칼리시바이러스 감염증", "제2조 제2항 ②", "고양이칼리시바이러스 감염증", ("고양이",), note="vaccine"),
    Term("비기관지염", r"비기관지염|허피스|헤르페스", "고양이바이러스성비기관지염", "제2조 제2항 ②", "고양이바이러스성비기관지염", ("고양이",), note="vaccine"),
    Term("백혈병", r"백혈병", "고양이백혈병 바이러스감염증", "제2조 제2항 ②", "고양이백혈병 바이러스감염증", ("고양이",), note="vaccine"),
    Term("클라미디아", r"클라미디아", "고양이클라미디아감염증", "제2조 제2항 ②", "고양이클라미디아감염증", ("고양이",), note="vaccine"),
    Term("선천", r"선천|유전", "선천적·유전적 질병", "제2조 제2항 ①", "반려동물의 선천적, 유전적 질병에 의한 손해", note="congenital"),
    Term("출산", r"임신|출산|제왕\s*절개|인공\s*유산|분만", "임신·출산 관련 비용", "제2조 제2항 ⑤", "임신·출산, 제왕절개, 인공유산", procedure=True),
    Term("발정", r"발정", "발정 관련 비용", "제2조 제2항 ⑤", "발정과 관련된 비용", ("고양이",)),
    Term("중성화", r"중성화|불임\s*수술|피임", "중성화·불임·피임 수술", "제2조 제2항 ⑥", "중성화, 불임 및 피임을 목적으로 한 수술 및 처치", procedure=True),
    Term("미용", r"미용(?!\s*성형)", "미용 비용", "제2조 제2항 ⑦", "미용으로 인한 비용"),
    Term("성형", r"귀\s*성형|꼬리\s*성형|성대\s*(?:제거|수술)|미용\s*성형", "귀·꼬리 성형, 성대제거, 미용성형", "제2조 제2항 ⑧",
         "귀 성형, 꼬리 성형, 성대제거 및 미용성형을 위한 수술 및 처치", procedure=True),
    Term("건강수술", r"손톱\s*(?:절제|제거)|며느리\s*발톱|잔존\s*유치|유치\s*(?:발치|제거)|잠복\s*고환|배꼽\s*탈장|제대\s*허니아|항문낭\s*(?:제거|수술)",
         "손톱절제·잔존유치·잠복고환·제대허니아·항문낭 제거 등", "제2조 제2항 ⑨",
         "손톱절제(며느리발톱 제거 포함), 잔존유치, 잠복고환, 제대허니아(배꼽부위탈장), 항문낭 제거 등 건강동물에 실시하는 외과수술", procedure=True),
    Term("서혜부", r"서혜부", "서혜부허니아(서혜부탈장)", "제2조 제2항 ⑩", "서혜부허니아(서혜부탈장)", type1_only=True),
    Term("눈물", r"첩모\s*난생|속눈썹|눈물샘|눈물\s*자국", "첩모난생(속눈썹 질환)·눈물샘으로 인한 비용", "제2조 제2항 ⑩",
         "첩모난생(속눈썹 질환), 눈물샘으로 인한 비용"),
    Term("기생충", r"벼룩|진드기|모낭충|기생충", "예방 가능한 기생충(벼룩·진드기·모낭충 등)으로 생긴 질병", "제2조 제2항 ⑬",
         "예방 가능한 기생충(벼룩, 진드기, 모낭충 등)의 제거비용 및 기생충으로 발생한 질병의 치료비"),
    Term("아포퀠", r"아포퀠|apoquel", "아포퀠 등 JAK inhibitor 약물", "제2조 제2항 ⑳", "아포퀠(Apoquel) 등의 JAK inhibitor", type1_only=True),
]

# 약관에 없는 흔한 병명·증상 — 목록에 없어 원칙 보상(사람 판단). note: 원인이 면책 항목일 수 있는 단서
COMMON = [
    Term("감기", r"감기", "감기", note="resp"),
    Term("기침", r"기침", "기침", note="resp"),
    Term("콧물", r"콧물|재채기", "콧물·재채기", note="resp"),
    Term("켄넬코프", r"켄넬\s*코프", "켄넬코프", note="resp"),
    Term("폐렴", r"폐렴", "폐렴", note="resp"),
    Term("기관지염", r"(?<!비)기관지염", "기관지염", ("강아지",), note="resp"),
    Term("장염", r"장염", "장염", note="gut"),
    Term("설사", r"설사", "설사", note="gut"),
    Term("구토", r"구토|토해|토를", "구토"),
    Term("위염", r"위염", "위염"),
    Term("췌장염", r"췌장염", "췌장염"),
    Term("방광염", r"방광염", "방광염"),
    Term("결석", r"결석", "결석"),
    Term("신부전", r"신부전", "신부전"),
    Term("당뇨", r"당뇨", "당뇨"),
    Term("피부염", r"피부염|피부병", "피부염", note="skin"),
    Term("외이염", r"외이염|중이염|귓병", "외이염·중이염"),
    Term("결막염", r"결막염", "결막염"),
    Term("각막", r"각막\s*(?:염|궤양)", "각막염·각막궤양"),
    Term("백내장", r"백내장", "백내장"),
    Term("녹내장", r"녹내장", "녹내장"),
    Term("디스크", r"디스크", "디스크"),
    Term("종양", r"종양|림프종", "종양"),
]

_RESP_DOG = "파라 인플루엔자·인플루엔자·디스템퍼 등"
_RESP_CAT = "고양이바이러스성비기관지염·칼리시바이러스·인플루엔자 등"
_GUT_DOG = "파보·코로나 바이러스 감염"
_GUT_CAT = "고양이범백혈구감소증·코로나 바이러스 감염"

_COVER_SHORT = re.compile(r"(?:돼요|되나요|될까요|되죠|되는지|되는\s*건가요|되요|돼|되냐|가능한가요|가능해요)\s*[?？.!~]*\s*$")
_NOT_HERE = re.compile(r"몇|한도|횟수|까지|언제|서류|어떻게|방법|기간|예방\s*접종|접종|백신")    # 한도·기간·절차·접종 시기는 다른 규칙·모델로
REPLY_MAX = 20                                       # 병명 되묻기 뒤 짧은 답("감기예요", "장염이요")


def terms_in(question: str, species: str) -> list[Term]:
    return [t for t in EXCLUDED + COMMON if species in t.species and re.search(t.pattern, question, re.I)]


def _types(pet: Pet, riders) -> set[str]:
    return {"II" if re.search(r"Ⅱ|Ⅲ", p.section_name) else "I" for p in riders}


def fires(question: str, prior_answer: str | None, pet: Pet | None) -> Term | None:
    """발동 조건 — 맞으면 그 항목, 아니면 None. 질문 글(question)은 지금 턴 것만 본다(앞 질문의 병명으로 걸리지 않는다)"""
    if pet is None:
        return None
    hits = terms_in(question, pet.species)
    if len({t.key for t in hits}) != 1:
        return None
    if AMOUNT_UPSELL.search(question) or EXEMPT_FACT.search(question) or INJURY.search(question) or _NOT_HERE.search(question):
        return None
    if payout.matched_exclusions(question, pet):
        return None
    reply = bool(prior_answer and ASKED_MARK in prior_answer) and len(re.sub(r"\s", "", question)) <= REPLY_MAX
    if not (reply or COVERAGE_Q_STRICT.search(question) or _COVER_SHORT.search(question)):
        return None
    return hits[0]


def _josa(word: str, pair: str) -> str:
    last = word[-1]
    has = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
    return pair[0] if has else pair[1]


def answer(question: str, card: str, prior_answer: str | None, pet: Pet | None, notes) -> str | None:
    """notes: customer_facts.notes(대기기간·슬관절·비뇨기 줄). card: 앞 질문까지 이은 글 — 입원/통원은 여기서 본다"""
    from app.services.customer_facts import _riders, short_name
    t = fires(question, prior_answer, pet)
    if t is None:
        return None
    medical, kind, riders = _riders(card, pet)
    if not riders:
        return None
    types = _types(pet, riders)
    who = f"{pet.name}{_josa(pet.name, '은는')}"
    names = ", ".join(short_name(p) for p in riders)
    excluded = t in EXCLUDED and (not t.type1_only or "I" in types)
    if t in EXCLUDED and not excluded:
        return None                                  # Ⅱ·Ⅲ 특약에는 없는 항목 — 유형이 섞이면 어렵다, 모델로
    if excluded:
        if t.note == "vaccine":
            lines = [f"{t.name}{_josa(t.name, '은는')} 의료비 특약 {t.clause}의 면책 감염병이라 원칙적으로 보상하지 않습니다.",
                     "다만 질병 발생일로부터 과거 1년 이내의 예방접종 기록이 있으면 보상합니다 — 청구할 때 동물병원의 접종 기록으로 확인합니다."]
        elif t.note == "congenital":
            lines = [f"선천적·유전적 질병은 의료비 특약 {t.clause}에 따라 보상하지 않습니다(보험계약 이전부터 객관적으로 인지할 수 있는 증상 포함).",
                     "다만 보험기간 중 최초로 발견된 경우에는 해당 보험기간에 한하여 보상합니다."]
        else:
            lines = [f"{t.name}{_josa(t.name, '은는')} 의료비 특약 {t.clause}(\"{t.quote}\")에 해당해 보상하지 않습니다."]
            if t.procedure:
                lines.append("같은 날 다른 진료를 함께 받았다면 그 진료는 보상 대상이고, 이 처치(마취 비용 포함)만 빠집니다(제2조 제3항).")
        return "\n".join(lines)
    waits = notes(f"{card} {question}", pet)          # 대기기간(질병 30일)·반려묘 비뇨기 90일 — 결론을 바꾸는 사실이라 원칙 바로 뒤에
    head = f"{t.name}{_josa(t.name, '은는')} 의료비 특약 제2조(보험금을 지급하지 않는 사유)의 면책 목록에 없어"
    tail = f"{who} {names} 특약으로 원칙대로 보상됩니다(1일 지급 한도·자기부담금·보상비율 적용, 제1조)."
    if any("이내" in w and "보상하지 않습니다" in w for w in waits):
        lines = [f"{head}, 아래 대기기간이 지난 뒤 발생했다면 {tail} 대기기간 안에 발생했다면 보상하지 않습니다."]
    else:
        lines = [f"{head}, {tail}"]
    lines += waits
    dog = pet.species == "강아지"
    if t.note == "resp":
        lines.append(f"- 다만 {_RESP_DOG if dog else _RESP_CAT} 면책 감염병(제2조 제2항 ②)으로 진단되면, 질병 발생일로부터 과거 1년 이내의 "
                     f"예방접종 기록이 있어야 보상합니다.")
    elif t.note == "gut":
        lines.append(f"- 다만 {_GUT_DOG if dog else _GUT_CAT}(제2조 제2항 ②)으로 진단되면, 질병 발생일로부터 과거 1년 이내의 예방접종 기록이 "
                     f"있어야 보상합니다.")
    elif t.note == "skin":
        lines.append("- 다만 벼룩·진드기·모낭충 등 예방 가능한 기생충으로 생긴 피부병은 보상하지 않습니다(제2조 제2항 ⑬)."
                     + (" 아포퀠 등 JAK inhibitor 약물 비용도 빠집니다(제2조 제2항 ⑳)." if "I" in types else ""))
    lines.append("- 가입 전에 이미 발병한 질병(제2조 제1항 ⑥)과 선천적·유전적 질병(제2조 제2항 ①)은 보상하지 않습니다.")
    lines.append("- 청구할 때는 진단서의 상병명으로 확인합니다 — 상병명을 알 수 없는 질병은 보상하지 않습니다(제2조 제2항 ③).")
    return "\n".join(lines)

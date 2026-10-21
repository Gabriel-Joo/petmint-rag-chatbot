"""
customer_facts.py
고객 고유 사실을 코드가 답에 넣는다(2026-10-21, rebuild5 준비 4d단계). 모델은 고객 정보를 받지 않는다(09번 5절 — 학습 형식이
2턴이라 넣으면 형식이 바뀐다). 그래서 기준선에서 이 변수들은 모두 실패했다: 미가입 0/21, 연간 잔여 0/9, 나이 0/9, 대기기간 6/15.

- not_enrolled: 가입하지 않은 특약을 물었다 — 모델 대신 코드가 "가입하지 않았다"고 답한다(그 특약 조항은 검색 범위에서 빠져 있다)
- annual_answer: 올해(보험연도) 받은 보험금·남은 연간 한도 — 청구 이력으로 코드가 답한다
- notes: 답 끝에 붙일 고객 사실 — 가입 30일 이내 질병, 반려견 1년 이내 슬관절·고관절 / 반려묘 90일 이내 비뇨기계질환·전염성복막염,
  반려동물 나이
"""

import re
from datetime import date, timedelta

from data.rag_context import infer_type_from_section_name
from data.search_scope import MEDICAL_SECTIONS

from app.schemas import Pet
from app.services import daycalc, payout

LIAB = "갱신형 펫퍼민트 반려견 배상책임보장 특별약관"
LEGAL = "민사소송법률비용Ⅱ보장 특별약관"
_LIAB_WORDS = re.compile(r"물었|물어|물림|물렸|물려|배상|피해자|다치게")
_LEGAL_WORDS = re.compile(r"소송|변호사|법률\s*비용|송달료|인지액")
_MEDICAL_INTENT = re.compile(r"치료|병원|진료|수술|보험금|한도|얼마|보장|보상|나와|나오|청구|입원비|통원비")
_DISEASE = re.compile(r"질병|병(?!원)|감기|장염|염증|[가-힣]염\b|아프|아파|증상|걸렸|걸리|설사|구토|진단|감염|질환")
_KNEE = re.compile(r"슬개골|슬관절|고관절|무릎|탈구")
_URINARY = re.compile(r"비뇨|방광|요로|신장|결석|소변|오줌|복막염|FIP", re.I)
_AGE = re.compile(r"나이|몇\s*살|\d+\s*살|살이|살인데|살\s*넘|재가입|가입\s*(?:되|돼|할\s*수|가능|이\s*되)")


def _josa(word: str, pair: str) -> str:
    return pair[0] if payout._has_batchim(word) else pair[1]


def short_name(p) -> str:
    """'펫퍼민트 반려견 통원의료비Ⅱ보장 특별약관' 고급형 → '통원의료비Ⅱ 고급형'"""
    m = re.search(r"(통원|입원)의료비(Ⅱ|Ⅲ)?", p.section_name)
    base = m.group(0) if m else p.section_name.replace(" 특별약관", "").replace("갱신형 펫퍼민트 반려견 ", "")
    return f"{base} {p.coverage_type}" if p.coverage_type else base


def not_enrolled(question: str, pet: Pet | None) -> str | None:
    """가입하지 않은 특약을 물었으면 그 안내(코드 답). 아니면 None"""
    if pet is None:
        return None
    names = {p.section_name for p in pet.policies}
    missing = None
    if _LEGAL_WORDS.search(question) and LEGAL not in names:
        missing = "민사소송법률비용Ⅱ보장"
    elif pet.species == "강아지" and _LIAB_WORDS.search(question) and LIAB not in names:
        missing = "배상책임보장"
    else:
        said = [w for w in ("통원", "입원") if w in question]
        medical = [p for p in pet.policies if p.section_name in MEDICAL_SECTIONS[pet.species] and p.coverage_type]
        if len(said) == 1 and _MEDICAL_INTENT.search(question) and medical and not any(said[0] in p.section_name for p in medical):
            missing = f"{said[0]}의료비보장"
    if missing is None:
        return None
    have = ", ".join(short_name(p) for p in pet.policies if p.coverage_type or "배상" in p.section_name or "법률" in p.section_name)
    return (f"{pet.name}{_josa(pet.name, '은는')} {missing} 특약에 가입하지 않아 이 보험으로는 보장되지 않습니다. "
            f"가입한 특약: {have or '의료비 특약 없음'}.")


def annual_answer(question: str, pet: Pet | None, on: date | None = None) -> str | None:
    """올해 받은 보험금·남은 연간 한도를 물으면 청구 이력으로 답한다(코드 답). 아니면 None"""
    if pet is None or not payout.ANNUAL_ASK.search(question):
        return None
    on = on or payout.today()
    medical = [p for p in pet.policies if p.section_name in MEDICAL_SECTIONS[pet.species] and p.coverage_type]
    said = [w for w in ("통원", "입원") if w in question]
    if len(said) == 1:
        medical = [p for p in medical if said[0] in p.section_name] or medical
    if not medical:
        return None
    lines = []
    for p in medical:
        t = infer_type_from_section_name(p.section_name)
        lim = daycalc.DayLimits.of(p.coverage_type, t, p.copay or 0)
        a = payout.annual_usage(pet, p, lim.annual_total, on)
        lines.append(f"{short_name(p)}: 올해(보험연도 {a.year_start}부터) 받은 보험금 {payout._won(a.used)}"
                     f"{f'(청구 {a.claims}건)' if a.claims else ''}, 연간 총 한도 {payout._won(a.total)} 중 "
                     f"남은 한도 **{payout._won(a.remaining)}**입니다.")
    return "\n".join(lines) + "\n청구 이력은 지급이 끝난 건 기준입니다."


def notes(question: str, pet: Pet | None, on: date | None = None) -> list[str]:
    """답 끝에 붙일 고객 사실 — 가입일 대기기간(질병 30일, 슬관절·고관절 1년)과 나이"""
    if pet is None:
        return []
    on = on or payout.today()
    out = []
    medical = [p for p in pet.policies if p.section_name in MEDICAL_SECTIONS[pet.species] and p.coverage_type]
    starts = sorted({p.contract_date for p in medical})
    if starts:
        start = starts[-1]                        # 가장 늦은 가입일 기준(특약마다 같으면 하나)
        if _DISEASE.search(question) and (on - start).days < 30:
            end = start + timedelta(days=29)
            out.append(f"참고: {pet.name}{_josa(pet.name, '은는')} {start.isoformat()} 가입이라 보장개시일부터 30일 이내"
                       f"({end.month}월 {end.day}일까지)에 발생한 질병은 보상하지 않습니다(의료비 특약 제1조 ③). 상해는 해당하지 않습니다.")
        # 종마다 다르다 — 반려견 제1조 ④ 1년 이내 슬관절·고관절 / 반려묘 제1조 ④ 90일 이내 비뇨기계질환·전염성복막염
        # (반려묘 약관에는 슬관절 규칙이 없다 — 2026-10-21 4d 측정에서 고양이에게 반려견 규칙을 붙이던 것을 고침)
        if pet.species == "강아지" and _KNEE.search(question) and (on - start).days < 365:
            end = start + timedelta(days=364)
            out.append(f"참고: 보장개시일부터 1년 이내({end.isoformat()}까지)에 발생한 슬관절탈구·고관절탈구·슬관절형성부전·"
                       f"고관절형성부전 등은 보상하지 않습니다(의료비 특약 제1조 ④).")
        if pet.species == "고양이" and _URINARY.search(question) and (on - start).days < 90:
            end = start + timedelta(days=89)
            out.append(f"참고: 보장개시일부터 90일 이내({end.isoformat()}까지)에 발생한 비뇨기계질환·전염성복막염 등은 "
                       f"보상하지 않습니다(의료비 특약 제1조 ④).")
    if _AGE.search(question) and pet.age is not None:
        out.append(f"참고: {pet.name}{_josa(pet.name, '은는')} 원장 기준 {pet.age}세입니다. 새로 가입할 수 있는 나이는 만 8세(실속형은 "
                   f"만 10세)까지이고, 재가입은 회사가 정한 재가입 나이 범위 안이어야 합니다(구체 나이는 약관에 없음).")
    return out

"""
dayparse.py
자유 입력에서 치료비 총액·일수(횟수)·날짜별 금액·수술한 날 금액을 읽는다(규칙, 모델 없음).

- 금액: "70만원", "12만 5,000원", "300,000원"에 더해 원 없이 "30만"(만·천 단위가 있으면). 단위 없는 숫자는 1,000 이상이고
  뒤가 일·번·회·년… 이 아닐 때만. "30만 30만 10만"처럼 띄어 쓴 금액은 단위가 작아질 때만 한 금액으로 잇는다("12만 5,000").
  자기부담금·한도·보험료 바로 뒤 금액은 치료비가 아니라 건너뛴다(payout.treatment_cost와 같은 규칙).
- 일수: "2박 3일" → 3(입원한 날을 센다) / "3일" / "사흘"·"열흘"·"보름" / "일주일"·"2주" / 횟수 "3번"·"세 번"·"2회".
  "1일당"·"1일차"·"두 번째"·"10월 3일"은 일수가 아니다. "같은 날 두 번"은 하루(약관 단위가 1일당이다).
- 금액마다 앞뒤(쉼표·줄바꿈까지)에 '수술'이 있으면 수술한 날, 'MRI·CT·내시경'이 있으면 그날 MRI, '총·합계·전체·모두'가
  앞에 있으면 총액이다.
"""

import re
from dataclasses import dataclass, field

_UNIT = {"억": 10 ** 8, "천만": 10 ** 7, "백만": 10 ** 6, "만": 10 ** 4, "천": 10 ** 3, "백": 100}
_UNIT_RE = "|".join(sorted(_UNIT, key=len, reverse=True))
_PIECE = re.compile(rf"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*({_UNIT_RE})?")
_WON_AFTER = re.compile(r"\s*원")
# 단위 없는 숫자 뒤에 오면 금액이 아니다(일수·횟수·날짜·나이…)
_STOP_AFTER = re.compile(r"\s*(?:박|일|번|회|차|째|살|세|시|분|개|kg|키로|%|퍼센트|년|월|주|달|마리|층|호|조|항|등급|형)")
_NOT_COST = re.compile(r"(자기\s*부담금?|한도|보험료|공제)\s*(은|는|이|가|을|를|도|로)?\s*$")
_SEP = re.compile(r"[,，、/;\n]|\s그리고\s|\s이고\s")
_SURGERY = re.compile(r"수술")
_NO_SURGERY = re.compile(r"수술\s*(을|은)?\s*(안|하지\s*않|없이|없는|없었)|비수술")
_MRI = re.compile(r"MRI|CT|내시경|엠알아이", re.I)
_TOTAL = re.compile(r"총|합계|합쳐|전체|모두|통틀어|다\s*해서")

_KDAYS = {"하루": 1, "이틀": 2, "사흘": 3, "나흘": 4, "닷새": 5, "엿새": 6, "이레": 7, "여드레": 8, "아흐레": 9, "열흘": 10,
          "보름": 15}
_KNUM = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}
_NIGHTS = re.compile(r"(\d+)\s*박\s*(\d+)\s*일")
_DAYS_NUM = re.compile(r"(?<![\d월])(?<!월\s)(\d+)\s*일(?!\s*(?:당|차|째|자|분|기준|한도|지급))")
_WEEKS = re.compile(r"(?:(\d+)|(일|한))\s*주(?:일)?(?:\s*(?:간|동안|입원|통원))?(?![가-힣]*(?:세요|시면|면))")
_DAYS_WORD = re.compile(rf"(?<![가-힣])({'|'.join(_KDAYS)})")
_VISITS_NUM = re.compile(r"(\d+)\s*(?:번|회)(?!\s*(?:째|차))")
_VISITS_WORD = re.compile(rf"(?<![가-힣])({'|'.join(sorted(_KNUM, key=len, reverse=True))})\s*(?:번|회)(?!\s*(?:째|차))")
_SAME_DAY = re.compile(r"같은\s*날|당일|하루에\s*(?:두|세|2|3)\s*(?:번|회)")
_UNKNOWN = re.compile(r"모르|몰라|모름|잘\s*몰|확인\s*(?:이\s*)?(?:안|못|어렵)|기억\s*(?:이\s*)?안|범위")


@dataclass(frozen=True)
class Amount:
    value: int
    start: int
    end: int
    surgery: bool = False
    mri: bool = False
    total: bool = False          # '총·합계' 뒤 — 총액


@dataclass
class Reading:
    amounts: list[Amount] = field(default_factory=list)
    days: int | None = None      # 일수·횟수
    unit: str | None = None      # "일" / "번" — 무엇으로 셌나
    same_day: bool = False       # "같은 날 두 번" — 하루로 셌다
    unknown: bool = False        # "잘 모르겠어요"
    surgery: bool = False        # 문장 어디든 수술(부정 아님)
    mri: bool = False


def _pieces(text: str) -> list[tuple[int, int, float, str | None]]:
    return [(m.start(), m.end(), float(m.group(1).replace(",", "")), m.group(2)) for m in _PIECE.finditer(text)]


def amounts(text: str) -> list[Amount]:
    """문장 속 금액(원)과 그 앞뒤 표시. 1,000원 미만은 버린다"""
    pieces = _pieces(text)
    groups: list[list[tuple]] = []
    for p in pieces:
        if groups:
            last = groups[-1][-1]
            gap = text[last[1]:p[0]]
            # "12만 5,000" — 큰 단위 뒤에 더 작은 단위(또는 단위 없음)가 공백만 두고 오면 한 금액
            if not gap.strip() and last[3] and _UNIT[last[3]] > _UNIT.get(p[3], 1) and _UNIT[last[3]] >= 10 ** 4:
                groups[-1].append(p)
                continue
        groups.append([p])
    seps = [0] + [m.end() for m in _SEP.finditer(text)]
    out: list[Amount] = []
    for g in groups:
        start, end = g[0][0], g[-1][1]
        won = _WON_AFTER.match(text, end)
        has_unit = any(u for *_, u in g)
        if won:
            end = won.end()
        elif not has_unit and _STOP_AFTER.match(text, end):
            continue
        elif not has_unit and _STOP_AFTER.match(text, g[-1][1]):
            continue
        value = int(sum(v * _UNIT.get(u, 1) for _, _, v, u in g))
        if value < 1000 or _NOT_COST.search(text[:start]):
            continue
        out.append(Amount(value, start, end))
    # 금액마다 앞뒤 구간 — 앞 금액(또는 구분자) 뒤부터 다음 금액(또는 구분자) 앞까지
    marked = []
    for i, a in enumerate(out):
        lo = max([s for s in seps if s <= a.start] + [out[i - 1].end if i else 0])
        nxt = [m.start() for m in _SEP.finditer(text, a.end)]
        hi = min(nxt[:1] + ([out[i + 1].start] if i + 1 < len(out) else []) + [len(text)])
        before, after = text[lo:a.start], text[a.end:hi]
        zone = before + " " + after
        surgery = bool(_SURGERY.search(zone)) and not _NO_SURGERY.search(zone)
        marked.append(Amount(a.value, a.start, a.end, surgery=surgery, mri=bool(_MRI.search(zone)),
                             total=bool(_TOTAL.search(before))))
    return marked


def day_count(text: str) -> tuple[int | None, str | None, bool]:
    """(일수·횟수, "일"/"번", 같은 날로 셌나). 못 읽으면 (None, None, False)"""
    same = bool(_SAME_DAY.search(text))
    m = _NIGHTS.search(text)
    if m:
        return int(m.group(2)), "일", False
    for pat, unit in ((_VISITS_NUM, "번"), (_VISITS_WORD, "번")):
        m = pat.search(text)
        if m:
            n = int(m.group(1)) if m.group(1).isdigit() else _KNUM[m.group(1)]
            return (1, "번", True) if same else (n, "번", False)
    m = _WEEKS.search(text)
    if m:
        return (int(m.group(1)) if m.group(1) else 1) * 7, "일", False
    m = _DAYS_NUM.search(text)
    if m:
        return int(m.group(1)), "일", False
    m = _DAYS_WORD.search(text)
    if m:
        return _KDAYS[m.group(1)], "일", False
    return None, None, False


def read(text: str) -> Reading:
    n, unit, same = day_count(text)
    return Reading(amounts=amounts(text), days=n, unit=unit, same_day=same, unknown=bool(_UNKNOWN.search(text)),
                   surgery=bool(_SURGERY.search(text)) and not _NO_SURGERY.search(text), mri=bool(_MRI.search(text)))


def is_reply(text: str) -> bool:
    """금액 되묻기·날짜별 되묻기에 답한 말인가 — 금액·일수·'모르겠어요' 중 하나가 있다"""
    r = read(text)
    return bool(r.amounts) or r.days is not None or r.unknown

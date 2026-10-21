"""
daycalc.py
의료비를 하루 단위로 계산한다 — 약관의 모든 단위가 하루다(통원·입원 Ⅰ·Ⅱ·Ⅲ 제1조 표: "1일당 자기부담금", "1일당 한도").
날마다 (그날 치료비 - 자기부담금) × 보상비율을 그날 한도(수술한 날·MRI 날·그 밖의 날)까지 내고, 그 합계에 연간 총 한도
(이미 받은 보험금을 뺀 남은 한도)가 걸린다. 숫자는 전부 정수(원)로 계산한다.

총액만 알고 날짜별 금액을 모르면 정확한 값은 없다 — bounds()가 날짜별로 나뉠 수 있는 모든 경우의 최소·최대를 낸다.
하루치 함수 f(x) = min(max((x - c) × r, 0), L)는 [0, c]에서 0, [c, s]에서 기울기 r, s 이상에서 L이다(s = c + L/r).
조각마다 목적식이 선형이고 제약은 날마다의 상·하한과 합계 하나뿐이라, 최적해는 꼭짓점 — 하루를 빼고는 모두 꺾이는 점
(하한 m · 자기부담금 c · 포화점 s)에 있다. 그 조합을 다 세면 최소·최대가 정확히 나온다(tests/test_daycalc.py가 전수 탐색과 대조).
하한 m은 하루 최소 치료비 1만원으로 둔다(진료한 날에 0원은 없다) — 총액이 일수 × 1만원보다 작으면 총액 / 일수.
"""

import math
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import product

from data.limit_table import get_limit

DAY_FLOOR = 10_000            # 하루 최소 치료비(범위 계산의 하한)


def day_payout(cost: int, copay: int, pct: int, limit: int) -> int:
    """하루치 — (치료비 - 자기부담금) × 보상비율, 그날 한도까지. 자기부담금 이하면 0"""
    return max(min((cost - copay) * pct // 100, limit), 0)


@dataclass(frozen=True)
class DayLimits:
    """가입 특약 하나의 하루 한도들과 연간 총 한도"""
    type_: str                       # Ⅰ/Ⅱ/Ⅲ
    copay: int
    pct: int                         # 보상비율(%)
    non_surgery: int                 # 수술하지 않은 날(Ⅲ은 MRI·CT·내시경 없는 날)
    surgery: int
    mri_1st: int | None              # Ⅲ만 — MRI·CT·내시경을 받은 날, 연간 첫 번째
    mri_2nd: int | None              # Ⅲ만 — 연간 두 번째 이상
    annual_total: int

    @classmethod
    def of(cls, coverage_type: str, type_: str, copay: int) -> "DayLimits":
        base = get_limit(coverage_type, type_, "non_surgery_no_mri" if type_ == "Ⅲ" else "non_surgery")
        mri = type_ == "Ⅲ"
        return cls(type_=type_, copay=copay, pct=round(base["rate"] * 100), non_surgery=base["limit"],
                   surgery=get_limit(coverage_type, type_, "surgery")["limit"],
                   mri_1st=get_limit(coverage_type, type_, "non_surgery_mri_1st")["limit"] if mri else None,
                   mri_2nd=get_limit(coverage_type, type_, "non_surgery_mri_2nd_plus")["limit"] if mri else None,
                   annual_total=base["annual_total"])

    def limit_for(self, surgery: bool, mri_nth: int | None) -> tuple[int, str]:
        """그날의 한도와 이름. mri_nth: 그날이 올해 몇 번째 MRI·CT·내시경 날인가(1부터, Ⅲ에서 MRI 날일 때만).
        수술과 MRI가 같은 날이면 수술 한도(limit_table 주석 — 원문 예시)"""
        if surgery:
            return self.surgery, "수술한 날"
        if self.type_ == "Ⅲ" and mri_nth is not None:
            return (self.mri_1st, "MRI 등 연간 첫 번째") if mri_nth == 1 else (self.mri_2nd, "MRI 등 연간 두 번째 이상")
        return self.non_surgery, "수술 안 한 날" if self.type_ != "Ⅲ" else "수술·MRI 없는 날"


@dataclass(frozen=True)
class DayIn:
    """하루 — 치료비와 그날 수술·MRI 여부"""
    cost: int
    surgery: bool = False
    mri: bool = False


@dataclass(frozen=True)
class DayOut:
    cost: int
    surgery: bool
    mri: bool
    limit: int
    label: str
    payout: int


def exact(days: list[DayIn], lim: DayLimits, mri_before: int = 0) -> list[DayOut]:
    """날짜별 금액을 알 때 — 날마다 계산. mri_before: 올해 이미 받은 MRI·CT·내시경 날 수(청구 이력, Ⅲ만 쓴다).
    수술한 날의 MRI는 수술 한도라 MRI 횟수에 넣지 않는다"""
    out, seen = [], mri_before
    for d in days:
        nth = None
        if d.mri and not d.surgery:
            seen += 1
            nth = seen
        limit, label = lim.limit_for(d.surgery, nth)
        out.append(DayOut(d.cost, d.surgery, d.mri, limit, label, day_payout(d.cost, lim.copay, lim.pct, limit)))
    return out


def even_split(total: int, n: int) -> list[int]:
    """총액을 n일에 고르게 — 나머지 원은 앞날부터 1원씩"""
    q, r = divmod(total, n)
    return [q + 1 if i < r else q for i in range(n)]


def _saturation(copay: int, pct: int, limit: int) -> Fraction:
    """하루 지급액이 한도에 닿는 치료비 — 원 단위로 올리면 남은 날 몫이 1원 줄어 최대가 1원 작아진다. 분수 그대로 둔다"""
    return copay + Fraction(limit * 100, pct)


def bounds(total: int, limits: list[int], copay: int, pct: int) -> tuple[int, int]:
    """총액 total이 len(limits)일에 어떻게 나뉘든 나올 수 있는 지급 합계의 (최소, 최대). limits = 날마다의 한도
    (수술한 날이 섞이면 그날만 다르다). 날마다 하한 DAY_FLOOR(총액이 모자라면 총액 / 일수).
    원 미만은 합계에서 한 번 버린다. 날짜별 계산(exact)은 날마다 버리므로, 실제 나눔의 합계는 이 범위보다 (일수 - 1)원까지
    작을 수 있다(230,000원·4일: 최소 77,000원 ↔ 115,000·38,334·38,333·38,333원이면 76,999원). 원 단위 오차라 범위를 깎지 않는다"""
    n = len(limits)
    if n == 0:
        return 0, 0
    floor = min(DAY_FLOOR, total // n)
    # 같은 한도의 날은 서로 바꿔도 같다 — 한도별 날 수로 묶어 센다
    groups: dict[int, int] = {}
    for L in limits:
        groups[L] = groups.get(L, 0) + 1
    kinds = list(groups.items())
    best_min, best_max = None, None
    for free_kind in range(len(kinds)):                # 꼭짓점에서 벗어날 수 있는 하루가 어느 한도의 날인가
        per_kind = []                                   # 한도별로 (쓴 치료비, 지급액) 선택지
        for i, (L, cnt) in enumerate(kinds):
            fixed = cnt - 1 if i == free_kind else cnt
            pts = sorted({floor, max(copay, floor), max(_saturation(copay, pct, L), floor)})
            per_kind.append([(sum(x * k for x, k in zip(pts, comp)),
                              sum(_value100(x, copay, pct, L) * k for x, k in zip(pts, comp)))
                             for comp in _compositions(fixed, len(pts))])
        free_L = kinds[free_kind][0]
        for choice in product(*per_kind):
            rest = total - sum(c[0] for c in choice)
            if rest < floor:
                continue
            v = sum(c[1] for c in choice) + _value100(rest, copay, pct, free_L)
            best_min = v if best_min is None else min(best_min, v)
            best_max = v if best_max is None else max(best_max, v)
    if best_min is None:                               # 꺾이는 점 조합이 다 총액을 넘는다 — 고르게 하나뿐
        v = sum(day_payout(x, copay, pct, L) for x, L in zip(even_split(total, n), limits))
        return v, v
    return math.floor(best_min / 100), math.floor(best_max / 100)


def _value100(cost: Fraction | int, copay: int, pct: int, limit: int) -> Fraction | int:
    """하루치의 100배 — 범위 계산은 원 미만을 버리지 않고 더한 뒤 마지막에 한 번 버린다. 날마다 버리면 꼭짓점 조합이
    1원씩 손해를 봐 최대가 실제로 나올 수 있는 값보다 1~2원 작았다(3일 70만원: 440,999 ↔ 날짜별 45만·24만·1만이면 441,000)"""
    return max(min((cost - copay) * pct, limit * 100), 0)


def even_value(total: int, limits: list[int], copay: int, pct: int) -> int:
    """고르게 나뉘었다면 — 날마다 total / n(원 미만 그대로)으로 계산해 합계에서 한 번 버린다. 원 단위로 나눠 날마다 버리면
    3일 70만원이 426,999원(233,334 + 233,333 + 233,333)이 돼 범위(최소·최대)와 버림 방식이 어긋났다"""
    share = Fraction(total, len(limits))
    return math.floor(sum(_value100(share, copay, pct, L) for L in limits) / 100)


def _compositions(n: int, k: int):
    """n을 k칸에 나누는 모든 방법(0 포함)"""
    if k == 1:
        yield (n,)
        return
    for first in range(n + 1):
        for rest in _compositions(n - first, k - 1):
            yield (first, *rest)


@dataclass
class Annual:
    """연간 총 한도 — 올해(보험연도) 이미 받은 보험금을 빼고 남은 한도"""
    total: int
    used: int
    year_start: str | None           # 이번 보험연도 시작일(가입일 기준 계약해당일, ISO). 가입일을 모르면 None
    claims: int = 0                  # 올해 청구 건수
    mri_before: int = 0              # 올해 MRI·CT·내시경 날 수(Ⅲ)

    @property
    def remaining(self) -> int:
        return max(self.total - self.used, 0)

    def cap(self, value: int) -> int:
        return min(value, self.remaining)


@dataclass
class Plan:
    """한 계산의 결과 — 정확하면 days(날짜별), 아니면 lo·hi·even(범위와 고르게 나뉜 추정)"""
    exact: bool
    n: int
    total: int
    days: list[DayOut] = field(default_factory=list)
    lo: int | None = None            # 범위 — 연간 한도 적용 전
    hi: int | None = None
    even: int | None = None          # 고르게 나뉘었다면 — 연간 한도 적용 전
    raw: int = 0                     # 연간 한도 적용 전 합계(정확하면 날짜별 합, 범위면 even)
    payout: int = 0                  # 연간 한도까지 적용한 대표값(정확하면 그 값, 범위면 even)
    capped: bool = False             # 연간 한도에 걸렸다(대표값 기준)
    fixed: list[DayOut] = field(default_factory=list)   # 범위 계산에서 금액을 아는 날(수술한 날 금액 등)

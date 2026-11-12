"""
demo.py
체험 로그인 카드(2026-11-12, 13번 2-4절) — 체험 풀의 가상 직원마다 "이 계정으로 무엇을 볼 수 있나"를 한 줄 + 태그로.

- 숫자는 사내규정 개인화와 같은 계산(hr_personal.profile)이다 — 카드의 연차 잔여와 챗봇 답이 어긋나지 않는다
- 급여 · 평균임금 · 수당 금액 · 평가 등급은 싣지 않는다(본인 정보 블록과 같은 기준 — 물을 때 답에만 나온다)
- 근속은 휴직(육아 · 병역 외)을 뺀 값이다(hr_personal.tenure_days, 제3조 5호)
"""

from datetime import date

from app.schemas import DemoAccountOut
from app.services import hr_personal
from app.services.auth import Employee


def _tenure(years: int, months: int) -> str:
    if years == 0:
        return f"근속 {months}개월"
    return f"근속 {years}년" + (f" {months}개월" if months else "")


def _days(x: float | None) -> str:
    return "" if x is None else (f"{int(x)}" if float(x).is_integer() else f"{x:g}")


def card(emp: Employee, role: str, f: hr_personal.Facts | None, today: date) -> DemoAccountOut:
    """카드 한 장. 인사 원장이 없으면 이름 · 직급만"""
    if f is None:
        return DemoAccountOut(employee_id=emp.employee_id, name=emp.name, grade=emp.grade, team=emp.team, role=role,
                              summary=f"{emp.name} {emp.grade}", tags=[])
    p = hr_personal.profile(f, today)
    parts = [f"{emp.name} {emp.grade}", _tenure(p["tenure_years"], p["tenure_months"])]
    if p["leave_left"] is not None:
        parts.append(f"연차 {_days(p['leave_left'])}일 남음")
    tags: list[str] = []
    if p["probation_end"] is not None:
        tags.append(f"수습 중({p['probation_end']:%m-%d}까지)")
    if f.employment_type != "정규직":
        tags.append(f.employment_type)
    if f.career_hire:
        tags.append("경력 입사(수습 면제)")
    if p["tenure_years"] < 1:
        tags.append("1년 미만(퇴직금 없음)")
    for kind, start, end in f.absences:
        tags.append(f"{kind} {'중' if start <= today <= end else '이력'}")
    if p["certificates"]:
        tags.append(f"자격증 {len(p['certificates'])}개(자격수당)")
    elig = p["promotion_eligible_on"]
    if p["next_grade"] and elig is not None and elig <= today:
        tags.append(f"{p['next_grade']} 승진 대상")
    return DemoAccountOut(employee_id=emp.employee_id, name=emp.name, grade=emp.grade, team=emp.team, role=role,
                          summary=" · ".join(parts), tags=tags)

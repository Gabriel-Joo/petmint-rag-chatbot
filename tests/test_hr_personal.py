"""사내규정 개인화(hr_personal) — 트리거 범위와 인사규정 계산(연차 제17조·퇴직금 제28조·자격수당 제27조·승진 제33조). DB 없이"""

import unittest
from datetime import date

from app.services.hr_personal import Facts, annual_leave, answer, average_wage, cert_allowance, promotion, tenure_days, topics_of

TODAY = date(2026, 10, 28)


def facts(**kw) -> Facts:
    base = dict(employee_id="E1", name="홍길동", team="보상기획팀", grade="대리", grade_since=date(2022, 3, 1),
                employment_type="정규직", hire_date=date(2018, 1, 2), birth_date=date(1990, 1, 1), retired_on=None)
    extra = {k: kw.pop(k) for k in ("certificates", "payroll", "leaves", "absences", "evaluations") if k in kw}
    f = Facts(**(base | kw))
    for k, v in extra.items():
        setattr(f, k, v)
    return f


class Triggers(unittest.TestCase):
    def test_personal_questions_fire(self):
        for q, t in [("제 연차 몇 개 남았어요?", ["연차"]), ("내 퇴직금 예상액 알려줘", ["퇴직금"]),
                     ("저 언제 대리 될 수 있어요?", ["승진"]), ("제가 차장 승진 대상인가요?", ["승진"]),
                     ("내 자격수당 얼마야?", ["자격수당"]), ("제 연차 몇 개 남았고 퇴직금은 얼마예요?", ["연차", "퇴직금"])]:
            self.assertEqual(topics_of(q), t, q)

    def test_general_or_out_of_scope_do_not_fire(self):
        for q in ["연차는 몇 개 나와요?", "퇴직금은 어떻게 계산해요?", "과장에서 차장 되려면 몇 년 있어야 해요?",
                  "손해사정사 따면 자격수당 얼마예요?", "제가 손해사정사 따면 자격수당 얼마예요?",
                  "할머니가 돌아가셨는데 제 경조휴가는 며칠이에요?", "제 병가는 며칠까지 쓸 수 있어요?",
                  "제가 재택근무 며칠까지 되나요?", "제17조 연차 규정 알려줘", "제 연차 사용 방법 알려주세요", "대리에서 과장 되려면 최소 몇 년 있어야 해요?"]:
            self.assertEqual(topics_of(q), [], q)

    def test_unknown_employee_goes_to_model(self):
        self.assertIsNone(answer("제 연차 몇 개 남았어요?", None, TODAY))


class Leave(unittest.TestCase):
    def test_cap_25_and_used_in_current_period(self):
        f = facts(hire_date=date(2001, 3, 2), leaves=[("연차", date(2026, 4, 13), 5), ("연차", date(2026, 2, 1), 3),
                                                       ("병가", date(2026, 5, 1), 2), ("연차", date(2026, 9, 18), 0.5)])
        a = annual_leave(f, TODAY)
        self.assertEqual((a["start"], a["end"], a["grant"], a["used"], a["left"]),
                         (date(2026, 3, 2), date(2027, 3, 1), 25, 5.5, 19.5))

    def test_under_one_year_monthly(self):
        a = annual_leave(facts(hire_date=date(2025, 12, 1)), TODAY)
        self.assertEqual((a["grant"], a["left"]), (10, 10))

    def test_two_years_no_extra(self):
        self.assertEqual(annual_leave(facts(hire_date=date(2024, 5, 1)), TODAY)["grant"], 15)
        self.assertEqual(annual_leave(facts(hire_date=date(2021, 5, 1)), TODAY)["grant"], 17)   # 5년 → +2


class Severance(unittest.TestCase):
    PAY = [(date(2026, 7, 1), 3_000_000), (date(2026, 8, 1), 3_000_000), (date(2026, 9, 1), 3_200_000), (date(2026, 10, 1), 9_999_999)]

    def test_average_wage_uses_last_three_finished_months(self):
        per_day, months, total, days = average_wage(facts(payroll=self.PAY), TODAY)
        self.assertEqual((months[0], months[-1], total, days), (date(2026, 7, 1), date(2026, 9, 1), 9_200_000, 92))

    def test_excluded_absence(self):
        f = facts(absences=[("질병휴직", date(2019, 5, 1), date(2019, 5, 10)), ("육아휴직", date(2020, 1, 1), date(2020, 12, 31))])
        self.assertEqual(tenure_days(f, TODAY), ((TODAY - date(2018, 1, 2)).days - 10, 10))

    def test_under_one_year(self):
        text, _ = answer("제 퇴직금 얼마예요?", facts(hire_date=date(2026, 1, 5), payroll=self.PAY), TODAY)
        self.assertIn("퇴직금이 없습니다", text)
        self.assertIn("2027년 1월 5일", text)


class Allowance(unittest.TestCase):
    def test_bigger_one_and_next_month_rule(self):
        f = facts(certificates=[("정보처리기사", date(2010, 1, 1), date(2010, 1, 5)), ("손해사정사", date(2026, 9, 1), date(2026, 9, 30)),
                                ("손해평가사", date(2026, 10, 1), date(2026, 10, 15)), ("변호사", date(2026, 1, 1), None)])
        c = cert_allowance(f, TODAY)
        self.assertEqual((c["amount"], c["cert"]), (200_000, "손해사정사"))
        self.assertEqual([(n, s) for n, _, s in c["pending"]], [("손해평가사", date(2026, 11, 1)), ("변호사", None)])


class Promotion(unittest.TestCase):
    def test_dd_excluded(self):
        p = promotion(facts(evaluations=[("2025-H1", "B"), ("2025-H2", "D"), ("2026-H1", "D")]), TODAY)
        self.assertEqual((p["next"], p["eligible"], p["met"], p["dd"]), ("과장", date(2026, 3, 1), True, True))

    def test_top_grade(self):
        text, _ = answer("저 승진 언제 돼요?", facts(grade="부장", grade_since=date(2016, 1, 1)), TODAY)
        self.assertIn("규정에 나와 있지 않습니다", text)


class Status(unittest.TestCase):
    def test_contract_staff(self):
        text, arts = answer("제 퇴직금 얼마예요?", facts(employment_type="계약직"), TODAY)
        self.assertIn("개별근로계약", text)
        self.assertEqual(arts, [2])

    def test_retired(self):
        text, _ = answer("제 연차 몇 개 남았어요?", facts(retired_on=date(2026, 8, 31)), TODAY)
        self.assertIn("퇴직한 직원", text)


if __name__ == "__main__":
    unittest.main()

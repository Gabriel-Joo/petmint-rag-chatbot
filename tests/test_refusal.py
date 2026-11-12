"""
test_refusal.py
거절 판정(data/refusal.py) — 2026-11-12 C안. 운영에서 잘못 찍힌 답(정년 · 연차수당 · 출장비 · 나이 참고 줄)은 거절이 아니고,
진짜 거절(NO_ANSWER 그대로 · 그 뒤 참고 줄 · 서두 뒤 "명시되어 있지 않습니다")은 그대로 거절이다. refused_v1은 예전 판정 그대로.
"""

import unittest

from data import prompts, refusal

AGE_NOTE = ("\n\n참고: 까미는 원장 기준 9세입니다. 새로 가입할 수 있는 나이는 만 8세(실속형은 만 10세)까지이고, "
            "재가입은 회사가 정한 재가입 나이 범위 안이어야 합니다(구체 나이는 약관에 없음).")
# 운영 2026-11-11 · 11-10 · 11-03 — 다 답한 뒤 맺음말 · 단서
ANSWERED = [
    "귀하의 정년은 만 60세입니다. 정년퇴직일은 정년에 도달한 날이 속하는 달의 말일로 합니다. [발췌 1] 제43조(정년) ①항에 명시된 내용입니다. "
    "촉탁직 재채용 여부는 회사와 협의해야 하며, 규정에서 직접 확인되지는 않습니다. 인사부서에 확인하여 구체적인 절차를 안내받으시기 바랍니다.",
    "따라서, 다음 주 부산 출장 시 일비는 30,000원, 숙박비는 100,000원까지 지급됩니다. 추가 확인이 필요한 경우 인사부서에 문의하시기 바랍니다.",
    "통원 치료비 77만원의 70%인 53만 9,000원이 1일 한도 15만원을 넘어 15만원입니다." + AGE_NOTE,      # 나이 참고 줄만 문구를 가졌다
]
REFUSED = [
    prompts.NO_ANSWER_TEXT,
    prompts.NO_ANSWER_TEXT + AGE_NOTE,                                                              # 모델 거절 + 코드 참고 줄
    "메리츠 펫보험 상담원으로서 답변드리겠습니다.\n\n보험금 할인에 관한 정보는 [약관 발췌]에 명시되어 있지 않습니다.",   # 서두 뒤 거절(베이스 N04)
    "[규정 발췌]에 따르면, 부모님의 칠순 잔치에 대한 경조휴가는 명시되어 있지 않습니다. 인사부서에 확인하여 정확한 절차를 따르는 것이 필요합니다.",
]


class Refusal(unittest.TestCase):
    def test_answered_not_refused(self):
        self.assertEqual([a[:20] for a in ANSWERED if refusal.refused(a)], [])

    def test_refused_kept(self):
        self.assertEqual([a[:20] for a in REFUSED if not refusal.refused(a)], [])

    def test_v1_unchanged(self):
        """예전 판정은 그대로 — 위 ANSWERED도 v1에서는 거절이었다(과거 수치 재현)"""
        self.assertTrue(all(refusal.refused_v1(a) for a in ANSWERED + REFUSED))

    def test_sign_off(self):
        """맺음말은 다른 답이 있으면 거절이 아니고, 맺음말뿐이면 거절이다"""
        with_answer = "올해 연차는 15일이고 지금까지 3일을 써서 12일 남았습니다. 인사부서에 확인하세요."
        self.assertFalse(refusal.refused(with_answer))
        self.assertTrue(refusal.refused_v1(with_answer))
        self.assertTrue(refusal.refused("인사부서에 문의해 주세요."))
        self.assertTrue(refusal.refused("자세한 내용은 인사부서에 확인하세요."))

if __name__ == "__main__":
    unittest.main()

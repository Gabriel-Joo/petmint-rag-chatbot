"""
test_stage5.py
rebuild5 준비 5단계(2026-10-21) — 생성 검사 버그. 별표 검산이 단락 평가로 꺼지던 것(verify_all), 반려동물 주어 검사.
"""

import unittest

from data import faq_verify
from data.faq_checks import check_pet_subject

LAWYER = "【별표3】 소송목적의 값에 따른 변호사비용"


class VerifyAll(unittest.TestCase):
    def test_byeopyo_wrong_amount_caught(self):
        """학습 데이터에 남았던 예 — 3,000만원 → 570만원(정답 280만원). 예전 `verify or verify_byeopyo`는 통과시켰다"""
        qa = {"question": "소송목적의 값이 3,000만원일 때 변호사비용은 어떻게 계산되나요?",
              "answer": "300만원까지는 30만원이고, 그 이후의 2,700만원(3,000만원 - 300만원)에 대해 10%를 적용해 "
                        "30만원 + 270만원 = 570만원입니다."}
        old = faq_verify.verify(qa, None, LAWYER) or faq_verify.verify_byeopyo(qa, LAWYER)
        new = faq_verify.verify_all(qa, None, LAWYER)
        self.assertFalse(new[0])
        self.assertNotEqual(bool(old and not old[0]), True)        # 예전 검사는 놓쳤다(버그 재현)

    def test_byeopyo_right_amount_passes(self):
        qa = {"question": "소송목적의 값이 3,000만원이면 변호사비용 한도는요?",
              "answer": "200만원 + (3,000만원 - 2,000만원) × 8% = 280만원입니다."}
        self.assertTrue(faq_verify.verify_all(qa, None, LAWYER)[0])

    def test_not_calc(self):
        self.assertIsNone(faq_verify.verify_all({"question": "해지하면 환급금 있나요?", "answer": "있습니다."}, None, None))


class PetSubject(unittest.TestCase):
    def test_flags(self):
        self.assertTrue(check_pet_subject("우리 강아지가 소송으로 법원에 가야 하는데 비용 나와요?"))
        self.assertTrue(check_pet_subject("우리 고양이의 주소가 바뀌었는데 어떻게 해야 하나요?"))
        self.assertFalse(check_pet_subject("우리 강아지가 다리를 다쳤는데 치료비 나와요?"))
        self.assertFalse(check_pet_subject("소송 걸리면 변호사비 나와요?"))


if __name__ == "__main__":
    unittest.main()

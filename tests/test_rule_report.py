"""
test_rule_report.py
코드 답 규칙 운영 집계(db/rule_report.py, docs/16 5절 2단계)와 turns.code_rule 기록(0008).

- 집계는 숫자만 — 질문·답 글·세션 id가 결과 어디에도 없다
- 거절 문구는 평가(scripts/verify_cases)와 같다
- DB 쪽(턴 로그가 code_rule을 쓰는가)은 PETMINT_DB_TESTS=1일 때만 돈다
"""

import json
import os
import unittest
import uuid

from db import rule_report
from scripts.verify_cases import REFUSAL_PHRASES

REFUSE = "제공된 약관 발췌에서는 확인되지 않는 내용입니다."


def turn(sid, q, a, rule=None, mode="업무특화", clarified=False, status="ok", rating=None, pet="초코"):
    return dict(mode=mode, session_id=sid, question=q, answer=a, pet_name=pet, code_rule=rule, clarified=clarified,
                status=status, rating=rating)


class RefusalTest(unittest.TestCase):
    def test_same_phrases_as_eval(self):
        self.assertEqual(rule_report.REFUSAL_PHRASES, REFUSAL_PHRASES)

    def test_refused(self):
        self.assertTrue(rule_report.refused(REFUSE))
        self.assertTrue(rule_report.refused("인사부서에 문의해 주세요."))
        self.assertFalse(rule_report.refused("통원 1일 한도는 15만 원입니다."))


class ReportTest(unittest.TestCase):
    ROWS = [
        turn("S-secret-1", "초코가 입원했어요. 보장되나요?", "…**어떤 질병이나 상해로 입원했는지**…", "disease_ask", clarified=True,
             rating="down"),
        turn("S-secret-1", "감기예요", REFUSE),
        turn("S-secret-1", "산책하다 다쳤어요", "상해(다친 것)라면…", "injury_followup", clarified=True),
        turn("S-secret-2", "초코가 장염으로 입원했는데 보험 되나요?", REFUSE),
        turn("S-secret-2", "통원 한도가 얼마예요?", "15만 원입니다.", rating="up"),
        turn("S-secret-2", "x", "", status="error"),
        turn("S-secret-3", "제 연차 며칠 남았어요?", REFUSE, mode="사내규정", pet=None),
        turn("S-secret-3", "연차 미사용분은 얼마 받나요?", "잔여 연차는 3일…", "hr_personal", mode="사내규정", pet=None),
    ]

    def setUp(self):
        self.out = rule_report.report(self.ROWS)

    def test_rules(self):
        r = self.out["rules"]
        self.assertEqual(r["disease_ask"], {"발동": 1, "되묻기": 1, "👎": 1, "다음 턴 모델 답": 1, "다음 턴 모델 거절": 1})
        self.assertEqual(r["injury_followup"]["다음 턴 없음"], 1)
        self.assertEqual(r["hr_personal"]["발동"], 1)

    def test_modes(self):
        m = self.out["modes"]["업무특화"]
        self.assertEqual((m["턴"], m["코드 답"], m["모델 답"], m["모델 거절"], m["상태 error"]), (6, 2, 3, 2, 1))
        self.assertEqual(self.out["modes"]["사내규정"]["모델 거절"], 1)

    def test_misses(self):
        self.assertEqual(self.out["misses"]["업무특화"],
                         {"병명되묻기: 겪은일+보장질문, 정규식이 병명 있다고 봄": 1})      # 병명(장염)이 있다 — 정규식 ⑤가 막은 갈래
        self.assertEqual(self.out["misses"]["사내규정"], {"개인화: 주제+본인 지칭(직원 정보 없음·답 없음)": 1})

    def test_numbers_only(self):
        dumped = json.dumps(self.out, ensure_ascii=False) + rule_report.render(self.out, "2026-10-29", None)
        for r in self.ROWS:
            for v in (r["session_id"], r["question"], r["answer"], r["pet_name"]):
                if v and len(v) > 1:
                    self.assertNotIn(v, dumped)

    def test_biz_miss_buckets(self):
        m = rule_report.biz_miss
        self.assertEqual(m("초코가 입원했는데 보험금 얼마 나와요?", "초코"), "병명되묻기: 겪은일+보장질문, 금액 낱말이 막음")
        self.assertEqual(m("초코가 태풍 때 다쳐서 입원했어요. 보장되나요?", "초코"), "병명되묻기: 겪은일+보장질문, 면책 사실이 막음")
        self.assertEqual(m("초코가 입원했어요. 보장되나요?", "초코"), "병명되묻기: 조건 모두 통과(특약 없음·후속 턴 등)")
        self.assertEqual(m("계단에서 떨어졌어요", "초코"), "상해 낱말")
        self.assertEqual(m("슬개골 탈구는 보장되나요?", "초코"), "병명되묻기: 보장질문만(겪은일 낱말 없음)")
        self.assertIsNone(m("가입 나이가 어떻게 되나요?", "초코"))


@unittest.skipUnless(os.environ.get("PETMINT_DB_TESTS") == "1", "로컬 MySQL 필요(PETMINT_DB_TESTS=1)")
class CodeRuleColumnTest(unittest.TestCase):
    """턴 로그가 code_rule을 쓴다 — 규칙 답은 이름, 모델 답은 NULL"""

    @classmethod
    def setUpClass(cls):
        from sqlalchemy import text

        from app.db import make_engine, now, utc
        from app.schemas import TurnLog
        from app.services.turn_log import TurnLogStore
        from db.conn import app_settings
        cls.text, cls.now, cls.utc, cls.TurnLog = staticmethod(text), staticmethod(now), staticmethod(utc), TurnLog
        cls.engine = make_engine(app_settings("petmint"))
        cls.store = TurnLogStore(cls.engine)
        cls.sid = str(uuid.uuid4())

    def setUp(self):
        with self.engine.begin() as c:
            c.execute(self.text("INSERT INTO sessions (session_id, mode, agent_email, started_at) VALUES (:s, '일반', 't@test', :t)"),
                      dict(s=self.sid, t=self.now()))

    def tearDown(self):
        with self.engine.begin() as c:
            c.execute(self.text("DELETE FROM turns WHERE session_id = :s"), dict(s=self.sid))
            c.execute(self.text("DELETE FROM sessions WHERE session_id = :s"), dict(s=self.sid))

    def log(self, rule):
        tid = str(uuid.uuid4())
        self.store.record(self.TurnLog(turn_id=tid, session_id=self.sid, question="q", answer="a", code_rule=rule, model="m",
                                       prompt_version="p", index_version="i", latency_ms=1, created_at=self.utc(self.now())))
        with self.engine.connect() as c:
            return c.execute(self.text("SELECT code_rule FROM turns WHERE turn_id = :t"), dict(t=tid)).scalar()

    def test_code_rule_written(self):
        self.assertEqual(self.log("disease_ask"), "disease_ask")
        self.assertIsNone(self.log(None))

    def test_report_reads_db(self):
        self.log("hr_personal")
        rows = [r for r in rule_report.fetch(self.engine, self.now().replace(year=2000), None) if r["session_id"] == self.sid]
        self.assertEqual(rule_report.report(rows)["rules"]["hr_personal"]["발동"], 1)


if __name__ == "__main__":
    unittest.main()

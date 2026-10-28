"""
rule_report.py
코드 답 규칙 운영 집계(2026-10-29, docs/16 5절 2단계) — 운영 턴 로그(turns.code_rule)를 규칙별로 센다. **숫자만** 낸다:
질문·답 글, 세션·상담원·고객·반려동물 값은 어떤 옵션으로도 찍지 않는다(운영 질문 글은 개인정보 — 사용자만 본다).
이미지에 db/가 들어 있어 클러스터 안에서 그대로 돈다(scripts/는 이미지에 없다).

  kubectl exec -n petmint deploy/petmint-app -- python -m db.rule_report              # 0008 적용 시각부터
  kubectl exec -n petmint deploy/petmint-app -- python -m db.rule_report --since 2026-11-01 --until 2026-11-08 --json

- 규칙별: 발동 수, 되묻기(clarified) 수, 👍/👎, 다음 턴(같은 세션 바로 뒤 질문) — 없음·코드 답·모델 답·모델 거절
- 모드별: 턴 수, 코드 답 수, 모델 답 중 거절 수 — 거절은 평가와 같은 문구 판정(verify_cases.REFUSAL_PHRASES, NO_ANSWER_TEXT)
- 놓침 후보(모델이 거절한 턴만): 업무특화 — 병명 되묻기 앞 조건(겪은 일·보장 질문) 중 어디까지 걸렸고 무엇이 막았는지,
  상해 낱말. 사내규정 — 개인화 주제 낱말이 본인 지칭과 함께 / 지칭 없이 있었는지. 정규식만 돌린다(모델은 부르지 않는다 — 3단계)
- code_rule NULL = 모델 답. 0008 전의 턴도 NULL이라 기본 시작 시각을 0008 적용 시각으로 둔다
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime

from sqlalchemy import text

from app.db import make_engine
from app.services import hr_personal
from app.services.lexicon import (AMOUNT_UPSELL, COVERAGE_Q_STRICT, EVENT_HAPPENED, EXEMPT_FACT, INJURY,
                                  NO_NAME_FILLER)
from data import prompts
from db.conn import app_settings

MIGRATION = "0008_turn_code_rule.sql"
# scripts/verify_cases.REFUSAL_PHRASES와 같아야 한다(tests/test_rule_report가 확인) — scripts/는 이미지에 없어 옮겨 적는다
REFUSAL_PHRASES = ("확인되지 않", "확인되지않", "명시되어 있지 않", "명시되어있지않", "나와 있지 않", "규정에 없", "약관에 없",
                   "찾을 수 없", "포함되어 있지 않", "언급되어 있지 않", "인사부서에 확인", "인사부서에 문의")


def _norm(t: str | None) -> str:
    return re.sub(r"[\s,]", "", t or "")


def refused(answer: str | None) -> bool:
    a = _norm(answer)
    return any(_norm(p) in a for p in REFUSAL_PHRASES) or _norm(prompts.NO_ANSWER_TEXT)[:12] in a


def biz_miss(question: str, pet_name: str | None) -> str | None:
    """업무특화 모델 거절 턴의 놓침 갈래 — 병명 되묻기(disease_ask) 앞 조건을 차례로 본다. 해당 없으면 None"""
    event, cover = bool(EVENT_HAPPENED.search(question)), bool(COVERAGE_Q_STRICT.search(question))
    if event and cover:
        if AMOUNT_UPSELL.search(question):
            return "병명되묻기: 겪은일+보장질문, 금액 낱말이 막음"
        if EXEMPT_FACT.search(question):
            return "병명되묻기: 겪은일+보장질문, 면책 사실이 막음"
        rest = re.sub(re.escape(pet_name) + r"(?:이|가|는|은|를|을|도|의)?", " ", question) if pet_name else question
        if re.search(r"[가-힣]", NO_NAME_FILLER.sub(" ", rest)):
            return "병명되묻기: 겪은일+보장질문, 정규식이 병명 있다고 봄"
        return "병명되묻기: 조건 모두 통과(특약 없음·후속 턴 등)"
    if INJURY.search(question):
        return "상해 낱말"
    if event:
        return "병명되묻기: 겪은일만(보장 질문 낱말 없음)"
    if cover:
        return "병명되묻기: 보장질문만(겪은일 낱말 없음)"
    return None


def hr_miss(question: str) -> str | None:
    if hr_personal.topics_of(question):
        return "개인화: 주제+본인 지칭(직원 정보 없음·답 없음)"
    if hr_personal.topics_of(question, assume_self=True):
        return "개인화: 주제 낱말만(본인 지칭 없음)"
    return None


def report(rows: list[dict]) -> dict:
    """rows: 턴(오래된 순) — mode, session_id, question, answer, pet_name, code_rule, clarified, status, rating.
    세션 id·글은 여기서만 쓰고 결과에는 숫자만 남긴다"""
    modes: dict[str, Counter] = defaultdict(Counter)
    rules: dict[str, Counter] = defaultdict(Counter)
    misses: dict[str, Counter] = defaultdict(Counter)
    by_session: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_session[r["session_id"]].append(r)
    for turns in by_session.values():
        for i, r in enumerate(turns):
            m, rule = modes[r["mode"]], r["code_rule"]
            m["턴"] += 1
            if r["status"] != "ok":
                m[f"상태 {r['status']}"] += 1
                continue
            if rule is None:
                m["모델 답"] += 1
                if refused(r["answer"]):
                    m["모델 거절"] += 1
                    miss = (biz_miss(r["question"], r["pet_name"]) if r["mode"] == "업무특화" else
                            hr_miss(r["question"]) if r["mode"] == "사내규정" else None)
                    if miss:
                        misses[r["mode"]][miss] += 1
                continue
            m["코드 답"] += 1
            c = rules[rule]
            c["발동"] += 1
            c["되묻기"] += bool(r["clarified"])
            if r["rating"]:
                c["👍" if r["rating"] == "up" else "👎"] += 1
            nxt = turns[i + 1] if i + 1 < len(turns) else None
            if nxt is None:
                c["다음 턴 없음"] += 1
            elif nxt["status"] != "ok":
                c["다음 턴 실패·취소"] += 1
            elif nxt["code_rule"] is not None:
                c["다음 턴 코드 답"] += 1
            else:
                c["다음 턴 모델 답"] += 1
                c["다음 턴 모델 거절"] += refused(nxt["answer"])
    return {"modes": {k: dict(v) for k, v in sorted(modes.items())},
            "rules": {k: dict(v) for k, v in sorted(rules.items(), key=lambda kv: -kv[1]["발동"])},
            "misses": {k: dict(v.most_common()) for k, v in sorted(misses.items())}}


def fetch(engine, since: datetime, until: datetime | None) -> list[dict]:
    q = ("SELECT s.mode, t.session_id, t.question, t.answer, t.pet_name, t.code_rule, t.clarified, t.status, f.rating"
         " FROM turns t JOIN sessions s USING (session_id) LEFT JOIN feedback f USING (turn_id)"
         " WHERE t.created_at >= :since" + (" AND t.created_at < :until" if until else "") +
         " ORDER BY t.session_id, t.created_at, t.turn_id")
    with engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(q), dict(since=since, until=until))]


def migration_time(engine) -> datetime:
    with engine.connect() as c:
        t = c.execute(text("SELECT applied_at FROM schema_migrations WHERE version = :v"), dict(v=MIGRATION)).scalar()
    if t is None:
        raise SystemExit(f"{MIGRATION}이 아직 적용되지 않았다 — python -m db.migrate")
    return t


def render(out: dict, since, until) -> str:
    lines = [f"기간 {since} ~ {until or '지금'} (UTC)", "", "[모드별]"]
    for mode, c in out["modes"].items():
        model = c.get("모델 답", 0)
        rate = f" ({c.get('모델 거절', 0) / model:.1%})" if model else ""
        lines.append(f"  {mode}: 턴 {c['턴']} · 코드 답 {c.get('코드 답', 0)} · 모델 답 {model} · 모델 거절 {c.get('모델 거절', 0)}{rate}"
                     + "".join(f" · {k} {v}" for k, v in c.items() if k.startswith("상태")))
    lines += ["", "[규칙별]  발동 · 되묻기 · 👍/👎 · 다음 턴: 없음/코드/모델(거절)/실패"]
    for rule, c in out["rules"].items():
        lines.append(f"  {rule:16} {c['발동']:5} · {c.get('되묻기', 0):4} · {c.get('👍', 0)}/{c.get('👎', 0)}"
                     f" · {c.get('다음 턴 없음', 0)}/{c.get('다음 턴 코드 답', 0)}/{c.get('다음 턴 모델 답', 0)}"
                     f"({c.get('다음 턴 모델 거절', 0)})/{c.get('다음 턴 실패·취소', 0)}")
    lines += ["", "[놓침 후보 — 모델이 거절한 턴]"]
    for mode, c in out["misses"].items():
        lines.append(f"  {mode}")
        lines += [f"    {k}: {v}" for k, v in c.items()]
    return "\n".join(lines)


def _when(s: str) -> datetime:
    return datetime.combine(date.fromisoformat(s), datetime.min.time()) if len(s) == 10 else datetime.fromisoformat(s)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=_when, help="UTC, 2026-11-01 또는 2026-11-01T09:00 — 기본은 0008 적용 시각")
    ap.add_argument("--until", type=_when)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    engine = make_engine(app_settings("petmint"))
    since = a.since or migration_time(engine)
    out = report(fetch(engine, since, a.until))
    print(json.dumps(out, ensure_ascii=False, indent=1) if a.json else render(out, since, a.until))


if __name__ == "__main__":
    main()

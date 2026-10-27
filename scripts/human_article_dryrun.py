"""
human_article_dryrun.py
보통약관 사람 보험 조(제3조 지급사유·제4조 세부규정·제5조 지급하지 않는 사유) dry-run(2026-10-28) — 모델은 부르지 않는다.
검색 서버(운영 설정: v3·확장 v2·pool 50)에서 후보 20개를 받아 서버와 같은 섹션 가중으로 줄 세운 뒤 두 안이 어디에 걸리는지 센다.

  1안 demote  업무특화에서 보통약관 제3·4·5조 점수에 FACTOR를 곱한다
  2안 inject  질문에 특약 낱말이 없고, 상위 3에 보통약관 제3·5조가 있으면 가입한 의료비 특약의 같은 제목 조
              (제3조 ↔ 제1조 보험금의 지급사유, 제5조 ↔ 제2조 보험금을 지급하지 않는 사유) 중 후보 20 안에 든 조각을
              그 보통약관 조각 바로 앞으로 올린다(후보에 없으면 아무것도 안 함)

대상: 평가 220 보이는 세트의 모든 턴(질문 그대로) + 탐침 15문항 × 초코·치즈·콩이(평가에서 뽑지 않음)
  python -m scripts.human_article_dryrun [--factor 0.5] [--out data/review/human_article_dryrun.md]
"""

import argparse
import json
import re
from pathlib import Path

from app import config
from app.services.customers import scope_for
from app.services.retrieval import Retriever
from data.rag_context import SECTION_PRIORITY
from scripts.eval_serving import pets

ROOT = Path(__file__).resolve().parent.parent
HUMAN = {3, 4, 5}                       # 보통약관 사람 상해보험 보장 조
TWIN = {3: 1, 5: 2}                     # 보통약관 조 → 같은 제목 의료비 특약 조
RIDER_WORD = re.compile(r"통원|입원|치료|진료|수술|의료비|병원|질병|특약")
PROBES = ["보험금 안 나오는 경우는 어떤 게 있어요?", "면책 사항이 뭐뭐 있어요?", "보장 안 되는 질병은 뭔가요?",
          "어떤 치료는 보험이 안 돼요?", "병원비 보험금 못 받는 경우가 있나요?", "보상 제외되는 항목 알려 주세요",
          "치료비 청구가 거절되는 경우는요?", "통원비 안 나오는 경우가 있어요?", "입원비는 어떤 경우에 안 나와요?",
          "보험금 지급 안 되는 사유가 뭐예요?", "병원비 보장되는 범위가 어떻게 돼요?", "어떤 경우에 치료비를 보상받을 수 있어요?",
          "질병 치료는 다 보장되나요?", "다쳐서 병원 가면 보장돼요?", "보장 내용 좀 알려 주세요"]
PROBE_PETS = ["P001", "P004", "P005"]


def is_human(r): return r.get("section") == "보통약관" and r.get("article_num") in HUMAN
def is_med(r): return "의료비" in (r.get("section_name") or "")
def label(r): return f"{(r.get('section_name') or r['section'])[-12:]} {r.get('article_num')}"


def rank(raw, factor=1.0):
    out = [dict(r, adj=r["score"] * SECTION_PRIORITY.get(r.get("section"), 0.8) * (factor if is_human(r) else 1.0)) for r in raw]
    return sorted(out, key=lambda r: r["adj"], reverse=True)


def inject(q, ranked):
    if RIDER_WORD.search(q):
        return ranked, False
    top = ranked[:3]
    hum = next((i for i, r in enumerate(top) if r.get("section") == "보통약관" and r.get("article_num") in TWIN), None)
    if hum is None:
        return ranked, False
    want = TWIN[ranked[hum]["article_num"]]
    twins = [r for r in ranked[3:] if is_med(r) and r.get("article_num") == want]
    if not twins:
        return ranked, "후보 없음"
    rest = [r for r in ranked if r not in twins]
    return rest[:hum] + twins + rest[hum:], True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--factor", type=float, default=0.5)
    ap.add_argument("--out", default=str(ROOT / "data/review/human_article_dryrun.md"))
    a = ap.parse_args()
    rt = Retriever(config.SEARCH_SERVICE_URL, expand=config.SEARCH_EXPAND, variant=config.SEARCH_VARIANT,
                   pool_k=config.SEARCH_POOL, expand_dict=config.SEARCH_EXPAND_DICT)
    pm = pets()
    cases = json.loads((ROOT / "data/eval/eval220.json").read_text(encoding="utf-8"))["cases"]
    items = [(t["id"], c["pet_id"], t["query"], t.get("gold") or []) for c in cases for t in (c.get("turns") or [c])]
    items += [(f"탐침{i + 1:02d}-{pm[p].name}", p, q, []) for i, q in enumerate(PROBES) for p in PROBE_PETS]
    rows = []
    for tid, pid, q, gold in items:
        raw = rt.search(q, scope_for(pm[pid]), top_k=20, candidate_k=20)
        now = rank(raw)
        dem = rank(raw, a.factor)
        inj, fired = inject(q, now)
        both, fired2 = inject(q, dem)
        r = dict(id=tid, q=q, now=[label(x) for x in now[:3]], dem=[label(x) for x in dem[:3]],
                 inj=[label(x) for x in inj[:3]], both=[label(x) for x in both[:3]], fired=fired, fired2=fired2,
                 human_top3=any(is_human(x) for x in now[:3]), human_pool=sum(is_human(x) for x in now),
                 med_pool=[i + 1 for i, x in enumerate(now) if is_med(x)][:5])
        rows.append(r)
        print(tid, r["now"], "→", r["dem"] if r["dem"] != r["now"] else "-", "|", r["fired"], flush=True)
    json.dump(rows, open(Path(a.out).with_suffix(".json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

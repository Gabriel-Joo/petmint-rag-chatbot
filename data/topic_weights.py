"""
topic_weights.py
주제 가중치(data/review/topic_weights_draft_20261013.md 초안) — 05 단위별 생성 횟수와 06 단위 상한에 같이 곱한다.

- 05: 단위별 생성 횟수 × 가중치(faq_generate.build_plan)
- 06: find_over_cap 상한 max(5, 길이/40) × 가중치(faq_checks.weighted_cap) — 상한도 곱하지 않으면 많이 만들어도 06에서 깎인다
- 초안이 스스로 지적한 한계: 조문 가중치만으로는 빈출 주제가 늘지 않는다(가입 나이 1.5% → 1.3%, 계산).
  가입 나이는 일반조항 제2조 '반려동물' 정의의 1호, 기왕증은 의료비 제2조 ⑥처럼 조문 안의 한두 항목이라서다.
  → ×3 묶음 중 원문이 그 주제를 다루는 단위(faq_style.eligible_topics)에 주제 지정 회차를 더한다(faq_generate, 실험 C v2C-T r2 방식).
- ×0 묶음('제외 목록 확정분')은 faq_units.EXCLUDE_ARTICLES·EXCLUDE_SECTION_NAMES로 이미 단위에서 빠져 있다(make_units).

규칙은 단위·QA 어느 것이든(section, section_name, article_num, article_title만 본다) 적용된다.
초안 표의 '현재 최종 QA' 열과 같은 수가 나오는지는 python -m data.topic_weights 로 확인한다(check_against_draft).

실행: python -m data.topic_weights        — 규칙 검증 + 적용 후 예상 주제 분포(생성 전, GPU·Ollama 불필요)
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
FAQ_DIR = PROJECT_DIR / "data" / "faq"

GENERAL = "반려동물 비용손해 관련 특별약관 일반조항"
LIABILITY = "갱신형 펫퍼민트 반려견 배상책임보장 특별약관"
LIMITED = "반려동물 특정 질병 보장제한부 인수 특별약관"


def _is_med(d: dict) -> bool:
    return d.get("section") == "특별약관" and "의료비" in (d.get("section_name") or "")


def _art(d: dict, nums) -> bool:
    return d.get("article_num") in nums


# (가중치, 묶음, 초안 표의 대상 이름, 초안 '현재 최종 QA', 조건) — 순서대로 처음 맞는 규칙을 쓴다
RULES = [
    (3.0, "핵심", "의료비 특약 제1조(보상 한도·자기부담금·보상비율·면책기간 단서)", 738,
     lambda d: _is_med(d) and _art(d, (1,))),
    (3.0, "핵심", "의료비 특약 제2조(보장 제외 — 기왕증·예방접종·중성화·미용 등)", 403,
     lambda d: _is_med(d) and _art(d, (2,))),
    (3.0, "핵심", "일반조항 제2조(반려동물 정의 = 가입 나이·대상)", 130,
     lambda d: d.get("section_name") == GENERAL and _art(d, (2,))),
    (3.0, "핵심", "일반조항 제4·5조(보험금 청구 서류·지급 기한)", 61,
     lambda d: d.get("section_name") == GENERAL and _art(d, (4, 5))),
    (3.0, "핵심", "일반조항 제15·16조(재가입·보장개시)", 68,
     lambda d: d.get("section_name") == GENERAL and _art(d, (15, 16))),
    (3.0, "핵심", "특정 질병 보장제한부 인수 특약 + 특정질병 분류표(부담보)", 123,
     lambda d: d.get("section_name") == LIMITED or (d.get("section_name") or "").startswith("특정질병 분류표")),
    # 의료비 제3~5조 중 정의 조문만 — 통원 제4·5조는 '특별약관의 소멸'이다
    (2.0, "자주", "의료비 특약 제3~5조(수술·입원·MRI 정의)", 277,
     lambda d: _is_med(d) and _art(d, (3, 4, 5)) and "정의" in (d.get("article_title") or "")),
    (2.0, "자주", "일반조항 제7~9조(알릴 의무·위반 효과)", 91,
     lambda d: d.get("section_name") == GENERAL and _art(d, (7, 8, 9))),
    (2.0, "자주", "일반조항 제17·18·20조(연체 해지·부활·임의해지)", 72,
     lambda d: d.get("section_name") == GENERAL and _art(d, (17, 18, 20))),
    (2.0, "자주", "보통약관 제20조(청약 철회)·제35조(해약환급금)", 34,
     lambda d: d.get("section") == "보통약관" and _art(d, (20, 35))),
    (2.0, "자주", "배상책임 특약 제1·2조(보상하는/않는 손해, 강아지)", 30,
     lambda d: d.get("section_name") == LIABILITY and _art(d, (1, 2))),
    (2.0, "자주", "안내: 가입자 유의사항·주요내용 요약서·보험금 지급 절차", 174,
     lambda d: d.get("section_name") in ("가입자 유의사항", "주요내용 요약서", "보험금 지급 절차")),
    (0.5, "중복", "보통약관 제7·8·15·17·18·19·23·26·29~33조(일반조항이 같은 역할)", 297,
     lambda d: d.get("section") == "보통약관" and _art(d, (7, 8, 15, 17, 18, 19, 23, 26, 29, 30, 31, 32, 33))),
]
DEFAULT = (1.0, "나머지", "그 밖의 모든 조문")
TOPIC_ROUND_MIN_WEIGHT = 3.0     # 주제 지정 회차 대상: ×3 묶음 중 원문이 그 주제를 다루는 단위(초안 '×3 묶음에서 시작')


def rule_of(d: dict) -> tuple[float, str, str]:
    """(가중치, 묶음, 대상 이름)"""
    for w, tier, name, _, cond in RULES:
        if cond(d):
            return w, tier, name
    return DEFAULT


def unit_weight(d: dict) -> float:
    return rule_of(d)[0]


def cap_weights(units: dict[str, dict]) -> dict[str, float]:
    """unit_id → 가중치 (06 find_over_cap용)"""
    return {uid: unit_weight(u) for uid, u in units.items()}


# ---------- 검증: 초안 표와 같은 대상을 고르는가 ----------
def check_against_draft() -> list[tuple[str, int, int]]:
    """(대상, 초안 수, 이 규칙으로 센 수) — 초안이 센 데이터(checked/final, 2026-10-13, 사람 대상 조항 제외 전)에 규칙을 적용"""
    final = [f for sp in ("강아지", "고양이")
             for f in json.load(open(FAQ_DIR / "checked" / f"petmint_{sp}_faq_final.json", encoding="utf-8"))]
    got = Counter(rule_of(f)[2] for f in final)
    return [(name, draft, got.get(name, 0)) for _, _, name, draft, _ in RULES]


# ---------- 예상 주제 분포 (생성 전) ----------
def _survivors(checked: list[dict]) -> list[dict]:
    """06 상한(unit_cap) 전에 남은 QA — drop이 없거나 drop 사유가 unit_cap뿐인 것"""
    return [f for f in checked if all(c["check"] == "unit_cap" or c["action"] != "drop" for c in f["checks"])]


def estimate(plan: dict, units: dict[str, dict[str, dict]]) -> dict:
    """plan: faq_generate.build_plan 결과. units: 종 → unit_id → 단위.
    가정(근사): 단위마다 '생성 1회당 06 상한 전 생존 QA 수'와 그 QA의 주제 비율이 기존 전량(v1, 10라운드)과 같다.
    주제 회차는 실험 C v2C-T r2(주제 회차, V2C 프롬프트, 16단위 21건)에서 ① 호출당 생존 QA ② 지정한 주제가 질문에 실제로
    나온 비율(주제별, 표본이 없으면 전체 평균)을 쓴다. 이번 주제 회차는 v1·주제 하나라 실제와 다를 수 있다.
    06 상한은 단위마다 min(상한 × 가중치, 예상 생존 수)로 자르고, 잘리면 일반·주제 QA를 같은 비율로 줄인다."""
    from data import faq_checks, faq_style
    topic_tot, total, by_tier = Counter(), 0.0, defaultdict(lambda: [0, 0, 0.0])
    exp = FAQ_DIR / "exp_c" / "v2C-T" / "checked" / "petmint_강아지_faq_checked_all.json"
    exp_sel = FAQ_DIR / "exp_c" / "selection.json"
    t_all = [f for f in json.load(open(exp, encoding="utf-8")) if f.get("gen_kind") == "topic"] if exp.exists() else []
    t_surv = [f for f in _survivors(t_all)]
    t_called = sum(1 for s in json.load(open(exp_sel, encoding="utf-8")) if s["eligible_topics"]) if exp_sel.exists() else 0
    t_rate = len(t_surv) / t_called if t_called else 0.0                      # 호출당 06 상한 전 생존 QA
    hits = {}
    for t in faq_style.TOPICS:
        asked = [f for f in t_all if t in f.get("topics", [])]
        hits[t] = sum(t in faq_style.question_topics(f["question"]) for f in asked) / len(asked) if asked else None
    known = [h for h in hits.values() if h is not None]
    hit_avg = sum(known) / len(known) if known else 0.5
    hits = {t: (h if h is not None else hit_avg) for t, h in hits.items()}
    base_topic, base_total = Counter(), 0
    for sp, by_uid in units.items():
        p = FAQ_DIR / "checked" / f"petmint_{sp}_faq_checked_all.json"
        checked = json.load(open(p, encoding="utf-8")) if p.exists() else []
        surv = defaultdict(list)
        for f in _survivors(checked):
            surv[f["unit_id"]].append(f)
        finals = [f for f in checked if all(c["action"] != "drop" for c in f["checks"]) and f["unit_id"] in by_uid]
        base_total += len(finals)
        base_topic.update(t for f in finals for t in faq_style.question_topics(f["question"]))
        rates = sorted(len(surv[u]) / plan["base_gens"][sp][u] for u in by_uid if surv.get(u))
        median_rate = rates[len(rates) // 2] if rates else 1.0
        for uid, u in by_uid.items():
            w, tier, _ = rule_of(u)
            qs = surv.get(uid, [])
            rate = len(qs) / plan["base_gens"][sp][uid] if qs else median_rate
            share = Counter(t for f in qs for t in faq_style.question_topics(f["question"]))
            normal = rate * plan["gens"][sp][uid]
            tg = plan["topic_gens"][sp].get(uid, {})
            topic = t_rate * sum(tg.values())
            kept = min(faq_checks.weighted_cap(len(u["content"]), w), normal + topic)
            scale = kept / (normal + topic) if normal + topic else 0.0
            for t in faq_style.TOPICS:
                topic_tot[t] += scale * (normal * (share[t] / len(qs) if qs else 0.0) + t_rate * tg.get(t, 0) * hits[t])
            total += kept
            by_tier[(w, tier)][0] += 1
            by_tier[(w, tier)][1] += plan["gens"][sp][uid] + sum(tg.values())
            by_tier[(w, tier)][2] += kept
    return {"total": total, "topics": {t: topic_tot[t] / total if total else 0.0 for t in faq_style.TOPICS},
            "base_total": base_total, "base_topics": {t: base_topic[t] / base_total if base_total else 0.0 for t in faq_style.TOPICS},
            "tiers": {f"×{w:g} {tier}": {"units": n, "calls": c, "final_est": round(k)} for (w, tier), (n, c, k) in
                      sorted(by_tier.items(), key=lambda kv: -kv[0][0])},
            "topic_round_basis": {"exp_rows": len(t_all), "exp_survivors": len(t_surv), "exp_units_called": t_called,
                                  "per_call": round(t_rate, 2), "hit": {t: round(h, 2) for t, h in hits.items()}}}


def render_estimate(est: dict) -> str:
    from data import faq_style
    L = ["예상 최종 QA(06 후, 근사): %.0f건 (기존 전량, 지금 단위 기준 %d건)" % (est["total"], est["base_total"]), "",
         "| 묶음 | 단위 | 생성 호출 | 예상 최종 QA |", "|---|---|---|---|"]
    L += [f"| {k} | {v['units']} | {v['calls']} | {v['final_est']} |" for k, v in est["tiers"].items()]
    L += ["", "| 주제 | 기존 전량(지금 단위) | 적용 후 예상 |", "|---|---|---|"]
    L += [f"| {t} | {est['base_topics'][t]:.1%} | {est['topics'][t]:.1%} |" for t in faq_style.TOPICS]
    b = est["topic_round_basis"]
    L += ["", f"주제 회차 기준값(실험 C v2C-T r2, V2C 프롬프트): {b['exp_units_called']}단위 호출 → {b['exp_rows']}건 생성, "
              f"06 상한 전 생존 {b['exp_survivors']}건(호출당 {b['per_call']}) | 지정 주제가 질문에 나온 비율 {b['hit']}",
          "표본이 21건이라 주제 회차 몫은 크게 흔들릴 수 있다. 06 후 실제 분포는 rebuild 로그(check 단계 끝)에 찍힌다."]
    return "\n".join(L)


def main(argv=None):
    print("## 규칙 검증 — 초안 표 '현재 최종 QA'(checked/final 2026-10-13)와 같은 대상을 고르는가")
    bad = 0
    for name, draft, got in check_against_draft():
        mark = "" if draft == got else "  ← 다름"
        bad += draft != got
        print(f"  {got:5d} / 초안 {draft:5d}  {name}{mark}")
    print("  전부 일치" if not bad else f"  {bad}개 다름 — 규칙 확인 필요")
    from data import faq_generate
    plan, units = faq_generate.plan_from_data()
    print()
    print(faq_generate.render_plan(plan))
    print()
    print(render_estimate(estimate(plan, units)))


if __name__ == "__main__":
    sys.exit(main())

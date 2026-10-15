"""
faq_style.py
05 FAQ 질문의 성질(라벨 누출·상황형·주제)을 재는 정의와, 실험 C(2026-10-14, 05 질문 프롬프트 개편) 비교 리포트.

정의를 한곳에 둔다 — 05는 TOPIC_SRC로 단위마다 지정할 주제를 고르고, 리포트는 같은 정의로 질문을 센다.
기존 측정과 맞춘 값(06 checked_all 13,760건 / 최종 5,343건, 2026-10-14):
- LABEL_LEAK: 21.2% — '약관|특약'만 19.0%(사용자 측정 '약관 명칭 포함' 18%)에 조문 번호(제N조)·별표를 더한 정의
- TOPIC_Q(최종 기준): 가입 나이 1.4 / 기왕증 0.5 / 자기부담금 9.5 / 면책·보장개시 5.1 / 보장 제외 3.0%
  (topic_weights 초안 1.5 / 1.1 / 9.5 / 3.9 / 4.6과 비슷 — 정규식이라 근사치다)
- SITUATIONAL: 1.13%(155건, 최종 통과 66) — 사용자 측정 1.1%(149건, 통과 59)와 같은 수준. 리포트에 판정 예시를 함께 찍는다.

실행: python -m data.faq_style data/faq/exp_c/v1 data/faq/exp_c/v2A data/faq/exp_c/v2B
      실험 C-2(V2C): ... data/faq/exp_c/v2B data/faq/exp_c/v2C data/faq/exp_c/v2C-T (기존 설정과 같은 표에 나온다)
      (각 폴더 = 05 실험 C 출력 + 06을 EXPERIMENT로 돌린 checked/) → data/review/exp_c_compare_<날짜시각>.md
"""

import ast
import json
import re
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
FAQ_DIR = PROJECT_DIR / "data" / "faq"
REVIEW_DIR = PROJECT_DIR / "data" / "review"

LABEL_LEAK = re.compile(r"제\s*\d+\s*조|약관|특약|별표")
# 화자가 자기 반려동물·자기 상황을 말하는 질문(1인칭 표지 + 상황 서술 연결어미)
SITUATIONAL = re.compile(r"(?<![가-힣])(?:제가|저는|저희|저의|제\s?(?:강아지|고양이|반려견|반려묘|아이|개)|내가|"
                         r"우리\s?(?:집|아이|강아지|고양이|애|개|냥이|반려))|키우(?:는|고)|"
                         r"(?:했|됐|았|었|받았|갔|생겼)는데")

TOPICS = ["가입 나이", "기왕증", "자기부담금", "면책·보장개시", "보장 제외"]
TOPIC_Q = {
    "가입 나이": re.compile(r"가입\s?(?:가능\s?)?(?:나이|연령)|나이|연령|만\s?\d+\s?세|생후"),
    "기왕증": re.compile(r"기왕증|가입\s?전|이전부터|이미\s?(?:앓|있던|진단)|선천|유전"),
    "자기부담금": re.compile(r"자기부담|공제금액|본인부담"),
    "면책·보장개시": re.compile(r"면책|보장\s?개시|책임\s?개시|대기\s?기간|부담보|\d+\s?일\s?이내|\d+\s?일이\s?지나"),
    "보장 제외": re.compile(r"보장\s?(?:에서\s?)?제외|보상하지\s?않|지급하지\s?않|보장(?:이)?\s?안\s?되|보장되지\s?않|보장받을\s?수\s?없"),
}
# 원문 쪽 — 이 단위가 그 주제에 답할 수 있는가. 원문에 없는 주제를 지정하면 지어내기(fabricated)를 부른다.
TOPIC_SRC = {
    "가입 나이": re.compile(r"반려동물의?\s?나이|가입\s?(?:가능\s?)?나이|생후"),     # '만 65세 이상의 계약자'(사람 나이)는 뺀다
    "기왕증": re.compile(r"기왕증|(?<!재)가입\s?전|계약\s?이전부터|이전에\s?발생|선천|유전"),
    "자기부담금": re.compile(r"자기부담|공제금액"),
    "면책·보장개시": re.compile(r"면책|보장개시|책임개시|부담보"),                      # 'N일 이내'만으로는 세지 않는다(청약 철회 15일 등)
    "보장 제외": re.compile(r"보험금을\s?지급하\s?지\s?않|보상하지\s?않|보장하지\s?않"),  # '이자를 지급하지 않' 같은 절차 문장은 뺀다
}
JUDGE_TYPES = ["incomplete", "fabricated", "clause_mix", "reversal", "wrong_value", "wrong_term", "question_quality"]
POST_JUDGE_CHECKS = {"judge", "judge_fail", "judge_truncated", "duplicate", "unit_cap"}     # 심판 이후 단계


def has_label_leak(q: str) -> bool:
    return bool(LABEL_LEAK.search(q))


def is_situational(q: str) -> bool:
    return bool(SITUATIONAL.search(q))


def question_topics(q: str) -> list[str]:
    return [t for t in TOPICS if TOPIC_Q[t].search(q)]


def eligible_topics(content: str) -> list[str]:
    return [t for t in TOPICS if TOPIC_SRC[t].search(content)]


def judge_types(f: dict) -> list[str]:
    """06 checks의 judge 상세("['incomplete', ...] 이유")에서 유형 목록"""
    out = []
    for c in f.get("checks", []):
        if c["check"] == "judge":
            m = re.match(r"(\[.*?\])", c["detail"])
            try:
                out += ast.literal_eval(m.group(1)) if m else []
            except (ValueError, SyntaxError):
                pass
    return out


def style_stats(questions: list[str]) -> dict:
    n = len(questions) or 1
    topics = Counter(t for q in questions for t in question_topics(q))
    return {"n": len(questions),
            "label_leak": sum(map(has_label_leak, questions)) / n,
            "situational": sum(map(is_situational, questions)) / n,
            "q_len_median": statistics.median(len(q) for q in questions) if questions else 0,
            "topics": {t: topics[t] / n for t in TOPICS}}


def judge_stats(checked: list[dict]) -> dict:
    """checked: 06 checked_all 레코드. 심판 통과율 = 결정적 검사를 통과해 심판을 받은 QA 중 judge drop이 아닌 비율"""
    judged = [f for f in checked
              if not any(c["action"] == "drop" and c["check"] not in POST_JUDGE_CHECKS for c in f["checks"])]
    judge_drop = [f for f in judged if any(c["check"] == "judge" for c in f["checks"])]
    det_drop = Counter(c["check"] for f in checked for c in f["checks"]
                       if c["action"] == "drop" and c["check"] not in POST_JUDGE_CHECKS)
    return {"n": len(checked), "judged": len(judged),
            "judge_pass": 1 - len(judge_drop) / len(judged) if judged else 0,
            "final_pass": sum(f["decision"] != "drop" for f in checked) / len(checked) if checked else 0,
            "judge_types": Counter(t for f in judge_drop for t in judge_types(f)),
            "det_drop": det_drop}


def _rounds(d: Path, species: str) -> dict[int, list[dict]]:
    out = {}
    for p in d.glob(f"petmint_{species}_faq_round*.json"):
        m = re.fullmatch(rf"petmint_{species}_faq_round(\d+)\.json", p.name)
        if m:
            out[int(m.group(1))] = json.load(open(p, encoding="utf-8"))
    return dict(sorted(out.items()))


def _failures(d: Path, species: str, r: int) -> list[dict]:
    p = d / f"petmint_{species}_faq_round{r}_failures.json"
    return json.load(open(p, encoding="utf-8")) if p.exists() else []


def load_config(d: Path, species: str = "강아지") -> list[dict]:
    """실험 폴더 하나 → 라운드별 행. checked가 있으면 라운드별로 나눠 심판 통계를 붙인다"""
    checked_path = d / "checked" / f"petmint_{species}_faq_checked_all.json"
    checked = json.load(open(checked_path, encoding="utf-8")) if checked_path.exists() else None
    tokens_path = d / "prompt_tokens.json"
    tokens = json.load(open(tokens_path, encoding="utf-8")) if tokens_path.exists() else {}
    rows = []
    for r, qas in _rounds(d, species).items():
        fails = _failures(d, species, r)
        kinds = Counter(q.get("gen_kind", "normal") for q in qas)
        row = {"name": f"{d.name} r{r}" + (f" ({'/'.join(kinds)})" if kinds else ""),
               "units": len({q["unit_id"] for q in qas}),
               "parse_fail": sum(f.get("status") == "parse_fail" for f in fails),
               "rejected_05": sum(len(f.get("rejected", [])) for f in fails),
               "retries": sum(max(len(f.get("raw_outputs", [])) - 1, 0) for f in fails if f.get("status") == "ok"),
               "style": style_stats([q["question"] for q in qas])}
        tk = tokens.get(str(r))
        if tk:
            s = sorted(tk)
            row["tokens"] = (s[len(s) // 2], s[int(len(s) * 0.9)], s[-1])
        if checked is not None:
            row["checked"] = [f for f in checked if f.get("round") == r]
            row["judge"] = judge_stats(row["checked"])
        rows.append(row)
    return rows


def reference_row(unit_ids: set[str], species: str = "강아지") -> dict | None:
    """같은 단위의 기존 전량 데이터 생성 라운드 1(v1 프롬프트, temperature 0.5) — 추가 생성 없이 쓰는 참고값"""
    p = FAQ_DIR / "checked" / f"petmint_{species}_faq_checked_all.json"
    if not p.exists():
        return None
    checked = [f for f in json.load(open(p, encoding="utf-8")) if f["round"] == 1 and f["unit_id"] in unit_ids]
    return {"name": "기존 전량 r1 (같은 단위)", "units": len({f["unit_id"] for f in checked}), "checked": checked,
            "style": style_stats([f["question"] for f in checked]), "judge": judge_stats(checked)}


def whole_data_row() -> tuple[dict, list[str]]:
    """기존 전량 데이터 전체(두 종) — 정의가 기존 측정과 맞는지 보는 기준선 + 상황형 판정 예시"""
    checked = []
    for sp in ("강아지", "고양이"):
        p = FAQ_DIR / "checked" / f"petmint_{sp}_faq_checked_all.json"
        if p.exists():
            checked += json.load(open(p, encoding="utf-8"))
    qs = [f["question"] for f in checked]
    sit = [q for q in qs if is_situational(q)]
    examples = sit[:: max(len(sit) // 10, 1)][:10]
    return {"name": "기존 전량 전체(두 종)", "units": len({f["unit_id"] for f in checked}),
            "style": style_stats(qs), "judge": judge_stats(checked)}, examples


def _pct(x: float) -> str:
    return f"{x:.1%}"


def render(rows: list[dict], examples: list[str], config_examples: dict[str, list[str]]) -> str:
    L = ["# 실험 C — 05 질문 프롬프트 비교", "", f"생성: {datetime.now():%Y-%m-%d %H:%M}", "",
         "## 질문 성질", "",
         "| 설정 | 단위 | QA | 라벨 누출 | 상황형 | 질문 길이 중앙 | " + " | ".join(TOPICS) + " |",
         "|---|---|---|---|---|---|" + "---|" * len(TOPICS)]
    for r in rows:
        s = r["style"]
        L.append(f"| {r['name']} | {r['units']} | {s['n']} | {_pct(s['label_leak'])} | {_pct(s['situational'])} | "
                 f"{s['q_len_median']} | " + " | ".join(_pct(s["topics"][t]) for t in TOPICS) + " |")
    L += ["", "## 생성 안정성 (05)", "", "| 설정 | 파싱 실패 단위 | 재시도 후 성공 | 05 검증 탈락 QA | 입력 토큰 중앙/p90/최대 |",
          "|---|---|---|---|---|"]
    for r in rows:
        if "parse_fail" in r:
            tk = "/".join(map(str, r["tokens"])) if r.get("tokens") else "(기록 없음)"
            L.append(f"| {r['name']} | {r['parse_fail']} | {r['retries']} | {r['rejected_05']} | {tk} |")
    L += ["", "## 06 심판", "",
          "| 설정 | QA | 심판 받음 | 심판 통과율 | 06 최종 통과율 | " + " | ".join(JUDGE_TYPES) + " | 결정적 검사 버림 |",
          "|---|---|---|---|---|" + "---|" * len(JUDGE_TYPES) + "---|"]
    for r in rows:
        j = r.get("judge")
        if not j:
            L.append(f"| {r['name']} | (06 결과 없음) |")
            continue
        L.append(f"| {r['name']} | {j['n']} | {j['judged']} | {_pct(j['judge_pass'])} | {_pct(j['final_pass'])} | "
                 + " | ".join(str(j["judge_types"].get(t, 0)) for t in JUDGE_TYPES) + f" | {dict(j['det_drop'])} |")
    # 단위별로 짝지어 본다 — 구어체 질문이 같은 단위에서 clause_mix를 늘렸는가
    unit_rows = [r for r in rows if r.get("checked") is not None and r["name"] != "기존 전량 전체(두 종)"]
    if unit_rows:
        uids = sorted({f["unit_id"] for r in unit_rows for f in r["checked"]})
        L += ["", "## 단위별 심판 탈락 — clause_mix / 탈락 / QA", "",
              "| 단위 | " + " | ".join(r["name"] for r in unit_rows) + " |", "|---|" + "---|" * len(unit_rows)]
        for uid in uids:
            cells = []
            for r in unit_rows:
                fs_ = [f for f in r["checked"] if f["unit_id"] == uid]
                drop = [f for f in fs_ if any(c["check"] == "judge" for c in f["checks"])]
                cm = sum("clause_mix" in judge_types(f) for f in drop)
                cells.append(f"{cm} / {len(drop)} / {len(fs_)}" if fs_ else "-")
            L.append(f"| {uid.split('|', 1)[1].replace('|', ' · ')} | " + " | ".join(cells) + " |")
    L += ["", "## 해석 시 주의", "",
          "- 설정당 QA가 약 80건이라 통과율 차이가 ±10%p 안쪽이면 구분할 수 없다.",
          "- 의료비 제1조 비중이 커서 기존 전체 39%가 아니라 v1 대조군·'기존 전량 r1(같은 단위)'과 비교한다.",
          "- 06 최종 통과율에는 중복·단위 상한이 들어간다. 라운드 1개라 기존(10라운드)보다 중복이 적다 — 심판 통과율을 주 지표로 본다.",
          "- 상황형·주제는 정규식 판정이다. 아래 예시로 정의를 확인할 것.",
          "", "## 상황형 판정 예시 — 기존 전량 데이터", ""]
    L += [f"- {q}" for q in examples]
    for name, qs in config_examples.items():
        L += ["", f"## 질문 예시 — {name} (앞 15개)", ""] + [f"- {q}" for q in qs]
    return "\n".join(L) + "\n"


def main(argv=None):
    dirs = [Path(a) for a in (argv if argv is not None else sys.argv[1:])]
    rows, config_examples = [], {}
    base, examples = whole_data_row()
    rows.append(base)
    sel_path = FAQ_DIR / "exp_c" / "selection.json"
    if sel_path.exists():
        ref = reference_row({s["unit_id"] for s in json.load(open(sel_path, encoding="utf-8"))})
        if ref:
            rows.append(ref)
    for d in dirs:
        cfg_rows = load_config(d)
        rows += cfg_rows
        for r, qas in _rounds(d, "강아지").items():
            config_examples[f"{d.name} r{r}"] = [q["question"] for q in qas[:15]]
    md = render(rows, examples, config_examples)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = REVIEW_DIR / f"exp_c_compare_{datetime.now():%Y%m%d_%H%M}.md"
    out.write_text(md, encoding="utf-8")
    print(md)
    print("저장:", out)


if __name__ == "__main__":
    main()

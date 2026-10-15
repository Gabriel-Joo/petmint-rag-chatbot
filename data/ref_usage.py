"""
ref_usage.py
참조 조문 활용도 측정 — 다른 조 참조(rag_context.cross_article_refs)가 붙은 단위의 QA가 참조 내용을 실제로 쓰는가, 06에서 어떻게 걸러지는가.
05·06 산출물을 세기만 한다(모델 호출 없음, 참조 원문은 Milvus 조회). 2026-10-14 기존 전량 측정을 옮긴 것.

사용 판정(대략적 기준 — 바꿔 쓴 표현은 못 잡으므로 사용률은 하한에 가깝다):
- content: 다른 조 참조에만 있는 숫자(질문에 나온 숫자·단위 본문에 있는 숫자 제외)가 답변에 있거나,
           참조와 15자 이상 일치하는 구간(단위 본문에도 있는 구간 제외)이 있음
- mention: content는 아니고 참조 조번호만 언급
- none: 둘 다 아님
06: 심판 탈락률의 분모는 심판을 받은 QA(중복·단위 상한으로 심판 전에 빠진 것 제외).

질문 노출: 질문에 "다른 조항"·"함께 적용"·조문 번호(제N조)가 있음. 형식 실패: 05에서 parse_fail·all_rejected로 QA가 0개인 호출.
참조 회차(gen_kind "ref", 05 faq_generate)가 든 폴더는 전체·일반 회차만·참조 회차만 세 줄로 나눠 보여 준다.

실행: python -m data.ref_usage exp_r/v1 exp_r/v1ref                — 폴더(data/faq 기준 또는 절대 경로, 안에 checked/)
      python -m data.ref_usage . exp_r/v1 exp_r/v1ref --units=exp_r/selection.json
                                                                   — 기존 전량(.)도 파일럿 단위로 좁혀 같은 표에
      인자 없으면 기존 전량(.)의 다른 조 단위 전체 → data/review/ref_usage_<날짜시각>.md
참조 회차 채택 기준(제안, 대조군 = 참조 회차가 없는 첫 폴더): 참조 회차 QA의 참조 내용 사용 ≥ 50%, 질문 노출 ≤ 5%,
형식 실패 ≤ 5%, 심판 탈락률 대조군 대비 +5%p 이내. 앞서 기각한 v1r(일반 회차 3개 중 1개) 결과: data/review/ref_usage_20261014_2031.md
"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from data import faq_units, rag_context
from data.rag_context import _flat_cite, _longest_shared

PROJECT_DIR = Path(__file__).resolve().parent.parent
FAQ_DIR = PROJECT_DIR / "data" / "faq"
REVIEW_DIR = PROJECT_DIR / "data" / "review"
SPAN_MIN = 15
REF_ROUND_START = 201      # faq_generate.REF_ROUND_START — 실패 기록(_failures.json)은 라운드 번호로만 회차를 안다
TARGET_CONTENT = 0.50
MAX_LEAK = 0.05
MAX_FORMAT_FAIL = 0.05
MAX_DROP_UP = 0.05
LEAK = re.compile(r"다른\s*조항|함께\s*적용|제\s*\d+\s*조")
KINDS = {None: "", "normal": " (일반 회차만)", "ref": " (참조 회차만)"}
NUM = re.compile(r"\d[\d,.]*\s*(?:%|퍼센트|만\s*원|천\s*원|원|일|년|개월|세|회|시간|주|배|급|등급)")
TAGS = ("incomplete", "clause_mix", "reversal", "wrong_value", "fabricated", "wrong_term", "question_quality")


def _nums(t: str) -> set[str]:
    return {re.sub(r"[\s,]", "", m) for m in NUM.findall(t or "")}


def _body(answer: str) -> str:
    return re.sub(r"\s*근거\s*:.*$", "", answer, flags=re.DOTALL).strip()


def usage(qa: dict, unit: dict, cross: list[dict]) -> str:
    b, content = _body(qa["answer"]), unit["content"]
    unit_flat = _flat_cite(content)
    for r in cross:
        rc = r.get("content") or ""
        if (_nums(b) & (_nums(rc) - _nums(content))) - _nums(qa["question"]) or _longest_shared(b, rc, unit_flat, SPAN_MIN) >= SPAN_MIN:
            return "content"
    if any(re.search(rf"제\s*{r['article_num']}\s*조(?!의)", b) for r in cross if r.get("article_num") is not None):
        return "mention"
    return "none"


def judged(qa: dict) -> bool:
    """심판을 받았는가 — 통과·보류했거나 심판 기록이 있음(중복·단위 상한 등으로 심판 전에 빠진 것은 아님)"""
    return qa["decision"] != "drop" or any(c["check"] == "judge" for c in qa["checks"])


def judge_tags(qa: dict) -> set[str]:
    return {t for c in qa["checks"] if c["check"] == "judge" and c["action"] == "drop"
            for t in re.findall(r"'([a-z_]+)'", c.get("detail", "")[:80])}


def resolve_dir(arg: str) -> Path:
    p = Path(arg)
    return p if p.is_absolute() else (FAQ_DIR / arg).resolve()


class Units:
    """(종, unit_id) → (단위, 다른 조 참조). 필요한 단위만 참조를 붙인다"""
    def __init__(self):
        self.builder = rag_context.ContextBuilder()
        self.by_uid = {sp: {faq_units.unit_id(u): u for u in faq_units.make_units(self.builder.chunks[sp])}
                       for sp in ("강아지", "고양이")}
        self._cross = {}

    def get(self, species: str, uid: str):
        if (species, uid) not in self._cross:
            u = self.by_uid[species].get(uid)
            refs = self.builder.resolve_references(u, species, source_chunks=u["records"]) if u else []
            self._cross[(species, uid)] = (u, rag_context.cross_article_refs(u, refs)[0] if u else [])
        return self._cross[(species, uid)]


def _is_ref(qa: dict) -> bool:
    return qa.get("gen_kind") == "ref"


def format_failures(folder: Path, units: Units, only, kind: str | None) -> tuple[int, int]:
    """(QA 0개 호출, 호출 수) — 다른 조 참조 단위만. 05 라운드 파일 + _failures.json으로 센다"""
    fail = calls = 0
    for path in folder.glob("petmint_*_faq_round*_failures.json"):
        species, r = path.name.split("_")[1], int(re.search(r"round(\d+)_failures", path.name).group(1))
        if kind is not None and (r >= REF_ROUND_START) != (kind == "ref"):
            continue
        ok = {qa["unit_id"] for qa in json.load(open(path.with_name(path.name.replace("_failures", "")), encoding="utf-8"))}
        bad = {f["unit_id"] for f in json.load(open(path, encoding="utf-8")) if f["status"] in ("parse_fail", "all_rejected")}
        for uid in ok | bad:
            if (only is None or (species, uid) in only) and units.get(species, uid)[1]:
                calls += 1
                fail += uid in bad and uid not in ok
    return fail, calls


def measure(folder: Path, units: Units, only: set[tuple[str, str]] | None, kind: str | None = None) -> dict:
    """kind: None = 전체, "normal" = 일반·주제 회차, "ref" = 참조 회차만"""
    rows = []
    for path in sorted((folder / "checked").glob("petmint_*_faq_checked_all.json")):
        species = path.name.split("_")[1]
        for qa in json.load(open(path, encoding="utf-8")):
            if only is not None and (species, qa["unit_id"]) not in only:
                continue
            if kind is not None and _is_ref(qa) != (kind == "ref"):
                continue
            unit, cross = units.get(species, qa["unit_id"])
            if unit is None or not cross:
                continue
            rows.append({"qa": qa, "species": species, "use": usage(qa, unit, cross), "judged": judged(qa),
                         "drop": any(c["check"] == "judge" and c["action"] == "drop" for c in qa["checks"]),
                         "tags": judge_tags(qa), "leak": bool(LEAK.search(qa["question"]))})
    assert rows, f"{folder}: 다른 조 참조 단위 QA가 없다(checked/ 확인)"
    j = [r for r in rows if r["judged"]]
    calls = defaultdict(bool)
    for r in rows:
        calls[(r["species"], r["qa"]["unit_id"], r["qa"].get("round"))] |= r["use"] == "content"
    fmt_fail, fmt_calls = format_failures(folder, units, only, kind)
    name = str(folder.relative_to(FAQ_DIR)) if folder.is_relative_to(FAQ_DIR) else str(folder)
    return {
        "name": name + KINDS[kind], "kind": kind, "has_ref": any(_is_ref(r["qa"]) for r in rows),
        "rows": rows, "n": len(rows), "units": len({(r["species"], r["qa"]["unit_id"]) for r in rows}),
        "use": Counter(r["use"] for r in rows), "calls": len(calls), "calls_content": sum(calls.values()),
        "leak": sum(r["leak"] for r in rows), "fmt_fail": fmt_fail, "fmt_calls": fmt_calls,
        "judged": len(j), "drop": sum(r["drop"] for r in j),
        "tags": Counter(t for r in j if r["drop"] for t in r["tags"]),
        "kept": sum(r["qa"]["decision"] != "drop" for r in rows),
        "kept_content": sum(r["qa"]["decision"] != "drop" and r["use"] == "content" for r in rows),
        "by_use": {u: (sum(r["judged"] for r in rows if r["use"] == u),
                       sum(r["drop"] for r in rows if r["use"] == u and r["judged"])) for u in ("content", "mention", "none")},
    }


def pct(a: int, b: int) -> str:
    return f"{a / b:.1%}" if b else "-"


def render(results: list[dict], only_note: str) -> str:
    L = [f"# 참조 조문 활용도 — {datetime.now():%Y-%m-%d %H:%M}", "", only_note, "",
         "| 폴더 | 단위 | QA | 참조 내용 사용 | 조번호만 | 안 씀 | 호출당 사용 QA ≥1 | 질문 노출 | 형식 실패(호출) | 심판 탈락 | 06 통과 | 통과 중 내용 사용 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in results:
        u = m["use"]
        L.append(f"| {m['name']} | {m['units']} | {m['n']} | {u['content']} ({pct(u['content'], m['n'])}) | "
                 f"{u['mention']} ({pct(u['mention'], m['n'])}) | {u['none']} ({pct(u['none'], m['n'])}) | "
                 f"{m['calls_content']}/{m['calls']} ({pct(m['calls_content'], m['calls'])}) | "
                 f"{m['leak']} ({pct(m['leak'], m['n'])}) | {m['fmt_fail']}/{m['fmt_calls']} ({pct(m['fmt_fail'], m['fmt_calls'])}) | "
                 f"{m['drop']}/{m['judged']} ({pct(m['drop'], m['judged'])}) | {m['kept']} | {m['kept_content']} |")
    L += ["", "## 심판 탈락 사유 (심판 받은 QA 대비)", "", "| 폴더 | " + " | ".join(TAGS) + " |", "|---" * (len(TAGS) + 1) + "|"]
    for m in results:
        L.append(f"| {m['name']} | " + " | ".join(pct(m["tags"][t], m["judged"]) for t in TAGS) + " |")
    L += ["", "## 사용 여부별 심판 탈락률", "", "| 폴더 | 내용 사용 | 조번호만 | 안 씀 |", "|---|---|---|---|"]
    for m in results:
        L.append(f"| {m['name']} | " + " | ".join(f"{d}/{n} ({pct(d, n)})" for n, d in (m["by_use"][u] for u in ("content", "mention", "none"))) + " |")
    base = next((m for m in results if m["kind"] is None and not m["has_ref"]), None)
    for ref in [m for m in results if m["kind"] == "ref"]:
        content, leak = ref["use"]["content"] / ref["n"], ref["leak"] / ref["n"]
        fmt = ref["fmt_fail"] / ref["fmt_calls"] if ref["fmt_calls"] else 0.0
        checks = [(f"참조 내용 사용 ≥ {TARGET_CONTENT:.0%}", f"{content:.1%}", content >= TARGET_CONTENT),
                  (f"질문 노출 ≤ {MAX_LEAK:.0%}", f"{leak:.1%}", leak <= MAX_LEAK),
                  (f"형식 실패 ≤ {MAX_FORMAT_FAIL:.0%}", f"{fmt:.1%}", fmt <= MAX_FORMAT_FAIL)]
        if base:
            drop_up = ref["drop"] / ref["judged"] - base["drop"] / base["judged"]
            checks.append((f"심판 탈락률 {base['name']} 대비 ≤ +{MAX_DROP_UP:.0%}p", f"{drop_up:+.1%}p", drop_up <= MAX_DROP_UP))
        L += ["", f"## 참조 회차 채택 기준(제안) — {ref['name']}", ""]
        L += [f"- {'통과' if ok else '미달'}: {name} — {val}" for name, val, ok in checks]
        L.append(f"- 참고: 참조 회차 호출당 06 통과 + 참조 내용 사용 QA {ref['kept_content']}/{ref['fmt_calls']} "
                 f"({ref['kept_content'] / max(ref['fmt_calls'], 1):.2f}건) — 전량의 회차 수(REF_ROUNDS)를 정할 때 쓴다")
    last = results[-1]
    for title, pick in (("내용 사용 QA", lambda r: r["use"] == "content"), ("안 씀·조번호만 QA", lambda r: r["use"] != "content"),
                        ("질문 노출", lambda r: r["leak"])):
        L += ["", f"## 예시 — {last['name']} ({title}, 앞 8건)", ""]
        for r in [r for r in last["rows"] if pick(r)][:8]:
            qa = r["qa"]
            L += [f"- `{qa['unit_id']}` {qa['decision']} {sorted(r['tags']) or ''} ({r['use']})",
                  f"  - Q: {qa['question']}", f"  - A: {_body(qa['answer'])}"]
    return "\n".join(L) + "\n"


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    opts = dict(a[2:].split("=", 1) for a in args if a.startswith("--") and "=" in a)
    folders = [resolve_dir(a) for a in args if not a.startswith("--")] or [FAQ_DIR]
    only, note = None, "범위: 다른 조 참조가 있는 단위 전체"
    if "units" in opts:
        sel_path = resolve_dir(opts["units"])
        only = {(s["species"], s["unit_id"]) for s in json.load(open(sel_path, encoding="utf-8"))}
        note = f"범위: {sel_path.relative_to(FAQ_DIR)}의 {len(only)}단위"
    units = Units()
    results = []
    for f in folders:
        results.append(measure(f, units, only))
        if results[-1]["has_ref"]:
            results += [measure(f, units, only, "normal"), measure(f, units, only, "ref")]
    text = render(results, note)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = REVIEW_DIR / f"ref_usage_{datetime.now():%Y%m%d_%H%M}.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print("저장:", out)


if __name__ == "__main__":
    main()

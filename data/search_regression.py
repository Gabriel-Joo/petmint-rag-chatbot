"""
search_regression.py
검색 회귀 테스트 — 검색(search_engine·search_scope·rag_context.search_with_graph)을 고칠 때마다 돌린다.
질문 세트: data/eval/search_regression.json (섹션별로 고르게 + 등급 언급이 다른 섹션을 지우던 결함 겨냥 + 가입 제외 확인).

예전 검증 질문은 한도·등급 질문에 쏠려 있어서, 등급 필터가 등급 없는 청크(보통약관·일반조항·별표·안내·법규)를
통째로 지우는 결함이 드러나지 않았다(2026-10-13). 그래서 범주별로 따로 집계한다 — 전체 평균에 묻히지 않게.

- check_static: GPU·Milvus 없이 세트 자체를 검사(gold 실재, evidence가 gold 청크에 있음, scope 이름 실재)
- run: search_fn으로 전 문항 검색 → 문항별 gold 순위와 범위 위반, 범주별 hit@1/3/5·MRR
- legacy_search_fn: backups/pre_search_scope_20261013의 옛 검색으로 같은 세트를 돌린다(결함 재현용 기준선)
- check_scope_consistency: scope.allows(BM25)와 Milvus 식(dense)이 같은 청크 집합을 고르는지
"""

import importlib.util
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from data.search_scope import MEDICAL_SECTIONS, OPTIONAL_SECTIONS, SearchScope

BASE_DIR = Path(__file__).parent
CASES_PATH = BASE_DIR / "eval" / "search_regression.json"
RESULTS_DIR = BASE_DIR / "eval" / "results"
LEGACY_DIR = BASE_DIR.parent / "backups" / "pre_search_scope_20261013"


def _flat(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def scope_of(case: dict) -> SearchScope:
    s, sp = case["scope"], case["species"]
    if s["kind"] == "unrestricted":
        return SearchScope.unrestricted(sp)
    if s["kind"] == "from_query":
        return SearchScope.from_query(case["query"], sp)
    if s["kind"] == "policies":
        return SearchScope.for_policies(sp, s["policies"])
    raise ValueError(f"{case['id']}: 알 수 없는 scope kind {s['kind']}")


def matches(r: dict, gold: dict) -> bool:
    """검색 결과(또는 청크)가 gold 항목에 해당하는가. gold의 article_num None = 그 섹션(안내·별표 등) 아무 청크"""
    if r.get("section") != gold["section"] or r.get("section_name") != gold["section_name"]:
        return False
    if gold.get("article_num") is not None and r.get("article_num") != gold["article_num"]:
        return False
    if gold.get("coverage_type") and r.get("coverage_type") != gold["coverage_type"]:
        return False
    return True


def check_static(cases: list[dict], chunks: dict[str, list[dict]]) -> list[str]:
    """세트 자체의 정합성. 위반 메시지 목록(빈 목록이면 통과)"""
    errors = []
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        errors.append("id 중복")
    for sp in MEDICAL_SECTIONS:
        names = {c.get("section_name") for c in chunks[sp]}
        listed = list(MEDICAL_SECTIONS[sp]) + [n for k, v in OPTIONAL_SECTIONS[sp].items() for n in (k, *v)]
        errors += [f"search_scope의 {sp} 섹션명이 청크에 없음: {n}" for n in listed if n not in names]
    for case in cases:
        sp, cid = case["species"], case["id"]
        try:
            scope = scope_of(case)
        except ValueError as e:
            errors.append(f"{cid}: scope 생성 실패 — {e}")
            continue
        names = {c.get("section_name") for c in chunks[sp]}
        for p in case["scope"].get("policies", []):
            if p["section_name"] not in names:
                errors.append(f"{cid}: 가입 특약명이 청크에 없음 — {p['section_name']}")
        for gd in case["gold"]:
            rows = [c for c in chunks[sp] if matches(c, gd)]
            label = f"{gd['section']}|{gd['section_name']}|{gd.get('article_num')}|{gd.get('coverage_type')}"
            if not rows:
                errors.append(f"{cid}: gold 청크 없음 — {label}")
                continue
            if gd.get("evidence") and _flat(gd["evidence"]) not in _flat(" ".join(r["content"] for r in rows)):
                errors.append(f"{cid}: evidence '{gd['evidence']}'가 gold에 없음 — {label}")
            if not any(scope.allows(r) for r in rows):
                errors.append(f"{cid}: gold가 이 문항의 검색 범위 밖 — {label}")
    return errors


def new_search_fn(engine, builder):
    """현재 검색: search_fn(query, scope, top_k) -> 결과 목록"""
    from data import rag_context
    return lambda query, scope, top_k: rag_context.search_with_graph(engine, builder, query, scope, top_k=top_k)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def legacy_search_fn(engine, builder, legacy_dir: Path = LEGACY_DIR):
    """수정 전 검색(질문 정규식 필터를 컬렉션 전체에 거는 방식)을 같은 모델·Milvus로 재현한다.
    모델을 다시 올리지 않도록 옛 SearchEngine 객체에 현재 엔진의 상태(모델·client·청크·BM25)를 그대로 넘긴다.
    옛 방식은 scope를 모르므로 policies 문항도 질문 문자열만으로 검색된다 — 범위 위반으로 드러난다."""
    old_se = _load_module("legacy_search_engine", legacy_dir / "search_engine.py")
    old_rc = _load_module("legacy_rag_context", legacy_dir / "rag_context.py")
    legacy = object.__new__(old_se.SearchEngine)
    legacy.__dict__.update(engine.__dict__)
    return lambda query, scope, top_k: old_rc.search_with_graph(legacy, builder, query, scope.species, top_k=top_k)


def _brief(r: dict) -> str:
    art = f"제{r['article_num']}조" if r.get("article_num") is not None else "-"
    return f"{r.get('section')}|{r.get('section_name')}|{art}|{r.get('coverage_type')}"


def run(search_fn, cases: list[dict], top_k: int = 5) -> dict:
    per_case = []
    for case in cases:
        scope = scope_of(case)
        results = search_fn(case["query"], scope, top_k)
        rank = next((i for i, r in enumerate(results, 1) if any(matches(r, gd) for gd in case["gold"])), None)
        per_case.append({
            "id": case["id"], "species": case["species"], "category": case["category"],
            "scope_kind": case["scope"]["kind"], "query": case["query"],
            "has_gold": bool(case["gold"]), "rank": rank,
            "out_of_scope": [_brief(r) for r in results if not scope.allows(r)],
            "top": [_brief(r) for r in results],
        })
    return {"created": datetime.now().isoformat(timespec="seconds"), "top_k": top_k,
            "summary": summarize(per_case), "cases": per_case}


def summarize(per_case: list[dict]) -> dict:
    groups = defaultdict(list)
    for p in per_case:
        groups[p["category"]].append(p)
        groups["(전체)"].append(p)
    out = {}
    for cat, ps in groups.items():
        graded = [p for p in ps if p["has_gold"]]
        n = len(graded)
        hit = lambda k: sum(1 for p in graded if p["rank"] and p["rank"] <= k)
        out[cat] = {"n": len(ps), "n_gold": n,
                    "hit@1": hit(1), "hit@3": hit(3), "hit@5": hit(5),
                    "mrr": round(sum(1 / p["rank"] for p in graded if p["rank"]) / n, 3) if n else None,
                    "out_of_scope_cases": sum(1 for p in ps if p["out_of_scope"])}
    return out


def print_summary(report: dict):
    print(f"{'범주':16s} {'문항':>4s} {'gold':>4s} {'@1':>4s} {'@3':>4s} {'@5':>4s} {'MRR':>6s} {'범위위반':>6s}")
    for cat, s in sorted(report["summary"].items(), key=lambda kv: (kv[0] == "(전체)", kv[0])):
        mrr = f"{s['mrr']:.3f}" if s["mrr"] is not None else "-"
        print(f"{cat:16s} {s['n']:4d} {s['n_gold']:4d} {s['hit@1']:4d} {s['hit@3']:4d} {s['hit@5']:4d} {mrr:>6s} {s['out_of_scope_cases']:6d}")
    misses = [p for p in report["cases"] if (p["has_gold"] and not p["rank"]) or p["out_of_scope"]]
    for p in misses:
        why = "범위 위반 " + str(len(p["out_of_scope"])) if p["out_of_scope"] else "gold 없음"
        print(f"  ✗ {p['id']} [{p['category']}/{p['scope_kind']}] {p['query']} — {why}")


def save(report: dict, tag: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"search_regression_{datetime.now():%Y%m%d_%H%M}_{tag}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def diff(prev: dict, cur: dict) -> dict:
    """직전 결과 대비 새로 틀린 문항 / 새로 맞힌 문항(top_k 안 gold 여부 + 범위 위반 기준)"""
    ok = lambda p: (not p["has_gold"] or p["rank"] is not None) and not p["out_of_scope"]
    before = {p["id"]: ok(p) for p in prev["cases"]}
    now = {p["id"]: ok(p) for p in cur["cases"]}
    return {"newly_failed": [i for i in now if before.get(i) and not now[i]],
            "newly_passed": [i for i in now if before.get(i) is False and now[i]]}


def check_scope_consistency(engine, scopes: list[SearchScope]) -> list[str]:
    """scope.allows로 고른 청크 수 == Milvus filter로 고른 행 수. dense와 BM25가 같은 범위를 보는지"""
    from data.search_engine import COLLECTION_NAMES
    errors = []
    for scope in scopes:
        n_allows = sum(1 for c in engine.chunks[scope.species] if scope.allows(c))
        rows = engine.client.query(collection_name=COLLECTION_NAMES[scope.species],
                                   filter=scope.milvus_expr() or "chunk_index >= 0",
                                   output_fields=["chunk_index"], limit=16384)
        if n_allows != len(rows):
            errors.append(f"{scope.describe()}: allows {n_allows} ≠ Milvus {len(rows)}")
    return errors

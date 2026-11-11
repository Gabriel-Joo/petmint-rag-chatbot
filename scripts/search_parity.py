"""
scripts/search_parity.py
search-service 전후 대조 — model-service 분리(2026-11-11) 때 만들었다. 같은 질문을 던져 응답 본문을 그대로 저장하고,
두 저장본을 값으로 비교한다 — 결과 순서 · 청크 필드 · 리랭커 점수 · 벡터가 모두 같아야 한다. 점수 · 벡터는 JSON의 float를
파이썬 float로 읽어 == 로 본다(왕복 손실 없는 표기라 비트까지 같다는 뜻). 바이트로 보지 않는 이유: Milvus가 돌려주는 청크
필드의 키 순서가 호출마다 바뀐다(같은 서버에 두 번 던져도 391건 중 232건 본문이 달랐고, 값은 모두 같았다 — 2026-11-11).

  dump  --url http://192.168.122.1:8100 --out logs/parity/before.json
  diff  logs/parity/before.json logs/parity/after.json      → 다른 항목 수(0이면 종료 코드 0)

던지는 것
- /search: 검색 회귀 세트 약관 103 + 인사규정 26문항 × 설정 둘
  - prod: 운영 ConfigMap과 같다(질의 확장 · 사전 v2 · 1차 후보 50 · 약관만 variant v3 — app/services/retrieval.py와 같은 규칙)
  - base: 아무것도 붙이지 않은 기본
  top_k=200 — 리랭커가 매긴 후보 전부(운영의 top_k는 그 앞부분이다). 순서 · 점수 · 청크가 모두 본문에 있다
- /embed: 질문 129개를 하나씩(앱의 금액 되묻기와 같은 크기) + 약관 청크 색인 텍스트 256개를 64개씩(최대 묶음)
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import httpx

from data import search_regression as R
from data.search_engine import CHUNK_FILES, build_embedding_text

PROD = {"expand": True, "expand_dict": "v2", "pool_k": 50}
PROD_VARIANT = "v3"
VARIANT_SPECIES = ("강아지", "고양이")          # app/services/retrieval.py와 같다 — 인사규정에는 variant를 붙이지 않는다
TIMEOUT = httpx.Timeout(120, connect=3)


def _requests():
    cases = [("pet", c) for c in R.load_cases(R.CASES_PATH)] + [("hr", c) for c in R.load_cases(R.HR_CASES_PATH)]
    for name, c in cases:
        scope = R.scope_of(c)
        base = {"query": c["query"], "scope": scope.describe(), "top_k": 200, "candidate_k": 20}
        prod = base | PROD | ({"variant": PROD_VARIANT} if scope.species in VARIANT_SPECIES else {})
        yield f"search/{name}/{c['id']}/base", "/search", base
        yield f"search/{name}/{c['id']}/prod", "/search", prod
    for name, c in cases:
        yield f"embed/q/{name}/{c['id']}", "/embed", {"texts": [c["query"]]}
    chunks = json.loads(CHUNK_FILES["강아지"].read_text(encoding="utf-8"))[:256]
    texts = [build_embedding_text(c) for c in chunks]
    for i in range(0, len(texts), 64):
        yield f"embed/chunks/{i:03d}", "/embed", {"texts": texts[i:i + 64]}


def dump(url: str, out: Path):
    res = {}
    with httpx.Client(base_url=url.rstrip("/"), timeout=TIMEOUT) as cl:
        for key, path, body in _requests():
            r = cl.post(path, json=body)
            res[key] = {"status": r.status_code, "body": r.text}
            if r.status_code != 200:
                print(f"{key}: {r.status_code} {r.text[:200]}", file=sys.stderr)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"url": url, "results": res}, ensure_ascii=False), encoding="utf-8")
    bad = sum(v["status"] != 200 for v in res.values())
    digest = hashlib.sha256("".join(res[k]["body"] for k in sorted(res)).encode()).hexdigest()[:16]
    print(f"{out} — 요청 {len(res)} · 200 아님 {bad} · 본문 지문 {digest}")


def diff(a: Path, b: Path) -> int:
    ra, rb = (json.loads(p.read_text(encoding="utf-8"))["results"] for p in (a, b))
    keys = sorted(set(ra) | set(rb))
    bad = []
    for k in keys:
        if k not in ra or k not in rb or not _same(ra[k], rb[k]):
            bad.append(k)
    groups = {}
    for k in keys:
        g = "/".join(k.split("/")[:2])
        groups.setdefault(g, [0, 0])
        groups[g][0] += 1
        groups[g][1] += k in bad
    for g, (n, d) in groups.items():
        print(f"{g:16s} {n:4d}건 · 다름 {d}")
    for k in bad[:10]:
        print("다름:", k, _why(ra.get(k), rb.get(k)))
    print(f"합계 {len(keys)}건 · 다름 {len(bad)}")
    return len(bad)


def _same(x, y) -> bool:
    """상태가 같고, 본문을 JSON으로 읽은 값이 같다(리스트는 순서까지, 딕셔너리는 키 순서 무시, float는 ==)"""
    if x["status"] != y["status"]:
        return False
    try:
        return json.loads(x["body"]) == json.loads(y["body"])
    except ValueError:
        return x["body"] == y["body"]


def _why(x, y) -> str:
    if x is None or y is None:
        return "한쪽에 없음"
    if x["status"] != y["status"]:
        return f"상태 {x['status']} ≠ {y['status']}"
    try:
        jx, jy = json.loads(x["body"]), json.loads(y["body"])
    except ValueError:
        return "본문이 JSON이 아님"
    if isinstance(jx, list):           # /search — 순서가 같은지, 점수만 다른지
        ids = lambda j: [(r.get("section_name"), r.get("article_num"), r.get("chunk_index")) for r in j]
        if ids(jx) != ids(jy):
            return f"순서·청크 다름(길이 {len(jx)}·{len(jy)})"
        d = max(abs(p["score"] - q["score"]) for p, q in zip(jx, jy))
        return f"순서 같음 · 점수 최대 차 {d:.3g}"
    vx, vy = jx["vectors"], jy["vectors"]
    d = max(abs(p - q) for u, v in zip(vx, vy) for p, q in zip(u, v))
    return f"벡터 최대 차 {d:.3g}"


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--url", required=True)
    d.add_argument("--out", required=True, type=Path)
    f = sub.add_parser("diff")
    f.add_argument("a", type=Path)
    f.add_argument("b", type=Path)
    args = ap.parse_args()
    if args.cmd == "dump":
        dump(args.url, args.out)
    else:
        sys.exit(1 if diff(args.a, args.b) else 0)


if __name__ == "__main__":
    main()

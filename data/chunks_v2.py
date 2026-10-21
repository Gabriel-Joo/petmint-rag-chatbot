"""
chunks_v2.py
청크 v2(2026-10-21, rebuild5 준비 6단계) — 지금 청크(data/chunks/)를 바탕으로 실험용 청크 묶음 data/chunks/v2/와 그래프 data/graph/v2/,
Milvus 컬렉션 <이름>_v2를 만든다. 지금 청크·컬렉션은 건드리지 않는다(서빙은 그대로, search-service는 variant='v2'로 고른다).

바꾸는 것(청킹 감사 2026-10-21의 설계안):
1. 긴 열거 → 호 묶음: 500자 넘고 표가 아닌 청크에 최상위 열거(①… / 1. / 가.)가 3개 이상이면 도입문 조각 + 호 묶음(300자 이하)으로.
   도입문은 모든 호 조각의 context_prefix에 복제한다(임베딩·BM25·리랭커와 모델 발췌에 함께 나간다). content는 원문 조각 그대로라
   조각을 이으면 원문이다(_join_records·evidence 대조가 기대는 불변식). 감사 측정: 근거 문장 198개 중 잃는 것 0, 경계에 걸리는 것 0
2. 조 제목만 남은 청크 삭제(제목 괄호 정규식 버그로 생긴 것) / 도입문만 있는 청크(…다음과 같습니다)는 다음 표 청크의 머리말로
3. 표 정리: PDF 배치 글자와 Markdown 표가 둘 다 있는 청크에서 표에 이미 있는 배치 글자 줄을 뺀다. 셀 안 <br>는 낱말이 이어지면
   붙이고 아니면 띄운다. 별표3처럼 공식의 비율이 옆 칸으로 빠진 줄은 공식에 되돌린다("x ]" + "10%" → "x 10%]").
   공식 자리에 남은 PDF 글리프(U+E000~F8FF, 원문의 분수 기호)는 지운다
4. 조각마다 부모(원래 청크)를 남긴다 — parent_content·parent_context_prefix·parent_key. 6단계 B 조건(작은 조각으로 찾고 모델에게는
   부모를 보여주기)이 쓴다

그래프: 조각의 인용은 부모 인용 중 그 조각 글(머리말 포함)에 '제N조'나 조 제목이 나오는 것만(인용 위치 정보가 없어 03-2를 그대로
다시 돌릴 수 없다 — 감사 4절).

  python -m data.chunks_v2 build      # 청크·그래프 파일
  python -m data.chunks_v2 index      # Milvus <이름>_v2 컬렉션(임베딩은 search-service /embed)
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from data.rag_context import graph_key
from data.search_engine import CHUNK_FILES, CHUNKS_DIR, COLLECTION_NAMES, build_embedding_text

ROOT = Path(__file__).resolve().parent.parent
GRAPH_DIR = ROOT / "data" / "graph"
VARIANT = "v2"
OUT_CHUNKS = CHUNKS_DIR / VARIANT
OUT_GRAPH = GRAPH_DIR / VARIANT
MIN_SPLIT, PACK = 500, 300
SPECIES = ("강아지", "고양이")

_TOP = {"circle": re.compile(r"^[ \t]*[①-⑳]", re.M),
        "num": re.compile(r"^[ \t]*(?:\d{1,2}\.|\(\d{1,2}\)|\d{1,2}\))[ \t]", re.M),
        "mok": re.compile(r"^[ \t]*[가-하]\.[ \t]", re.M)}
_HEADER_ONLY = re.compile(r"^제\d+조\(.*$", re.S)
_INTRO_ONLY = re.compile(r"(다음과\s*같습니다|아래와\s*같습니다|다음\s*각\s*호)[.:]?\s*$")
_JOSA_START = re.compile(r"^(을|를|이|가|은|는|의|에|로|으로|과|와|도|만|에게|께)")


def flat(t: str | None) -> str:
    return re.sub(r"\s+", "", t or "")


# ----- 1. 긴 열거 → 호 묶음 -----
def top_level(content: str):
    best = None
    for kind, pat in _TOP.items():
        ms = list(pat.finditer(content))
        if len(ms) >= 3 and (best is None or ms[0].start() < best[1][0].start()):
            best = (kind, ms)
    return best


def split_items(c: dict) -> tuple[str, list[str]] | None:
    """(도입문, 호 묶음들) — 나눌 대상이 아니면 None. 도입문은 비어 있을 수 있다(조각의 뒷부분)"""
    t = c["content"]
    if len(t) <= MIN_SPLIT or "[표]" in t:
        return None
    tl = top_level(t)
    if tl is None:
        return None
    starts = [m.start() for m in tl[1]]
    lead = t[:starts[0]]
    items = [t[s:e] for s, e in zip(starts, starts[1:] + [len(t)])]
    packs, cur = [], ""
    for it in items:
        if cur and len(cur) + len(it) > PACK:
            packs.append(cur)
            cur = ""
        cur += it
    packs.append(cur)
    return lead, packs


# ----- 3. 표 정리 -----
_PUA = re.compile(r"[\ue000-\uf8ff]")       # PDF 글리프(사용자 정의 영역) — 별표3 공식의 분수 기호가 이렇게 남았다


def _join_br(cell: str) -> str:
    parts = _PUA.sub("", cell).split("<br>")
    out = parts[0]
    for p in parts[1:]:
        if not p.strip():
            out += " "
            continue
        out += ("" if _JOSA_START.match(p.strip()) else " ") + p.lstrip()
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def clean_table(md: str) -> str:
    rows = []
    for line in md.split("\n"):
        if not line.startswith("|"):
            rows.append(line)
            continue
        cells = [_join_br(x) for x in line.strip().strip("|").split("|")]
        # 공식의 비율이 옆 칸으로 빠졌다 — "[… x ]" + "10%"
        for i, cell in enumerate(cells[:-1]):
            nxt = cells[i + 1].strip()
            if re.search(r"x\s*\]$", cell) and re.fullmatch(r"\d+(?:\.\d+)?%", nxt):
                cells[i] = re.sub(r"x\s*\]$", f"x {nxt}]", cell)
        rows.append("|" + "|".join(cells) + "|")
    return "\n".join(rows)


def clean_table_chunk(content: str) -> tuple[str, bool]:
    """배치 글자 + [표] Markdown이면 표에 이미 있는 배치 줄을 빼고 표를 정리한다. (새 글, 바뀌었나)"""
    if "[표]" not in content:
        return content, False
    layout, _, md = content.partition("[표]")
    md_clean = clean_table(md)
    table_flat = flat(md_clean) + flat(md)
    kept = [ln for ln in layout.split("\n") if ln.strip() and flat(ln) not in table_flat]
    new = ("\n".join(kept).strip() + "\n\n" if kept else "") + "[표]" + md_clean
    return new, new != content


# ----- 조립 -----
def build_species(sp: str) -> tuple[list[dict], dict, Counter]:
    chunks = json.loads(CHUNK_FILES[sp].read_text(encoding="utf-8"))
    graph = json.loads((GRAPH_DIR / f"petmint_{sp}_graph.json").read_text(encoding="utf-8"))
    stats = Counter()
    out: list[dict] = []
    carry_prefix = None                                   # 도입문만 있던 청크의 글 — 다음 청크 머리말로
    for i, c in enumerate(chunks):
        t = c["content"]
        if _HEADER_ONLY.match(flat(t)) and "다." not in t and len(flat(t)) < 60:
            stats["제목만_삭제"] += 1
            continue
        nxt = chunks[i + 1] if i + 1 < len(chunks) else None
        if (len(flat(t)) < 100 and _INTRO_ONLY.search(t.strip()) and nxt is not None
                and nxt.get("article_num") == c.get("article_num") and nxt.get("section_name") == c.get("section_name")
                and "[표]" in nxt["content"]):
            carry_prefix = re.sub(r"\s+", " ", t).strip()
            stats["도입문만_이동"] += 1
            continue
        parent = dict(c)
        pkey = graph_key(c)
        base = {**c, "parent_key": pkey, "parent_index": i, "parent_content": c["content"],
                "parent_context_prefix": c.get("context_prefix")}
        if carry_prefix:
            base["context_prefix"] = " / ".join(x for x in (c.get("context_prefix"), carry_prefix) if x)
            carry_prefix = None
        cleaned, changed = clean_table_chunk(t)
        if changed:
            stats["표_정리"] += 1
            base["content"] = cleaned
            out.append(base)
            continue
        sp_items = split_items(parent)
        if sp_items is None:
            out.append(base)
            continue
        lead, packs = sp_items
        stats["호_분할"] += 1
        lead_txt = re.sub(r"\s+", " ", lead).strip()
        if flat(lead):
            out.append({**base, "content": lead, "piece": "lead"})
        for p in packs:
            prefix = " / ".join(x for x in (c.get("context_prefix"), lead_txt) if x) or None
            out.append({**base, "content": p, "context_prefix": prefix, "piece": "item"})
    # chunk_index·chunk_total — 같은 (섹션, 조, 항, 등급) 안에서 다시 매긴다
    groups = defaultdict(list)
    for c in out:
        groups[(c["section"], c.get("section_name"), c.get("article_num"), c.get("coverage_type"), c.get("paragraph_num"))].append(c)
    for g in groups.values():
        for k, c in enumerate(g):
            c["chunk_index"], c["chunk_total"] = k, len(g)
    # 그래프 — 부모 인용 중 조각 글에 나오는 것만
    new_graph = {}
    for c in out:
        edges = graph.get(c["parent_key"], [])
        if c.get("piece") is None:
            kept = edges
        else:
            text = flat((c.get("context_prefix") or "") + c["content"])
            kept = [e for e in edges if f"제{e[0]}조" in text or (e[1] and flat(e[1]) in text)]
        if kept:
            new_graph[graph_key(c)] = kept
    stats["청크"] = len(out)
    return out, new_graph, stats


def build():
    OUT_CHUNKS.mkdir(parents=True, exist_ok=True)
    OUT_GRAPH.mkdir(parents=True, exist_ok=True)
    for sp in SPECIES:
        chunks, graph, stats = build_species(sp)
        (OUT_CHUNKS / CHUNK_FILES[sp].name).write_text(json.dumps(chunks, ensure_ascii=False, indent=1), encoding="utf-8")
        (OUT_GRAPH / f"petmint_{sp}_graph.json").write_text(json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8")
        old = len(json.loads(CHUNK_FILES[sp].read_text(encoding="utf-8")))
        print(f"{sp}: {old} → {stats['청크']} | " + " · ".join(f"{k} {v}" for k, v in stats.items() if k != "청크"))
    # 인사규정은 바꾸지 않는다 — 같은 폴더에 그대로(앱이 PETMINT_CHUNKS_DIR 하나로 세 코퍼스를 읽는다)
    for name in ("hr_인사규정.json",):
        (OUT_CHUNKS / name).write_text((CHUNKS_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
        (OUT_GRAPH / "hr_인사규정_graph.json").write_text((GRAPH_DIR / "hr_인사규정_graph.json").read_text(encoding="utf-8"),
                                                       encoding="utf-8")


def index(search_url: str = "http://192.168.122.1:8100", milvus_uri: str = "http://localhost:19530"):
    """Milvus <이름>_v2 컬렉션 — 02 노트북과 같은 스키마, 같은 임베딩 텍스트(build_embedding_text). 임베딩은 search-service /embed"""
    from pymilvus import DataType, MilvusClient
    client = MilvusClient(uri=milvus_uri)
    for sp in SPECIES:
        name = f"{COLLECTION_NAMES[sp]}_{VARIANT}"
        if client.has_collection(name):
            client.drop_collection(name)
        schema = client.create_schema(auto_id=True, enable_dynamic_field=True)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=1024)
        schema.add_field("content", DataType.VARCHAR, max_length=12000)
        schema.add_field("species", DataType.VARCHAR, max_length=10)
        schema.add_field("section", DataType.VARCHAR, max_length=64)
        schema.add_field("section_name", DataType.VARCHAR, max_length=256, nullable=True)
        schema.add_field("type", DataType.VARCHAR, max_length=5, nullable=True)
        schema.add_field("article_num", DataType.INT64, nullable=True)
        schema.add_field("article_title", DataType.VARCHAR, max_length=256, nullable=True)
        schema.add_field("coverage_type", DataType.VARCHAR, max_length=10, nullable=True)
        schema.add_field("paragraph_num", DataType.INT64, nullable=True)
        schema.add_field("chunk_index", DataType.INT64)
        schema.add_field("chunk_total", DataType.INT64)
        schema.add_field("printed_page_start", DataType.INT64)
        schema.add_field("printed_page_end", DataType.INT64)
        schema.add_field("citations_raw", DataType.VARCHAR, max_length=4000, nullable=True)
        schema.add_field("context_prefix", DataType.VARCHAR, max_length=1024, nullable=True)
        idx = client.prepare_index_params()
        idx.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        client.create_collection(collection_name=name, schema=schema, index_params=idx)
        chunks = json.loads((OUT_CHUNKS / CHUNK_FILES[sp].name).read_text(encoding="utf-8"))
        for s in range(0, len(chunks), 16):
            batch = chunks[s:s + 16]
            r = httpx.post(f"{search_url}/embed", json={"texts": [build_embedding_text(c) for c in batch]}, timeout=120)
            r.raise_for_status()
            client.insert(collection_name=name, data=[{
                "vector": v, "content": c["content"], "species": c["species"], "section": c["section"],
                "section_name": c.get("section_name"), "type": c.get("type"), "article_num": c.get("article_num"),
                "article_title": c.get("article_title"), "coverage_type": c.get("coverage_type"),
                "paragraph_num": c.get("paragraph_num"), "chunk_index": c["chunk_index"], "chunk_total": c["chunk_total"],
                "printed_page_start": c["printed_page_range"][0], "printed_page_end": c["printed_page_range"][1],
                "citations_raw": None, "context_prefix": c.get("context_prefix")} for c, v in zip(batch, r.json()["vectors"])])
        client.flush(name)
        print(f"{name}: {len(chunks)}건 색인")


if __name__ == "__main__":
    {"build": build, "index": index}[sys.argv[1]]()

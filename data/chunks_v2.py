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
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from data.rag_context import graph_key
from data.search_engine import CHUNK_FILES, CHUNKS_DIR, COLLECTION_NAMES, build_embedding_text

ROOT = Path(__file__).resolve().parent.parent
GRAPH_DIR = ROOT / "data" / "graph"
VARIANT = os.environ.get("PETMINT_CHUNK_VARIANT", "v3")   # v2(2026-10-21, 정규식 새로 짬 — 측정 재현용으로 남김) / v3(2026-10-22, 01 도구)
OUT_CHUNKS = CHUNKS_DIR / VARIANT
OUT_GRAPH = GRAPH_DIR / VARIANT
MIN_SPLIT, PACK = 500, 300
SPECIES = ("강아지", "고양이")

_HEADER_ONLY = re.compile(r"^제\d+조\(.*$", re.S)
_INTRO_ONLY = re.compile(r"(다음과\s*같습니다|아래와\s*같습니다|다음\s*각\s*호)[.:]?\s*$")
_JOSA_START = re.compile(r"^(을|를|이|가|은|는|의|에|로|으로|과|와|도|만|에게|께)")


def flat(t: str | None) -> str:
    return re.sub(r"\s+", "", t or "")


# ----- 1. 긴 열거 → 호 묶음 -----
# v2(2026-10-21)는 정규식을 새로 짜 154개 중 19개를 잘못 쪼갰다 — 1. / 1) / (1)을 한 단계로 봤고(하위가 상위와 다른 조각으로),
# 인용 법조문 박스의 ①(그 법의 항)을 약관 열거와 같은 단계로 이었고, 주요내용 요약서처럼 01이 일부러 하위를 쪼개지 않은 섹션도 쪼갰다.
# v3(2026-10-22)는 새로 짜지 않고 01 전처리 노트북의 도구를 그대로 실행해 가져온다(_nb01):
#   - 섹션마다 표기 해석: SECTION_MAP의 파서 — 약관 조-항(parse_articles·의료비 2·3단계)은 항이 \uf000이라 본문 ①은 열거(호),
#     법규(parse_bupgyu)는 ①이 항(청크가 이미 항 단위)이라 그 안의 '1.'만 호. 나머지 섹션은 01 파서가 정한 단위를 바꾸지 않는다
#     (parse_summary_notice docstring: "하위 구조(①②, 1), (1))는 쪼개지 않고 본문에 포함한다")
#   - 인용 법조문 박스: 셀 8 SPLIT_BOUNDARIES의 '법령박스' 경계 — 따로 떼어 별도 조각(piece="lawbox")
#   - ① 열거: 셀 8 HANG_LINE + 순서 거르기(split_by_korean_sub와 같은 규칙 — 번호가 앞보다 커야 라벨)
#   - 호: 셀 3 split_by_numbered_title(NUMBERED_TITLE — 'N.'만. 1)·(1)은 하위라 그 호 안에 남는다)
#   - 목: 셀 3 split_by_korean_sub(순서 역행 라벨과 줄바꿈으로 끊긴 '다.'(_is_wrapped_word_end)를 거른다)
NB01 = ROOT / "notebooks" / "01_데이터_전처리.ipynb"
ARTICLE_PARSERS = {"parse_articles", "parse_medical_teukyak_2stage", "parse_medical_teukyak_3stage"}
LAW_PARSERS = {"parse_bupgyu"}
_LAW_BOX_TITLE = re.compile(r"[ \t]*【[^】]*(?:법|령|규칙|규정)[^】]*】")      # 법령 인용 박스(용어 풀이 박스 【계약 전 알릴 의무】는 아님)
_GRADE_LABEL = re.compile(r"[ \t]*[①②③]\s*(?:고급형|기본형|실속형)")          # 의료비 특약의 등급 표지(셀 3 TYPE_PATTERN) — 열거 아님
_TOOLS: dict = {}


def _nb01() -> dict:
    """01 노트북 셀 2(SECTION_MAP)·3(텍스트 파싱 도구)·8(분할 경계)을 그대로 실행한 이름공간. 셀 끝의 실행부(PDF 읽기·레코드 조립)는 뺀다"""
    if not _TOOLS:
        cells = ["".join(c["source"]) for c in json.loads(NB01.read_text(encoding="utf-8"))["cells"]]
        g = {"re": re, "Counter": Counter}
        exec(cells[1][:cells[1].index("\nfor species, path in PDF_FILES")], g)
        exec(cells[2], g)
        exec(cells[7][:cells[7].index("\nfor species, src in")], g)
        _TOOLS.update(g)
    return _TOOLS


def parser_of(sp: str, c: dict) -> str | None:
    """청크의 01 파서 — SECTION_MAP에서 section_name으로(보통약관은 section_name None → parse_articles)"""
    if c.get("section_name") is None:
        return "parse_articles" if c["section"] == "보통약관" else None
    return next((e["parser"] for e in _nb01()["SECTION_MAP"][sp] if e["section_name"] == c["section_name"]), None)


def _starts(text: str, segments: list[dict]) -> list[int]:
    """01 분리 함수가 돌려준 조각(text)의 원문 위치 — 라벨이 있는 조각만. 조각을 이어 원문이 되게 위치로만 쓴다"""
    out, cur = [], 0
    for seg in segments:
        i = text.find(seg["text"], cur)
        if i < 0:
            continue
        cur = i + len(seg["text"])
        if seg.get("num") is not None or seg.get("label") is not None:
            out.append(i)
    return out


def _circle_starts(text: str) -> list[int]:
    g = _nb01()
    circles = g["CIRCLE_NUMS"] + "⑯⑰⑱⑲⑳"
    out, last = [], 0
    for m in g["HANG_LINE"].finditer(text):
        if _GRADE_LABEL.match(text, m.start()):
            continue
        k = circles.index(text[m.end() - 1]) + 1
        if k > last:                                   # 순서 거르기 — split_by_korean_sub와 같은 규칙
            out.append(m.start())
            last = k
    return out


def item_starts(body: str, parser: str) -> tuple[str, list[int]] | None:
    """(표기, 열거 시작 위치들) — 섹션의 표기 해석대로 가장 바깥 단계 하나. 3개 미만이면 None"""
    g = _nb01()
    tries = []
    if parser in ARTICLE_PARSERS:
        tries.append(("원문자", _circle_starts(body)))
    tries.append(("호(N.)", _starts(body + "\n", g["split_by_numbered_title"](body + "\n"))))
    tries.append(("목(가.)", _starts(body + "\n", g["split_by_korean_sub"](body + "\n"))))
    for kind, st in tries:
        st = [x for x in st if x < len(body)]
        if len(st) >= 3:
            return kind, st
    return None


def law_box_spans(t: str) -> list[tuple[int, int]]:
    """인용 법조문 박스 구간 — 셀 8 '법령박스' 경계(줄 시작의 【)로 나눈 구간 중 제목이 법령인 것"""
    cuts = [0] + [m.start() + 1 for m in _nb01()["SPLIT_BOUNDARIES"][0][1].finditer(t)]   # 0: 01이 법령박스 경계에서 잘라 박스로 시작하는 청크
    bounds = sorted(set(cuts + [len(t)]))
    return [(a, b) for a, b in zip(bounds, bounds[1:]) if _LAW_BOX_TITLE.match(t, a)]


def split_items(c: dict, sp: str) -> tuple[list[tuple[str, str]], dict] | None:
    """[(piece 종류, 글)] — 이어 붙이면 원문. 나눌 대상이 아니면 None.
    종류: lead(도입문) · item(호 묶음, 300자 이하) · body(열거로 못 나눈 본문) · lawbox(인용 법조문)"""
    t = c["content"]
    parser = parser_of(sp, c)
    if len(t) <= MIN_SPLIT or "[표]" in t or parser not in ARTICLE_PARSERS | LAW_PARSERS:
        return None
    boxes = law_box_spans(t) if parser in ARTICLE_PARSERS else []
    spans, pos = [], 0
    for a, b in boxes:
        if a > pos:
            spans.append(("text", pos, a))
        spans.append(("lawbox", a, b))
        pos = b
    if pos < len(t):
        spans.append(("text", pos, len(t)))
    pieces, info = [], {"kind": None, "lawbox": len(boxes)}
    for typ, a, b in spans:
        seg = t[a:b]
        if typ == "lawbox":
            pieces.append(("lawbox", seg))
            continue
        found = item_starts(seg, parser) if len(seg) > MIN_SPLIT else None
        if found is None:
            pieces.append(("body", seg))
            continue
        info["kind"], st = found
        if st[0] > 0:
            pieces.append(("lead", seg[:st[0]]))
        cur = ""
        for x, y in zip(st, st[1:] + [len(seg)]):
            if cur and len(cur) + (y - x) > PACK:
                pieces.append(("item", cur))
                cur = ""
            cur += seg[x:y]
        pieces.append(("item", cur))
    if len(pieces) == 1:
        return None
    assert "".join(p for _, p in pieces) == t
    return pieces, info


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


# 공백 정렬 배치표(2026-10-22) — 01의 rebuild_level2/3_table이 의료비 특약 제1조 ②의 깨진 한도표를 칸을 공백으로 맞춘 글 표로
# 다시 만들었다(종마다 18개). 칸 구분은 공백 2칸 이상. Markdown 표로 바꿔야 답 아래 표 붙이기(app/services/tables.py)가 읽는다
_LAYOUT_HEAD = re.compile(r"^[ \t]*항목[ \t]{2,}자기부담금[ \t]{2,}지급 한도[ \t]*$", re.M)


def layout_table_to_md(content: str) -> tuple[str, bool]:
    m = _LAYOUT_HEAD.search(content)
    if m is None:
        return content, False
    end = content.find("\n\n", m.end())
    end = len(content) if end < 0 else end
    lines = [l for l in content[m.start():end].split("\n") if l.strip()]
    rows = [re.split(r"[ \t]{2,}", l.strip()) for l in lines]
    if any(len(r) != 3 for r in rows):
        return content, False
    md = "[표]\n" + "\n".join("|" + "|".join(r) + "|" for r in rows[:1]) + "\n|---|---|---|\n" \
        + "\n".join("|" + "|".join(r) + "|" for r in rows[1:])
    start = content.rfind("\n", 0, m.start()) + 1
    return content[:start] + md + content[end:], True


def _in_table(line: str, table_flat: str, max_pieces: int = 3, min_piece: int = 2, min_line: int = 12) -> bool:
    """배치 줄이 표에 이미 있나 — 줄 전체가 표 글에 있거나, 표 글의 조각 max_pieces개 이하로 다시 만들어지면 있다.
    두 칸이 한 줄에 섞인 배치 줄("보험  보험금 지급사유가 … 회사에 보험" / "수익자 금을 청구하여 …", 일반조항 제2조)은 줄 전체로는
    표에 없다(2026-10-23 v4 — 가입 나이 4문항이 그 청크에서 3회 모두 거절). 짧은 줄(묶음 제목 "계약관련 용어")은 남긴다"""
    s = flat(line)
    if s in table_flat:
        return True
    if len(s) < min_line:
        return False
    i = pieces = 0
    while i < len(s):
        j = len(s)
        while j - i >= min_piece and s[i:j] not in table_flat:
            j -= 1
        if j - i < min_piece:
            return False
        i, pieces = j, pieces + 1
        if pieces > max_pieces:
            return False
    return True


def clean_table_chunk(content: str) -> tuple[str, bool]:
    """배치 글자 + [표] Markdown이면 표에 이미 있는 배치 줄을 빼고 표를 정리한다. (새 글, 바뀌었나)"""
    if "[표]" not in content:
        return content, False
    layout, _, md = content.partition("[표]")
    md_clean = clean_table(md)
    table_flat = flat(md_clean) + flat(md)
    kept = [ln for ln in layout.split("\n") if ln.strip() and not _in_table(ln, table_flat)]
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
        t, laid = layout_table_to_md(t)
        if laid:
            stats["배치표_변환"] += 1
            base["content"] = t
            out.append(base)
            continue
        cleaned, changed = clean_table_chunk(t)
        if changed:
            stats["표_정리"] += 1
            base["content"] = cleaned
            out.append(base)
            continue
        sp_items = split_items(parent, sp)
        if sp_items is None:
            out.append(base)
            continue
        pieces, info = sp_items
        stats["호_분할" if info["kind"] else "법령박스만_분리"] += 1
        stats["법령박스_조각"] += info["lawbox"]
        lead_txt = next((re.sub(r"\s+", " ", p).strip() for k, p in pieces if k == "lead"), "")
        for kind, p in pieces:
            if not flat(p):
                continue
            if kind == "item":
                prefix = " / ".join(x for x in (c.get("context_prefix"), lead_txt) if x) or None
            elif kind == "lawbox":
                head = f"제{c['article_num']}조({c.get('article_title') or ''})" if c.get("article_num") else ""
                prefix = " / ".join(x for x in (c.get("context_prefix"), f"{head} 인용 법조문".strip()) if x)
            else:
                prefix = c.get("context_prefix")
            out.append({**base, "content": p, "context_prefix": prefix, "piece": kind})
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

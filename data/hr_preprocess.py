"""
hr_preprocess.py
사내규정(가상 회사 인사규정) RAG 데이터 전처리 — 09 UI "사내규정" 모드용. 01(약관 전처리)의 사내규정판.
베이스 모델 + RAG로 쓰므로 FAQ·파인튜닝용 처리는 없다.

01을 그대로 쓰지 않는 이유(2026-10-13 확인):
- 항 기호: 약관 PDF는 항을 사설 글리프 \\uf000로 찍어 01의 split_into_paragraphs가 그것으로 자른다. 인사규정은 실제 원문자(①②③).
- 조 머리: pymupdf가 "제1 조(목적)", "5 일"처럼 숫자 뒤에 공백을 넣는다(LibreOffice 출력) → 01 ARTICLE_HEADER(제(\\d+)조\\()에 안 걸린다.
- 읽기 순서: 약관은 2단이라 sort=True가 필요했지만 인사규정은 1단이고, sort=True는 일부 줄의 띄어쓰기를 잃는다
  (별표1 ※ "해외출장의경우…"). sort=False는 표 셀을 한 줄씩 순서대로 내보내 표 위치를 찾기도 쉽다.

결정:
- 청크 = 조 단위(표 포함). 조가 짧고(평균 195자, 최대 482자) 항끼리 기댄다("제1항의 휴가에", "제2항의 승인").
  조가 SPLIT_LIMIT을 넘으면 그때 항으로 나눈다(현재 0건).
- 표는 본문 뒤에 덧붙이지 않고 본문의 표 텍스트 자리를 마크다운으로 바꾼다 — 약관은 덧붙여서 같은 표가 두 번 들어갔다(KNOWN_ISSUES).
  쪽을 넘어 갈라진 표(제30조 법정의무교육)는 머리글이 같으면 하나로 합친다.
- section = 본칙/부칙/별표, section_name = 장 이름("제4장 휴일 및 휴가") — 부칙 제1조와 본칙 제1조를 section으로 구분한다.
- 인용: 제N조 → 본칙 N조(그래프 엣지), 제N항·제N항제M호 → 같은 조(조 단위 청크라 엣지 없음),
  별표N → 별표 청크(엣지, 조번호 없음), 「법」 제N조 → 원문 미수록(엣지 없음).

실행: python -m data.hr_preprocess  → data/chunks/hr_인사규정.json, data/graph/hr_인사규정_graph.json
"""

import json
import re
from pathlib import Path

import pymupdf

BASE_DIR = Path(__file__).parent
PDF_PATH = BASE_DIR / "raw_pdf" / "펫퍼민트손해보험_인사규정.pdf"
CORPUS = "인사규정"
CHUNK_FILE = BASE_DIR / "chunks" / "hr_인사규정.json"
GRAPH_FILE = BASE_DIR / "graph" / "hr_인사규정_graph.json"
DOC_META = {"doc_id": "petmint_hr_2601", "doc_name": "펫퍼민트손해보험 주식회사 인사규정", "regulation_version": "2026-01"}
DROPPED_HEADERS: list[str] = []   # 이어진 표에서 지운 반복 머리글(load_pages가 채움)
SPLIT_LIMIT = 1500          # 조 하나가 이보다 길면 항 단위로 나눈다(현재 최장 약 900자)

CIRCLES = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
CHAPTER = re.compile(r"^제(\d+)장\s*(.+?)\s*$")
ARTICLE = re.compile(r"^제(\d+)조\(([^)]*)\)\s*$")
ADDENDUM = re.compile(r"^부칙\s*$")
APPENDIX = re.compile(r"^별표(\d+)\.\s*(.+?)\s*$")
LINE_MARKER = re.compile(rf"^\s*([{CIRCLES}]|\d+\.\s|제\d+조\(|제\d+장|부칙|별표\d|※|\|)")
CITATION = re.compile(r"(「[^」]+」\s*)?제(\d+)조(?:\s*제(\d+)항)?(?:\s*제(\d+)호)?|제(\d+)항(?:\s*제(\d+)호)?|별표(\d+)")


def normalize(text: str) -> str:
    """pymupdf가 넣은 숫자 뒤 공백을 지운다: '제1 조' → '제1조', '5 일' → '5일', '별표 1' → '별표1'."""
    text = re.sub(r"제\s*(\d+)\s*(조|장|항|호)", r"제\1\2", text)
    text = re.sub(r"별표\s*(\d+)", r"별표\1", text)
    return re.sub(r"(\d) (?=[가-힣])", r"\1", text)


def _flat(s: str) -> str:
    return re.sub(r"\s+", "", s)


def table_markdown(rows: list[list[str]]) -> str:
    rows = [[normalize(re.sub(r"\s*\n\s*", " ", c or "")).strip() for c in r] for r in rows]
    head, body = rows[0], rows[1:]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in body])


def replace_tables(page_text: str, tables: list[list[list[str]]]) -> tuple[str, int]:
    """쪽 본문에서 각 표가 차지한 글자 구간을 찾아 마크다운으로 바꾼다.
    구간 = 첫 셀이 시작하는 줄부터, 공백을 뺀 글자가 셀 전체(행 순서)와 정확히 같아지는 지점까지.
    마지막 셀 글자로 끝을 찾으면 같은 값('1 일')이 앞에서 먼저 걸린다. 반환: (새 본문, 바꾼 표 수)"""
    out, cursor, n = [], 0, 0
    for rows in tables:
        target = _flat("".join(c or "" for r in rows for c in r))
        first = (rows[0][0] or "").strip()
        start = page_text.find("\n" + first, cursor)
        start = 0 if page_text.startswith(first) and cursor == 0 else (start + 1 if start >= 0 else -1)
        if start < 0:
            raise ValueError(f"표 머리 '{first}'를 본문에서 못 찾음")
        got, i = 0, start
        while i < len(page_text) and got < len(target):
            if not page_text[i].isspace():
                if page_text[i] != target[got]:
                    raise ValueError(f"표 '{first}' 글자 불일치: {page_text[i]!r} ≠ {target[got]!r}")
                got += 1
            i += 1
        out += [page_text[cursor:start], "\n" + table_markdown(rows) + "\n"]
        cursor, n = i, n + 1
    out.append(page_text[cursor:])
    return "".join(out), n


def load_pages(pdf_path: Path = PDF_PATH) -> list[dict]:
    """쪽마다 표를 마크다운으로 바꾼 본문. 쪽을 넘어 갈라진 표는 다음 쪽 조각의 머리글을 지우고 앞 표에 잇는다."""
    doc = pymupdf.open(pdf_path)
    pages, prev_head = [], None
    for i, p in enumerate(doc):
        tables = [t.extract() for t in p.find_tables().tables]
        text, n = replace_tables(p.get_text(), tables)
        assert n == len(tables)
        text = normalize(text)
        # 쪽 첫머리 표의 머리글이 앞 쪽 마지막 표와 같으면 이어진 표다 → 머리글·구분줄 삭제
        if tables and prev_head is not None and text.lstrip().startswith("| " + " | ".join(prev_head) + " |"):
            body = text.lstrip()
            DROPPED_HEADERS.append("".join(prev_head))       # 검증에서 원문 대조할 때 빼 준다
            text = "\n".join(body.split("\n")[2:])
            pages[-1]["text"] = pages[-1]["text"].rstrip("\n") + "\n"
            pages[-1]["continued_table"] = True
        # 이 쪽이 표로 끝나면(표 뒤에 다른 줄이 없으면) 그 머리글을 기억
        last = text.rstrip().split("\n")[-1] if text.strip() else ""
        prev_head = [normalize(re.sub(r"\s*\n\s*", " ", c or "")).strip() for c in tables[-1][0]] if tables and last.startswith("|") else None
        pages.append({"page": i + 1, "text": text})
    doc.close()
    return pages


def unwrap(text: str) -> str:
    """줄 바꿈 중 문장 중간인 것만 잇는다(머리줄·항·호·표·※는 줄 시작을 지킨다).
    'X \\nY' → 'X Y', 'X\\nY'(낱말 중간·쪽 경계) → 'XY'."""
    lines = text.split("\n")
    out = []
    for line in lines:
        if out and out[-1].strip() and line.strip() and not LINE_MARKER.match(line) \
                and not (CHAPTER.match(out[-1].strip()) or ARTICLE.match(out[-1].strip()) or ADDENDUM.match(out[-1].strip())
                         or APPENDIX.match(out[-1].strip()) or out[-1].lstrip().startswith("|")) \
                and not re.search(r"(다|음)\.\s*$", out[-1]):
            prev = out.pop()
            out.append(prev + (" " if prev.endswith(" ") else "") + line.lstrip() if prev.endswith(" ") else prev + line.lstrip())
            out[-1] = re.sub(r"  +", " ", out[-1])
        else:
            out.append(line.rstrip())
    return "\n".join(out)


def find_citations(content: str, own_article: int | None) -> list[dict]:
    """조문 본문의 인용. 머리줄(제N조(제목), 별표N. 제목)은 빼고 찾는다 — 자기 자신을 가리키는 엣지가 생긴다."""
    first, _, rest = content.partition("\n")
    body = rest if (ARTICLE.match(first.strip()) or APPENDIX.match(first.strip())) else content
    out = []
    for m in CITATION.finditer(body):
        law, art, para, ho, self_para, self_ho, appx = m.groups()
        if appx:
            out.append({"kind": "appendix", "appendix_num": int(appx), "raw": m.group(0)})
        elif law:
            out.append({"kind": "law_not_in_excerpt", "law_name": law.strip(" 「」"), "article_num": int(art), "raw": m.group(0).strip()})
        elif art:
            kind = "self_article" if own_article is not None and int(art) == own_article else "same_document"
            out.append({"kind": kind, "article_num": int(art), "paragraph_num": int(para) if para else None,
                        "sub_ho": int(ho) if ho else None, "raw": m.group(0)})
        else:
            out.append({"kind": "self_paragraph", "paragraph_num": int(self_para), "sub_ho": int(self_ho) if self_ho else None,
                        "raw": m.group(0)})
    return out


def parse(pages: list[dict]) -> list[dict]:
    full, bounds = "", []
    for p in pages:
        bounds.append((len(full), p["page"]))
        full += p["text"].rstrip("\n") + "\n"
    full = unwrap(full)
    # unwrap은 줄만 잇고 글자 수를 줄이므로 쪽 경계는 공백 제거 글자 수로 다시 잡는다
    flat_bounds, acc = [], 0
    for p in pages:
        flat_bounds.append((acc, p["page"]))
        acc += len(_flat(unwrap(p["text"])))

    def page_of(pos: int) -> int:
        k = len(_flat(full[:pos]))
        return max(pg for start, pg in flat_bounds if start <= k)

    lines = full.split("\n")
    offsets, o = [], 0
    for ln in lines:
        offsets.append(o)
        o += len(ln) + 1
    heads = []      # (줄 번호, 종류, 값)
    for i, ln in enumerate(lines):
        s = ln.strip()
        for kind, pat in (("chapter", CHAPTER), ("article", ARTICLE), ("addendum", ADDENDUM), ("appendix", APPENDIX)):
            m = pat.match(s)
            if m:
                heads.append((i, kind, m))
                break
    chunks, section, section_name, chapter = [], "본칙", None, None
    for h, (i, kind, m) in enumerate(heads):
        if kind == "chapter":
            chapter, section_name = int(m.group(1)), f"제{m.group(1)}장 {m.group(2)}"
            continue
        if kind == "addendum":
            section, section_name, chapter = "부칙", "부칙", None
            continue
        end = heads[h + 1][0] if h + 1 < len(heads) else len(lines)
        body = "\n".join(lines[i:end]).strip()
        start_pos = offsets[i]
        end_pos = offsets[end - 1] + len(lines[end - 1]) if end - 1 < len(lines) else len(full)
        if kind == "appendix":
            rec = {"section": "별표", "section_name": f"별표{m.group(1)} {m.group(2)}", "chapter_num": None,
                   "article_num": None, "article_title": m.group(2), "appendix_num": int(m.group(1))}
        else:
            rec = {"section": section, "section_name": section_name, "chapter_num": chapter,
                   "article_num": int(m.group(1)), "article_title": m.group(2)}
        assert len(body) <= SPLIT_LIMIT, f"{rec['section_name']} 제{rec.get('article_num')}조 {len(body)}자 — 항 분할 필요"
        chunks.append({**DOC_META, "corpus": CORPUS, **rec, "paragraph_num": None, "coverage_type": None, "type": None,
                       "chunk_index": 0, "chunk_total": 1, "context_prefix": None,
                       "printed_page_range": [page_of(start_pos), page_of(end_pos)],
                       "effective_date": None, "content": body,
                       "citations": find_citations(body, rec.get("article_num") if rec["section"] == "본칙" else None)})
    eff = next((c for c in chunks if c["section"] == "부칙" and c["article_num"] == 1), None)
    m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", eff["content"]) if eff else None
    for c in chunks:
        c["effective_date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None
    return chunks


def graph_key(c: dict) -> str:
    """rag_context.graph_key와 같은 형식(그래프를 ContextBuilder가 그대로 읽는다)"""
    return (f"{c['section']}|{c.get('section_name')}|{c.get('article_num')}|{c.get('coverage_type')}"
            f"|{c.get('paragraph_num')}|{c.get('chunk_index')}")


def build_graph(chunks: list[dict]) -> tuple[dict, list[str]]:
    """03-2와 같은 엣지 6요소 [조, 제목, 섹션, 문서, 항, 호]. 별표는 조번호 없이 [None, 제목, '별표', 별표 이름, None, None].
    반환: (그래프, 해석 못 한 내부 인용 목록)"""
    main = {c["article_num"]: c for c in chunks if c["section"] == "본칙"}
    appx = {c["appendix_num"]: c for c in chunks if c["section"] == "별표"}
    graph, unresolved = {}, []
    for c in chunks:
        edges = []
        for cit in c["citations"]:
            if cit["kind"] == "same_document":
                t = main.get(cit["article_num"])
                if t is None:
                    unresolved.append(f"{c['section_name']} 제{c['article_num']}조 → {cit['raw']}")
                    continue
                e = [t["article_num"], t["article_title"], t["section"], t["section_name"], cit["paragraph_num"], cit["sub_ho"]]
            elif cit["kind"] == "appendix":
                t = appx.get(cit["appendix_num"])
                if t is None:
                    unresolved.append(f"{c['section_name']} → {cit['raw']}")
                    continue
                e = [None, t["article_title"], "별표", t["section_name"], None, None]
            else:
                continue
            if e not in edges:
                edges.append(e)
        if edges:
            graph[graph_key(c)] = edges
    return graph, unresolved


def validate(chunks: list[dict], graph: dict, unresolved: list[str], pdf_text: str) -> list[str]:
    errors = []
    main = sorted(c["article_num"] for c in chunks if c["section"] == "본칙")
    add = sorted(c["article_num"] for c in chunks if c["section"] == "부칙")
    if main != list(range(1, 46)):
        errors.append(f"본칙 조 번호가 1~45가 아님: {main}")
    if add != [1, 2, 3]:
        errors.append(f"부칙 조 번호가 1~3이 아님: {add}")
    if sum(1 for c in chunks if c["section"] == "별표") != 1:
        errors.append("별표가 1개가 아님")
    n_tables = sum(1 for c in chunks for ln in c["content"].split("\n") if ln.startswith("|---"))
    if n_tables != 7:
        errors.append(f"표 {n_tables}개(기대 7)")
    chapters = sorted({c["chapter_num"] for c in chunks if c["chapter_num"]})
    if chapters != list(range(1, 9)):
        errors.append(f"장 번호 {chapters}")
    # 원문 손실 검사: 일부러 뺀 줄(문서 제목·장 머리·'부칙')만 빼면, 표 기호와 공백을 지운 글자열이 PDF와 정확히 같아야 한다
    dropped = lambda ln: ln.strip() == DOC_META["doc_name"] or CHAPTER.match(ln.strip()) or ADDENDUM.match(ln.strip())
    expect = _flat("".join(ln for ln in normalize(pdf_text).split("\n") if not dropped(ln)))
    actual = _flat(re.sub(r"\|[-|]*", "", "".join(c["content"] for c in chunks)))
    expect = re.sub(r"\|", "", expect)
    for h in DROPPED_HEADERS:          # 쪽을 넘어 이어진 표의 두 번째 머리글은 일부러 지웠다
        h = _flat(h)
        first = expect.find(h)
        second = expect.find(h, first + len(h)) if first >= 0 else -1
        if second >= 0:
            expect = expect[:second] + expect[second + len(h):]
    if expect != actual:
        k = next((i for i, (a, b) in enumerate(zip(expect, actual)) if a != b), min(len(expect), len(actual)))
        errors.append(f"원문 글자열 불일치(PDF {len(expect)}자 / 청크 {len(actual)}자) — 첫 차이 {k}: "
                      f"PDF …{expect[max(0, k - 15):k + 15]}… / 청크 …{actual[max(0, k - 15):k + 15]}…")
    if unresolved:
        errors.append(f"해석 못 한 내부 인용 {unresolved}")
    if any(c.get("printed_page_range")[0] > c.get("printed_page_range")[1] for c in chunks):
        errors.append("쪽 범위 역전")
    return errors


def main():
    pages = load_pages()
    chunks = parse(pages)
    graph, unresolved = build_graph(chunks)
    doc = pymupdf.open(PDF_PATH)
    pdf_text = "".join(p.get_text() for p in doc)
    doc.close()
    errors = validate(chunks, graph, unresolved, pdf_text)
    CHUNK_FILE.write_text(json.dumps(chunks, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    GRAPH_FILE.write_text(json.dumps(graph, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    kinds = {}
    for c in chunks:
        for cit in c["citations"]:
            kinds[cit["kind"]] = kinds.get(cit["kind"], 0) + 1
    L = sorted(len(c["content"]) for c in chunks)
    print(f"청크 {len(chunks)}개(본칙 {sum(c['section'] == '본칙' for c in chunks)}, 부칙 {sum(c['section'] == '부칙' for c in chunks)}, "
          f"별표 {sum(c['section'] == '별표' for c in chunks)}) | 길이 중앙 {L[len(L) // 2]} 최대 {L[-1]}")
    print(f"인용 {kinds} | 그래프 노드 {len(graph)}, 엣지 {sum(len(v) for v in graph.values())}")
    print("검증:", errors or "통과")
    return errors


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)

"""
rag_context.py
펫퍼민트 약관 RAG 컨텍스트 조립 — 검색 결과(또는 FAQ 생성 단위)에 참조 조문·inline 법령 정의를 붙인다.
04번(RAG 조립)과 05번(FAQ 생성)이 공통으로 import해서 쓰는 "진실의 원천" 모듈.

- ContextBuilder: Milvus client + 청크 + 03번 그래프만 사용(모델 로드 없음 — 05에서 Ollama와 GPU 공유 가능)
- build_full_context: 04번 전용. SearchEngine 검색 → 섹션 가중 → ContextBuilder로 참조 보강
"""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from pymilvus import MilvusClient

from data.search_scope import SearchScope

BASE_DIR = Path(__file__).parent  # data/ 폴더 기준
CHUNKS_DIR = BASE_DIR / "chunks"
GRAPH_DIR = BASE_DIR / "graph"

MILVUS_URI = "http://localhost:19530"

# 키는 '종 또는 코퍼스'(search_engine.COLLECTION_NAMES와 같다)
COLLECTION_NAMES = {
    "강아지": "petmint_dog",
    "고양이": "petmint_cat",
    "인사규정": "hr_regulation",
}

CHUNK_FILES = {
    "강아지": CHUNKS_DIR / "petmint_강아지.json",
    "고양이": CHUNKS_DIR / "petmint_고양이.json",
    "인사규정": CHUNKS_DIR / "hr_인사규정.json",
}

GRAPH_FILES = {
    "강아지": GRAPH_DIR / "petmint_강아지_graph.json",
    "고양이": GRAPH_DIR / "petmint_고양이_graph.json",
    "인사규정": GRAPH_DIR / "hr_인사규정_graph.json",
}

# reranker 점수에 곱하는 section 우선순위(목차/색인 등 낮은 비중 섹션 억제). 목록에 없는 섹션은 0.8
SECTION_PRIORITY = {
    "보통약관": 1.0, "특별약관": 1.0, "기타_제도성_특별약관": 1.0,
    "별표": 0.95, "별첨": 0.95,
    "법규": 0.9,
    "안내_요약": 0.85, "안내_용어": 0.85, "약관_이용": 0.85,
    "안내_절차": 0.8, "안내_개인정보": 0.7,
    "목차": 0.5, "색인": 0.5, "간지": 0.3, "표지": 0.3,
    "본칙": 1.0, "부칙": 0.7,     # 인사규정 — 부칙(시행일·경과조치)은 주제 질문에서 뒤로
}


def _load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def graph_key(c: dict) -> str:
    """03-2 build_reference_graph와 같은 형식이어야 한다(None은 문자열 "None"이 됨).
    청크(조각) 단위 — 그 청크가 직접 인용한 조문만 붙는다. 조 단위면 다른 항이 인용한 조문까지,
    항 단위면 분할된 항의 다른 조각이 인용한 조문까지 붙었다. 05의 여러 레코드 묶음은 레코드별 키의 합집합."""
    return (f"{c['section']}|{c.get('section_name')}|{c.get('article_num')}|{c.get('coverage_type')}"
            f"|{c.get('paragraph_num')}|{c.get('chunk_index')}")


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def reference_label(num, title, para=None, ho=None) -> str:
    """'제13조(알릴 의무 위반의 효과) 제1항 제2호' — 조회 단위는 항이고 호는 표기만 한다"""
    label = f"제{num}조({title})" if title else f"제{num}조"
    if para is not None:
        label += f" 제{para}항"
    if ho is not None:
        label += f" 제{ho}호"
    return label


def strip_leading_title(content: str, article_num: int) -> str:
    pattern = re.compile(rf"^제{article_num}조\(((?:[^()]|\([^()]*\))*?)\)\s*", re.DOTALL)
    return pattern.sub("", content, count=1).strip()


def infer_type_from_section_name(section_name: str) -> str | None:
    """01번의 extract_doc_type과 동일한 규칙 — fetch 단계에서도 유형 혼동을 막기 위해 재사용"""
    if not section_name or "의료비" not in section_name:
        return None
    if "Ⅲ" in section_name:
        return "Ⅲ"
    elif "Ⅱ" in section_name:
        return "Ⅱ"
    return "Ⅰ"


def display_text(unit: dict) -> str:
    """LLM 컨텍스트에 넣을 본문. 분할된 뒷조각은 context_prefix(도입 문장/제목 경로)를 앞에 붙여 보여준다.
    fetch 결합(fetch_article_content)에는 쓰지 않는다 — 조각을 이으면 원문이 이미 온전하다."""
    prefix = unit.get("context_prefix")
    return f"[{prefix}]\n{unit['content']}" if prefix else unit["content"]


GRADE_LABEL = re.compile(r"[①②③]\s*(고급형|기본형|실속형)")
PAGE_NUM_LINE = re.compile(r"^\s*\d{1,4}\s*$", re.M)


def _graded_text(text: str) -> str:
    """등급 비교용: 등급 라벨과 페이지 번호 줄을 빼고, 줄 구조는 유지(줄 안 연속 공백만 하나로, 빈 줄 제거).
    줄바꿈을 지우면 한도표 행과 예시 ①②③이 한 줄로 이어져 읽기 어렵다."""
    t = PAGE_NUM_LINE.sub("", GRADE_LABEL.sub("", text))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in t.split("\n")]
    return "\n".join(line for line in lines if line)


def _strip_spaces(text: str) -> tuple[str, list[int]]:
    """공백 없는 문자열과, 그 각 글자의 원문 위치"""
    idx = [i for i, ch in enumerate(text) if not ch.isspace()]
    return "".join(text[i] for i in idx), idx


def _word_span(text: str, start: int, end: int) -> tuple[int, int]:
    """[start, end)를 공백(줄바꿈 포함) 기준 단어 경계까지 넓힌다"""
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return start, end


_BRACKET_PAIRS = [("[", "]"), ("(", ")")]


def _balanced(text: str) -> bool:
    return all(text.count(a) == text.count(b) for a, b in _BRACKET_PAIRS)


def _balance_span(text: str, start: int, end: int) -> tuple[int, int]:
    """구간 안 괄호 짝이 맞을 때까지 단어 단위로 넓힌다(여는 괄호가 많으면 오른쪽, 닫는 괄호가 많으면 왼쪽).
    계산식 '[(33만원 - 3만원)×70%, 30만원]'이 등급 대안 두 개로 쪼개지면 LLM이 무엇에서 무엇을 빼는지 잇지 못한다."""
    for _ in range(60):
        seg = text[start:end]
        if _balanced(seg):
            break
        if any(seg.count(a) > seg.count(b) for a, b in _BRACKET_PAIRS) and end < len(text):
            end = _word_span(text, end, min(end + 1, len(text)))[1]
        elif start > 0:
            start = _word_span(text, max(start - 1, 0), start)[0]
        else:
            break
    return start, end


def _merge_spans(spans: list) -> list[list[int]]:
    spans = sorted(spans)
    merged = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


def _merge_variants(variants: list[tuple[str, str]]) -> str:
    """같은 항의 등급별 본문을 한 벌로: 다른 부분만 {고급형: … / 기본형: … / 실속형: …}로 병기.
    비교는 공백을 무시한 글자 단위 — 등급별 PDF 쪽마다 줄바꿈 위치가 달라('한도 로'/'한도로') 단어 단위로는 엇갈린다.
    다른 구간은 단어 경계, 이어서 괄호 짝이 맞는 단위까지 넓히고, 겹치는 구간은 하나로 합친다."""
    base_grade, base = variants[0]
    b_ns, b_map = _strip_spaces(base)
    aligned, spans = [], []
    for grade, text in variants[1:]:
        v_ns, v_map = _strip_spaces(text)
        ops = SequenceMatcher(None, b_ns, v_ns, autojunk=False).get_opcodes()
        aligned.append((grade, text, v_map, ops))
        for op, i1, i2, j1, j2 in ops:
            if op == "equal":
                continue
            s = b_map[i1] if i1 < len(b_map) else len(base)
            e = b_map[i2 - 1] + 1 if i2 > i1 else s
            spans.append(_balance_span(base, *_word_span(base, s, e)))
    if not spans:
        return base
    merged = _merge_spans(spans)
    while True:                      # 합친 뒤 다시 넓혀야 하는 경우까지 수렴할 때까지
        again = _merge_spans([_balance_span(base, s, e) for s, e in merged])
        if again == merged:
            break
        merged = again

    def to_variant(pos_ns: int, ops, at_end: bool) -> int:
        for op, i1, i2, j1, j2 in ops:
            if i1 <= pos_ns < i2 or (at_end and i1 < pos_ns <= i2):
                return j1 + (pos_ns - i1) if op == "equal" else (j2 if at_end else j1)
        return ops[-1][4] if ops else 0

    out, cur = [], 0
    for s, e in merged:
        out.append(base[cur:s])
        s_ns = sum(1 for i in b_map if i < s)
        e_ns = sum(1 for i in b_map if i < e)
        alts = [f"{base_grade}: {base[s:e] or '-'}"]
        for grade, text, v_map, ops in aligned:
            vs, ve = to_variant(s_ns, ops, False), to_variant(e_ns, ops, True)
            ts = v_map[vs] if vs < len(v_map) else len(text)
            te = v_map[ve - 1] + 1 if ve > vs else ts
            if te > ts:
                ts, te = _word_span(text, ts, te)
            alts.append(f"{grade}: {text[ts:te] or '-'}")
        out.append("{" + " / ".join(alts) + "}")
        cur = e
    out.append(base[cur:])
    return "".join(out)


def merge_graded_rows(rows: list[dict]) -> list[str]:
    """등급별로 나뉜 행들을 (항, 조각)마다 한 벌로. 등급 라벨·페이지 번호만 다른 행은 그대로 하나."""
    groups = {}
    for r in rows:
        groups.setdefault((r.get("paragraph_num"), r.get("chunk_index")), []).append(
            (r.get("coverage_type") or "공통", _graded_text(r["content"])))
    return [variants[0][1] if len({t for _, t in variants}) == 1 else _merge_variants(variants)
            for variants in groups.values()]


def extract_inline_law_definition(main_content: str, law_name: str, article_num: int) -> tuple[str, str] | None:
    """본문 안의 【법명 제N조(…)】 박스에서 (박스 제목, 본문)을 뽑는다.
    03-1 find_inline_law_box와 같은 규칙: 【「법명 중첩 괄호, 제59조의4 같은 조의N, 괄호 앞 공백 허용.
    본문은 다음 【 박스 직전까지(박스 안에 페이지번호·빈 줄이 끼어 \\n\\n 기준이면 ②항부터 잘림).
    citation의 article_num엔 "의4"가 없어(59) 제목은 원문 박스에서 그대로 가져온다
    — "소득세법 제59조"는 실재하는 다른 조문(근로소득세액공제)이라 틀린 조문을 인용하게 된다."""
    pattern = re.compile(
        rf"【\s*[「『]?\s*({re.escape(law_name)}\s*[」』]?\s*제{article_num}조(?:의\d+)?\s*\([^)]*\))\s*】\s*\n(.*?)(?=\n\s*【|\Z)",
        re.DOTALL
    )
    m = pattern.search(main_content)
    if not m:
        return None
    heading = re.sub(r"[「」『』]", "", m.group(1)).strip()
    body = "\n".join(line for line in m.group(2).splitlines() if not line.strip().isdigit())  # 페이지번호 줄 제거
    body = body.strip()
    return (heading, body) if body else None


# 조 전체 참조 상한. 측정(2026-10-12, 조 전체 참조 226건): 적용형('~를 준용/따라') 최대 1895자,
# 그다음 금융소비자보호법 제46조 2151자(청약철회의 기한·효력·반환·손해배상·예외가 1~5항에 흩어져 조 전체가 필요),
# 그다음 3261자 — 2151~3261 빈 구간의 값. 넘는 것은 정의형 14건(보통약관 제2조 용어의 정의 5026자,
# 의료비Ⅲ 제1조 3261·3436자)뿐이고 각각 용어가 든 항(5항 / 1항)만 필요했다. 2000이면 제46조를 잘라 놓친다.
WHOLE_REF_CAP = 2500
_TITLE_RE = r"\((?:[^()]|\([^()]*\))*\)"
_DEFINED_IN = re.compile(rf"^(?:{_TITLE_RE})?(?:제\d+항)?(?:제\d+호)?(?:에서|에)(?:정한|정하는|정하여진|규정한)")


def defined_term_paragraphs(unit_content: str, ref_num: int, paras: dict) -> tuple[list, list[str]]:
    """unit이 '제N조(…)에서 정한 X'로 인용했으면 X가 든 항 번호들과 용어.
    용어 = 인용 뒤 글자열 중 대상 조문에 실제로 나오는 가장 긴 앞부분(3자 이상) — 조사에서 자르면
    '수의사'가 '수'가 되는 식으로 틀린다(측정: 자르는 방식 23/48 실패, 이 방식 44/57 찾음)."""
    text = _norm(unit_content)
    found, terms = [], []
    for m in re.finditer(rf"제{ref_num}조(?!의)", text):
        rest = text[m.end():]
        d = _DEFINED_IN.match(rest)
        if not d:
            continue
        after = rest[d.end():d.end() + 20]
        for k in range(len(after), 2, -1):
            hit = [p for p, rs in paras.items() if p is not None and after[:k] in _norm("".join(r["content"] for r in rs))]
            if hit:
                terms.append(after[:k])
                found += [p for p in hit if p not in found]
                break
    return found, terms


def shorten_whole_reference(unit_content: str, ref_num: int, rows: list[dict], assemble, cap: int) -> str:
    """상한을 넘는 조 전체 참조를 줄인다. 정의형 인용이면 용어가 든 항 + 조 머리(항 없는 행),
    아니면 1항부터 상한까지. 줄였다는 사실을 LLM이 알도록 끝에 생략 표시를 붙인다."""
    paras = {}
    for r in rows:
        paras.setdefault(r.get("paragraph_num"), []).append(r)
    keep, terms = defined_term_paragraphs(unit_content, ref_num, paras)
    if keep:
        kept = [r for r in rows if r.get("paragraph_num") is None or r.get("paragraph_num") in keep]
        nums = ", ".join(f"제{p}항" for p in sorted(keep))
        return assemble(kept) + f"\n(제{ref_num}조 중 '{terms[0]}'이(가) 나오는 {nums}만 발췌, 나머지 항 생략)"
    kept = []
    for p, rs in paras.items():
        if kept and len(assemble(kept + rs)) > cap:
            break
        kept += rs
    return assemble(kept) + f"\n(제{ref_num}조의 이하 항 생략)"


# 별표 역참조 — 별표가 발췌(단위·검색 결과)로 들어오면 그 표를 인용하는 조항 본문을 [참조]로 붙인다.
# 참조 그래프(03b)에는 별표로 가는 엣지가 없어(【별표1(…)】 표기를 조문 참조로 뽑지 않는다) 표만 들어가고,
# 모델이 표를 못 읽고 주석만 옮겼다 — 2026-10-18 97문항 판정 R041·R066·R084: 이율표만 받은 정답 발췌 모드에서
# "이자가 붙는다"는 본문을 빼고 "계약자 귀책이면 미지급" 단서만 남겨 뜻이 뒤집혔고, 보통약관 제8조 본문이 함께 들어간
# 검색 모드에서는 맞혔다. 대상은 청크 본문에서 【별표N】을 인용하는 조항(강아지·고양이 같은 구조) 중 반려동물 상담에 쓰는 것.
# 값: (section, section_name, article_num, paragraph_num) — paragraph_num None이면 조 전체
ANNEX_CITED_BY = {
    "【별표1】 보험금을 지급할 때의 적립이율 계산": [
        ("보통약관", None, 8, 5),                                        # 보험금 지급기일 넘기면 별표1 이율로 더해 지급
        ("특별약관", "반려동물 비용손해 관련 특별약관 일반조항", 5, 4),   # 의료비 특약 보험금의 같은 규정
    ],
    "【별표2】 장해분류표": [("보통약관", None, 3, None)],               # 장해지급률 80% 이상 → 가입금액 전액
    "【별표3】 소송목적의 값에 따른 변호사비용": [("특별약관", "민사소송법률비용Ⅱ보장 특별약관", 3, 2)],
    "【별표4】 민사소송 인지액 /【별표5】 송달료": [("특별약관", "민사소송법률비용Ⅱ보장 특별약관", 3, 2)],
}


class ContextBuilder:
    """참조 조문 보강기. 한 번 만들어 여러 단위(검색 결과 청크, FAQ 블록)에 재사용한다."""

    def __init__(self, client: MilvusClient = None, chunks: dict = None, graphs: dict = None,
                 merge_graded: bool = True, whole_ref_cap: int | None = WHOLE_REF_CAP):
        self.merge_graded = merge_graded
        self.whole_ref_cap = whole_ref_cap
        # SearchEngine이 이미 들고 있는 client/chunks를 넘기면 중복 로드하지 않는다
        self.client = client or MilvusClient(uri=MILVUS_URI)
        self.chunks = chunks or {sp: _load_json(p) for sp, p in CHUNK_FILES.items() if p.exists()}
        # 그래프는 청크가 있는 코퍼스만(전처리 전인 코퍼스는 둘 다 없다)
        self.graphs = graphs or {sp: _load_json(p) for sp, p in GRAPH_FILES.items() if sp in self.chunks and p.exists()}
        self._check_graph_keys()

    def _check_graph_keys(self):
        # 03번 키 형식이 바뀌면 graph.get()이 조용히 빈 리스트를 반환하므로, 로드 시점에 정합성을 확인한다
        for sp, g in self.graphs.items():
            chunk_keys = {graph_key(c) for c in self.chunks[sp]}
            orphan = [k for k in g if k not in chunk_keys]
            assert not orphan, f"{sp} 그래프 키가 청크와 불일치: {orphan[:3]}"

    def references_of(self, unit: dict, species: str, source_chunks: list[dict] = None) -> list:
        """그래프 엣지 [ref_num, ref_title, ref_section, ref_section_name, 항, 호] 목록.
        source_chunks가 있으면(05의 여러 레코드 묶음) 레코드별 항 키의 합집합, 없으면 unit 자신의 키."""
        keys = []
        for c in (source_chunks or [unit]):
            k = graph_key(c)
            if k not in keys:
                keys.append(k)
        edges = []
        for k in keys:
            for e in self.graphs[species].get(k, []):
                if e not in edges:
                    edges.append(e)
        return edges

    def source_chunks_of(self, unit: dict, species: str) -> list[dict]:
        """unit 본문을 이루는 원본 청크들(citations 조회용). 04는 청크 1개, 05는 블록의 여러 청크.
        content 비교를 쓰는 이유: (section_name, 조, 항, 등급, chunk_index) 키는 안내류에서 비고유"""
        unit_content = unit["content"]
        return [c for c in self.chunks[species]
                if c.get("article_num") == unit.get("article_num")
                and c["section"] == unit["section"]
                and c.get("section_name") == unit.get("section_name")
                and c.get("coverage_type") == unit.get("coverage_type")
                and c["content"].strip() in unit_content]

    def fetch_article_rows(self, species: str, section: str, section_name: str, article_num: int,
                           coverage_type: str = None, paragraph_num: int = None) -> list[dict]:
        """참조된 조(또는 항)의 Milvus 행들을 원문 순서(항, 분할조각)로. 없으면 등급→항 순으로 조건을 완화.
        article_num이 None이면 조번호 없는 문서(인사규정 별표 등)를 section·section_name으로 가져온다."""
        filter_expr = f'section == "{section}"' + (f' and article_num == {article_num}' if article_num is not None else "")
        if section_name:
            filter_expr += f' and section_name == "{section_name}"'
        ref_type = infer_type_from_section_name(section_name)
        if ref_type:
            filter_expr += f' and type == "{ref_type}"'   # Ⅰ/Ⅱ/Ⅲ 혼동 방지
        if coverage_type:
            filter_expr += f' and coverage_type == "{coverage_type}"'
        if paragraph_num is not None:
            filter_expr += f' and paragraph_num == {paragraph_num}'

        # limit을 넉넉히(조당 최대 33행) — limit=3이면 제목행+1·2항만 남아 3항 이후가 잘렸다
        rows = self.client.query(collection_name=COLLECTION_NAMES[species], filter=filter_expr,
                                 output_fields=["content", "paragraph_num", "chunk_index", "coverage_type"], limit=100)
        if not rows:
            if coverage_type:
                return self.fetch_article_rows(species, section, section_name, article_num, None, paragraph_num)
            if paragraph_num is not None:
                return self.fetch_article_rows(species, section, section_name, article_num, None, None)
            return []
        rows.sort(key=lambda r: (r["paragraph_num"] if r["paragraph_num"] is not None else -1, r["chunk_index"]))
        return rows

    def fetch_article_content(self, species: str, section: str, section_name: str, article_num: int,
                              coverage_type: str = None, paragraph_num: int = None) -> str | None:
        rows = self.fetch_article_rows(species, section, section_name, article_num, coverage_type, paragraph_num)
        if not rows:
            return None
        return strip_leading_title(" ".join(r["content"] for r in rows), article_num)

    def annex_citing_references(self, annex_name: str | None, species: str, seen: set) -> list[dict]:
        """별표를 인용하는 조항 본문(ANNEX_CITED_BY). 표기는 약관 이름을 앞에 붙인다 — 보통약관 제8조와 일반조항 제5조처럼
        같은 규정이 두 약관에 있어 조번호만으로는 어느 약관인지 모른다"""
        out = []
        for sec, sec_name, num, para in ANNEX_CITED_BY.get(annex_name, ()):
            rows = self.fetch_article_rows(species, sec, sec_name, num, None, para)
            if not rows:
                continue
            content = strip_leading_title(" ".join(r["content"] for r in rows), num)
            dedup = (sec, sec_name, num, content)
            if dedup in seen:
                continue
            seen.add(dedup)
            title = next((c.get("article_title") for c in self.chunks[species]
                          if c["section"] == sec and c.get("section_name") == sec_name and c.get("article_num") == num), None)
            out.append({"article_num": num, "article_title": title,
                        "citation_label": f"{sec_name or sec} {reference_label(num, title, para)}",
                        "section_name": sec_name, "paragraph_num": para, "content": content})
        return out

    def resolve_references(self, unit: dict, species: str, source_chunks: list[dict] = None,
                           coverage_hint: str | None = None) -> list[dict]:
        """unit(section, section_name, article_num, coverage_type, content)에 참조 조문과 inline 법령 정의를 붙인다.
        각 항목의 citation_label을 인용 표기로 쓸 것("제{article_num}조(...)" 조립은 법령의 "의N"이 빠진다).
        coverage_hint: 등급 없는 unit이라도 가입 등급을 알면(SearchScope.grade_for) 참조를 그 등급 한 벌만 붙인다.
        None이면 예전과 같다(05·06은 넘기지 않는다)."""
        if source_chunks is None:
            source_chunks = self.source_chunks_of(unit, species)
        unit_content = unit["content"]
        unit_grade = unit.get("coverage_type") or coverage_hint

        enriched_refs = []
        seen = set()
        unit_norm = _norm(unit_content)
        if unit.get("section") == "별표":
            enriched_refs += self.annex_citing_references(unit.get("section_name"), species, seen)
        for ref_num, ref_title, ref_section, ref_section_name, ref_para, ref_ho in self.references_of(unit, species, source_chunks):
            # 그래프가 참조 대상의 section을 직접 담으므로(03번), unit의 section이 아니라 ref의 section으로 조회
            rows = self.fetch_article_rows(species, ref_section, ref_section_name, ref_num,
                                           unit_grade, ref_para)
            # 자기 본문 제외(행 단위): unit 본문에 이미 있는 행은 빼고 나머지만 잇는다
            rows = [r for r in rows if _norm(r["content"]) not in unit_norm]
            if not rows:
                continue
            # 등급 없는 unit이 등급별로 나뉜 조문을 참조하면 고급·기본·실속 3벌이 다 붙는다
            # (예: 통원의료비Ⅲ 제4조 → 제1조 9458자). 같은 행은 한 벌, 다른 부분만 등급별로 병기한다.
            graded = self.merge_graded and unit_grade is None \
                and len({r.get("coverage_type") for r in rows if r.get("coverage_type")}) > 1

            def assemble(rs):
                if graded:
                    return strip_leading_title("\n".join(merge_graded_rows(rs)), ref_num)
                return strip_leading_title(" ".join(r["content"] for r in rs), ref_num)

            ref_content = assemble(rows)
            if self.whole_ref_cap and ref_para is None and len(ref_content) > self.whole_ref_cap:
                ref_content = shorten_whole_reference(unit_content, ref_num, rows, assemble, self.whole_ref_cap)
            dedup = (ref_section, ref_section_name, ref_num, ref_content)
            if dedup in seen:
                continue
            seen.add(dedup)
            enriched_refs.append({
                "article_num": ref_num, "article_title": ref_title,
                # 조번호 없는 참조(인사규정 별표)는 문서 이름으로 표기
                "citation_label": reference_label(ref_num, ref_title, ref_para, ref_ho) if ref_num is not None
                else (ref_section_name or ref_title),
                "section_name": ref_section_name, "paragraph_num": ref_para,
                "content": ref_content,
            })

        for sc in source_chunks:
            for cit in sc.get("citations", []):
                if not cit.get("law_name") or cit.get("article_num") is None:
                    continue
                # 박스는 그 citation이 나온 원본 레코드 안에서만 찾는다 — 05처럼 여러 레코드를 이은 unit에서 찾으면
                # 박스 본문이 '다음 【 또는 끝'까지 이어져 뒤 레코드(예: 2항 보상 비용·한도표)까지 딸려 들어간다
                law_box = extract_inline_law_definition(sc["content"], cit["law_name"], cit["article_num"])
                if law_box and ("법규", law_box) not in seen:
                    seen.add(("법규", law_box))
                    heading, law_content = law_box
                    enriched_refs.append({
                        "article_num": cit["article_num"], "article_title": heading,
                        "citation_label": heading,   # 예: "소득세법 제59조의4(특별세액공제)"
                        "section_name": None, "paragraph_num": None,
                        "content": law_content,
                    })

        # 포함 관계 제거: 같은 조를 조 전체와 특정 항으로 이중 참조하면 항 쪽이 조 전체에 통째로 들어 있다
        norms = [_norm(r["content"]) for r in enriched_refs]
        return [r for i, r in enumerate(enriched_refs)
                if not any(j != i and norms[i] in norms[j] and (len(norms[i]) < len(norms[j]) or j < i)
                           for j in range(len(enriched_refs)))]


# ===== 답변이 실제로 쓴 참조만 고르기 (FAQ 근거 표기·RAG 답변 인용용) =====
_FLAT = re.compile(r"[\s「」『』｢｣()\[\],.·ㆍ'\"“”]")
def _flat_cite(t): return _FLAT.sub("", t or "")

def _longest_shared(ans, ref, exclude=None, minlen=8):
    """답변·참조가 공유하는 일치 구간 중 최장 길이. exclude(단위 본문)에 있는 구간은 세지 않는다"""
    a, r = _flat_cite(ans), _flat_cite(ref)
    best = 0
    for b in SequenceMatcher(None, a, r, autojunk=False).get_matching_blocks():
        if b.size >= minlen and (exclude is None or a[b.a:b.a + b.size] not in exclude):
            best = max(best, b.size)
    return best

def _mostly_inside(content: str, unit_flat: str, n: int = 12, ratio: float = 0.8) -> bool:
    """참조 본문이 단위 본문에서 뽑은 것인가(법령 박스) — 페이지 번호 제거 등으로 완전 포함은 아니므로 12자 조각 80% 기준"""
    f = _flat_cite(content)
    grams = [f[i:i + n] for i in range(0, max(1, len(f) - n + 1), n)]
    return bool(grams) and sum(g in unit_flat for g in grams) / len(grams) >= ratio

def used_references(answer_body: str, refs: list[dict], unit_content: str, minlen: int = 8,
                    unit_article: int | None = None, longest_only: bool = False) -> list[dict]:
    """답변 본문이 실제로 쓴 참조만. (1) 조문 번호 언급(법령은 법명까지, '제118조의4' 포함) 또는
    (2) 답변과 참조 본문이 minlen자 이상 일치하는 구간 — 단위 본문에도 있는 구간은 단위에서 온 것으로 보고 제외한다.
    단, 단위 본문 안에서 뽑은 법령 박스(참조 본문이 단위 본문의 일부)는 제외 없이 일치만 본다.
    longest_only: (2)로만 걸린 것 중 가장 길게 겹친 것만 남긴다(같은 길이면 모두). (1) 언급으로 걸린 것은 그대로.
      서비스(app/services/answer.py)가 발췌를 고를 때 쓴다 — 같은 문구가 여러 발췌에 있으면 전부 걸리던 것을 줄인다
      (2026-10-18 측정: 답변 234건·후보 720개, 실오판 43 → 22). 05·06 근거 표기는 기본값(False) 그대로다."""
    unit_flat = _flat_cite(unit_content)
    hits = []   # (참조, 언급, 겹침 길이)
    for r in refs:
        content = r.get("content") or ""
        m = re.match(r"\s*(.*?)\s*제(\d+)조(의\d+)?", r["citation_label"])
        hang = re.search(r"\)\s*제(\d+)항|조\s*제(\d+)항", r["citation_label"])
        mention = False
        if m:
            law, num, sub = m.group(1), m.group(2), m.group(3) or ""
            if re.match(r"제\d+[장절관]", law):
                # 인사규정 라벨은 장 제목이 앞에 붙는다("제4장 휴일 및 휴가 제20조(병가)") — 법령 이름이 아니다.
                # 법령으로 읽으면 답변에 "제4장 휴일 및 휴가 제20조"가 있어야 해 조문 언급이 늘 안 걸렸다(2026-10-21 HR4)
                law = ""
            pat =(rf"{re.escape(law)}\s*" if law else "") + rf"제\s*{num}\s*조{sub}(?!의)"
            if hang:
                # 항까지 지정된 참조는 그 항을 언급해야 한다 — 같은 조의 다른 항을 인용한 답변에 붙지 않게
                # 같은 조 규칙(아래 or 뒤): 단위와 참조가 같은 조이고, 답변에 '제N조'가 없이 '제k항'만 있으면 언급으로 본다.
                # 알려진 오판(2026-10-18 합성 시험, 고치지 않음): 답변이 단위 본문 문장을 옮기다 그 안의 '제k항'을 함께 옮기면
                # 참조를 쓰지 않았는데도 걸린다. 재현: 단위 = 보통약관 제4조 제2항, 참조 = 제4조(보험금 지급에 관한 세부규정) 제1항,
                # 답변 = "제1항에 따라 장해지급률이 결정되었으나 그 이후 보장을 받을 수 있는 …"(제2항 본문 앞부분) → 제1항이 잡힌다
                h = hang.group(1) or hang.group(2)
                mention = bool(re.search(pat + rf"[^.]{{0,40}}?제\s*{h}\s*항", answer_body)) or (
                    unit_article is not None and int(num) == unit_article
                    and bool(re.search(rf"(?<!조)\s제\s*{h}\s*항", " " + answer_body)) and not re.search(r"제\s*\d+\s*조", answer_body))
            else:
                mention = bool(re.search(pat, answer_body))
        inside_unit = _mostly_inside(content, unit_flat)
        overlap = _longest_shared(answer_body, content, None if inside_unit else unit_flat, minlen)
        hits.append((r, mention, overlap))
    best = max((o for _, _, o in hits), default=0)
    floor = best if longest_only else minlen
    return [r for r, mention, overlap in hits if mention or (overlap >= minlen and overlap >= floor)]


def cross_article_refs(unit: dict, refs: list[dict]) -> tuple[list[dict], list[dict]]:
    """resolve_references 결과를 (다른 조 참조, 나머지)로 나눈다. 나머지 = 단위 본문 안에서 뽑은 법령 박스 +
    같은 문서·같은 조의 다른 항(예: 특약 제1조 실속형 → 제1조 제5항). 05 v1r 프롬프트와 참조 활용도 측정(data/ref_usage.py)이 쓴다"""
    unit_flat = _flat_cite(unit["content"])
    cross, other = [], []
    for r in refs:
        same_article = r.get("article_num") == unit.get("article_num") and r.get("section_name") == unit.get("section_name")
        (other if same_article or _mostly_inside(r.get("content") or "", unit_flat) else cross).append(r)
    return cross, other


def search_with_graph(engine, builder: ContextBuilder, query: str, scope: SearchScope,
                      top_k: int = 5, candidate_k: int = 20) -> list[dict]:
    """Hybrid Search(BM25+Dense) + Reranker 상위 candidate_k개를 섹션 가중으로 재정렬해 top_k개.
    scope: 검색 범위(가입 정보면 SearchScope.for_policies, 질문 속 등급·유형만 쓰려면 SearchScope.from_query)"""
    species = scope.species
    raw_results = engine.search(query, scope, top_k=candidate_k, candidate_k=candidate_k)
    for r in raw_results:
        r["adjusted_score"] = r["score"] * SECTION_PRIORITY.get(r.get("section"), 0.8)
    raw_results.sort(key=lambda r: r["adjusted_score"], reverse=True)

    # 조항 중복 제거(같은 조는 최고점 청크 하나)는 2026-10-19 뺐다 — 답이 든 형제 청크(뒷조각·본문)를 지워
    # 검색 모드 답변 거절이 rebuild3 7/69 → 14/70으로 늘었다. 조 단위 hit@5(88→90)는 이걸 못 봤다
    # (data/review/rebuild4_eval_compare_20261019.md). 검색 변경은 hit@5와 답변 거절률을 함께 잰다.
    # 리랭커 라벨(조 제목 앞붙임)도 2026-10-20 뺐다 — 본문 없는 짧은 조각을 끌어올려 거절 7 → 12/69
    enriched = []
    for r in raw_results[:top_k]:
        enriched.append({
            "score": r["score"], "adjusted_score": r["adjusted_score"],
            "section": r["section"], "section_name": r.get("section_name"),
            "type": r.get("type"),
            "article_num": r.get("article_num"), "article_title": r.get("article_title"),
            "coverage_type": r.get("coverage_type"), "content": r["content"],
            "paragraph_num": r.get("paragraph_num"), "chunk_index": r.get("chunk_index"),
            "context_prefix": r.get("context_prefix"),
            "references": builder.references_of(r, species),
        })
    return enriched


def build_full_context(engine, builder: ContextBuilder, query: str, scope: SearchScope, top_k: int = 3) -> list[dict]:
    """04번 RAG용: 검색 결과마다 reference_contents(참조 조문 + inline 법령 정의)를 붙인다.
    가입 등급을 아는 scope면 등급 없는 결과의 참조도 그 등급 한 벌만 붙는다(coverage_hint)."""
    species = scope.species
    results = search_with_graph(engine, builder, query, scope, top_k=top_k)
    for r in results:
        # 검색 결과는 청크 1개 — content 완전 일치로 원본 청크를 찾는다(측정상 100/100 매칭)
        source = next((c for c in builder.chunks[species]
                       if c["section"] == r["section"]
                       and c.get("section_name") == r.get("section_name")
                       and c.get("article_num") == r.get("article_num")
                       and c.get("coverage_type") == r.get("coverage_type")
                       and c["content"].strip() == r["content"].strip()), None)
        r["reference_contents"] = builder.resolve_references(r, species, [source] if source else [],
                                                             coverage_hint=scope.grade_for(r.get("section_name")))
    return results

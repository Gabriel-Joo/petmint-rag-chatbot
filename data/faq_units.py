"""
faq_units.py
FAQ 생성 단위 구성 — 05번(FAQ 생성)과 06번(품질 검증)이 함께 import한다.
06이 FAQ를 검사하려면 그 FAQ를 만든 단위(원문·참조·레코드)를 05와 똑같이 다시 만들어야 하므로 한곳에 둔다(2026-10-12 05 셀에서 분리).
"""
import re
from collections import defaultdict

# 01번이 이미 구조 경계에서 나눈 레코드를 '조(article_block)·등급' 단위로 모으되, 레코드를 다시 쪼개지 않고
# FAQ_UNIT_MAX 이하로 차례대로 묶는다. (예전: 블록을 "\n\n"으로 이은 뒤 1000자/200자로 재분할 → 이중 분할 + 오버랩 중복)
# 같은 원본의 분할 조각끼리는 그대로 이으면 원문이 되고(오버랩 없음), 다른 항/항목 사이는 빈 줄로 구분한다.
# 2026-10-12 측정: 의료비 제1조를 항 단위로 쪼개도(1500자 묶음 대신) 전체 오류 43% → 46%로 나아지지 않았다(KNOWN_ISSUES).
FAQ_UNIT_MAX = 1500
# 법규(인용 법률 전문)는 FAQ에서 뺀다 — 2026-10-12 샘플 검수: 법규 10건 중 5건이 보험 상담과 무관한 법률 일반 상식
# 질문으로 흘렀다(10세 어린이 책임능력, 6촌 친족 등). 약관이 법규를 인용하는 부분은 참조 조문으로 이미 붙는다.
EXCLUDE_FROM_FAQ: set[str] = {"법규"}

# 사람 대상 조항 — 이 상품의 보통약관은 사람 피보험자의 상해를 보장하는 기본계약(일반상해80%이상후유장해)이라,
# 펫 상담에서 거의 묻지 않는 조항이 섞여 있다(06 최종 QA의 약 19%, 장해분류표 한 표가 12%). 2026-10-13 확정
# (data/review/human_target_candidates_20261013.md). 약관상 효력이 없다는 뜻이 아니라 FAQ·학습에서 뺀다는 뜻이다.
# - 보통약관 제3·4·5·9·10·25·38조: 반려동물 특약 준용규정(일반조항 제22조, 배상책임 일반조항 제17조)이 명시적으로 제외(03-1 excluded_reference)
# - 보통약관 제11·16·22·24조: 사람 피보험자 전용(보험금 받는 방법, 직업·운전 변경, 사망 서면동의, 사람 보험나이) — 반려동물 쪽은 일반조항이 따로 정한다
# - 【별표2】 장해분류표: 본문 인용이 보통약관 제2·3·4조뿐(제3·4조는 위에서 제외)
# - 이륜자동차 운전중 상해 부보장 특별약관: 사람 피보험자의 이륜차 운전 중 상해
EXCLUDE_ARTICLES: set[tuple] = {("보통약관", None, n) for n in (3, 4, 5, 9, 10, 11, 16, 22, 24, 25, 38)}
EXCLUDE_SECTION_NAMES: set[str] = {"【별표2】 장해분류표", "이륜자동차 운전중 상해 부보장 특별약관"}


def is_human_target(d: dict) -> bool:
    """단위·청크·QA 어느 것이든(section, section_name, article_num만 본다) 사람 대상 제외 조항인가"""
    return d.get("section_name") in EXCLUDE_SECTION_NAMES or \
        (d.get("section"), d.get("section_name"), d.get("article_num")) in EXCLUDE_ARTICLES


def _join_records(records: list[dict]) -> str:
    text = ""
    for i, r in enumerate(records):
        same_parent = i > 0 and r["chunk_index"] > 0       # 직전 레코드의 뒷조각
        text += r["content"] if same_parent else (("\n\n" if text else "") + r["content"].strip("\n"))
    return text


def build_faq_units(chunks: list[dict]) -> list[dict]:
    position = {id(c): i for i, c in enumerate(chunks)}   # 원본 청크 목록에서의 위치 — unit_id를 고유하게
    groups = defaultdict(list)          # 삽입 순서 = 문서 순서
    for c in chunks:
        if c["section"] in EXCLUDE_FROM_FAQ:
            continue
        groups[(c.get("article_block_id"), c.get("coverage_type"))].append(c)

    units = []
    for (block_id, coverage_type), recs in groups.items():
        packs, cur = [], []
        for r in recs:
            if cur and len(_join_records(cur + [r])) > FAQ_UNIT_MAX:
                packs.append(cur)
                cur = []
            cur.append(r)
        if cur:
            packs.append(cur)
        for pack in packs:
            first = pack[0]
            units.append({
                "article_block_id": block_id, "coverage_type": coverage_type,
                "section": first["section"], "section_name": first.get("section_name"),
                "type": first.get("type"),
                "article_num": first.get("article_num"),
                "article_title": (first.get("article_title") or "").replace("\n", " ").strip() or None,
                # 묶음이 분할 조각 중간에서 시작하면 그 조각의 맥락(도입 문장/제목 경로)을 앞에 보여준다
                "context_prefix": first.get("context_prefix") if first["chunk_index"] > 0 else None,
                "content": _join_records(pack),
                "records": pack,
                "record_range": (position[id(pack[0])], position[id(pack[-1])]),
            })
    return units


# 준용규정만 있는 단위('이 특별약관에서 정하지 않은 사항은 … 일반조항·보통약관을 따릅니다' 한 문장)는 같은 특약의 바로 앞
# 단위에 붙인다. 2026-10-12 측정(강아지 18단위, QA 판정): 단독 61% 오류(같은 특약 제1조에 있는 자기부담금·한도를
# '명시 안 됨'이라 하거나 상황을 지어냄) → 앞 조와 묶으면 18%. 준용 대상 조문 목록을 붙이는 방식은 41%(틀린 조번호를 단정).
MERGE_JUNYONG_MAX = 300


def merge_junyong_units(units: list[dict]) -> list[dict]:
    out, last_of = [], {}
    for u in units:
        is_jun = (u.get("article_title") or "").startswith("준용") and len(u["content"]) < MERGE_JUNYONG_MAX
        prev = last_of.get(u["section_name"])
        if is_jun and prev is not None:
            p = out[prev]
            label = f"제{u['article_num']}조({u['article_title']})"
            out[prev] = {**p, "content": p["content"] + "\n\n" + u["content"], "records": p["records"] + u["records"],
                         "record_range": (p["record_range"][0], u["record_range"][1]),
                         "merged_refs": p.get("merged_refs", []) + [{"citation_label": label, "content": u["content"],
                                                                      "section_name": u["section_name"], "paragraph_num": None,
                                                                      "article_num": u["article_num"]}]}
            continue
        last_of[u["section_name"]] = len(out)
        out.append(u)
    return out


# 조 첫머리의 도입 문장만 남은 단위('… 용어의 정의는 … 다음과 같습니다.')는 FAQ에서 뺀다 — 뒤 레코드(정의 표)를 붙이면
# FAQ_UNIT_MAX를 넘어 혼자 묶인 것이다. 2026-10-13 전량 생성: 일반조항 제2조 도입 문장(73자) 단위에서 강아지 21/21이
# 정의를 지어냈고(심판 fabricated·incomplete), 고양이도 1/24만 남았다(그 1건도 '다른 조항에서 규정'이라는 회피).
# 정의는 뒤 단위들(r245~)에 있어 주제가 빠지지 않는다. 앞뒤 단위에 합치지 않는 이유: 합친 단위의 unit_id가 바뀌어
# 이미 생성한 QA가 06에서 '현재 데이터에 없는 단위'로 버려진다. 해당 단위는 종마다 1개(측정).
INTRO_ONLY_MAX = 100


def is_intro_only(unit: dict) -> bool:
    text = unit["content"].strip()
    return len(text) <= INTRO_ONLY_MAX and re.search(r"(다음|아래)(과|와) 같습니다\.?$", text) is not None


def intro_only_unit_ids(chunks: list[dict]) -> set[str]:
    """make_units가 뺀 도입 문장 단위 — 06이 그 단위의 기존 QA를 '제외 단위'로 표시하는 데 쓴다"""
    return {unit_id(u) for u in merge_junyong_units(build_faq_units(chunks)) if is_intro_only(u)}


def human_target_unit_ids(chunks: list[dict]) -> set[str]:
    """make_units가 뺀 사람 대상 조항 단위 — 06이 기존 QA를 '제외 단위'로 표시하는 데 쓴다"""
    return {unit_id(u) for u in merge_junyong_units(build_faq_units(chunks)) if is_human_target(u)}


def make_units(chunks: list[dict]) -> list[dict]:
    """05·06이 쓰는 최종 단위 = 레코드 묶음 + 준용규정 병합 − 도입 문장 단위 − 사람 대상 조항.
    제외는 묶은 뒤에 하므로 다른 단위의 unit_id(레코드 위치 범위)는 바뀌지 않는다 — 기존 QA가 그대로 맞는다."""
    return [u for u in merge_junyong_units(build_faq_units(chunks)) if not is_intro_only(u) and not is_human_target(u)]


def unit_id(unit: dict) -> str:
    """단위 식별자. 조번호 없는 단위(안내류·별표)는 섹션·조·항이 전부 같아 겹치므로 원본 레코드 위치 범위를 넣는다"""
    first, last = unit["record_range"]
    return f"{unit['section']}|{unit.get('section_name')}|{unit.get('article_num')}|{unit.get('coverage_type')}|r{first}-{last}"


def main_label(unit: dict) -> str:
    """메인 출처 표기. 법규는 법명까지(약관 조번호와 혼동 방지), 안내형은 섹션명."""
    if unit.get("article_num") is None:
        return unit.get("section_name") or unit["section"]
    label = f"제{unit['article_num']}조({unit['article_title']})" if unit.get("article_title") else f"제{unit['article_num']}조"
    if unit["section"] == "법규":
        law = (unit.get("section_name") or "").split("】")[-1].strip()
        label = f"{law} {label}".strip()
    if unit.get("coverage_type"):
        label += f" {unit['coverage_type']}"
    return label


def build_citation_suffix(unit: dict, used_refs: list[dict]) -> str:
    """메인 출처 + 답변이 실제로 쓴 참조 조문만(rag_context.used_references로 고른 것). 참조 표기는 citation_label —
    '제{article_num}조(...)' 조립은 법령의 '의N'이 빠져 다른 조문을 가리킨다(소득세법 제59조 ≠ 제59조의4)."""
    parts = [main_label(unit)]
    for ref in used_refs:
        if ref["citation_label"] not in parts:
            parts.append(ref["citation_label"])
    return "근거: " + ", ".join(parts)

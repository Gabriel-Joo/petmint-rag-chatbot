"""
tables.py
답 아래 표 붙이기(2026-10-22) — 모델이 답한 턴에서, 답이 실제로 쓴 발췌에 표가 있으면 코드가 그 표를 그대로 보내고 질문에 맞는 행을
강조한다. 모델이 표를 그리면 숫자를 틀린다(사내규정 HR3 30만원 오답). 숫자는 발췌 원문 그대로다.

- 표: 발췌 본문의 Markdown 표(01의 [표], 청크 v3가 공백 정렬 배치표를 바꾼 것 포함). 머리행 + 행
- 어느 발췌: answer.pick_excerpts가 고른 것(답이 쓴 발췌)만 — 쓰지 않은 발췌의 표는 붙이지 않는다
- 행 강조: 행마다 점수 — ① 질문 금액이 행의 구간(초과·까지·이하)에 들면 3 ② 고객 가입 등급·통원/입원 낱말이 행에 있으면 1
  ③ 행 이름(첫 칸)의 낱말이 질문에 있거나, 질문 낱말(동의어 사전으로 넓힘)이 행 이름에 있으면 낱말마다 1. 1등이 혼자이고 1점 이상일 때만 강조(애매하면 강조하지 않는다)
- 크기: 12행·6열을 넘으면 머리행 + 강조한 행 앞뒤 1행만 보내고 접힘 표시(collapsed). 강조가 없으면 앞 12행만 + 접힘
- 카드 턴(코드 답)에는 붙이지 않는다 — _generate의 모델 답 뒤에서만 부른다
"""

import re

from app.schemas import Pet, TableItem
from app.services import dayparse, payout

MAX_ROWS, MAX_COLS = 12, 6
_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_SEP = re.compile(r"^\s*\|?\s*:?-{2,}")
_WORD = re.compile(r"[가-힣A-Za-z]{2,}")
_STOP = {"보험", "보험금", "계약", "회사", "비용", "부분", "얼마", "얼마나", "어떻게", "되나요", "나와요", "있나요", "받을", "경우", "보장", "보상", "하면", "인데",
         "우리", "강아지", "고양이", "강아지가", "고양이가", "가입", "했는데"}


def parse_tables(text: str) -> list[dict]:
    """Markdown 표 → [{"header": [...], "rows": [[...]]}]. 구분줄(|---|)이 머리행 바로 뒤에 있는 것만"""
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines) - 1:
        if _ROW.match(lines[i]) and _SEP.match(lines[i + 1]):
            header = [c.strip() for c in _ROW.match(lines[i]).group(1).split("|")]
            rows, j = [], i + 2
            while j < len(lines) and _ROW.match(lines[j]):
                rows.append([c.strip() for c in _ROW.match(lines[j]).group(1).split("|")])
                j += 1
            if rows:
                out.append({"header": header, "rows": rows})
            i = j
        else:
            i += 1
    return out


def _range_hit(cell: str, value: int) -> bool:
    """'300만원을 초과하여 2,000만원까지 부분' · '300만원까지 부분' · '5억원을 초과하는 부분'에 value가 드는가"""
    amounts = payout.amounts_in(cell.split("[")[0])
    if not amounts:
        return False
    if "초과" in cell and len(amounts) >= 2:
        return amounts[0] < value <= amounts[1]
    if "초과" in cell:
        return value > amounts[0]
    if re.search(r"까지|이하", cell):
        return value <= amounts[0]
    return False


def _terms(question: str) -> set[str]:
    from data.synonyms import ENTRIES
    words = {w for w in _WORD.findall(question) if w not in _STOP}
    for e in ENTRIES:
        if e.trigger.search(question):
            words |= {w for w in re.split(r"\s+", e.expand) if len(w) >= 2}
    return words


def highlight(table: dict, question: str, pet: Pet | None) -> int | None:
    values = payout.amounts_in(question) or [a.value for a in dayparse.amounts(question)]   # '1억짜리'처럼 '원' 없는 금액도
    grades = {p.coverage_type for p in pet.policies if p.coverage_type} if pet else set()
    settings = [w for w in ("통원", "입원") if w in question]
    terms = _terms(question)
    qflat = re.sub(r"\s+", "", question)
    scores = []
    for row in table["rows"]:
        first, joined = re.sub(r"\s+", "", row[0]), re.sub(r"\s+", "", " ".join(row))
        s = 3 * any(_range_hit(row[0], v) for v in values)
        s += any(g in joined for g in grades) + any(w in joined for w in settings)
        # 행 이름의 낱말이 질문에 있거나(조사가 붙어도 — '피보험자가'), 질문 낱말·동의어가 행 이름에 있으면
        s += len({w for w in _WORD.findall(row[0]) if w not in _STOP and w in qflat} | {t for t in terms if t in first})
        s += 2 * (len(first) >= 2 and first in qflat)            # 행 이름 전체가 질문에('보험수익자') — 낱말 하나보다 강하다
        scores.append(s)
    if not scores:
        return None
    top = max(scores)
    return scores.index(top) if top >= 1 and scores.count(top) == 1 else None


def trim(table: dict, hl: int | None) -> tuple[list[list[str]], list[int], bool]:
    """(보낼 행, 그 행의 원래 번호, 접힘) — 크면 강조 행 앞뒤 1행, 강조가 없으면 앞 MAX_ROWS행"""
    rows = table["rows"]
    if len(rows) <= MAX_ROWS:
        return rows, list(range(len(rows))), False
    idx = list(range(max(0, hl - 1), min(len(rows), hl + 2))) if hl is not None else list(range(MAX_ROWS))
    return [rows[i] for i in idx], idx, True


def answer_tables(chosen_texts: list[tuple[str, str]], question: str, pet: Pet | None) -> list[TableItem]:
    """chosen_texts = [(발췌 라벨, 발췌 본문)] — 답이 쓴 발췌만. 표마다 TableItem"""
    out = []
    for label, text in chosen_texts:
        for t in parse_tables(text):
            hl = highlight(t, question, pet)
            rows, idx, collapsed = trim(t, hl)
            cols = len(t["header"])
            out.append(TableItem(source=label, header=t["header"][:MAX_COLS], rows=[r[:MAX_COLS] for r in rows],
                                 row_index=idx, highlight=hl, total_rows=len(t["rows"]),
                                 collapsed=collapsed or cols > MAX_COLS))
    return out

"""
article_display.py
근거 패널의 약관 원문 표시(2026-10-28) — PDF 2단 조판에서 뽑은 글을 읽기 좋은 블록으로 바꾼다. **표시만**이다:
원문(Milvus 행·청크)·검색·발췌·프롬프트는 그대로이고, 조항 원문 API(ArticleOut.blocks)와 근거 목록(SourceItem.snippet)에 칸을 더할 뿐이다.
인사규정은 1단·조 단위라 이미 깨끗해 쓰지 않는다. 조사·시안·정확도는 data/review/article_display_survey.md.

- 줄 잇기: PDF 줄바꿈은 낱말 중간("「동물⏎병원」")일 수도, 띄어쓰기 자리("반려동물에게⏎질병")일 수도 있다. 같은 약관에서 붙인 꼴과
  띄운 꼴 중 많은 쪽 → 같으면 뒤가 조사·어미면 붙임, 앞이 조사·어미면 띄움, 뒤가 따로 쓰이는 낱말이면 띄움(인공 줄바꿈 2,494곳 91.0%)
- 쪽 넘김 빈 줄: 문장 중간이고 뒤가 항목·박스·표가 아니면 지운다
- 등급 여러 벌: 행의 coverage_type으로 나눈다(가입 등급을 먼저, 나머지는 화면이 접는다). 항 머리: 항이 둘 이상이면 "제N항"
  (항 안의 호가 ①을 쓰므로 항에 ①을 붙이지 않는다). 같은 항의 분할 행은 줄바꿈으로 먼저 잇는다
- 【】 박스(정의·법령·예시), 공백 정렬 표 → 표, 박스 뒤 흩어진 그림 글자 → 고정폭 묶음, 사설 글리프 제거
"""

import re
from collections import Counter

PART = re.compile(r"(?:은|는|이|가|을|를|의|에|에게|에서|로|으로|와|과|도|만|및|등|고|며|면|서|다|지|요|한|된|할|될|인|하여|하고|경우|때|후|중|"
                  r"부터|까지|이며|이고|이나|나|든지|라도|,|\)|」)$")
ATTACH = re.compile(r"^(?:이|가|을|를|의|에|에서|에게|로|으로|와|과|은|는|도|만|이라|라|이나|하여|하는|한|할|된|되는|됩니다|합니다|입니다|니다|다\.|다)")
END = re.compile(r"(?:다\.|요\.|[.:])\s*$")
ITEM = re.compile(r"^\s*(?:[①-⑳]|\d+\.\s|·|※|-\s)")
KOR_ITEM = re.compile(r"^\s*[가나다라마바사아자차카타파하]\.\s")      # 가. 나. — 앞 줄이 문장 끝일 때만 항목("산후⏎기. 그러나"는 아니다)
BOX = re.compile(r"^\s*【")
PRIVATE = re.compile("[-]")
PET = ("강아지", "고양이")


EDGE = re.compile(r"^[「『(\[<〈\"']+|[」』)\]>〉\"',.:;·]+$")


def _core(w: str) -> str:
    """낱말 앞뒤 괄호·따옴표·문장부호를 뗀다 — "「동물"+"병원」이라"도 "동물"+"병원"으로 센다"""
    return EDGE.sub("", EDGE.sub("", w))


class Vocab:
    """약관 말뭉치의 낱말·두 낱말 빈도 — 줄 잇기에서 붙일지 띄울지 정한다(앱이 기동 때 읽은 청크로 만든다).
    낱말 그대로와, 앞뒤 부호를 뗀 꼴(core)을 함께 센다 — 그대로는 동률(0:0)일 때가 많다(「동물⏎병원」)"""

    def __init__(self, chunks: dict[str, list[dict]]):
        self.tok, self.bi, self.ctok, self.cbi = Counter(), Counter(), Counter(), Counter()
        self.excluded = ""                                     # 정확도 측정용 — 잰 줄 자신을 글자열 빈도에서 뺀다
        self._sub: dict[str, int] = {}
        seen = set()
        for sp in PET:
            for c in chunks.get(sp, []):
                for text in (c.get("content"), c.get("parent_content")):
                    for line in (text or "").split("\n"):
                        line = line.strip()
                        if line and line not in seen:
                            seen.add(line)
                            self.remember(line)
        self.text = "\n".join(seen)                           # 줄 단위 — 줄바꿈 너머는 세지 않는다

    def remember(self, line: str, k: int = 1) -> None:
        ws = line.split()
        cs = [_core(w) for w in ws]
        for c, xs in ((self.tok, ws), (self.ctok, cs)):
            for x in xs:
                c[x] += k
        for c, xs in ((self.bi, ws), (self.cbi, cs)):
            for x in zip(xs, xs[1:]):
                c[x] += k

    def forget(self, line: str) -> None:
        self.remember(line, -1)
        self.excluded = line

    def restore(self, line: str) -> None:
        self.remember(line)
        self.excluded = ""

    def sub_count(self, pat: str) -> int:
        if pat not in self._sub:
            self._sub[pat] = self.text.count(pat)
        return self._sub[pat] - (self.excluded.count(pat) if self.excluded else 0)

    def space_between(self, left: str, right: str) -> bool:
        # ① 줄바꿈 양옆 한글 두 글자씩의 글자열 빈도 — "동물⏎병원": "동물병원"(동물병원에서·동물병원 진료비…)이 "동물 병원"보다 많다.
        #   같은 문장이 등급마다 같은 자리에서 끊겨 낱말 빈도로는 동률이 많았다(「동물⏎병원」이라)
        ha, hb = re.search(r"[가-힣]{1,2}$", left.rstrip()), re.match(r"[가-힣]{1,2}", right.lstrip())
        if ha and hb and len(ha[0]) + len(hb[0]) >= 3:
            joined, spaced = self.sub_count(ha[0] + hb[0]), self.sub_count(ha[0] + " " + hb[0])
            if joined != spaced and max(joined, spaced) >= 2:
                return spaced > joined
        a, b = left.split()[-1], right.split()[0]
        joined, spaced = self.tok[a + b], self.bi[(a, b)]
        if joined != spaced:
            return spaced > joined
        ca, cb = _core(a), _core(b)
        if ca and cb and (ca, cb) != (a, b):
            joined, spaced = self.ctok[ca + cb], self.cbi[(ca, cb)]
            if joined != spaced:
                return spaced > joined
        if ATTACH.match(b):
            return False
        if PART.search(a):
            return True
        return self.tok[b] > 0


_VOCAB: dict[int, Vocab] = {}


def vocab(chunks: dict[str, list[dict]]) -> Vocab:
    key = id(chunks)
    if key not in _VOCAB:
        _VOCAB.clear()
        _VOCAB[key] = Vocab(chunks)
    return _VOCAB[key]


def _is_table_line(line: str) -> bool:
    return bool(re.search(r"\S {3,}\S", line)) and len(line.strip()) > 6


def _is_fig_line(line: str) -> bool:
    return len(line) - len(line.lstrip()) >= 8 or (len(line.strip()) <= 14 and bool(re.search(r"\s{6,}", line)))


def _heal(lines: list[str]) -> list[str]:
    """쪽 넘김 빈 줄 — 앞 줄이 문장 중간이고, 빈 줄 뒤 첫 줄이 항목·박스·표가 아니면 그 빈 줄들을 지운다"""
    out, k = [], 0
    while k < len(lines):
        if not lines[k].strip() and out and out[-1].strip() and not END.search(out[-1]) and not BOX.match(out[-1]):
            j = k
            while j < len(lines) and not lines[j].strip():
                j += 1
            nxt = lines[j] if j < len(lines) else ""
            if nxt and not ITEM.match(nxt) and not BOX.match(nxt) and not _is_table_line(nxt):
                k = j
                continue
        out.append(lines[k])
        k += 1
    return out


def _paragraphs(lines: list[str], v: Vocab) -> list[dict]:
    """줄 → 문단. 항목 줄(①·1.·※·· , 문장 끝 뒤의 가.)은 새 문단, 나머지는 PDF 줄바꿈이라 잇는다"""
    out: list[dict] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if not out or ITEM.match(line) or (KOR_ITEM.match(line) and END.search(out[-1]["text"])):
            out.append({"kind": "p", "text": s, "item": bool(ITEM.match(line) or KOR_ITEM.match(line))})
        else:
            out[-1]["text"] += (" " if v.space_between(out[-1]["text"], s) else "") + s
    return out


def blocks_of(text: str, v: Vocab) -> list[dict]:
    """한 항(또는 조) 글 → 블록 [{kind: p|box|table, …}]"""
    lines = _heal(PRIVATE.sub("", text).split("\n"))
    out: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if BOX.match(line):                                   # 박스: 제목(】까지) + 빈 줄 전까지 + 뒤의 그림 글자
            title = line.strip()
            i += 1
            while "】" not in title and i < len(lines):
                title += lines[i].strip()
                i += 1
            body = []
            while i < len(lines) and lines[i].strip() and not BOX.match(lines[i]):
                body.append(lines[i])
                i += 1
            fig = []
            while i < len(lines) and (not lines[i].strip() or _is_fig_line(lines[i])) and not re.match(r"^\s*(?:【|※)", lines[i]):
                if lines[i].strip():
                    fig.append(lines[i].rstrip())
                i += 1
            name = title.strip().strip("【】").strip()
            out.append({"kind": "box", "title": name, "example": "예시" in name, "paras": _paragraphs(body, v),
                        "figure": "\n".join(fig) or None})
            continue
        if _is_table_line(line) and i + 1 < len(lines) and _is_table_line(lines[i + 1]):
            rows = []
            while i < len(lines) and _is_table_line(lines[i]):
                rows.append([c.strip() for c in re.split(r" {3,}", lines[i].strip())])
                i += 1
            out.append({"kind": "table", "rows": rows})
            continue
        para = []
        while (i < len(lines) and lines[i].strip() and not BOX.match(lines[i])
               and not (_is_table_line(lines[i]) and i + 1 < len(lines) and _is_table_line(lines[i + 1]))):
            para.append(lines[i])
            i += 1
        out += _paragraphs(para, v)
    return out


def article_sections(rows: list[dict], mine: str | None, v: Vocab) -> list[dict]:
    """조의 Milvus 행(fetch_article_rows) → 등급 묶음 [{grade, mine, blocks}]. 가입 등급(mine)을 먼저"""
    by: dict[str | None, list[dict]] = {}
    for r in rows:
        by.setdefault(r.get("coverage_type"), []).append(r)
    out = []
    for grade in sorted(by, key=lambda g: (g != mine, g is None, g or "")):
        merged: dict[int | None, list[str]] = {}
        for r in by[grade]:                                   # 같은 항의 분할 행은 줄바꿈으로 잇는다 — 항목 하나가 두 행에 걸친다
            merged.setdefault(r.get("paragraph_num"), []).append(r["content"])
        multi = len(merged) > 1
        blocks: list[dict] = []
        for pn, parts in merged.items():
            if multi and pn is not None:
                blocks.append({"kind": "label", "text": f"제{pn}항"})
            blocks += blocks_of("\n".join(parts), v)
        out.append({"grade": grade, "mine": grade is not None and grade == mine, "blocks": blocks})
    return out


def snippet(text: str, v: Vocab) -> str:
    """접힌 미리보기(2줄) — 줄을 이은 평문"""
    paras = []
    for b in blocks_of(text, v):
        if b["kind"] == "p":
            paras.append(b["text"])
        elif b["kind"] == "box":
            paras.append(b["title"] + " " + " ".join(p["text"] for p in b["paras"]))
        else:
            paras.append(" ".join(" ".join(r) for r in b["rows"]))
    return " ".join(paras)

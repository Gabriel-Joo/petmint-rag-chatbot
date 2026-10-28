"""
article_display_survey.py
근거 패널 '원문'(GET /api/articles — ContextBuilder.fetch_article_content)의 표시 문제를 유형별로 센다(2026-10-28). 데이터는 바꾸지 않는다.

  python -m scripts.article_display_survey [--out data/review/article_display_survey.md]
"""

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

from pymilvus import MilvusClient

from app import config
from app.services import policy_data
from data.rag_context import ContextBuilder

ROOT = Path(__file__).resolve().parent.parent
HANGUL = re.compile(r"[가-힣]")
MARK = re.compile(r"^\s*(?:[①-⑳]|\d+\.|[가-하]\.|※|【|\||-|·|<|\(\d+\)|제\d+조)")
END = re.compile(r"(?:다\.|요\.|[.:)）」』】]|합니다|한다)\s*$")


def survey(text: str, rows: list[dict]) -> Counter:
    c = Counter()
    lines = text.split("\n")
    for a, b in zip(lines, lines[1:]):
        if a.strip() and b.strip() and not END.search(a) and not MARK.match(b):
            c["문장 중간 줄바꿈"] += 1
            if HANGUL.search(a.rstrip()[-1:]) and HANGUL.match(b.strip()[:1]):
                c["  그중 낱말 중간 끊김(한글-한글)"] += 1
    c["빈 줄 2개 이상 연속"] = len(re.findall(r"\n\s*\n\s*\n", text))
    c["공백 정렬 표 줄"] = sum(1 for l in lines if len(re.findall(r"\S {3,}\S", l)) >= 1 and len(l.strip()) > 10)
    c["인용·정의 박스【】"] = len(re.findall(r"^\s*【[^】]+】\s*$", text, re.M))
    c["예시 블록"] = len(re.findall(r"^\s*[<〈(（\[]?\s*예\s*시\s*[>〉)）\]]?", text, re.M))
    c["행 이어 붙임(공백 하나로 다음 행)"] = max(0, len(rows) - 1)
    grades = {r.get("coverage_type") for r in rows if r.get("coverage_type")}
    if len(grades) > 1:
        c["등급별 같은 조 여러 벌(이름표 없음)"] = 1
        c["  그 벌 수"] = len(grades)
    paras = {}
    for r in rows:
        paras.setdefault((r.get("coverage_type"), r.get("paragraph_num")), r)
    c["항 기호(①…) 없이 시작하는 항"] = sum(1 for (g, p), r in paras.items() if p is not None and not re.match(r"\s*[①-⑳]", r["content"]))
    c["사설 글리프·제어문자"] = len(re.findall(r"[-\x00-\x08]", text))
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data/review/article_display_survey.md"))
    a = ap.parse_args()
    chunks, graphs = policy_data.load()
    b = ContextBuilder(client=MilvusClient(uri=config.MILVUS_URL), chunks=chunks, graphs=graphs)
    total, arts, examples = Counter(), Counter(), defaultdict(list)
    n = 0
    for sp in ("강아지", "고양이"):
        keys = sorted({(c["section"], c.get("section_name"), c.get("article_num")) for c in chunks[sp] if c.get("article_num") is not None},
                      key=lambda k: (k[0], k[1] or "", k[2]))
        for sec, name, num in keys:
            rows = b.fetch_article_rows(sp, sec, name, num)
            text = b.fetch_article_content(sp, sec, name, num)
            if not text:
                continue
            n += 1
            c = survey(text, rows)
            total.update(c)
            for k, v in c.items():
                if v:
                    arts[k] += 1
                    if len(examples[k]) < 3:
                        examples[k].append(f"{sp} {(name or sec)[-18:]} 제{num}조")
    L = [f"# 근거 패널 원문 표시 문제 — 유형별 (조 {n}개, 강아지·고양이)", "", "| 유형 | 건수 | 걸린 조 | 예 |", "|---|---|---|---|"]
    for k in ["문장 중간 줄바꿈", "  그중 낱말 중간 끊김(한글-한글)", "행 이어 붙임(공백 하나로 다음 행)", "등급별 같은 조 여러 벌(이름표 없음)",
              "  그 벌 수", "항 기호(①…) 없이 시작하는 항", "인용·정의 박스【】", "공백 정렬 표 줄", "빈 줄 2개 이상 연속", "예시 블록", "사설 글리프·제어문자"]:
        L.append(f"| {k} | {total[k]} | {arts[k]} | {', '.join(examples[k])} |")
    Path(a.out).write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()

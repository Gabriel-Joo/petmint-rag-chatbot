// 근거 패널 약관 원문(2026-10-28) — 서버가 만든 표시용 블록(ArticleOut.sections)을 그린다. 원문 글자는 바꾸지 않는다:
// 줄 잇기·박스·표·등급 묶음은 app/services/article_display.py. 블록이 없으면(인사규정·옛 응답) 원문을 그대로 보인다.
// 등급별로 다른 조(의료비 특약 제1조)는 가입 등급을 먼저 펼치고 다른 등급은 접는다 — 상담원이 그 고객의 한도를 바로 본다

import { useState } from "react";
import type { ArticleBlock, ArticleSection } from "../api/types";
import s from "./ArticleText.module.css";

function Block({ b }: { b: ArticleBlock }) {
  if (b.kind === "label") return <div className={s.label}>{b.text}</div>;
  if (b.kind === "p") return <p className={b.item ? s.item : s.p}>{b.text}</p>;
  if (b.kind === "table") {
    const [head, ...body] = b.rows ?? [];
    return (
      <div className={s.tableWrap}>
        <table className={s.table}>
          {head && <thead><tr>{head.map((c, i) => <th key={i}>{c}</th>)}</tr></thead>}
          <tbody>{body.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
        </table>
      </div>
    );
  }
  return (
    <div className={`${s.box} ${b.example ? s.example : ""}`}>
      <div className={s.boxTitle}>{b.title}</div>
      {(b.paras ?? []).map((p, i) => <Block key={i} b={p} />)}
      {b.figure && <pre className={s.figure}>{b.figure}</pre>}
    </div>
  );
}

function Section({ sec, multi }: { sec: ArticleSection; multi: boolean }) {
  const [open, setOpen] = useState(sec.mine || !multi);
  return (
    <div className={s.section}>
      {multi && sec.grade && (
        <button className={`${s.grade} ${sec.mine ? s.mine : ""}`} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          <span aria-hidden>{open ? "▾" : "▸"}</span> {sec.grade}{sec.mine && " · 가입 등급"}
        </button>
      )}
      {open && sec.blocks.map((b, i) => <Block key={i} b={b} />)}
    </div>
  );
}

export function ArticleText({ sections, content }: { sections?: ArticleSection[] | null; content: string }) {
  if (!sections?.length) return <div className={s.raw}>{content}</div>;
  const multi = sections.length > 1;
  return <div className={s.doc}>{sections.map((sec, i) => <Section key={sec.grade ?? i} sec={sec} multi={multi} />)}</div>;
}

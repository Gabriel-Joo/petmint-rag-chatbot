import { useState } from "react";
import { ApiError, getArticle } from "../api/client";
import type { ReferenceItem, SourceItem } from "../api/types";
import s from "./SourcePanel.module.css";

interface Props {
  items: SourceItem[];
  references: ReferenceItem[];
  /** side = PC 오른쪽 2단 패널, inline = 모바일·대화창의 답변 아래 접힌 영역(09 2-3). 같은 데이터, 배치만 다르다 */
  variant: "side" | "inline";
}

const sameArticle = (a: SourceItem, r: ReferenceItem) =>
  a.species === r.species && a.section === r.section && a.section_name === r.section_name && a.article_num === r.article_num;

function itemLabel(it: SourceItem) {
  const num = it.article_num === null ? "" : `제${it.article_num}조`;
  const title = it.article_title ? `(${it.article_title})` : "";
  return `${num}${title}` || it.section_name || it.section;
}

// 같은 조항을 다시 펼칠 때 다시 부르지 않는다
const articleCache = new Map<string, string>();

function SourceRow({ it, used }: { it: SourceItem; used: boolean }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState<string | null>(articleCache.get(it.graph_key) ?? null);
  const [error, setError] = useState<string | null>(null);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (!next || text !== null) return;
    try {
      const a = await getArticle(it.species, it.section, it.section_name, it.article_num, { coverage_type: it.coverage_type });
      articleCache.set(it.graph_key, a.content);
      setText(a.content);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  };

  return (
    <li className={`${s.item} ${used ? s.used : ""}`}>
      <button className={s.itemBtn} onClick={toggle} aria-expanded={open}>
        <span className={s.label}>{itemLabel(it)}</span>
        <span className={s.meta}>
          <span>{it.section_name ?? it.section}</span>
          {it.coverage_type && <span>{it.coverage_type}</span>}
          {used && <span className={s.badge}>답변에 쓰임</span>}
        </span>
        {!open && <span className={s.snippet}>{it.content}</span>}
      </button>
      {open && (
        <div className={s.full}>
          {error ? <span className={s.err}>{error}</span> : text ?? "불러오는 중…"}
        </div>
      )}
    </li>
  );
}

export function SourcePanel({ items, references, variant }: Props) {
  const list = (
    <ul className={s.list} style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {items.map((it) => (
        <SourceRow key={it.graph_key} it={it} used={references.some((r) => sameArticle(it, r))} />
      ))}
    </ul>
  );

  if (variant === "inline") {
    if (!items.length) return null;
    return (
      <details className={s.inline}>
        <summary>근거 조항 {items.length}건</summary>
        {list}
      </details>
    );
  }
  return (
    <section className={s.panel} aria-label="근거 조항">
      <div className={s.head}>
        <span>근거 조항</span>
        {items.length > 0 && <span>{items.length}건</span>}
      </div>
      {items.length ? list : <div className={s.empty}>질문하면 검색된 조항이 여기 뜹니다.</div>}
    </section>
  );
}

import type { TableItem } from "../api/types";
import s from "./AnswerTable.module.css";

/** 답이 쓴 발췌의 표 — 서버(tables.py)가 발췌 원문 그대로 보낸다. 질문에 맞는 행은 강조. 모델이 그린 표가 아니다 */
export function AnswerTable({ item }: { item: TableItem }) {
  return (
    <div className={`raised ${s.card}`} aria-label={`표 · ${item.source}`}>
      <div className={s.title}>표 · {item.source}</div>
      <div className={s.wrap}>
        <table className={s.table}>
          <thead><tr>{item.header.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
          <tbody>
            {item.rows.map((r, i) => (
              <tr key={item.row_index[i]} className={item.row_index[i] === item.highlight ? s.hl : undefined}>
                {r.map((c, j) => <td key={j}>{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {item.collapsed && <div className={s.note}>전체 {item.total_rows}행 중 {item.rows.length}행 — 나머지는 근거 패널의 원문에서 볼 수 있습니다</div>}
    </div>
  );
}

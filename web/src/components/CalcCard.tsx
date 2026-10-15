import type { CalcResult } from "../api/types";
import { shortSection, won } from "../format";
import s from "./CalcCard.module.css";

/** 계산 카드(09 2-3) — 서버 limit_table 결과를 그대로 보여준다. 모델은 계산에 손대지 않는다 */
export function CalcCard({ calc }: { calc: CalcResult }) {
  return (
    <div className={`raised ${s.card}`} aria-label="예상 보험금 계산">
      <div className={s.title}>예상 보험금 · {shortSection(calc.section_name)} {calc.coverage_type}</div>
      <div className={s.row}><span className="dim">청구 치료비</span><span>{won(calc.claimed)}</span></div>
      <div className={s.row}><span className="dim">자기부담금</span><span>− {won(calc.copay)}</span></div>
      <div className={s.row}><span className="dim">지급 한도</span><span>{won(calc.limit)}</span></div>
      <div className={`${s.row} ${s.total}`}><span>예상 지급액</span><span>{won(calc.payout)}</span></div>
      <div className={s.note}>{calc.note}</div>
    </div>
  );
}

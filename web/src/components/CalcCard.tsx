import type { CalcResult, LegalCalc, MedicalCalc } from "../api/types";
import { shortSection, won } from "../format";
import s from "./CalcCard.module.css";

/** 금액이 모델 답변이 아니라 약관 표에서 나왔다는 표시 — 답변이 거절하거나 다른 금액을 말해도 카드가 무엇인지 알 수 있게 */
const BASIS = "금액은 약관 표로 계산한 값";

/** 계산 카드(09 2-3) — 서버 limit_table 결과를 그대로 보여준다. 모델은 계산에 손대지 않는다. kind로 의료비·법률비용을 가른다 */
export function CalcCard({ calc }: { calc: CalcResult }) {
  return calc.kind === "legal" ? <LegalCard calc={calc} /> : <MedicalCard calc={calc} />;
}

function MedicalCard({ calc }: { calc: MedicalCalc }) {
  return (
    <div className={`raised ${s.card}`} aria-label="예상 보험금 계산">
      <div className={s.title}>예상 보험금 · {shortSection(calc.section_name)} {calc.coverage_type}</div>
      <div className={s.basis}>{BASIS}</div>
      <div className={s.row}><span className="dim">청구 치료비</span><span>{won(calc.claimed)}</span></div>
      <div className={s.row}><span className="dim">자기부담금</span><span>− {won(calc.copay)}</span></div>
      <div className={s.row}><span className="dim">지급 한도</span><span>{won(calc.limit)}</span></div>
      <div className={`${s.row} ${s.total}`}><span>예상 지급액</span><span>{won(calc.payout)}</span></div>
      <div className={s.note}>{calc.note}</div>
    </div>
  );
}

function LegalCard({ calc }: { calc: LegalCalc }) {
  const where = [calc.instance, calc.case_kind].filter(Boolean).join(" ");
  return (
    <div className={`raised ${s.card}`} aria-label="법률비용 계산">
      <div className={s.title}>법률비용 한도 · {shortSection(calc.section_name)}</div>
      <div className={s.basis}>{BASIS}</div>
      {calc.claim_value !== null && (
        <>
          <div className={s.row}><span className="dim">소송목적의 값</span><span>{won(calc.claim_value)}</span></div>
          {calc.bracket && <div className={s.sub}>적용 구간 {calc.bracket}</div>}
        </>
      )}
      {calc.lawyer_limit !== null && (
        <>
          <div className={s.row}><span className="dim">변호사비 한도 【별표3】</span><span>{won(calc.lawyer_limit)}</span></div>
          <div className={s.row}><span className="dim">자기부담금(실제 보수에서)</span><span>− {won(calc.lawyer_copay)}</span></div>
        </>
      )}
      {calc.stamp !== null && (
        <div className={s.row}><span className="dim">인지액 【별표4】</span><span>{won(calc.stamp)}</span></div>
      )}
      <div className={s.row}>
        <span className="dim">송달료 【별표5】{where && ` ${where}`}</span>
        <span>{calc.service !== null ? won(calc.service) : <span className="dim">심급을 말하면 표시</span>}</span>
      </div>
      <div className={s.sub}>1소송당 상한 — 변호사비 {won(calc.lawyer_cap)} · 인지액+송달료 {won(calc.stamp_service_cap)}</div>
      {calc.lawyer_max !== null && (
        <div className={`${s.row} ${s.total}`}><span>변호사 보수 최대</span><span>{won(calc.lawyer_max)}</span></div>
      )}
      <div className={s.note}>{calc.note}</div>
    </div>
  );
}

import { useState } from "react";
import type { CalcResult, DaysAskCalc, DayRow, LegalCalc, LimitsCalc, MedicalCalc } from "../api/types";
import { shortSection, won } from "../format";
import s from "./CalcCard.module.css";

/** 금액이 모델 답변이 아니라 약관 표에서 나왔다는 표시 — 답변이 거절하거나 다른 금액을 말해도 카드가 무엇인지 알 수 있게 */
const BASIS = "금액은 약관 표로 계산한 값";

/** 계산 카드(09 2-3) — 서버 계산 결과를 그대로 보여준다. 모델은 계산에 손대지 않는다. kind로 의료비·법률비용·한도·날짜별 입력을 가른다.
 *  onAnswer: 날짜별 입력 카드가 마지막 턴일 때만 — 채운 값을 다음 질문으로 보낸다. 없으면 입력칸은 읽기 전용 */
export function CalcCard({ calc, onAnswer }: { calc: CalcResult; onAnswer?: (text: string) => void }) {
  if (calc.kind === "legal") return <LegalCard calc={calc} />;
  if (calc.kind === "limits") return <LimitsCard calc={calc} />;
  if (calc.kind === "days_ask") return <DaysAskCard calc={calc} onAnswer={onAnswer} />;
  return <MedicalCard calc={calc} />;
}

const dayName = (setting: string | null | undefined, i: number) => (setting === "통원" ? `${i}번째` : `${i}일째`);
const tag = (r: { surgery: boolean; mri: boolean }) => (r.surgery ? " 수술" : r.mri ? " MRI 등" : "");

function MedicalCard({ calc }: { calc: MedicalCalc }) {
  const days = calc.days ?? 1;
  const exact = calc.exact ?? true;
  const unit = calc.setting === "통원" ? "번" : "일";
  const status = !exact ? "범위 — 날짜별 금액 모름" : calc.days_known === false ? "하루로 계산 — 일수 모름" : "정확한 값";
  const rows: DayRow[] = calc.day_rows ?? [];
  return (
    <div className={`raised ${s.card}`} aria-label="예상 보험금 계산">
      <div className={s.title}>예상 보험금 · {shortSection(calc.section_name)} {calc.coverage_type}</div>
      <div className={s.badges}>
        <span className={s.basis}>{BASIS}</span>
        <span className={`${s.chip} ${exact && calc.days_known !== false ? s.chipOk : s.chipWarn}`}>{status}</span>
      </div>
      <div className={s.row}>
        <span className="dim">청구 치료비{days > 1 && ` · ${calc.setting ?? ""} ${days}${unit}`}</span><span>{won(calc.claimed)}</span>
      </div>
      <div className={s.row}>
        <span className="dim">자기부담금{days > 1 && " (날마다)"}</span>
        <span>− {won(calc.copay)}{days > 1 && ` × ${days}${unit === "번" ? "회" : "일"}`}</span>
      </div>
      {calc.rate_pct != null && <div className={s.row}><span className="dim">보상비율</span><span>{calc.rate_pct}%</span></div>}
      <div className={s.row}>
        <span className="dim">{days > 1 ? "1일 지급 한도(수술 안 한 날)" : "지급 한도(1일)"}</span><span>{won(calc.limit)}</span>
      </div>
      {rows.length > 0 && (
        <div className={s.days} aria-label="날짜별 계산">
          {!exact && <div className={s.sub}>금액을 아는 날</div>}
          {rows.map((r, i) => (
            <div key={i} className={s.row}>
              <span className="dim">{exact ? dayName(calc.setting, i + 1) : ""}{tag(r)} {won(r.cost)}</span>
              <span>{won(r.payout)}{r.payout === r.limit && r.payout > 0 && <span className="dim"> 한도</span>}</span>
            </div>
          ))}
        </div>
      )}
      {calc.annual_total != null && (
        <div className={`${s.row}${calc.capped ? ` ${s.hl}` : ""}`}>
          <span className="dim">올해 사용 {won(calc.annual_used ?? 0)} / 남은 한도</span>
          <span>{won(calc.annual_remaining ?? calc.annual_total)}</span>
        </div>
      )}
      {calc.mri_before != null && calc.mri_before > 0 && (
        <div className={s.sub}>올해 MRI·CT·내시경 {calc.mri_before}번 받음(청구 이력)</div>
      )}
      {exact ? (
        <div className={`${s.row} ${s.total}`}><span>예상 지급액</span><span>{won(calc.payout)}</span></div>
      ) : (
        <>
          <div className={`${s.row} ${s.total}`}>
            <span>예상 지급액 범위</span>
            <span>{won(calc.range_min ?? 0)} ~ {won(calc.range_max ?? 0)}</span>
          </div>
          <div className={s.row}><span className="dim">고르게 나뉘었다면</span><span>{won(calc.even ?? calc.payout)}</span></div>
        </>
      )}
      {calc.capped && <div className={s.sub}>남은 연간 한도까지로 줄인 금액입니다</div>}
      {(calc.assumptions ?? []).map((a) => <div key={a} className={s.assume}>{a}</div>)}
      <div className={s.note}>{calc.note}</div>
    </div>
  );
}

/** "300,000" · "30만" · "12만 5000" → 원. 못 읽으면 null */
export function parseWon(text: string): number | null {
  const t = text.replace(/[,\s원]/g, "");
  if (!t) return null;
  const m = t.match(/^(\d+(?:\.\d+)?)만(\d+)?$/);
  if (m) return Math.round(parseFloat(m[1]) * 10000) + (m[2] ? parseInt(m[2], 10) : 0);
  return /^\d+$/.test(t) ? parseInt(t, 10) : null;
}

/** 날짜별 금액 입력 — 일수만큼 칸(수술한 날·MRI 표시), 합계와 앞서 말한 총액 비교. 다 채우면 질문으로 보낸다 */
function DaysAskCard({ calc, onAnswer }: { calc: DaysAskCalc; onAnswer?: (text: string) => void }) {
  const [costs, setCosts] = useState(() => calc.prefill.map((d) => (d.cost != null ? d.cost.toLocaleString("ko-KR") : "")));
  const [surgery, setSurgery] = useState(() => calc.prefill.map((d) => d.surgery));
  const [mri, setMri] = useState(() => calc.prefill.map((d) => d.mri));
  const live = !!onAnswer;
  const values = costs.map(parseWon);
  const sum = values.reduce<number>((a, v) => a + (v ?? 0), 0);
  const complete = values.every((v) => v !== null && v > 0);
  const diff = sum - calc.total;
  const unit = calc.setting === "통원" ? "번" : "일";

  const fillEven = () => {
    // 이미 채운 칸(수술한 날 등)은 두고 빈 칸에 남은 총액을 고르게 — 나머지 원은 첫 빈 칸에
    const empty = values.map((v, i) => (v === null ? i : -1)).filter((i) => i >= 0);
    const targets = empty.length ? empty : values.map((_, i) => i);
    const fixed = empty.length ? sum : 0;
    const rest = Math.max(calc.total - fixed, 0);
    const share = Math.floor(rest / targets.length);
    setCosts(costs.map((c, i) => {
      const k = targets.indexOf(i);
      if (k < 0) return c;
      return (share + (k === 0 ? rest - share * targets.length : 0)).toLocaleString("ko-KR");
    }));
  };
  const submit = () => {
    if (!onAnswer || !complete) return;
    onAnswer(values.map((v, i) => `${v!.toLocaleString("ko-KR")}원${surgery[i] ? "(수술)" : mri[i] ? "(MRI)" : ""}`).join(", "));
  };
  const toggle = (arr: boolean[], set: (v: boolean[]) => void, i: number) => set(arr.map((b, j) => (j === i ? !b : b)));

  return (
    <div className={`raised ${s.card}`} aria-label="날짜별 치료비 입력">
      <div className={s.title}>날짜별 치료비 · {shortSection(calc.section_name)} {calc.coverage_type} · {calc.setting} {calc.days}{unit}</div>
      <div className={s.sub}>{calc.note}{calc.surgery_mentioned && " · 수술한 날을 표시해 주세요"}</div>
      <div className={s.form}>
        {costs.map((c, i) => (
          <div key={i} className={s.field}>
            <label className="dim" htmlFor={`day-${i}`}>{dayName(calc.setting, i + 1)}</label>
            <input id={`day-${i}`} className={s.input} inputMode="numeric" placeholder="예: 300,000 또는 30만" value={c}
                   disabled={!live} aria-invalid={c !== "" && values[i] === null}
                   onChange={(e) => setCosts(costs.map((x, j) => (j === i ? e.target.value : x)))}
                   onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) submit(); }} />
            <label className={s.check}>
              <input type="checkbox" checked={surgery[i]} disabled={!live} onChange={() => toggle(surgery, setSurgery, i)} />수술
            </label>
            {calc.type === "Ⅲ" && (
              <label className={s.check}>
                <input type="checkbox" checked={mri[i]} disabled={!live} onChange={() => toggle(mri, setMri, i)} />MRI
              </label>
            )}
          </div>
        ))}
      </div>
      <div className={`${s.row} ${diff !== 0 && complete ? s.warn : ""}`}>
        <span className="dim">입력 합계 / 앞서 말한 총액</span>
        <span>{won(sum)} / {won(calc.total)}</span>
      </div>
      {complete && diff !== 0 && (
        <div className={s.warn}>총액과 {won(Math.abs(diff))} {diff > 0 ? "많습니다" : "적습니다"} — 보내면 날짜별 금액으로 계산합니다</div>
      )}
      {live && (
        <div className={s.btns}>
          <button className="btn" onClick={fillEven}>고르게 나눠 넣기</button>
          <button className="btn" onClick={() => onAnswer!("잘 모르겠어요")}>잘 모르겠어요</button>
          <button className={`btn ${s.primary}`} onClick={submit} disabled={!complete}>계산하기</button>
        </div>
      )}
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

/** 한도표 — 가입한 의료비 특약마다 한 묶음. 질문이 짚은 줄(수술한 날·MRI 등)은 강조 */
function LimitsCard({ calc }: { calc: LimitsCalc }) {
  const on = (k: LimitsCalc["highlight"]) => (calc.highlight === k ? ` ${s.hl}` : "");
  return (
    <div className={`raised ${s.card}`} aria-label="지급 한도">
      <div className={s.title}>{calc.hypothetical ? "가정한 등급의 한도" : "지급 한도"} · {calc.pet_name}</div>
      <div className={s.basis}>{calc.hypothetical ? `실제 가입: ${calc.enrolled}` : BASIS}</div>
      {calc.rows.map((r) => (
        <div key={r.section_name} className={s.group}>
          <div className={s.groupHead}>{shortSection(r.section_name)} {r.coverage_type}</div>
          <div className={s.sub}>{r.copay !== null && `자기부담 ${won(r.copay)} · `}보상비율 {r.rate_pct}%</div>
          <div className={`${s.row}${on("non_surgery")}`}>
            <span className="dim">{r.mri_1st !== null ? "수술·MRI 없는 날" : "수술 안 한 날"} 1일</span><span>{won(r.non_surgery)}</span>
          </div>
          {r.mri_1st !== null && (
            <div className={`${s.row}${on("mri")}`}><span className="dim">MRI 등 연간 첫 번째</span><span>{won(r.mri_1st)}</span></div>
          )}
          {r.mri_2nd_plus !== null && (
            <div className={`${s.row}${on("mri")}`}><span className="dim">MRI 등 두 번째부터</span><span>{won(r.mri_2nd_plus)}</span></div>
          )}
          <div className={`${s.row}${on("surgery")}`}><span className="dim">수술한 날 1일</span><span>{won(r.surgery)}</span></div>
          <div className={s.row}><span className="dim">연간 총 한도</span><span>{won(r.annual_total)}</span></div>
          {r.annual_remaining != null && (
            <div className={s.row}><span className="dim">올해 남은 한도</span><span>{won(r.annual_remaining)}</span></div>
          )}
        </div>
      ))}
      <div className={s.note}>{calc.note}</div>
    </div>
  );
}

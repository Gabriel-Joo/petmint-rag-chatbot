import type { EmployeeProfile } from "../api/types";
import s from "./CustomerCard.module.css";

// 사내규정 본인 정보 블록(2026-10-28) — 업무특화 고객 블록(CustomerCard)과 같은 자리·CSS·층(큰 줄 / 칩 줄 / 작은 줄).
// 급여·평균임금·수당 금액·인사평가는 띄우지 않는다 — 옆에서 볼 수 있다. 물을 때만 답에 나온다(hr_personal).
// 숫자는 서버가 답과 같은 계산(hr_personal.profile)으로 낸 값이다 — 화면에서 다시 계산하지 않는다

const days = (x: number) => `${Number.isInteger(x) ? x : x.toFixed(1)}일`;

export function EmployeeCard({ p }: { p: EmployeeProfile }) {
  const tenure = `${p.tenure_years}년${p.tenure_months ? ` ${p.tenure_months}개월` : ""}`;
  return (
    <section className={`raised ${s.card}`} aria-label="내 정보">
      <div className={s.top}>
        <div className={s.big}>
          <span className={s.customer}>{p.name}</span>
          <span className={s.pet}>{p.grade}</span>{/* 팀은 하나(고객상담팀)라 띄우지 않는다 — 직급은 승진·수습·정년 계산에 걸린다 */}
          <span className={s.petMeta}>
            {p.employment_type !== "정규직" && `${p.employment_type} · `}입사 {p.hire_date} · 근속 {tenure}
            {p.tenure_excluded_days > 0 && ` (휴직 ${p.tenure_excluded_days}일 제외)`}
          </span>
        </div>
      </div>

      <div className={s.mid}>
        {p.leave_left !== null && p.leave_total !== null && p.leave_used !== null && (
          <span className={s.chip}>연차 잔여 <b>{days(p.leave_left)}</b> · 총 {days(p.leave_total)} · 사용 {days(p.leave_used)}</span>
        )}
        {p.certificates.map((c) => (
          <span key={c.name} className={c.submitted ? s.chip : s.excl} title={c.submitted ? `취득 ${c.acquired_on}` : "자격증 사본을 내면 다음 달부터 수당이 나옵니다"}>
            {c.submitted ? c.name : <><b>사본 미제출</b> {c.name}</>}
          </span>
        ))}
        {p.employment_type !== "정규직" && <span className={s.chip}>급여·퇴직·휴가는 개별근로계약</span>}
      </div>

      <div className={s.small}>
        {p.leave_start && p.leave_end && <span>연차 기간 {p.leave_start} ~ {p.leave_end}</span>}
        {p.probation_end && <span>수습 ~ {p.probation_end}</span>}
        {p.next_grade && p.promotion_eligible_on && <span>{p.next_grade} 승진 체류연수 {p.promotion_eligible_on}</span>}
        {p.retirement_on && <span>정년퇴직일 {p.retirement_on}</span>}
      </div>
    </section>
  );
}

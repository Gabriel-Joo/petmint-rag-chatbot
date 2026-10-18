import { RING_SECONDS, type Ringing } from "../hooks/useCallSimulator";
import { SPECIES_ICON } from "../format";
import s from "./CallAlert.module.css";

interface Props {
  ringing: Ringing | null;
  notice: string | null;
  onAccept: () => void;
  onReject: () => void;
}

/** 전역 전화 알림(10번 1절). 어느 화면에서든 같은 자리에 뜬다 */
export function CallAlert({ ringing, notice, onAccept, onReject }: Props) {
  if (!ringing) {
    return notice ? <div className={`raised ${s.notice}`} role="status">{notice}</div> : null;
  }
  const { customer, secondsLeft } = ringing;
  return (
    <div className={`raised ${s.wrap}`} role="alertdialog" aria-label="전화 수신">
      <div className={s.phone} aria-hidden>
        <span className={s.ring} /><span className={s.ring} /><span className={s.ring} />
        📞
      </div>
      <div className={s.body}>
        <div className={s.head}>
          <span className={s.label}>전화 수신</span>
          <span className={s.count} aria-label={`${secondsLeft}초 남음`}>
            {secondsLeft}<span className={s.unit}>초</span>
          </span>
        </div>
        <div className={s.timer} aria-hidden>
          <div className={s.timerFill} style={{ width: `${(secondsLeft / RING_SECONDS) * 100}%` }} />
        </div>
        <div className={s.name}>{customer.name}</div>
        <div className={s.pets}>
          {customer.pets.map((p) => `${SPECIES_ICON[p.species]} ${p.name}`).join("  ")}
        </div>
        <div className={s.actions}>
          <button className={s.accept} onClick={onAccept}>받기</button>
          <button className="btn" onClick={onReject}>거절</button>
        </div>
      </div>
    </div>
  );
}

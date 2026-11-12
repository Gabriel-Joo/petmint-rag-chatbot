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
    return notice ? <div className={`raised chat-text ${s.notice}`} role="status">{notice}</div> : null;
  }
  const { customer, secondsLeft } = ringing;
  return (
    // 대화 배율(.chat-text) — 고객 조회 카드와 같은 글씨(2026-10-23)
    <div className={`raised chat-text ${s.wrap}`} role="alertdialog" aria-label="전화 수신">
      <div className={s.phone} aria-hidden>
        <span className={s.ring} /><span className={s.ring} /><span className={s.ring} />
        {/* 수화기 — 이모지(📞)는 글꼴 색이라 빨갛게 나와 원 바탕(--call)에 묻혔다. 흰 선 아이콘으로(2026-11-12 사용자) */}
        <svg className={s.icon} viewBox="0 0 24 24" width="1.3em" height="1.3em" fill="currentColor" aria-hidden focusable="false">
          <path d="M6.6 10.8a15.1 15.1 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.57a1 1 0 0 1-.25 1L6.6 10.8z" />
        </svg>
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
        <div className={s.who}>
          <span className={s.name}>{customer.name}</span>
          <span className={s.tel}>{customer.phone}</span>
        </div>
        {/* 반려동물 — 고객 조회 카드처럼 이름 옆에 "품종 · 나이", 넘치면 말줄임 */}
        <div className={s.pets}>
          {customer.pets.map((p) => (
            <div key={p.pet_id} className={s.pet}>
              <span className={s.petName}>{SPECIES_ICON[p.species]} {p.name}</span>
              <span className={s.petMeta}>{p.breed} · {p.age}세</span>
            </div>
          ))}
        </div>
        <div className={s.actions}>
          <button className={s.accept} onClick={onAccept}>받기</button>
          <button className={`btn ${s.reject}`} onClick={onReject}>거절</button>
        </div>
      </div>
    </div>
  );
}

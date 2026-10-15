import type { Mode } from "../api/types";
import domainIcon from "../assets/characters/domain-icon.png";
import generalIcon from "../assets/characters/general-icon.png";
import hrIcon from "../assets/characters/hr-icon.png";
import s from "./ModeIcon.module.css";

// 모드 아이콘 — 각 캐릭터 정지 이미지에서 머리만 동그랗게 잘라낸 것(128px). 헤더 모드 탭, 대화·상담 화면 제목이 같이 쓴다(모드 카드에는 같은 캐릭터가 크게 있어 쓰지 않는다)
const ICON: Record<Mode, string> = { 일반: generalIcon, 사내규정: hrIcon, 업무특화: domainIcon };

/** 옆에 모드 이름이 같이 붙으므로 장식으로 둔다(alt 없음) */
export function ModeIcon({ mode }: { mode: Mode }) {
  return <img className={s.icon} src={ICON[mode]} alt="" aria-hidden draggable={false} />;
}

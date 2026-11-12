import type { Mode } from "../api/types";
import { ModeIcon } from "./ModeIcon";
import s from "./Badges.module.css";

// 작은 배지(2026-11-12, 13번 2-5절) — 거절 표시와 같은 크기 · 모양(테두리 칩, 모서리 6px, --font-2xs 굵게).
// 권한(관리자 · 상담원)은 직급과 따로다 — 이름 뒤 직급, 그 옆 권한 배지. 헤더 상담원 표시와 관리자 화면이 같이 쓴다.

/** 권한 배지 — 관리자는 보라, 상담원은 회색. 앱 계정이 없으면(role null) 상담원으로 본다(고객상담팀 상담원) */
export function RoleBadge({ role }: { role: string | null | undefined }) {
  const admin = role === "관리자";
  return <span className={`${s.badge} ${admin ? s.admin : s.agent}`}>{admin ? "관리자" : "상담원"}</span>;
}

/** 모드 배지 — 모드 탭과 같은 캐릭터 아이콘 + 모드 이름(탭에는 모드별 색이 따로 없고 캐릭터가 모드를 가른다) */
export function ModeBadge({ mode }: { mode: Mode }) {
  return <span className={`${s.badge} ${s.mode}`}><ModeIcon mode={mode} />{mode}</span>;
}

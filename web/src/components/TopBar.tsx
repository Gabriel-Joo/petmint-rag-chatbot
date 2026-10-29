import { useEffect, useRef, useState } from "react";
import { IS_FAKE_API } from "../api/client";
import type { MeOut, Mode } from "../api/types";
import { ModeIcon } from "./ModeIcon";
import s from "./TopBar.module.css";

// 모드 선택 카드와 같은 순서 — 업무특화가 메인이라 가운데
const MODES: Mode[] = ["일반", "업무특화", "사내규정"];

interface Props {
  current: Mode | null;
  /** 상담 진행 중 — 모드 전환 잠김(10번 5절) */
  locked: boolean;
  onHome: () => void;
  onMode: (m: Mode) => void;
  autoRing: boolean;
  onAutoRing: (v: boolean) => void;
  onRing: () => void;
  me: MeOut;
  /** 앱 로그인일 때만 — 있으면 오른쪽 끝에 직원 이름·팀과 로그아웃 */
  onLogout: (() => void) | null;
}

export function TopBar({ current, locked, onHome, onMode, autoRing, onAutoRing, onRing, me, onLogout }: Props) {
  // 1023px 이하에서만 전화 묶음을 햄버거 메뉴로 접는다. 넓은 화면에서는 버튼이 숨고 묶음이 늘 보인다
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: PointerEvent) => { if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMenuOpen(false); };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("pointerdown", onDown); document.removeEventListener("keydown", onKey); };
  }, [menuOpen]);

  // 상담원 표기 — 모두 상담원이라 팀은 쓰지 않는다. 관리자 계정은 역할을 그대로 붙인다("○○○ 관리자")
  const who = me.name ? `${me.name} ${me.role === "관리자" ? "관리자" : "상담원"}` : me.email;

  return (
    <header className={s.bar}>
      {/* 왼쪽: 제목·부제 → 모드 탭(+잠금 표시). 좁으면 이 칸 안에서만 줄을 바꾼다 */}
      <div className={s.leftCol}>
        <div className={s.brandRow}>
          <button className={s.brand} onClick={onHome} disabled={locked}>
            <span className={s.brandTitle}>펫퍼민트 상담</span>
            <span className={s.brandSub}>약관 안내 챗봇</span>
          </button>
          {IS_FAKE_API && <span className={s.fake} title="백엔드 대신 고정 응답을 돌려주는 가짜 API 층">가짜 API</span>}
        </div>
        <div className={s.left}>
          <nav className={s.tabs} aria-label="모드">
            {MODES.map((m) => (
              <button key={m} className={`${s.tab} ${current === m ? s.tabOn : ""}`} disabled={locked && current !== m}
                      aria-current={current === m || undefined} onClick={() => onMode(m)}
                      title={locked ? "상담 중에는 모드를 바꿀 수 없습니다" : undefined}>
                <ModeIcon mode={m} />{m}
              </button>
            ))}
          </nav>
          {locked && <span className={s.lock}>🔒 상담 중</span>}
        </div>
      </div>

      {/* 오른쪽: 전화 묶음 → 상담원. 늘 첫 줄 오른쪽 끝 — 모드·상담 중 표시로 자리가 바뀌지 않는다(2026-10-28) */}
      <div className={s.rightCol}>
        {/* 개발·시연용 가상 전화(10번 1절) */}
        <div className={s.callWrap} ref={menuRef}>
          <button className={s.menuBtn} aria-label="전화 메뉴" aria-expanded={menuOpen} aria-controls="call-menu"
                  onClick={() => setMenuOpen((v) => !v)}>
            <span aria-hidden>☰</span>
          </button>
          <div id="call-menu" className={`${s.call} ${menuOpen ? s.callOpen : ""}`}>
            <label className={s.switch}>
              <input type="checkbox" checked={autoRing} onChange={(e) => onAutoRing(e.target.checked)} />
              자동 전화
            </label>
            <button className={`btn ${s.ringBtn}`} onClick={() => { setMenuOpen(false); onRing(); }} disabled={locked}
                    title={locked ? "상담 중에는 전화가 울리지 않습니다" : undefined}>
              전화 울리기
            </button>
            {/* 휴대폰 폭에서는 로그아웃이 이 메뉴 안으로 들어온다(상단 첫 줄 폭) — 넓은 화면에서는 숨는다 */}
            {onLogout && (
              <button className={`btn ${s.ringBtn} ${s.menuLogout}`} onClick={() => { setMenuOpen(false); onLogout(); }} disabled={locked}
                      title={locked ? "상담을 종료한 뒤 로그아웃할 수 있습니다" : undefined}>
                로그아웃
              </button>
            )}
          </div>
        </div>

        {/* 앱 로그인(13번 2-1절) — 누가 상담하는지. 상담 중에는 로그아웃을 막는다(종료 후에) */}
        {onLogout && (
          <div className={s.user}>
            <span className={s.userName} title={me.email}>{who}</span>
            <button className={`btn ${s.logout}`} onClick={onLogout} disabled={locked}
                    title={locked ? "상담을 종료한 뒤 로그아웃할 수 있습니다" : undefined}>
              로그아웃
            </button>
          </div>
        )}
      </div>
    </header>
  );
}

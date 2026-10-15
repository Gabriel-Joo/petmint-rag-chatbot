import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import type { SessionOut, SessionSummary } from "../api/types";
import { ChatHistory } from "../components/ChatHistory";
import { TurnView } from "../components/TurnView";
import { Composer } from "../components/Composer";
import { ModeIcon } from "../components/ModeIcon";
import { dropChat, loadHistory, useChatSocket } from "../hooks/useChatSocket";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { WS_CLOSE_SESSION_NOT_FOUND } from "../api/types";
import s from "./Chat.module.css";

interface Props {
  mode: "일반" | "사내규정";
  session: SessionOut | null;
  onNewChat: () => void;
  /** "지난 채팅"에서 고른 세션을 이 모드의 현재 대화로 연다 */
  onOpenSession: (s: SessionSummary) => void;
  /** 지난 채팅을 목록에서 제거했다 — 지금 보던 대화였으면 새 대화로 바꾼다 */
  onSessionDeleted: (sessionId: string) => void;
  /** 4404 — 이 모드는 고객 조회가 없으므로 빈 대화창에서 새 세션을 연다(09 6-2) */
  onSessionLost: () => void;
}

/** 대화창 위 캐릭터 인사. 모드 선택 화면의 대사가 소개라면 여기는 인사다 */
const GREETING = {
  일반: "무엇이든 편하게 물어보세요. 사내 서버에서만 처리돼요.",
  사내규정: "인사, 복무 규정은 제가 알아요. 편하게 물어보세요.",
};

// 사이드바 접힘 — 넓은 화면에서 접어 둔 것만 기억한다(좁은 화면은 늘 접힌 채로 시작해 대화창을 가리지 않는다)
const COLLAPSED_KEY = "petmint.chatHistory.collapsed";
function readCollapsed(): boolean {
  try { return localStorage.getItem(COLLAPSED_KEY) === "1"; } catch { return false; }
}

// 사이드바 폭 — 경계를 끌어 정한 값을 접힘 상태처럼 브라우저가 기억한다. 넓은 화면에서만 쓴다
const WIDTH_KEY = "petmint.chatHistory.width";
const MIN_WIDTH = 200;
const MAX_WIDTH = 640;
const maxWidth = () => Math.min(MAX_WIDTH, Math.round(window.innerWidth * 0.5)); // 대화창이 사이드바보다 좁아지지 않게
const clampWidth = (w: number) => Math.round(Math.max(MIN_WIDTH, Math.min(maxWidth(), w)));
function readWidth(): number | null {
  try {
    const v = Number(localStorage.getItem(WIDTH_KEY));
    return v > 0 ? clampWidth(v) : null;
  } catch { return null; }
}
function saveWidth(w: number) {
  try { localStorage.setItem(WIDTH_KEY, String(w)); } catch { /* 이번 화면에서만 */ }
}

/** 일반·사내규정 대화창 — 같은 컴포넌트, 모드만 다르다. 상담원 개인의 작업 공간(10번 2절) */
export function Chat({ mode, session, onNewChat, onOpenSession, onSessionDeleted, onSessionLost }: Props) {
  const sessionId = session?.session_id ?? null;
  const chat = useChatSocket(sessionId);
  const logRef = useRef<HTMLDivElement>(null);
  const narrow = useMediaQuery("(max-width: 899px)");
  const [collapsed, setCollapsed] = useState(() => narrow || readCollapsed());
  const [sideWidth, setSideWidth] = useState<number | null>(readWidth);
  const layoutRef = useRef<HTMLDivElement>(null);

  /** 경계 끌기 — 가로만. 포인터를 잡아 두고 사이드바 왼쪽 끝부터 포인터까지를 폭으로 쓴다 */
  const startResize = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const handle = e.currentTarget;
    handle.setPointerCapture(e.pointerId);
    const left = layoutRef.current?.getBoundingClientRect().left ?? 0;
    let last = sideWidth;
    const move = (ev: PointerEvent) => { last = clampWidth(ev.clientX - left); setSideWidth(last); };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      if (last !== null) saveWidth(last);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
  };

  /** 키보드로도 — 좌우 화살표 16px씩 */
  const keyResize = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const base = sideWidth ?? (layoutRef.current?.querySelector("aside")?.getBoundingClientRect().width ?? MIN_WIDTH);
    const w = clampWidth(base + (e.key === "ArrowRight" ? 16 : -16));
    setSideWidth(w);
    saveWidth(w);
  };

  // 지금 보던 대화면 App이 새 대화로 바꾼다. 아니면 이 탭에 남은 대화 상태만 버린다
  const deleted = (id: string) => { if (id === sessionId) onSessionDeleted(id); else dropChat(id); };

  const toggleHistory = () => {
    setCollapsed((v) => {
      if (!narrow) { try { localStorage.setItem(COLLAPSED_KEY, v ? "0" : "1"); } catch { /* 이번 화면에서만 */ } }
      return !v;
    });
  };

  const openPast = (it: SessionSummary) => {
    if (narrow) setCollapsed(true); // 좁은 화면에서는 덮고 있던 목록을 걷는다
    if (it.session_id !== sessionId) onOpenSession(it);
  };

  useEffect(() => {
    if (chat.closedCode === WS_CLOSE_SESSION_NOT_FOUND) onSessionLost();
  }, [chat.closedCode, onSessionLost]);

  // 지난 대화를 열면 남은 턴을 불러온다. 이 탭에서 이미 보던 대화면 그대로 쓴다
  useEffect(() => {
    if (!sessionId) return;
    loadHistory(sessionId).catch((e) => { if (e instanceof ApiError && e.status === 404) onSessionLost(); });
  }, [sessionId, onSessionLost]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [chat.turns]);

  return (
    <div className={s.layout} ref={layoutRef}>
      {/* 아직 질문이 없으면 이미 새 대화다 — 빈 세션을 늘리지 않는다 */}
      <ChatHistory mode={mode} currentId={sessionId} refreshKey={`${sessionId}:${chat.turns.length}:${chat.busy}`}
                   collapsed={collapsed} onToggle={toggleHistory} onOpen={openPast}
                   onNewChat={onNewChat} newChatDisabled={!session || chat.turns.length === 0}
                   onDeleted={deleted} width={narrow ? null : sideWidth} />
      {!collapsed && !narrow && (
        <div className={s.resizer} role="separator" aria-orientation="vertical" aria-label="지난 채팅 폭 조절"
             aria-valuemin={MIN_WIDTH} aria-valuemax={MAX_WIDTH} aria-valuenow={sideWidth ?? undefined} tabIndex={0}
             onPointerDown={startResize} onKeyDown={keyResize} onDoubleClick={() => { setSideWidth(null); saveWidth(0); }}
             title="끌어서 폭 조절 · 두 번 누르면 기본 폭" />
      )}
      <main className={s.page}>
        {/* 모드 이름은 헤더 탭에 있으므로 여기서는 캐릭터 인사만 */}
        <div className={s.head}>
          <span className={s.avatar}><ModeIcon mode={mode} /></span>
          <p className={s.greeting}>{GREETING[mode]}</p>
        </div>
        <div ref={logRef} className={`raised ${s.log}`}>
          {!session && <div className={s.empty}>세션을 여는 중…</div>}
          {chat.turns.map((t) => (
            <TurnView key={t.key} turn={t} inlineSources={mode === "사내규정" ? "always" : "never"} />
          ))}
        </div>
        <div className={`raised ${s.composer}`}>
          <Composer busy={chat.busy} disabled={!session} onCancel={chat.cancel}
                    onSend={(text) => chat.ask(text, null)} placeholder="질문을 입력하세요 (Enter 전송, Shift+Enter 줄바꿈)" />
        </div>
      </main>
    </div>
  );
}

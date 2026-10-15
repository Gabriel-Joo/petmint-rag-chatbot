// 화면 전환과 세션 수명(10번 2·3·5절)을 여기서 쥔다.
// - 일반·사내규정: 모드별로 지금 보는 세션 하나. 모드를 오가도 유지된다. 세션은 닫지 않는다 —
//   "새 대화"는 새 세션을 여는 것뿐이고, 앞 대화는 "지난 채팅"에서 다시 열어 이어 쓸 수 있다
// - 업무특화: 상담 시작 시 생성, 종료로 닫는다. 진입은 전화 받기 / 고객 조회 둘 — 같은 startConsultation으로 수렴
// - 상담 진행 중에는 모드 전환이 잠기고 전화가 울리지 않는다. 종료 후에는 화면에 머문다(읽기 전용)

import { useCallback, useState } from "react";
import { ApiError, createSession, deleteSession } from "./api/client";
import type { Customer, Mode, SessionOut, SessionSummary } from "./api/types";
import { CallAlert } from "./components/CallAlert";
import { TopBar } from "./components/TopBar";
import { useCallSimulator } from "./hooks/useCallSimulator";
import { closeChatSocket, dropChat } from "./hooks/useChatSocket";
import { Chat } from "./pages/Chat";
import { Consultation, type ConsultState } from "./pages/Consultation";
import { CustomerSelect } from "./pages/CustomerSelect";
import { ModeSelect } from "./pages/ModeSelect";
import s from "./App.module.css";

type ChatMode = "일반" | "사내규정";
type Screen = "mode" | ChatMode | "customers" | "consult";

export default function App() {
  const [screen, setScreen] = useState<Screen>("mode");
  const [chatSessions, setChatSessions] = useState<Record<ChatMode, SessionOut | null>>({ 일반: null, 사내규정: null });
  const [consult, setConsult] = useState<ConsultState | null>(null);
  const [starting, setStarting] = useState(false);
  const [ending, setEnding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const locked = consult !== null && !consult.ended;

  const fail = (e: unknown) => setError(e instanceof ApiError ? e.detail : String(e));

  const openChatSession = useCallback(async (mode: ChatMode) => {
    try {
      const sess = await createSession({ mode });
      setChatSessions((prev) => ({ ...prev, [mode]: sess }));
    } catch (e) { fail(e); }
  }, []);

  /** 종료된 상담 화면을 떠나면 그 대화는 버린다 — 업무특화를 다시 누르면 고객 조회가 뜬다(10번 5절) */
  const leaveEndedConsult = () => {
    if (consult?.ended) {
      dropChat(consult.session.session_id);
      setConsult(null);
    }
  };

  const goMode = (mode: Mode) => {
    if (locked) return;
    leaveEndedConsult();
    if (mode === "업무특화") {
      setScreen("customers");
      return;
    }
    setScreen(mode);
    if (!chatSessions[mode]) void openChatSession(mode);
  };

  const goHome = () => {
    if (locked) return;
    leaveEndedConsult();
    setScreen("mode");
  };

  /** "새 대화" — 새 세션을 열 뿐 앞 세션은 닫지 않는다. 대화 상태도 버리지 않아 "지난 채팅"에서 바로 다시 열린다 */
  const newChat = (mode: ChatMode) => openChatSession(mode);

  /** "지난 채팅"에서 고른 세션을 이 모드의 현재 대화로 — 턴은 Chat이 불러온다 */
  const openPastChat = (mode: ChatMode, it: SessionSummary) => {
    setChatSessions((prev) => ({ ...prev, [mode]: { session_id: it.session_id, mode, customer_id: null, started_at: it.started_at } }));
  };

  /** 4404를 받은 일반·사내규정 — 그 모드의 빈 대화창에서 새 세션(09 6-2) */
  const chatSessionLost = useCallback((mode: ChatMode) => {
    setChatSessions((prev) => {
      if (prev[mode]) dropChat(prev[mode]!.session_id);
      return { ...prev, [mode]: null };
    });
    void openChatSession(mode);
  }, [openChatSession]);

  /** 업무특화 진입점 하나 — 전화 받기와 고객 조회가 여기로 모인다(10번 3절) */
  const startConsultation = useCallback(async (customer: Customer) => {
    setStarting(true);
    try {
      const session = await createSession({ mode: "업무특화", customer_id: customer.customer_id });
      setConsult((prev) => {
        if (prev) dropChat(prev.session.session_id); // 종료된 화면에서 전화를 받으면 새 고객으로 갈린다
        return { session, customer, ended: false };
      });
      setScreen("consult");
    } catch (e) { fail(e); } finally { setStarting(false); }
  }, []);

  const endConsultation = async () => {
    if (!consult) return;
    setEnding(true);
    try {
      await deleteSession(consult.session.session_id);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) { fail(e); setEnding(false); return; }
    }
    closeChatSocket(consult.session.session_id);
    setConsult({ ...consult, ended: true });
    setEnding(false);
  };

  /** 4404를 받은 업무특화 — 고객 조회로 돌아간다(09 6-2) */
  const consultLost = useCallback(() => {
    setConsult((prev) => {
      if (prev) dropChat(prev.session.session_id);
      return null;
    });
    setScreen("customers");
    setError("세션이 만료되어 고객 조회로 돌아왔습니다.");
  }, []);

  const call = useCallSimulator({ blocked: locked || starting, onAccept: startConsultation });

  const currentMode: Mode | null =
    screen === "mode" ? null : screen === "customers" || screen === "consult" ? "업무특화" : screen;

  return (
    <div className={s.app}>
      <TopBar current={currentMode} locked={locked} onHome={goHome} onMode={goMode}
              autoRing={call.autoRing} onAutoRing={call.setAutoRing} onRing={() => void call.ring()} />
      {error && (
        <div className={s.error} role="alert">
          <span>{error}</span>
          <button onClick={() => setError(null)} aria-label="닫기">✕</button>
        </div>
      )}
      <div className={s.main}>
        {screen === "mode" && <ModeSelect onSelect={goMode} />}
        {(screen === "일반" || screen === "사내규정") && (
          <Chat key={screen} mode={screen} session={chatSessions[screen]}
                onNewChat={() => void newChat(screen)} onOpenSession={(it) => openPastChat(screen, it)}
                onSessionDeleted={(id) => { dropChat(id); void openChatSession(screen); }} onSessionLost={() => chatSessionLost(screen)} />
        )}
        {screen === "customers" && <CustomerSelect onStart={(c) => void startConsultation(c)} starting={starting} />}
        {screen === "consult" && consult && (
          <Consultation key={consult.session.session_id} consult={consult} onEnd={() => void endConsultation()}
                        ending={ending} onSessionLost={consultLost} />
        )}
      </div>
      <CallAlert ringing={call.ringing} notice={call.notice} onAccept={call.accept} onReject={call.reject} />
    </div>
  );
}

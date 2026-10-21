// WS 수신 + turn_id별 상태(09 8절). 대화 상태와 소켓은 컴포넌트가 아니라 이 모듈의 저장소(session_id별)에 둔다 —
// 일반·사내규정은 모드를 오가며 화면이 내려가도 대화가 남아야 하기 때문이다(10번 2절).

import { useCallback, useEffect, useSyncExternalStore } from "react";
import { getSessionTurns, openChatSocket, type ChatSocket } from "../api/client";
import type { CalcResult, ReferenceItem, ServerMessage, SourceItem, TurnContextInfo, TurnOut } from "../api/types";

export type TurnStatus = "searching" | "clarify" | "streaming" | "done" | "error";

export interface Turn {
  key: string;                 // 화면 키. turn_id는 서버 첫 메시지가 와야 정해진다
  turn_id: string | null;
  question: string;
  pet_id: string | null;
  context: TurnContextInfo | null; // 후속 질문을 앞 대화로 푼 방법(↳ 줄). 단독 질문이면 null
  sources: SourceItem[];
  answer: string;
  clarify: string[] | null;    // 되묻기 선택지(대기 중)
  clarifyChoice: string | null;
  references: ReferenceItem[];
  calc: CalcResult | null;
  exclusions: string[] | null; // 서버가 대조한 부담보(없으면 화면이 직접 대조 — 지난 턴)
  error: string | null;
  status: TurnStatus;
  latency_ms: number | null;
  first_token_ms: number | null;
}

export interface ChatState {
  turns: Turn[];
  /** 소켓이 서버 쪽에서 닫힌 코드(4404 등). null이면 열려 있거나 아직 안 열림 */
  closedCode: number | null;
  /** 상담 종료 등으로 클라이언트가 닫았다 — 대화는 읽기 전용으로 남는다 */
  readOnly: boolean;
}

interface Entry {
  state: ChatState;
  socket: ChatSocket | null;
  listeners: Set<() => void>;
}

const EMPTY: ChatState = { turns: [], closedCode: null, readOnly: true };
const store = new Map<string, Entry>();

function entry(sessionId: string): Entry {
  let e = store.get(sessionId);
  if (!e) {
    e = { state: { turns: [], closedCode: null, readOnly: false }, socket: null, listeners: new Set() };
    store.set(sessionId, e);
  }
  return e;
}

function update(sessionId: string, fn: (s: ChatState) => ChatState) {
  const e = store.get(sessionId);
  if (!e) return;
  e.state = fn(e.state);
  e.listeners.forEach((l) => l());
}

function patchTurn(turns: Turn[], idx: number, patch: Partial<Turn>): Turn[] {
  return turns.map((t, i) => (i === idx ? { ...t, ...patch } : t));
}

/** 서버 메시지를 턴에 붙인다. 처음 보는 turn_id는 아직 turn_id가 없는 가장 오래된 질문의 것이다 */
function apply(state: ChatState, msg: ServerMessage): ChatState {
  let idx = state.turns.findIndex((t) => t.turn_id === msg.turn_id && msg.turn_id !== "");
  let turns = state.turns;
  if (idx < 0) {
    idx = turns.findIndex((t) => t.turn_id === null);
    if (idx < 0) return state; // 이미 지운 턴의 늦은 메시지
    turns = patchTurn(turns, idx, { turn_id: msg.turn_id || null });
  }
  const t = turns[idx];
  switch (msg.type) {
    case "context":
      return { ...state, turns: patchTurn(turns, idx, { context: { kind: msg.kind, reason: msg.reason, text: msg.text, turns: msg.turns } }) };
    case "sources":
      return { ...state, turns: patchTurn(turns, idx, { sources: msg.items }) };
    case "token":
      return { ...state, turns: patchTurn(turns, idx, { answer: t.answer + msg.text, status: "streaming" }) };
    case "clarify":
      return { ...state, turns: patchTurn(turns, idx, { clarify: msg.options, status: "clarify" }) };
    case "references":
      return { ...state, turns: patchTurn(turns, idx, { references: msg.items }) };
    case "calc":
      return { ...state, turns: patchTurn(turns, idx, { calc: msg.result }) };
    case "exclusions":
      return { ...state, turns: patchTurn(turns, idx, { exclusions: msg.items }) };
    case "done":
      return { ...state, turns: patchTurn(turns, idx, {
        status: t.status === "error" ? "error" : "done", latency_ms: msg.latency_ms, first_token_ms: msg.first_token_ms }) };
    case "error":
      // 원장 오류(customer_data)는 상담원에게 보일 안내 문구 그대로 — 코드는 상담원에게 의미가 없다
      return { ...state, turns: patchTurn(turns, idx, {
        error: msg.code === "customer_data" ? msg.message : `${msg.code}: ${msg.message}`, status: "error" }) };
  }
}

function connect(sessionId: string): ChatSocket {
  const e = entry(sessionId);
  if (!e.socket) {
    e.socket = openChatSocket(sessionId, {
      onMessage: (msg) => update(sessionId, (s) => apply(s, msg)),
      onClose: (code) => {
        e.socket = null;
        update(sessionId, (s) => ({ ...s, closedCode: code }));
      },
    });
  }
  return e.socket;
}

/** 상담 종료 — 소켓만 닫고 대화는 읽기 전용으로 남긴다(10번 5절) */
export function closeChatSocket(sessionId: string) {
  const e = store.get(sessionId);
  if (!e) return;
  e.socket?.close();
  e.socket = null;
  update(sessionId, (s) => ({ ...s, readOnly: true }));
}

/** 대화를 버린다(끝난 상담 화면을 떠날 때, 4404로 세션이 사라졌을 때) */
export function dropChat(sessionId: string) {
  store.get(sessionId)?.socket?.close();
  store.delete(sessionId);
  historyLoaded.delete(sessionId);
}

const historyLoaded = new Set<string>();

/** 서버에 남은 턴 → 화면 턴(끝난 상태). 지난 대화와 과거 상담 모달이 같이 쓴다 */
export function turnFromOut(t: TurnOut): Turn {
  return {
    key: t.turn_id, turn_id: t.turn_id, question: t.question, pet_id: t.pet_id, sources: t.sources, answer: t.answer,
    context: t.context_kind ? { kind: t.context_kind, reason: t.follow_up, text: t.rewritten_question, turns: t.context_turns } : null,
    clarify: null, clarifyChoice: null, references: t.references, calc: t.payout, exclusions: null, error: null, status: "done",
    latency_ms: t.latency_ms, first_token_ms: t.first_token_ms,
  };
}

/** 지난 대화를 열 때 — 서버에 남은 턴으로 화면 상태를 채운다. 이 탭에서 이미 보던 세션(턴이 있음)이면 그대로 둔다.
 *  없는 세션이면 ApiError(404)를 그대로 던진다 */
export async function loadHistory(sessionId: string): Promise<void> {
  if (historyLoaded.has(sessionId)) return;
  historyLoaded.add(sessionId);
  if (entry(sessionId).state.turns.length) return;
  try {
    const past = await getSessionTurns(sessionId);
    update(sessionId, (s) => ({ ...s, turns: [...past.map(turnFromOut), ...s.turns] }));
  } catch (e) {
    historyLoaded.delete(sessionId);
    throw e;
  }
}

export function useChatSocket(sessionId: string | null) {
  const subscribe = useCallback((l: () => void) => {
    if (!sessionId) return () => {};
    const e = entry(sessionId);
    e.listeners.add(l);
    return () => e.listeners.delete(l);
  }, [sessionId]);
  const state = useSyncExternalStore(subscribe, () => (sessionId ? entry(sessionId).state : EMPTY));

  const ask = useCallback((question: string, pet_id: string | null) => {
    if (!sessionId || entry(sessionId).state.readOnly) return;
    const turn: Turn = {
      key: crypto.randomUUID(), turn_id: null, question, pet_id, sources: [], answer: "", clarify: null,
      clarifyChoice: null, references: [], calc: null, exclusions: null, error: null, status: "searching", latency_ms: null,
      first_token_ms: null,
      context: null,
    };
    const socket = connect(sessionId);
    update(sessionId, (s) => ({ ...s, turns: [...s.turns, turn] }));
    socket.send({ type: "question", text: question, pet_id });
  }, [sessionId]);

  const cancel = useCallback(() => {
    if (sessionId) store.get(sessionId)?.socket?.send({ type: "cancel" });
  }, [sessionId]);

  const answerClarify = useCallback((turn_id: string, choice: string) => {
    if (!sessionId) return;
    update(sessionId, (s) => ({ ...s, turns: s.turns.map((t) => (t.turn_id === turn_id
      ? { ...t, clarify: null, clarifyChoice: choice, status: "searching" } : t)) }));
    connect(sessionId).send({ type: "clarify_answer", turn_id, choice });
  }, [sessionId]);

  // 세션 화면이 뜨면 미리 연결해 둔다(없는 세션이면 4404가 바로 온다)
  useEffect(() => {
    if (sessionId && !state.readOnly && state.closedCode === null) connect(sessionId);
  }, [sessionId, state.readOnly, state.closedCode]);

  const busy = state.turns.some((t) => t.status === "searching" || t.status === "streaming" || t.status === "clarify");
  return { ...state, busy, ask, cancel, answerClarify };
}

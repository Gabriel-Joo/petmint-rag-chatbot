// ============================================================================
// API 층 — 백엔드 호출은 이 파일 하나에 모은다. 화면·훅은 이 파일의 export만 쓴다.
//
// 09 7-1(REST)·7-2(WS) 그대로. 경로는 상대 경로(/api, /ws)라 개발 중에는 vite 프록시가,
// 배포에서는 같은 오리진의 FastAPI가 받는다. 상담원 신원(agent_email)은 서버가 정한다 — Cloudflare Access 헤더(PETMINT_AUTH=access)
// 또는 로그인 쿠키(app, HttpOnly라 스크립트가 읽지 못한다). 프론트는 신원을 보내지 않는다.
// ============================================================================

import type {
  ArticleOut, LoginIn, MeOut, PasswordIn, ClientMessage, Corpus, Customer, CustomerSessionSummary, FeedbackIn, FeedbackOut, Grade, RecentConsultation, ServerMessage,
  SessionCreate, SessionDetail, SessionOut, SessionPatch, SessionSummary, TurnOut,
} from "./types";

/** 가짜 API 층을 쓰는지(상단 배지). 실제 백엔드로 바꿨다 — 답변·조항 원문은 백엔드가 아직 더미를 돌려준다 */
export const IS_FAKE_API = false;

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(`${status}: ${detail}`);
  }
}

/** 조항 원문 경로에서 null인 값(보통약관 section_name, 별표 article_num)을 나타내는 조각 — app/routers/articles.py와 같다 */
export const NULL_SEGMENT = "_";

export function articlePath(species: Corpus, section: string, section_name: string | null,
                            article_num: number | null): string {
  const seg = (v: string | number | null) => (v === null ? NULL_SEGMENT : encodeURIComponent(String(v)));
  return `/api/articles/${seg(species)}/${seg(section)}/${seg(section_name)}/${seg(article_num)}`;
}

// ----- fetch 공통 -----

/** FastAPI 오류 본문 → 사람이 읽을 문장. HTTPException은 detail이 문자열, 검증 오류(422)는 배열이다 */
function errorDetail(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (typeof d?.msg === "string" ? d.msg : JSON.stringify(d))).join("; ");
  }
  return fallback;
}

/** 로그인이 풀렸다(401·WS 4401) — AuthGate가 듣고 로그인 화면으로 돌아간다. /api/auth/*의 401은 화면이 직접 처리한다 */
export const UNAUTHORIZED_EVENT = "petmint:unauthorized";
export const WS_CLOSE_UNAUTHORIZED = 4401;

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw new ApiError(0, `서버에 연결할 수 없습니다 (${e instanceof Error ? e.message : String(e)})`);
  }
  if (res.status === 204) return undefined as T;
  const data: unknown = await res.json().catch(() => null);
  if (res.status === 401 && !path.startsWith("/api/auth/")) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  if (!res.ok) throw new ApiError(res.status, errorDetail(data, res.statusText));
  return data as T;
}

// ----- 인증 -----

/** GET /api/auth/me — 로그인 안 됐으면 401(app 모드). access 모드는 늘 답한다 */
export function getMe(): Promise<MeOut> {
  return request("GET", "/api/auth/me");
}

export function login(body: LoginIn): Promise<MeOut> {
  return request("POST", "/api/auth/login", body);
}

export function logout(): Promise<void> {
  return request("POST", "/api/auth/logout");
}

/** 바꾸면 다른 기기의 로그인은 서버가 끊는다 */
export function changePassword(body: PasswordIn): Promise<void> {
  return request("POST", "/api/auth/password", body);
}

const qs = (params: Record<string, string | number | null | undefined>) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined) q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
};

// ----- 7-1 REST -----

/** GET /api/customers */
export function listCustomers(): Promise<Customer[]> {
  return request("GET", "/api/customers");
}

/** GET /api/customers/{id} */
export function getCustomer(customerId: string): Promise<Customer> {
  return request("GET", `/api/customers/${encodeURIComponent(customerId)}`);
}

/** GET /api/customers/{id}/sessions — 그 고객의 과거 상담 목록(09 2-2). 남이 받은 상담도 나온다 */
export function listCustomerSessions(customerId: string, limit = 50): Promise<CustomerSessionSummary[]> {
  return request("GET", `/api/customers/${encodeURIComponent(customerId)}/sessions${qs({ limit })}`);
}

/** POST /api/sessions — 업무특화만 customer_id를 받는다(서버가 검증: 없으면 422, 모르는 고객 404) */
export function createSession(body: SessionCreate): Promise<SessionOut> {
  return request("POST", "/api/sessions", body);
}

/** DELETE /api/sessions/{id} — 업무특화는 상담 종료, 일반·사내규정은 지난 채팅 목록에서 제거(로그는 서버에 남는다) */
export function deleteSession(sessionId: string): Promise<void> {
  return request("DELETE", `/api/sessions/${encodeURIComponent(sessionId)}`);
}

/** PATCH /api/sessions/{id} — 고정·이름 변경(일반·사내규정). 바뀐 목록 한 줄을 돌려준다 */
export function updateSession(sessionId: string, patch: SessionPatch): Promise<SessionSummary> {
  return request("PATCH", `/api/sessions/${encodeURIComponent(sessionId)}`, patch);
}

/** GET /api/consultations/recent — 고객별 마지막 상담 시각(내림차순). 고객 조회 "최근 상담" 탭 */
export function listRecentConsultations(): Promise<RecentConsultation[]> {
  return request("GET", "/api/consultations/recent");
}

/** GET /api/sessions?mode=&limit= — "지난 채팅" 목록(일반·사내규정). 이 상담원의 것만, 질문이 있는 세션만.
 *  고정한 것 먼저, 그 안에서 마지막 활동 시각 내림차순 */
export function listSessions(mode: "일반" | "사내규정", limit = 50): Promise<SessionSummary[]> {
  return request("GET", `/api/sessions${qs({ mode, limit })}`);
}

/** GET /api/sessions/{id} — 세션 상세(담당 상담원·턴). 과거 상담 모달은 이것으로 연다 — 소유자와 무관하게 읽기 전용 */
export function getSession(sessionId: string): Promise<SessionDetail> {
  return request("GET", `/api/sessions/${encodeURIComponent(sessionId)}`);
}

/** 지난 대화를 다시 열 때 화면에 그릴 턴(오래된 순). 서버 turns·retrieved에서 복원한다 */
export async function getSessionTurns(sessionId: string): Promise<TurnOut[]> {
  return (await getSession(sessionId)).turns;
}

/** GET /api/articles/{species}/{section}/{section_name}/{article_num}?coverage_type=&paragraph_num= */
export function getArticle(species: Corpus, section: string, section_name: string | null, article_num: number | null,
                           opts: { coverage_type?: Grade | null; paragraph_num?: number | null } = {}): Promise<ArticleOut> {
  return request("GET", articlePath(species, section, section_name, article_num) +
    qs({ coverage_type: opts.coverage_type, paragraph_num: opts.paragraph_num }));
}

/** POST /api/turns/{turn_id}/feedback — 다시 누르면 서버가 덮어쓴다 */
export function postFeedback(turnId: string, body: FeedbackIn): Promise<FeedbackOut> {
  return request("POST", `/api/turns/${encodeURIComponent(turnId)}/feedback`, body);
}

// ----- 7-2 WebSocket /ws/chat/{session_id} -----

export interface ChatSocketHandlers {
  onMessage: (msg: ServerMessage) => void;
  /** 서버 쪽에서 닫혔을 때만 온다(우리가 close()한 것은 오지 않는다). 4404 = 없는·종료된 세션 */
  onClose: (code: number) => void;
}

export interface ChatSocket {
  send: (msg: ClientMessage) => void;
  close: () => void;
}

export function openChatSocket(sessionId: string, handlers: ChatSocketHandlers): ChatSocket {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/ws/chat/${encodeURIComponent(sessionId)}`);
  const pending: string[] = []; // 연결이 열리기 전에 보낸 메시지 — 열리면 순서대로 보낸다
  let closedByUs = false;

  ws.onopen = () => {
    for (const m of pending.splice(0)) ws.send(m);
  };
  ws.onmessage = (ev) => {
    try {
      handlers.onMessage(JSON.parse(ev.data as string) as ServerMessage);
    } catch (e) {
      console.error("WS 메시지 해석 실패", e, ev.data);
    }
  };
  ws.onclose = (ev) => {
    if (ev.code === WS_CLOSE_UNAUTHORIZED) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    if (!closedByUs) handlers.onClose(ev.code);
  };

  return {
    send(msg) {
      const raw = JSON.stringify(msg);
      if (ws.readyState === WebSocket.OPEN) ws.send(raw);
      else if (ws.readyState === WebSocket.CONNECTING) pending.push(raw);
    },
    close() {
      closedByUs = true;
      ws.close();
    },
  };
}

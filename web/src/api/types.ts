// app/schemas.py와 같은 모양(09 6·7절). 서버가 계산해서 내려주는 값(Policy.type)도 응답에 들어 있다.

export type Mode = "일반" | "사내규정" | "업무특화";
export type Species = "강아지" | "고양이";
export type Grade = "고급형" | "기본형" | "실속형";
/** 검색 코퍼스. 사내규정 모드의 근거는 인사규정이라 Species만으로는 담을 수 없다(백엔드 schemas.py도 맞춰야 함 — species→corpus 이름 변경은 KNOWN_ISSUES) */
export type Corpus = Species | "인사규정";

// ----- 6-1 고객 -----

export interface Policy {
  doc_id: string;
  product_name: string;
  policy_version: string;
  section_name: string;
  coverage_type: Grade | null;
  copay: number | null;
  contract_date: string;
  renewal: string | null;
  excluded_conditions: string[];
  type: "Ⅰ" | "Ⅱ" | "Ⅲ" | null; // section_name에서 서버가 계산
}

export interface Pet {
  pet_id: string;
  name: string;
  species: Species;
  breed: string | null;
  age: number | null;
  policies: Policy[];
}

export interface Customer {
  customer_id: string;
  name: string;
  phone: string;
  pets: Pet[];
  // 종 조합 분류(card)는 폐기했다 — 백엔드 schemas.py의 computed card는 아직 남아 있으나 프론트는 쓰지 않는다
}

/** 고객별 마지막 상담 시각 — 고객 조회 "최근 상담" 탭과 카드 배지. GET /api/consultations/recent (sessions 테이블) */
export interface RecentConsultation {
  customer_id: string;
  last_consulted_at: string; // ISO
}

// ----- 7-1 REST -----

export interface SessionCreate {
  mode: Mode;
  customer_id?: string | null; // 업무특화면 필수, 나머지 모드는 보내면 422
}

export interface SessionOut {
  session_id: string;
  mode: Mode;
  customer_id: string | null;
  started_at: string;
}

/** GET /api/sessions?mode=&limit= — "지난 채팅" 목록 한 줄. 질문이 하나라도 있는 세션만 온다(빈 세션은 제목이 없다) */
export interface SessionSummary {
  session_id: string;
  mode: Mode;
  /** 첫 질문을 서버가 모델로 짧게 요약한 것. 세션의 첫 질문 때 한 번 만든다(모델이 안 되면 첫 줄을 자른 것) */
  title: string;
  /** 고정된 세션은 목록 맨 위에 모은다 */
  pinned: boolean;
  started_at: string;
  last_active_at: string; // 목록 정렬·상대 시간 기준
}

/** GET /api/sessions/{id} — 세션과 그 턴. 고객이 있는 세션(업무특화)은 남이 받은 상담도 열린다 — 연 쪽에서는 읽기 전용 */
export interface SessionDetail extends SessionOut {
  /** 그 상담을 담당했던 상담원 — 누가 안내한 내용인지 화면에 보인다 */
  agent_email: string;
  title: string | null;
  pinned: boolean;
  ended_at: string | null;
  turns: TurnOut[];
}

/** GET /api/customers/{id}/sessions 한 줄 — 그 고객의 과거 상담(09 2-2). 담당 상담원과 무관하게 전부, 시작 시각 역순 */
export interface CustomerSessionSummary {
  session_id: string;
  mode: Mode;
  title: string;
  agent_email: string;
  started_at: string;
  ended_at: string | null; // null = 아직 진행 중
}

/** PATCH /api/sessions/{id} — 지난 채팅 항목 메뉴(고정, 이름 변경). 보낸 필드만 바꾼다 */
export interface SessionPatch {
  title?: string;
  pinned?: boolean;
}

/** GET /api/sessions/{id}의 turns — 지난 대화를 다시 열 때 화면에 다시 그릴 턴(로그 turns·retrieved 테이블에서 뽑는다) */
/** 그 턴에 적용된 특약 하나(turn_scope) — 당시 값이다. 고객 데이터가 바뀌어도 그대로(12번 2-2절) */
export interface ScopeRow {
  section_name: string;
  coverage_type: Grade | null;
  copay: number | null;
  excluded_conditions: string[];
}

/** 멀티턴 처리 종류(09 5절) — rewrite: 사내규정 재작성 / concat: 업무특화 앞 질문과 이어서 검색 / history: 일반 이력 전달 */
export type ContextKind = "rewrite" | "concat" | "history";

/** 후속 질문을 앞 대화로 어떻게 풀었는지 — 화면의 ↳ 줄 */
export interface TurnContextInfo {
  kind: ContextKind;
  reason: string | null; // 후속으로 본 규칙(지시어·생략 꼬리·금액만·짧음)
  text: string | null; // rewrite: 재작성된 질문 / concat: 이어 붙인 앞 질문
  turns: number | null; // history: 전달한 이력 턴 수
}

export interface TurnOut {
  turn_id: string;
  question: string;
  rewritten_question: string | null; // 기준 질문(멀티턴). 단독 질문이면 null
  follow_up: string | null;
  context_kind: ContextKind | null;
  context_turns: number | null;
  pet_id: string | null;
  /** 그 턴의 반려동물·가입 내용 스냅샷. 과거 상담 화면은 지금 고객 데이터가 아니라 이 값으로 그린다 */
  pet_name: string | null;
  species: Species | null;
  scope: ScopeRow[];
  answer: string;
  payout: CalcResult | null; // 그 턴의 계산 카드(turns.payout)
  sources: SourceItem[];
  references: ReferenceItem[];
  latency_ms: number | null;
  first_token_ms: number | null;
  timestamp: string;
}

export interface ArticleOut {
  species: Corpus;
  section: string;
  section_name: string | null;
  article_num: number | null;
  coverage_type: Grade | null;
  paragraph_num: number | null;
  content: string;
}

export interface FeedbackIn {
  rating: "up" | "down";
  comment?: string | null;
}

export interface FeedbackOut {
  turn_id: string;
  accepted: boolean;
}

// ----- 7-2 WebSocket: 클라이언트 → 서버 -----

export type ClientMessage =
  | { type: "question"; text: string; pet_id?: string | null }
  | { type: "cancel" }
  | { type: "clarify_answer"; turn_id: string; choice: string };

// ----- 7-2 WebSocket: 서버 → 클라이언트 (전부 turn_id를 가진다) -----

export interface SourceItem {
  graph_key: string;
  species: Corpus;
  section: string;
  section_name: string | null;
  article_num: number | null;
  article_title: string | null;
  coverage_type: Grade | null;
  score: number;
  content: string;
}

export interface ReferenceItem {
  citation_label: string;
  species: Corpus;
  section: string | null; // 법령 박스(그래프로 따라간 약관 밖 법령)는 null — 근거 패널의 어느 조문과도 같지 않다
  section_name: string | null;
  article_num: number | null;
  paragraph_num: number | null;
}

/** 날짜별 계산 한 줄 */
export interface DayRow {
  cost: number;
  surgery: boolean;
  mri: boolean;
  limit: number; // 그날 한도
  label: string; // 수술한 날 / 수술 안 한 날 / MRI 등 연간 첫 번째…
  payout: number;
}

/** 의료비 계산 카드(09 2-3) — 날마다 (치료비 - 자기부담금) × 보상비율을 그날 한도까지, 합계에 연간 남은 한도.
 *  kind가 없으면(법률비용 카드 전에 저장된 턴) 의료비다. days 이하가 없으면(10-21 여러 날 계산 전 카드) 하루·정확 */
export interface MedicalCalc {
  kind?: "medical";
  section_name: string;
  coverage_type: Grade;
  claimed: number; // 청구 치료비(합계)
  copay: number; // 1일당
  limit: number; // 수술하지 않은 날 1일 한도(하루면 그날 상황의 한도)
  payout: number; // 예상 지급액(범위면 고르게 나뉜 추정)
  note: string;
  rate_pct?: number | null; // 보상비율(%) — 예전 카드엔 없다
  setting?: "통원" | "입원" | null;
  days?: number;
  days_known?: boolean;
  exact?: boolean;
  day_rows?: DayRow[];
  range_min?: number | null;
  range_max?: number | null;
  even?: number | null;
  annual_total?: number | null;
  annual_used?: number | null;
  annual_remaining?: number | null;
  year_start?: string | null;
  capped?: boolean;
  mri_before?: number | null;
  assumptions?: string[];
  flow?: "question" | "ask";
}

/** 날짜별 금액 입력칸 하나의 미리 채운 값 */
export interface DayInput {
  cost: number | null;
  surgery: boolean;
  mri: boolean;
}

/** 날짜별 치료비 되묻기 — 일수(2~5)만큼 입력칸. 채우면 "300,000원(수술), 300,000원, …" 질문으로 보낸다 */
export interface DaysAskCalc {
  kind: "days_ask";
  section_name: string;
  coverage_type: Grade;
  setting: "통원" | "입원";
  days: number;
  total: number; // 앞서 말한 총액
  type: string; // Ⅰ/Ⅱ/Ⅲ — Ⅲ이면 MRI 표시도
  prefill: DayInput[];
  surgery_mentioned: boolean;
  note: string;
}

/** 법률비용 계산 카드 — 민사소송법률비용 특약 【별표3·4·5】. 소송 금액 없이 심급만 말하면 송달료만 있다 */
export interface LegalCalc {
  kind: "legal";
  section_name: string;
  claim_value: number | null; // 소송목적의 값
  bracket: string | null; // 【별표3】 적용 구간
  lawyer_limit: number | null; // 【별표3】 변호사비용 한도
  lawyer_max: number | null; // 변호사 보수 보험금 최대 = min(별표3 한도, 1소송당 상한)
  lawyer_copay: number;
  lawyer_cap: number;
  stamp: number | null; // 【별표4】 인지액
  instance: string | null;
  case_kind: string | null;
  service: number | null; // 【별표5】 송달료
  stamp_service_cap: number;
  note: string;
}

/** 한도 카드 한 줄 — 가입한 의료비 특약 하나 */
export interface LimitRow {
  section_name: string;
  coverage_type: Grade;
  type: string; // Ⅰ/Ⅱ/Ⅲ
  copay: number | null;
  rate_pct: number;
  non_surgery: number; // 수술하지 않은 날 1일 한도(Ⅲ은 MRI·CT·내시경 없는 날)
  surgery: number; // 수술한 날 1일 한도
  mri_1st: number | null; // Ⅲ만
  mri_2nd_plus: number | null;
  annual_total: number;
  annual_used?: number | null; // 올해(보험연도) 받은 보험금 — 가정 카드엔 없다
  annual_remaining?: number | null;
  mri_before?: number | null; // Ⅲ — 올해 받은 MRI·CT·내시경 날 수
}

/** 한도 카드 — 치료비 금액 없이 한도를 물으면 가입한 의료비 특약의 한도표 */
export interface LimitsCalc {
  kind: "limits";
  pet_name: string;
  rows: LimitRow[];
  highlight: "non_surgery" | "surgery" | "mri" | null; // 질문이 짚은 줄
  note: string;
  hypothetical?: boolean; // 가입과 다른 등급·유형을 물었다 — 그 등급의 표(이 고객의 한도가 아니다)
  enrolled?: string | null; // 가정 카드일 때 실제 가입
}

/** 계산 카드 — WS calc 메시지와 과거 턴(TurnOut.payout)이 같은 모양 */
export type CalcResult = MedicalCalc | LegalCalc | LimitsCalc | DaysAskCalc;

export type ServerMessage =
  // 멀티턴 — 후속 질문이면 sources 앞에 한 번
  | { type: "context"; turn_id: string; kind: ContextKind; reason: string; text: string | null; turns: number | null }
  | { type: "sources"; turn_id: string; items: SourceItem[] }
  | { type: "token"; turn_id: string; text: string }
  | { type: "clarify"; turn_id: string; options: string[] }
  | { type: "references"; turn_id: string; items: ReferenceItem[] }
  | { type: "done"; turn_id: string; latency_ms: number; first_token_ms: number | null }
  // 잘못된 메시지·남의 pet_id·검색/생성 실패
  | { type: "error"; turn_id: string; code: string; message: string }
  // 계산 카드 — 치료비가 들어간 질문이면 sources 다음에 한 번
  | { type: "calc"; turn_id: string; result: CalcResult }
  // 질문에 걸리는 부담보(서버 대조 — 분류표·같은 부위 이름까지). 걸린 것이 있을 때만
  | { type: "exclusions"; turn_id: string; items: string[] }
  // 답이 쓴 발췌의 표(서버가 원문 그대로, 질문에 맞는 행 강조). 모델이 답한 턴에서 표가 있을 때만
  | { type: "tables"; turn_id: string; items: TableItem[] };

/** 답 아래 표 한 개 — row_index는 보낸 행의 원래 번호, highlight도 원래 번호 */
export interface TableItem {
  source: string;
  header: string[];
  rows: string[][];
  row_index: number[];
  highlight: number | null;
  total_rows: number;
  collapsed: boolean;
}

/** WS 종료 코드 — 없는(만료된) 세션 */
export const WS_CLOSE_SESSION_NOT_FOUND = 4404;

// ----- 인증(13번 2-1절, 2026-10-28) — app/schemas.py MeOut·LoginIn·PasswordIn -----

export type AuthMode = "access" | "app";

export interface MeOut {
  auth_mode: AuthMode;
  email: string;
  employee_id: string | null;
  name: string | null;
  team: string | null;
  grade: string | null;
  role: "상담원" | "관리자" | null;
  must_change_password: boolean;
}

export interface LoginIn { employee_id: string; password: string }
export interface PasswordIn { current: string; new: string }

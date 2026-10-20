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

export interface TurnOut {
  turn_id: string;
  question: string;
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

/** 의료비 계산 카드(09 2-3) — limit_table.calculate_payout 결과. kind가 없으면(법률비용 카드 전에 저장된 턴) 의료비다 */
export interface MedicalCalc {
  kind?: "medical";
  section_name: string;
  coverage_type: Grade;
  claimed: number; // 청구 치료비
  copay: number;
  limit: number;
  payout: number;
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
}

/** 한도 카드 — 치료비 금액 없이 한도를 물으면 가입한 의료비 특약의 한도표 */
export interface LimitsCalc {
  kind: "limits";
  pet_name: string;
  rows: LimitRow[];
  highlight: "non_surgery" | "surgery" | "mri" | null; // 질문이 짚은 줄
  note: string;
}

/** 계산 카드 — WS calc 메시지와 과거 턴(TurnOut.payout)이 같은 모양 */
export type CalcResult = MedicalCalc | LegalCalc | LimitsCalc;

export type ServerMessage =
  | { type: "sources"; turn_id: string; items: SourceItem[] }
  | { type: "token"; turn_id: string; text: string }
  | { type: "clarify"; turn_id: string; options: string[] }
  | { type: "references"; turn_id: string; items: ReferenceItem[] }
  | { type: "done"; turn_id: string; latency_ms: number; first_token_ms: number | null }
  // 잘못된 메시지·남의 pet_id·검색/생성 실패
  | { type: "error"; turn_id: string; code: string; message: string }
  // 계산 카드 — 치료비가 들어간 질문이면 sources 다음에 한 번
  | { type: "calc"; turn_id: string; result: CalcResult };

/** WS 종료 코드 — 없는(만료된) 세션 */
export const WS_CLOSE_SESSION_NOT_FOUND = 4404;

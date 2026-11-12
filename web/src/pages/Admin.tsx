// 관리자 화면(2026-11-12, 13번 2-5절) — 상담원별 상담 조회 · 직원 목록. 읽기만 한다.
// - Grafana(전체 추세)와 역할이 다르다 — 여기는 개별 상담을 연다. 숫자 · 그래프는 다시 그리지 않는다(상담원별 건수만).
// - 일반 모드는 서버가 빼고 준다. 대화는 지난 상담 창과 같은 TurnView(readOnly) + 거절 · 평가 표시.
// - 1024px 이상은 두 칸(상담원 | 상담 목록), 그보다 좁으면 한 칸씩(상담원 → 상담 목록, 「← 상담원」).
// - 글씨는 대화 화면 배율(.chat-text) 안의 기존 토큰만 쓴다 — 새 크기를 만들지 않는다.

import { useEffect, useState } from "react";
import { ApiError, getAdminSession, listAdminAgents, listAdminEmployees, listAdminSessions } from "../api/client";
import type { AdminAgent, AdminEmployee, AdminSession, AdminSessionDetail, AdminSessionList } from "../api/types";
import { matchExclusions } from "../components/ExclusionBanner";
import { TurnView } from "../components/TurnView";
import { turnFromOut } from "../hooks/useChatSocket";
import s from "./Admin.module.css";

const MAX_DAYS = 31;   // 서버(app/services/admin.py)와 같다

/** KST 날짜 YYYY-MM-DD — 서버 기간도 KST 날짜다 */
function kstDate(d = new Date()): string {
  return d.toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });
}
function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
function spanDays(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000) + 1;
}
/** 화면에는 권한(관리자 · 상담원)만 쓴다 — 직급과 권한은 따로다(13번 2-5절). 앱 계정이 없어도 고객상담팀 상담원이다 */
const roleLabel = (role: string | null) => (role === "관리자" ? "관리자" : "상담원");
const errText = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

type Tab = "sessions" | "staff";

export function Admin() {
  const [tab, setTab] = useState<Tab>("sessions");
  return (
    <div className={`chat-text ${s.page}`}>
      <div className={s.head}>
        <h1 className={s.title}>관리자 화면</h1>
        <p className={s.intro}>
          상담원마다 고른 기간에 나눈 업무특화 · 사내규정 상담을 열어, 상담원이 무엇을 물었고 챗봇이 무엇을 답했는지,
          답이 기댄 근거 조항, 챗봇이 답하지 못한 턴(거절), 상담원이 남긴 👍👎 평가를 그대로 봅니다.
          일반 모드 대화는 개인적인 질문이라 보이지 않습니다. 직원 탭은 인사 원장의 직원 목록을 보여 줍니다.
          이 화면에서는 아무것도 바꾸지 않으며, 상담을 열어 본 기록은 남습니다. 전체 추세(질문 수 · 거절률 · 응답 시간)는 Grafana에서 봅니다.
        </p>
      </div>
      <nav className={s.tabs} aria-label="관리자 화면">
        <button type="button" className={`btn ${s.tab} ${tab === "sessions" ? "selected" : ""}`} aria-current={tab === "sessions" || undefined}
                onClick={() => setTab("sessions")}>상담 조회</button>
        <button type="button" className={`btn ${s.tab} ${tab === "staff" ? "selected" : ""}`} aria-current={tab === "staff" || undefined}
                onClick={() => setTab("staff")}>직원</button>
      </nav>
      {tab === "sessions" ? <Sessions /> : <Staff />}
    </div>
  );
}

// ----- 상담 조회

function Sessions() {
  const today = kstDate();
  const [range, setRange] = useState({ from: today, to: today });
  const [agents, setAgents] = useState<AdminAgent[] | null>(null);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const span = spanDays(range.from, range.to);
  const rangeError = span < 1 ? "끝 날짜가 시작 날짜보다 앞입니다." : span > MAX_DAYS ? `기간은 ${MAX_DAYS}일까지 고를 수 있습니다.` : null;

  useEffect(() => {
    if (rangeError) return;
    let alive = true;
    setAgents(null); setError(null);
    listAdminAgents(range.from, range.to).then((xs) => { if (alive) setAgents(xs); }, (e) => { if (alive) setError(errText(e)); });
    return () => { alive = false; };
  }, [range.from, range.to, rangeError]);

  const quick = (days: number) => setRange({ from: addDays(today, -(days - 1)), to: today });
  const isQuick = (days: number) => range.to === today && range.from === addDays(today, -(days - 1));
  const label = range.from === range.to ? (range.from === today ? "오늘" : range.from.slice(5)) : `${span}일`;
  const agent = agents?.find((a) => a.employee_id === agentId) ?? null;

  return (
    <>
      <div className={s.range}>
        <span className={s.quick}>
          {[[1, "오늘"], [7, "7일"], [30, "30일"]].map(([d, t]) => (
            <button key={t} type="button" className={`btn ${s.tab} ${isQuick(d as number) ? "selected" : ""}`} onClick={() => quick(d as number)}>{t}</button>
          ))}
        </span>
        <label className={s.date}>
          <span className={s.dateLabel}>시작</span>
          <input type="date" value={range.from} max={today} onChange={(e) => e.target.value && setRange((r) => ({ ...r, from: e.target.value }))} />
        </label>
        <label className={s.date}>
          <span className={s.dateLabel}>끝</span>
          <input type="date" value={range.to} max={today} onChange={(e) => e.target.value && setRange((r) => ({ ...r, to: e.target.value }))} />
        </label>
        {rangeError && <span className={s.err} role="alert">{rangeError}</span>}
      </div>

      <div className={`${s.split} ${agentId ? s.picked : ""}`}>
        <section className={`raised ${s.agents}`} aria-label="상담원">
          {error && <p className={s.err}>{error}</p>}
          {!error && !agents && !rangeError && <p className={s.empty}>불러오는 중…</p>}
          {agents && (
            <ul className={s.list}>
              {agents.map((a) => (
                <li key={a.employee_id}>
                  <button type="button" data-agent={a.employee_id} className={`${s.item} ${a.employee_id === agentId ? "selected" : ""}`}
                          aria-current={a.employee_id === agentId || undefined} onClick={() => setAgentId(a.employee_id)}>
                    <span className={s.itemTitle}>
                      {a.name} <span className={s.dim}>{roleLabel(a.role)}</span>
                      {a.retired && <span className={s.tag}>퇴직</span>}
                    </span>
                    <span className={s.itemMeta}>
                      {label} {a.sessions}건{a.customers > 0 && <>, 고객 {a.customers}명</>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className={`raised ${s.sessions}`} aria-label="상담 목록">
          {agent
            ? <AgentSessions key={`${agent.employee_id} ${range.from} ${range.to}`} agent={agent} from={range.from} to={range.to}
                             multiDay={range.from !== range.to} onBack={() => setAgentId(null)} />
            : <p className={s.empty}>왼쪽에서 상담원을 고르세요.</p>}
        </section>
      </div>
    </>
  );
}

function AgentSessions({ agent, from, to, multiDay, onBack }:
                       { agent: AdminAgent; from: string; to: string; multiDay: boolean; onBack: () => void }) {
  const [list, setList] = useState<AdminSessionList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [more, setMore] = useState(false);

  /** 「더 보기」 — 다음 묶음(서버가 200건씩)을 뒤에 붙인다 */
  const loadMore = () => {
    if (!list) return;
    setMore(true);
    listAdminSessions(agent.employee_id, from, to, list.items.length).then(
      (x) => setList((l) => (l ? { ...l, items: [...l.items, ...x.items] } : x)),
      (e) => setError(errText(e))).finally(() => setMore(false));
  };

  useEffect(() => {
    let alive = true;
    listAdminSessions(agent.employee_id, from, to).then((x) => { if (alive) setList(x); }, (e) => { if (alive) setError(errText(e)); });
    return () => { alive = false; };
  }, [agent.employee_id, from, to]);

  return (
    <>
      <div className={s.listHead}>
        <button type="button" className={`btn ${s.back}`} onClick={onBack}>← 상담원</button>
        <h2 className={s.subTitle}>{agent.name} {roleLabel(agent.role)}</h2>
        {list && <span className={s.itemMeta}>{list.total > list.items.length ? `${list.total}건 중 최신 ${list.items.length}건` : `${list.total}건`}</span>}
      </div>
      {error && <p className={s.err}>{error}</p>}
      {!error && !list && <p className={s.empty}>불러오는 중…</p>}
      {list && list.items.length === 0 && <p className={s.empty}>이 기간에 상담이 없습니다.</p>}
      {list && list.items.length > 0 && (
        <ul className={s.list}>
          {list.items.map((it) => (
            <li key={it.session_id} className={open === it.session_id ? s.openItem : undefined}>
              <button type="button" data-session={it.session_id} className={s.item} aria-expanded={open === it.session_id}
                      onClick={() => setOpen((o) => (o === it.session_id ? null : it.session_id))}>
                <SessionRow it={it} multiDay={multiDay} />
              </button>
              {open === it.session_id && <SessionDetail sessionId={it.session_id} />}
            </li>
          ))}
        </ul>
      )}
      {list && list.total > list.items.length && (
        <div className={s.moreRow}>
          <button type="button" className={`btn ${s.tab}`} onClick={loadMore} disabled={more}>
            {more ? "불러오는 중…" : `더 보기 (${list.total - list.items.length}건 남음)`}
          </button>
        </div>
      )}
    </>
  );
}

function hhmm(iso: string, withDate: boolean): string {
  const d = new Date(iso);
  const t = d.toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false });
  return withDate ? `${kstDate(d).slice(5)} ${t}` : t;
}

function SessionRow({ it, multiDay }: { it: AdminSession; multiDay: boolean }) {
  const who = it.mode === "업무특화"
    ? `${it.customer_name ?? "고객"}${it.pet_names.length ? ` / ${it.pet_names.join(", ")}` : ""}`
    : "(사내규정)";
  return (
    <>
      <span className={s.row}>
        <time className={s.time} dateTime={it.started_at}>{hhmm(it.started_at, multiDay)}</time>
        <span className={s.who}>{who}</span>
        {it.mode === "업무특화" && <span className={s.tag}>업무특화</span>}
        <span className={s.turns}>{it.turns}턴</span>
      </span>
      <span className={s.itemMeta}>
        {it.title && <span className={s.titleText}>{it.title}</span>}
        {it.refused > 0 && <span className={s.refused}>거절 {it.refused}</span>}
        {it.mode === "업무특화" && it.ended_at === null && <span className={s.live}>진행 중</span>}
        {it.hidden && <span className={s.tag}>목록에서 지움</span>}
      </span>
    </>
  );
}

function SessionDetail({ sessionId }: { sessionId: string }) {
  const [d, setD] = useState<AdminSessionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    getAdminSession(sessionId).then((x) => { if (alive) setD(x); }, (e) => { if (alive) setError(errText(e)); });
    return () => { alive = false; };
  }, [sessionId]);
  if (error) return <p className={s.err}>{error}</p>;
  if (!d) return <p className={s.empty}>불러오는 중…</p>;
  return (
    <div className={s.detail}>
      <div className={s.itemMeta}>
        <span>{new Date(d.started_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}</span>
        <span>담당 <b>{d.agent_name ?? d.agent_email}</b></span>
        {d.customer_name && <span>고객 <b>{d.customer_name}</b></span>}
        <span className={s.readOnly}>읽기 전용</span>
      </div>
      {d.turns.map((t) => (
        <TurnView key={t.turn_id} turn={turnFromOut(t)} inlineSources="always" readOnly
                  marks={{ refused: t.refused, rating: t.rating, comment: t.rating_comment }}
                  exclusions={matchExclusions(`${t.rewritten_question ?? ""} ${t.question}`, t.scope.flatMap((p) => p.excluded_conditions))} />
      ))}
    </div>
  );
}

// ----- 직원 목록 — 인사 원장 그대로(읽기만). 급여 · 평가 · 휴가는 없다. 표 머리를 눌러 정렬, 위에 필터 셋

const GRADE_ORDER: Record<string, number> = { 부장: 5, 차장: 4, 과장: 3, 대리: 2, 사원: 1 };   // 직급 순서(가나다순이 아니다)

type SortKey = "employee_id" | "name" | "grade" | "employment_type" | "hire_date" | "tenure" | "status" | "account";
const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "employee_id", label: "사번" }, { key: "name", label: "이름" }, { key: "grade", label: "직급" },
  { key: "employment_type", label: "고용" }, { key: "hire_date", label: "입사일" }, { key: "tenure", label: "근속" },
  { key: "status", label: "재직" }, { key: "account", label: "앱 계정" },
];
const accountText = (r: AdminEmployee) => (r.role ? `${r.role}${r.disabled ? " 중지" : ""}` : "없음");

function sortValue(r: AdminEmployee, k: SortKey): string | number {
  switch (k) {
    case "grade": return GRADE_ORDER[r.grade] ?? 0;
    case "tenure": return r.tenure_years * 12 + r.tenure_months;
    case "status": return r.retired_on ? `1 ${r.retired_on}` : "0";
    case "account": return accountText(r);
    default: return r[k];
  }
}

type Filter = { status: "all" | "active" | "retired"; type: string; account: "all" | "yes" | "no" };

function Chips<T extends string>({ label, value, options, onChange }:
                                 { label: string; value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <span className={s.filter} role="group" aria-label={label}>
      <span className={s.dateLabel}>{label}</span>
      {options.map(([v, t]) => (
        <button key={v} type="button" className={`btn ${s.chip} ${value === v ? "selected" : ""}`} aria-pressed={value === v}
                onClick={() => onChange(v)}>{t}</button>
      ))}
    </span>
  );
}

function Staff() {
  const [rows, setRows] = useState<AdminEmployee[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; asc: boolean }>({ key: "employee_id", asc: true });
  const [filter, setFilter] = useState<Filter>({ status: "all", type: "all", account: "all" });
  useEffect(() => {
    let alive = true;
    listAdminEmployees().then((x) => { if (alive) setRows(x); }, (e) => { if (alive) setError(errText(e)); });
    return () => { alive = false; };
  }, []);

  const types = rows ? [...new Set(rows.map((r) => r.employment_type))] : [];
  const shown = (rows ?? [])
    .filter((r) => filter.status === "all" || (filter.status === "retired") === (r.retired_on !== null))
    .filter((r) => filter.type === "all" || r.employment_type === filter.type)
    .filter((r) => filter.account === "all" || (filter.account === "yes") === (r.role !== null))
    .sort((a, b) => {
      const x = sortValue(a, sort.key), y = sortValue(b, sort.key);
      const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "ko");
      return (sort.asc ? c : -c) || a.employee_id.localeCompare(b.employee_id);
    });
  const toggle = (key: SortKey) => setSort((p) => (p.key === key ? { key, asc: !p.asc } : { key, asc: true }));

  return (
    <section className={`raised ${s.staff}`} aria-label="직원 목록">
      <p className={s.staffNote}>인사 원장(기간계)을 그대로 보여 줍니다. 직원 추가, 계정 중지, 비밀번호 초기화는 인사 시스템에서 처리합니다.</p>
      {rows && (
        <div className={s.filters}>
          <Chips label="재직" value={filter.status} onChange={(v) => setFilter((f) => ({ ...f, status: v }))}
                 options={[["all", "전체"], ["active", "재직"], ["retired", "퇴직"]]} />
          <Chips label="고용" value={filter.type} onChange={(v) => setFilter((f) => ({ ...f, type: v }))}
                 options={[["all", "전체"], ...types.map((t): [string, string] => [t, t])]} />
          <Chips label="앱 계정" value={filter.account} onChange={(v) => setFilter((f) => ({ ...f, account: v }))}
                 options={[["all", "전체"], ["yes", "있음"], ["no", "없음"]]} />
          <span className={s.count}>{shown.length}명</span>
        </div>
      )}
      {error && <p className={s.err}>{error}</p>}
      {!error && !rows && <p className={s.empty}>불러오는 중…</p>}
      {rows && (
        <div className={s.tableWrap}>
          <table className={s.table}>
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th key={c.key} aria-sort={sort.key === c.key ? (sort.asc ? "ascending" : "descending") : "none"}>
                    <button type="button" className={s.sortBtn} onClick={() => toggle(c.key)}>
                      {c.label}<span className={s.sortMark} aria-hidden>{sort.key === c.key ? (sort.asc ? "▲" : "▼") : ""}</span>
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.employee_id}>
                  <td className={s.mono}>{r.employee_id}</td>
                  <td><b>{r.name}</b></td>
                  <td>{r.grade}</td>
                  <td>{r.employment_type}</td>
                  <td>{r.hire_date}</td>
                  <td>{r.tenure_years ? `${r.tenure_years}년 ` : ""}{r.tenure_months}개월</td>
                  <td>{r.retired_on ? <span className={s.tag}>퇴직 {r.retired_on}</span> : "재직"}</td>
                  <td>{r.role ? <>{r.role}{r.disabled && <span className={s.tag}>중지</span>}</> : <span className={s.dim}>없음</span>}</td>
                </tr>
              ))}
              {shown.length === 0 && <tr><td colSpan={COLUMNS.length} className={s.dim}>조건에 맞는 직원이 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

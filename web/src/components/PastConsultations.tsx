import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ApiError, getSession, listCustomerSessions } from "../api/client";
import type { Customer, CustomerSessionSummary, ScopeRow, SessionDetail, TurnOut } from "../api/types";
import { relativeTime, shortSection, SPECIES_ICON, won } from "../format";
import { turnFromOut } from "../hooks/useChatSocket";
import { useNow } from "../hooks/useNow";
import { matchExclusions } from "./ExclusionBanner";
import { TurnView } from "./TurnView";
import s from "./PastConsultations.module.css";

interface Props {
  customer: Customer;
  /** 지금 진행 중인 상담 — 목록에서 뺀다(상담 화면에서 부를 때) */
  excludeSessionId?: string;
}

type View = { kind: "list" } | { kind: "detail"; sessionId: string };

/** 고객 하나에 딸린 과거 상담(09 2-2). 고객 조회 카드와 상담 화면 고객 카드 두 곳에서 부른다 — 둘 다 모달로 덮는다.
 *  상담 화면에서 화면을 바꾸지 않는 이유: 진행 중 상담을 잃는다. 모달은 상담 화면 위에 덮일 뿐이라 세션·WS는 그대로다.
 *  열린 과거 상담은 소유자와 무관하게 읽기 전용이다 — 입력창이 없고, 이어서 질문할 수 없다 */
export function PastConsultations({ customer, excludeSessionId }: Props) {
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);

  // 닫힌 dialog를 열 때만 showModal — Esc·배경 클릭으로 닫히면 onClose가 상태를 맞춘다
  useEffect(() => {
    const d = dialog.current;
    if (open && d && !d.open) d.showModal();
  }, [open]);

  return (
    <>
      <button type="button" className={`btn ${s.trigger}`} onClick={(e) => { e.stopPropagation(); setOpen(true); }}>
        과거 상담
      </button>
      {open && createPortal(
        <dialog ref={dialog} className={`raised ${s.dialog}`} aria-label={`${customer.name} 고객 과거 상담`}
                onClose={() => setOpen(false)}
                onClick={(e) => { e.stopPropagation(); if (e.target === dialog.current) dialog.current?.close(); }}>
          <PastBody customer={customer} excludeSessionId={excludeSessionId} onClose={() => dialog.current?.close()} />
        </dialog>,
        document.body,
      )}
    </>
  );
}

function PastBody({ customer, excludeSessionId, onClose }: Props & { onClose: () => void }) {
  const [view, setView] = useState<View>({ kind: "list" });
  return (
    <div className={s.body}>
      <header className={s.head}>
        {view.kind === "detail"
          ? <button type="button" className="btn" onClick={() => setView({ kind: "list" })}>← 목록</button>
          : <h2 className={s.title}>{customer.name} 고객 과거 상담</h2>}
        <button type="button" className={s.close} onClick={onClose} aria-label="닫기">✕</button>
      </header>
      {view.kind === "list"
        ? <PastList customerId={customer.customer_id} excludeSessionId={excludeSessionId}
                    onOpen={(id) => setView({ kind: "detail", sessionId: id })} />
        : <PastDetail sessionId={view.sessionId} />}
    </div>
  );
}

const errText = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

function PastList({ customerId, excludeSessionId, onOpen }:
                  { customerId: string; excludeSessionId?: string; onOpen: (id: string) => void }) {
  const [items, setItems] = useState<CustomerSessionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const now = useNow(60_000);

  useEffect(() => {
    let alive = true;
    listCustomerSessions(customerId).then(
      (xs) => { if (alive) setItems(xs.filter((x) => x.session_id !== excludeSessionId)); },
      (e) => { if (alive) setError(errText(e)); });
    return () => { alive = false; };
  }, [customerId, excludeSessionId]);

  if (error) return <p className={s.err}>{error}</p>;
  if (!items) return <p className="dim">불러오는 중…</p>;
  if (!items.length) return <p className={s.empty}>지난 상담 기록이 없습니다.</p>;
  return (
    <ul className={s.list}>
      {items.map((it) => (
        <li key={it.session_id}>
          <button type="button" className={s.item} onClick={() => onOpen(it.session_id)}>
            <span className={s.itemTitle}>{it.title}</span>
            <span className={s.itemMeta}>
              <time dateTime={it.started_at} title={new Date(it.started_at).toLocaleString("ko-KR")}>
                {relativeTime(it.started_at, now)}
              </time>
              <span>담당 {it.agent_email}</span>
              {it.ended_at === null && <span className={s.live}>진행 중</span>}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** 턴의 스냅샷 한 줄 — 그때 이야기한 반려동물과 적용된 특약·등급·자기부담금·부담보. 앞 턴과 같으면 다시 그리지 않는다 */
function snapshotKey(t: TurnOut) {
  return JSON.stringify([t.pet_id, t.scope]);
}

function Snapshot({ t }: { t: TurnOut }) {
  const excl = t.scope.flatMap((p) => p.excluded_conditions);
  const chips = t.scope.filter((p) => p.excluded_conditions.length === 0);
  return (
    <div className={s.snap} aria-label="당시 가입 내용">
      <span className={s.snapLabel}>당시</span>
      {t.pet_name && <span className={s.snapPet}>{t.species && SPECIES_ICON[t.species]} {t.pet_name}</span>}
      {chips.map((p: ScopeRow) => (
        <span key={p.section_name} className={s.chip}>
          {shortSection(p.section_name)}
          {p.coverage_type && <> <b>{p.coverage_type}</b></>}
          {p.copay !== null && <> · 자기부담 {won(p.copay)}</>}
        </span>
      ))}
      {excl.length > 0 && <span className={s.excl}><b>부담보</b> {excl.join(", ")}</span>}
    </div>
  );
}

function PastDetail({ sessionId }: { sessionId: string }) {
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getSession(sessionId).then((d) => { if (alive) setDetail(d); }, (e) => { if (alive) setError(errText(e)); });
    return () => { alive = false; };
  }, [sessionId]);

  if (error) return <p className={s.err}>{error}</p>;
  if (!detail) return <p className="dim">불러오는 중…</p>;
  return (
    <>
      <div className={s.detailHead}>
        <h2 className={s.title}>{detail.title ?? "제목 없음"}</h2>
        <div className={s.itemMeta}>
          <span>{new Date(detail.started_at).toLocaleString("ko-KR")}</span>
          <span>담당 <b>{detail.agent_email}</b></span>
          <span className={s.readOnly}>읽기 전용</span>
          {detail.ended_at === null && <span className={s.live}>진행 중</span>}
        </div>
      </div>
      <div className={s.turns}>
        {detail.turns.length === 0 && <p className={s.empty}>대화 없이 끝난 상담입니다.</p>}
        {detail.turns.map((t, i) => (
          <div key={t.turn_id} className={s.turn}>
            {(i === 0 || snapshotKey(t) !== snapshotKey(detail.turns[i - 1])) && t.pet_id && <Snapshot t={t} />}
            <TurnView turn={turnFromOut(t)} inlineSources="always" readOnly
                      exclusions={matchExclusions(t.question, t.scope.flatMap((p) => p.excluded_conditions))} />
          </div>
        ))}
      </div>
      <p className={s.note}>과거 상담은 읽기 전용입니다. 이어서 질문할 수 없습니다 — 물을 것이 있으면 닫고 지금 상담에서 물어보세요.</p>
    </>
  );
}

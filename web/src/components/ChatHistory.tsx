import { useEffect, useRef, useState } from "react";
import { ApiError, deleteSession, listSessions, updateSession } from "../api/client";
import type { SessionSummary } from "../api/types";
import { relativeTime } from "../format";
import { useNow } from "../hooks/useNow";
import s from "./ChatHistory.module.css";

interface Props {
  mode: "일반" | "사내규정";
  currentId: string | null;
  /** 바뀌면 목록을 다시 불러온다 — 질문을 보내거나 답이 끝날 때(첫 질문 뒤 제목이 생기고, 마지막 활동 시각이 바뀐다) */
  refreshKey: string;
  collapsed: boolean;
  onToggle: () => void;
  onOpen: (s: SessionSummary) => void;
  onNewChat: () => void;
  newChatDisabled: boolean;
  /** 지난 채팅을 목록에서 제거했다 — 지금 보던 대화면 Chat이 새 대화로 바꾼다 */
  onDeleted: (sessionId: string) => void;
  /** 사용자가 끌어서 정한 폭(px). null이면 CSS 기본 폭 */
  width: number | null;
}

/** 항목 메뉴 — ⋮ 버튼 바로 아래에 뜬다. 목록이 스크롤돼도 잘리지 않게 화면 기준(fixed)으로 둔다 */
interface Menu {
  item: SessionSummary;
  /** 아래로 열 때 top, 화면 아래쪽 항목이면 위로 열어 bottom */
  top?: number;
  bottom?: number;
  right: number;
  confirmDelete: boolean;
}

/** "지난 채팅" — 일반·사내규정 대화창 왼쪽. 모드마다 자기 세션만 보인다(업무특화에는 두지 않는다) */
export function ChatHistory({ mode, currentId, refreshKey, collapsed, onToggle, onOpen, onNewChat, newChatDisabled,
                              onDeleted, width }: Props) {
  const newTitle = newChatDisabled ? "질문을 하나 보내면 새 대화를 열 수 있습니다" : undefined;
  const [items, setItems] = useState<SessionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; draft: string } | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const now = useNow(60_000);

  useEffect(() => {
    let alive = true;
    listSessions(mode)
      .then((list) => { if (alive) { setItems(list); setError(null); } })
      .catch((e) => { if (alive) setError(e instanceof ApiError ? e.detail : String(e)); });
    return () => { alive = false; };
  }, [mode, refreshKey, reload]);

  // 메뉴는 바깥을 누르거나 Esc, 스크롤·창 크기 변경이면 닫는다(떠 있는 위치가 항목과 어긋나므로)
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    const onDown = (e: PointerEvent) => { if (!menuRef.current?.contains(e.target as Node)) close(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", close);
    document.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", close);
      document.removeEventListener("scroll", close, true);
    };
  }, [menu]);

  const fail = (e: unknown) => setError(e instanceof ApiError ? e.detail : String(e));

  const openMenu = (it: SessionSummary, btn: HTMLElement) => {
    if (menu?.item.session_id === it.session_id) return setMenu(null);
    const r = btn.getBoundingClientRect();
    const right = window.innerWidth - r.right;
    const roomBelow = window.innerHeight - r.bottom;
    setMenu(roomBelow < 200 // 메뉴·제거 확인이 들어갈 만큼 남지 않았다
      ? { item: it, bottom: window.innerHeight - r.top + 4, right, confirmDelete: false }
      : { item: it, top: r.bottom + 4, right, confirmDelete: false });
  };

  const togglePin = async (it: SessionSummary) => {
    setMenu(null);
    try { await updateSession(it.session_id, { pinned: !it.pinned }); setReload((n) => n + 1); } catch (e) { fail(e); }
  };

  const startRename = (it: SessionSummary) => {
    setMenu(null);
    setRenaming({ id: it.session_id, draft: it.title });
  };

  const commitRename = async () => {
    if (!renaming) return;
    const { id, draft } = renaming;
    setRenaming(null);
    const old = items?.find((x) => x.session_id === id)?.title;
    if (!draft.trim() || draft.trim() === old) return; // 비우거나 그대로면 바꾸지 않는다
    try { await updateSession(id, { title: draft }); setReload((n) => n + 1); } catch (e) { fail(e); }
  };

  const remove = async (it: SessionSummary) => {
    setMenu(null);
    try {
      await deleteSession(it.session_id);
      onDeleted(it.session_id);
      setReload((n) => n + 1);
    } catch (e) { fail(e); }
  };

  if (collapsed) {
    return (
      <aside className={`${s.side} ${s.rail}`}>
        <button className={s.toggle} onClick={onToggle} aria-label="지난 채팅 펼치기" aria-expanded={false} title="지난 채팅">›</button>
        <button className={s.toggle} onClick={onNewChat} disabled={newChatDisabled} aria-label="새 대화" title={newTitle ?? "새 대화"}>＋</button>
      </aside>
    );
  }

  const pinned = items?.filter((it) => it.pinned) ?? [];
  const rest = items?.filter((it) => !it.pinned) ?? [];

  const row = (it: SessionSummary) => {
    const current = it.session_id === currentId;
    const menuOpen = menu?.item.session_id === it.session_id;
    if (renaming?.id === it.session_id) {
      return (
        <li key={it.session_id} className={s.row}>
          <input className={s.rename} value={renaming.draft} autoFocus aria-label="새 제목" maxLength={100}
                 onFocus={(e) => e.currentTarget.select()}
                 onChange={(e) => setRenaming({ id: it.session_id, draft: e.target.value })}
                 onKeyDown={(e) => {
                   if (e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); void commitRename(); }
                   if (e.key === "Escape") setRenaming(null);
                 }}
                 onBlur={() => void commitRename()} />
        </li>
      );
    }
    return (
      <li key={it.session_id} className={`${s.row} ${current ? s.current : ""} ${menuOpen ? s.rowMenuOpen : ""}`}>
        <button className={s.item} onClick={() => onOpen(it)} aria-current={current || undefined} title={it.title}>
          <span className={s.itemTitle}>{it.title}</span>
          <span className={s.time}>{relativeTime(it.last_active_at, now)}</span>
        </button>
        <button className={s.more} aria-label={`${it.title} 메뉴`} aria-haspopup="menu" aria-expanded={menuOpen}
                onClick={(e) => openMenu(it, e.currentTarget)}>⋮</button>
      </li>
    );
  };

  return (
    <aside className={s.side} aria-label="지난 채팅" style={width === null ? undefined : { width }}>
      <div className={s.top}>
        <button className={`btn ${s.newChat}`} onClick={onNewChat} disabled={newChatDisabled} title={newTitle}>＋ 새 대화</button>
        <button className={s.toggle} onClick={onToggle} aria-label="지난 채팅 접기" aria-expanded title="접기">‹</button>
      </div>
      {error && <div className={s.note}>{error}</div>}
      {!error && items === null && <div className={s.note}>불러오는 중…</div>}
      {items?.length === 0 && <div className={s.note}>아직 지난 채팅이 없습니다.</div>}
      <div className={s.scroll}>
        {pinned.length > 0 && (
          <>
            <h2 className={s.title}>고정</h2>
            <ul className={s.list}>{pinned.map(row)}</ul>
          </>
        )}
        {rest.length > 0 && (
          <>
            <h2 className={s.title}>지난 채팅</h2>
            <ul className={s.list}>{rest.map(row)}</ul>
          </>
        )}
      </div>

      {menu && (
        <div ref={menuRef} className={s.menu} role="menu" style={{ top: menu.top, bottom: menu.bottom, right: menu.right }}>
          {menu.confirmDelete ? (
            <div className={s.confirm}>
              <p>이 대화를 목록에서 제거할까요?<br />목록에서 다시 열 수 없습니다.</p>
              <div className={s.confirmBtns}>
                <button className="btn" onClick={() => setMenu(null)}>취소</button>
                <button className={`btn ${s.danger}`} onClick={() => void remove(menu.item)} autoFocus>제거</button>
              </div>
            </div>
          ) : (
            <>
              <button role="menuitem" className={s.menuItem} onClick={() => void togglePin(menu.item)}>
                {menu.item.pinned ? "고정 해제" : "고정"}
              </button>
              <button role="menuitem" className={s.menuItem} onClick={() => startRename(menu.item)}>이름 변경</button>
              <button role="menuitem" className={`${s.menuItem} ${s.dangerText}`}
                      onClick={() => setMenu({ ...menu, confirmDelete: true })}>목록에서 제거</button>
            </>
          )}
        </div>
      )}
    </aside>
  );
}

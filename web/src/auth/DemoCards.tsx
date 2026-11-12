// 체험 카드 흐름(2026-11-12, 13번 2-4절) — 런슈즈 로그인의 체험 카드(runshoes src/components/DemoCards.tsx)와 같은 동작.
// 상담원 카드가 2줄로 천천히 한쪽으로 흐른다. 마우스를 올리면 멈추고, 끌면 손을 따라오고, 놓으면 관성으로 미끄러지다 멈춘 뒤 다시 흐른다.
// 끝없이 이어지게 목록을 두 번 이어 붙인다(뒤의 것은 화면 읽기 · 탭 순서에서 뺀다). 움직임 줄이기 설정이면 스스로 흐르지 않는다(끌기는 된다).
// 다른 점: 펫퍼민트 카드는 근속 · 연차와 칩(볼 수 있는 것)을 싣느라 폭이 넓다(CARD — 칩이 한 줄에 둘씩 들어가는 폭). 카드 수가 보이는 칸보다 적으면 흐르지 않고 가운데 선다.

import { useEffect, useRef, useState, type PointerEvent } from "react";
import type { DemoAccount } from "../api/types";
import s from "./Login.module.css";

const CARD = 228;            // 카드 폭 — Login.module.css .demoTrack grid-auto-columns와 같아야 끊김 없이 돈다
const GAP = 8;
const COLUMN = CARD + GAP;
const ROWS = 2;
const MAX_COLUMNS = 4;
const MIN_COLUMNS = 1;       // 휴대폰 — 한 열만 들어가면 보이는 칸을 칸 전체 폭으로 넓혀 다음 카드가 살짝 보이게(옆으로 더 있다는 표시)
const SPEED = 13;            // 스스로 흐르는 속도(초당 px) — 런슈즈와 같다
const FRICTION = 3.2;
const FRICTION_TOUCH = 2.6;
const STILL_MS = 80;
const EASE_BACK = 1.5;

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** 요약에서 이름 · 직급을 뺀 나머지("근속 17년 4개월 · 연차 17.5일 남음") — 이름은 카드 첫 줄에 따로 쓴다 */
export function detailOf(a: DemoAccount): string {
  return a.summary.split(" · ").slice(1).join(" · ");
}

export function DemoCard({ a, busy, onPick, copy = false, admin = false, moved }: {
  a: DemoAccount; busy: boolean; onPick: (a: DemoAccount) => void; copy?: boolean; admin?: boolean; moved?: () => number;
}) {
  return (
    <button type="button" className={`${s.demoCard} ${admin ? s.demoAdmin : ""}`} disabled={busy}
            onClick={() => (moved?.() ?? 0) <= 5 && onPick(a)} tabIndex={copy ? -1 : undefined} aria-hidden={copy || undefined}>
      <strong className={s.demoName}>{a.name} {a.grade}</strong>
      <span className={s.demoDetail}>{detailOf(a)}</span>
      {a.tags.length > 0 && (
        <span className={s.demoTags}>{a.tags.map((t) => <span key={t} className={s.demoTag}>{t}</span>)}</span>
      )}
    </button>
  );
}

export function DemoCards({ cards, busy, onPick }: { cards: DemoAccount[]; busy: boolean; onPick: (a: DemoAccount) => void }) {
  const outerRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const [columns, setColumns] = useState(MAX_COLUMNS);
  const offset = useRef(0);
  const flow = useRef(0);
  const fling = useRef(0);
  const friction = useRef(FRICTION);
  const hover = useRef(false);
  const drag = useRef({ active: false, startX: 0, startOffset: 0, moved: 0, samples: [] as { t: number; x: number }[] });
  const [dragging, setDragging] = useState(false);
  const loop = Math.ceil(cards.length / ROWS) * COLUMN;
  const flows = cards.length > columns * ROWS;

  const paint = () => {
    offset.current = ((offset.current % loop) + loop) % loop;
    if (trackRef.current) trackRef.current.style.transform = `translate3d(${-offset.current}px, 0, 0)`;
  };

  // 보이는 열 수 — 바깥 칸 폭에 들어가는 만큼(MAX_COLUMNS까지)
  useEffect(() => {
    const el = outerRef.current?.parentElement;
    if (!el) return;
    const ro = new ResizeObserver(([e]) =>
      setColumns(Math.max(MIN_COLUMNS, Math.min(MAX_COLUMNS, Math.floor((e.contentRect.width + GAP) / COLUMN)))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 흐르지 않으면 제자리로
  useEffect(() => {
    if (!flows && trackRef.current) {
      offset.current = 0;
      trackRef.current.style.transform = "";
    }
  }, [flows]);

  // 흐름 · 관성 — 화면을 그릴 때마다(transform만 바꾼다, React 다시 그리기 없음)
  useEffect(() => {
    if (!flows) return;
    let raf = 0, last = performance.now();
    const still = reducedMotion();
    const tick = (now: number) => {
      const dt = Math.min(now - last, 64) / 1000;
      last = now;
      if (!drag.current.active) {
        if (fling.current !== 0) {
          offset.current += fling.current * dt;
          fling.current *= Math.exp(-friction.current * dt);
          if (Math.abs(fling.current) < 4) fling.current = 0;
        }
        const target = hover.current || still || fling.current !== 0 ? 0 : SPEED;
        flow.current += (target - flow.current) * (1 - Math.exp(-EASE_BACK * dt));
        offset.current += flow.current * dt;
        paint();
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // paint는 loop만 본다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flows, loop]);

  // 끌기 — 손을 그대로 따라오고, 놓으면 마지막 0.1초의 속도로 미끄러진다. 5px 넘게 끌었으면 그 클릭(로그인)은 먹는다
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (!flows) return;
    drag.current = { active: true, startX: e.clientX, startOffset: offset.current, moved: 0, samples: [{ t: e.timeStamp, x: e.clientX }] };
    fling.current = 0;
    flow.current = 0;
    friction.current = e.pointerType === "touch" ? FRICTION_TOUCH : FRICTION;
    setDragging(true);
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d.active) return;
    const dx = e.clientX - d.startX;
    d.moved = Math.max(d.moved, Math.abs(dx));
    if (d.moved > 5 && !e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.setPointerCapture(e.pointerId);
    const moves = e.nativeEvent.getCoalescedEvents?.() ?? [];
    for (const m of moves.length ? moves : [e.nativeEvent]) d.samples.push({ t: m.timeStamp, x: m.clientX });
    while (d.samples.length > 2 && e.timeStamp - d.samples[0].t > 100) d.samples.shift();
    offset.current = d.startOffset - dx;
    paint();
  };
  // 손가락은 처음 닿은 카드가 저절로 잡고 있다가 칸으로 옮길 때 카드 쪽 lostpointercapture가 올라온다 — 칸 자신의 것만 '놓음'으로 본다
  const onPointerUp = (e?: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d.active) return;
    d.active = false;
    setDragging(false);
    const first = d.samples[0], lastS = d.samples[d.samples.length - 1];
    const ms = lastS.t - first.t;
    const still = (e?.timeStamp ?? lastS.t) - lastS.t;
    if (d.moved > 5 && ms > 0 && ms < 200 && still < STILL_MS) fling.current = Math.max(-3000, Math.min(3000, (-(lastS.x - first.x) / ms) * 1000));
  };

  if (cards.length === 0) return null;
  const moved = () => drag.current.moved;
  const shown = flows ? columns : Math.ceil(cards.length / ROWS);
  return (
    <div className={s.demoCarousel} role="region" aria-roledescription="carousel" aria-label="체험 상담원 계정">
      <div className={`${s.demoViewport} ${dragging ? s.demoDragging : ""} ${flows ? s.demoFlows : ""}`} ref={outerRef}
           style={{ width: flows && columns === 1 ? "100%" : shown * COLUMN - GAP, maxWidth: "100%" }}
           onMouseEnter={() => (hover.current = true)}
           onMouseLeave={() => (hover.current = false)}
           onFocus={() => (hover.current = true)}
           onBlur={(e) => !e.currentTarget.contains(e.relatedTarget as Node) && (hover.current = false)}
           onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
           onLostPointerCapture={(e) => e.target === e.currentTarget && onPointerUp(e)}>
        <div className={s.demoTrack} ref={trackRef}>
          {cards.map((a) => <DemoCard key={`a${a.employee_id}`} a={a} busy={busy} onPick={onPick} moved={moved} />)}
          {flows && cards.map((a) => <DemoCard key={`b${a.employee_id}`} a={a} busy={busy} onPick={onPick} moved={moved} copy />)}
        </div>
      </div>
    </div>
  );
}

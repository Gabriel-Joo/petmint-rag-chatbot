// 흐르는 카드 줄(2026-11-12) — 런슈즈 로그인 체험 카드(runshoes src/components/DemoCards.tsx)와 같은 동작을 공용으로 뺐다.
// 쓰는 곳: 로그인 체험 카드(2줄, auth/DemoCards.tsx) · 홈 모드 카드(1줄, 1023px 이하 — pages/ModeSelect.tsx).
// 카드가 rows줄로 천천히 한쪽으로 흐른다. 마우스를 올리면 멈추고, 끌면 손을 따라오고, 놓으면 관성으로 미끄러지다 멈춘 뒤 다시 흐른다.
// 끝없이 이어지게 목록을 두 번 이어 붙인다(뒤의 것은 화면 읽기 · 탭 순서에서 뺀다). 움직임 줄이기 설정이면 스스로 흐르지 않는다(끌기는 된다).
// 다 보이면(카드 수 ≤ 보이는 칸 × 줄) 흐르지 않고 가운데 선다. 한 열만 들어가면 보이는 칸을 칸 전체 폭으로 넓혀 다음 카드가 살짝 보이게 한다.

import { useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import s from "./FlowCarousel.module.css";

const SPEED = 13;            // 스스로 흐르는 속도(초당 px) — 런슈즈와 같다
const FRICTION = 3.2;        // 관성이 줄어드는 빠르기(1/초)
const FRICTION_TOUCH = 2.6;  // 손가락은 끄는 거리가 짧아 같은 마찰이면 금방 멈춘다
const STILL_MS = 80;         // 놓기 전에 이만큼 멈춰 있었으면 던진 것이 아니다(관성 없음)
const EASE_BACK = 1.5;       // 멈췄다 다시 흐를 때 속도가 붙는 빠르기(1/초)

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export interface FlowItemProps {
  /** 뒤에 이어 붙인 복제 카드 — 탭 순서 · 화면 읽기에서 뺀다(tabIndex -1, aria-hidden) */
  copy: boolean;
  /** 클릭이 끌기 끝이 아닌가 — 5px 넘게 끌었으면 false(그 클릭은 먹는다) */
  clickable: () => boolean;
}

interface Props<T> {
  items: T[];
  keyOf: (item: T) => string;
  render: (item: T, p: FlowItemProps) => ReactNode;
  card: number;              // 카드 폭(px)
  gap?: number;
  rows?: number;
  maxColumns?: number;
  label: string;             // 화면 읽기 이름
}

export function FlowCarousel<T>({ items, keyOf, render, card, gap = 8, rows = 1, maxColumns = 6, label }: Props<T>) {
  const column = card + gap;
  const outerRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const [columns, setColumns] = useState(maxColumns);
  const offset = useRef(0);              // 흐른 거리(px) — 한 바퀴(loop)로 감싼다
  const flow = useRef(0);                // 지금 스스로 흐르는 속도 — 멈췄다 다시 흐를 때 0 → SPEED로 붙는다
  const fling = useRef(0);               // 놓은 뒤 남은 관성(초당 px)
  const friction = useRef(FRICTION);
  const hover = useRef(false);
  const drag = useRef({ active: false, startX: 0, startOffset: 0, moved: 0, samples: [] as { t: number; x: number }[] });
  const [dragging, setDragging] = useState(false);
  const loop = Math.ceil(items.length / rows) * column;
  const flows = items.length > columns * rows;

  const paint = () => {
    offset.current = ((offset.current % loop) + loop) % loop;
    if (trackRef.current) trackRef.current.style.transform = `translate3d(${-offset.current}px, 0, 0)`;
  };

  // 보이는 열 수 — 바깥 칸 폭에 들어가는 만큼(maxColumns까지, 적어도 1)
  useEffect(() => {
    const el = outerRef.current?.parentElement;
    if (!el) return;
    const ro = new ResizeObserver(([e]) =>
      setColumns(Math.max(1, Math.min(maxColumns, Math.floor((e.contentRect.width + gap) / column)))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [column, gap, maxColumns]);

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

  // 끌기 — 손을 그대로 따라오고, 놓으면 마지막 0.1초의 속도로 미끄러진다. 5px 넘게 끌었으면 그 클릭은 먹는다.
  // 속도는 마지막 움직임까지로 잰다. 브라우저가 묶은 움직임(coalesced)도 표본에 넣는다
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

  if (items.length === 0) return null;
  const clickable = () => drag.current.moved <= 5;
  const shown = flows ? columns : Math.ceil(items.length / rows);
  return (
    <div className={s.carousel} role="region" aria-roledescription="carousel" aria-label={label}>
      <div className={`${s.viewport} ${dragging ? s.dragging : ""} ${flows ? s.flows : ""}`} ref={outerRef}
           style={{ width: flows && columns === 1 ? "100%" : shown * column - gap, maxWidth: "100%" }}
           onMouseEnter={() => (hover.current = true)}
           onMouseLeave={() => (hover.current = false)}
           onFocus={() => (hover.current = true)}
           onBlur={(e) => !e.currentTarget.contains(e.relatedTarget as Node) && (hover.current = false)}
           onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
           onLostPointerCapture={(e) => e.target === e.currentTarget && onPointerUp(e)}>
        <div className={s.track} ref={trackRef}
             style={{ gridTemplateRows: `repeat(${rows}, auto)`, gridAutoColumns: `${card}px`, gap }}>
          {items.map((it) => <div key={`a${keyOf(it)}`} className={s.cell}>{render(it, { copy: false, clickable })}</div>)}
          {flows && items.map((it) => (
            <div key={`b${keyOf(it)}`} className={s.cell} aria-hidden>{render(it, { copy: true, clickable })}</div>
          ))}
        </div>
      </div>
    </div>
  );
}

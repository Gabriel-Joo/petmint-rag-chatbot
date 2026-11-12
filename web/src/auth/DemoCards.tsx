// 체험 카드(2026-11-12, 13번 2-4절) — 상담원 카드가 2줄로 천천히 가로로 흐른다. 흐름 · 끌기 · 관성은 공용 FlowCarousel
// (런슈즈 로그인 체험 카드와 같은 동작). 펫퍼민트 카드는 근속 · 연차와 칩(볼 수 있는 것)을 싣느라 폭이 넓다(CARD — 칩이 한 줄에 둘).

import type { DemoAccount } from "../api/types";
import { FlowCarousel } from "../components/FlowCarousel";
import s from "./Login.module.css";

const CARD = 300;            // 카드 폭 — 대화 화면 칩 크기에서 칩이 한 줄에 둘

/** 요약에서 이름 · 직급을 뺀 나머지("근속 17년 4개월 · 연차 17.5일 남음") — 이름은 카드 첫 줄에 따로 쓴다 */
export function detailOf(a: DemoAccount): string {
  return a.summary.split(" · ").slice(1).join(" · ");
}

export function DemoCard({ a, busy, onPick, copy = false, admin = false, moved }: {
  a: DemoAccount; busy: boolean; onPick: (a: DemoAccount) => void; copy?: boolean; admin?: boolean; moved?: () => number;
}) {
  return (
    <button type="button" className={`raised lift chat-text ${s.demoCard} ${admin ? s.demoAdmin : ""}`} disabled={busy}
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
  return (
    <FlowCarousel items={cards} keyOf={(a) => a.employee_id} card={CARD} gap={12} rows={2} maxColumns={6} label="체험 상담원 계정"
                  render={(a, { copy, clickable }) => (
                    <DemoCard a={a} busy={busy} onPick={onPick} copy={copy} moved={() => (clickable() ? 0 : 6)} />
                  )} />
  );
}

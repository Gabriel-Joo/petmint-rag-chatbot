import { useEffect, useMemo, useState } from "react";
import { ApiError, listCustomers, listRecentConsultations } from "../api/client";
import { PastConsultations } from "../components/PastConsultations";
import type { Customer } from "../api/types";
import { relativeTime, SPECIES_ICON } from "../format";
import { useNow } from "../hooks/useNow";
import { summarizePet } from "../policySummary";
import s from "./CustomerSelect.module.css";

type Tab = "전체" | "최근 상담";
const TABS: Tab[] = ["전체", "최근 상담"];
let lastTab: Tab = "전체"; // 상담을 마치고 돌아왔을 때 보던 탭을 유지한다

interface Props {
  onStart: (c: Customer) => void;
  starting: boolean;
}

/** 고객 조회 — 전화 없이 상담을 시작하는 두 번째 입구(10번 3절). 종은 상담 화면에서 반려동물을 고르면 따라온다 */
export function CustomerSelect({ onStart, starting }: Props) {
  const [customers, setCustomers] = useState<Customer[] | null>(null);
  const [recent, setRecent] = useState<Map<string, string>>(new Map()); // customer_id → 마지막 상담 시각(내림차순)
  const [error, setError] = useState<string | null>(null);
  const [tab, setTabState] = useState<Tab>(lastTab);
  const now = useNow(60_000);

  const setTab = (t: Tab) => { lastTab = t; setTabState(t); };

  useEffect(() => {
    Promise.all([listCustomers(), listRecentConsultations()]).then(([cs, rs]) => {
      setCustomers(cs);
      setRecent(new Map(rs.map((r) => [r.customer_id, r.last_consulted_at])));
    }, (e) => setError(e instanceof ApiError ? e.detail : String(e))); // 500(원장 오류)이면 서버가 준 안내 문구 그대로
  }, []);

  const shown = useMemo(() => {
    if (!customers) return [];
    if (tab === "전체") return customers;
    const byId = new Map(customers.map((c) => [c.customer_id, c]));
    return [...recent.keys()].map((id) => byId.get(id)).filter((c): c is Customer => c !== undefined);
  }, [customers, recent, tab]);

  return (
    <main className={s.page}>
      <h1 className={s.title}>고객 조회</h1>
      <p className={s.sub}>상담할 고객을 고르세요. 반려동물별 가입 특약과 등급·자기부담금은 상담 화면에서 확인할 수 있습니다.</p>

      <div className={`chat-text ${s.filters}`} role="tablist" aria-label="고객 목록">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={`btn ${tab === t ? "selected" : ""}`} onClick={() => setTab(t)}>
            {t}{t === "최근 상담" && recent.size > 0 && <span className={s.count}>{recent.size}</span>}
          </button>
        ))}
      </div>

      {error && <p className={s.err}>{error}</p>}
      {!customers && !error && <p className="dim">불러오는 중…</p>}

      {customers && tab === "최근 상담" && shown.length === 0 && (
        <div className={`raised ${s.empty}`}>
          <span className={s.emptyIcon} aria-hidden>🕘</span>
          <span className={s.emptyTitle}>아직 상담한 고객이 없어요</span>
          <span className="dim">전화를 받거나 전체 탭에서 고객을 골라 상담하면, 여기에 최근 순서로 쌓입니다.</span>
          <button className="btn" onClick={() => setTab("전체")}>전체 고객 보기</button>
        </div>
      )}

      <div className={`chat-text ${s.grid}`}>
        {shown.map((c) => {
          const last = recent.get(c.customer_id);
          const pets = c.pets.map((p) => ({ p, sum: summarizePet(p) }));
          return (
            // 카드 = 상담 시작 버튼 + 과거 상담. 버튼 안에 버튼을 둘 수 없어 카드는 div로 두고 본문을 시작 버튼으로 덮는다
            <div key={c.customer_id} className={`raised lift ${s.card}`}>
              {/* 위쪽 띠 — 반려동물마다 한 칸, 그 반려동물의 가장 높은 등급 색(띠만 봐도 몇 마리·어떤 등급인지) */}
              <div className={s.band} aria-hidden>
                {pets.map(({ p, sum }) => <span key={p.pet_id} className={sum.top ? s[sum.top] : s.none} />)}
              </div>
              <button className={s.start} disabled={starting} onClick={() => onStart(c)}>
                <div className={s.row}>
                  <span className={s.name}>{c.name}</span>
                  {/* 상담 기록이 없으면 비워 둔다 — 빈 자리가 "아직 상담한 적 없음"이다 */}
                  {last && (
                    <time className={s.when} dateTime={last} title={new Date(last).toLocaleString("ko-KR")}>
                      {relativeTime(last, now)}
                    </time>
                  )}
                </div>
                <span className={s.phone}>{c.phone}</span>
                <span className={s.sep} role="presentation" />
                <div className={s.pets}>
                  {/* 부담보는 반려동물마다(특약 '반려동물 특정 질병 보장제한부 인수'는 그 반려동물의 것) — 고객 전체에 모으면
                      여러 마리 고객에서 다른 반려동물 것처럼 보였다(2026-10-23 김서연: 초코의 슬개골 탈구가 맨 아래에) */}
                  {pets.map(({ p, sum }) => (
                    // 이름과 "품종 · 나이"를 각각 끊기지 않는 덩어리로 — 자리가 없으면 "품종 · 나이"가 통째로 다음 줄로
                    <span key={p.pet_id} className={s.pet}>
                      <span className={s.petName}>{SPECIES_ICON[p.species]} {p.name}</span>
                      <span className={s.petMeta}>{p.breed} · {p.age}세</span>
                      <span className={s.chips}>
                        {sum.grades.map((g) => (
                          <span key={g.text + (g.key ?? "")} className={`${s.chip} ${s[g.tone]}`}>
                            {g.key && <span className={s.chipKey}>{g.key}</span>}{g.text}{g.tail && <span className={s.chipKey}> · {g.tail}</span>}
                          </span>
                        ))}
                        {sum.extras.map((e) => <span key={e} className={`${s.chip} ${s.extra}`}>{e}</span>)}
                        {sum.exclusions.length > 0 && <span className={`${s.chip} ${s.excl}`}>부담보 {sum.exclusions.join(", ")}</span>}
                      </span>
                    </span>
                  ))}
                </div>
              </button>
              <div className={s.cardFoot}><PastConsultations customer={c} /></div>
            </div>
          );
        })}
      </div>
    </main>
  );
}

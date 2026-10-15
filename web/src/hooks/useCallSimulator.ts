// 가상 전화(10번 1절). 실제 CTI가 없으므로 앱 안에서 울린다.
// 자동 2~3분 주기(토글) + 수동 "전화 울리기". 10초 지속, 무응답은 자동 거절. 상담 진행 중이면 자동·수동 모두 울리지 않는다.

import { useCallback, useEffect, useRef, useState } from "react";
import { listCustomers } from "../api/client";
import type { Customer } from "../api/types";

export const RING_SECONDS = 10;
const AUTO_MIN_MS = 120_000;
const AUTO_MAX_MS = 180_000;
const NOTICE_MS = 3_000;

export interface Ringing {
  customer: Customer;
  secondsLeft: number;
}

export function useCallSimulator({ blocked, onAccept }: { blocked: boolean; onAccept: (c: Customer) => void }) {
  const [autoRing, setAutoRing] = useState(false);
  const [ringing, setRinging] = useState<Ringing | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const blockedRef = useRef(blocked);
  blockedRef.current = blocked;

  const ring = useCallback(async () => {
    if (blockedRef.current) return;
    const customers = await listCustomers();
    if (blockedRef.current) return;
    const customer = customers[Math.floor(Math.random() * customers.length)];
    setRinging((r) => r ?? { customer, secondsLeft: RING_SECONDS });
  }, []);

  const showNotice = useCallback((text: string) => {
    setNotice(text);
    window.setTimeout(() => setNotice((n) => (n === text ? null : n)), NOTICE_MS);
  }, []);

  // 10초 카운트다운 — 0이 되면 자동 거절
  useEffect(() => {
    if (!ringing) return;
    if (ringing.secondsLeft <= 0) {
      setRinging(null);
      showNotice("다른 상담원에게 연결됨");
      return;
    }
    const id = window.setTimeout(() => setRinging((r) => r && { ...r, secondsLeft: r.secondsLeft - 1 }), 1000);
    return () => clearTimeout(id);
  }, [ringing, showNotice]);

  // 상담이 시작되면 울리던 전화도 끊는다(고객 조회로 먼저 상담을 연 경우)
  useEffect(() => {
    if (blocked) setRinging(null);
  }, [blocked]);

  // 자동 주기
  useEffect(() => {
    if (!autoRing || blocked || ringing) return;
    const delay = AUTO_MIN_MS + Math.random() * (AUTO_MAX_MS - AUTO_MIN_MS);
    const id = window.setTimeout(() => void ring(), delay);
    return () => clearTimeout(id);
  }, [autoRing, blocked, ringing, ring]);

  const accept = useCallback(() => {
    if (!ringing) return;
    setRinging(null);
    onAccept(ringing.customer);
  }, [ringing, onAccept]);

  const reject = useCallback(() => {
    setRinging(null);
    showNotice("다른 상담원에게 연결됨");
  }, [showNotice]);

  return { autoRing, setAutoRing, ringing, notice, ring, accept, reject };
}

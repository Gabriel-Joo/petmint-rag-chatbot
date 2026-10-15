import { useEffect, useState } from "react";

/** 주기마다 바뀌는 현재 시각. 상대 시간 표기를 화면 하나에서 타이머 하나로 갱신한다 */
export function useNow(intervalMs = 60_000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

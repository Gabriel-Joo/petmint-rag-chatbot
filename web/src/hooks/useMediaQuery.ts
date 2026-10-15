import { useCallback, useSyncExternalStore } from "react";

/** 화면 폭 같은 미디어 쿼리 결과. 창 크기를 바꾸면 바로 따라간다 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback((onChange: () => void) => {
    const mq = window.matchMedia(query);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches);
}

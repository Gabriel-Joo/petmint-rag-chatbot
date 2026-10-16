import { useLayoutEffect, type RefObject } from "react";

/** 스크롤 상자의 세로 스크롤바 폭(px)을 그 상자의 CSS 변수 --scrollbar-w 에 적어 둔다.
 *  폭은 브라우저가 실제로 그린 값(offsetWidth − clientWidth)이라 브라우저·OS·배율과 상관없이 맞다.
 *  겹쳐 뜨는 스크롤바(macOS 등)나 스크롤이 없을 때는 0. 내용이 늘거나 줄어 스크롤바가 생기고 없어질 때도 따라간다 */
export function useScrollbarWidth(ref: RefObject<HTMLElement | null>, enabled: boolean) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !enabled) return;
    const measure = () => {
      const b = getComputedStyle(el);
      const w = el.offsetWidth - el.clientWidth - parseFloat(b.borderLeftWidth) - parseFloat(b.borderRightWidth);
      el.style.setProperty("--scrollbar-w", `${Math.max(0, w)}px`);
    };
    measure();
    // 내용 상자 크기를 본다 — 스크롤바가 생기거나 없어지면 내용 폭이 바뀌어 다시 잰다. 내용(자식) 높이 변화도 함께 본다
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    for (const c of Array.from(el.children)) ro.observe(c);
    return () => { ro.disconnect(); el.style.removeProperty("--scrollbar-w"); };
  }, [ref, enabled]);
}

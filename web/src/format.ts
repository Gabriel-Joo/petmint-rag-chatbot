import type { Species } from "./api/types";

/** 300000 → "30만원", 1234567 → "1,234,567원" */
export function won(n: number): string {
  if (n >= 10000 && n % 10000 === 0) return `${(n / 10000).toLocaleString("ko-KR")}만원`;
  return `${n.toLocaleString("ko-KR")}원`;
}

export const SPECIES_ICON: Record<Species, string> = { 강아지: "🐶", 고양이: "🐱" };

/** 특약명을 카드에 맞게 줄인다: "펫퍼민트 반려견 통원의료비Ⅱ보장 특별약관" → "통원의료비Ⅱ" */
export function shortSection(name: string): string {
  const m = name.match(/(통원|입원)의료비(Ⅱ|Ⅲ)?/);
  if (m) return m[0];
  return name.replace(/ ?특별약관$/, "");
}

/** 상대 시간: 방금 / N분 전 / N시간 전 / 어제 / N일 전, 그보다 오래되면 날짜 */
export function relativeTime(iso: string, now: Date): string {
  const t = new Date(iso);
  const min = Math.floor((now.getTime() - t.getTime()) / 60_000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  if (min < 24 * 60) return `${Math.floor(min / 60)}시간 전`;
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day(now) - day(t)) / 86_400_000);
  if (days <= 1) return "어제";
  if (days < 7) return `${days}일 전`;
  return t.getFullYear() === now.getFullYear()
    ? `${t.getMonth() + 1}월 ${t.getDate()}일`
    : `${t.getFullYear()}. ${t.getMonth() + 1}. ${t.getDate()}.`;
}

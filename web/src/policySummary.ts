// 반려동물 특약을 고객 조회 카드용 칩으로 줄인다(2026-10-23 B안).
// 의료비: 통원·입원 등급이 같으면 칩 하나("Ⅱ 고급형"), 다르면 둘("통원 고급형", "입원 기본형"), 한쪽만이면 "통원만"·"입원만"을 붙인다.
// 유형 Ⅰ(번호 없는 기본 특약)은 번호를 쓰지 않는다. 배상책임·법률비용은 회색 칩, 부담보는 그 반려동물의 것만 모은다.
import type { Grade, Pet } from "./api/types";

export type GradeTone = "high" | "mid" | "low";
export const GRADE_TONE: Record<Grade, GradeTone> = { 고급형: "high", 기본형: "mid", 실속형: "low" };
const RANK: Record<GradeTone, number> = { high: 3, mid: 2, low: 1 };

export interface GradeChip { tone: GradeTone; text: string; key?: "통원" | "입원"; tail?: "통원만" | "입원만" }
export interface PetSummary {
  grades: GradeChip[];
  extras: string[];             // 배상책임 · 법률비용
  exclusions: string[];         // 부담보(이 반려동물의 것)
  top: GradeTone | null;        // 가장 높은 등급 — 카드 위 띠의 이 반려동물 칸 색
}

export function summarizePet(pet: Pet): PetSummary {
  const med: Partial<Record<"통원" | "입원", { series: string; grade: Grade }>> = {};
  const extras: string[] = [];
  const exclusions: string[] = [];
  for (const p of pet.policies) {
    exclusions.push(...p.excluded_conditions);
    if (p.section_name.includes("의료비") && p.coverage_type) {
      const kind = p.section_name.includes("통원") ? "통원" : "입원";
      med[kind] = { series: p.type && p.type !== "Ⅰ" ? p.type : "", grade: p.coverage_type };
    } else if (p.section_name.includes("배상책임")) extras.push("배상책임");
    else if (p.section_name.includes("법률비용")) extras.push("법률비용");
  }
  const label = (x: { series: string; grade: Grade }) => (x.series ? `${x.series} ${x.grade}` : x.grade);
  const t = med.통원, h = med.입원;
  const grades: GradeChip[] = [];
  if (t && h && t.series === h.series && t.grade === h.grade) grades.push({ tone: GRADE_TONE[t.grade], text: label(t) });
  else if (t && h) {
    grades.push({ tone: GRADE_TONE[t.grade], key: "통원", text: label(t) });
    grades.push({ tone: GRADE_TONE[h.grade], key: "입원", text: t.series === h.series ? h.grade : label(h) });
  } else if (t || h) {
    const x = (t ?? h)!;
    grades.push({ tone: GRADE_TONE[x.grade], text: label(x), tail: t ? "통원만" : "입원만" });
  }
  const top = grades.reduce<GradeTone | null>((a, g) => (!a || RANK[g.tone] > RANK[a] ? g.tone : a), null);
  return { grades, extras, exclusions, top };
}

import s from "./ExclusionBanner.module.css";

/** 질문이 부담보 조건에 걸리는가 — 모델이 아니라 코드가 대조한다(09 2-3).
 *  지금은 글자 대조(공백 무시 전체 일치, 또는 3글자 이상 낱말 일치)뿐이다. "무릎" ↔ "슬개골" 같은 동의어는 못 잡는다 */
export function matchExclusions(question: string, conditions: string[]): string[] {
  const q = question.replace(/\s+/g, "");
  return conditions.filter((c) =>
    q.includes(c.replace(/\s+/g, "")) || c.split(/\s+/).some((w) => w.length >= 3 && q.includes(w)));
}

export function ExclusionBanner({ matched }: { matched: string[] }) {
  if (!matched.length) return null;
  return (
    <div className={s.banner} role="note">
      <span className={s.icon} aria-hidden>!</span>
      <span>부담보 해당 가능: <b>{matched.join(", ")}</b> — 이 조건은 보장 제외로 가입되어 있습니다. 답변과 함께 부담보 특약을 확인하세요.</span>
    </div>
  );
}

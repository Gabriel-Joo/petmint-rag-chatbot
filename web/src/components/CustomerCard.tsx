import type { ReactNode } from "react";
import type { Customer, Pet } from "../api/types";
import { SPECIES_ICON, shortSection, won } from "../format";
import s from "./CustomerCard.module.css";

interface Props {
  customer: Customer;
  pet: Pet;
  /** 종 토글 — 반려동물이 둘 이상이면 하나씩 본다(10번 6절) */
  toggle?: ReactNode;
}

/** 전화를 받자마자 훑는 카드(10번 6절). 약관 시행일·종료일은 고객 레코드에 없고 조회 API도 아직 없어 띄우지 않는다 */
export function CustomerCard({ customer, pet, toggle }: Props) {
  const exclusions = pet.policies.flatMap((p) => p.excluded_conditions);
  const docs = [...new Map(pet.policies.map((p) => [p.doc_id, p])).values()];
  const dates = [...new Set(pet.policies.map((p) => p.contract_date))];
  return (
    <section className={`raised ${s.card}`} aria-label="고객 정보">
      <div className={s.top}>
        <div className={s.big}>
          <span className={s.customer}>{customer.name}</span>
          <span className={s.pet}>{SPECIES_ICON[pet.species]} {pet.name}</span>
          <span className={s.petMeta}>{pet.species} · {pet.breed ?? "품종 미상"} · {pet.age ?? "?"}세</span>
        </div>
        {toggle}
      </div>

      <div className={s.mid}>
        {pet.policies.filter((p) => p.excluded_conditions.length === 0).map((p) => (
          <span key={p.section_name} className={s.chip}>
            {shortSection(p.section_name)}
            {p.coverage_type && <> <b>{p.coverage_type}</b></>}
            {p.copay !== null && <> · 자기부담 {won(p.copay)}</>}
          </span>
        ))}
      </div>

      {exclusions.length > 0 && (
        <div className={s.excl}><b>부담보</b> {exclusions.join(", ")}</div>
      )}

      <div className={s.small}>
        {docs.map((d) => <span key={d.doc_id}>{d.product_name} · 약관 {d.policy_version}</span>)}
        <span>가입일 {dates.join(", ")}</span>
      </div>
    </section>
  );
}

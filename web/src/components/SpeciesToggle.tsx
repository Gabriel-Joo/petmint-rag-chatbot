import type { Pet } from "../api/types";
import { SPECIES_ICON } from "../format";
import s from "./SpeciesToggle.module.css";

interface Props {
  pets: Pet[];
  value: string;
  onChange: (petId: string) => void;
  disabled?: boolean;
}

/** 반려동물이 둘 이상일 때 하나씩 고른다(09 2-3, 10번 6절). 고른 pet_id가 질문 메시지에 실린다 — 세션에는 두지 않는다 */
export function SpeciesToggle({ pets, value, onChange, disabled }: Props) {
  if (pets.length < 2) return null;
  return (
    <div className={s.toggle} role="radiogroup" aria-label="상담 대상 반려동물">
      {pets.map((p) => (
        <button key={p.pet_id} role="radio" aria-checked={p.pet_id === value} disabled={disabled}
                className={`${s.opt} ${p.pet_id === value ? s.on : ""}`} onClick={() => onChange(p.pet_id)}>
          {SPECIES_ICON[p.species]} {p.name}
        </button>
      ))}
    </div>
  );
}

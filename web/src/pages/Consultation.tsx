import { useEffect, useMemo, useRef, useState } from "react";
import type { Customer, SessionOut } from "../api/types";
import { WS_CLOSE_SESSION_NOT_FOUND } from "../api/types";
import { Composer } from "../components/Composer";
import { CustomerCard } from "../components/CustomerCard";
import { matchExclusions } from "../components/ExclusionBanner";
import { SourcePanel } from "../components/SourcePanel";
import { SpeciesToggle } from "../components/SpeciesToggle";
import { ModeIcon } from "../components/ModeIcon";
import { PastConsultations } from "../components/PastConsultations";
import { TurnView } from "../components/TurnView";
import { SPECIES_ICON } from "../format";
import { useChatSocket } from "../hooks/useChatSocket";
import s from "./Consultation.module.css";

export interface ConsultState {
  session: SessionOut;
  customer: Customer;
  /** 상담 종료 후에도 화면에 머문다 — 세션만 닫히고 대화는 읽기 전용(10번 5절) */
  ended: boolean;
}

interface Props {
  consult: ConsultState;
  onEnd: () => void;
  ending: boolean;
  /** 4404 — 업무특화는 고객 조회로 돌아간다(09 6-2) */
  onSessionLost: () => void;
}

export function Consultation({ consult, onEnd, ending, onSessionLost }: Props) {
  const { customer, session, ended } = consult;
  const [petId, setPetId] = useState(customer.pets[0].pet_id);
  const pet = customer.pets.find((p) => p.pet_id === petId) ?? customer.pets[0];
  const chat = useChatSocket(session.session_id);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (chat.closedCode === WS_CLOSE_SESSION_NOT_FOUND && !ended) onSessionLost();
  }, [chat.closedCode, ended, onSessionLost]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [chat.turns.length]);

  // PC 근거 패널은 고른 턴(기본: 마지막 턴)의 검색 결과를 보여준다
  const panelTurn = chat.turns.find((t) => t.key === selectedKey) ?? chat.turns[chat.turns.length - 1];
  const petsById = useMemo(() => new Map(customer.pets.map((p) => [p.pet_id, p])), [customer]);

  return (
    <main className={s.page}>
      <div className={s.status}>
        <span className={s.mode}><ModeIcon mode="업무특화" />업무특화</span>
        {ended ? <span className={s.ended}>상담 종료됨 · 읽기 전용</span> : <span className="dim">상담 중</span>}
        {!ended && <button className={`btn ${s.end}`} onClick={onEnd} disabled={ending}>상담 종료</button>}
      </div>

      <div className={s.customer}>
        <CustomerCard customer={customer} pet={pet}
                      toggle={<SpeciesToggle pets={customer.pets} value={pet.pet_id} onChange={setPetId} />}
                      actions={<PastConsultations customer={customer} excludeSessionId={session.session_id} />} />
      </div>

      <div ref={logRef} className={`raised chat-text ${s.log}`}>
        {chat.turns.length === 0 && (
          <div className={s.empty}>
            {ended ? "대화 없이 종료된 상담입니다." : `${customer.name} 고객 상담을 시작합니다. ${pet.name}에 대해 물어보세요.`}
          </div>
        )}
        {chat.turns.map((t) => {
          const turnPet = t.pet_id ? petsById.get(t.pet_id) : undefined;
          const excl = turnPet ? matchExclusions(t.question, turnPet.policies.flatMap((p) => p.excluded_conditions)) : [];
          return (
            <TurnView key={t.key} turn={t} inlineSources="mobile" exclusions={excl}
                      petLabel={turnPet && customer.pets.length > 1 ? `${SPECIES_ICON[turnPet.species]} ${turnPet.name}` : undefined}
                      onClarify={ended ? undefined : chat.answerClarify}
                      selected={panelTurn?.key === t.key && chat.turns.length > 1}
                      onSelect={() => setSelectedKey(t.key)} />
          );
        })}
      </div>

      <div className={`raised ${s.composer}`}>
        <Composer busy={chat.busy} disabled={ended} disabledText="상담이 종료되어 입력할 수 없습니다. 대화는 그대로 볼 수 있습니다."
                  onCancel={chat.cancel} onSend={(text) => chat.ask(text, pet.pet_id)}
                  placeholder={`${pet.name}(${pet.species}) 관련 질문 — 예: 해지하면 환급금 있나요? / 수술 한도는? / 치료비 40만원이면?`} />
      </div>

      <aside className={`raised ${s.panel}`}>
        <SourcePanel items={panelTurn?.sources ?? []} references={panelTurn?.references ?? []} variant="side" />
      </aside>
    </main>
  );
}

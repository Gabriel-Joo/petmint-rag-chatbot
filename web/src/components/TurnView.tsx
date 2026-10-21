import { useState } from "react";
import { postFeedback } from "../api/client";
import type { TurnContextInfo } from "../api/types";
import type { Turn } from "../hooks/useChatSocket";
import { AnswerMarkdown } from "./AnswerMarkdown";
import { AnswerTable } from "./AnswerTable";
import { CalcCard } from "./CalcCard";
import { ExclusionBanner } from "./ExclusionBanner";
import { SourcePanel } from "./SourcePanel";
import s from "./TurnView.module.css";

interface Props {
  turn: Turn;
  onClarify?: (turnId: string, choice: string) => void;
  /** 답변 아래 접힌 근거: always(대화창) / mobile(상담 화면 — PC는 오른쪽 패널) / never */
  inlineSources: "always" | "mobile" | "never";
  exclusions?: string[];
  petLabel?: string;
  selected?: boolean;
  onSelect?: () => void;
  /** 과거 상담 — 평가 버튼을 두지 않는다(남의 상담일 수 있고, 읽기만 하는 화면이다) */
  readOnly?: boolean;
  /** 날짜별 치료비 입력 카드를 채워 다음 질문으로 보낸다 — 진행 중 상담의 마지막 턴에만. 없으면 입력칸은 읽기 전용 */
  onAnswer?: (text: string) => void;
}

const STATUS_TEXT: Partial<Record<Turn["status"], string>> = { searching: "검색 중…", clarify: "어느 쪽을 물으시나요?" };

export function TurnView({ turn, onClarify, inlineSources, exclusions = [], petLabel, selected, onSelect, readOnly, onAnswer }: Props) {
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const streaming = turn.status === "streaming";

  const rate = (r: "up" | "down") => {
    if (!turn.turn_id) return;
    setRating(r);
    void postFeedback(turn.turn_id, { rating: r });
  };

  return (
    <article className={`${s.turn} ${onSelect ? s.selectable : ""} ${selected ? s.selected : ""}`}
             onClick={onSelect} aria-current={selected || undefined}>
      <div className={s.q}>{turn.question}</div>
      {turn.context && <ContextLine ctx={turn.context} />}

      <ExclusionBanner matched={exclusions} />

      {turn.clarify && onClarify && turn.turn_id && (
        <div className={s.clarify} onClick={(e) => e.stopPropagation()}>
          <span className="dim">{STATUS_TEXT.clarify}</span>
          {turn.clarify.map((o) => (
            <button key={o} className="btn" onClick={() => onClarify(turn.turn_id!, o)}>{o}</button>
          ))}
        </div>
      )}
      {turn.clarifyChoice && <div className={s.status}>↳ {turn.clarifyChoice} 기준</div>}

      {turn.answer ? (
        <div className={s.a}><AnswerMarkdown text={turn.answer} streaming={streaming} />{streaming && <span className={s.caret} aria-hidden />}</div>
      ) : (
        turn.status === "searching" && <div className={s.status}>{STATUS_TEXT.searching}</div>
      )}
      {turn.error && <div className={s.err}>{turn.error}</div>}

      {turn.tables?.map((t, i) => <AnswerTable key={i} item={t} />)}

      {turn.calc && (
        <div onClick={(e) => e.stopPropagation()}>
          <CalcCard calc={turn.calc} onAnswer={turn.status === "done" ? onAnswer : undefined} />
        </div>
      )}

      {inlineSources !== "never" && (
        <div className={inlineSources === "mobile" ? s.mobileOnly : undefined} onClick={(e) => e.stopPropagation()}>
          <SourcePanel items={turn.sources} references={turn.references} variant="inline" />
        </div>
      )}

      {turn.status === "done" && (
        <div className={s.foot} onClick={(e) => e.stopPropagation()}>
          {petLabel && <span>{petLabel}</span>}
          {turn.first_token_ms !== null && <span>첫 글자 {turn.first_token_ms}ms</span>}
          {turn.latency_ms !== null && <span>전체 {turn.latency_ms}ms</span>}
          {!readOnly && <>
            <button className={`${s.fb} ${rating === "up" ? s.fbOn : ""}`} onClick={() => rate("up")} aria-label="좋아요"
                    disabled={!turn.turn_id}>👍</button>
            <button className={`${s.fb} ${rating === "down" ? s.fbOn : ""}`} onClick={() => rate("down")} aria-label="별로예요"
                    disabled={!turn.turn_id}>👎</button>
          </>}
        </div>
      )}
    </article>
  );
}

/** 후속 질문을 어떻게 풀었는지(09 5절) — 상담원이 해석을 확인하고 틀렸으면 고쳐 물을 수 있게. 질문 말풍선 바로 아래 오른쪽 */
function ContextLine({ ctx }: { ctx: TurnContextInfo }) {
  const text =
    ctx.kind === "rewrite" ? ctx.text
    : ctx.kind === "concat" ? `앞 질문 '${ctx.text}'과 이어서 검색`
    : `앞 대화 ${ctx.turns ?? 0}턴 참고`;
  return <div className={s.context} title={ctx.reason ? `후속 질문으로 봄 — ${ctx.reason}` : undefined}>↳ {text}</div>;
}

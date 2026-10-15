import { useState, type ReactNode } from "react";
import s from "./Composer.module.css";

interface Props {
  onSend: (text: string) => void;
  onCancel: () => void;
  busy: boolean;
  disabled?: boolean;
  disabledText?: string;
  placeholder?: string;
  /** 입력창 옆(종 토글 자리) */
  side?: ReactNode;
}

export function Composer({ onSend, onCancel, busy, disabled, disabledText, placeholder, side }: Props) {
  const [text, setText] = useState("");
  const send = () => {
    const t = text.trim();
    if (!t || disabled) return;
    onSend(t);
    setText("");
  };
  return (
    <div>
      {disabled && disabledText && <div className={s.closed}>{disabledText}</div>}
      <div className={s.bar}>
        {side}
        <textarea className={s.input} rows={1} value={text} disabled={disabled} placeholder={placeholder}
                  aria-label="질문 입력"
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); }
                  }} />
        {busy && !disabled && <button className="btn" onClick={onCancel}>중지</button>}
        <button className="btn-primary" onClick={send} disabled={disabled || !text.trim()}>보내기</button>
      </div>
    </div>
  );
}

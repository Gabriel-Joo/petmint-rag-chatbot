// 로그인 · 첫 로그인 비밀번호 변경 화면(13번 2-1절). 한 화면 두 쓰임 — changeFor가 있으면 변경.
// 실패 문구는 서버 것을 그대로 쓴다(사번이 없는지 비밀번호가 틀렸는지 구분하지 않는다).

import { useState, type FormEvent } from "react";
import { ApiError, changePassword, getMe, login } from "../api/client";
import type { MeOut } from "../api/types";
import s from "./Login.module.css";

const MIN_PASSWORD = 10; // app/services/auth.py MIN_PASSWORD

interface Props {
  notice?: string | null;
  /** 임시 비밀번호로 들어온 직원 — 비밀번호를 바꿔야 앱으로 간다 */
  changeFor?: MeOut;
  onDone: (me: MeOut) => void;
}

export function Login({ notice = null, changeFor, onDone }: Props) {
  const [employeeId, setEmployeeId] = useState("");
  const [password, setPassword] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (changeFor) {
      if (next.length < MIN_PASSWORD) return setError(`새 비밀번호는 ${MIN_PASSWORD}자 이상이어야 합니다.`);
      if (next !== confirm) return setError("새 비밀번호 두 칸이 다릅니다.");
    }
    setBusy(true);
    try {
      if (changeFor) {
        await changePassword({ current: password, new: next });
        onDone(await getMe());
      } else {
        onDone(await login({ employee_id: employeeId.trim(), password }));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className={s.page}>
      <form className={`raised ${s.card}`} onSubmit={(e) => void submit(e)} noValidate>
        <h1 className={s.brand}>펫퍼민트 상담</h1>
        <p className={s.sub}>
          {changeFor ? `${changeFor.name ?? changeFor.employee_id}님, 처음 로그인하셨습니다. 비밀번호를 바꿔 주세요.` : "사번과 비밀번호로 로그인하세요."}
        </p>
        {notice && !changeFor && <p className={s.notice} role="status">{notice}</p>}

        {!changeFor && (
          <label className={s.field}>
            <span>사번</span>
            <input value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} autoComplete="username"
                   autoFocus required spellCheck={false} />
          </label>
        )}
        <label className={s.field}>
          <span>{changeFor ? "지금 비밀번호" : "비밀번호"}</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 autoComplete="current-password" autoFocus={!!changeFor} required />
        </label>
        {changeFor && (
          <>
            <label className={s.field}>
              <span>새 비밀번호 <small>({MIN_PASSWORD}자 이상)</small></span>
              <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required />
            </label>
            <label className={s.field}>
              <span>새 비밀번호 확인</span>
              <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />
            </label>
          </>
        )}

        {error && <p className={s.error} role="alert">{error}</p>}
        <button className={`btn btn-primary ${s.submit}`} type="submit"
                disabled={busy || !password || (!changeFor && !employeeId.trim()) || (!!changeFor && (!next || !confirm))}>
          {busy ? "확인 중…" : changeFor ? "비밀번호 바꾸기" : "로그인"}
        </button>
      </form>
    </main>
  );
}

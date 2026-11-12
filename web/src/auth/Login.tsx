// 로그인 · 첫 로그인 비밀번호 변경 화면(13번 2-1절). 한 화면 두 쓰임 — changeFor가 있으면 변경.
// 실패 문구는 서버 것을 그대로 쓴다(사번이 없는지 비밀번호가 틀렸는지 구분하지 않는다).

import { useEffect, useState, type FormEvent } from "react";
import { ApiError, changePassword, demoLogin, getDemoAccounts, getMe, login } from "../api/client";
import type { DemoAccount, MeOut } from "../api/types";
import s from "./Login.module.css";

const MIN_PASSWORD = 10; // app/services/auth.py MIN_PASSWORD

// 사번 기억하기(2026-10-30) — 사번만 이 브라우저에 둔다. 비밀번호는 저장하지 않는다(브라우저 비밀번호 관리자에 맡긴다).
// 기본 꺼짐 — 공용 PC. 체크를 풀면 바로 지운다
const REMEMBER_KEY = "petmint.login.employeeId";

function savedEmployeeId(): string {
  try { return localStorage.getItem(REMEMBER_KEY) ?? ""; } catch { return ""; }
}

interface Props {
  notice?: string | null;
  /** 임시 비밀번호로 들어온 직원 — 비밀번호를 바꿔야 앱으로 간다 */
  changeFor?: MeOut;
  onDone: (me: MeOut) => void;
}

export function Login({ notice = null, changeFor, onDone }: Props) {
  const [employeeId, setEmployeeId] = useState(savedEmployeeId);
  const [remember, setRemember] = useState(() => savedEmployeeId() !== "");
  const [password, setPassword] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // 체험 카드(13번 2-4절) — 서버가 꺼 두면(PETMINT_DEMO_LOGIN) 빈 목록이라 영역이 없다. 비밀번호 변경 화면에는 띄우지 않는다
  const [demo, setDemo] = useState<DemoAccount[]>([]);
  const [demoError, setDemoError] = useState<string | null>(null);

  useEffect(() => {
    if (changeFor) return;
    getDemoAccounts().then(setDemo).catch(() => setDemo([]));
  }, [changeFor]);

  // 카드를 누르면 바로 로그인 — 비밀번호는 화면에 없다(서버가 체험 풀 안의 사번만 받는다)
  const tryDemo = async (a: DemoAccount) => {
    setDemoError(null);
    setBusy(true);
    try {
      onDone(await demoLogin(a.employee_id));
    } catch (err) {
      setDemoError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setBusy(false);
    }
  };
  const admins = demo.filter((a) => a.role === "관리자");
  const agents = demo.filter((a) => a.role !== "관리자");

  useEffect(() => {
    if (changeFor) return;
    try {
      const id = employeeId.trim();
      if (remember && id) localStorage.setItem(REMEMBER_KEY, id);
      else localStorage.removeItem(REMEMBER_KEY);
    } catch { /* 저장소를 못 쓰면 기억하지 않는다 */ }
  }, [remember, employeeId, changeFor]);

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
      <form className={`raised ${s.card}`} method="post" onSubmit={(e) => void submit(e)} noValidate>
        <h1 className={s.brand}>펫퍼민트 상담</h1>
        <p className={s.sub}>
          {changeFor ? `${changeFor.name ?? changeFor.employee_id}님, 처음 로그인하셨습니다. 비밀번호를 바꿔 주세요.` : "사번과 비밀번호로 로그인하세요."}
        </p>
        {notice && !changeFor && <p className={s.notice} role="status">{notice}</p>}

        {/* 브라우저 비밀번호 저장: 사번은 username, 비밀번호는 current-password · new-password. 변경 화면에도 사번을 숨겨 두어
            새 비밀번호가 어느 계정 것인지 브라우저가 안다 */}
        {changeFor ? (
          <input type="text" name="username" autoComplete="username" value={changeFor.employee_id ?? ""} readOnly hidden />
        ) : (
          <div className={s.idGroup}>
            <label className={s.field}>
              <span>사번</span>
              <input id="employee-id" name="username" value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}
                     autoComplete="username" autoCapitalize="none" autoFocus={!employeeId} required spellCheck={false} />
            </label>
            <label className={s.remember}>
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
              <span>사번 기억하기</span>
            </label>
          </div>
        )}
        <label className={s.field}>
          <span>{changeFor ? "지금 비밀번호" : "비밀번호"}</span>
          <input type="password" name="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 autoComplete="current-password" autoFocus={!!changeFor || !!employeeId} required />
        </label>
        {changeFor && (
          <>
            <label className={s.field}>
              <span>새 비밀번호 <small>({MIN_PASSWORD}자 이상)</small></span>
              <input type="password" value={next} onChange={(e) => setNext(e.target.value)} name="new-password"
                     autoComplete="new-password" required />
            </label>
            <label className={s.field}>
              <span>새 비밀번호 확인</span>
              <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} name="confirm-password"
                     autoComplete="new-password" required />
            </label>
          </>
        )}

        {error && <p className={s.error} role="alert">{error}</p>}
        <button className={`btn btn-primary ${s.submit}`} type="submit"
                disabled={busy || !password || (!changeFor && !employeeId.trim()) || (!!changeFor && (!next || !confirm))}>
          {busy ? "확인 중…" : changeFor ? "비밀번호 바꾸기" : "로그인"}
        </button>
      </form>

      {/* 체험 — 상담원 · 관리자를 나눈다(2026-11-12 사용자, 런슈즈 로그인과 같은 나눔). 직원마다 인사 데이터가 달라 카드에 무엇을 볼 수 있는지 적는다 */}
      {!changeFor && demo.length > 0 && (
        <section className={`raised ${s.demo}`} aria-label="체험 계정">
          <h2 className={s.demoHead}>사번 없이 체험하기</h2>
          <p className={s.demoNote}>
            누구나 함께 쓰는 체험 계정입니다. 남긴 상담은 다른 방문자도 볼 수 있어요. 고객 · 직원 정보는 모두 가상입니다.
            사내규정 모드에서 "제 연차 며칠 남았어요?"처럼 물으면 고른 직원의 인사 기록으로 답합니다.
          </p>
          {demoError && <p className={s.error} role="alert">{demoError}</p>}
          {agents.length > 0 && (
            <div className={s.demoGroup}>
              <h3 className={s.demoTitle}>상담원으로 체험하기</h3>
              <ul className={s.demoList}>
                {agents.map((a) => <DemoCard key={a.employee_id} a={a} busy={busy} onPick={tryDemo} />)}
              </ul>
            </div>
          )}
          {admins.length > 0 && (
            <div className={s.demoGroup}>
              <h3 className={s.demoTitle}>관리자로 체험하기</h3>
              <p className={s.demoNote}>지금은 상담원과 같은 화면입니다. 관리자 화면은 준비 중이에요.</p>
              <ul className={s.demoList}>
                {admins.map((a) => <DemoCard key={a.employee_id} a={a} busy={busy} onPick={tryDemo} />)}
              </ul>
            </div>
          )}
        </section>
      )}
    </main>
  );
}

function DemoCard({ a, busy, onPick }: { a: DemoAccount; busy: boolean; onPick: (a: DemoAccount) => void }) {
  return (
    <li>
      <button type="button" className={s.demoCard} onClick={() => onPick(a)} disabled={busy}>
        <strong className={s.demoSummary}>{a.summary}</strong>
        {a.tags.length > 0 && (
          <span className={s.demoTags}>{a.tags.map((t) => <span key={t} className={s.demoTag}>{t}</span>)}</span>
        )}
      </button>
    </li>
  );
}

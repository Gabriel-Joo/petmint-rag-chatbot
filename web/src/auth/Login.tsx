// 로그인 · 첫 로그인 비밀번호 변경 화면(13번 2-1절). 한 화면 두 쓰임 — changeFor가 있으면 변경.
// 실패 문구는 서버 것을 그대로 쓴다(사번이 없는지 비밀번호가 틀렸는지 구분하지 않는다).

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ApiError, changePassword, demoLogin, getDemoAccounts, getMe, login } from "../api/client";
import type { DemoAccount, MeOut } from "../api/types";
import { DemoCard, DemoCards } from "./DemoCards";
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
        {/* 로고는 상단바 로고(TopBar .brandTitle)와 같은 토큰 — 본문 배율 그대로(.chat-text 밖). 그 아래 글씨는 대화 화면 토큰(.chat-text) */}
        <h1 className={s.brand}>펫퍼민트 상담</h1>
        <div className={`chat-text ${s.body}`}>
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
        <PasswordField id="password" label={changeFor ? "지금 비밀번호" : "비밀번호"} name="password" value={password}
                       onChange={setPassword} autoComplete="current-password" autoFocus={!!changeFor || !!employeeId} />
        {changeFor && (
          <>
            <PasswordField id="new-password" label={<>새 비밀번호 <small>({MIN_PASSWORD}자 이상)</small></>} name="new-password"
                           value={next} onChange={setNext} autoComplete="new-password" />
            <PasswordField id="confirm-password" label="새 비밀번호 확인" name="confirm-password" value={confirm}
                           onChange={setConfirm} autoComplete="new-password" />
          </>
        )}

        {error && <p className={s.error} role="alert">{error}</p>}
        <button className={`btn btn-primary ${s.submit}`} type="submit"
                disabled={busy || !password || (!changeFor && !employeeId.trim()) || (!!changeFor && (!next || !confirm))}>
          {busy ? "확인 중…" : changeFor ? "비밀번호 바꾸기" : "로그인"}
        </button>
        </div>
      </form>

      {/* 체험 — 상담원 · 관리자를 나눈다(2026-11-12 사용자, 런슈즈 로그인과 같은 나눔). 상담원은 2줄로 가로로 흐르고(DemoCards),
          관리자는 그 아래 한 장(점선). 칩은 이 계정으로 볼 수 있는 것 — 무엇을 물어볼지 알게 다 싣는다 */}
      {!changeFor && demo.length > 0 && (
        <section className={`chat-text ${s.demo}`} aria-label="체험 계정">
          <h2 className={s.demoHead}>사번 없이 체험하기</h2>
          <p className={s.demoNote}>
            누구나 함께 쓰는 체험 계정이라 남긴 상담은 다른 방문자도 볼 수 있어요. 고객 · 직원 정보는 모두 가상입니다.<br />
            사내규정 모드에서 "제 연차 며칠 남았어요?"처럼 물으면 고른 직원의 인사 기록으로 답합니다.
          </p>
          {demoError && <p className={s.error} role="alert">{demoError}</p>}
          {/* 상담원 · 관리자를 세로로 쌓는다(2026-11-12 사용자) — 흐르는 영역이 화면 전체 폭을 쓴다 */}
          {agents.length > 0 && (
            <div className={s.demoGroup}>
              <h3 className={s.demoTitle}>상담원으로 체험하기</h3>
              <DemoCards cards={agents} busy={busy} onPick={(a) => void tryDemo(a)} />
            </div>
          )}
          {admins.length > 0 && (
            <div className={`${s.demoGroup} ${s.demoAdmins}`}>
              <h3 className={s.demoTitle}>관리자로 체험하기</h3>
              {admins.map((a) => <DemoCard key={a.employee_id} a={a} busy={busy} onPick={(x) => void tryDemo(x)} admin />)}
              <p className={s.demoNote}>지금은 상담원과 같은 화면이에요. 관리자 화면은 준비 중입니다.</p>
            </div>
          )}
        </section>
      )}
    </main>
  );
}

/** 비밀번호 보기 단추의 눈 — 가렸을 때는 사선이 그어진 눈, 보일 때는 눈(런슈즈 src/auth/Field.tsx와 같은 그림) */
function Eye({ open }: { open: boolean }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor"
         strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
      {!open && <path d="M4 20 20 4" />}
    </svg>
  );
}

/** 비밀번호 칸 + 보기 단추(2026-11-12, 런슈즈 로그인과 같은 방식) — 칸 오른쪽 끝에 겹친 눈. 칸마다 따로 켠다 */
function PasswordField({ id, label, name, value, onChange, autoComplete, autoFocus = false }: {
  id: string; label: ReactNode; name: string; value: string; onChange: (v: string) => void;
  autoComplete: string; autoFocus?: boolean;
}) {
  const [shown, setShown] = useState(false);
  return (
    <label className={s.field} htmlFor={id}>
      <span>{label}</span>
      <span className={s.pw}>
        <input id={id} type={shown ? "text" : "password"} name={name} value={value} onChange={(e) => onChange(e.target.value)}
               autoComplete={autoComplete} autoFocus={autoFocus} required spellCheck={false} />
        <button type="button" className={s.pwToggle} onClick={() => setShown((v) => !v)}
                aria-label={shown ? "비밀번호 가리기" : "비밀번호 보기"} aria-pressed={shown} aria-controls={id}>
          <Eye open={shown} />
        </button>
      </span>
    </label>
  );
}

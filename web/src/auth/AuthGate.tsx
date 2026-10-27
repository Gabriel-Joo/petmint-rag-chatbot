// 로그인 관문(13번 2-1절, 2026-10-28). 처음에 /api/auth/me를 불러
// - access 모드(Cloudflare Access 헤더가 신원): 바로 앱을 띄운다 — 지금 동작 그대로
// - app 모드: 로그인 안 됐으면 로그인 화면, 관리자가 준 임시 비밀번호면 비밀번호 변경 화면, 다 되면 앱
// 앱이 쓰는 중에 401·WS 4401이 오면(만료·다른 기기에서 비밀번호 변경·퇴직) 로그인 화면으로 돌아간다.
// 로그아웃은 새로고침으로 끝낸다 — 대화 캐시·소켓(useChatSocket 모듈 상태)을 남기지 않는다.

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiError, getMe, logout, UNAUTHORIZED_EVENT } from "../api/client";
import type { MeOut } from "../api/types";
import { Login } from "./Login";

interface Props {
  children: (me: MeOut, onLogout: (() => void) | null) => ReactNode;
}

type State = { kind: "loading" } | { kind: "error"; message: string } | { kind: "login"; notice: string | null } | { kind: "ready"; me: MeOut };

export function AuthGate({ children }: Props) {
  const [state, setState] = useState<State>({ kind: "loading" });

  const load = useCallback(async () => {
    try {
      setState({ kind: "ready", me: await getMe() });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setState({ kind: "login", notice: null });
      else setState({ kind: "error", message: e instanceof ApiError ? e.detail : String(e) });
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    const onLost = () => setState((prev) => (prev.kind === "ready" && prev.me.auth_mode === "app"
      ? { kind: "login", notice: "로그인이 만료되었습니다. 다시 로그인하세요." } : prev));
    window.addEventListener(UNAUTHORIZED_EVENT, onLost);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onLost);
  }, []);

  const onLogout = useCallback(async () => {
    try { await logout(); } finally { window.location.reload(); }
  }, []);

  if (state.kind === "loading") return null;
  if (state.kind === "error") return <div role="alert" style={{ padding: 24 }}>서버에 연결할 수 없습니다 — {state.message}</div>;
  if (state.kind === "login") return <Login notice={state.notice} onDone={(me) => setState({ kind: "ready", me })} />;
  if (state.me.must_change_password) {
    return <Login changeFor={state.me} onDone={(me) => setState({ kind: "ready", me })} />;
  }
  return <>{children(state.me, state.me.auth_mode === "app" ? () => void onLogout() : null)}</>;
}

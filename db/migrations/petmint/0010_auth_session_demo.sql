-- petmint 0010_auth_session_demo.sql — 체험 로그인 세션 표시(2026-11-12, docs/13 2-4절).
-- 체험 로그인(POST /api/auth/demo)은 비밀번호 없이 기존 가상 직원으로 들어온다. 계정이 아니라 로그인 세션에 표시한다 —
-- 같은 직원이 사번 · 비밀번호로 들어오면 체험이 아니다. demo 세션은 비밀번호를 바꿀 수 없고, 질문이 분당 10회로 제한되고,
-- 화면에 "체험 계정"이 붙는다. 체험 로그인의 IP별 횟수도 이 칸으로 센다.
-- 기존 세션은 FALSE(일반 로그인)다. ALGORITHM=INSTANT — 테이블을 다시 쓰지 않는다.

ALTER TABLE auth_sessions
    ADD COLUMN demo BOOLEAN NOT NULL DEFAULT FALSE AFTER user_agent,
    ALGORITHM=INSTANT;

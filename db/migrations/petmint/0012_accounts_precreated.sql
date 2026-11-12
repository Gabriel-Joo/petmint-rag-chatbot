-- petmint 0012_accounts_precreated.sql — 가상 직원 앱 계정을 미리 만든다(2026-11-12 사용자, docs/13 2-4절).
-- 전에는 체험 로그인을 누를 때 계정이 생겨, 체험할수록 관리자 화면 직원 목록의 「앱 계정 없음」이 줄었다.
-- 이제 계정은 여기서 정하고, 체험 로그인은 있는 계정만 쓴다(app/services/auth.py demo_pool).
--
-- 만든다(비밀번호 없음 — 사번 · 비밀번호로는 들어올 수 없다. 사람이 쓰려면 python -m db.employees reset <사번>):
--   권태호(관리자) · 송미경 · 임동욱 · 장민혁 · 노은비 · 배수정 · 신하늘(상담원)
--   이미 있으면 그대로 둔다(역할 · 비밀번호 · 잠금 · 중지를 바꾸지 않는다).
-- 계정 없음으로 둔다(있으면 지운다 — 로그인 세션도 FK CASCADE로 지워진다. 상담 기록 sessions.agent_email은 남는다):
--   조현석 · 문태양 · 류채원 — 입사가 늦어 아직 앱 계정이 없는 상황
--   황재민 — 2026-08-31 퇴직

INSERT INTO accounts (employee_id, role, password_hash, must_change_password, created_at) VALUES
    ('E2001003', '관리자', NULL, TRUE, UTC_TIMESTAMP(3)),
    ('E2009021', '상담원', NULL, TRUE, UTC_TIMESTAMP(3)),
    ('E2013007', '상담원', NULL, TRUE, UTC_TIMESTAMP(3)),
    ('E2018032', '상담원', NULL, TRUE, UTC_TIMESTAMP(3)),
    ('E2020005', '상담원', NULL, TRUE, UTC_TIMESTAMP(3)),
    ('E2020114', '상담원', NULL, TRUE, UTC_TIMESTAMP(3)),
    ('E2022071', '상담원', NULL, TRUE, UTC_TIMESTAMP(3))
AS new
ON DUPLICATE KEY UPDATE employee_id = accounts.employee_id;

DELETE FROM accounts WHERE employee_id IN ('E2025112', 'E2025030', 'E2026090', 'E2015044');

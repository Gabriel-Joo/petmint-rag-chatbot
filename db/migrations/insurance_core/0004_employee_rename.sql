-- insurance_core 0004_employee_rename.sql — 가상 직원 이름·이메일·팀 바꾸기(2026-10-28).
-- 예시 이름(홍길동 등) → 고객 10명과 성까지 겹치지 않는 이름, 팀은 고객상담팀 하나(상담원 전용 도구 — 칸은 남긴다, 나중에 부서가 생길 수 있다).
-- 사번은 그대로다(입사연도 + 순번, 로그인 ID). 이미 깔린 원장(운영 포함)을 바꾼다 — 새로 까는 원장은 픽스처가 이미 새 값이라 바뀌는 행이 없다.
-- 상담 기록(petmint.sessions.agent_email)은 petmint 0007이 같은 이메일로 바꾼다.

UPDATE employees SET name = '권태호', email = 'kwon.taeho@petmint.example', team = '고객상담팀' WHERE employee_id = 'E2001003';
UPDATE employees SET name = '송미경', email = 'song.mikyung@petmint.example', team = '고객상담팀' WHERE employee_id = 'E2009021';
UPDATE employees SET name = '임동욱', email = 'lim.dongwook@petmint.example', team = '고객상담팀' WHERE employee_id = 'E2013007';
UPDATE employees SET name = '배수정', email = 'bae.sujeong@petmint.example', team = '고객상담팀' WHERE employee_id = 'E2020114';
UPDATE employees SET name = '장민혁', email = 'jang.minhyuk@petmint.example', team = '고객상담팀' WHERE employee_id = 'E2018032';
UPDATE employees SET name = '노은비', email = 'noh.eunbi@petmint.example', team = '고객상담팀' WHERE employee_id = 'E2020005';
UPDATE employees SET name = '신하늘', email = 'shin.haneul@petmint.example', team = '고객상담팀' WHERE employee_id = 'E2022071';
UPDATE employees SET name = '조현석', email = 'cho.hyunseok@petmint.example', team = '고객상담팀' WHERE employee_id = 'E2025112';
UPDATE employees SET name = '류채원', email = 'ryu.chaewon@petmint.example', team = '고객상담팀' WHERE employee_id = 'E2026090';
UPDATE employees SET name = '문태양', email = 'moon.taeyang@petmint.example', team = '고객상담팀' WHERE employee_id = 'E2025030';
UPDATE employees SET name = '황재민', email = 'hwang.jaemin@petmint.example', team = '고객상담팀' WHERE employee_id = 'E2015044';

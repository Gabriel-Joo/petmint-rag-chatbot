-- petmint 0007_agent_email_rename.sql — 가상 직원 이메일 바꾸기에 맞춰 상담 기록의 상담원 이메일을 옮긴다(2026-10-28, insurance_core 0004와 짝).
-- 세션 소유권·지난 채팅 목록이 agent_email로 거르므로, 바꾸지 않으면 이름을 바꾼 직원의 지난 상담이 사라진 것처럼 보인다.
-- 로그인(accounts·auth_sessions)은 사번으로 묶여 있어 그대로 이어진다.

UPDATE sessions SET agent_email = 'kwon.taeho@petmint.example' WHERE agent_email = 'hong.gildong@petmint.example';
UPDATE sessions SET agent_email = 'song.mikyung@petmint.example' WHERE agent_email = 'kim.minji@petmint.example';
UPDATE sessions SET agent_email = 'lim.dongwook@petmint.example' WHERE agent_email = 'lee.seojun@petmint.example';
UPDATE sessions SET agent_email = 'bae.sujeong@petmint.example' WHERE agent_email = 'park.jieun@petmint.example';
UPDATE sessions SET agent_email = 'jang.minhyuk@petmint.example' WHERE agent_email = 'choi.hyunwoo@petmint.example';
UPDATE sessions SET agent_email = 'noh.eunbi@petmint.example' WHERE agent_email = 'jung.daeun@petmint.example';
UPDATE sessions SET agent_email = 'shin.haneul@petmint.example' WHERE agent_email = 'han.subin@petmint.example';
UPDATE sessions SET agent_email = 'cho.hyunseok@petmint.example' WHERE agent_email = 'kang.doyun@petmint.example';
UPDATE sessions SET agent_email = 'ryu.chaewon@petmint.example' WHERE agent_email = 'yoon.seoyeon@petmint.example';
UPDATE sessions SET agent_email = 'moon.taeyang@petmint.example' WHERE agent_email = 'lim.jaehyun@petmint.example';
UPDATE sessions SET agent_email = 'hwang.jaemin@petmint.example' WHERE agent_email = 'oh.jungmin@petmint.example';

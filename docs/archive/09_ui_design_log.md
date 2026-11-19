# 09 UI 설계 구현 기록

docs/02_pipeline/09_ui_design.md 에서 떼어 낸 구현 기록(2026-11-19 문서 정리 B단계). 지금 설계는 docs/02_pipeline/09_ui_design.md

## 구현 순서 (옛 10절)

뼈대부터 만들되 구조는 전부 넣는다. 나중에 끼우면 전체를 뒤집어야 하는 것을 먼저 둔다.

| 먼저 | 나중에 |
| --- | --- |
| 세션·턴 모델, turn_id | 캐릭터 그림 |
| WS 메시지 순서와 cancel | 근거 패널 디자인 |
| 로그 스키마 | 애니메이션·전환 |
| 반응형 레이아웃 |  |

## 되묻기 구현 상태 (옛 4절 끝 줄)

✓ 되묻기 판정·`clarify`·`clarify_answer`로 잇기(answer.py `clarify_options`·`resume_clarified`) — 로컬·배포 서버 확인(10-20·21, 검증 R3). ✓ 금액 되묻기(10-21, 검증 R14·R15). ✓ 여러 날 입원·여러 번 통원 — 날짜별 입력 카드·범위·청구 이력(10-21, 검증 R18~R29). △ 가정 질문 판정(`is_hypothetical`)과 "가입 계약 기준 아님" 배너는 코드 없음 — 가입과 다른 등급·유형의 한도 질문은 가정 등급 한도표(`payout.hypothetical_card`, 2026-10-21, 16번 ⑤)가 답한다. [code:app/services/answer.py:268] [code:app/services/answer.py:310] [code:data/review/verify_modes_20261021.md:21] [code:app/services/answer.py:19] [code:app/services/payout.py:462] <!-- 확인 못 함: 배포 서버 확인 기록은 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답). 다시 재려면 서비스가 끊길 수 있어 사람 승인이 필요함 -->

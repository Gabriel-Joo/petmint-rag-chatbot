# rebuild5 (7단계) 설정 — 2026-10-21 사용자 결정

이 파일이 7단계 설정의 원본이다. compact 뒤에도 이 파일을 먼저 읽는다.

| 항목 | 결정 |
|---|---|
| 청크 | **B** — v2 작은 조각으로 찾고(`PETMINT_SEARCH_VARIANT=v2`) 원래 청크를 보여줌(`PETMINT_DISPLAY_PARENT=1`). 학습 데이터 발췌도 같은 경로로 만든다 |
| 1차 후보 | **20** 유지(pool_k 늘리지 않음) |
| 질의 확장 | 켬(`PETMINT_SEARCH_EXPAND=1`) — 동의어 사전은 4번 결정대로 확장 후 회귀 확인 |
| QA 수정 | 반려동물 주어(pet_subject)는 **표시만**(빼지 않음). 계산이 틀린 QA(변호사비·인지액·의료비)는 **코드 값으로 고친다**(버리지 않음) |
| 일상어 | 질문 재작성에 **넣되**, 일상어 데이터를 **따로 학습하지 않는다**(같은 QA의 질문만 바꿈, 건수 늘리지 않음). 재작성 프롬프트에 예시 문장을 넣지 않는다(예시 따라 쓰기 → 반려동물이 소송·배당금 주어가 된 버그) |
| 목표 답 | **"결론 + 단서"** 형식 |
| 라벨 | 3가지(정답 있음 / 부분 / 정답 없음 → 거절). 정답 청크가 검색에 없을 때 넣는 비율과 '정답 없어 거절' 비율을 rebuild4(90.8% / 9.2%)와 비교해 기록 |
| 코드 답 | 의료비·한도·법률비용 카드 턴, 가정 등급·유형 질문, 미가입·연간 잔여는 코드가 답(6·7번) |
| 진행 | 학습 → 체크포인트 선택(data.ckpt_select) → GGUF·Ollama → **숨긴 세트(eval220_hidden) 열고** 평가(eval_serving --open-hidden, 3회 + judge, rebuild4 대비)까지 멈추지 않는다 |
| 서빙 최종 설정 | `PETMINT_SEARCH_EXPAND=1 PETMINT_CUSTOMER_FACTS=1 PETMINT_CHUNKS_DIR=data/chunks/v2 PETMINT_GRAPH_DIR=data/graph/v2 PETMINT_SEARCH_VARIANT=v2 PETMINT_DISPLAY_PARENT=1` |

바꾸지 않는 것: 생성 모델·임베딩·리랭커, 운영 클러스터 기본 동작(새 기능은 opt-in), 외부 API 0건.

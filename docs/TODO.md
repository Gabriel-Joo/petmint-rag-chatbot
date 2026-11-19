<!--
다루는 곳: app/services/followup.py, deploy/host/petmint-search.service, README.md, deploy/README.md
읽은 커밋: 6710b83
-->
# 나중에 할 일 (정해 두고 미룬 것)

대화에서 "나중에 하자"고 정한 것만 적는다. 끝나면 이 표에서 뺀다.

꼴과 번호: 항목은 `- **petmint-N** 제목 (올린 날)`, 다음 줄에 언제와 조건, 그다음 줄에 나온 곳을 쓴다. 번호는 한 번 쓰면 다시 쓰지 않고 끝난 항목은 지운다. 올린 날은 그 줄이 이 파일에 처음 적힌 커밋의 날이다(2026-11-19 표에서 옮기며 셈, FOREMAN `docs/TODO.md`와 같은 꼴). 번호는 옮기기 전 표의 줄 차례다.

- **petmint-1** 후속 질문 판별에 LLM 얹기 (2026-11-10)
  언제: 정하지 않음. 규칙(지시어, 생략 꼬리, 금액만, 8자 이하)이 놓치는 후속 질문이 거슬릴 때만. 지금은 규칙만 쓴다 [code:app/services/followup.py]
  나온 곳: 사람 말 10-21 06:50("놓치는 게 거슬리면 나중에 LLM을 얹는다"), `docs/02_pipeline/09_ui_design.md` 1-9절 [c:be32dca]
- **petmint-2** 노션 「인프라 > 쿠버네티스 설치」의 낡은 문장 고치기 (2026-11-10)
  언제: 정하지 않음. 사람이 노션에서 직접 고친다. 이 페이지는 docs→Notion 자동 반영 대상(20개) 밖이다
  나온 곳: 사람 말 11-09 11:02("나중에 따로 고칠게") [c:be32dca]
- **petmint-3** 포트폴리오 쪽 정리(보여줄 문서, 영상, 구조 설명) (2026-11-10)
  언제: 정하지 않음. 사람이 시작을 말할 때. 저장소 루트 README는 11-10에 썼다. 남은 것은 포트폴리오 쪽 정리다
  나온 곳: 사람 말 11-10 09:14("포트폴리오는 나중에 한다"), 루트 README 11-10 [c:ae76968]
- **petmint-4** README 「돌리는 법」 명령을 실제로 따라 해 보기(`db.bootstrap`, `npm ci && npm run dev` 포함) (2026-11-10)
  언제: 정하지 않음. 11-10 작성 당시 명령은 파일만 보고 옮겼고 돌려보지 않았다
  나온 곳: 루트 README 11-10(1f85f98) [c:fff6bba]
- **petmint-5** 압축 손실 점검 #2 결과 보고 되살릴 것 정하기: 세션 대화가 압축되며 문서에 안 남은 결정을 기계로 찾은 결과(사라짐 93, 약해짐 38, 뒤집힘 16, 살아 있음 42, 끝남 81) (2026-11-15)
  언제: 펫퍼민트를 다시 만질 때. 사람이 결과를 보고 정한다. 결과는 FOREMAN에 있다: 점검 #2(세션 155), FOREMAN `log/cross_paste_20261109.md` 3절. 11-09 커밋 1cf1479가 결정 11개를 되살렸지만 이 점검 결과를 보고 한 것인지는 확인되지 않는다
  나온 곳: 사람 말 11-09("펫퍼민트 손실 결과는 나중에 볼게. 지금 그 프로젝트 안 건드리니까"), FOREMAN README 「나중에 할 일」에서 옮김(11-15 사용자 지시, FOREMAN 관리자 전달) [c:aea5a6f]
- **petmint-6** 노션 기술문서 일곱 쪽(09, 11~16) 덮기를 FOREMAN 관리자에게 알리기. 덮은 뒤 일곱 쪽이 다시 「사람 수정으로 멈춤」으로 서는지 보고 사람에게 알린다 (2026-11-19)
  언제: 펫퍼민트 docs를 다시 쓴 뒤. 지금은 FOREMAN 서기실에 일곱 쪽이 「사람 수정으로 멈춤」으로 뜬다. 고장이 아니라 미룬 상태다. 일곱 쪽 모두 노션에만 있는 글자는 없었다(11-19 글자 단위 비교)
  나온 곳: FOREMAN 사용자 결정 11-19(FOREMAN 관리자 전달, 「docs를 다시 쓴 뒤 덮습니다」), 사람 말 11-19(「덮은 뒤 일곱 쪽이 다시 「사람이 고침」으로 멈추는지 보고 알려 주세요. 멈추면 덮기로 풀리는 문제가 아닙니다」) [c:68ed76d]
- **petmint-8** 재부팅 순서 확인: `model-service` → Milvus 대기 → `petmint-search`가 순서대로 뜨는지, model-service가 늦거나 Restart될 때 petmint-search가 기다리는지, virbr0가 늦을 때 bind 실패 뒤 Restart로 회복하는지 (2026-11-11)
  언제: 다음 서버 재부팅 때. 재부팅은 사람이 정한다(이 세션은 재부팅하지 않는다). 볼 명령은 model-service 런북 8절 [code:deploy/host/petmint-search.service]
  나온 곳: 사람 말 11-11("실제 재부팅 시험은 아직 안 했다"), `docs/02_pipeline/14_deployment.md` 1-16절 [c:26bee9f]
- **petmint-9** 모드 검증의 거절 판정을 운영과 같은 기준으로 (2026-11-19)
  언제: 정하지 않음. 모드 검증(`scripts/verify_modes.py`)은 C안 함수 `data.refusal.refused`를 쓰지 않고 거절 문구 목록 전체로 거절을 가린다. 그래서 맺음말 문구만 있어도 거절로 친다. 운영 집계(`turns.refused`)와 서빙 평가는 C안이라 모드 검증만 기준이 다르다. 일부러 그렇게 둔 것인지는 문서에 없다 [code:scripts/verify_modes.py:93-95]
  나온 곳: 문서 정리 A단계 근거 달기(2026-11-19), `docs/02_pipeline/12_data_storage.md` turns 표, `docs/02_pipeline/15_monitoring.md` 1-3절
- **petmint-10** 대화 기록에 색인 버전이 남지 않음 (2026-11-19)
  언제: 정하지 않음. `INDEX_VERSION`이 "unset" 그대로라 턴 기록의 색인 버전으로 로그를 비교할 수 없다. 주석은 「재색인 때 올린다」이다 [code:app/config.py:80]
  나온 곳: 문서 정리 A단계 근거 달기(2026-11-19), `docs/02_pipeline/09_ui_design.md` 1-12절
- **petmint-11** 지금 동작보다 뒤처진 코드 주석 (2026-11-19)
  언제: 정하지 않음. 동작은 문서와 같고 주석만 낡았다. `data/faq_rag.py:7` 「그 질문도 되살려 쓴다」(실제로는 `full()`이 되살린 incomplete를 뺀다), `data/answer_eval.py:220` 「answer.fit_to_budget」(실제로는 `prompts.fit_to_budget`), `data/faq_verify.py:4` 「74개 중 19개 오류, 26%」(KNOWN_ISSUES는 고친 검증기로 26/74, 35%. 같은 측정인지 확인 필요), `app/services/article_display.py:4` 「ArticleOut.blocks」(칸 이름은 sections), 같은 파일 8줄 「91.0%」(최종 93.8%), `web/src/styles/tokens.css:1` 「10번 10절」(지금은 11번), 같은 파일 14줄 「전화 전용」(진행 중 상담 표시에도 쓴다), 같은 파일 69줄과 `web/src/styles/global.css:13` 「헤더 로고만 완주대둔산체」(로그인 화면 등 여러 곳에 쓴다), `app/services/answer.py:19` 「아직 없는 것: 부담보 배너」(이미 있다) [code:data/faq_rag.py:7] [code:data/answer_eval.py:220] [code:data/faq_verify.py:4] [code:app/services/article_display.py:4] [code:app/services/article_display.py:8] [code:web/src/styles/tokens.css:1] [code:web/src/styles/tokens.css:14] [code:web/src/styles/tokens.css:69] [code:web/src/styles/global.css:13] [code:app/services/answer.py:19]
  나온 곳: 문서 정리 A단계 근거 달기(2026-11-19), 07, 05, 10, 11, 09편 안 맞음 대조
- **petmint-12** `deploy/README.md`의 배포 흐름이 옛 그대로 (2026-11-19)
  언제: 정하지 않음. 「Jenkins petmint-app (2분 폴링)」, 「사람이 Sync (지금은 수동)」으로 적혀 있다. 지금은 웹훅과 안전망 폴링 15분이고 ArgoCD는 자동 Sync다(2026-11-11~) [code:deploy/README.md:21] [code:deploy/README.md:23] [code:Jenkinsfile:3] [docs:02_pipeline/14_deployment.md]
  나온 곳: 문서 정리 A단계 근거 달기(2026-11-19), `docs/02_pipeline/14_deployment.md` 1-15절
- **petmint-13** 홈 모드 카드 넘김 화살표의 `font-size: 22px`가 「크기는 새로 만들지 않는다」에 걸리는지 (2026-11-19)
  언제: 정하지 않음. 규칙 원문은 「새 배율 · px을 만들지 않고 이미 있는 글자 크기 토큰만 쓴다」(11번 1-3절, 2026-11-12)라 새 크기를 막는 뜻과 토큰 밖 값을 막는 뜻이 한 문장에 함께 있어 가를 수 없다. 22px는 같은 날 넘김 화살표를 더한 커밋에서 들어왔고, 글자가 아니라 44px 단추 안 화살표 글리프다 [code:web/src/pages/ModeSelect.module.css:229] [c:f30cf58] [docs:02_pipeline/11_design_system.md:77]
  나온 곳: 문서 정리 A단계 근거 달기(2026-11-19), `docs/02_pipeline/11_design_system.md`
- **petmint-14** 06 심판 코드 주석의 Gemma 재현율 77%를 원자료 값 75%로 (2026-11-19)
  언제: 정하지 않음. `data/faq_judge.py` 머리 주석은 「후보(개발용 1·2차 88건): Gemma 4 12B 재현 77%」라고 적는데, 원자료 `data/faq/review/judge_dev_candidates_20261013.json`의 참조를 함께 준 88건을 다시 세면 75%다(오탐 15%와 다른 모델 값은 맞다). 문서(06번 2-2-2절 표)는 75%로 고쳤다. 같은 수가 두 곳에 있고 코드 쪽이 틀렸다 [code:data/faq_judge.py:7] [c:3f49bb5]
  나온 곳: 문서 정리 A단계 원자료 대조(2026-11-19), `docs/02_pipeline/06_quality_check.md` 2-2-2절
- **petmint-15** 홈 모드 카드 주석 「영상(10-6)」이 가리키는 문서 절 찾기 (2026-11-19)
  언제: 10편이나 11편을 고쳐 쓸 때. `web/src/pages/ModeSelect.tsx` 16행 주석이 「영상(10-6)」을 가리키는데 B단계 전에도 그런 절이 없어 새 번호로 고치지 못했다. 캐릭터 영상 설명이 있는 절을 찾아 주석을 고친다
  나온 곳: 문서 정리 B단계 코드 주석 절 번호 고치기(2026-11-19), `docs/02_pipeline/10_consultation_flow.md` 맨 아래 옛 절 번호 표
- **petmint-16** 시드 상담 데이터의 `note`가 옛 절 번호를 가리킴 (2026-11-19)
  언제: 정하지 않음. `db/fixtures/seed_consultations.json` 2행 `note` 값이 「docs/13 2-5절」(시드 상담)을 가리키는데 그 절은 기록 파일로 옮겼다. 주석이 아니라 데이터 값이라 고치지 않았다. 화면에 보일 수 있으니 고칠지 그때 정한다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/13_access_and_tunnel.md` 맨 아래 표
- **petmint-17** 운영 DB 백업 실패를 알리지 않음 (2026-11-19)
  언제: 정하지 않음. CronJob 실패는 kubectl과 ArgoCD 화면에서만 보인다
  나온 곳: 문서 정리 B단계 한계 가르기(2026-11-19), `docs/02_pipeline/12_data_storage.md` 옛 4절
- **petmint-18** 백업이 하루 단위라 마지막 백업 뒤 대화를 잃음(PITR 없음) (2026-11-19)
  언제: 정하지 않음
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/12_data_storage.md` 옛 4절
- **petmint-19** 로그인 잠금이 사번 단위 (2026-11-19)
  언제: 정하지 않음. 없는 사번을 돌려 가며 시도하는 것을 막지 못하고, 잠김 안내로 사번이 있다는 것이 드러난다 [code:app/services/auth.py:28-33] [code:app/services/auth.py:124-135]
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/13_access_and_tunnel.md` 옛 4절
- **petmint-20** Access를 앞에 두면 로그인을 두 번 함 (2026-11-19)
  언제: 정하지 않음. SSO 연동이 따로 필요하다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/13_access_and_tunnel.md` 옛 4절
- **petmint-21** 체험 로그인 IP 제한의 빈틈 (2026-11-19)
  언제: 정하지 않음. 남은 세션 행으로 세어 로그아웃하면 다시 셀 수 있고, `CF-Connecting-IP`는 사설망 요청이면 바꿔 보낼 수 있다 [code:app/services/auth.py:162-166] [code:app/services/auth.py:196-199] [code:app/deps.py:50-54]
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/13_access_and_tunnel.md` 옛 4절
- **petmint-22** 답 고쳐쓰기 버튼(「더 짧게」, 「고객에게 말하듯이 다시」를 베이스 모델로) (2026-11-19)
  언제: 정하지 않음. 코드가 없다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/09_ui_design.md` 옛 5절
- **petmint-23** 멀티턴 재작성의 실제 품질 재기 (2026-11-19)
  언제: 정하지 않음. 부족하면 재작성기만 따로 학습한다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/09_ui_design.md` 옛 9절
- **petmint-24** 파이프라인을 LangChain(LCEL)으로 묶을지 직접 짤지 정하기 (2026-11-19)
  언제: 정하지 않음
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/09_ui_design.md` 옛 9절
- **petmint-25** WebSocket cancel 서버 처리 (2026-11-19)
  언제: 정하지 않음. 턴이 수신 루프 안에서 돌아 생성 중에 cancel을 받지 못한다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/09_ui_design.md` 옛 7-2절
- **petmint-26** Ollama 두 모델 상주 설정 정하고 재기 (2026-11-19)
  언제: 정하지 않음. `OLLAMA_MAX_LOADED_MODELS`와 keep_alive를 검색 모델 몫을 뺀 VRAM으로 정한다. 두 모델이 함께 상주할 수 있으면 2로 두고, 못 하면 갈아 끼우는 지연을 first_token_ms로 잰다. 생성 중과 겹친 VRAM 값도 잰다. 10편 1-9절의 keep_alive 「설정 전」 줄과 같은 일이다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/09_ui_design.md` 옛 7-3절, `docs/02_pipeline/10_consultation_flow.md` 1-9절
- **petmint-27** 가정 질문 판정(is_hypothetical)과 「가입 계약 기준 아님」 배너 (2026-11-19)
  언제: 정하지 않음
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/09_ui_design.md` 옛 4절 끝 줄(기록 파일로 옮김)
- **petmint-28** 약관 시행일과 종료일을 청크 메타에서 조회해 고객 카드에 띄우기 (2026-11-19)
  언제: 정하지 않음. `doc_id`로 조회한다. 코드가 없다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/10_consultation_flow.md` 옛 6절
- **petmint-29** 「받기」 버튼 대비가 4.5:1에 못 미침 (2026-11-19)
  언제: 정하지 않음. 한 단계 더 어둡게 하거나 버튼용과 링용 값을 나눈다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/11_design_system.md` 옛 2절
- **petmint-30** 완주대둔산체 공공누리 1유형 출처 표시가 화면에 없음 (2026-11-19)
  언제: 정하지 않음. 1유형은 출처 표시가 조건인데 지금은 CSS 주석에만 있다 [code:web/src/styles/global.css:13]
  나온 곳: 문서 정리 B단계 사람 지시(2026-11-19), `docs/02_pipeline/11_design_system.md`
- **petmint-31** 이웃 청크가 답에 기여하는 비율 재기 (2026-11-19)
  언제: 정하지 않음. 노이즈 비용과 견줘 넣을지 정한다. 08번 Ragas Context Precision과 Recall로 잴 수 있다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/04_rag_assembly.md` 옛 10절
- **petmint-32** 04번이 못 뽑는 법령 박스 (2026-11-19)
  언제: 정하지 않음. 03-1은 박스로 보는데 04번이 못 뽑는 것이 종별 3건 남았다. 03b 표의 `inline_law_*` 줄(박스가 다른 조각 6건, 정규식 차이 3건)도 같은 갈래다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/04_rag_assembly.md` 2-5절, `docs/02_pipeline/03b_reference_graph.md` 1-3절
- **petmint-33** 06 needs_review 표시 약 735건 안에 추정 오류 약 300건이 다 드는지 확인 (2026-11-19)
  언제: 정하지 않음
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/06_quality_check.md` 옛 3-3절
- **petmint-34** 06 심판 수치를 지금 파이프라인 전량으로 다시 재기 (2026-11-19)
  언제: 정하지 않음. 정답지 1, 2회차는 문제 41%, 3회차는 25%였다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/06_quality_check.md` 옛 11절
- **petmint-35** 06 flag 330건(review_queue) 사람 처리 (2026-11-19)
  언제: 정하지 않음
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/06_quality_check.md` 옛 11절
- **petmint-36** 06 단위 상한이 원문 길이만 봄 (2026-11-19)
  언제: 정하지 않음. 상한에 걸린 131개 단위 중 19개가 답의 절반 이상을 외부 참조에 기댔다(2026-10-13) [code:KNOWN_ISSUES.md:289]
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/06_quality_check.md` 옛 8절, 옛 11절
- **petmint-37** 06 안내류와 별표의 잔여율이 낮은(20~32%) 원인 확인 (2026-11-19)
  언제: 정하지 않음
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/06_quality_check.md` 옛 11절
- **petmint-38** Prometheus가 한 대라 노드 drain 때 멈춤 (2026-11-19)
  언제: 정하지 않음
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/15_monitoring.md` 옛 4절
- **petmint-39** search-service와 model-service가 답하는지 모니터링이 보지 못함 (2026-11-19)
  언제: 정하지 않음. Ollama는 json-exporter로 본다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/15_monitoring.md` 옛 4절
- **petmint-40** 앱 `/metrics`가 없음 (2026-11-19)
  언제: 정하지 않음
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/15_monitoring.md` 옛 4절
- **petmint-41** 같은 사실을 두 코드 답 규칙이 각자 만듦 (2026-11-19)
  언제: 정하지 않음. 대기기간 줄을 notes와 ⑫, ⑬이 각자 만든다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/16_code_answers.md` 옛 3-2절
- **petmint-42** 코드 답 충돌 탐침을 운영 로그로 다시 보기 (2026-11-19)
  언제: 정하지 않음. 지금 탐침은 세션이 만든 질문이다. ⑩을 ④ 앞으로 옮기는 안도 그때 잰다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/16_code_answers.md` 옛 3-2절, 4-1절 표
- **petmint-43** 질문이 아닌 한 마디(「초코 입원했는데」)를 어느 규칙도 받지 않음 (2026-11-19)
  언제: 정하지 않음
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/16_code_answers.md` 옛 3-3절
- **petmint-44** app 노드가 둘이라 하나가 빠지면 두 번째 Pod가 Pending (2026-11-19)
  언제: 정하지 않음
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/14_deployment.md` 옛 4절
- **petmint-45** 단일 장애점이 노드마다 흩어짐 (2026-11-19)
  언제: 정하지 않음. 노드 하나가 죽으면 그 노드의 서비스가 멈춘다(MySQL Primary w1, Harbor와 Jenkins와 ArgoCD w3, 모니터링 w4)
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/14_deployment.md` 옛 4절
- **petmint-46** 08번 Ragas 본 평가 (2026-11-19)
  언제: 정하지 않음. 파일럿 1회(2026-10-18) 뒤 멈춰 있다. Context Recall을 보려면 필요하다. 08번 2-1절 「지금 값은 다시 재야 한다」 검색 지표도 함께 잰다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/14_deployment.md` 옛 「다음에 할 일」, `docs/02_pipeline/08_ragas_eval.md` 2-1절
- **petmint-47** 노트북 01의 정규식이 두 셀에 다르게 정의됨 (2026-11-19)
  언제: 정하지 않음. 셀 3과 셀 5에 `ARTICLE_HEADER`, `find_article_headers`, `PARAGRAPH_MARKER`, `split_into_paragraphs`가 두 번 있고 정규식이 다르다. 지금 도는 것은 셀 5다 [c:12a4e2b]
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/01_preprocessing.md` 옛 4절
- **petmint-48** 임베딩 모델 양자화 (2026-11-19)
  언제: 정하지 않음. 임베딩 모델(KURE-v1)을 양자화할지 본다. 문서에 까닭이나 계획이 없다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/pipeline.md` 9절(vLLM 줄에 함께 있었다)
- **petmint-49** 동시 접속 검증 (2026-11-19)
  언제: 정하지 않음. 운영에서 세션 셋이 동시에 질문해도 수신이 막히지 않고 토큰이 섞이지 않는지 확인한다. 체크 항목은 09번 5절에 있다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/requirements.md` 상태 줄과 비기능 「동시성」 줄
- **petmint-50** `OLLAMA_NUM_PARALLEL` 정하기 (2026-11-19)
  언제: 정하지 않음. VRAM 예산을 재면서 GPU 추론 동시 처리 수를 정한다. 지금은 설정이 없어 Ollama 기본값을 따른다(2026-11-19 `docker inspect ollama`로 잼). petmint-26과 함께 본다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/requirements.md` 비기능 「동시성」 줄, `docs/02_pipeline/09_ui_design.md` 1-15절
- **petmint-51** 계산 카드를 `calculate_payout`에서 하루 단위 계산으로 바꾼 까닭 찾아 적기 (2026-11-19)
  언제: 정하지 않음. docs에서 까닭을 찾지 못해 07번에 적지 않았다
  나온 곳: 문서 정리 B단계 사람 지시(2026-11-19), `docs/02_pipeline/07_finetuning.md`
- **petmint-52** 단계 문서 0절 「한 줄 요약」 새로 쓰기 (2026-11-19)
  언제: 정하지 않음. B단계에서 0절에 옛 「목표」, 「전제」, 「도메인 배경」 본문을 그대로 옮겼다. 요약 문장은 새로 쓰지 않았다
  나온 곳: 문서 정리 B단계 사람 지시(2026-11-19)
- **petmint-53** 참조 그래프 검증의 청크 수가 기록과 하나 다름 (2026-11-19)
  언제: 정하지 않음. 지금 레코드를 세면 1,778(928 + 850), 검증 기록은 1,779다. 왜 다른지 모른다. 지금 레코드로 검증을 다시 돌려 차이 0건을 확인한다 [code:KNOWN_ISSUES.md:105]
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/03b_reference_graph.md` 1-1절
- **petmint-54** 운영 DB 백업의 바깥 사본 만들기 (2026-11-19)
  언제: 정하지 않음. 백업과 MySQL PVC가 같은 호스트 NVMe에 있어 디스크 고장에 못 버틴다. 같은 디스크에 있다는 것은 조건이고, 바깥 사본이 없다는 것은 할 일이다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/12_data_storage.md` 4절
- **petmint-55** 웹훅 Bypass 경로를 WAF 규칙으로 좁히기 (2026-11-19)
  언제: 정하지 않음. Cloudflare 경로 일치가 하위 경로를 포함하고 대소문자를 가리지 않으니 정확한 경로의 POST만 남긴다(선택, 미적용)
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/13_access_and_tunnel.md` 1-3절
- **petmint-56** Ragas 평가: partial 10, flawed 2 문항 처리와 집계 방식 정하기 (2026-11-19)
  언제: 08번 본 평가 전(petmint-46). 제안 A는 answerable 85문항으로 집계하고 partial과 flawed는 따로 표에 둔다(answer_eval, ckpt_select와 같은 처리). 제안 B는 97문항 전체로 집계하고 표시만 한다. 라벨은 `data/eval/answer_eval_labels.json` [code:data/ckpt_select.py:9]
  나온 곳: 문서 정리 B단계 사람 지시(2026-11-19), `docs/02_pipeline/08_ragas_eval.md` 옛 4-1, 4-2절
- **petmint-57** Ragas 평가: answer_relevancy 임베딩 정하기 (2026-11-19)
  언제: 08번 본 평가 전. KURE-v1을 `~/ragas_env`에 sentence-transformers와 torch를 더해 쓸지(무겁다), 공용 model-service `/embed`를 부를지, Ollama 임베딩 모델을 새로 받을지 [code:data/model_client.py:3] [code:data/model_client.py:36]
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/08_ragas_eval.md` 옛 4-1절
- **petmint-58** Ragas 평가: 생성 온도 정하기 (2026-11-19)
  언제: 08번 본 평가 전. 서비스는 Modelfile 값(tri-7b 0.3)을 따른다. 평가 재현을 위해 0으로 고정할지 정한다 [c:3f49bb5]
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/08_ragas_eval.md` 옛 4-1절
- **petmint-59** Ragas 평가: RAG 없음 조합의 입력 정하기 (2026-11-19)
  언제: 08번 본 평가 전. 질문만 보낼지, `build_messages(question, [])`로 "(검색된 발췌 없음)"을 넣을지 정한다 [code:data/prompts.py:63]
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/08_ragas_eval.md` 옛 4-1절
- **petmint-60** Ragas 평가: RAG 조합의 발췌 조립 정하기 (2026-11-19)
  언제: 08번 본 평가 전. 서비스와 answer_eval `--search`는 `build_full_context`(참조 조문 포함)를 쓰고, 예전 `search_with_graph`(참조 없음)는 `--search-legacy`로만 남았다. 어느 쪽을 쓸지 정한다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/08_ragas_eval.md` 옛 4-1절
- **petmint-61** Ragas 평가: 목표치 정하기 (2026-11-19)
  언제: 08번 파일럿 뒤. faithfulness, answer_relevancy의 우리 목표(08번 1-1절 표)를 정한다
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/08_ragas_eval.md` 옛 4-1절
- **petmint-62** Ragas 평가: no_answer 20문항을 생성 평가에 넣을지 정하기 (2026-11-19)
  언제: 08번 본 평가 전. 넣으면 거절률 비교가 늘고 생성 횟수가 388회에서 468회가 된다 [code:data/answer_eval.py:30] [code:data/answer_eval.py:200]
  나온 곳: 문서 정리 B단계(2026-11-19), `docs/02_pipeline/08_ragas_eval.md` 옛 4-1절

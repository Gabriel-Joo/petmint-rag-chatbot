<!--
다루는 곳: app/services/followup.py, deploy/host/petmint-search.service, README.md, deploy/README.md
읽은 커밋: 6710b83
-->
# 나중에 할 일 (정해 두고 미룬 것)

대화에서 "나중에 하자"고 정한 것만 적는다. 끝나면 이 표에서 뺀다.

꼴과 번호: 항목은 `- **petmint-N** 제목 (올린 날)`, 다음 줄에 언제와 조건, 그다음 줄에 나온 곳을 쓴다. 번호는 한 번 쓰면 다시 쓰지 않고 끝난 항목은 지운다. 올린 날은 그 줄이 이 파일에 처음 적힌 커밋의 날이다(2026-11-19 표에서 옮기며 셈, FOREMAN `docs/TODO.md`와 같은 꼴). 번호는 옮기기 전 표의 줄 차례다.

- **petmint-1** 후속 질문 판별에 LLM 얹기 (2026-11-10)
  언제: 정하지 않음. 규칙(지시어·생략 꼬리·금액만·8자 이하)이 놓치는 후속 질문이 거슬릴 때만. 지금은 규칙만 쓴다 [code:app/services/followup.py]
  나온 곳: 사람 말 10-21 06:50("놓치는 게 거슬리면 나중에 LLM을 얹는다") · `docs/02_pipeline/09_ui_design.md` 5절 [c:be32dca]
- **petmint-2** 노션 「인프라 > 쿠버네티스 설치」의 낡은 문장 고치기 (2026-11-10)
  언제: 정하지 않음. 사람이 노션에서 직접 고친다. 이 페이지는 docs→Notion 자동 반영 대상(20개) 밖이다
  나온 곳: 사람 말 11-09 11:02("나중에 따로 고칠게") [c:be32dca]
- **petmint-3** 포트폴리오 쪽 정리(보여줄 문서 · 영상 · 구조 설명) (2026-11-10)
  언제: 정하지 않음. 사람이 시작을 말할 때. 저장소 루트 README는 11-10에 썼다 — 남은 것은 포트폴리오 쪽 정리다
  나온 곳: 사람 말 11-10 09:14("포트폴리오는 나중에 한다") · 루트 README 11-10 [c:ae76968]
- **petmint-4** README 「돌리는 법」 명령을 실제로 따라 해 보기 — `db.bootstrap` · `npm ci && npm run dev` 포함 (2026-11-10)
  언제: 정하지 않음. 11-10 작성 당시 명령은 파일만 보고 옮겼고 돌려보지 않았다
  나온 곳: 루트 README 11-10(1f85f98) [c:fff6bba]
- **petmint-5** 압축 손실 점검 #2 결과 보고 되살릴 것 정하기 — 세션 대화가 압축되며 문서에 안 남은 결정을 기계로 찾은 결과(사라짐 93 · 약해짐 38 · 뒤집힘 16 · 살아 있음 42 · 끝남 81) (2026-11-15)
  언제: 펫퍼민트를 다시 만질 때. 사람이 결과를 보고 정한다. 결과는 FOREMAN에 있다 — 점검 #2(세션 155), FOREMAN `log/cross_paste_20261109.md` 3절. 11-09 커밋 1cf1479가 결정 11개를 되살렸지만 이 점검 결과를 보고 한 것인지는 확인되지 않는다
  나온 곳: 사람 말 11-09("펫퍼민트 손실 결과는 나중에 볼게. 지금 그 프로젝트 안 건드리니까") · FOREMAN README 「나중에 할 일」에서 옮김(11-15 사용자 지시, FOREMAN 관리자 전달) [c:aea5a6f]
- **petmint-6** 노션 기술문서 일곱 쪽(09, 11~16) 덮기를 FOREMAN 관리자에게 알리기 — 덮은 뒤 일곱 쪽이 다시 「사람 수정으로 멈춤」으로 서는지 보고 사람에게 알린다 (2026-11-19)
  언제: 펫퍼민트 docs를 다시 쓴 뒤. 지금은 FOREMAN 서기실에 일곱 쪽이 「사람 수정으로 멈춤」으로 뜬다. 고장이 아니라 미룬 상태다. 일곱 쪽 모두 노션에만 있는 글자는 없었다(11-19 글자 단위 비교)
  나온 곳: FOREMAN 사용자 결정 11-19(FOREMAN 관리자 전달, 「docs를 다시 쓴 뒤 덮습니다」) · 사람 말 11-19(「덮은 뒤 일곱 쪽이 다시 「사람이 고침」으로 멈추는지 보고 알려 주세요. 멈추면 덮기로 풀리는 문제가 아닙니다」) [c:68ed76d]
- **petmint-7** 이 파일을 FOREMAN 번호 꼴로 바꾸기 — `- **petmint-N** 제목 (YYYY-MM-DD)`, 다음 줄 본문, 「나온 곳:」 줄. 지금 표의 줄도 모두 옮긴다 (2026-11-19)
  언제: 펫퍼민트 docs를 다시 쓸 때 함께. 꼴은 FOREMAN `docs/TODO.md`를 따른다. 접두어는 `petmint`. 표인 동안은 FOREMAN 포스트잇 [TODO로] 단추가 번호를 못 붙여 거부된다
  나온 곳: FOREMAN 사용자 결정 11-19(FOREMAN 관리자 전달) · 사람 말 11-19(「접두어는 petmint로 두세요」) [c:68ed76d]
- **petmint-8** 재부팅 순서 확인 — `model-service` → Milvus 대기 → `petmint-search`가 순서대로 뜨는지, model-service가 늦거나 Restart될 때 petmint-search가 기다리는지, virbr0가 늦을 때 bind 실패 뒤 Restart로 회복하는지 (2026-11-11)
  언제: 다음 서버 재부팅 때. 재부팅은 사람이 정한다(이 세션은 재부팅하지 않는다). 볼 명령은 model-service 런북 8절 [code:deploy/host/petmint-search.service]
  나온 곳: 사람 말 11-11("실제 재부팅 시험은 아직 안 했다") · `docs/02_pipeline/14_deployment.md` 1-26절 [c:26bee9f]
- **petmint-9** 모드 검증의 거절 판정을 운영과 같은 기준으로 (2026-11-19)
  언제: 정하지 않음. 모드 검증(`scripts/verify_modes.py`)은 C안 함수 `data.refusal.refused`를 쓰지 않고 거절 문구 목록 전체로 거절을 가린다. 그래서 맺음말 문구만 있어도 거절로 친다. 운영 집계(`turns.refused`)와 서빙 평가는 C안이라 모드 검증만 기준이 다르다. 일부러 그렇게 둔 것인지는 문서에 없다 [code:scripts/verify_modes.py:93-95]
  나온 곳: 문서 정리 A단계 근거 달기(2026-11-19), `docs/02_pipeline/12_data_storage.md` turns 표, `docs/02_pipeline/15_monitoring.md` 4-1절
- **petmint-10** 대화 기록에 색인 버전이 남지 않음 (2026-11-19)
  언제: 정하지 않음. `INDEX_VERSION`이 "unset" 그대로라 턴 기록의 색인 버전으로 로그를 비교할 수 없다. 주석은 「재색인 때 올린다」이다 [code:app/config.py:80]
  나온 곳: 문서 정리 A단계 근거 달기(2026-11-19), `docs/02_pipeline/09_ui_design.md` 6절
- **petmint-11** 지금 동작보다 뒤처진 코드 주석 (2026-11-19)
  언제: 정하지 않음. 동작은 문서와 같고 주석만 낡았다. `data/faq_rag.py:7` 「그 질문도 되살려 쓴다」(실제로는 `full()`이 되살린 incomplete를 뺀다), `data/answer_eval.py:220` 「answer.fit_to_budget」(실제로는 `prompts.fit_to_budget`), `data/faq_verify.py:4` 「74개 중 19개 오류, 26%」(KNOWN_ISSUES는 고친 검증기로 26/74, 35%. 같은 측정인지 확인 필요), `app/services/article_display.py:4` 「ArticleOut.blocks」(칸 이름은 sections), 같은 파일 8줄 「91.0%」(최종 93.8%), `web/src/styles/tokens.css:1` 「10번 10절」(지금은 11번), 같은 파일 14줄 「전화 전용」(진행 중 상담 표시에도 쓴다), 같은 파일 69줄과 `web/src/styles/global.css:13` 「헤더 로고만 완주대둔산체」(로그인 화면 등 여러 곳에 쓴다), `app/services/answer.py:19` 「아직 없는 것: 부담보 배너」(이미 있다) [code:data/faq_rag.py:7] [code:data/answer_eval.py:220] [code:data/faq_verify.py:4] [code:app/services/article_display.py:4] [code:app/services/article_display.py:8] [code:web/src/styles/tokens.css:1] [code:web/src/styles/tokens.css:14] [code:web/src/styles/tokens.css:69] [code:web/src/styles/global.css:13] [code:app/services/answer.py:19]
  나온 곳: 문서 정리 A단계 근거 달기(2026-11-19), 07, 05, 10, 11, 09편 안 맞음 대조
- **petmint-12** `deploy/README.md`의 배포 흐름이 옛 그대로 (2026-11-19)
  언제: 정하지 않음. 「Jenkins petmint-app (2분 폴링)」, 「사람이 Sync (지금은 수동)」으로 적혀 있다. 지금은 웹훅과 안전망 폴링 15분이고 ArgoCD는 자동 Sync다(2026-11-11~) [code:deploy/README.md:21] [code:deploy/README.md:23] [code:Jenkinsfile:3] [docs:02_pipeline/14_deployment.md]
  나온 곳: 문서 정리 A단계 근거 달기(2026-11-19), `docs/02_pipeline/14_deployment.md` 1-25절
- **petmint-13** 홈 모드 카드 넘김 화살표의 `font-size: 22px`가 「크기는 새로 만들지 않는다」에 걸리는지 (2026-11-19)
  언제: 정하지 않음. 규칙 원문은 「새 배율 · px을 만들지 않고 이미 있는 글자 크기 토큰만 쓴다」(11번 1절, 2026-11-12)라 새 크기를 막는 뜻과 토큰 밖 값을 막는 뜻이 한 문장에 함께 있어 가를 수 없다. 22px는 같은 날 넘김 화살표를 더한 커밋에서 들어왔고, 글자가 아니라 44px 단추 안 화살표 글리프다 [code:web/src/pages/ModeSelect.module.css:229] [c:f30cf58] [docs:02_pipeline/11_design_system.md:77]
  나온 곳: 문서 정리 A단계 근거 달기(2026-11-19), `docs/02_pipeline/11_design_system.md`

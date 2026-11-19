<!--
다루는 곳: app/, web/, search_service/, data/hr_preprocess.py, data/hr_index.py
읽은 커밋: 6710b83
-->
> 상태: 요구사항 확정. R1~R3 충족, R4 진행 중 — 세 모드 모두 운영 서버에서 답한다: search-service 연결과 업무특화 모델 rebuild4(2026-10-21, 14번 1-4절), 인사규정 색인(hr_regulation 49건, 02번), 앱 로그인과 사내규정 개인화(2026-10-28, 14번 1-11절, `docs/archive/14_deployment_log.md` 1-17절). 남은 것은 동시 접속 검증, 다음 재학습(rebuild5 C안은 두 번 기준 미달로 접음, 07번). [docs:02_pipeline/14_deployment.md:73] [docs:02_pipeline/14_deployment.md:165] [docs:02_pipeline/14_deployment.md:317] [docs:02_pipeline/14_deployment.md:341] [docs:02_pipeline/02_embedding_index.md:1] [docs:02_pipeline/07_finetuning.md:574] [code:app/services/answer.py:183-193] [c:ddfc740] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app/configmap.yaml:26, :30 --> <!-- 2026-11-19 잼: 운영 체험 흐름으로 사내규정 모드에 1회 물어 답이 옴. 업무특화와 일반은 묻지 않아 못 잼 -->

## 프로젝트 한 줄 요약

시나리오: 보험사 상담원이 복잡한 약관 조항을 매번 PDF에서 찾아보는 대신, 사내 RAG 챗봇에 물어보고 근거와 함께 바로 답을 받는다. (구체적으로는 메리츠화재 홈페이지에 공개된 '펫퍼민트' 반려동물 보험 약관을 실제 데이터로 사용했다.) [docs:02_pipeline/01_preprocessing.md] <!-- 확인 못 함: 약관 PDF라 라이선스상 올리지 않음(data/raw_pdf/) -->

## 최종 목표

모델 성능 검증에서 그치지 않고, 실제 서비스로 배포 가능한 수준까지 완성하는 것이다. 사용자가 쓸 수 있는 UI, 여러 사용자가 동시에 접속해도 각 세션의 대화가 서로 섞이지 않도록 격리하는 구조, Kubernetes 기반 배포 인프라까지 전부 프로젝트 범위에 포함했다. [code:web/] [code:app/services/sessions.py] [code:Dockerfile] [docs:02_pipeline/14_deployment.md]

답변의 목표는 **"상담원이 마주치는 변수 조합마다, 그 고객에게 맞는 답을 근거와 함께 준다"**(2026-10-21 사용자 결정)이다. 새 설계는 이 목표에 맞는지로 판단한다. [c:1cf1479]

## 고객 요구사항

- 작업지시서: 사내LLM_최종프로젝트_지시서.docx 기준 <!-- 확인 못 함: 지시서 docx는 과목 자료라 저장소에 두지 않은 문서 -->

### 기능 요구사항 (R1~R4)

| 번호 | 요구사항 | 비고 | 현재 |
| --- | --- | --- | --- |
| R1 | ChatGPT와 유사한 LLM 서비스를 사내에 자체 구축 | 외부 클라우드 LLM 사용 시 데이터 유출 우려 | ✓ Tri-7B 로컬 서빙(GGUF 변환·Ollama 등록), 외부 API 호출 0건. ✓ 일반 모드 답변 생성을 배포 서버에서 확인(2026-10-18). ✓ 업무특화는 search-service와 어댑터 모델 `kabyul-tri-7b-rag1-rebuild4-ckpt462`로 운영(2026-10-21, 14번 1-4절). [code:app/services/llm.py:34] [code:app/config.py:66-71] [code:app/services/answer.py:192-193] [docs:02_pipeline/00_model_setup.md] [docs:02_pipeline/14_deployment.md:73] [c:12a4e2b] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app/configmap.yaml:30 --> |
| R2 | 모바일과 사내 PC 모두에서 채팅 서비스 접속 | 외부 네트워크에서도 접근 가능하게 구성 | ✓ 반응형 + Cloudflare Tunnel + 앱 로그인(`PETMINT_AUTH=app`. Access 정책은 데모 시연을 위해 사용자가 지웠다, 2026-11-09 확인, 13번) [code:web/src/auth/Login.module.css:67] [code:app/config.py:89] [code:app/routers/auth.py:33-44] [docs:02_pipeline/13_access_and_tunnel.md:1] <!-- 확인 못 함: Access 정책은 Cloudflare 대시보드 설정이라 저장소와 서버에서 읽을 수 없음 --> |
| R3 | 사내 규정 등 자사 한정 정보에도 답변 | 범용 모델로는 불가, RAG 필요 | ✓ 인사규정 전처리(청크 49, 그래프 7엣지). ✓ Milvus 색인(hr_regulation 49건)·search-service 운영(02번). ✓ 사내규정 개인화 — 로그인한 직원 본인 연차·퇴직금·급여 등을 인사 원장으로 코드가 답한다(2026-10-28, `docs/archive/14_deployment_log.md` 1-17절) [code:data/hr_preprocess.py] [code:data/hr_index.py] [code:search_service/main.py:119-122] [code:app/services/hr_personal.py:431] [docs:02_pipeline/02_embedding_index.md:1] [docs:02_pipeline/03b_reference_graph.md:76] [docs:02_pipeline/14_deployment.md:341] |
| R4 | 자사 업무에 특화된 LLM 모델 제공 | 범용 모델의 한계, 파인튜닝 필요 | ✓ 파인튜닝 학습. rebuild4가 운영 모델이다(`docs/archive/07_finetuning_log.md` 10절, 07번 3-7절, 14번 1-10절) [docs:02_pipeline/07_finetuning.md:472] [docs:02_pipeline/07_finetuning.md:574] [docs:02_pipeline/14_deployment.md:73] [code:data/finetune_data.py] [code:data/rebuild.py] [code:notebooks/07_파인튜닝.ipynb] |

### 비기능 요구사항

- 보안: 모델·데이터 사내 서버 상주, 외부 유출 0건 원칙 [code:app/config.py:66] [code:app/services/llm.py:34]
- 접근성: 사설망 내부 서버를 외부(모바일)에서도 도메인으로 접속 (Cloudflare Tunnel 이용) [docs:02_pipeline/13_access_and_tunnel.md] <!-- 확인 못 함: 터널 공개 호스트 설정은 Cloudflare 대시보드 설정이라 저장소와 서버에서 읽을 수 없음 -->
- 운영성: 개발은 로컬에서 uvicorn + vite, 배포는 Kubernetes(Deployment + 롤링 업데이트, replicas 2). ArgoCD가 Git을 기준으로 상태를 유지한다 — ✓ 자동 Sync(2026-11-11, 그 전 2026-10-16부터 수동으로 매니페스트 반영을 확인했다) (14번 1-15절) [code:web/package.json] [code:Dockerfile] [code:web/src/components/ArchDiagram.tsx:69] [docs:02_pipeline/14_deployment.md:167] [docs:02_pipeline/14_deployment.md:464] [c:ddfc740] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app/deployment.yaml:17-23, apps/petmint/app.yaml:4-6, :25-28 -->
- 동시성: 여러 사용자 동시 접속은 FastAPI 비동기 처리 + Ollama 자체 큐로 해결 — △ 설계. 생성은 운영에서 돌지만 동시 접속(세션 셋 동시 질문)은 검증 전이다(09번 5절). GPU 추론을 몇 개까지 동시에 돌릴지는 `OLLAMA_NUM_PARALLEL`로 정한다 — △ 설정 전이라 Ollama 기본값을 따른다. VRAM 예산을 재면서 함께 정한다(09번 1-15절). [code:app/routers/chat_ws.py:54] [docs:02_pipeline/09_ui_design.md:632] [docs:02_pipeline/09_ui_design.md:793] <!-- 2026-11-19 잼: docker inspect ollama의 OLLAMA_ 환경변수는 OLLAMA_HOST 하나뿐이고 OLLAMA_NUM_PARALLEL은 없음(Ollama 0.34.0) -->

## UI 설계 방향: 3탭 구조

- 일반: Tri-7B 원본, 파인튜닝 없음 (R1 — 사내 자체 LLM 구축 충족) [code:app/services/answer.py:183-193]
- 업무특화: Tri-7B 파인튜닝 + RAG (R4 — 업무 특화 모델 충족) [code:app/services/answer.py:183-193]
- 사내규정: Tri-7B 원본 + RAG (R3 — 사내 전용 정보 응답 충족) [code:app/services/answer.py:183-193]

같은 베이스(Tri-7B) 모델 하나로, 탭마다 파인튜닝·RAG 적용 여부를 조합해 서빙한다 — ✓ 세 탭 모두 운영에서 답한다 — 업무특화는 rebuild4 + 약관 RAG, 사내규정은 원본 + 인사규정 RAG(2026-10-21 search-service 연결). 반려동물의 종은 검색 단계에서부터 고정한다 — 고객 조회로 반려동물을 고르면 그 개체의 종이 따라온다(여러 마리면 개체 선택). 모델이 종을 스스로 추론할 필요가 없어, 강아지/고양이 약관이 서로 섞여 검색될 위험을 원천 차단한다. [code:app/services/answer.py:183-193] [code:app/services/customers.py:64-66] [code:search_service/main.py] [c:12a4e2b]

화면 설계는 09번, 상담원의 업무 흐름은 10번, 색·글꼴·캐릭터는 11번 문서다. [docs:02_pipeline/09_ui_design.md] [docs:02_pipeline/10_consultation_flow.md] [docs:02_pipeline/11_design_system.md]
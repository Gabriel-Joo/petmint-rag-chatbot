<!--
다루는 곳: .foreman/docs.toml
읽은 커밋: 6710b83
-->
# docs/

이 폴더에는 성격이 다른 두 종류의 문서가 있다. 섞지 않는다.

폴더 구조는 노션과 같다(2026-11-09). 노션 「02. 파이프라인 설계」 아래 단계 문서는 `02_pipeline/`에, 상위 문서 둘은 이 폴더 바로 아래에 둔다. 운영 기록, 체크리스트는 `ops/`에 둔다. 그림은 `img/`. [docs:02_pipeline/00_model_setup.md] [docs:ops/모드검증.md] [docs:img/01_preprocessing_20261007.png] [c:5409464] <!-- 확인 못 함: 노션 페이지 구조는 Notion 쪽이라 저장소와 서버에서 읽을 수 없음 -->

## 파일 이름 규칙

- **숫자가 있으면 파이프라인 단계 문서**다(`07_finetuning.md`, `09_*.md` ~ `16_*.md`). 번호는 노션의 단계 번호를 따른다(예: 15 = 모니터링). 이 폴더에서 번호를 새로 매기지 않는다. [docs:02_pipeline/07_finetuning.md] [docs:02_pipeline/15_monitoring.md] [c:d833182]
- **숫자가 없으면 상위 문서이거나 작업 문서**다.
  - 상위 문서: `requirements.md`(노션 01: 요구사항), `pipeline.md`(노션 02: 파이프라인, 아키텍처). [docs:requirements.md] [docs:pipeline.md]
    노션에서 02는 단계 문서들을 품는 상위 페이지라, 단계 문서와 같은 줄에 번호를 붙이면 헷갈린다. 그래서 상위 문서는 번호를 떼고 이름만 쓴다.
  - 작업 문서: 아래 2절의 표에 있는 것.

상위 문서 둘도 설계 문서다(1절). 어느 쪽인지는 아래 1, 2절의 목록으로 가린다.

## 1. 설계 문서: 저장소가 원천, 노션은 사본

| 파일 | 노션 |
|---|---|
| `requirements.md` | 01: 요구사항 |
| `pipeline.md` | 02: 파이프라인, 아키텍처(상위 페이지) |
| `02_pipeline/00_*.md` ~ `02_pipeline/16_*.md` | 각 단계 문서(02의 하위 페이지) [docs:02_pipeline/00_model_setup.md] [docs:02_pipeline/16_code_answers.md] |

**원천은 이 폴더다(2026-10-18부터).** 노션은 이 파일들을 옮겨 둔 사본이다. [c:0ea05cc]

- 설계가 바뀌면 이 파일들을 저장소에서 직접 고친다.
- 고친 뒤에는 **무엇을 고쳤는지(파일, 절, 바뀐 내용) 알린다.**
- 노션에서 다시 내보내 이 파일들을 덮어쓰지 않는다. 노션에서만 고친 것은 이 폴더로 옮긴다.

**노션 반영은 FOREMAN이 한다(2026-11-09부터). 2026-11-19부터는 멈춰 있다.** 게시 설정은 이 저장소 `.foreman/notion.toml`이 정하고, 지금 `docs = "manual"`이라 서기실에서 [Notion에 올리기]를 눌러야 올라간다. 원고 폴더를 `notion/`으로 바꿀 때까지 멈춘다(문서에 단 머리 주석과 근거 표시를 게시기가 떼는 것은 `notion/` 아래 원고일 때뿐이다). 자동(`auto`)일 때는 push 뒤 30분 조용하면 바뀐 파일의 바뀐 블록만 노션 사본에 옮긴다. 짝이 있는 페이지의 제목은 바꾸지 않고, 짝 없는 문서는 새 페이지로 만든다(같은 폴더 형제의 부모 아래, 제목은 「00. 모델 준비」 꼴). 올릴 때마다 맨 아래 회색 "마지막 갱신" 줄을 고친다. [c:756df4d] [c:39d2d6b] <!-- FOREMAN 저장소 근거(d2d0607 판, 2026-11-19 FOREMAN 관리자 답): 자동 게시 bridge/docsync.py 299~304, 블록 비교 bridge/notion.py _publish_shape 1429와 shape_patch 717, 새 페이지 bridge/notion.py 1094와 1152~1176, 제목 유지 _publish_one 1359, 갱신 줄 footer_block 587 -->

- **대상**: 원고 폴더(지금 `docs/`) 아래 `.md`에서 `.foreman/notion.toml`의 `skip`을 뺀 나머지다. 지금 `skip`은 이 `README.md`, `next_rebuild.md`, `ops/`이다. 원고 폴더 아래 `archive/`는 늘 뺀다. [c:39d2d6b] [c:756df4d] <!-- FOREMAN 저장소 근거(d2d0607 판, 2026-11-19 FOREMAN 관리자 답): skip 칸 뜻 bridge/notioncfg.py 48, 거르는 곳 bridge/docsync.py skipped 54 -->
- **노션 모양을 그대로 두는 예외**: 제목 단계, 인라인 코드와 업로드 이미지, 글자는 같고 모양만 다른 블록. 이것들은 git과 달라도 덮어쓰지 않는다. 모양만 다른 블록은 쪽 단위로 꾸밈 표시, 체크박스 표시, 공백, 줄바꿈을 뺀 글만 견줘 가린다. [c:39d2d6b] [c:756df4d] <!-- FOREMAN 저장소 근거(d2d0607 판, 2026-11-19 FOREMAN 관리자 답): keep_notion 처리 bridge/notion.py adopt_notion_shape 605(인라인 코드 610, 제목 단계 625, 그림 638), shape 비교 665와 shape_text 701 -->
- **짝은 경로로 맺는다.** 파일을 옮기거나 이름을 바꾸면 노션 페이지와 짝이 끊긴다. `git mv`, 이름 변경은 FOREMAN과 먼저 맞춘다. 이름을 바꾸면 새 경로는 짝 없는 문서라 새 페이지가 생기고, 옛 페이지는 휴지통으로 가지 않고 짝 없이 남는다(`archive = false`). [c:39d2d6b] [c:756df4d] <!-- FOREMAN 저장소 근거(2026-11-19 FOREMAN 관리자 답): 짝은 FOREMAN DB doc_publish 의 (프로젝트, 경로) -->
- **노션을 직접 고칠 때는 글자가 git과 같아야 한다.** 다르면 FOREMAN이 사람이 고친 페이지로 보고 그 페이지 반영을 멈춘다. 멈춘 페이지는 덮어쓰지 않고 텔레그램과 서기실 「할 일」로 알리며, 사람이 서기실 [Notion 수정 버리고 덮기]를 눌러야 덮는다. **사람이 노션을 고치지 않아도 같은 꼴로 멈출 수 있다.** git에서 바뀐 곳에 표, 그림, 안쪽 목록이 있거나 git 맨 앞에 블록이 새로 생기면 게시기가 그 페이지를 고치지 못해 「사람이 고침」과 같은 꼴로 멈춘다. 멈춘 편을 보면 노션을 고쳤는지보다 이것을 먼저 의심한다. FOREMAN의 알려진 고장이고 FOREMAN TODO foreman-121에 있다. [c:756df4d] <!-- FOREMAN 저장소 근거(d2d0607 판, 2026-11-19 FOREMAN 관리자 답): 사람 고침 판정 bridge/notion.py class HumanEdited 49와 _publish_shape 1429, 표와 그림과 안쪽 목록 746, 맨 앞 블록 756, 알림과 덮기 단추 bridge/docsync.py -->

## 2. 작업 문서: 저장소에만 있다

노션에 옮기지 않고 이 폴더에만 있는 문서다.

- 번호를 붙이지 않는다(단계 문서 번호 체계 밖).
- 측정, 작업 계획, 지시서처럼 진행 중인 작업을 위한 문서다.

| 파일 | 내용 |
|---|---|
| `next_rebuild.md` | 다음 FAQ, 파인튜닝 재구축 지시서 [docs:next_rebuild.md] |
| `archive/` | 기록 폴더(B단계에서 떼어 낸 구현 기록과 처음 설계) |
| `TODO.md` | 나중에 할 일: 정해 두고 미룬 것(무엇, 언제, 조건, 근거) [docs:TODO.md] [c:be32dca] |
| `ops/저녁실행.md` | rebuild3 뒤 실행 순서서(명령, 시간, 성공, 실패, 건너뛰면) [docs:ops/저녁실행.md] [c:5409464] |
| `ops/배포기록.md` | 배포, 알림 시험처럼 코드 변경 없이 배포를 일으킨 커밋의 기록 [docs:ops/배포기록.md] [c:98f785b] |
| `ops/모드검증.md` | 일반, 사내규정, 업무특화 모드 검증 체크리스트(질문과 정답은 `scripts/verify_modes.py`, `scripts/verify_cases.py`와 같다) [docs:ops/모드검증.md] [c:5409464] [code:scripts/verify_modes.py:31] [code:scripts/verify_modes.py:271-280] [code:scripts/verify_cases.py] |

측정 기록과 검수 결과는 `docs/`가 아니라 `data/review/`에 둔다. [code:data/review/]

`data/review/`에서 git에 올리는 것은 **근거**다: 사람이 읽고 판단을 적은 기록(측정 메모, 판정, 비교, 조사), 그리고 설계 문서(1절)나 코드가 인용하는 파일. 작업 문서(`ops/`, `next_rebuild.md`)만 인용하는 실행 결과는 올리지 않는다. 실패한 실험도 근거다(`pipeline.md` 6절). 체크포인트마다 기계가 낸 **원자료**(같은 명령을 다시 돌리면 다시 나오고 아무도 인용하지 않는 평가, 검수 출력)는 올리지 않는다. `data/eval/results/`를 무시하는 것과 같다. 원자료를 문서에서 인용하게 되면 그때 올린다(2026-11-11 사용자 결정. 그 전 기록은 기능 커밋에 그때그때 실렸고, 10-16 저녁부터 체크포인트별 answer_eval 출력은 올리지 않았다). [code:data/review/] [code:.gitignore] [c:47d4b0d]

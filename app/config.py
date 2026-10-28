"""
config.py
09 UI 서버 설정 — 모델명·경로·접속 정보. 값만 둔다(로직 없음).
접속 정보는 전부 환경변수다(12번 1-2절) — 개발은 리포 루트 .env, 배포는 K8s Secret. db/conn.py가 .env를 읽는다.
"""

import os
from pathlib import Path

from data.prompts import PROMPT_VERSION
from db.conn import app_settings

ROOT = Path(__file__).resolve().parent.parent

# 고객 원장 — 보험사 기간계(insurance_core)를 읽기만 한다. 다른 데이터베이스라 petmint에서 외래키를 걸지 않는다(12번 4절).
# app/fixtures/customers.json은 시드일 뿐 앱이 읽지 않는다(db/seed_insurance_core.py가 적재)
CORE_DB = app_settings("petmint_core")         # PETMINT_CORE_DB_HOST / _PORT / _NAME / _USER / _PASSWORD (SELECT만)

# 약관 청크·참조 그래프 — 런타임에 읽는다. 이미지·git에 넣지 않는다(01번 "외부 유출 0건"). 컨테이너는 볼륨으로 붙인다
CHUNKS_DIR = Path(os.environ.get("PETMINT_CHUNKS_DIR", ROOT / "data" / "chunks"))
GRAPH_DIR = Path(os.environ.get("PETMINT_GRAPH_DIR", ROOT / "data" / "graph"))

# React 빌드물(web/dist) — 있으면 FastAPI가 같은 포트에서 / 로 서빙한다(09번 8절). 컨테이너는 1단계 빌드 산출물을 여기 둔다
WEB_DIST = Path(os.environ.get("PETMINT_WEB_DIST", ROOT / "web" / "dist"))

DB = app_settings("petmint")                   # PETMINT_DB_HOST / _PORT / _NAME / _USER / _PASSWORD

WS_CLOSE_UNAUTHORIZED = 4401                   # 로그인 안 됨·만료(PETMINT_AUTH=app) — 로그인 화면으로
WS_CLOSE_FORBIDDEN_ORIGIN = 4403               # 다른 사이트에서 연 WS
WS_CLOSE_SESSION_NOT_FOUND = 4404              # 없는·종료된·남의 세션. 업무특화는 고객 조회로, 일반·사내규정은 새 대화로

# 7-3: GPU 쓰는 것은 호스트에 두고 네트워크로 호출한다. Pod에서는 호스트 주소로 바꿔 준다(기본값은 호스트에서 직접 띄울 때)
SEARCH_SERVICE_URL = os.environ.get("PETMINT_SEARCH_URL", "http://localhost:8100")
SEARCH_EXPAND = os.environ.get("PETMINT_SEARCH_EXPAND", "0") == "1"      # 질의 확장(data/query_expansion.py) — 기본 끔
SEARCH_EXPAND_DICT = os.environ.get("PETMINT_EXPAND_DICT") or None     # 질의 확장 사전 판(v1·v2) — 기본 search-service 기본(v1)
ANSWER_TABLES = os.environ.get("PETMINT_ANSWER_TABLES", "0") == "1"   # 답이 쓴 발췌의 표를 답 아래에(app/services/tables.py) — 기본 끔
SEARCH_POOL = int(os.environ.get("PETMINT_SEARCH_POOL", "0")) or None      # 1차 후보 깊이(search-service pool_k) — 기본 candidate_k
SEARCH_VARIANT = os.environ.get("PETMINT_SEARCH_VARIANT") or None       # 실험 청크 묶음(data/chunks/<variant>/) — 기본 지금 청크
NUMBER_GUARD = os.environ.get("PETMINT_NUMBER_GUARD", "1") == "1"       # 숫자 가드레일(guardrail.py) — 업무특화 모델 답
# 6단계 B 조건: 작은 조각(청크 v2)으로 찾고 모델에게는 부모 청크를 보여준다 — 실험용, 기본 끔
DISPLAY_PARENT = os.environ.get("PETMINT_DISPLAY_PARENT", "0") == "1"
# 2026-10-23 1안: 지급사유 조항의 예외 항이 발췌 본문이면 같은 조 제1항(원칙)을 참조에서 본문 앞으로 옮긴다(answer.rule_first) — 기본 끔
RULE_FIRST = os.environ.get("PETMINT_RULE_FIRST", "0") == "1"
# 2026-10-23 3안′: 보장 여부 질문이 그 반려동물 부담보에 걸리면 모델 대신 코드가 답한다(customer_facts.exclusion_answer) — 기본 끔
COVERAGE_CODE = os.environ.get("PETMINT_COVERAGE_CODE", "0") == "1"
# 2026-10-24: 신규 가입 나이를 숫자로 묻는 질문은 코드가 약관 기준(만 8세, 실속형 만 10세)과 비교해 답한다(customer_facts.enrollment_age_answer) — 기본 끔
AGE_CODE = os.environ.get("PETMINT_AGE_CODE", "0") == "1"
# 2026-10-24: 면책 단서가 보장 쪽으로 빼 주는 경우(⑫ 침술 · ② 1년 이내 예방접종 · ⑲ 치아 외 구강질환)는 코드가 답한다(customer_facts.proviso_answer) — 기본 끔
PROVISO_CODE = os.environ.get("PETMINT_PROVISO_CODE", "0") == "1"
# 2026-10-28 업무특화 검색에서 보통약관(사람 상해보험) 제3·4·5조 낮추기 / 같은 제목 의료비 특약 조 올리기 — 기본 끔
HUMAN_DEMOTE = os.environ.get("PETMINT_HUMAN_DEMOTE", "0") == "1"
TWIN_ARTICLE = os.environ.get("PETMINT_TWIN_ARTICLE", "0") == "1"
# 2026-10-28 사내규정 개인화: 상담원 본인의 연차 잔여·퇴직금·자격수당·승진 시점은 인사 원장으로 코드가 답한다(hr_personal) — 기본 끔
HR_PERSONAL = os.environ.get("PETMINT_HR_PERSONAL", "0") == "1"
# 2026-10-28 병명 없이 보장을 묻는 업무특화 질문은 코드가 원칙 + 병명 되묻기로 답한다(customer_facts.disease_ask) — 기본 끔
ASK_DISEASE = os.environ.get("PETMINT_ASK_DISEASE", "0") == "1"
# 2026-10-28 B안: 병명 되묻기 ⑤(병명·증상 이름이 있는가)를 베이스 모델로 본다(name_check). 실패하면 정규식으로 — 기본 끔
ASK_DISEASE_LLM = os.environ.get("PETMINT_ASK_DISEASE_LLM", "0") == "1"
# 병명이 있는 보장 질문(2026-10-29) — 그 반려동물 의료비 특약 제2조 면책 목록과 대조해 코드가 답한다(named_cover). 금액 되묻기 뒤
# "감기도 돼요?"처럼 다른 것을 물으면 금액 되묻기를 되풀이하지 않는다
NAMED_COVER = os.environ.get("PETMINT_NAMED_COVER", "0") == "1"
# 평가 전용: 오늘 날짜를 고정한다(YYYY-MM-DD). 대기기간·보험연도가 날짜에 따라 바뀌어 평가 정답이 날마다 달라졌다 — 평가 220은 기준일 2026-10-21.
# 운영에서는 비워 둔다(실제 날짜)
TODAY = os.environ.get("PETMINT_TODAY") or None
CUSTOMER_FACTS = os.environ.get("PETMINT_CUSTOMER_FACTS", "1") == "1"   # 고객 사실(customer_facts.py)·서버 부담보 대조 — 측정용 스위치
OLLAMA_URL = os.environ.get("PETMINT_OLLAMA_URL", "http://localhost:11434")
MILVUS_URL = os.environ.get("PETMINT_MILVUS_URL", "http://localhost:19530")   # 조항 원문(ContextBuilder) — 행을 Milvus에서 읽는다

# 모드별 모델(9절: 어댑터는 설정값으로 빼 모델만 갈아끼운다). Ollama 모델 이름 — 어댑터를 바꿀 때 이미지를 다시 빌드하지 않는다
BASE_MODEL = os.environ.get("PETMINT_MODEL_BASE", "tri-7b")            # 일반·사내규정 답변 + 업무특화의 질문 재작성기(5절)
FINETUNED_MODEL = os.environ.get("PETMINT_MODEL_RAG", "tri-7b-rag-1")  # 업무특화 답변

# 지난 채팅 제목(10번 2-1절) — 첫 질문을 베이스 모델로 한 번 요약. 끄면(0) 첫 질문 첫 줄을 잘라 쓴다
TITLE_USE_LLM = os.environ.get("PETMINT_TITLE_LLM", "1") == "1"
# 평가용(scripts/eval_serving.py): 설정하면 업무특화·사내규정 턴의 프롬프트를 이 파일에 JSON 한 줄씩 남긴다. 배포에서는 비운다
PROMPT_LOG = os.environ.get("PETMINT_PROMPT_LOG") or None
TITLE_MAX_CHARS = 40
TITLE_TIMEOUT_SEC = 15

INDEX_VERSION = "unset"                        # 로그 비교용(6-3). 재색인 때 올린다
PROMPT_VERSION = PROMPT_VERSION

# 13번: Cloudflare Access가 넣는 헤더 → sessions.agent_email. 로컬 개발에는 없으므로 기본값
AGENT_HEADER = "Cf-Access-Authenticated-User-Email"
DEFAULT_AGENT = os.environ.get("PETMINT_DEFAULT_AGENT", "dev@local")

# 2026-10-28 앱 자체 인증(13번 2-1절). access: 지금처럼 위 헤더(없으면 기본값)가 상담원이다. app: 사번·비밀번호 로그인 쿠키가 있어야 한다.
# 직원 신원은 기간계 insurance_core.employees(CORE_DB, 읽기만), 비밀번호·로그인 세션은 petmint.accounts·auth_sessions
AUTH = os.environ.get("PETMINT_AUTH", "access")
if AUTH not in ("access", "app"):
    raise RuntimeError(f"PETMINT_AUTH는 access 또는 app: {AUTH!r}")
AUTH_COOKIE = "petmint_session"
COOKIE_SECURE = os.environ.get("PETMINT_COOKIE_SECURE", "1") == "1"   # 로컬 http 개발에서만 0
# 상태를 바꾸는 요청·WS 연결의 Origin이 이 목록이나 요청 Host와 같아야 한다(쿠키 인증의 CSRF·WS 위조 방지). 개발 서버(vite)는
# changeOrigin으로 Host를 바꾸므로 목록에 둔다
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "PETMINT_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

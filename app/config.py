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

WS_CLOSE_SESSION_NOT_FOUND = 4404              # 없는·종료된·남의 세션. 업무특화는 고객 조회로, 일반·사내규정은 새 대화로

# 7-3: GPU 쓰는 것은 호스트에 두고 네트워크로 호출한다. Pod에서는 호스트 주소로 바꿔 준다(기본값은 호스트에서 직접 띄울 때)
SEARCH_SERVICE_URL = os.environ.get("PETMINT_SEARCH_URL", "http://localhost:8100")
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

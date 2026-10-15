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

CUSTOMERS_PATH = ROOT / "app" / "fixtures" / "customers.json"

DB = app_settings("petmint")                   # PETMINT_DB_HOST / _PORT / _NAME / _USER / _PASSWORD

WS_CLOSE_SESSION_NOT_FOUND = 4404              # 없는·종료된·남의 세션. 업무특화는 고객 조회로, 일반·사내규정은 새 대화로

# 7-3: GPU 쓰는 것은 호스트에 두고 네트워크로 호출한다
SEARCH_SERVICE_URL = os.environ.get("PETMINT_SEARCH_URL", "http://localhost:8100")
OLLAMA_URL = os.environ.get("PETMINT_OLLAMA_URL", "http://localhost:11434")

# 모드별 모델(9절: 어댑터는 설정값으로 빼 모델만 갈아끼운다). 이름은 GGUF 변환 후 확정
BASE_MODEL = "tri-7b"                          # 일반·사내규정 답변 + 업무특화의 질문 재작성기(5절)
FINETUNED_MODEL = "tri-7b-rag-1"               # 업무특화 답변

# 지난 채팅 제목(10번 2-1절) — 첫 질문을 베이스 모델로 한 번 요약. 끄면(0) 첫 질문 첫 줄을 잘라 쓴다
TITLE_USE_LLM = os.environ.get("PETMINT_TITLE_LLM", "1") == "1"
TITLE_MAX_CHARS = 40
TITLE_TIMEOUT_SEC = 15

INDEX_VERSION = "unset"                        # 로그 비교용(6-3). 재색인 때 올린다
PROMPT_VERSION = PROMPT_VERSION

# 13번: Cloudflare Access가 넣는 헤더 → sessions.agent_email. 로컬 개발에는 없으므로 기본값
AGENT_HEADER = "Cf-Access-Authenticated-User-Email"
DEFAULT_AGENT = os.environ.get("PETMINT_DEFAULT_AGENT", "dev@local")

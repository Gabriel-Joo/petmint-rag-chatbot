# 펫퍼민트 상담 앱 — FastAPI + React 빌드물 한 컨테이너(09번 7-3·8절).
# GPU를 쓰는 Ollama·search-service는 GPU 호스트에 남고, 이 컨테이너가 네트워크로 부른다.
# 접속 정보는 전부 실행할 때 환경변수로 준다(12번 1-2절) — 이미지에 .env를 넣지 않는다(.dockerignore).
# 약관 청크·참조 그래프도 넣지 않는다(01번 "모델·데이터 사내 서버 상주, 외부 유출 0건") — 이미지는 Harbor로 나간다.
# 실행할 때 볼륨으로 붙인다. 없으면 앱이 무엇이 없는지 밝히고 기동을 멈춘다.
#
#   docker build -t petmint-app .
#   docker run -p 8000:8000 --env-file <(접속 정보) \
#     -v <약관>/chunks:/var/lib/petmint/chunks:ro -v <약관>/graph:/var/lib/petmint/graph:ro petmint-app
#   스키마 초기화(Job): docker run --rm <같은 환경변수> petmint-app python -m db.migrate

# ---- 1단계: React 빌드 ----
FROM node:20-alpine AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- 2단계: 앱 ----
FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv/petmint

COPY app/requirements.txt app/requirements.txt
RUN pip install -r app/requirements.txt \
 && useradd --no-log-init --uid 10001 --no-create-home petmint

# 09번 8절 구조 그대로. data/는 앱이 import하는 모듈(.py)만 — 약관 데이터·notebooks/·data/faq/·data/finetune/은 넣지 않는다.
# 파일은 root 소유로 둔다(앱이 코드를 고쳐 쓸 일이 없다). 실행만 비root로
COPY app/ app/
COPY db/ db/
COPY data/*.py data/
COPY --from=web /src/web/dist web/dist

# 약관 데이터 마운트 지점(K8s에서는 PVC). 경로를 바꾸려면 실행할 때 같은 변수를 덮어쓴다
ENV PETMINT_CHUNKS_DIR=/var/lib/petmint/chunks \
    PETMINT_GRAPH_DIR=/var/lib/petmint/graph

USER petmint

EXPOSE 8000
# 세션이 DB에 있으므로 worker를 늘려도 된다(09번 7-3절). 늘리려면 --workers N을 덧붙인다
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

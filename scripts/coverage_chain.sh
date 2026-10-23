#!/bin/bash
# 보장 여부 질문 개선 — 3안′ 측정 → 청크 v4(표 앞 깨진 배치 줄 정리) 만들기·색인 → v4에서 3안′ 측정. 운영 v3는 건드리지 않는다
cd /home/kopo17/AI_programming/petmint-rag-chatbot
L=logs/coverage; mkdir -p $L
log() { echo "[$(date '+%F %T')] $*" | tee -a $L/chain.log; }
log "3안′ 측정"
scripts/coverage_measure.sh a3b PETMINT_RULE_FIRST=1 PETMINT_COVERAGE_CODE=1 > $L/a3b.log 2>&1 || { log "3안′ 실패"; exit 1; }
log "청크 v4 만들기·색인"
PETMINT_CHUNK_VARIANT=v4 python -m data.chunks_v2 build > $L/v4_build.log 2>&1 || { log "v4 build 실패"; exit 1; }
PETMINT_CHUNK_VARIANT=v4 python -m data.chunks_v2 index > $L/v4_index.log 2>&1 || { log "v4 index 실패"; exit 1; }
python -m scripts.search_regression_run --out $L/sr_v4 --expand --variant v4 --dict v2 --compare logs/rollout/sr_v2/search_regression_pet.json > $L/sr_v4.log 2>&1
log "v4에서 3안′ 측정"
scripts/coverage_measure.sh a4 PETMINT_RULE_FIRST=1 PETMINT_COVERAGE_CODE=1 PETMINT_CHUNKS_DIR=data/chunks/v4 PETMINT_GRAPH_DIR=data/graph/v4 PETMINT_SEARCH_VARIANT=v4 > $L/a4.log 2>&1 || { log "v4 측정 실패"; exit 1; }
python -m scripts.coverage_table 기준=$L/base 1안=$L/a1 3안=$L/a3 "3안′"=$L/a3b "3안′+v4"=$L/a4 > $L/table.log 2>&1
log "끝 — data/review/coverage_measure.md"

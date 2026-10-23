#!/bin/bash
# 1차 후보 깊이(pool_k) 20 → 50 측정(2026-10-24) — 검색 회귀 + 3안′(운영 설정) 위에 PETMINT_SEARCH_POOL=50 평가 220 3회
cd /home/kopo17/AI_programming/petmint-rag-chatbot
set -a; . ./.env; set +a
L=logs/coverage; mkdir -p $L
log() { echo "[$(date '+%F %T')] $*" | tee -a $L/pool_chain.log; }
log "검색 회귀 pool 50"
python -m scripts.search_regression_run --out $L/sr_pool50 --expand --variant v3 --dict v2 --pool 50 --compare logs/rollout/sr_v2/search_regression_pet.json > $L/sr_pool50.log 2>&1 || { log "회귀 실패"; exit 1; }
log "평가 pool 50"
scripts/coverage_measure.sh pool50 PETMINT_RULE_FIRST=1 PETMINT_COVERAGE_CODE=1 PETMINT_SEARCH_POOL=50 > $L/pool50.log 2>&1 || { log "평가 실패"; exit 1; }
python -m scripts.coverage_table "3안′"=$L/a3b "pool50"=$L/pool50 --out data/review/pool_measure.md > $L/pool_table.log 2>&1
log "끝 — data/review/pool_measure.md"

#!/bin/bash
# 신규 가입 나이 코드 답 측정(2026-10-24) — 운영 설정(pool 50 포함) 위에 PETMINT_AGE_CODE=1, 평가 220 3회 → pool50과 비교
cd /home/kopo17/AI_programming/petmint-rag-chatbot
L=logs/coverage
log() { echo "[$(date '+%F %T')] $*" | tee -a $L/age_chain.log; }
log "평가 age"
scripts/coverage_measure.sh age PETMINT_RULE_FIRST=1 PETMINT_COVERAGE_CODE=1 PETMINT_SEARCH_POOL=50 PETMINT_AGE_CODE=1 > $L/age.log 2>&1 || { log "평가 실패"; exit 1; }
kill $(ss -ltnp | grep "127.0.0.1:8000" | grep -o "pid=[0-9]*" | cut -d= -f2) 2>/dev/null
python -m scripts.coverage_table "pool50"=$L/pool50 "age"=$L/age --out data/review/age_measure.md > $L/age_table.log 2>&1
log "끝 — data/review/age_measure.md"

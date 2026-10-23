#!/bin/bash
# 면책 단서 코드 답 측정(2026-10-24) — 기준선(운영 설정 + 기준일 고정 + 고친 평가 파일) vs PETMINT_PROVISO_CODE=1, 평가 220 3회 + 탐침 12턴 3회
cd /home/kopo17/AI_programming/petmint-rag-chatbot
L=logs/coverage
log() { echo "[$(date '+%F %T')] $*" | tee -a $L/proviso_chain.log; }
log "기준선"; scripts/prod_measure.sh base2 > $L/base2.log 2>&1 || { log "기준선 실패"; exit 1; }
log "세 안"; scripts/prod_measure.sh proviso PETMINT_PROVISO_CODE=1 > $L/proviso.log 2>&1 || { log "세 안 실패"; exit 1; }
kill $(ss -ltnp | grep "127.0.0.1:8000" | grep -o "pid=[0-9]*" | cut -d= -f2) 2>/dev/null; sleep 2
log "탐침 기준선"; /tmp/claude-1000/-home-kopo17-AI-programming-petmint-rag-chatbot/cddadc68-1f56-45a1-9b98-56d807e8179a/scratchpad/proviso/run.sh base > /dev/null 2>&1
log "탐침 세 안"; /tmp/claude-1000/-home-kopo17-AI-programming-petmint-rag-chatbot/cddadc68-1f56-45a1-9b98-56d807e8179a/scratchpad/proviso/run.sh proviso PETMINT_PROVISO_CODE=1 > /dev/null 2>&1
python -m scripts.coverage_table "기준선"=$L/base2 "세 안"=$L/proviso --out data/review/proviso_measure.md > $L/proviso_table.log 2>&1
log "끝"

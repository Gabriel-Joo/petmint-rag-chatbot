#!/bin/bash
# 보통약관 사람 보험 조 1안(낮추기)·2안(같은 제목 특약 조 올리기) 측정(2026-10-28)
#   검색 회귀 4설정 → 평가 220 3회(1+2안; 기준선은 logs/coverage/proviso — 같은 운영 설정) → 탐침 135턴 × 4설정
cd /home/kopo17/AI_programming/petmint-rag-chatbot
L=logs/coverage; P=data/review/offtarget; mkdir -p $L/offtarget_probe
log() { echo "[$(date '+%F %T')] $*" | tee -a $L/human_chain.log; }
SR="--expand --variant v3 --pool 50 --dict v2"
log "검색 회귀"
for c in "base:" "demote:--human-demote" "twin:--twin" "both:--human-demote --twin"; do
  n=${c%%:*}; f=${c#*:}
  python -m scripts.search_regression_run --out $L/sr_human/$n $SR $f > $L/sr_human_$n.log 2>&1 || { log "검색 회귀 $n 실패"; exit 1; }
done
log "평가 220"; scripts/prod_measure.sh human PETMINT_HUMAN_DEMOTE=1 PETMINT_TWIN_ARTICLE=1 > $L/human.log 2>&1 || { log "평가 실패"; exit 1; }
kill $(ss -ltnp | grep "127.0.0.1:8000" | grep -o "pid=[0-9]*" | cut -d= -f2) 2>/dev/null; sleep 2
set -a; . ./.env; set +a
export PETMINT_CHUNKS_DIR=data/chunks/v3 PETMINT_GRAPH_DIR=data/graph/v3 PETMINT_SEARCH_VARIANT=v3 PETMINT_DISPLAY_PARENT=1 PETMINT_SEARCH_EXPAND=1 PETMINT_EXPAND_DICT=v2 PETMINT_ANSWER_TABLES=1 PETMINT_MODEL_RAG=kabyul-tri-7b-rag1-rebuild4-ckpt462 PETMINT_RULE_FIRST=1 PETMINT_COVERAGE_CODE=1 PETMINT_SEARCH_POOL=50 PETMINT_AGE_CODE=1 PETMINT_PROVISO_CODE=1 PETMINT_TODAY=2026-10-21
for c in "base:0:0" "demote:1:0" "twin:0:1" "both:1:1"; do
  IFS=: read n d t <<< "$c"
  log "탐침 $n"
  PETMINT_HUMAN_DEMOTE=$d PETMINT_TWIN_ARTICLE=$t PETMINT_PROMPT_LOG=$L/offtarget_probe/prompts_$n.jsonl nohup uvicorn app.main:app --port 8000 > $L/offtarget_probe/server_$n.log 2>&1 &
  for i in $(seq 1 90); do grep -q "startup complete" $L/offtarget_probe/server_$n.log && break; sleep 1; done
  python scripts/offtarget_probe.py $P/probe_$n.json > $L/offtarget_probe/probe_$n.log 2>&1 || log "탐침 $n 실패"
  kill $(ss -ltnp | grep "127.0.0.1:8000" | grep -o "pid=[0-9]*" | cut -d= -f2); sleep 2
done
python -m scripts.coverage_table "기준선"=$L/proviso "1+2안"=$L/human --out data/review/human_article_measure.md > $L/human_table.log 2>&1
log "끝"

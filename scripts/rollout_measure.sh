#!/bin/bash
# 운영 반영 판단 측정(2026-10-23 사용자 지시: 사전 v2 · 청크 v3 기본값 · 운영에 켤 것 — 각각 거절률까지).
# 모델은 rebuild4 그대로. 평가 220 보이는 세트 3회 + 내용 판정. 끝나면 scripts/rollout_table.py로 표를 만든다
#   scripts/rollout_measure.sh   (로그 logs/rollout/run.log)
cd /home/kopo17/AI_programming/petmint-rag-chatbot
O=logs/rollout; mkdir -p $O
log() { echo "[$(date '+%F %T')] $*" | tee -a $O/run.log; }
R4=PETMINT_MODEL_RAG=kabyul-tri-7b-rag1-rebuild4-ckpt462
V3="PETMINT_CHUNKS_DIR=data/chunks/v3 PETMINT_GRAPH_DIR=data/graph/v3 PETMINT_SEARCH_VARIANT=v3 PETMINT_DISPLAY_PARENT=1"
V1="PETMINT_CHUNKS_DIR=data/chunks PETMINT_GRAPH_DIR=data/graph PETMINT_SEARCH_VARIANT= PETMINT_DISPLAY_PARENT=0"
log "검색 회귀 118 — v3 + 확장, 사전 v1 / v2"
python -m scripts.search_regression_run --out $O/sr_v1 --expand --variant v3 --dict v1 > $O/sr_v1.log 2>&1
python -m scripts.search_regression_run --out $O/sr_v2 --expand --variant v3 --dict v2 --compare $O/sr_v1/search_regression_pet.json > $O/sr_v2.log 2>&1
run() { local tag=$1; shift; [ -n "$(ls $O/$tag/eval_serving_*_$tag.judge.json 2>/dev/null)" ] && { log "건너뜀 $tag(이미 있음)"; return; }
  log "평가 $tag: $*"; scripts/stage_eval.sh $tag $O/$tag "$@" $R4 >> $O/eval.log 2>&1 || log "실패 $tag"; }
run all     $V3 PETMINT_SEARCH_EXPAND=1 PETMINT_EXPAND_DICT=v1 PETMINT_ANSWER_TABLES=1
run dictv2  $V3 PETMINT_SEARCH_EXPAND=1 PETMINT_EXPAND_DICT=v2 PETMINT_ANSWER_TABLES=1
run nov3    $V1 PETMINT_SEARCH_EXPAND=1 PETMINT_EXPAND_DICT=v1 PETMINT_ANSWER_TABLES=1
run noexp   $V3 PETMINT_SEARCH_EXPAND=0 PETMINT_ANSWER_TABLES=1
run codeonly $V1 PETMINT_SEARCH_EXPAND=0 PETMINT_ANSWER_TABLES=0
python -m scripts.rollout_table > $O/table.log 2>&1
log "끝 — data/review/rollout_measure.md"

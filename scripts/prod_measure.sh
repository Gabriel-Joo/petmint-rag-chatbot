#!/bin/bash
# 지금 운영 설정(2026-10-24 ConfigMap — pool 50·나이 코드·면책 단서 코드 포함) + 평가 기준일 고정으로 평가 220 3회.
#   scripts/prod_measure.sh <태그> [VAR=값 ...]   → logs/coverage/<태그>
cd /home/kopo17/AI_programming/petmint-rag-chatbot
TAG=$1; shift
PROD="PETMINT_CHUNKS_DIR=data/chunks/v3 PETMINT_GRAPH_DIR=data/graph/v3 PETMINT_SEARCH_VARIANT=v3 PETMINT_DISPLAY_PARENT=1 PETMINT_SEARCH_EXPAND=1 PETMINT_EXPAND_DICT=v2 PETMINT_ANSWER_TABLES=1 PETMINT_MODEL_RAG=kabyul-tri-7b-rag1-rebuild4-ckpt462 PETMINT_RULE_FIRST=1 PETMINT_COVERAGE_CODE=1 PETMINT_SEARCH_POOL=50 PETMINT_AGE_CODE=1 PETMINT_PROVISO_CODE=1 PETMINT_TODAY=2026-10-21"
scripts/stage_eval.sh $TAG logs/coverage/$TAG $PROD "$@"

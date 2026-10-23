#!/bin/bash
# 보장 여부 질문 개선 측정(2026-10-23 사용자 지시 — 순서: 평가 항목 → 1안 → 3안 → 제2조 정리). 운영 설정 + 안마다 플래그.
#   scripts/coverage_measure.sh <태그> [VAR=값 ...]   → logs/coverage/<태그>
cd /home/kopo17/AI_programming/petmint-rag-chatbot
TAG=$1; shift
PROD="PETMINT_CHUNKS_DIR=data/chunks/v3 PETMINT_GRAPH_DIR=data/graph/v3 PETMINT_SEARCH_VARIANT=v3 PETMINT_DISPLAY_PARENT=1 PETMINT_SEARCH_EXPAND=1 PETMINT_EXPAND_DICT=v2 PETMINT_ANSWER_TABLES=1 PETMINT_MODEL_RAG=kabyul-tri-7b-rag1-rebuild4-ckpt462"
scripts/stage_eval.sh $TAG logs/coverage/$TAG $PROD "$@"

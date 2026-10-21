#!/bin/bash
# 6단계 — A(옛 청크) = 4d 결과. B(v2로 찾고 부모를 보여줌)·C(v2 조각 그대로) 업무특화 3회, 베이스 대조군 A·C 2회.
# 4단계 설정(질의 확장 켬, 고객 사실 켬, 1차 후보 깊이 20)은 고정
cd /home/kopo17/AI_programming/petmint-rag-chatbot
V2="PETMINT_CHUNKS_DIR=data/chunks/v2 PETMINT_GRAPH_DIR=data/graph/v2 PETMINT_SEARCH_VARIANT=v2"
COMMON="PETMINT_SEARCH_EXPAND=1 PETMINT_CUSTOMER_FACTS=1"
scripts/stage_eval.sh 6B logs/stage6/B $COMMON $V2 PETMINT_DISPLAY_PARENT=1 || exit 1
scripts/stage_eval.sh 6C logs/stage6/C $COMMON $V2 || exit 1
RUNS=2 scripts/stage_eval.sh 6A_base logs/stage6/A_base $COMMON PETMINT_MODEL_RAG=tri-7b || exit 1
RUNS=2 scripts/stage_eval.sh 6C_base logs/stage6/C_base $COMMON $V2 PETMINT_MODEL_RAG=tri-7b || exit 1
echo "6단계 끝"

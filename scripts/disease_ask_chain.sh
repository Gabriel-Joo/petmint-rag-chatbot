#!/bin/bash
# 병명 되묻기 측정(2026-10-28) — 운영 설정 + 기준일 2026-10-21, 태그별 서버로 탐침 3회.  scripts/disease_ask_chain.sh <태그> [VAR=값 ...]
cd /home/kopo17/AI_programming/petmint-rag-chatbot
TAG=$1; shift; O=logs/disease_ask/$TAG; mkdir -p $O; rm -f $O/prompts.jsonl
set -a; . ./.env; set +a
export PETMINT_CHUNKS_DIR=$PWD/data/chunks/v3 PETMINT_GRAPH_DIR=$PWD/data/graph/v3 PETMINT_SEARCH_VARIANT=v3 PETMINT_DISPLAY_PARENT=1 PETMINT_SEARCH_EXPAND=1 PETMINT_EXPAND_DICT=v2 PETMINT_ANSWER_TABLES=1 PETMINT_MODEL_RAG=kabyul-tri-7b-rag1-rebuild4-ckpt462 PETMINT_RULE_FIRST=1 PETMINT_COVERAGE_CODE=1 PETMINT_SEARCH_POOL=50 PETMINT_AGE_CODE=1 PETMINT_PROVISO_CODE=1 PETMINT_TWIN_ARTICLE=1 PETMINT_TODAY=2026-10-21
for kv in "$@"; do export "$kv"; done
PETMINT_PROMPT_LOG=$PWD/$O/prompts.jsonl nohup uvicorn --app-dir ${CODE:-.} app.main:app --port 8000 > $O/server.log 2>&1 &
for i in $(seq 1 90); do grep -q "startup complete" $O/server.log && break; sleep 1; done
python -m scripts.disease_ask_probe $O/answers.json --runs ${RUNS:-3} --file ${FILE:-data/eval/disease_ask_probe.json} > $O/probe.log 2>&1; rc=$?
kill $(ss -ltnp | grep "127.0.0.1:8000" | grep -o "pid=[0-9]*" | cut -d= -f2)
tail -n 1 $O/probe.log; exit $rc

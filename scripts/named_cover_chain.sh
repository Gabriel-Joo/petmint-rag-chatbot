#!/bin/bash
# 병명 보장 대조 측정(2026-10-29) — 운영 설정(병명 되묻기 + 모델 ⑤ 켬)에서 PETMINT_NAMED_COVER 끔/켬.
#   내 탐침 3회 · gemma 80문항 1회 · 병명 되묻기 탐침 3회(회귀) · 평가 220 1회씩.  scripts/named_cover_chain.sh > logs/named_cover/chain.log
cd /home/kopo17/AI_programming/petmint-rag-chatbot
SP=${SP:?gemma 탐침 파일 폴더}
ON="PETMINT_ASK_DISEASE=1 PETMINT_ASK_DISEASE_LLM=1"
step() { echo "[$(date '+%F %T')] $*"; }
for f in 0 1; do
  step "내 탐침 NAMED_COVER=$f"; RUNS=3 FILE=data/eval/named_cover_probe.json bash scripts/disease_ask_chain.sh nc_probe_$f $ON PETMINT_NAMED_COVER=$f
  step "gemma NAMED_COVER=$f";   RUNS=1 FILE=$SP/nc/gemma_seq.json bash scripts/disease_ask_chain.sh nc_gemma_$f $ON PETMINT_NAMED_COVER=$f
done
step "병명 되묻기 탐침(회귀) NAMED_COVER=1"; RUNS=3 bash scripts/disease_ask_chain.sh nc_da_1 $ON PETMINT_NAMED_COVER=1
FLAGS="PETMINT_RULE_FIRST=1 PETMINT_COVERAGE_CODE=1 PETMINT_SEARCH_POOL=50 PETMINT_AGE_CODE=1 PETMINT_PROVISO_CODE=1 PETMINT_TWIN_ARTICLE=1 PETMINT_TODAY=2026-10-21 $ON"
for f in 0 1; do
  step "평가 220 NAMED_COVER=$f"; RUNS=1 scripts/coverage_measure.sh nc_eval_$f $FLAGS PETMINT_NAMED_COVER=$f
done
kill $(ss -ltnp | grep ":8000" | grep -o "pid=[0-9]*" | cut -d= -f2) 2>/dev/null
step "끝"

#!/bin/bash
# 판정 기준에 결론없음을 넣은 뒤(2026-10-24) 같은 답을 다시 판정 — 예전 판정은 각 폴더 judge_v1.json
cd /home/kopo17/AI_programming/petmint-rag-chatbot
for d in a3b pool50 age; do
  R=$(ls logs/coverage/$d/eval_serving_*.json | grep -v judge | tail -1)
  python -m scripts.eval_judge --result "$R" > logs/coverage/$d/rejudge.log 2>&1 || { echo "$d 실패"; exit 1; }
  echo "$d 끝"
done

#!/bin/bash
# 단계 측정 — 앱 서버를 주어진 환경으로 다시 띄우고 평가 세트 220(보이는 세트)을 3회 + 내용 판정 + 프롬프트 대조.
#   scripts/stage_eval.sh <태그> <출력 폴더> [VAR=값 ...]   (예: PETMINT_SEARCH_EXPAND=1)
#   EVAL_ARGS="--open-hidden" 이면 숨긴 세트까지(rebuild5 평가 때만)
cd /home/kopo17/AI_programming/petmint-rag-chatbot
set -a; . ./.env; set +a
TAG=$1; O=$2; shift 2
for kv in "$@"; do export "$kv"; done
mkdir -p "$O"
unload() { for m in $(curl -s localhost:11434/api/ps | python3 -c "import json,sys; print(' '.join(x['name'] for x in json.load(sys.stdin)['models']))"); do curl -s localhost:11434/api/generate -d "{\"model\":\"$m\",\"keep_alive\":0}" >/dev/null; done; }
kill $(ss -ltnp | grep ":8000" | grep -o "pid=[0-9]*" | cut -d= -f2) 2>/dev/null; sleep 2
rm -f "$O/prompts_$TAG.jsonl"
PETMINT_PROMPT_LOG="$O/prompts_$TAG.jsonl" nohup uvicorn app.main:app --port 8000 > "$O/server_$TAG.log" 2>&1 &
for i in $(seq 1 90); do grep -q "startup complete" "$O/server_$TAG.log" && break; sleep 1; done
grep -q "startup complete" "$O/server_$TAG.log" || { echo "서버 기동 실패"; exit 1; }
unload
python -m scripts.eval_serving --tag "$TAG" --runs "${RUNS:-3}" --prompt-log "$O/prompts_$TAG.jsonl" --out "$O" ${EVAL_ARGS:-} > "$O/eval_$TAG.log" 2>&1 || { echo "평가 실패"; tail -20 "$O/eval_$TAG.log"; exit 1; }
unload
R=$(ls -t "$O"/eval_serving_*_"$TAG".json | head -1)
python -m scripts.eval_judge --result "$R" > "$O/judge_$TAG.log" 2>&1
python -m scripts.eval_check_prompts --result "$R" --prompt-log "$O/prompts_$TAG.jsonl" --n 40 2>&1 | grep -v -i warn > "$O/check_$TAG.log"
echo "끝 $TAG $R"

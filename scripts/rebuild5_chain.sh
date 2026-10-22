#!/bin/bash
# rebuild5 전 구간(2026-10-22 사용자 지시: 전량 생성 → 판정 → 학습 → 체크포인트 선택 → 평가(숨긴 세트 포함)까지 멈추지 말고).
# 단계마다 끝났는지 표시 파일을 남겨, 중간에 끊겨도 다시 실행하면 이어서 한다. 로그: logs/stage7/chain.log
#   scripts/rebuild5_chain.sh [동시 처리 수]
cd /home/kopo17/AI_programming/petmint-rag-chatbot
W=${1:-1}
L=logs/stage7; mkdir -p $L/done
log() { echo "[$(date '+%F %T')] $*" | tee -a $L/chain.log; }
step() { [ -f "$L/done/$1" ]; }
mark() { touch "$L/done/$1"; log "끝: $1"; }
die() { log "멈춤: $*"; exit 1; }
unload() { for m in $(curl -s localhost:11434/api/ps | python3 -c "import json,sys; print(' '.join(x['name'] for x in json.load(sys.stdin)['models']))"); do curl -s localhost:11434/api/generate -d "{\"model\":\"$m\",\"keep_alive\":0}" >/dev/null; done; }
B="PETMINT_CHUNKS_DIR=data/chunks/v3 PETMINT_GRAPH_DIR=data/graph/v3 PETMINT_SEARCH_VARIANT=v3 PETMINT_SEARCH_EXPAND=1 PETMINT_DISPLAY_PARENT=1"
SERVE="$B PETMINT_CUSTOMER_FACTS=1 PETMINT_ANSWER_TABLES=1"
R4=kabyul-tri-7b-rag1-rebuild4-ckpt462

# 1. C 전량 생성·판정
if ! step c_full; then
  log "1. C 전량(final) 생성·판정 — 동시 $W"
  env $B python -m data.faq_rag full --workers $W >> $L/c_full.log 2>&1 || die "C 전량 실패 — $L/c_full.log"
  mark c_full
fi
# 2. 학습 샘플
if ! step build; then
  log "2. 학습 샘플"
  python -m data.faq_rag build --out-dir data/finetune/rebuild5 >> $L/build.log 2>&1 || die "build 실패 — $L/build.log"
  N=$(python3 -c "import json; print(json.load(open('data/finetune/rebuild5/stats.json'))['train'])")
  [ "$N" -ge 3000 ] || die "train $N건 — 3,000 미만(판정이 너무 많이 버림)"
  mark build
fi
# 3. 학습(07 노트북)
if ! step train; then
  log "3. 학습"
  unload
  # 학습은 GPU 최대 10GiB(rebuild4 기록) — search-service(5.75GB)와 같이 16GB를 넘는다. search-service를 내리면 운영 클러스터 검색이
  # 멈추므로 사용자 허락(logs/stage7/allow_stop_search 파일)이 있을 때만 학습 동안 내렸다가 끝나면 다시 올린다. 없으면 기다린다
  SPID=$(ss -ltnp | grep "192.168.122.1:8100" | grep -oP 'pid=\K[0-9]+')
  if [ -n "$SPID" ]; then
    while [ ! -f $L/allow_stop_search ]; do log "학습 대기 — search-service를 내려도 되는지 허락 필요($L/allow_stop_search)"; sleep 1800; done
    log "search-service 내림(pid $SPID) — 학습 동안 운영 검색 중단"
    kill $SPID; sleep 5
  fi
  PETMINT_FT_DATA_DIR=$PWD/data/finetune/rebuild5 PETMINT_ADAPTER_TAG=rebuild5 python -m jupyter nbconvert --to notebook --execute \
    notebooks/07_파인튜닝.ipynb --output-dir $L --output 07_executed_rebuild5.ipynb --ExecutePreprocessor.timeout=-1 >> $L/train.log 2>&1
  RC=$?
  if [ -n "$SPID" ]; then
    nohup python -m search_service.main > logs/search_service.log 2>&1 &
    for i in $(seq 1 60); do curl -s -m2 http://192.168.122.1:8100/health | grep -q '"ok":true' && break; sleep 5; done
    curl -s -m2 http://192.168.122.1:8100/health | grep -q '"ok":true' && log "search-service 다시 올림" || die "search-service 재기동 실패 — 운영 검색이 멈춰 있다"
  fi
  [ $RC -eq 0 ] || die "학습 실패 — $L/train.log"
  mark train
fi
AD=$(ls -dt models/lora_adapter/*_rebuild5 | head -1)
log "어댑터: $AD"
# 4. rebuild4 기준값 — 같은 코드, 숨긴 세트 포함(학습이 끝난 뒤 연다)
if ! step r4; then
  log "4. rebuild4 재측정(숨긴 세트 포함)"
  EVAL_ARGS="--open-hidden" scripts/stage_eval.sh r4final $L/r4 $SERVE PETMINT_MODEL_RAG=$R4 >> $L/r4.log 2>&1 || die "rebuild4 평가 실패"
  mark r4
fi
R4J=$(ls -t $L/r4/eval_serving_*_r4final.json | head -1)
# 5. 체크포인트 선택(평가 220 보이는 세트)
if ! step select; then
  log "5. 체크포인트 선택"
  unload
  python -m scripts.ckpt_select220 "$AD" --result "$R4J" --prompts $L/r4/prompts_r4final.jsonl >> $L/select.log 2>&1 || die "선택 실패 — $L/select.log"
  mark select
fi
BEST=$(python3 -c "import json; print(json.load(open('$AD/ckpt_select.json'))['best_path'])")
STEPN=$(python3 -c "import json; s=json.load(open('$AD/ckpt_select.json'))['best_step']; print(s if s < 10**9 else 'final')")
NAME=kabyul-tri-7b-rag1-rebuild5-ckpt$STEPN
log "선택: $BEST → $NAME"
# 6. 병합 → GGUF → Ollama(docs/저녁실행.md 7절과 같은 절차, 베이스와 같은 Q4_K_M·매개변수)
if ! step gguf; then
  log "6. 병합·GGUF·ollama create"
  unload
  CUDA_VISIBLE_DEVICES="" python - >> $L/gguf.log 2>&1 <<EOF || die "병합 실패"
import torch
from pathlib import Path
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
out = Path("models/merged/$NAME")
base = AutoModelForCausalLM.from_pretrained("models/base/Tri-7B", dtype=torch.bfloat16)
PeftModel.from_pretrained(base, "$BEST").merge_and_unload().save_pretrained(out, safe_serialization=True)
AutoTokenizer.from_pretrained("models/base/Tri-7B").save_pretrained(out)
print("병합:", out)
EOF
  LC=~/AI_programming/notebooks/llama.cpp
  python $LC/convert_hf_to_gguf.py models/merged/$NAME --outtype f16 --outfile models/gguf/$NAME-f16.gguf >> $L/gguf.log 2>&1 || die "GGUF 변환 실패"
  $LC/build/bin/llama-quantize models/gguf/$NAME-f16.gguf models/gguf/$NAME-Q4_K_M.gguf Q4_K_M >> $L/gguf.log 2>&1 || die "양자화 실패"
  printf "FROM /tmp/$NAME-Q4_K_M.gguf\nPARAMETER num_ctx 8192\nPARAMETER temperature 0.3\n" > models/gguf/Modelfile.$NAME
  docker cp models/gguf/$NAME-Q4_K_M.gguf ollama:/tmp/$NAME-Q4_K_M.gguf && docker cp models/gguf/Modelfile.$NAME ollama:/tmp/Modelfile.$NAME \
    && docker exec ollama ollama create $NAME -f /tmp/Modelfile.$NAME >> $L/gguf.log 2>&1 || die "ollama create 실패"
  docker exec ollama ollama list | grep -q "$NAME" || die "ollama list에 $NAME 없음"
  mark gguf
fi
# 7. rebuild5 평가(숨긴 세트 포함)
if ! step r5; then
  log "7. rebuild5 평가(숨긴 세트 포함)"
  EVAL_ARGS="--open-hidden" scripts/stage_eval.sh r5final $L/r5 $SERVE PETMINT_MODEL_RAG=$NAME >> $L/r5.log 2>&1 || die "rebuild5 평가 실패"
  mark r5
fi
R5J=$(ls -t $L/r5/eval_serving_*_r5final.json | head -1)
# 8. 채택 판정
python -m scripts.rebuild5_verdict --r4 "$R4J" --r5 "$R5J" --out data/review/rebuild5_verdict.md >> $L/verdict.log 2>&1 || die "판정 실패"
log "끝 — data/review/rebuild5_verdict.md"
grep -m1 "판정:" data/review/rebuild5_verdict.md | tee -a $L/chain.log

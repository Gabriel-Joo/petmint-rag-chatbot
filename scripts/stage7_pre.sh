#!/usr/bin/env bash
# 7단계 준비 측정(2026-10-21) — 동의어 사전 v1/v2 검색 회귀 + 라벨 비율 표본. search-service가 새 코드(expand_dict)로 떠 있어야 한다
set -u
cd "$(dirname "$0")/.."
OUT=logs/stage7
B="PETMINT_CHUNKS_DIR=data/chunks/v2 PETMINT_GRAPH_DIR=data/graph/v2 PETMINT_SEARCH_VARIANT=v2 PETMINT_SEARCH_EXPAND=1 PETMINT_DISPLAY_PARENT=1"
echo "== 검색 회귀 118 (v2 청크 + 확장) — 사전 v1 / v2 $(date +%T)"
python -m scripts.search_regression_run --out $OUT/sr_dict_v1 --expand --variant v2 --dict v1 2>&1 | grep -E "hit|MRR|==" | head -12
python -m scripts.search_regression_run --out $OUT/sr_dict_v2 --expand --variant v2 --dict v2 --compare $OUT/sr_dict_v1/search_regression_pet.json 2>&1 | grep -vE "^\s*$" | tail -40
echo "== 라벨 비율 표본(종마다 150) — 사전 v1 $(date +%T)"
env $B PETMINT_EXPAND_DICT=v1 python -m data.finetune5 --final-dir data/faq/rebuild4/rw/checked --out-dir $OUT/ft_sample_v1 --sample 150 2>&1 | tail -1
echo "== 끝 $(date +%T)"

#!/usr/bin/env bash
# Full training pipeline (run from the repo root on a Colab A100). Paths come from env vars.
#   TRAIN_DIR=/content/data/train PUBLIC_DIR=/content/data/public_test OUT=/content/drive/MyDrive/DataMate_ZAC2026/models/run1 bash training_code/train.sh
set -euo pipefail
: "${TRAIN_DIR:?}" "${OUT:?}"
PUBLIC_DIR="${PUBLIC_DIR:-}"
python training_code/data_generation/split_holdout.py --split "$TRAIN_DIR" --out configs/split.json
python training_code/data_generation/gen_trajectories.py --split "$TRAIN_DIR" ${PUBLIC_DIR:+--public-test "$PUBLIC_DIR"} \
  --split-file configs/split.json --out training_code/data --work /content/work --max-hours "${GEN_HOURS:-6}"
python training_code/src/manifest.py --data training_code/data
python training_code/src/sft.py --data training_code/data/sft.jsonl --out "$OUT"

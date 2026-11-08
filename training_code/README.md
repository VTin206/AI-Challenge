# Training pipeline

Run on a Colab A100 through the notebooks in [`../notebooks`](../notebooks). The team workflow and the Drive layout are in [`../docs/TEAM_RUNBOOK.md`](../docs/TEAM_RUNBOOK.md).

| Step | Script | Notebook |
|---|---|---|
| Holdout split by template family | `data_generation/split_holdout.py` → `configs/split.json` | 02 |
| Teacher trajectories, rejection sampling on train only | `data_generation/gen_trajectories.py` | 02 |
| Data manifest | `src/manifest.py` | 02 |
| QLoRA SFT, saves the adapter only | `src/sft.py` + `configs/sft_qwen3_14b.yaml` | 03 |
| Holdout evaluation, base vs adapter | `scripts/run_split.py --lora`, `scripts/tune_tau.py` | 04 |
| Merge the adapter (Docker path only, deferred) | `src/merge.py` | — |

## Data rules

- Only the train split and trajectories we generate ourselves go into training. The public and private tests are never trained on.
- `gen_trajectories.py` refuses a split without `answers.jsonl`.
- It aborts when any question overlaps with public_test.
- The sandbox runs on a staged copy of the split that has no labels.
- Code that touches files, the environment or parent directories is rejected.
- Every trajectory, accepted or rejected, is kept under `data/raw/`.
- `training_code/data/`, `checkpoints/` and `logs/` are ignored by git. Outputs go to Drive.

`train.sh` runs the whole pipeline end to end from environment variables, as an alternative to the notebooks.

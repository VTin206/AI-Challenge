# Team runbook: DataMate SLM on Colab

**Shared Drive folder:** https://drive.google.com/drive/folders/101nqt-JVt73QnaCLo8Y_ROeNHNf6WKJi

Goal: reach the top of the public leaderboard (SLM) before **2026-11-16 23:59 GMT+7**. The code lives on branch `feat/slm-agent` of this repo. Data, notebooks, runs and models live on the Drive folder above.

## One-time setup

1. Open the Drive link and choose **Add shortcut to Drive → My Drive**. The notebooks expect the folder at `/content/drive/MyDrive/DataMate_ZAC2026`.
2. The link is read-only. To write runs and models, ask the folder owner to add your Gmail as an **Editor**. Without that, change `DRIVE_ROOT` in the first cell to a folder of your own.
3. Open a notebook from `notebooks/` on Drive (or from the GitHub repo) in Colab. Choose **Runtime → Change runtime type → A100 GPU**.

## Drive layout

```text
DataMate_ZAC2026/
  data/train/train.zip              # competition train split (has answers.jsonl)
  data/public_test/public_test.zip  # public test, inference only
  notebooks/01..04 *.ipynb
  runs/<run>/submission.jsonl, log.jsonl, run_config.json
  models/<run>/adapter/             # LoRA adapters from notebook 03
  training/data/                    # generated trajectories (sft.jsonl, raw/, yield_report.json)
  submissions_log.csv               # one row per portal submission
```

## Notebook order

| Notebook | Purpose | Approx. cost |
|---|---|---|
| `01_zero_shot_eval` | Measure holdout PA (6 train shops in `configs/holdout.json`), tune τ, then run public_test and produce `submission.jsonl` | Holdout k=5 first: read `sec_per_question` in the log before running everything |
| `02_generate_trajectories` | Teacher rejection sampling on train only, excluding holdout shops | Set `--max-hours`; resumable |
| `03_sft_qlora` | Unsloth QLoRA on `sft.jsonl`; saves the adapter only | Checkpoints on Drive; resumable |
| `04_eval_finetuned` | Holdout PA for base vs adapter, then a public_test submission with the adapter | Same as 01 |

Every run takes `--resume`. If Colab disconnects, re-run the same cell and it continues from the last finished question.

## Submitting

- Upload `runs/<run>/submission.jsonl` on the portal. The limit is **5 submissions per day**.
- After each submission, fill `portal_pa` and `holdout_pa` for that run in `submissions_log.csv`. This lets us keep the config whose holdout gains also show up on the portal.
- Scoring is +1 correct, 0 abstain, −1 wrong. Abstaining below the agreement threshold τ is what keeps PA positive. Choose τ with `scripts/tune_tau.py`, never by guesswork.

## Daily loop

1. Run 01 (or 04) on holdout with the change you want to test: thinking on or off, `k`, prompt edit, or adapter.
2. Keep the change only if holdout PA improves. Then run public_test and submit.
3. Analyse wrong answers with `log.jsonl` (each record keeps every sample's code, output and final answer). Fix the prompt, helpers or rulebook handling in the repo and push to `feat/slm-agent`.
4. Go/no-go for the fine-tuned adapter: use it only if it beats the base on both holdout PA and portal PA.

## Rules we follow

- Train only on the train split plus data we generate ourselves. Never train on public or private test.
- Competition data never goes into GitHub. Only Drive holds it.
- No API keys or tokens in notebooks or commits.

## Local commands

```bash
pip install -e .[dev]
python -m pytest -q
python scripts/evaluate.py --predictions runs/x/submission.jsonl --gold <train>/answers.jsonl --questions <train>/questions.jsonl --only-predicted
```

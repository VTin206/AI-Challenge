"""QLoRA SFT of Qwen3 on accepted agent trajectories (Unsloth). Saves the LoRA adapter only.

Each assistant turn becomes one prompt/completion sample whose prompt is rendered exactly as the
agent renders it at inference (``apply_chat_template(..., add_generation_prompt=True,
enable_thinking=False)``), so loss is only on that turn and train/inference contexts match.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

import yaml


def turn_samples(tok, messages: list[dict]) -> list[dict]:
    out = []
    for i, msg in enumerate(messages):
        if msg["role"] == "assistant":
            prompt = tok.apply_chat_template(messages[:i], tokenize=False, add_generation_prompt=True, enable_thinking=False)
            out.append({"prompt": prompt, "completion": msg["content"] + tok.eos_token})
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, default=Path("training_code/configs/sft_qwen3_14b.yaml"))
    p.add_argument("--data", type=Path, default=Path("training_code/data/sft.jsonl"))
    p.add_argument("--out", type=Path, required=True, help="adapter output dir (e.g. on Drive)")
    a = p.parse_args()
    cfg = yaml.safe_load(a.config.read_text(encoding="utf-8"))

    from unsloth import FastLanguageModel  # must be imported before trl/transformers/peft

    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer

    rows = [json.loads(x) for x in a.data.read_text(encoding="utf-8").splitlines() if x.strip()]
    model, tok = FastLanguageModel.from_pretrained(cfg["base_model"], max_seq_length=cfg["max_seq_len_cap"],
                                                   load_in_4bit=True, dtype=None)
    samples = [s for r in rows for s in turn_samples(tok, r["messages"])]
    for s in samples:
        s["n"] = len(tok(s["prompt"] + s["completion"], add_special_tokens=False)["input_ids"])
    lengths = sorted(s["n"] for s in samples)
    p95 = lengths[min(len(lengths) - 1, int(0.95 * len(lengths)))]
    max_len = min(cfg["max_seq_len_cap"], int(math.ceil(p95 / 1024) * 1024)) if cfg.get("max_seq_len") == "p95" else int(cfg["max_seq_len"])
    keep = [{"prompt": s["prompt"], "completion": s["completion"]} for s in samples if s["n"] <= max_len]
    print(json.dumps({"trajectories": len(rows), "turn_samples": len(samples), "p95_tokens": p95, "max_len": max_len,
                      "dropped": len(samples) - len(keep)}))
    random.Random(cfg["seed"]).shuffle(keep)

    model = FastLanguageModel.get_peft_model(
        model, r=cfg["lora_r"], lora_alpha=cfg["lora_alpha"], lora_dropout=0, bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=cfg["seed"],
    )
    trainer = SFTTrainer(
        model=model, processing_class=tok, train_dataset=Dataset.from_list(keep),
        args=SFTConfig(
            output_dir=str(a.out / "checkpoints"), max_length=max_len, completion_only_loss=True,
            per_device_train_batch_size=cfg["batch_size"], gradient_accumulation_steps=cfg["grad_accum"],
            num_train_epochs=cfg["epochs"], learning_rate=float(cfg["lr"]), lr_scheduler_type="cosine",
            warmup_ratio=cfg["warmup_ratio"], logging_steps=10, save_steps=cfg["save_steps"], save_total_limit=2,
            optim="adamw_8bit", bf16=True, seed=cfg["seed"], report_to="none", packing=False,
        ),
    )
    resume = any((a.out / "checkpoints").glob("checkpoint-*"))
    trainer.train(resume_from_checkpoint=resume or None)
    adapter = a.out / "adapter"
    model.save_pretrained(str(adapter))
    tok.save_pretrained(str(adapter))
    (adapter / "train_meta.json").write_text(json.dumps({"config": cfg, "max_len": max_len, "samples": len(keep)}, indent=2), encoding="utf-8")
    print(f"adapter saved to {adapter}")


if __name__ == "__main__":
    main()

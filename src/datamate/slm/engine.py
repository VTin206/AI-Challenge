"""Generation backends: vLLM (Colab GPU) and transformers (CPU smoke).

Both expose ``render(messages)``, ``count(text)`` and ``generate(prompts, max_tokens, seeds)``.
With thinking on, generation is two-phase: think up to ``think_cap`` tokens, force ``</think>``,
then generate the answer segment with the protocol stop strings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STOPS = ["</code>", "</final>"]


@dataclass
class GenConfig:
    model: str
    backend: str = "vllm"
    lora: str | None = None
    max_model_len: int = 32768
    max_new_tokens: int = 1536
    temperature: float = 0.6
    top_p: float = 0.95
    thinking: bool = False
    think_cap: int = 1024
    tensor_parallel_size: int = 1
    gpu_memory_utilization: float = 0.9
    quantization: str | None = None
    dtype: str = "auto"
    extra: dict[str, Any] = field(default_factory=dict)


class _Base:
    def __init__(self, cfg: GenConfig, tokenizer):
        self.cfg = cfg
        self.tok = tokenizer

    def render(self, messages: list[dict[str, str]]) -> str:
        return self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=self.cfg.thinking)

    def count(self, text: str) -> int:
        return len(self.tok(text, add_special_tokens=False)["input_ids"])

    def _raw(self, prompts: list[str], max_tokens: list[int], seeds: list[int], stops: list[str]) -> list[str]:
        raise NotImplementedError

    def generate(self, prompts: list[str], max_tokens: list[int], seeds: list[int]) -> list[str]:
        if not self.cfg.thinking:
            return self._raw(prompts, max_tokens, seeds, STOPS)
        caps = [max(1, min(self.cfg.think_cap, m - 256)) for m in max_tokens]
        thoughts = self._raw(prompts, caps, seeds, ["</think>"])
        thoughts = [t.split("</think>")[0].rstrip() + "\n</think>\n\n" for t in thoughts]
        rest = [max(64, m - self.count(t)) for m, t in zip(max_tokens, thoughts)]
        answers = self._raw([p + t for p, t in zip(prompts, thoughts)], rest, seeds, STOPS)
        return [t + a for t, a in zip(thoughts, answers)]


class VLLMEngine(_Base):
    def __init__(self, cfg: GenConfig):
        from vllm import LLM

        kwargs: dict[str, Any] = dict(
            model=cfg.model, tensor_parallel_size=cfg.tensor_parallel_size, max_model_len=cfg.max_model_len,
            enable_prefix_caching=True, gpu_memory_utilization=cfg.gpu_memory_utilization, dtype=cfg.dtype,
        )
        if cfg.quantization:
            kwargs["quantization"] = cfg.quantization
        if cfg.lora:
            kwargs.update(enable_lora=True, max_lora_rank=cfg.extra.get("max_lora_rank", 64))
        kwargs.update(cfg.extra.get("vllm_kwargs", {}))
        self.llm = LLM(**kwargs)
        self.lora_request = None
        if cfg.lora:
            from vllm.lora.request import LoRARequest

            self.lora_request = LoRARequest("adapter", 1, cfg.lora)
        super().__init__(cfg, self.llm.get_tokenizer())

    def _raw(self, prompts, max_tokens, seeds, stops):
        from vllm import SamplingParams

        params = [
            SamplingParams(temperature=self.cfg.temperature, top_p=self.cfg.top_p, max_tokens=m, seed=s,
                           stop=stops, include_stop_str_in_output=True)
            for m, s in zip(max_tokens, seeds)
        ]
        outs = self.llm.generate(prompts, params, lora_request=self.lora_request, use_tqdm=False)
        return [o.outputs[0].text for o in outs]


class HFEngine(_Base):
    def __init__(self, cfg: GenConfig):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tok = AutoTokenizer.from_pretrained(cfg.model)
        self.torch = torch
        self.model = AutoModelForCausalLM.from_pretrained(cfg.model, torch_dtype="auto")
        if cfg.lora:
            from peft import PeftModel

            self.model = PeftModel.from_pretrained(self.model, cfg.lora)
        self.model.eval()
        super().__init__(cfg, tok)

    def _raw(self, prompts, max_tokens, seeds, stops):
        outs = []
        for prompt, m, s in zip(prompts, max_tokens, seeds):
            self.torch.manual_seed(s)
            ids = self.tok(prompt, return_tensors="pt", add_special_tokens=False)
            with self.torch.no_grad():
                gen = self.model.generate(
                    **ids, max_new_tokens=m, do_sample=self.cfg.temperature > 0, temperature=self.cfg.temperature or None,
                    top_p=self.cfg.top_p, stop_strings=stops, tokenizer=self.tok, pad_token_id=self.tok.eos_token_id,
                )
            text = self.tok.decode(gen[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
            for stop in stops:
                if stop in text:
                    text = text[: text.index(stop) + len(stop)]
            outs.append(text)
        return outs


def build_engine(cfg: GenConfig):
    return VLLMEngine(cfg) if cfg.backend == "vllm" else HFEngine(cfg)

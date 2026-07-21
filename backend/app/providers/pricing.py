"""
Pricing table referenced by providers/base.py's docstring.

All three comparison models (Qwen2.5-Coder 7B, Llama 3.1 8B, gpt-oss:20b/Mistral 7B)
run locally via Ollama -- there is no per-token billing, so cost is always $0.
This module exists so the pattern (provider looks up its own pricing table) still
holds, and so a real pricing table can be dropped in here without touching callers
if the project ever adds a paid provider back in.
"""

from __future__ import annotations


def ollama_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    return 0.0

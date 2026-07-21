"""
OllamaProvider: the single provider implementation for this project (Capstone_Roadmap
Section 1 -- 3 free local LLMs via Ollama, no paid APIs). Qwen2.5-Coder, Llama 3.1,
and gpt-oss/Mistral are all called through this one class; which model runs is just
the `model` argument, so the same runModel-style call is identical across all three
(roadmap Week 1, "Ollama orchestration layer" task).
"""

from __future__ import annotations

import os
from typing import Optional

import ollama

from app.providers.base import BaseLLMProvider, ProviderCallError
from app.providers.pricing import ollama_cost_usd
from app.schemas.llm_result import ProviderName

DEFAULT_HOST = "http://localhost:11434"


class OllamaProvider(BaseLLMProvider):
    provider_name = ProviderName.OLLAMA
    default_model = "qwen2.5-coder:7b"

    def __init__(self, host: Optional[str] = None):
        self._client = ollama.Client(host=host or os.environ.get("OLLAMA_HOST", DEFAULT_HOST))

    def _call_model(
        self, model: str, system_prompt: str, user_prompt: str
    ) -> tuple[str, int, int]:
        try:
            response = self._client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as e:
            # Covers ollama.ResponseError (e.g. model not pulled) and connection
            # failures (e.g. Ollama daemon not running) -- both unrecoverable here,
            # unlike the rate-limit/timeout cases BaseLLMProvider retries internally.
            raise ProviderCallError(f"Ollama call failed for model '{model}': {e}") from e

        return (
            response.message.content or "",
            response.prompt_eval_count or 0,
            response.eval_count or 0,
        )

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        return ollama_cost_usd(model, input_tokens, output_tokens)

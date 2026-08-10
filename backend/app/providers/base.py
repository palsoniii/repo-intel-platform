"""
BaseLLMProvider: the interface every LLM vendor integration implements.

To add a new provider:
  1. Subclass BaseLLMProvider
  2. Implement `_call_model()` -- the one vendor-specific method (raw API call)
  3. Everything else (retry/backoff, latency timing, cost estimation, result-object
     construction) is handled here in the base class so it isn't duplicated per vendor.

Cost estimates are approximate -- pricing tables are maintained in
providers/pricing.py and dated. Do not treat estimated_cost_usd as billing-accurate.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Optional

from app.schemas.llm_result import (
    ContextVariant,
    LLMMetrics,
    LLMOutput,
    LLMResult,
    LLMTask,
    ProviderName,
    RunStatus,
)


class ProviderCallError(Exception):
    """Raised by _call_model on unrecoverable failures (auth, bad request).
    Rate limits / timeouts should be retried internally before raising this."""


class BaseLLMProvider(ABC):
    provider_name: ProviderName
    default_model: str
    max_retries: int = 2

    @abstractmethod
    def _call_model(
        self, model: str, system_prompt: str, user_prompt: str
    ) -> tuple[str, int, int]:
        """Vendor-specific API call. Must return (raw_text, input_tokens, output_tokens).
        Should retry internally on rate limits/timeouts up to self.max_retries before
        raising ProviderCallError. This is the ONLY method a new provider needs to write."""
        raise NotImplementedError

    @abstractmethod
    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Look up this provider's pricing table and return an approximate USD cost."""
        raise NotImplementedError

    def _run(
        self,
        task: LLMTask,
        context_variant: ContextVariant,
        repo_name: str,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        prompt_template_version: Optional[str] = None,
    ) -> LLMResult:
        model = model or self.default_model
        start = time.monotonic()
        retry_count = 0

        try:
            raw_text, in_tok, out_tok = self._call_model(model, system_prompt, user_prompt)
            status = RunStatus.SUCCESS
            error = None
        except ProviderCallError as e:
            raw_text, in_tok, out_tok = "", 0, 0
            status = RunStatus.FAILED
            error = str(e)

        latency_ms = int((time.monotonic() - start) * 1000)
        cost = self.estimate_cost(model, in_tok, out_tok) if status == RunStatus.SUCCESS else 0.0

        return LLMResult(
            provider=self.provider_name,
            model=model,
            task=task,
            context_variant=context_variant,
            repo_name=repo_name,
            output=LLMOutput(raw_text=raw_text, parsed=None, valid=False),
            metrics=LLMMetrics(
                latency_ms=latency_ms,
                input_tokens=in_tok,
                output_tokens=out_tok,
                estimated_cost_usd=cost,
                retry_count=retry_count,
            ),
            status=status,
            error=error,
            prompt_template_version=prompt_template_version,
        )

    def generate_summary(
        self,
        context: str,
        repo_name: str,
        context_variant: ContextVariant,
        prompt_template: str,
        model: Optional[str] = None,
    ) -> LLMResult:
        """Downstream code (evaluation harness / validation layer) is responsible for
        parsing output.raw_text into structured JSON and setting output.parsed / .valid --
        keeping that here would couple this base class to a specific summary schema."""
        system_prompt = "You are a repository analysis assistant. Respond only with valid JSON."
        return self._run(
            task=LLMTask.SUMMARY,
            context_variant=context_variant,
            repo_name=repo_name,
            system_prompt=system_prompt,
            user_prompt=prompt_template.format(context=context),
            model=model,
        )

    def generate_architecture_diagram(
        self,
        context: str,
        repo_name: str,
        context_variant: ContextVariant,
        prompt_template: str,
        model: Optional[str] = None,
    ) -> LLMResult:
        system_prompt = "You are a software architecture assistant. Respond only with a valid Mermaid diagram definition."
        return self._run(
            task=LLMTask.ARCHITECTURE_DIAGRAM,
            context_variant=context_variant,
            repo_name=repo_name,
            system_prompt=system_prompt,
            user_prompt=prompt_template.format(context=context),
            model=model,
        )

    def judge(
        self,
        system_prompt: str,
        user_prompt: str,
        repo_name: str,
        context_variant: ContextVariant,
        model: Optional[str] = None,
    ) -> LLMResult:
        """Generic evaluation call -- used by the hallucination scorer to have one
        model grade another's summary. Takes fully-formed prompts (the caller owns
        the judging rubric) rather than a fixed template, and records the
        context_variant of the summary being judged so results are attributable to
        a representation arm. Parsing the verdict is the caller's job, as with
        generate_summary()."""
        return self._run(
            task=LLMTask.HALLUCINATION_JUDGE,
            context_variant=context_variant,
            repo_name=repo_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
        )

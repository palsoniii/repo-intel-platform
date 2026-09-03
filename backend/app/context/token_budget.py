import os
import tiktoken
import logging
from app.providers.prompts import SUMMARY_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

_budget_cache = {}
_encoder_cache = None

def get_encoder():
    global _encoder_cache
    if _encoder_cache is None:
        _encoder_cache = tiktoken.get_encoding("cl100k_base")
    return _encoder_cache

def compute_context_token_budget(reserved_output_tokens: int = 1200) -> int:
    global _budget_cache
    if reserved_output_tokens in _budget_cache:
        return _budget_cache[reserved_output_tokens]

    OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
    SYSTEM_PROMPT_TOKENS = 50
    
    enc = get_encoder()
    template_overhead_tokens = len(enc.encode(SUMMARY_PROMPT_TEMPLATE.format(context="")))
    
    budget = OLLAMA_NUM_CTX - (SYSTEM_PROMPT_TOKENS + template_overhead_tokens + reserved_output_tokens)
    _budget_cache[reserved_output_tokens] = budget
    
    if not hasattr(compute_context_token_budget, "_budget_logged"):
        logger.info(f"Computed context token budget: {budget} tokens (OLLAMA_NUM_CTX={OLLAMA_NUM_CTX})")
        print(f"Computed context token budget: {budget} tokens (OLLAMA_NUM_CTX={OLLAMA_NUM_CTX})")
        compute_context_token_budget._budget_logged = True
        
    return budget

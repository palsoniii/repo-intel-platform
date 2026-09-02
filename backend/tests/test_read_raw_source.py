import os
from pathlib import Path
import pytest
import tiktoken
from app.schemas.parser_schema import ParsedRepository, ModuleNode, RepoMetadata
from app.pipeline import _read_raw_source

def test_read_raw_source_token_budget(tmp_path, capsys):
    # Setup synthetic repo and files
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    
    file1 = repo_path / "main.py"
    file2 = repo_path / "utils.py"
    
    # Generate an oversized content
    # 5000 words ~ 6600 tokens per file
    content1 = "word " * 10000 
    content2 = "other " * 10000
    
    file1.write_text(content1)
    file2.write_text(content2)
    
    parsed = ParsedRepository(
        metadata=RepoMetadata(name="oversized-repo", source_url="http://fake", detected_language="python"),
        modules=[
            ModuleNode(id="m1", path="main.py"),
            ModuleNode(id="m2", path="utils.py"),
        ]
    )
    
    # Force a specific OLLAMA_NUM_CTX for predictability
    os.environ["OLLAMA_NUM_CTX"] = "8192"
    
    # Clear the logged budget flag to force a recalculation/logging
    import app.pipeline
    if hasattr(app.pipeline._read_raw_source, "_budget_logged"):
        delattr(app.pipeline._read_raw_source, "_budget_logged")
        
    result = app.pipeline._read_raw_source(repo_path, parsed)
    
    # Verify the output is within budget
    enc = tiktoken.get_encoding("cl100k_base")
    from app.providers.prompts import SUMMARY_PROMPT_TEMPLATE
    template_overhead_tokens = len(enc.encode(SUMMARY_PROMPT_TEMPLATE.format(context="")))
    budget = 8192 - (50 + template_overhead_tokens + 1200)
    
    result_tokens = len(enc.encode(result))
    
    # Due to truncation, it should match the budget exactly (or be very close)
    assert result_tokens <= budget
    
    # Verify the fast-fail warning was printed
    captured = capsys.readouterr()
    assert "WARNING: Repo oversized-repo raw source exceeds token budget!" in captured.out


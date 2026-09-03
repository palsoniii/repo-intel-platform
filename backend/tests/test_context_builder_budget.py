import os
import tiktoken
import pytest
from app.context.builder import _format_dependency_graph, _format_knowledge_graph

def test_builder_small_repo():
    os.environ["OLLAMA_NUM_CTX"] = "8192"
    # Create a small repo
    data = {
        "framework": "nestjs",
        "framework_version": "1.0",
        "module_rows": [
            {"path": "m1.ts", "imports": ["m2.ts"], "classes": ["C1"]}
        ],
        "endpoints": [{"method": "GET", "path": "/foo", "handler": "C1.foo"}],
        "external_dependencies": ["express"],
        "config_files": [".env"],
        "database_entities": ["User"]
    }
    
    kg_text = _format_knowledge_graph(data, "small-repo")
    assert "more modules omitted" not in kg_text
    assert "Framework: nestjs" in kg_text
    
    dep_rows = [
        {"module_path": "m1.ts", "imports": ["m2.ts"], "external_dependencies": ["express"]}
    ]
    dg_text = _format_dependency_graph(dep_rows, "small-repo")
    assert "m1.ts imports: m2.ts" in dg_text

def test_builder_large_repo(capsys):
    os.environ["OLLAMA_NUM_CTX"] = "8192"
    
    # 601 modules like ack-nestjs-boilerplate
    module_rows = []
    dep_rows = []
    for i in range(601):
        module_rows.append({
            "path": f"module{i}.ts",
            "imports": [f"module{i+1}.ts", f"module{i+2}.ts"],
            "classes": [f"Class{i}"]
        })
        dep_rows.append({
            "module_path": f"module{i}.ts",
            "imports": [f"module{i+1}.ts", f"module{i+2}.ts"],
            "external_dependencies": ["express", "typeorm"]
        })
        
    data = {
        "framework": "nestjs",
        "framework_version": "1.0",
        "module_rows": module_rows,
        "endpoints": [{"method": "GET", "path": f"/foo{i}", "handler": "h"} for i in range(10)],
        "external_dependencies": ["express", "typeorm"],
        "config_files": [".env"],
        "database_entities": ["User"]
    }
    
    import app.context.token_budget
    if hasattr(app.context.token_budget.compute_context_token_budget, "_budget_logged"):
        delattr(app.context.token_budget.compute_context_token_budget, "_budget_logged")
        
    kg_text = _format_knowledge_graph(data, "large-repo")
    assert "more modules omitted (token budget)" in kg_text
    
    captured_kg = capsys.readouterr()
    assert "WARNING: Repo large-repo knowledge_graph context exceeds token budget" in captured_kg.out
    
    dg_text = _format_dependency_graph(dep_rows, "large-repo")
    assert "more modules omitted (token budget)" in dg_text
    captured_dg = capsys.readouterr()
    assert "WARNING: Repo large-repo dependency_graph context exceeds token budget" in captured_dg.out


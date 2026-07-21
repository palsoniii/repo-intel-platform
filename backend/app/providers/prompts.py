"""
Summary prompt template -- Week 2 roadmap task (Mon-Wed Jul 28-30: "Prompt template
design for repository summary -- iterate against Qwen2.5-Coder only"). Passed to
BaseLLMProvider.generate_summary(), which does `prompt_template.format(context=context)`.

Output shape (overview/tech_stack/services/dependencies) intentionally mirrors
frontend/src/lib/types.ts's RepoSummary, so the two ends of the pipeline agree on a
shape without a translation layer -- pipeline.py's JSON parsing just needs a
snake_case -> camelCase mapping at the API boundary, not a schema redesign.
"""

SUMMARY_PROMPT_TEMPLATE = """\
You are analyzing a software repository from the structured context below. Base your \
answer ONLY on facts present in the context -- do not invent classes, functions, \
dependencies, or endpoints that aren't listed there. Respond with a single JSON \
object with exactly these keys:

- "overview": a 2-4 sentence plain-English description of what this repository does.
- "tech_stack": a list of frameworks/languages/major libraries actually named in the context.
- "services": short descriptions of the repository's main services or entry points \
(e.g. "HTTP server", "background worker"), inferred only from the modules and \
endpoints given.
- "dependencies": a list of external dependency names from the context.

If the context doesn't contain enough information for a field, return an empty list \
(for tech_stack/services/dependencies) or state that plainly in "overview" -- never \
guess or fill in a plausible-sounding value that isn't supported by the context.

Context:
{context}

Respond with only the JSON object and no other text.
"""

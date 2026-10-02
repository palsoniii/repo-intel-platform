"""
Product layer: the dashboard the platform is demonstrated with.

The research code (pipeline.py, evaluation/) re-clones and re-parses on every request,
which is right for an experiment and wrong for a product. This package analyses a
repository once, stores the result, and serves every view from that stored result.
It reuses the parsers, graph builder and Ollama provider unchanged, and writes nothing
the evaluation harness reads.
"""

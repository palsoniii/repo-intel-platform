import re

with open("app/evaluation/harness.py", "r") as f:
    content = f.read()

# Remove top-level import
content = re.sub(r"from app\.db\.neo4j_client import get_driver\n", "", content)

# Inject into run_evaluation where it's used
replacement = """    if not context_pack:
        from app.db.neo4j_client import get_driver
        driver = driver or get_driver()"""

content = re.sub(r"\s*driver = driver or get_driver\(\)", "\n" + replacement, content)

with open("app/evaluation/harness.py", "w") as f:
    f.write(content)

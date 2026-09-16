"""
Verifies that key backend modules import without errors.
Catches syntax errors, missing dependencies, and circular imports
without needing a running database or Ollama.

Run: venv\\Scripts\\python.exe scripts\\import_check.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MODULES = [
    ("app.router.service", ["RouterService", "_build_context_block"]),
    ("app.router.constants", ["RouterAction", "RouterResult"]),
    ("app.services.ai", ["AIService"]),
    ("app.services.smart_llm", ["SmartLLM"]),
]

failed = []
for module_path, names in MODULES:
    try:
        mod = __import__(module_path, fromlist=names)
        for name in names:
            if not hasattr(mod, name):
                raise ImportError(f"{name} not found in {module_path}")
        print(f"  OK  {module_path}")
    except Exception as exc:
        print(f"  FAIL {module_path}: {exc}")
        failed.append(module_path)

print()
if failed:
    print(f"FAILED: {len(failed)} module(s) could not be imported")
    sys.exit(1)
else:
    print(f"All {len(MODULES)} modules imported successfully")

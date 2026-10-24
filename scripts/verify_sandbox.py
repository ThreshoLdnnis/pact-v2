"""Independent read-only verifier. Usage: python scripts/verify_sandbox.py data/pact.db"""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.sandbox.acceptance import inspect_database

if __name__ == "__main__":
    result = inspect_database(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)

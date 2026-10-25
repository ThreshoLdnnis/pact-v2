"""Small .env reader: no shell evaluation and environment always wins."""
import os
from pathlib import Path

ALLOWED = {"PACT_MODEL_PROVIDER", "PACT_LLM_BASE_URL", "PACT_LLM_MODEL", "PACT_LLM_API_KEY", "PACT_LLM_FORMAT", "PACT_DATABASE_URL", "PACT_DEMO_PIN", "PACT_OLLAMA_URL", "PACT_OLLAMA_MODEL", "PACT_SANDBOX_CONTROLS", "PACT_SANDBOX_ADMIN_TOKEN"}


def load_local_env(path=None):
    path = Path(path) if path else Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return
    for line in path.read_text("utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key not in ALLOWED:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)

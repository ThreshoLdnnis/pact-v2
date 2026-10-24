"""First-run setup for the source/deployment archive. No bank/model credentials needed."""
import os
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if sys.version_info < (3, 12):
    raise SystemExit("Python 3.12 or newer is required.")
target = ROOT / ".venv"
python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not python.exists():
    venv.create(target, with_pip=True)
ready = target / ".pact-ready"
fingerprint = hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()
if not ready.exists() or ready.read_text() != fingerprint:
    subprocess.run([str(python), "-m", "pip", "install", "-r", "requirements.txt"], check=True)
    ready.write_text(fingerprint)
if not (ROOT / "apps/workbench/dist/index.html").exists():
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise SystemExit("Frontend not built. Install Node.js 24+, then run npm ci && npm run build in apps/workbench.")
    subprocess.run([npm, "ci"], cwd=ROOT / "apps/workbench", check=True)
    subprocess.run([npm, "run", "build"], cwd=ROOT / "apps/workbench", check=True)
print("Ready. Start: .venv Python -m uvicorn pact.app:create_app --factory --host 127.0.0.1 --port 8000")

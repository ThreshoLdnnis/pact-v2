"""First-run setup for the source/deployment archive. No bank/model credentials needed."""
import os
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import venv
import platform

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
    wheel_info = ROOT / "WHEELHOUSE.json"
    compatible = False
    if wheel_info.exists():
        bundle = json.loads(wheel_info.read_text("utf-8"))
        compatible = bundle["python"] == f"{sys.version_info.major}.{sys.version_info.minor}" and bundle["platform"] == sys.platform and bundle["machine"].lower() == platform.machine().lower()
    if compatible:
        for name, expected in bundle["files"].items():
            actual = hashlib.sha256((ROOT / "wheels" / name).read_bytes()).hexdigest()
            if actual != expected:
                raise SystemExit("Bundled dependency integrity check failed: " + name)
        subprocess.run([str(python), "-m", "pip", "install", "--no-index", "--find-links", "wheels", "--require-hashes", "-r", "requirements-offline.txt"], check=True)
    else:
        subprocess.run([str(python), "-m", "pip", "install", "-r", "requirements.txt"], check=True)
    ready.write_text(fingerprint)
if not (ROOT / "apps/workbench/dist/index.html").exists():
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise SystemExit("Frontend not built. Install Node.js 24+, then run npm ci && npm run build in apps/workbench.")
    subprocess.run([npm, "ci"], cwd=ROOT / "apps/workbench", check=True)
    subprocess.run([npm, "run", "build"], cwd=ROOT / "apps/workbench", check=True)
print("Ready. Start: .venv Python -m uvicorn pact.app:create_app --factory --host 127.0.0.1 --port 8000")

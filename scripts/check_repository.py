"""Check versioned JSON, local Markdown links and accidental local-data commits."""
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

root = Path(__file__).resolve().parents[1]
names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
files = [root / name for name in names if name and (root / name).is_file()]
issues = []
json_count, link_count = 0, 0
for path in files:
    name = path.relative_to(root).as_posix()
    if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example") or any(p in {".venv", "node_modules"} for p in path.parts) or path.suffix in {".db", ".sqlite", ".sqlite3", ".key", ".pem"}:
        issues.append(name + ": local environment/data must not be versioned")
    data = path.read_bytes()
    if re.search(rb"sk-[A-Za-z0-9_-]{24,}", data):
        issues.append(name + ": potential credential; value suppressed")
    if path.suffix == ".json":
        try:
            json.loads(data)
            json_count += 1
        except (ValueError, UnicodeError):
            issues.append(name + ": invalid JSON")
    if path.suffix != ".md":
        continue
    text = data.decode("utf-8")
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
        value = match.group(1).strip().strip("<>").split(' "', 1)[0]
        url = urlsplit(value)
        if url.scheme or not url.path:
            continue
        target = (path.parent / unquote(url.path)).resolve()
        link_count += 1
        if not target.exists():
            issues.append(name + ": missing local link " + url.path)
if issues:
    print(json.dumps({"passed": False, "issues": issues}, ensure_ascii=False, indent=2))
    raise SystemExit(1)
print(json.dumps({"passed": True, "versioned_files_checked": len(files), "json_files": json_count, "local_links": link_count}))

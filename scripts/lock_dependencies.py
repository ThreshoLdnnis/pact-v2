"""Pin the runtime dependency closure from the verified environment."""
from importlib.metadata import distribution
from pathlib import Path
from packaging.requirements import Requirement

root = Path(__file__).resolve().parents[1]
pending = ["fastapi", "sqlalchemy", "uvicorn", "httpx", "pydantic", "tzdata"]
resolved = {}
while pending:
    name = pending.pop().lower().replace("_", "-")
    if name in resolved:
        continue
    d = distribution(name)
    resolved[name] = d.version
    for value in d.requires or []:
        requirement = Requirement(value)
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
            pending.append(requirement.name)
(root / "requirements.txt").write_text("# Verified runtime dependency closure; Python 3.12\n" + "\n".join(f"{name}=={version}" for name, version in sorted(resolved.items())) + "\n", encoding="utf-8")
(root / "requirements-dev.txt").write_text("-r requirements.txt\npytest==" + distribution("pytest").version + "\npip-audit==" + distribution("pip-audit").version + "\n", encoding="utf-8")
print(f"Locked {len(resolved)} runtime packages")

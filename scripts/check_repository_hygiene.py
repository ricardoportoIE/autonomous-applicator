"""Check tracked files for credential patterns and accidentally published local data."""

import json
import re
import subprocess
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True)  # noqa: S603, S607
    paths = [path for path in result.stdout.decode("utf-8").split("\0") if path]
    patterns = [
        re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{30,}"),
        re.compile(r"gh[opusr]_[A-Za-z0-9_]{30,}"),
    ]
    local_profile = root / "data" / "ricardo-profile.json"
    contacts = []
    if local_profile.exists():
        profile = json.loads(local_profile.read_text(encoding="utf-8"))
        contacts = [profile[key] for key in ("email", "phone") if profile.get(key)]
    failures = []
    for name in paths:
        path = root / name
        if (
            name.startswith(("data/", "tmp/", "output/", ".venv/"))
            or name == ".env"
            or name.endswith((".sqlite3", ".log"))
        ):
            failures.append(f"Private data path tracked: {name}")
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(pattern.search(text) for pattern in patterns) or any(
            contact in text for contact in contacts
        ):
            failures.append(f"Potential private information in: {name}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(
        f"Repository hygiene passed for {len(paths)} tracked files; no credentials or local contact details found."
    )


if __name__ == "__main__":
    main()

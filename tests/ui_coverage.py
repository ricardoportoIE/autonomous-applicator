"""Collect precise V8 coverage from local dashboard tests, without recording page data."""

import hashlib
import json
from pathlib import Path


def start_coverage(page):
    session = page.context.new_cdp_session(page)
    session.send("Profiler.enable")
    session.send("Profiler.startPreciseCoverage", {"callCount": True, "detailed": True})
    return session


def save_coverage(session, name):
    scripts = session.send("Profiler.takePreciseCoverage")["result"]
    results = []
    for script in scripts:
        filename = script["url"].rsplit("/", 1)[-1]
        if filename not in {"app.js", "ui.js"}:
            continue
        source = Path("src/applicator/static") / filename
        results.append(
            {
                **script,
                "url": source.resolve().as_uri(),
                "source": source.read_text(encoding="utf-8"),
            }
        )
    folder = Path("test-results/frontend-coverage")
    folder.mkdir(parents=True, exist_ok=True)
    filename = hashlib.sha256(name.encode()).hexdigest()[:20] + ".json"
    (folder / filename).write_text(json.dumps({"result": results}), encoding="utf-8")
    session.detach()

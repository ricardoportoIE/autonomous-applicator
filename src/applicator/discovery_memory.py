"""Durable read backoff, separate from fit exclusions and application decisions."""

import json
import re
from datetime import UTC, datetime, timedelta
from typing import cast

from .store import Store


class DiscoveryMemory:
    def __init__(self, store: Store):
        self.store = store

    def holds(self) -> dict[str, dict[str, str | int]]:
        return cast(
            dict[str, dict[str, str | int]],
            json.loads(self.store.get_config("discovery_read_holds") or "{}"),
        )

    def waiting_until(self, key: str, *, now: datetime | None = None) -> str | None:
        row = self.holds().get(key)
        if row and datetime.fromisoformat(str(row["retry_at"])) > (now or datetime.now(UTC)):
            return str(row["retry_at"])
        return None

    def excluded_ids(self, *, known: bool = False, now: datetime | None = None) -> set[str]:
        current = now or datetime.now(UTC)
        excluded = self.store.discarded_job_ids("linkedin")
        excluded.update(
            key
            for key, row in self.holds().items()
            if key != "search" and datetime.fromisoformat(str(row["retry_at"])) > current
        )
        if known:
            excluded.update(
                row["source_id"] for row in self.store.applications() if row["source"] == "linkedin"
            )
        return excluded

    def defer(self, key: str, error_code: str, *, now: datetime | None = None) -> str:
        if not re.fullmatch(r"search|[0-9]{1,30}", key):
            raise ValueError("Invalid discovery read identifier")
        if error_code not in {"TimeoutError", "Error", "ReviewRequired", "ValueError"}:
            error_code = "ReadError"
        current = now or datetime.now(UTC)
        with self.store.connect(True) as db:
            row = db.execute("SELECT value FROM config WHERE key='discovery_read_holds'").fetchone()
            holds = json.loads(row[0]) if row else {}
            failures = min(int(holds.get(key, {}).get("failures", 0)) + 1, 5)
            retry_at = (current + timedelta(minutes=min(5 * 2 ** (failures - 1), 60))).isoformat()
            holds[key] = {"failures": failures, "retry_at": retry_at, "error_code": error_code}
            db.execute(
                "INSERT OR REPLACE INTO config VALUES('discovery_read_holds',?)",
                (json.dumps(holds),),
            )
            self.store.event(
                db,
                "discovery_read_deferred",
                json.dumps({"source": "linkedin", "key": key, **holds[key]}),
            )
        return retry_at

    def resolved(self, key: str) -> None:
        with self.store.connect(True) as db:
            row = db.execute("SELECT value FROM config WHERE key='discovery_read_holds'").fetchone()
            holds = json.loads(row[0]) if row else {}
            holds.pop(key, None)
            db.execute(
                "INSERT OR REPLACE INTO config VALUES('discovery_read_holds',?)",
                (json.dumps(holds),),
            )

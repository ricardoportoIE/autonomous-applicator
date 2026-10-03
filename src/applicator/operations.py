"""Durable, single-owner application processing and stage-level diagnostics."""

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from .store import Store


class OperationBusy(ValueError):
    """Another application operation already owns this workspace."""


class Operation:
    def __init__(self, store: Store, run_id: str):
        self.store, self.run_id = store, run_id
        self.completion_status = "completed"

    def progress(
        self, stage: str, detail: str, app_id: int | None = None, *, clear_application: bool = False
    ) -> None:
        with self.store.connect(True) as db:
            row = db.execute(
                "SELECT application_id FROM application_runs WHERE id=? AND status='running'",
                (self.run_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Application operation no longer owns this run")
            current = None if clear_application else app_id if app_id is not None else row[0]
            now = datetime.now(UTC).isoformat()
            db.execute(
                "UPDATE application_runs SET application_id=?,stage=?,detail=?,updated=?,"
                "stage_started=CASE WHEN stage!=? OR application_id IS NOT ? THEN ? ELSE stage_started END "
                "WHERE id=?",
                (current, stage, detail, now, stage, current, now, self.run_id),
            )
            self.store.event(
                db,
                "application_stage",
                json.dumps({"run_id": self.run_id, "stage": stage, "detail": detail}),
                current,
            )

    def result(self, outcome: str, error_code: str | None = None) -> None:
        with self.store.connect(True) as db:
            row = db.execute(
                "SELECT application_id,stage FROM application_runs WHERE id=? AND status='running'",
                (self.run_id,),
            ).fetchone()
            if row is None or row[0] is None:
                raise ValueError("Select an application before recording its result")
            now = datetime.now(UTC).isoformat()
            db.execute(
                "INSERT INTO application_run_results(run_id,application_id,outcome,stage,error_code,finished) "
                "VALUES(?,?,?,?,?,?)",
                (self.run_id, row[0], outcome, row[1], error_code, now),
            )
            self.store.event(
                db,
                "application_processing_result",
                json.dumps(
                    {
                        "run_id": self.run_id,
                        "stage": row[1],
                        "outcome": outcome,
                        "error_code": error_code,
                    }
                ),
                row[0],
            )

    def finish(self, status: str = "completed", error_code: str | None = None) -> None:
        with self.store.connect(True) as db:
            row = db.execute(
                "SELECT application_id,stage FROM application_runs WHERE id=? AND status='running'",
                (self.run_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Application operation no longer owns this run")
            now = datetime.now(UTC).isoformat()
            db.execute(
                "UPDATE application_runs SET status=?,error_code=?,updated=?,finished=? WHERE id=?",
                (status, error_code, now, now, self.run_id),
            )
            self.store.event(
                db,
                "application_run_finished",
                json.dumps(
                    {
                        "run_id": self.run_id,
                        "stage": row[1],
                        "status": status,
                        "error_code": error_code,
                    }
                ),
                row[0],
            )


class Operations:
    def __init__(self, store: Store):
        self.store = store

    @contextmanager
    def run(self, kind: str, app_id: int | None = None) -> Iterator[Operation]:
        run_id = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat()
        with self.store.connect(True) as db:
            if (
                app_id is not None
                and not db.execute("SELECT 1 FROM applications WHERE id=?", (app_id,)).fetchone()
            ):
                raise KeyError(app_id)
            try:
                db.execute(
                    "INSERT INTO application_runs(id,kind,status,application_id,stage,detail,started,"
                    "updated,stage_started) VALUES(?,?,'running',?,'starting','Starting application processing.',?,?,?)",
                    (run_id, kind, app_id, now, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise OperationBusy(
                    "Application processing is already running. Check the live queue monitor."
                ) from exc
            self.store.event(
                db, "application_run_started", json.dumps({"run_id": run_id, "kind": kind}), app_id
            )
        operation = Operation(self.store, run_id)
        try:
            yield operation
        except Exception as exc:
            operation.finish("failed", type(exc).__name__)
            raise
        else:
            with self.store.connect() as db:
                active = db.execute(
                    "SELECT 1 FROM application_runs WHERE id=? AND status='running'", (run_id,)
                ).fetchone()
            if active:
                operation.finish(operation.completion_status)

    def status(self) -> dict[str, Any]:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT r.*,a.job FROM application_runs r LEFT JOIN applications a ON a.id=r.application_id "
                "ORDER BY r.rowid DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return {"run": None, "results": []}
            run = dict(row)
            job = json.loads(run.pop("job")) if run["job"] else None
            run["job"] = {"title": job["title"], "company": job["company"]} if job else None
            results = []
            for item in db.execute(
                "SELECT r.*,a.job FROM application_run_results r JOIN applications a ON a.id=r.application_id "
                "ORDER BY r.id DESC LIMIT 50",
            ):
                result = dict(item)
                job = json.loads(result.pop("job"))
                result["job"] = {"title": job["title"], "company": job["company"]}
                results.append(result)
            return {"run": run, "results": results}

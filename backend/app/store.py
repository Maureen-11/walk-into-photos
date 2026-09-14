from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, payload TEXT NOT NULL, path TEXT NOT NULL, filename TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def save_analysis(self, analysis_id: str, payload: str, path: str, filename: str) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO analyses(id,payload,path,filename) VALUES (?,?,?,?)", (analysis_id, payload, path, filename))

    def get_analysis(self, analysis_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT id,payload,path,filename FROM analyses WHERE id=?", (analysis_id,)).fetchone()
        return dict(row) if row else None

    def save_job(self, job_id: str, payload: str) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO jobs(id,payload) VALUES (?,?)", (job_id, payload))

    def get_job(self, job_id: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        return str(row["payload"]) if row else None

    def list_jobs(self) -> list[str]:
        with self._connect() as db:
            return [str(row["payload"]) for row in db.execute("SELECT payload FROM jobs")]

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .models import QuarkLink


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    """Small SQLite checkpoint store for resumable batch processing."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        job_key TEXT PRIMARY KEY,
                        source_url TEXT NOT NULL,
                        passcode TEXT,
                        status TEXT NOT NULL,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        error TEXT,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )

    def upsert_extracted(self, item: QuarkLink) -> None:
        timestamp = _now()
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO jobs(job_key, source_url, passcode, status, created_at, updated_at)
                    VALUES (?, ?, ?, 'EXTRACTED', ?, ?)
                    ON CONFLICT(job_key) DO UPDATE SET
                        source_url=excluded.source_url,
                        passcode=COALESCE(excluded.passcode, jobs.passcode),
                        updated_at=excluded.updated_at
                    """,
                    (item.key, item.normalized_url, item.passcode, timestamp, timestamp),
                )

    def update(self, job_key: str, status: str, *, metadata: dict | None = None, error: str | None = None) -> None:
        with closing(self._connect()) as connection:
            with connection:
                if metadata is None:
                    row = connection.execute(
                        "SELECT metadata_json FROM jobs WHERE job_key=?",
                        (job_key,),
                    ).fetchone()
                    metadata_json = row["metadata_json"] if row is not None else "{}"
                else:
                    metadata_json = json.dumps(metadata, ensure_ascii=False)
                connection.execute(
                    """
                    UPDATE jobs
                    SET status=?, metadata_json=?, error=?, attempts=attempts+1, updated_at=?
                    WHERE job_key=?
                    """,
                    (status, metadata_json, error, _now(), job_key),
                )

    def update_metadata(
        self,
        job_key: str,
        patch: dict,
        *,
        status: str | None = None,
        error: str | None = None,
    ) -> None:
        """Merge publisher metadata without overwriting prior Quark checkpoints."""

        with closing(self._connect()) as connection:
            with connection:
                row = connection.execute(
                    "SELECT metadata_json, status, error FROM jobs WHERE job_key=?",
                    (job_key,),
                ).fetchone()
                if row is None:
                    return
                try:
                    metadata = json.loads(row["metadata_json"] or "{}")
                except json.JSONDecodeError:
                    metadata = {}
                metadata.update(patch)
                connection.execute(
                    """
                    UPDATE jobs
                    SET status=?, metadata_json=?, error=?, updated_at=?
                    WHERE job_key=?
                    """,
                    (
                        status or row["status"],
                        json.dumps(metadata, ensure_ascii=False),
                        error if error is not None else row["error"],
                        _now(),
                        job_key,
                    ),
                )

    def list_jobs(self) -> list[sqlite3.Row]:
        with closing(self._connect()) as connection:
            return list(connection.execute("SELECT * FROM jobs ORDER BY created_at"))

    def get(self, job_key: str) -> sqlite3.Row | None:
        with closing(self._connect()) as connection:
            return connection.execute(
                "SELECT * FROM jobs WHERE job_key=?",
                (job_key,),
            ).fetchone()

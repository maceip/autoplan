"""Persistent store for the chief-of-staff review queue.

SQLite-backed, single-file, local-only. Every queue item, operator
decision, and chief action is a persisted row; the queue UI and the
chief-of-staff agent read and write only through this store.
"""

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

STATUSES = [
    "queued",
    "triaged",
    "in_progress",
    "needs_review",
    "approved",
    "changes_requested",
    "landing",
    "landed",
    "done",
    "rejected",
    "snoozed",
    "failed",
]

KINDS = ["code_change", "task", "decision", "idea", "comms"]

_ITEM_FIELDS = [
    "source_agent",
    "kind",
    "title",
    "body",
    "repo_path",
    "branch",
    "target_branch",
    "test_command",
    "demo_url",
    "priority",
    "status",
    "recommendation",
]


def _now() -> float:
    return time.time()


class QueueStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    source_agent TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT DEFAULT '',
                    repo_path TEXT DEFAULT '',
                    branch TEXT DEFAULT '',
                    target_branch TEXT DEFAULT '',
                    test_command TEXT DEFAULT '',
                    demo_url TEXT DEFAULT '',
                    priority INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'queued',
                    recommendation TEXT DEFAULT '',
                    evidence_json TEXT DEFAULT '{}',
                    result_json TEXT DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    actor TEXT DEFAULT 'human',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    message TEXT DEFAULT '',
                    created_at REAL NOT NULL
                );
                """
            )
            self._conn.commit()

    def _row_to_item(self, row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
        item["result"] = json.loads(item.pop("result_json") or "{}")
        return item

    def create_item(self, data: Dict[str, Any]) -> Dict[str, Any]:
        item_id = uuid.uuid4().hex[:12]
        now = _now()
        values = {field: data.get(field, "" if field != "priority" else 0) for field in _ITEM_FIELDS}
        values["status"] = "queued"
        with self._lock:
            self._conn.execute(
                """INSERT INTO items (id, source_agent, kind, title, body, repo_path,
                   branch, target_branch, test_command, demo_url, priority, status,
                   recommendation, evidence_json, result_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', ?, ?)""",
                (
                    item_id,
                    values["source_agent"] or "unknown-agent",
                    values["kind"] if values["kind"] in KINDS else "task",
                    values["title"],
                    values["body"],
                    values["repo_path"],
                    values["branch"],
                    values["target_branch"] or "main",
                    values["test_command"],
                    values["demo_url"],
                    int(values["priority"] or 0),
                    values["status"],
                    values["recommendation"],
                    now,
                    now,
                ),
            )
            self._conn.commit()
        self.add_event(item_id, "created", f"Submitted by {values['source_agent'] or 'unknown-agent'}")
        return self.get_item(item_id)

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return self._row_to_item(row) if row else None

    def list_items(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM items WHERE status = ? ORDER BY priority DESC, created_at ASC",
                    (status,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM items ORDER BY priority DESC, created_at ASC"
                ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def update_item(self, item_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        allowed = set(_ITEM_FIELDS) | {"evidence", "result"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_item(item_id)
        sets, params = [], []
        for key, value in updates.items():
            if key in ("evidence", "result"):
                sets.append(f"{key}_json = ?")
                params.append(json.dumps(value))
            else:
                sets.append(f"{key} = ?")
                params.append(value)
        sets.append("updated_at = ?")
        params.extend([_now(), item_id])
        with self._lock:
            self._conn.execute(f"UPDATE items SET {', '.join(sets)} WHERE id = ?", params)
            self._conn.commit()
        return self.get_item(item_id)

    def add_decision(self, item_id: str, action: str, note: str = "", actor: str = "human") -> Dict[str, Any]:
        decision = {
            "id": uuid.uuid4().hex[:12],
            "item_id": item_id,
            "action": action,
            "note": note,
            "actor": actor,
            "created_at": _now(),
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO decisions (id, item_id, action, note, actor, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (decision["id"], item_id, action, note, actor, decision["created_at"]),
            )
            self._conn.commit()
        self.add_event(item_id, f"decision:{action}", note or action)
        return decision

    def list_decisions(self, item_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM decisions WHERE item_id = ? ORDER BY created_at ASC", (item_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def add_event(self, item_id: str, event_type: str, message: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (id, item_id, type, message, created_at) VALUES (?, ?, ?, ?, ?)",
                (uuid.uuid4().hex[:12], item_id, event_type, message, _now()),
            )
            self._conn.commit()

    def list_events(self, item_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE item_id = ? ORDER BY created_at ASC", (item_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def counts(self) -> Dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM items GROUP BY status"
            ).fetchall()
        result = {status: 0 for status in STATUSES}
        for row in rows:
            result[row["status"]] = row["n"]
        return result

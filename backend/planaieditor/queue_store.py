"""Persistent store for the chief-of-staff review queue, agent runs, ownership, and WebClaw sessions.

SQLite-backed, single-file, local-only. Every queue item, operator
decision, chief action, agent run, workspace claim, and WebClaw session
is a persisted row; the UIs and the chief-of-staff agent read and write
only through this store.
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

RUN_STATES = ["queued", "running", "succeeded", "failed", "stopped"]

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

_RUN_FIELDS = [
    "service",
    "model",
    "prompt",
    "cwd",
    "branch",
    "session_id",
    "queue_item_id",
    "webclaw_session_key",
    "state",
    "exit_code",
    "response_text",
    "stdout_tail",
    "stderr_tail",
    "started_at",
    "last_output_at",
    "finished_at",
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
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    service TEXT NOT NULL,
                    model TEXT DEFAULT '',
                    prompt TEXT NOT NULL,
                    cwd TEXT DEFAULT '',
                    branch TEXT DEFAULT '',
                    session_id TEXT DEFAULT '',
                    queue_item_id TEXT DEFAULT '',
                    webclaw_session_key TEXT DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'queued',
                    exit_code INTEGER,
                    response_text TEXT DEFAULT '',
                    stdout_tail TEXT DEFAULT '',
                    stderr_tail TEXT DEFAULT '',
                    metadata_json TEXT DEFAULT '{}',
                    started_at REAL NOT NULL,
                    last_output_at REAL NOT NULL,
                    finished_at REAL
                );
                CREATE TABLE IF NOT EXISTS ownership (
                    id TEXT PRIMARY KEY,
                    repo TEXT NOT NULL,
                    worktree TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    service TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    claimed_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    key TEXT PRIMARY KEY,
                    friendly_id TEXT UNIQUE NOT NULL,
                    label TEXT DEFAULT '',
                    service TEXT NOT NULL DEFAULT 'antigravity',
                    model TEXT DEFAULT '',
                    cwd TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    session_key TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content_json TEXT NOT NULL DEFAULT '[]',
                    details_json TEXT NOT NULL DEFAULT '{}',
                    is_error INTEGER NOT NULL DEFAULT 0,
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
        return self.get_item(item_id)  # type: ignore[return-value]

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

    # ---- Agent runs & workspace ownership -------------------------------

    def _row_to_run(self, row: sqlite3.Row) -> Dict[str, Any]:
        run = dict(row)
        run["metadata"] = json.loads(run.pop("metadata_json") or "{}")
        return run

    def create_run(self, data: Dict[str, Any]) -> Dict[str, Any]:
        run_id = data.get("id") or f"run_{uuid.uuid4().hex[:10]}"
        now = _now()
        state = data.get("state") if data.get("state") in RUN_STATES else "running"
        metadata = data.get("metadata") or {}
        with self._lock:
            self._conn.execute(
                """INSERT INTO runs (
                    id, service, model, prompt, cwd, branch, session_id,
                    queue_item_id, webclaw_session_key, state, exit_code,
                    response_text, stdout_tail, stderr_tail, metadata_json,
                    started_at, last_output_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    str(data.get("service") or "antigravity"),
                    str(data.get("model") or ""),
                    str(data.get("prompt") or ""),
                    str(data.get("cwd") or ""),
                    str(data.get("branch") or ""),
                    str(data.get("session_id") or ""),
                    str(data.get("queue_item_id") or ""),
                    str(data.get("webclaw_session_key") or ""),
                    state,
                    data.get("exit_code"),
                    str(data.get("response_text") or ""),
                    str(data.get("stdout_tail") or ""),
                    str(data.get("stderr_tail") or ""),
                    json.dumps(metadata),
                    float(data.get("started_at") or now),
                    float(data.get("last_output_at") or now),
                    data.get("finished_at"),
                ),
            )
            self._conn.commit()
        return self.get_run(run_id)  # type: ignore[return-value]

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._row_to_run(row) if row else None

    def list_runs(
        self,
        service: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if service:
            clauses.append("service = ?")
            params.append(service)
        if state:
            clauses.append("state = ?")
            params.append(state)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM runs {where} ORDER BY started_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def update_run(self, run_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        allowed = set(_RUN_FIELDS) | {"metadata"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_run(run_id)
        sets, params = [], []
        for key, value in updates.items():
            if key == "metadata":
                sets.append("metadata_json = ?")
                params.append(json.dumps(value))
            else:
                sets.append(f"{key} = ?")
                params.append(value)
        if "last_output_at" not in updates:
            sets.append("last_output_at = ?")
            params.append(_now())
        params.append(run_id)
        with self._lock:
            self._conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id = ?", params)
            self._conn.commit()
        return self.get_run(run_id)

    def claim_ownership(
        self, repo: str, worktree: str, branch: str, service: str, run_id: str
    ) -> Dict[str, Any]:
        now = _now()
        with self._lock:
            existing = self._conn.execute(
                """SELECT o.*, r.state AS run_state
                   FROM ownership o
                   LEFT JOIN runs r ON r.id = o.run_id
                   WHERE o.repo = ? AND o.branch = ?""",
                (repo, branch),
            ).fetchall()
            for row in existing:
                if row["run_state"] in ("queued", "running"):
                    raise ValueError(
                        f"Workspace '{repo}' branch '{branch}' is already claimed by active run {row['run_id']} ({row['service']})."
                    )
                self._conn.execute("DELETE FROM ownership WHERE id = ?", (row["id"],))
            claim_id = uuid.uuid4().hex[:12]
            self._conn.execute(
                """INSERT INTO ownership (id, repo, worktree, branch, service, run_id, claimed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (claim_id, repo, worktree, branch, service, run_id, now),
            )
            self._conn.commit()
        return {
            "id": claim_id,
            "repo": repo,
            "worktree": worktree,
            "branch": branch,
            "service": service,
            "run_id": run_id,
            "claimed_at": now,
        }

    def release_ownership(self, run_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM ownership WHERE run_id = ?", (run_id,))
            self._conn.commit()

    def list_ownership(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM ownership ORDER BY claimed_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    # ---- WebClaw persisted sessions & messages --------------------------

    def _row_to_chat_message(self, row: sqlite3.Row) -> Dict[str, Any]:
        raw = dict(row)
        return {
            "id": raw["id"],
            "role": raw["role"],
            "content": json.loads(raw["content_json"] or "[]"),
            "details": json.loads(raw["details_json"] or "{}"),
            "isError": bool(raw["is_error"]),
            "timestamp": int(float(raw["created_at"]) * 1000),
        }

    def _row_to_chat_session(self, row: sqlite3.Row) -> Dict[str, Any]:
        sess = dict(row)
        last_msg = None
        with self._lock:
            msg_row = self._conn.execute(
                "SELECT * FROM chat_messages WHERE session_key = ? ORDER BY created_at DESC LIMIT 1",
                (sess["key"],),
            ).fetchone()
        if msg_row:
            last_msg = self._row_to_chat_message(msg_row)
        derived_title = sess["label"] or ""
        if not derived_title and last_msg:
            parts = last_msg.get("content") or []
            if parts and isinstance(parts[0], dict):
                derived_title = str(parts[0].get("text") or "").strip()[:60]
        if not derived_title:
            derived_title = f"{sess['service']} session"
        return {
            "key": sess["key"],
            "friendlyId": sess["friendly_id"],
            "label": sess["label"],
            "title": sess["label"] or derived_title,
            "derivedTitle": derived_title,
            "service": sess["service"],
            "model": sess["model"],
            "cwd": sess["cwd"],
            "createdAt": int(float(sess["created_at"]) * 1000),
            "updatedAt": int(float(sess["updated_at"]) * 1000),
            "lastMessage": last_msg,
        }

    def get_or_create_main_chat_session(self, default_service: str = "antigravity") -> Dict[str, Any]:
        existing = self.get_chat_session("main")
        if existing:
            return existing
        return self.create_chat_session(
            {
                "key": "agent:autoplan:main",
                "friendly_id": "main",
                "label": "Chief & Lead Agents",
                "service": default_service,
            }
        )

    def create_chat_session(self, data: Dict[str, Any]) -> Dict[str, Any]:
        now = _now()
        friendly_id = str(data.get("friendly_id") or data.get("friendlyId") or uuid.uuid4().hex[:12]).strip()
        service = str(data.get("service") or "antigravity").strip()
        key = str(data.get("key") or f"agent:{service}:{friendly_id}").strip()
        label = str(data.get("label") or "").strip()
        model = str(data.get("model") or "").strip()
        cwd = str(data.get("cwd") or "").strip()
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO chat_sessions (
                    key, friendly_id, label, service, model, cwd, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (key, friendly_id, label, service, model, cwd, now, now),
            )
            self._conn.commit()
        return self.get_chat_session(key)  # type: ignore[return-value]

    def get_chat_session(self, key_or_friendly_id: str) -> Optional[Dict[str, Any]]:
        ident = (key_or_friendly_id or "").strip()
        if not ident:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM chat_sessions WHERE key = ? OR friendly_id = ? LIMIT 1",
                (ident, ident),
            ).fetchone()
        return self._row_to_chat_session(row) if row else None

    def list_chat_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM chat_sessions ORDER BY updated_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [self._row_to_chat_session(row) for row in rows]

    def update_chat_session(self, key_or_friendly_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        sess = self.get_chat_session(key_or_friendly_id)
        if not sess:
            return None
        allowed = {"label", "service", "model", "cwd"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return sess
        sets = [f"{k} = ?" for k in updates] + ["updated_at = ?"]
        params = list(updates.values()) + [_now(), sess["key"]]
        with self._lock:
            self._conn.execute(f"UPDATE chat_sessions SET {', '.join(sets)} WHERE key = ?", params)
            self._conn.commit()
        return self.get_chat_session(sess["key"])

    def delete_chat_session(self, key_or_friendly_id: str) -> bool:
        sess = self.get_chat_session(key_or_friendly_id)
        if not sess:
            return False
        with self._lock:
            self._conn.execute("DELETE FROM chat_messages WHERE session_key = ?", (sess["key"],))
            self._conn.execute("DELETE FROM chat_sessions WHERE key = ?", (sess["key"],))
            self._conn.commit()
        return True

    def add_chat_message(
        self,
        session_key: str,
        role: str,
        text: str,
        details: Optional[Dict[str, Any]] = None,
        is_error: bool = False,
    ) -> Dict[str, Any]:
        msg_id = uuid.uuid4().hex[:12]
        now = _now()
        content = [{"type": "text", "text": text}]
        with self._lock:
            self._conn.execute(
                """INSERT INTO chat_messages (
                    id, session_key, role, content_json, details_json, is_error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    msg_id,
                    session_key,
                    role,
                    json.dumps(content),
                    json.dumps(details or {}),
                    1 if is_error else 0,
                    now,
                ),
            )
            self._conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE key = ?",
                (now, session_key),
            )
            row = self._conn.execute(
                "SELECT * FROM chat_messages WHERE id = ?", (msg_id,)
            ).fetchone()
            self._conn.commit()
        return self._row_to_chat_message(row)

    def list_chat_messages(self, session_key: str, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM (
                    SELECT * FROM chat_messages
                    WHERE session_key = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ) ORDER BY created_at ASC""",
                (session_key, int(limit)),
            ).fetchall()
        return [self._row_to_chat_message(row) for row in rows]

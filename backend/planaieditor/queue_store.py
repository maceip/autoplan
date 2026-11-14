"""Persistent store for projects, review queue, agent runs, ownership, PlanAI graphs, and evolution.

SQLite-backed, single-file, local-only. Every project, queue item, operator
decision, chief action, agent run, workspace claim, PlanAI workflow graph,
prompt evolution version, learned rule, and chat session is a persisted row.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
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

WORKFLOW_STATES = ["queued", "running", "succeeded", "failed", "stopped"]

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
    "project_id",
    "workflow_id",
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
    "project_id",
    "workflow_id",
    "role",
    "started_at",
    "last_output_at",
    "finished_at",
]


def _now() -> float:
    return time.time()


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-")
    return cleaned or f"proj-{uuid.uuid4().hex[:6]}"


def _detect_git_default_branch(repo_path: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        branch = proc.stdout.strip()
        if proc.returncode == 0 and branch and branch != "HEAD":
            return branch
    except Exception:
        pass
    return "main"


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
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    repo_path TEXT UNIQUE NOT NULL,
                    default_branch TEXT NOT NULL DEFAULT 'main',
                    test_command TEXT DEFAULT '',
                    lead_service TEXT NOT NULL DEFAULT 'xiaomi-mimo',
                    description TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
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
                    project_id TEXT DEFAULT '',
                    workflow_id TEXT DEFAULT '',
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
                    project_id TEXT DEFAULT '',
                    workflow_id TEXT DEFAULT '',
                    role TEXT DEFAULT '',
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
                    project_id TEXT DEFAULT '',
                    claimed_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    key TEXT PRIMARY KEY,
                    friendly_id TEXT UNIQUE NOT NULL,
                    label TEXT DEFAULT '',
                    service TEXT NOT NULL DEFAULT 'antigravity',
                    model TEXT DEFAULT '',
                    cwd TEXT DEFAULT '',
                    project_id TEXT DEFAULT '',
                    mode TEXT NOT NULL DEFAULT 'single',
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
                CREATE TABLE IF NOT EXISTS planai_workflows (
                    id TEXT PRIMARY KEY,
                    project_id TEXT DEFAULT '',
                    session_key TEXT DEFAULT '',
                    graph_type TEXT NOT NULL DEFAULT 'teamwork',
                    title TEXT NOT NULL,
                    goal TEXT DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'running',
                    nodes_json TEXT NOT NULL DEFAULT '[]',
                    edges_json TEXT NOT NULL DEFAULT '[]',
                    events_json TEXT NOT NULL DEFAULT '[]',
                    provenance_json TEXT NOT NULL DEFAULT '[]',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    python_code TEXT DEFAULT '',
                    evolution_gen INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    finished_at REAL
                );
                CREATE TABLE IF NOT EXISTS prompt_versions (
                    id TEXT PRIMARY KEY,
                    worker_role TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    prompt_template TEXT NOT NULL,
                    rationale TEXT DEFAULT '',
                    parent_id TEXT DEFAULT '',
                    source_workflow_id TEXT DEFAULT '',
                    pass_count INTEGER NOT NULL DEFAULT 0,
                    fail_count INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evolution_rules (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL DEFAULT '*',
                    category TEXT NOT NULL,
                    rule_text TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT DEFAULT '',
                    evidence_count INTEGER NOT NULL DEFAULT 1,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )
            self._run_migrations()
            self._conn.commit()

    def _table_columns(self, table: str) -> set[str]:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(r["name"]) for r in rows}

    def _ensure_column(self, table: str, column: str, ddl_type: str) -> None:
        if column not in self._table_columns(table):
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")

    def _run_migrations(self) -> None:
        self._ensure_column("items", "project_id", "TEXT DEFAULT ''")
        self._ensure_column("items", "workflow_id", "TEXT DEFAULT ''")
        self._ensure_column("runs", "project_id", "TEXT DEFAULT ''")
        self._ensure_column("runs", "workflow_id", "TEXT DEFAULT ''")
        self._ensure_column("runs", "role", "TEXT DEFAULT ''")
        self._ensure_column("ownership", "project_id", "TEXT DEFAULT ''")
        self._ensure_column("chat_sessions", "project_id", "TEXT DEFAULT ''")
        self._ensure_column("chat_sessions", "mode", "TEXT NOT NULL DEFAULT 'single'")

    # ---- Multi-Project Registry -----------------------------------------

    def _row_to_project(self, row: sqlite3.Row) -> Dict[str, Any]:
        proj = dict(row)
        repo = Path(proj["repo_path"])
        proj["exists"] = repo.is_dir()
        proj["is_git_repo"] = (repo / ".git").exists()
        with self._lock:
            proj["session_count"] = self._conn.execute(
                "SELECT COUNT(*) AS n FROM chat_sessions WHERE project_id = ?",
                (proj["id"],),
            ).fetchone()["n"]
            proj["active_run_count"] = self._conn.execute(
                "SELECT COUNT(*) AS n FROM runs WHERE project_id = ? AND state = 'running'",
                (proj["id"],),
            ).fetchone()["n"]
            proj["open_review_count"] = self._conn.execute(
                "SELECT COUNT(*) AS n FROM items WHERE project_id = ? AND status = 'needs_review'",
                (proj["id"],),
            ).fetchone()["n"]
            proj["workflow_count"] = self._conn.execute(
                "SELECT COUNT(*) AS n FROM planai_workflows WHERE project_id = ?",
                (proj["id"],),
            ).fetchone()["n"]
        return proj

    def ensure_default_project(
        self, root_path: Path, default_service: str = "xiaomi-mimo"
    ) -> Dict[str, Any]:
        resolved = Path(root_path).resolve()
        with self._lock:
            existing = self._conn.execute(
                "SELECT * FROM projects WHERE repo_path = ? LIMIT 1", (str(resolved),)
            ).fetchone()
        if existing:
            proj = self._row_to_project(existing)
        else:
            proj_id = _slugify(resolved.name)
            with self._lock:
                collision = self._conn.execute(
                    "SELECT 1 FROM projects WHERE id = ?", (proj_id,)
                ).fetchone()
            if collision:
                proj_id = f"{proj_id}-{uuid.uuid4().hex[:4]}"
            default_test = ""
            if (resolved / "backend" / ".venv" / "bin" / "pytest").is_file():
                default_test = "backend/.venv/bin/pytest backend/tests/test_queue.py -q"
            proj = self.create_project(
                {
                    "id": proj_id,
                    "name": resolved.name,
                    "repo_path": str(resolved),
                    "default_branch": _detect_git_default_branch(resolved),
                    "test_command": default_test,
                    "lead_service": default_service,
                    "description": "Primary AutoPlan workspace",
                },
                require_git=False,
            )

        with self._lock:
            self._conn.execute(
                "UPDATE chat_sessions SET project_id = ?, cwd = CASE WHEN cwd = '' THEN ? ELSE cwd END WHERE project_id = ''",
                (proj["id"], proj["repo_path"]),
            )
            self._conn.execute(
                "UPDATE items SET project_id = ? WHERE project_id = ''",
                (proj["id"],),
            )
            self._conn.execute(
                "UPDATE runs SET project_id = ? WHERE project_id = ''",
                (proj["id"],),
            )
            self._conn.commit()
        return self.get_project(proj["id"]) or proj

    def create_project(
        self, data: Dict[str, Any], require_git: bool = True
    ) -> Dict[str, Any]:
        raw_path = str(data.get("repo_path") or "").strip()
        if not raw_path:
            raise ValueError("Missing required field: repo_path")
        resolved = Path(raw_path).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"Directory does not exist: {resolved}")
        if require_git and not (resolved / ".git").exists():
            raise ValueError(f"Not a git repository (missing .git): {resolved}")

        with self._lock:
            dup = self._conn.execute(
                "SELECT * FROM projects WHERE repo_path = ? LIMIT 1", (str(resolved),)
            ).fetchone()
            if dup:
                return self._row_to_project(dup)

        name = str(data.get("name") or resolved.name).strip() or resolved.name
        proj_id = _slugify(str(data.get("id") or name))
        with self._lock:
            if self._conn.execute("SELECT 1 FROM projects WHERE id = ?", (proj_id,)).fetchone():
                proj_id = f"{proj_id}-{uuid.uuid4().hex[:4]}"

        default_branch = (
            str(data.get("default_branch") or "").strip()
            or _detect_git_default_branch(resolved)
        )
        test_command = str(data.get("test_command") or "").strip()
        lead_service = str(data.get("lead_service") or "xiaomi-mimo").strip()
        description = str(data.get("description") or "").strip()
        now = _now()
        with self._lock:
            self._conn.execute(
                """INSERT INTO projects (
                    id, name, repo_path, default_branch, test_command,
                    lead_service, description, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    proj_id,
                    name,
                    str(resolved),
                    default_branch,
                    test_command,
                    lead_service,
                    description,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return self.get_project(proj_id)  # type: ignore[return-value]

    def get_project(self, project_id_or_path: str) -> Optional[Dict[str, Any]]:
        ident = (project_id_or_path or "").strip()
        if not ident:
            return None
        resolved_candidate = ""
        try:
            if "/" in ident or ident.startswith("~"):
                resolved_candidate = str(Path(ident).expanduser().resolve())
        except Exception:
            resolved_candidate = ""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM projects WHERE id = ? OR repo_path = ? OR repo_path = ? LIMIT 1",
                (ident, ident, resolved_candidate),
            ).fetchone()
        return self._row_to_project(row) if row else None

    def list_projects(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM projects ORDER BY created_at ASC"
            ).fetchall()
        return [self._row_to_project(row) for row in rows]

    def update_project(self, project_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        proj = self.get_project(project_id)
        if not proj:
            return None
        allowed = {"name", "default_branch", "test_command", "lead_service", "description"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return proj
        sets = [f"{k} = ?" for k in updates] + ["updated_at = ?"]
        params = list(updates.values()) + [_now(), proj["id"]]
        with self._lock:
            self._conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", params)
            self._conn.commit()
        return self.get_project(proj["id"])

    def delete_project(self, project_id: str) -> bool:
        proj = self.get_project(project_id)
        if not proj:
            return False
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) AS n FROM projects").fetchone()["n"]
            if total <= 1:
                raise ValueError("Cannot delete the last remaining project.")
            self._conn.execute("DELETE FROM projects WHERE id = ?", (proj["id"],))
            self._conn.commit()
        return True

    def is_repo_allowed(self, candidate: Path, root_path: Path) -> bool:
        resolved = candidate.resolve()
        root_resolved = root_path.resolve()
        try:
            resolved.relative_to(root_resolved)
            return True
        except ValueError:
            pass
        for proj in self.list_projects():
            proj_root = Path(proj["repo_path"]).resolve()
            try:
                resolved.relative_to(proj_root)
                return True
            except ValueError:
                continue
        return False

    def discover_git_repos(self, search_dir: Path, limit: int = 25) -> List[Dict[str, Any]]:
        base = Path(search_dir).expanduser().resolve()
        if not base.is_dir():
            return []
        registered_paths = {Path(p["repo_path"]).resolve() for p in self.list_projects()}
        found: List[Dict[str, Any]] = []
        try:
            entries = sorted(
                base.iterdir(),
                key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
                reverse=True,
            )
        except Exception:
            return []
        for child in entries:
            if len(found) >= limit:
                break
            if child.name.startswith(".") or not child.is_dir():
                continue
            if not (child / ".git").exists():
                continue
            resolved_child = child.resolve()
            found.append(
                {
                    "name": child.name,
                    "repo_path": str(resolved_child),
                    "default_branch": _detect_git_default_branch(resolved_child),
                    "already_registered": resolved_child in registered_paths,
                }
            )
        return found

    # ---- Queue Items ----------------------------------------------------

    def _row_to_item(self, row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
        item["result"] = json.loads(item.pop("result_json") or "{}")
        return item

    def create_item(self, data: Dict[str, Any]) -> Dict[str, Any]:
        item_id = uuid.uuid4().hex[:12]
        now = _now()
        values = {
            field: data.get(field, "" if field != "priority" else 0)
            for field in _ITEM_FIELDS
        }
        values["status"] = "queued"
        if not values.get("project_id") and values.get("repo_path"):
            matched = self.get_project(str(values["repo_path"]))
            if matched:
                values["project_id"] = matched["id"]
        with self._lock:
            self._conn.execute(
                """INSERT INTO items (id, source_agent, kind, title, body, repo_path,
                   branch, target_branch, test_command, demo_url, priority, status,
                   recommendation, project_id, workflow_id, evidence_json, result_json,
                   created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', ?, ?)""",
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
                    str(values.get("project_id") or ""),
                    str(values.get("workflow_id") or ""),
                    now,
                    now,
                ),
            )
            self._conn.commit()
        self.add_event(
            item_id,
            "created",
            f"Submitted by {values['source_agent'] or 'unknown-agent'}",
        )
        return self.get_item(item_id)  # type: ignore[return-value]

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        return self._row_to_item(row) if row else None

    def list_items(
        self,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM items {where} ORDER BY priority DESC, created_at ASC",
                params,
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
            self._conn.execute(
                f"UPDATE items SET {', '.join(sets)} WHERE id = ?", params
            )
            self._conn.commit()
        return self.get_item(item_id)

    def add_decision(
        self, item_id: str, action: str, note: str = "", actor: str = "human"
    ) -> Dict[str, Any]:
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
                (
                    decision["id"],
                    item_id,
                    action,
                    note,
                    actor,
                    decision["created_at"],
                ),
            )
            self._conn.commit()
        self.add_event(item_id, f"decision:{action}", note or action)
        return decision

    def list_decisions(self, item_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            if item_id:
                rows = self._conn.execute(
                    "SELECT * FROM decisions WHERE item_id = ? ORDER BY created_at ASC",
                    (item_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?",
                    (int(limit),),
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
                "SELECT * FROM events WHERE item_id = ? ORDER BY created_at ASC",
                (item_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def counts(self, project_id: Optional[str] = None) -> Dict[str, int]:
        with self._lock:
            if project_id:
                rows = self._conn.execute(
                    "SELECT status, COUNT(*) AS n FROM items WHERE project_id = ? GROUP BY status",
                    (project_id,),
                ).fetchall()
            else:
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
                    queue_item_id, webclaw_session_key, project_id, workflow_id, role,
                    state, exit_code, response_text, stdout_tail, stderr_tail, metadata_json,
                    started_at, last_output_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    str(data.get("project_id") or ""),
                    str(data.get("workflow_id") or ""),
                    str(data.get("role") or ""),
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
            row = self._conn.execute(
                "SELECT * FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
        return self._row_to_run(row) if row else None

    def list_runs(
        self,
        service: Optional[str] = None,
        state: Optional[str] = None,
        project_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
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
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if workflow_id:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)
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
            self._conn.execute(
                f"UPDATE runs SET {', '.join(sets)} WHERE id = ?", params
            )
            self._conn.commit()
        return self.get_run(run_id)

    def claim_ownership(
        self,
        repo: str,
        worktree: str,
        branch: str,
        service: str,
        run_id: str,
        project_id: str = "",
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
                """INSERT INTO ownership (id, repo, worktree, branch, service, run_id, project_id, claimed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (claim_id, repo, worktree, branch, service, run_id, project_id, now),
            )
            self._conn.commit()
        return {
            "id": claim_id,
            "repo": repo,
            "worktree": worktree,
            "branch": branch,
            "service": service,
            "run_id": run_id,
            "project_id": project_id,
            "claimed_at": now,
        }

    def release_ownership(self, run_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM ownership WHERE run_id = ?", (run_id,))
            self._conn.commit()

    def list_ownership(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if project_id:
                rows = self._conn.execute(
                    "SELECT * FROM ownership WHERE project_id = ? ORDER BY claimed_at DESC",
                    (project_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM ownership ORDER BY claimed_at DESC"
                ).fetchall()
        return [dict(row) for row in rows]

    # ---- PlanAI Workflows & Graph Executions ----------------------------

    def _row_to_workflow(self, row: sqlite3.Row) -> Dict[str, Any]:
        wf = dict(row)
        wf["nodes"] = json.loads(wf.pop("nodes_json") or "[]")
        wf["edges"] = json.loads(wf.pop("edges_json") or "[]")
        wf["events"] = json.loads(wf.pop("events_json") or "[]")
        wf["provenance"] = json.loads(wf.pop("provenance_json") or "[]")
        wf["result"] = json.loads(wf.pop("result_json") or "{}")
        wf["queue_item_id"] = str(wf["result"].get("queue_item_id") or "")
        return wf

    def create_workflow(self, data: Dict[str, Any]) -> Dict[str, Any]:
        wf_id = str(data.get("id") or f"wf_{uuid.uuid4().hex[:10]}")
        now = _now()
        state = data.get("state") if data.get("state") in WORKFLOW_STATES else "running"
        with self._lock:
            self._conn.execute(
                """INSERT INTO planai_workflows (
                    id, project_id, session_key, graph_type, title, goal, state,
                    nodes_json, edges_json, events_json, provenance_json, result_json,
                    python_code, evolution_gen, created_at, updated_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    wf_id,
                    str(data.get("project_id") or ""),
                    str(data.get("session_key") or ""),
                    str(data.get("graph_type") or "teamwork"),
                    str(data.get("title") or "PlanAI Workflow"),
                    str(data.get("goal") or ""),
                    state,
                    json.dumps(data.get("nodes") or []),
                    json.dumps(data.get("edges") or []),
                    json.dumps(data.get("events") or []),
                    json.dumps(data.get("provenance") or []),
                    json.dumps(data.get("result") or {}),
                    str(data.get("python_code") or ""),
                    int(data.get("evolution_gen") or 1),
                    now,
                    now,
                    data.get("finished_at"),
                ),
            )
            self._conn.commit()
        return self.get_workflow(wf_id)  # type: ignore[return-value]

    def get_workflow(self, wf_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM planai_workflows WHERE id = ?", (wf_id,)
            ).fetchone()
        return self._row_to_workflow(row) if row else None

    def list_workflows(
        self,
        project_id: Optional[str] = None,
        session_key: Optional[str] = None,
        graph_type: Optional[str] = None,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if session_key:
            clauses.append("session_key = ?")
            params.append(session_key)
        if graph_type:
            clauses.append("graph_type = ?")
            params.append(graph_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM planai_workflows {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_workflow(row) for row in rows]

    def update_workflow(self, wf_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        allowed_scalar = {
            "state",
            "title",
            "goal",
            "python_code",
            "evolution_gen",
            "finished_at",
        }
        allowed_json = {"nodes", "edges", "events", "provenance", "result"}
        sets, params = [], []
        for key, value in fields.items():
            if key in allowed_scalar:
                sets.append(f"{key} = ?")
                params.append(value)
            elif key in allowed_json:
                sets.append(f"{key}_json = ?")
                params.append(json.dumps(value))
        if not sets:
            return self.get_workflow(wf_id)
        sets.append("updated_at = ?")
        params.extend([_now(), wf_id])
        with self._lock:
            self._conn.execute(
                f"UPDATE planai_workflows SET {', '.join(sets)} WHERE id = ?", params
            )
            self._conn.commit()
        return self.get_workflow(wf_id)

    # ---- Evolution Engine Persistence -----------------------------------

    def get_active_prompt(self, worker_role: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                """SELECT * FROM prompt_versions
                   WHERE worker_role = ? AND active = 1
                   ORDER BY generation DESC LIMIT 1""",
                (worker_role,),
            ).fetchone()
        return dict(row) if row else None

    def list_prompt_versions(
        self, worker_role: Optional[str] = None, limit: int = 30
    ) -> List[Dict[str, Any]]:
        with self._lock:
            if worker_role:
                rows = self._conn.execute(
                    """SELECT * FROM prompt_versions
                       WHERE worker_role = ?
                       ORDER BY generation DESC LIMIT ?""",
                    (worker_role, int(limit)),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM prompt_versions ORDER BY created_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
        return [dict(row) for row in rows]

    def create_prompt_version(
        self,
        worker_role: str,
        prompt_template: str,
        rationale: str = "",
        source_workflow_id: str = "",
        activate: bool = True,
    ) -> Dict[str, Any]:
        now = _now()
        with self._lock:
            current = self._conn.execute(
                """SELECT * FROM prompt_versions
                   WHERE worker_role = ?
                   ORDER BY generation DESC LIMIT 1""",
                (worker_role,),
            ).fetchone()
            next_gen = (int(current["generation"]) + 1) if current else 1
            parent_id = str(current["id"]) if current else ""
            if activate:
                self._conn.execute(
                    "UPDATE prompt_versions SET active = 0 WHERE worker_role = ?",
                    (worker_role,),
                )
            pv_id = f"pv_{worker_role}_{next_gen}_{uuid.uuid4().hex[:6]}"
            self._conn.execute(
                """INSERT INTO prompt_versions (
                    id, worker_role, generation, prompt_template, rationale,
                    parent_id, source_workflow_id, pass_count, fail_count, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)""",
                (
                    pv_id,
                    worker_role,
                    next_gen,
                    prompt_template,
                    rationale,
                    parent_id,
                    source_workflow_id,
                    1 if activate else 0,
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM prompt_versions WHERE id = ?", (pv_id,)
            ).fetchone()
        return dict(row)

    def record_prompt_outcome(self, worker_role: str, passed: bool) -> None:
        col = "pass_count" if passed else "fail_count"
        with self._lock:
            self._conn.execute(
                f"""UPDATE prompt_versions
                    SET {col} = {col} + 1
                    WHERE worker_role = ? AND active = 1""",
                (worker_role,),
            )
            self._conn.commit()

    def upsert_evolution_rule(
        self,
        category: str,
        rule_text: str,
        source_type: str,
        source_ref: str = "",
        project_id: str = "*",
        evidence_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        normalized = rule_text.strip()
        now = _now()
        with self._lock:
            existing = self._conn.execute(
                """SELECT * FROM evolution_rules
                   WHERE project_id = ? AND rule_text = ? LIMIT 1""",
                (project_id or "*", normalized),
            ).fetchone()
            if existing:
                new_count = (
                    int(evidence_count)
                    if evidence_count is not None
                    else int(existing["evidence_count"]) + 1
                )
                self._conn.execute(
                    """UPDATE evolution_rules
                       SET evidence_count = ?, updated_at = ?, active = 1
                       WHERE id = ?""",
                    (new_count, now, existing["id"]),
                )
                self._conn.commit()
                row = self._conn.execute(
                    "SELECT * FROM evolution_rules WHERE id = ?", (existing["id"],)
                ).fetchone()
                return dict(row)
            rule_id = f"rule_{uuid.uuid4().hex[:10]}"
            cnt = int(evidence_count) if evidence_count is not None else 1
            self._conn.execute(
                """INSERT INTO evolution_rules (
                    id, project_id, category, rule_text, source_type,
                    source_ref, evidence_count, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    rule_id,
                    project_id or "*",
                    category,
                    normalized,
                    source_type,
                    source_ref,
                    cnt,
                    now,
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM evolution_rules WHERE id = ?", (rule_id,)
            ).fetchone()
        return dict(row)

    def list_evolution_rules(
        self, project_id: Optional[str] = None, active_only: bool = True
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if active_only:
            clauses.append("active = 1")
        if project_id and project_id != "*":
            clauses.append("(project_id = '*' OR project_id = ?)")
            params.append(project_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM evolution_rules {where} ORDER BY evidence_count DESC, updated_at DESC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def compute_service_fitness(
        self, project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Compute purely empirical run & review outcomes per agent service (zero synthetic numbers)."""
        with self._lock:
            if project_id:
                run_rows = self._conn.execute(
                    """SELECT service,
                              COUNT(*) AS total_runs,
                              SUM(CASE WHEN state = 'succeeded' THEN 1 ELSE 0 END) AS succeeded_runs,
                              SUM(CASE WHEN state = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
                              AVG(CASE WHEN finished_at IS NOT NULL THEN (finished_at - started_at) END) AS avg_duration_s
                       FROM runs
                       WHERE project_id = ?
                       GROUP BY service""",
                    (project_id,),
                ).fetchall()
                item_rows = self._conn.execute(
                    """SELECT source_agent,
                              SUM(CASE WHEN status IN ('approved', 'landed', 'done') THEN 1 ELSE 0 END) AS approved_count,
                              SUM(CASE WHEN status IN ('rejected', 'changes_requested', 'failed') THEN 1 ELSE 0 END) AS bounced_count
                       FROM items
                       WHERE project_id = ?
                       GROUP BY source_agent""",
                    (project_id,),
                ).fetchall()
            else:
                run_rows = self._conn.execute(
                    """SELECT service,
                              COUNT(*) AS total_runs,
                              SUM(CASE WHEN state = 'succeeded' THEN 1 ELSE 0 END) AS succeeded_runs,
                              SUM(CASE WHEN state = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
                              AVG(CASE WHEN finished_at IS NOT NULL THEN (finished_at - started_at) END) AS avg_duration_s
                       FROM runs
                       GROUP BY service"""
                ).fetchall()
                item_rows = self._conn.execute(
                    """SELECT source_agent,
                              SUM(CASE WHEN status IN ('approved', 'landed', 'done') THEN 1 ELSE 0 END) AS approved_count,
                              SUM(CASE WHEN status IN ('rejected', 'changes_requested', 'failed') THEN 1 ELSE 0 END) AS bounced_count
                       FROM items
                       GROUP BY source_agent"""
                ).fetchall()

        item_by_agent = {str(r["source_agent"]): dict(r) for r in item_rows}
        stats: List[Dict[str, Any]] = []
        for r in run_rows:
            svc = str(r["service"])
            total = int(r["total_runs"] or 0)
            succ = int(r["succeeded_runs"] or 0)
            failed = int(r["failed_runs"] or 0)
            avg_dur = (
                round(float(r["avg_duration_s"]), 2)
                if r["avg_duration_s"] is not None
                else None
            )
            ir = item_by_agent.get(svc, {})
            approved = int(ir.get("approved_count") or 0)
            bounced = int(ir.get("bounced_count") or 0)
            pass_rate = round(succ / total, 4) if total > 0 else None
            stats.append(
                {
                    "service": svc,
                    "total_runs": total,
                    "succeeded_runs": succ,
                    "failed_runs": failed,
                    "avg_duration_s": avg_dur,
                    "approved_items": approved,
                    "bounced_items": bounced,
                    "empirical_pass_rate": pass_rate,
                }
            )
        return sorted(
            stats,
            key=lambda x: (
                x["empirical_pass_rate"] if x["empirical_pass_rate"] is not None else -1.0,
                x["succeeded_runs"],
            ),
            reverse=True,
        )

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
            "projectId": sess.get("project_id") or "",
            "mode": sess.get("mode") or "single",
            "createdAt": int(float(sess["created_at"]) * 1000),
            "updatedAt": int(float(sess["updated_at"]) * 1000),
            "lastMessage": last_msg,
        }

    def get_or_create_main_chat_session(
        self, default_service: str = "antigravity", default_project_id: str = ""
    ) -> Dict[str, Any]:
        existing = self.get_chat_session("main")
        if existing:
            if default_project_id and not existing.get("projectId"):
                return (
                    self.update_chat_session("main", project_id=default_project_id)
                    or existing
                )
            return existing
        proj = self.get_project(default_project_id) if default_project_id else None
        if not proj:
            projects = self.list_projects()
            proj = projects[0] if projects else None
        return self.create_chat_session(
            {
                "key": "agent:autoplan:main",
                "friendly_id": "main",
                "label": "Chief & Lead Agents",
                "service": default_service,
                "project_id": proj["id"] if proj else "",
                "cwd": proj["repo_path"] if proj else "",
            }
        )

    def create_chat_session(self, data: Dict[str, Any]) -> Dict[str, Any]:
        now = _now()
        friendly_id = str(
            data.get("friendly_id") or data.get("friendlyId") or uuid.uuid4().hex[:12]
        ).strip()
        service = str(data.get("service") or "antigravity").strip()
        key = str(data.get("key") or f"agent:{service}:{friendly_id}").strip()
        label = str(data.get("label") or "").strip()
        model = str(data.get("model") or "").strip()
        project_id = str(
            data.get("project_id") or data.get("projectId") or ""
        ).strip()
        cwd = str(data.get("cwd") or "").strip()
        mode = str(data.get("mode") or "single").strip() or "single"
        if project_id and not cwd:
            proj = self.get_project(project_id)
            if proj:
                cwd = proj["repo_path"]
        elif not project_id:
            projects = self.list_projects()
            if projects:
                project_id = projects[0]["id"]
                if not cwd:
                    cwd = projects[0]["repo_path"]
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO chat_sessions (
                    key, friendly_id, label, service, model, cwd, project_id, mode, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (key, friendly_id, label, service, model, cwd, project_id, mode, now, now),
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

    def list_chat_sessions(
        self, project_id: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        with self._lock:
            if project_id:
                rows = self._conn.execute(
                    "SELECT * FROM chat_sessions WHERE project_id = ? ORDER BY updated_at DESC LIMIT ?",
                    (project_id, int(limit)),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM chat_sessions ORDER BY updated_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
        return [self._row_to_chat_session(row) for row in rows]

    def update_chat_session(
        self, key_or_friendly_id: str, **fields: Any
    ) -> Optional[Dict[str, Any]]:
        sess = self.get_chat_session(key_or_friendly_id)
        if not sess:
            return None
        if "projectId" in fields and "project_id" not in fields:
            fields["project_id"] = fields.pop("projectId")
        allowed = {"label", "service", "model", "cwd", "project_id", "mode"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "project_id" in updates and "cwd" not in updates:
            proj = self.get_project(str(updates["project_id"]))
            if proj:
                updates["cwd"] = proj["repo_path"]
        if not updates:
            return sess
        sets = [f"{k} = ?" for k in updates] + ["updated_at = ?"]
        params = list(updates.values()) + [_now(), sess["key"]]
        with self._lock:
            self._conn.execute(
                f"UPDATE chat_sessions SET {', '.join(sets)} WHERE key = ?", params
            )
            self._conn.commit()
        return self.get_chat_session(sess["key"])

    def delete_chat_session(self, key_or_friendly_id: str) -> bool:
        sess = self.get_chat_session(key_or_friendly_id)
        if not sess:
            return False
        with self._lock:
            self._conn.execute(
                "DELETE FROM chat_messages WHERE session_key = ?", (sess["key"],)
            )
            self._conn.execute(
                "DELETE FROM chat_sessions WHERE key = ?", (sess["key"],)
            )
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

    def list_chat_messages(
        self, session_key: str, limit: int = 200
    ) -> List[Dict[str, Any]]:
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

"""Real PlanAI Single-Agent State-Machine Workflow Graph (`SingleAgentWorkflowGraph`).

Replaces synthetic workflow JSON rows with genuine `planai.Graph` execution:
  SingleGoalTask
    ──▶ WorktreeRunner (TaskWorker [kind="agent"]: isolated branch/worktree execution)
    ──▶ VerificationGate (TaskWorker [kind="deterministic"]: test_command + Law-2 reality & secret scan)
    ──▶ ChiefReviewSink (TaskWorker [kind="human_gate"]: creates/updates ReviewItem & pauses at gate)

Supports IronCurtain state-machine semantics:
  - Semantic node kinds: `agent`, `deterministic`, `human_gate`, `terminal`
  - Terminal states: `DoneTerminal` (`APPROVE` / `landed`) and `AbortedTerminal` (`ABORT` / `failed`)
  - Bounded cyclic `FORCE_REVISION` (`request_changes`) back-edge `ChiefReviewSink ──▶ WorktreeRunner`
    preserving existing branch commits and incrementing `visit_counts` (`×2`, `×3`, up to `max_rounds`).
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

from planai import Graph, Task, TaskWorker
from pydantic import Field

from planaieditor.queue_store import QueueStore

_UNAUTHORIZED_MOCK_RE = re.compile(
    r"\b(MOCK_DATA|FAKE_RESPONSE|PLACEHOLDER_VALUE|hdr_observed|fp_observed)\b"
)
_AUTH_QUOTE_MARKER = "RYAN EXPLICIT MOCK/FALLBACK AUTHORIZATION:"
_SECRET_DIFF_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,})"
)

SINGLE_WORKFLOW_PYTHON_SOURCE = """from planai import Graph, Task, TaskWorker

# Single-Agent Isolated Branch Workflow with Deterministic Verification & Human Gate
graph = Graph(name="SingleAgentWorkflowGraph")
runner = WorktreeRunner()          # kind="agent"
gate = VerificationGate()          # kind="deterministic" (test_command + Law-2 reality & secret scan)
review = ChiefReviewSink()         # kind="human_gate" (APPROVE -> DoneTerminal | FORCE_REVISION -> WorktreeRunner | ABORT -> AbortedTerminal)

graph.add_workers(runner, gate, review)
graph.set_dependency(runner, gate).next(review)
"""


def run_reality_and_secret_scan(diff_text: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Mechanical Law-2 unauthorized mock/placeholder check and secret leak scan over git diff."""
    unauthorized_lines: List[str] = []
    secret_hits = 0
    lines = diff_text.splitlines()
    for idx, line in enumerate(lines):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if _SECRET_DIFF_RE.search(line):
            secret_hits += 1
        if _UNAUTHORIZED_MOCK_RE.search(line):
            prev_window = "\n".join(lines[max(0, idx - 3) : idx + 1])
            if _AUTH_QUOTE_MARKER not in prev_window:
                unauthorized_lines.append(line[1:].strip()[:140])
    reality = {
        "passed": len(unauthorized_lines) == 0,
        "violations": unauthorized_lines,
    }
    secrets = {
        "passed": secret_hits == 0,
        "redacted_hits_count": secret_hits,
    }
    return reality, secrets


def run_shell_test_command(command: str, cwd: Path, timeout: int = 300) -> Dict[str, Any]:
    """Execute a real project test command without shell injection and return structured report."""
    if not command.strip():
        return {"configured": False, "passed": True}
    started = time.time()
    try:
        tokens = shlex.split(command)
        cmd_env = dict(os.environ)
        while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
            k, v = tokens[0].split("=", 1)
            if k.isidentifier():
                cmd_env[k] = v
                tokens.pop(0)
            else:
                break
        if not tokens:
            return {
                "configured": True,
                "command": command,
                "exit_code": 1,
                "passed": False,
                "stdout_tail": "",
                "stderr_tail": "Empty test command",
                "duration_s": 0.0,
            }
        proc = subprocess.run(
            tokens,
            cwd=str(cwd),
            env=cmd_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "configured": True,
            "command": command,
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
            "stdout_tail": proc.stdout[-3000:],
            "stderr_tail": proc.stderr[-3000:],
            "duration_s": round(time.time() - started, 2),
        }
    except Exception as exc:
        return {
            "configured": True,
            "command": command,
            "exit_code": -1,
            "passed": False,
            "stdout_tail": "",
            "stderr_tail": str(exc),
            "duration_s": round(time.time() - started, 2),
        }


def build_single_workflow_nodes(
    service: str,
    branch_name: str,
    test_command: str = "",
) -> List[Dict[str, Any]]:
    return [
        {
            "id": "WorktreeRunner",
            "label": f"Run {service}",
            "kind": "agent",
            "worker_class": "WorktreeRunner",
            "worker_type": "TaskWorker",
            "svelte_type": "taskworker",
            "role": f"Isolated branch {branch_name}",
            "state": "idle",
            "position": {"x": 60, "y": 140},
            "metrics": {"service": service, "branch": branch_name},
        },
        {
            "id": "VerificationGate",
            "label": "Verify & scan",
            "kind": "deterministic",
            "worker_class": "VerificationGate",
            "worker_type": "TaskWorker",
            "svelte_type": "taskworker",
            "role": test_command or "Project tests + Law-2 reality & secret scan",
            "state": "idle",
            "position": {"x": 320, "y": 140},
            "metrics": {},
        },
        {
            "id": "ChiefReviewSink",
            "label": "Human Gate",
            "kind": "human_gate",
            "worker_class": "ChiefReviewSink",
            "worker_type": "TaskWorker",
            "svelte_type": "taskworker",
            "role": "Approve & merge, request revision, or abort",
            "state": "idle",
            "position": {"x": 580, "y": 140},
            "metrics": {},
        },
        {
            "id": "DoneTerminal",
            "label": "Landed",
            "kind": "terminal",
            "worker_class": "TerminalState",
            "worker_type": "Terminal",
            "svelte_type": "taskworker",
            "role": "Verified branch merged cleanly onto target branch",
            "state": "idle",
            "position": {"x": 850, "y": 90},
            "metrics": {},
        },
        {
            "id": "AbortedTerminal",
            "label": "Aborted",
            "kind": "terminal",
            "worker_class": "TerminalState",
            "worker_type": "Terminal",
            "svelte_type": "taskworker",
            "role": "Workflow aborted or halted on fatal error",
            "state": "idle",
            "position": {"x": 850, "y": 210},
            "metrics": {},
        },
    ]


def build_single_workflow_edges() -> List[Dict[str, Any]]:
    return [
        {
            "id": "e_run_verify",
            "source": "WorktreeRunner",
            "target": "VerificationGate",
            "label": "committed",
            "task_type": "BranchExecutionTask",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_verify_review",
            "source": "VerificationGate",
            "target": "ChiefReviewSink",
            "label": "verified",
            "task_type": "VerifiedBranchBundleTask",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_review_done",
            "source": "ChiefReviewSink",
            "target": "DoneTerminal",
            "label": "approve",
            "task_type": "MergeLanded",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_review_revision",
            "source": "ChiefReviewSink",
            "target": "WorktreeRunner",
            "label": "revision",
            "task_type": "RevisionDirective",
            "active": False,
            "is_back_edge": True,
        },
        {
            "id": "e_review_abort",
            "source": "ChiefReviewSink",
            "target": "AbortedTerminal",
            "label": "abort",
            "task_type": "Aborted",
            "active": False,
            "is_back_edge": False,
        },
    ]


class SingleGoalTask(Task):
    workflow_id: str
    run_id: str
    project_id: str = ""
    service: str
    model: str = ""
    prompt: str
    workspace_dir: str
    repo_dir: str = ""
    is_project_worktree: bool = False
    is_demo_repo: bool = False
    branch_name: str
    target_branch: str = "main"
    test_command: str = ""
    demo_token: str = ""
    demo_title: str = ""
    submit_to_queue: bool = True
    queue_title: str = ""
    existing_queue_item_id: str = ""
    round_num: int = 1
    max_rounds: int = 3
    revision_note: str = ""
    session_key: str = ""
    timeout: int = 180


class BranchExecutionTask(Task):
    workflow_id: str
    run_id: str
    project_id: str = ""
    service: str
    model: str = ""
    prompt: str
    workspace_dir: str
    repo_dir: str = ""
    is_project_worktree: bool = False
    is_demo_repo: bool = False
    branch_name: str
    final_branch: str
    target_branch: str = "main"
    test_command: str = ""
    submit_to_queue: bool = True
    queue_title: str = ""
    existing_queue_item_id: str = ""
    round_num: int = 1
    max_rounds: int = 3
    session_key: str = ""
    passed: bool
    exit_code: int
    session_id: str = ""
    response_text: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_s: float = 0.0
    committed: bool = False
    commit_sha: str = ""
    changed_files: List[str] = Field(default_factory=list)
    diff_text: str = ""


class VerifiedBranchBundleTask(Task):
    workflow_id: str
    run_id: str
    project_id: str = ""
    service: str
    model: str = ""
    prompt: str
    workspace_dir: str
    repo_dir: str = ""
    is_project_worktree: bool = False
    is_demo_repo: bool = False
    final_branch: str
    target_branch: str = "main"
    test_command: str = ""
    submit_to_queue: bool = True
    queue_title: str = ""
    existing_queue_item_id: str = ""
    round_num: int = 1
    max_rounds: int = 3
    session_key: str = ""
    passed: bool
    exit_code: int
    session_id: str = ""
    response_text: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_s: float = 0.0
    committed: bool = False
    commit_sha: str = ""
    changed_files: List[str] = Field(default_factory=list)
    diff_text: str = ""
    test_report: Dict[str, Any] = Field(default_factory=dict)
    reality_scan: Dict[str, Any] = Field(default_factory=dict)
    secret_scan: Dict[str, Any] = Field(default_factory=dict)
    gate_passed: bool = True


def transition_workflow_gate(
    store: QueueStore,
    wf_id: str,
    *,
    terminal: str,
    summary: str = "",
    merged_commit: str = "",
    on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Optional[Dict[str, Any]]:
    """Transition a `single` or `teamwork` workflow out of or into its human gate."""
    if not wf_id:
        return None
    wf = store.get_workflow(wf_id)
    if not wf:
        return None

    nodes = list(wf.get("nodes") or [])
    edges = list(wf.get("edges") or [])
    events = list(wf.get("events") or [])
    result = dict(wf.get("result") or {})
    visit_counts = dict(result.get("visit_counts") or {})

    gate_node_id = (
        "ChiefReviewSink" if wf.get("graph_type") == "single" else "ChiefEscalationSink"
    )
    now = time.time()

    for e in edges:
        e["active"] = False

    if terminal == "waiting_gate":
        for n in nodes:
            if n.get("id") == gate_node_id:
                n["state"] = "waiting_gate"
            elif n.get("id") in ("DoneTerminal", "AbortedTerminal"):
                n["state"] = "idle"
        wf_state = "waiting_gate"
        result["current_state"] = gate_node_id
        finished_at = None
    elif terminal == "done":
        visit_counts["DoneTerminal"] = int(visit_counts.get("DoneTerminal") or 0) + 1
        for n in nodes:
            if n.get("id") == gate_node_id:
                n["state"] = "succeeded"
            elif n.get("id") == "DoneTerminal":
                n["state"] = "succeeded"
                if merged_commit:
                    n["metrics"] = {
                        **dict(n.get("metrics") or {}),
                        "merged_commit": merged_commit[:10],
                    }
            elif n.get("id") == "AbortedTerminal":
                n["state"] = "idle"
        wf_state = "succeeded"
        result["current_state"] = "DoneTerminal"
        if merged_commit:
            result["merged_commit"] = merged_commit
        finished_at = now
    elif terminal == "aborted":
        visit_counts["AbortedTerminal"] = int(visit_counts.get("AbortedTerminal") or 0) + 1
        for n in nodes:
            if n.get("id") == gate_node_id and n.get("state") == "waiting_gate":
                n["state"] = "aborted"
            elif n.get("id") == "AbortedTerminal":
                n["state"] = "aborted"
            elif n.get("id") == "DoneTerminal":
                n["state"] = "idle"
        wf_state = "aborted"
        result["current_state"] = "AbortedTerminal"
        finished_at = now
    else:
        return wf

    result["visit_counts"] = visit_counts
    if summary:
        events.append(
            {
                "ts": now,
                "node_id": result.get("current_state") or gate_node_id,
                "state": wf_state,
                "summary": summary,
            }
        )

    updated = store.update_workflow(
        wf_id,
        state=wf_state,
        nodes=nodes,
        edges=edges,
        events=events,
        result=result,
        finished_at=finished_at,
    )
    if updated and on_event is not None:
        on_event("planai_workflow_updated", {"workflow": updated})
    return updated


def execute_single_agent_planai_graph(
    *,
    manager: Any,
    goal_task: SingleGoalTask,
    redact_fn: Callable[[str], str],
    register_proc: Callable[[subprocess.Popen], None],
    unregister_proc: Callable[[], None],
) -> Optional[Dict[str, Any]]:
    """Run a genuine 3-worker `planai.Graph` for a single-agent branch run or revision round."""
    store = manager.store
    wf_id = goal_task.workflow_id
    wf = store.get_workflow(wf_id)
    if not wf:
        return None

    state_lock = threading.Lock()
    nodes: List[Dict[str, Any]] = list(wf.get("nodes") or [])
    edges: List[Dict[str, Any]] = list(wf.get("edges") or [])
    events: List[Dict[str, Any]] = list(wf.get("events") or [])
    provenance_log: List[Any] = list(wf.get("provenance") or [])
    result_meta: Dict[str, Any] = dict(wf.get("result") or {})
    visit_counts: Dict[str, int] = {
        str(k): int(v) for k, v in dict(result_meta.get("visit_counts") or {}).items()
    }
    result_meta["round"] = goal_task.round_num
    result_meta["max_rounds"] = goal_task.max_rounds

    def emit_wf(
        *,
        wf_state: str = "running",
        current_node: str = "",
        active_edge: str = "",
        node_updates: Optional[Dict[str, Dict[str, Any]]] = None,
        event_entry: Optional[Dict[str, Any]] = None,
        prov_chain: Optional[List[str]] = None,
        extra_result: Optional[Dict[str, Any]] = None,
        finished: bool = False,
    ) -> Optional[Dict[str, Any]]:
        with state_lock:
            if node_updates:
                for n in nodes:
                    nid = n.get("id", "")
                    if nid in node_updates:
                        patch = node_updates[nid]
                        if "state" in patch:
                            n["state"] = patch["state"]
                        if "role" in patch:
                            n["role"] = patch["role"]
                        if "label" in patch:
                            n["label"] = patch["label"]
                        if "metrics" in patch:
                            n["metrics"] = {
                                **dict(n.get("metrics") or {}),
                                **patch["metrics"],
                            }
            for e in edges:
                e["active"] = bool(active_edge and e.get("id") == active_edge)
            if event_entry:
                events.append(event_entry)
            if prov_chain:
                provenance_log.append(prov_chain)
            if current_node:
                result_meta["current_state"] = current_node
            result_meta["visit_counts"] = dict(visit_counts)
            if extra_result:
                result_meta.update(extra_result)
            updated = store.update_workflow(
                wf_id,
                state=wf_state,
                nodes=nodes,
                edges=edges,
                events=events,
                provenance=provenance_log,
                result=result_meta,
                finished_at=time.time() if finished else None,
            )
        if updated:
            manager._on_event("planai_workflow_updated", {"workflow": updated})
        return updated

    class WorktreeRunner(TaskWorker):
        output_types: List[Type[Task]] = [BranchExecutionTask]

        def consume_work(self, task: SingleGoalTask) -> None:
            with state_lock:
                visit_counts["WorktreeRunner"] = (
                    int(visit_counts.get("WorktreeRunner") or 0) + 1
                )
                visits = visit_counts["WorktreeRunner"]

            emit_wf(
                wf_state="running",
                current_node="WorktreeRunner",
                active_edge="e_review_revision" if task.round_num > 1 else "",
                node_updates={
                    "WorktreeRunner": {
                        "state": "running",
                        "label": f"Run {task.service}",
                        "role": (
                            f"Round {task.round_num}/{task.max_rounds} on {task.branch_name}"
                            if task.round_num > 1
                            else f"Isolated branch {task.branch_name}"
                        ),
                        "metrics": {
                            "service": task.service,
                            "branch": task.branch_name,
                            "round": task.round_num,
                            "visits": visits,
                        },
                    },
                    "VerificationGate": {"state": "idle"},
                    "ChiefReviewSink": {"state": "idle"},
                    "DoneTerminal": {"state": "idle"},
                    "AbortedTerminal": {"state": "idle"},
                },
                event_entry={
                    "ts": time.time(),
                    "node_id": "WorktreeRunner",
                    "state": "running",
                    "summary": (
                        f"Revision round {task.round_num}: running {task.service} on {task.branch_name}"
                        if task.round_num > 1
                        else f"Running {task.service} on branch {task.branch_name}"
                    ),
                },
            )

            adapter = manager.get_adapter(task.service)
            workspace_path = Path(task.workspace_dir).resolve()
            repo_path = Path(task.repo_dir).resolve() if task.repo_dir else workspace_path

            try:
                res = adapter.dispatch(
                    prompt=task.prompt,
                    cwd=workspace_path,
                    model=task.model,
                    timeout=task.timeout,
                    on_proc=register_proc,
                )
            except Exception as exc:
                from planaieditor.agent_adapters import AdapterRunResult

                res = AdapterRunResult(
                    passed=False,
                    exit_code=1,
                    model=task.model,
                    response_text=f"Dispatch error: {exc}",
                    stderr_tail=str(exc),
                )
            finally:
                unregister_proc()
                store.release_ownership(task.run_id)

            current_run = store.get_run(task.run_id)
            if current_run and current_run["state"] == "stopped":
                return

            committed = False
            commit_sha = ""
            final_branch = task.branch_name
            changed_files: List[str] = []
            diff_text = ""
            effective_test_cmd = task.test_command

            if task.is_demo_repo and res.passed:
                committed, commit_sha, final_branch = manager._finalize_demo_repo_commit(
                    workspace_path, task.branch_name, task.run_id, task.service
                )
                if committed:
                    names_out = manager._git(
                        workspace_path,
                        "diff",
                        "--name-only",
                        f"main..{final_branch}",
                    ).stdout
                    changed_files = [
                        f.strip() for f in names_out.splitlines() if f.strip()
                    ]
                    diff_text = manager._git(
                        workspace_path, "diff", f"main..{final_branch}"
                    ).stdout
                    if not effective_test_cmd and task.demo_token:
                        effective_test_cmd = (
                            f"git grep -q {task.demo_token} {final_branch} -- task_result.txt"
                        )
            elif task.is_project_worktree and res.passed and workspace_path.exists():
                manager._git(workspace_path, "config", "user.email", "autoplan@local.invalid")
                manager._git(workspace_path, "config", "user.name", "AutoPlan Agent")
                manager._git(workspace_path, "add", "-A")
                diff_cached = manager._git(
                    workspace_path, "diff", "--cached", "--name-only"
                )
                staged = [
                    f.strip()
                    for f in diff_cached.stdout.splitlines()
                    if f.strip() and not f.strip().startswith(".mimocode")
                ]
                if staged:
                    commit_prefix = (
                        f"fix({task.service},r{task.round_num})"
                        if task.round_num > 1
                        else f"feat({task.service})"
                    )
                    headline = task.prompt.splitlines()[0][:56]
                    manager._git(
                        workspace_path,
                        "commit",
                        "-m",
                        f"{commit_prefix}: {headline}",
                    )
                ahead_raw = manager._git(
                    repo_path,
                    "rev-list",
                    "--count",
                    f"{task.target_branch}..{task.branch_name}",
                ).stdout.strip()
                ahead_n = int(ahead_raw or "0") if ahead_raw.isdigit() else 0
                if ahead_n > 0:
                    committed = True
                    commit_sha = manager._git(
                        repo_path, "rev-parse", task.branch_name
                    ).stdout.strip()
                    names_out = manager._git(
                        repo_path,
                        "diff",
                        "--name-only",
                        f"{task.target_branch}..{task.branch_name}",
                    ).stdout
                    changed_files = [
                        f.strip() for f in names_out.splitlines() if f.strip()
                    ]
                    diff_text = manager._git(
                        repo_path,
                        "diff",
                        f"{task.target_branch}..{task.branch_name}",
                    ).stdout

            emit_wf(
                wf_state="running",
                current_node="WorktreeRunner",
                active_edge="e_run_verify" if res.passed else "",
                node_updates={
                    "WorktreeRunner": {
                        "state": "succeeded" if res.passed else "failed",
                        "metrics": {
                            "service": task.service,
                            "branch": final_branch,
                            "commit_sha": commit_sha[:10] if commit_sha else "",
                            "changed_files_count": len(changed_files),
                            "duration_s": res.duration_s,
                            "round": task.round_num,
                        },
                    }
                },
                event_entry={
                    "ts": time.time(),
                    "node_id": "WorktreeRunner",
                    "state": "succeeded" if res.passed else "failed",
                    "summary": (
                        f"Committed {commit_sha[:10]} ({len(changed_files)} files) on {final_branch}"
                        if commit_sha
                        else (
                            f"Completed in {res.duration_s}s"
                            if res.passed
                            else f"{task.service} exited with code {res.exit_code}"
                        )
                    ),
                },
            )

            exec_task = BranchExecutionTask(
                workflow_id=task.workflow_id,
                run_id=task.run_id,
                project_id=task.project_id,
                service=task.service,
                model=res.model or task.model,
                prompt=task.prompt,
                workspace_dir=task.workspace_dir,
                repo_dir=task.repo_dir,
                is_project_worktree=task.is_project_worktree,
                is_demo_repo=task.is_demo_repo,
                branch_name=task.branch_name,
                final_branch=final_branch,
                target_branch=task.target_branch,
                test_command=effective_test_cmd,
                submit_to_queue=task.submit_to_queue,
                queue_title=task.queue_title,
                existing_queue_item_id=task.existing_queue_item_id,
                round_num=task.round_num,
                max_rounds=task.max_rounds,
                session_key=task.session_key,
                passed=res.passed,
                exit_code=res.exit_code,
                session_id=res.session_id,
                response_text=res.response_text,
                stdout_tail=res.stdout_tail,
                stderr_tail=res.stderr_tail,
                duration_s=res.duration_s,
                committed=committed,
                commit_sha=commit_sha,
                changed_files=changed_files,
                diff_text=diff_text,
            )
            self.publish_work(exec_task, input_task=task)

    class VerificationGate(TaskWorker):
        output_types: List[Type[Task]] = [VerifiedBranchBundleTask]

        def consume_work(self, task: BranchExecutionTask) -> None:
            workspace_path = Path(task.workspace_dir).resolve()
            repo_path = Path(task.repo_dir).resolve() if task.repo_dir else workspace_path

            try:
                if not task.passed:
                    self.publish_work(
                        VerifiedBranchBundleTask(
                            workflow_id=task.workflow_id,
                            run_id=task.run_id,
                            project_id=task.project_id,
                            service=task.service,
                            model=task.model,
                            prompt=task.prompt,
                            workspace_dir=task.workspace_dir,
                            repo_dir=task.repo_dir,
                            is_project_worktree=task.is_project_worktree,
                            is_demo_repo=task.is_demo_repo,
                            final_branch=task.final_branch,
                            target_branch=task.target_branch,
                            test_command=task.test_command,
                            submit_to_queue=task.submit_to_queue,
                            queue_title=task.queue_title,
                            existing_queue_item_id=task.existing_queue_item_id,
                            round_num=task.round_num,
                            max_rounds=task.max_rounds,
                            session_key=task.session_key,
                            passed=False,
                            exit_code=task.exit_code,
                            session_id=task.session_id,
                            response_text=task.response_text,
                            stdout_tail=task.stdout_tail,
                            stderr_tail=task.stderr_tail,
                            duration_s=task.duration_s,
                            committed=False,
                            gate_passed=False,
                        ),
                        input_task=task,
                    )
                    return

                with state_lock:
                    visit_counts["VerificationGate"] = (
                        int(visit_counts.get("VerificationGate") or 0) + 1
                    )
                    visits = visit_counts["VerificationGate"]

                emit_wf(
                    wf_state="running",
                    current_node="VerificationGate",
                    active_edge="e_run_verify",
                    node_updates={
                        "VerificationGate": {
                            "state": "running",
                            "metrics": {"visits": visits, "round": task.round_num},
                        }
                    },
                    event_entry={
                        "ts": time.time(),
                        "node_id": "VerificationGate",
                        "state": "running",
                        "summary": "Running deterministic test gate + Law-2 reality & secret scans",
                    },
                )

                test_report: Dict[str, Any] = {"configured": False, "passed": True}
                if task.committed and task.test_command.strip() and workspace_path.exists():
                    test_report = run_shell_test_command(task.test_command, workspace_path)

                reality_scan, secret_scan = run_reality_and_secret_scan(task.diff_text)
                gate_passed = (
                    bool(test_report.get("passed", True))
                    and bool(reality_scan["passed"])
                    and bool(secret_scan["passed"])
                )

                emit_wf(
                    wf_state="running",
                    current_node="VerificationGate",
                    active_edge="e_verify_review",
                    node_updates={
                        "VerificationGate": {
                            "state": "succeeded" if gate_passed else "failed",
                            "metrics": {
                                "gate_passed": gate_passed,
                                "test_passed": test_report.get("passed", True),
                                "test_exit_code": test_report.get("exit_code", 0),
                                "reality_passed": reality_scan["passed"],
                                "secret_passed": secret_scan["passed"],
                                "visits": visits,
                            },
                        }
                    },
                    event_entry={
                        "ts": time.time(),
                        "node_id": "VerificationGate",
                        "state": "succeeded" if gate_passed else "failed",
                        "summary": (
                            f"Verification {'passed' if gate_passed else 'flagged'} "
                            f"(tests={'ok' if test_report.get('passed', True) else 'fail'}, "
                            f"reality={'ok' if reality_scan['passed'] else 'violation'})"
                        ),
                    },
                )

                self.publish_work(
                    VerifiedBranchBundleTask(
                        workflow_id=task.workflow_id,
                        run_id=task.run_id,
                        project_id=task.project_id,
                        service=task.service,
                        model=task.model,
                        prompt=task.prompt,
                        workspace_dir=task.workspace_dir,
                        repo_dir=task.repo_dir,
                        is_project_worktree=task.is_project_worktree,
                        is_demo_repo=task.is_demo_repo,
                        final_branch=task.final_branch,
                        target_branch=task.target_branch,
                        test_command=task.test_command,
                        submit_to_queue=task.submit_to_queue,
                        queue_title=task.queue_title,
                        existing_queue_item_id=task.existing_queue_item_id,
                        round_num=task.round_num,
                        max_rounds=task.max_rounds,
                        session_key=task.session_key,
                        passed=task.passed,
                        exit_code=task.exit_code,
                        session_id=task.session_id,
                        response_text=task.response_text,
                        stdout_tail=task.stdout_tail,
                        stderr_tail=task.stderr_tail,
                        duration_s=task.duration_s,
                        committed=task.committed,
                        commit_sha=task.commit_sha,
                        changed_files=task.changed_files,
                        diff_text=task.diff_text,
                        test_report=test_report,
                        reality_scan=reality_scan,
                        secret_scan=secret_scan,
                        gate_passed=gate_passed,
                    ),
                    input_task=task,
                )
            finally:
                if task.is_project_worktree and task.repo_dir:
                    manager._git(
                        repo_path,
                        "worktree",
                        "remove",
                        "--force",
                        str(workspace_path),
                    )
                    if not task.committed and task.round_num == 1:
                        manager._git(repo_path, "branch", "-D", task.branch_name)

    class ChiefReviewSink(TaskWorker):
        output_types: List[Type[Task]] = []

        def consume_work(self, task: VerifiedBranchBundleTask) -> None:
            prov_chain = [str(p) for p in getattr(task, "_provenance", [])]
            if not prov_chain:
                prov_chain = ["WorktreeRunner", "VerificationGate", "ChiefReviewSink"]

            queue_item_id = task.existing_queue_item_id
            repo_for_item = (
                task.repo_dir
                if task.is_project_worktree and task.repo_dir
                else task.workspace_dir
            )

            if task.passed and task.submit_to_queue and (
                task.committed or not task.is_demo_repo
            ):
                with state_lock:
                    visit_counts["ChiefReviewSink"] = (
                        int(visit_counts.get("ChiefReviewSink") or 0) + 1
                    )
                    gate_visits = visit_counts["ChiefReviewSink"]

                has_code = bool(task.committed and task.final_branch)
                body_text = (
                    f"Agent `{task.service}` (`{task.model}`) completed round `{task.round_num}` "
                    f"(run `{task.run_id}`) in `{repo_for_item}`"
                    + (
                        f" on branch `{task.final_branch}` (commit `{task.commit_sha[:10]}`)."
                        if has_code
                        else "."
                    )
                    + f"\n\n{redact_fn(task.response_text)}"
                )
                item_result_payload: Dict[str, Any] = {
                    "workflow_id": task.workflow_id,
                    "run_id": task.run_id,
                    "round": task.round_num,
                    "branch_commit": task.commit_sha,
                    "changed_files": task.changed_files,
                    "gate_test": task.test_report,
                    "reality_scan": task.reality_scan,
                    "secret_scan": task.secret_scan,
                }
                if task.test_report.get("configured"):
                    item_result_payload["test"] = task.test_report

                if queue_item_id and store.get_item(queue_item_id):
                    existing = store.get_item(queue_item_id) or {}
                    merged_res = {**dict(existing.get("result") or {}), **item_result_payload}
                    q_item = store.update_item(
                        queue_item_id,
                        status="needs_review",
                        branch=task.final_branch if has_code else existing.get("branch", ""),
                        body=body_text,
                        result=merged_res,
                    )
                    store.add_event(
                        queue_item_id,
                        "revision_ready",
                        f"Round {task.round_num} completed on {task.final_branch} ({task.commit_sha[:10]}).",
                    )
                    if q_item:
                        manager._on_event("queue_item_created", {"item": q_item})
                else:
                    q_item = store.create_item(
                        {
                            "source_agent": task.service,
                            "kind": "code_change" if has_code else "task",
                            "title": task.queue_title
                            or f"[{task.service}] {task.prompt.splitlines()[0][:64]}",
                            "body": body_text,
                            "repo_path": repo_for_item if has_code else "",
                            "branch": task.final_branch if has_code else "",
                            "target_branch": task.target_branch if has_code else "main",
                            "test_command": task.test_command if has_code else "",
                            "priority": 30 if task.gate_passed else 70,
                            "project_id": task.project_id,
                            "workflow_id": task.workflow_id,
                        }
                    )
                    queue_item_id = q_item["id"]
                    q_item = store.update_item(queue_item_id, result=item_result_payload) or q_item
                    manager._on_event("queue_item_created", {"item": q_item})

            meta: Dict[str, Any] = {
                "is_demo_repo": task.is_demo_repo,
                "duration_s": task.duration_s,
                "round": task.round_num,
                "gate_passed": task.gate_passed,
            }
            if task.commit_sha:
                meta["branch_commit"] = task.commit_sha

            updated_run = store.update_run(
                task.run_id,
                session_id=task.session_id,
                queue_item_id=queue_item_id,
                state="succeeded" if task.passed else "failed",
                exit_code=task.exit_code,
                response_text=task.response_text,
                stdout_tail=task.stdout_tail,
                stderr_tail=task.stderr_tail,
                metadata=meta,
                finished_at=time.time(),
            )
            manager._on_event("run_updated", {"run": updated_run})

            if not task.passed:
                with state_lock:
                    visit_counts["AbortedTerminal"] = (
                        int(visit_counts.get("AbortedTerminal") or 0) + 1
                    )
                emit_wf(
                    wf_state="failed",
                    current_node="AbortedTerminal",
                    node_updates={
                        "AbortedTerminal": {"state": "failed"},
                    },
                    event_entry={
                        "ts": time.time(),
                        "node_id": "AbortedTerminal",
                        "state": "failed",
                        "summary": f"Run failed with exit code {task.exit_code}",
                    },
                    prov_chain=prov_chain,
                    extra_result={
                        "run_id": task.run_id,
                        "queue_item_id": queue_item_id,
                        "commit_sha": task.commit_sha,
                        "gate_passed": False,
                    },
                    finished=True,
                )
            elif queue_item_id:
                emit_wf(
                    wf_state="waiting_gate",
                    current_node="ChiefReviewSink",
                    node_updates={
                        "ChiefReviewSink": {
                            "state": "waiting_gate",
                            "metrics": {
                                "queue_item_id": queue_item_id,
                                "round": task.round_num,
                                "visits": visit_counts.get("ChiefReviewSink", 1),
                            },
                        }
                    },
                    event_entry={
                        "ts": time.time(),
                        "node_id": "ChiefReviewSink",
                        "state": "waiting_gate",
                        "summary": f"Paused at Human Gate ({queue_item_id}, round {task.round_num})",
                    },
                    prov_chain=prov_chain,
                    extra_result={
                        "run_id": task.run_id,
                        "queue_item_id": queue_item_id,
                        "commit_sha": task.commit_sha,
                        "changed_files": task.changed_files,
                        "gate_passed": task.gate_passed,
                        "test_report": task.test_report,
                        "reality_scan": task.reality_scan,
                        "secret_scan": task.secret_scan,
                        "repo_path": repo_for_item,
                        "branch": task.final_branch,
                        "target_branch": task.target_branch,
                        "service": task.service,
                        "model": task.model,
                        "is_demo_repo": task.is_demo_repo,
                        "is_project_worktree": task.is_project_worktree,
                        "test_command": task.test_command,
                    },
                    finished=False,
                )
            else:
                with state_lock:
                    visit_counts["ChiefReviewSink"] = (
                        int(visit_counts.get("ChiefReviewSink") or 0) + 1
                    )
                    visit_counts["DoneTerminal"] = (
                        int(visit_counts.get("DoneTerminal") or 0) + 1
                    )
                emit_wf(
                    wf_state="succeeded",
                    current_node="DoneTerminal",
                    node_updates={
                        "ChiefReviewSink": {"state": "succeeded"},
                        "DoneTerminal": {"state": "succeeded"},
                    },
                    event_entry={
                        "ts": time.time(),
                        "node_id": "DoneTerminal",
                        "state": "succeeded",
                        "summary": f"Completed in {task.duration_s}s",
                    },
                    prov_chain=prov_chain,
                    extra_result={
                        "run_id": task.run_id,
                        "queue_item_id": "",
                        "commit_sha": task.commit_sha,
                        "gate_passed": task.gate_passed,
                    },
                    finished=True,
                )

            if task.session_key:
                summary_lines = [task.response_text or "(no text output)"]
                if task.commit_sha:
                    summary_lines.append(
                        f"\n\nCommitted `{task.commit_sha[:10]}` on `{task.final_branch}` "
                        f"(round {task.round_num}/{task.max_rounds})."
                    )
                if queue_item_id:
                    summary_lines.append(
                        f"Awaiting Human Gate decision on `{queue_item_id}`."
                    )
                if not task.passed and task.stderr_tail:
                    summary_lines.append(
                        f"\n\nStderr:\n```\n{task.stderr_tail[-800:]}\n```"
                    )

                saved_msg = store.add_chat_message(
                    session_key=task.session_key,
                    role="assistant",
                    text="\n".join(summary_lines).strip(),
                    details={
                        "runId": task.run_id,
                        "workflowId": task.workflow_id,
                        "service": task.service,
                        "model": task.model,
                        "sessionId": task.session_id,
                        "queueItemId": queue_item_id,
                        "exitCode": task.exit_code,
                        "durationS": task.duration_s,
                        "round": task.round_num,
                    },
                    is_error=not task.passed,
                )
                manager._on_event(
                    "webclaw_chat",
                    {
                        "runId": task.run_id,
                        "sessionKey": task.session_key,
                        "state": "final" if task.passed else "error",
                        "message": saved_msg,
                    },
                )

    graph = Graph(name="SingleAgentWorkflowGraph")
    runner = WorktreeRunner()
    gate = VerificationGate()
    review = ChiefReviewSink()
    graph.add_workers(runner, gate, review)
    graph.set_dependency(runner, gate).next(review)
    graph.run(initial_tasks=[(runner, goal_task)], display_terminal=False)
    return store.get_workflow(wf_id)

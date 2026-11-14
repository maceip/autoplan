"""Real PlanAI Multi-Agent Teamwork & Planning Graph Orchestrator.

Executes multi-agent planning, parallel isolated-worktree execution,
`JoinedTaskWorker` fan-in synthesis, mechanical Law-2 reality & secret gates,
and Chief-of-Staff review escalation on top of real `planai.Graph` primitives:

  TeamGoalTask
    ──▶ PlanningSubGraph (SubGraphWorker: ContextHarvesterWorker ──▶ LeadPlannerWorker)
    ──▶ SubtaskFanOutWorker (TaskWorker: publishes N parallel SubAgentDirectiveTasks)
    ──▶ MultiAgentDispatchWorker (TaskWorker: runs real adapters in isolated git worktrees)
    ──▶ TeamSynthesisJoiner (JoinedTaskWorker[join_type=SubtaskFanOutWorker]: joins all N results)
    ──▶ VerificationGateWorker (TaskWorker: runs real project test_command + Law-2 reality scan)
    ──▶ ChiefEscalationSink (TaskWorker: queues verified bundle + updates EvolutionEngine)
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

from planai import (
    Graph,
    InitialTaskWorker,
    JoinedTaskWorker,
    LLMTaskWorker,
    SubGraphWorker,
    Task,
    TaskWorker,
)
from pydantic import BaseModel, Field

from planaieditor.agent_adapters import AgentRunManager, redact_secrets
from planaieditor.evolution_engine import EvolutionEngine
from planaieditor.planai_llm_core import PlanAILLMManager
from planaieditor.queue_store import QueueStore
from planaieditor.single_workflow_graph import run_reality_and_secret_scan

_UNAUTHORIZED_MOCK_RE = re.compile(
    r"\b(MOCK_DATA|FAKE_RESPONSE|PLACEHOLDER_VALUE|hdr_observed|fp_observed)\b"
)
_AUTH_QUOTE_MARKER = "RYAN EXPLICIT MOCK/FALLBACK AUTHORIZATION:"
_SECRET_DIFF_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,})"
)


# ---- Typed PlanAI Tasks -------------------------------------------------


class TeamGoalTask(Task):
    workflow_id: str
    project_id: str
    project_name: str
    repo_path: str
    default_branch: str
    base_branch: str = ""
    test_command: str = ""
    goal: str
    preferred_services: List[str] = Field(default_factory=list)
    session_key: str = ""
    round_num: int = 1
    max_rounds: int = 3
    existing_queue_item_id: str = ""


class ProjectContextTask(Task):
    workflow_id: str
    project_id: str
    project_name: str
    repo_path: str
    default_branch: str
    base_branch: str = ""
    test_command: str
    goal: str
    git_summary: str
    active_rules_block: str
    dispatch_services: List[str] = Field(default_factory=list)
    fitness_summary: str = ""
    session_key: str = ""
    round_num: int = 1
    max_rounds: int = 3
    existing_queue_item_id: str = ""


class SubtaskSpec(BaseModel):
    role: str = Field(description="Distinct specialist role name, e.g. Implementer or Verifier")
    service: str = Field(description="Assigned dispatch-ready agent service ID")
    objective: str = Field(description="Focused, concrete instructions for this sub-agent")
    owned_paths: List[str] = Field(
        default_factory=list,
        description="Disjoint files or directories owned by this sub-agent to prevent collisions",
    )


class LLMTeamPlanTask(Task):
    plan_summary: str = Field(description="Concise architectural summary of the team plan")
    subtasks: List[SubtaskSpec] = Field(
        description="2 to 3 non-overlapping sub-agent tasks"
    )


class TeamPlanTask(Task):
    workflow_id: str
    project_id: str
    project_name: str
    repo_path: str
    default_branch: str
    base_branch: str = ""
    test_command: str
    goal: str
    plan_summary: str
    subtasks: List[SubtaskSpec] = Field(default_factory=list)
    planner_generation: int = 1
    session_key: str = ""
    round_num: int = 1
    max_rounds: int = 3
    existing_queue_item_id: str = ""


class SubAgentDirectiveTask(Task):
    workflow_id: str
    project_id: str
    repo_path: str
    default_branch: str
    base_branch: str = ""
    test_command: str
    goal: str
    plan_summary: str
    subtask_index: int
    total_subtasks: int
    role: str
    service: str
    objective: str
    owned_paths: List[str] = Field(default_factory=list)
    session_key: str = ""
    round_num: int = 1
    max_rounds: int = 3
    existing_queue_item_id: str = ""


class SubAgentResultTask(Task):
    workflow_id: str
    project_id: str
    repo_path: str
    default_branch: str
    base_branch: str = ""
    test_command: str
    goal: str
    plan_summary: str
    subtask_index: int
    role: str
    service: str
    run_id: str
    passed: bool
    branch: str = ""
    commit_sha: str = ""
    changed_files: List[str] = Field(default_factory=list)
    response_text: str = ""
    duration_s: float = 0.0
    session_key: str = ""
    round_num: int = 1
    max_rounds: int = 3
    existing_queue_item_id: str = ""


class JoinedTeamSynthesisTask(Task):
    workflow_id: str
    project_id: str
    repo_path: str
    default_branch: str
    base_branch: str = ""
    test_command: str
    goal: str
    plan_summary: str
    integrated_branch: str = ""
    integrated_commit: str = ""
    integrated_worktree: str = ""
    merge_conflicts: List[str] = Field(default_factory=list)
    changed_files: List[str] = Field(default_factory=list)
    subagent_results: List[SubAgentResultTask] = Field(default_factory=list)
    session_key: str = ""
    round_num: int = 1
    max_rounds: int = 3
    existing_queue_item_id: str = ""


class VerifiedTeamBundleTask(Task):
    workflow_id: str
    project_id: str
    repo_path: str
    default_branch: str
    base_branch: str = ""
    test_command: str
    goal: str
    plan_summary: str
    integrated_branch: str = ""
    integrated_commit: str = ""
    changed_files: List[str] = Field(default_factory=list)
    merge_conflicts: List[str] = Field(default_factory=list)
    test_report: Dict[str, Any] = Field(default_factory=dict)
    reality_scan: Dict[str, Any] = Field(default_factory=dict)
    secret_scan: Dict[str, Any] = Field(default_factory=dict)
    gate_passed: bool = True
    subagent_results: List[SubAgentResultTask] = Field(default_factory=list)
    session_key: str = ""
    round_num: int = 1
    max_rounds: int = 3
    existing_queue_item_id: str = ""


TEAMWORK_GRAPH_PYTHON_SOURCE = """from planai import Graph, InitialTaskWorker, JoinedTaskWorker, LLMTaskWorker, SubGraphWorker, Task, TaskWorker

# Inner Planning SubGraph (ContextHarvester -> LLMTaskWorker LeadPlanner)
plan_graph = Graph(name="LeadPlanningSubGraph")
harvester = ContextHarvesterWorker()
planner = PlanAILeadPlannerLLMWorker(llm=llm, prompt=evolved_prompt)
plan_graph.add_workers(harvester, planner)
plan_graph.set_dependency(harvester, planner)
plan_graph.set_entry(harvester)
plan_graph.set_exit(planner)

planning_subgraph = SubGraphWorker(
    name="LeadPlanningSubGraph",
    graph=plan_graph,
    entry_worker=harvester,
    exit_worker=planner,
)

# Outer Multi-Agent Teamwork Graph
team_graph = Graph(name="MultiAgentTeamworkGraph")
fanout = SubtaskFanOutWorker()
executor = MultiAgentDispatchWorker(num_consumers=3)
joiner = TeamSynthesisJoiner()
gate = VerificationGateWorker()
sink = ChiefEscalationSink()

team_graph.add_workers(planning_subgraph, fanout, executor, joiner, gate, sink)
team_graph.set_dependency(planning_subgraph, fanout).next(executor).next(joiner).next(gate).next(sink)
"""


def _default_teamwork_nodes() -> List[Dict[str, Any]]:
    return [
        {
            "id": "ContextHarvesterWorker",
            "label": "ContextHarvesterWorker",
            "kind": "deterministic",
            "worker_type": "TaskWorker (SubGraph)",
            "svelte_type": "taskworker",
            "role": "Reads target project git state, branch, learned Brain rules & service fitness",
            "state": "idle",
            "position": {"x": 40, "y": 150},
            "metrics": {},
        },
        {
            "id": "LeadPlannerWorker",
            "label": "LeadPlannerWorker",
            "kind": "agent",
            "worker_type": "LLMTaskWorker (SubGraph)",
            "svelte_type": "llmtaskworker",
            "role": "Decomposes goal into disjoint multi-agent roles using evolved prompt",
            "state": "idle",
            "position": {"x": 290, "y": 150},
            "metrics": {},
        },
        {
            "id": "SubtaskFanOutWorker",
            "label": "SubtaskFanOutWorker",
            "kind": "deterministic",
            "worker_type": "TaskWorker",
            "svelte_type": "taskworker",
            "role": "Publishes N typed SubAgentDirectiveTasks in parallel",
            "state": "idle",
            "position": {"x": 540, "y": 150},
            "metrics": {},
        },
        {
            "id": "MultiAgentDispatchWorker",
            "label": "MultiAgentDispatchWorker",
            "kind": "agent",
            "worker_type": "TaskWorker (x3 parallel)",
            "svelte_type": "subgraphworker",
            "role": "Executes real agents (Antigravity / MiMo / MiniMax) in isolated git worktrees",
            "state": "idle",
            "position": {"x": 790, "y": 150},
            "metrics": {},
        },
        {
            "id": "TeamSynthesisJoiner",
            "label": "TeamSynthesisJoiner",
            "kind": "deterministic",
            "worker_type": "JoinedTaskWorker",
            "svelte_type": "joinedtaskworker",
            "role": "Joins all parallel SubAgentResultTasks by ProvenanceChain & merges worktrees",
            "state": "idle",
            "position": {"x": 1050, "y": 150},
            "metrics": {},
        },
        {
            "id": "VerificationGateWorker",
            "label": "VerificationGateWorker",
            "kind": "deterministic",
            "worker_type": "TaskWorker",
            "svelte_type": "taskworker",
            "role": "Runs project test_command + Law-2 Reality Scan + Secret Scan",
            "state": "idle",
            "position": {"x": 1300, "y": 150},
            "metrics": {},
        },
        {
            "id": "ChiefEscalationSink",
            "label": "ChiefEscalationSink",
            "kind": "human_gate",
            "worker_type": "TaskWorker",
            "svelte_type": "taskworker",
            "role": "Human Gate: approve & merge, request revision, or abort",
            "state": "idle",
            "position": {"x": 1550, "y": 150},
            "metrics": {},
        },
        {
            "id": "DoneTerminal",
            "label": "Landed",
            "kind": "terminal",
            "worker_type": "Terminal",
            "svelte_type": "taskworker",
            "role": "Integrated team branch merged onto target branch",
            "state": "idle",
            "position": {"x": 1800, "y": 100},
            "metrics": {},
        },
        {
            "id": "AbortedTerminal",
            "label": "Aborted",
            "kind": "terminal",
            "worker_type": "Terminal",
            "svelte_type": "taskworker",
            "role": "Workflow aborted or halted on fatal error",
            "state": "idle",
            "position": {"x": 1800, "y": 210},
            "metrics": {},
        },
    ]


def _default_teamwork_edges() -> List[Dict[str, Any]]:
    return [
        {
            "id": "e_ctx_plan",
            "source": "ContextHarvesterWorker",
            "target": "LeadPlannerWorker",
            "label": "context",
            "task_type": "ProjectContextTask",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_plan_fanout",
            "source": "LeadPlannerWorker",
            "target": "SubtaskFanOutWorker",
            "label": "plan",
            "task_type": "TeamPlanTask",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_fanout_exec",
            "source": "SubtaskFanOutWorker",
            "target": "MultiAgentDispatchWorker",
            "label": "directives",
            "task_type": "SubAgentDirectiveTask",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_exec_join",
            "source": "MultiAgentDispatchWorker",
            "target": "TeamSynthesisJoiner",
            "label": "results",
            "task_type": "SubAgentResultTask",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_join_gate",
            "source": "TeamSynthesisJoiner",
            "target": "VerificationGateWorker",
            "label": "integrated",
            "task_type": "JoinedTeamSynthesisTask",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_gate_sink",
            "source": "VerificationGateWorker",
            "target": "ChiefEscalationSink",
            "label": "verified",
            "task_type": "VerifiedTeamBundleTask",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_sink_done",
            "source": "ChiefEscalationSink",
            "target": "DoneTerminal",
            "label": "approve",
            "task_type": "MergeLanded",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_sink_revision",
            "source": "ChiefEscalationSink",
            "target": "LeadPlannerWorker",
            "label": "revision",
            "task_type": "RevisionDirective",
            "active": False,
            "is_back_edge": True,
        },
        {
            "id": "e_sink_abort",
            "source": "ChiefEscalationSink",
            "target": "AbortedTerminal",
            "label": "abort",
            "task_type": "Aborted",
            "active": False,
            "is_back_edge": False,
        },
    ]


def workflow_to_svelteflow(workflow: Dict[str, Any]) -> Dict[str, Any]:
    """Project a persisted `planai_workflow` row into PlanAI Editor SvelteFlow nodes & edges."""
    sf_nodes: List[Dict[str, Any]] = []
    for n in workflow.get("nodes") or []:
        sf_nodes.append(
            {
                "id": n["id"],
                "type": n.get("svelte_type") or "taskworker",
                "position": n.get("position") or {"x": 0, "y": 0},
                "data": {
                    "nodeName": n["label"],
                    "workerType": n.get("worker_type") or "TaskWorker",
                    "description": n.get("role") or "",
                    "state": n.get("state") or "idle",
                    "metrics": n.get("metrics") or {},
                },
            }
        )
    sf_edges: List[Dict[str, Any]] = []
    for e in workflow.get("edges") or []:
        sf_edges.append(
            {
                "id": e["id"],
                "source": e["source"],
                "target": e["target"],
                "label": e.get("task_type") or "Task",
                "animated": bool(e.get("active")),
            }
        )
    return {
        "graphName": workflow.get("title") or workflow.get("id"),
        "workflowId": workflow.get("id"),
        "state": workflow.get("state"),
        "nodes": sf_nodes,
        "edges": sf_edges,
        "pythonCode": workflow.get("python_code") or "",
    }


class TeamworkOrchestrator:
    """Runs multi-agent teamwork workflows across registered projects on real PlanAI graphs."""

    def __init__(
        self,
        store: QueueStore,
        root_path: Path,
        agent_manager: AgentRunManager,
        llm_manager: PlanAILLMManager,
        evolution_engine: EvolutionEngine,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self.store = store
        self.root_path = Path(root_path).resolve()
        self.worktrees_root = self.root_path / ".planai-queue" / "team-worktrees"
        self.agent_manager = agent_manager
        self.llm_manager = llm_manager
        self.evolution_engine = evolution_engine
        self._on_event = on_event or (lambda _t, _p: None)

    def _git(self, repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _prepare_subagent_worktree(
        self, repo_path: Path, base_branch: str, wf_id: str, idx: int, service: str
    ) -> tuple[Path, str, bool]:
        wt_base = (self.worktrees_root / wf_id / f"sub_{idx}_{service}").resolve()
        wt_base.parent.mkdir(parents=True, exist_ok=True)
        branch_name = f"team/{wf_id[-8:]}/sub-{idx}-{service}"
        if (repo_path / ".git").exists():
            # Verify base_branch exists; fall back to HEAD if needed
            ref_check = self._git(repo_path, "rev-parse", "--verify", base_branch)
            start_ref = base_branch if ref_check.returncode == 0 else "HEAD"
            add_wt = self._git(
                repo_path, "worktree", "add", "-B", branch_name, str(wt_base), start_ref
            )
            if add_wt.returncode == 0:
                return wt_base, branch_name, True
        wt_base.mkdir(parents=True, exist_ok=True)
        return wt_base, branch_name, False

    def _cleanup_worktree(self, repo_path: Path, wt_path: Path) -> None:
        if not wt_path.exists():
            return
        if (repo_path / ".git").exists():
            self._git(repo_path, "worktree", "remove", "--force", str(wt_path))
        if wt_path.exists():
            shutil.rmtree(wt_path, ignore_errors=True)

    def _reality_and_secret_scan(self, diff_text: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
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

    def start_teamwork_async(
        self,
        *,
        goal: str,
        project_id: str = "",
        preferred_services: Optional[List[str]] = None,
        session_key: str = "",
        timeout_per_agent: int = 180,
    ) -> Dict[str, Any]:
        clean_goal = goal.strip()
        if not clean_goal:
            raise ValueError("Missing required field: goal")

        proj = (
            self.store.get_project(project_id)
            if project_id
            else (self.store.list_projects()[0] if self.store.list_projects() else None)
        )
        if not proj:
            proj = self.store.ensure_default_project(
                self.root_path, self.agent_manager.default_dispatch_service()
            )

        wf_id = f"wf_team_{uuid.uuid4().hex[:8]}"
        lead_pv = self.store.get_active_prompt("lead_planner")
        cur_gen = int(lead_pv["generation"]) if lead_pv else 1
        nodes = _default_teamwork_nodes()
        edges = _default_teamwork_edges()

        wf = self.store.create_workflow(
            {
                "id": wf_id,
                "project_id": proj["id"],
                "session_key": session_key,
                "graph_type": "teamwork",
                "title": f"[{proj['name']}] {clean_goal[:72]}",
                "goal": clean_goal,
                "state": "running",
                "nodes": nodes,
                "edges": edges,
                "events": [],
                "provenance": [],
                "result": {
                    "round": 1,
                    "max_rounds": 3,
                    "visit_counts": {},
                    "current_state": "ContextHarvesterWorker",
                },
                "python_code": TEAMWORK_GRAPH_PYTHON_SOURCE,
                "evolution_gen": cur_gen,
            }
        )
        self._on_event("planai_workflow_updated", {"workflow": wf})

        if session_key:
            self._on_event(
                "webclaw_chat",
                {
                    "runId": wf_id,
                    "sessionKey": session_key,
                    "state": "delta",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Launching PlanAI `MultiAgentTeamworkGraph` (`{wf_id}`, Gen v{cur_gen}) on project **{proj['name']}** (`{proj['repo_path']}`)…",
                            }
                        ],
                        "timestamp": int(time.time() * 1000),
                    },
                },
            )

        thread = threading.Thread(
            target=self._execute_teamwork_graph,
            kwargs={
                "wf_id": wf_id,
                "proj": proj,
                "goal": clean_goal,
                "preferred_services": preferred_services or [],
                "session_key": session_key,
                "timeout_per_agent": timeout_per_agent,
                "nodes": nodes,
                "edges": edges,
                "round_num": 1,
                "max_rounds": 3,
                "base_branch": str(proj.get("default_branch") or "main"),
                "existing_queue_item_id": "",
            },
            daemon=True,
            name=f"planai-team-{wf_id}",
        )
        thread.start()
        return wf

    def resume_revision_async(
        self,
        *,
        wf_id: str,
        item: Dict[str, Any],
        revision_note: str,
        timeout_per_agent: int = 180,
    ) -> Dict[str, Any]:
        """Run a real cyclic `FORCE_REVISION` round of `MultiAgentTeamworkGraph` on the integrated branch."""
        clean_note = revision_note.strip()
        if not clean_note:
            raise ValueError("Revision feedback note is required for FORCE_REVISION.")

        wf = self.store.get_workflow(wf_id)
        if not wf or wf.get("graph_type") != "teamwork":
            raise ValueError(f"Teamwork workflow '{wf_id}' not found.")

        cur_round = int(wf.get("round") or 1)
        max_rounds = int(wf.get("max_rounds") or 3)
        if cur_round >= max_rounds:
            raise ValueError(
                f"Maximum revision rounds ({max_rounds}) reached for workflow '{wf_id}'."
            )
        next_round = cur_round + 1

        proj = (
            self.store.get_project(str(wf.get("project_id") or item.get("project_id") or ""))
            or self.store.ensure_default_project(
                self.root_path, self.agent_manager.default_dispatch_service()
            )
        )
        nodes = list(wf.get("nodes") or _default_teamwork_nodes())
        edges = list(wf.get("edges") or _default_teamwork_edges())
        for n in nodes:
            if n["id"] not in ("DoneTerminal", "AbortedTerminal"):
                n["state"] = "idle"
        for e in edges:
            e["active"] = e.get("id") == "e_sink_revision"

        wf_res = dict(wf.get("result") or {})
        wf_res["round"] = next_round
        wf_res["max_rounds"] = max_rounds
        wf_res["current_state"] = "LeadPlannerWorker"
        updated_wf = self.store.update_workflow(
            wf_id, state="running", nodes=nodes, edges=edges, result=wf_res
        )
        if updated_wf:
            self._on_event("planai_workflow_updated", {"workflow": updated_wf})

        self.store.update_item(item["id"], status="in_progress")
        base_branch = str(item.get("branch") or proj.get("default_branch") or "main")
        revised_goal = (
            f"{wf.get('goal')}\n\n"
            f"[Revision Round {next_round}/{max_rounds} — Operator Gate Feedback]\n"
            f"{clean_note}"
        )

        thread = threading.Thread(
            target=self._execute_teamwork_graph,
            kwargs={
                "wf_id": wf_id,
                "proj": proj,
                "goal": revised_goal,
                "preferred_services": list(wf_res.get("services_used") or []),
                "session_key": str(wf.get("session_key") or ""),
                "timeout_per_agent": timeout_per_agent,
                "nodes": nodes,
                "edges": edges,
                "round_num": next_round,
                "max_rounds": max_rounds,
                "base_branch": base_branch,
                "existing_queue_item_id": str(item["id"]),
            },
            daemon=True,
            name=f"planai-team-rev-{wf_id}-r{next_round}",
        )
        thread.start()
        return updated_wf or wf

    def _execute_teamwork_graph(
        self,
        *,
        wf_id: str,
        proj: Dict[str, Any],
        goal: str,
        preferred_services: List[str],
        session_key: str,
        timeout_per_agent: int,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        round_num: int = 1,
        max_rounds: int = 3,
        base_branch: str = "",
        existing_queue_item_id: str = "",
    ) -> None:
        existing_wf = self.store.get_workflow(wf_id) or {}
        events: List[Dict[str, Any]] = list(existing_wf.get("events") or [])
        provenance_log: List[Dict[str, Any]] = list(existing_wf.get("provenance") or [])
        result_meta: Dict[str, Any] = dict(existing_wf.get("result") or {})
        visit_counts: Dict[str, int] = {
            str(k): int(v) for k, v in dict(result_meta.get("visit_counts") or {}).items()
        }
        result_meta["round"] = round_num
        result_meta["max_rounds"] = max_rounds
        state_lock = threading.Lock()
        orchestrator = self
        final_outcomes: List[Dict[str, Any]] = []

        def update_graph_state(
            node_id: str,
            new_state: str,
            detail: str = "",
            edge_id: str = "",
            metrics: Optional[Dict[str, Any]] = None,
            prov: Optional[List[str]] = None,
            count_visit: bool = False,
        ) -> None:
            with state_lock:
                if count_visit:
                    visit_counts[node_id] = int(visit_counts.get(node_id) or 0) + 1
                for n in nodes:
                    if n["id"] == node_id:
                        n["state"] = new_state
                        merged_m = {**dict(n.get("metrics") or {})}
                        if metrics:
                            merged_m.update(metrics)
                        if node_id in visit_counts:
                            merged_m["visits"] = visit_counts[node_id]
                        n["metrics"] = merged_m
                for e in edges:
                    e["active"] = e["id"] == edge_id and new_state == "running"
                evt = {
                    "ts": time.time(),
                    "node_id": node_id,
                    "state": new_state,
                    "detail": detail,
                }
                events.append(evt)
                if prov:
                    provenance_log.append(
                        {"ts": time.time(), "node_id": node_id, "chain": prov}
                    )
                result_meta["visit_counts"] = dict(visit_counts)
                result_meta["current_state"] = node_id
                wf_row = orchestrator.store.update_workflow(
                    wf_id,
                    nodes=nodes,
                    edges=edges,
                    events=events,
                    provenance=provenance_log,
                    result=result_meta,
                )
            if wf_row:
                orchestrator._on_event("planai_workflow_updated", {"workflow": wf_row})

        def _build_team_plan_from_parsed(
            task: ProjectContextTask,
            parsed: Optional[LLMTeamPlanTask],
            gen: int,
        ) -> TeamPlanTask:
            subtasks: List[SubtaskSpec] = []
            plan_summary = ""
            if parsed is not None:
                plan_summary = parsed.plan_summary.strip()
                for idx, st in enumerate(parsed.subtasks[:3]):
                    svc = (
                        st.service
                        if st.service in task.dispatch_services
                        else task.dispatch_services[idx % len(task.dispatch_services)]
                    )
                    subtasks.append(
                        SubtaskSpec(
                            role=st.role.strip() or f"Specialist-{idx + 1}",
                            service=svc,
                            objective=st.objective.strip() or task.goal,
                            owned_paths=st.owned_paths,
                        )
                    )
            if len(subtasks) < 2:
                svc_primary = task.dispatch_services[0]
                svc_secondary = task.dispatch_services[1 % len(task.dispatch_services)]
                plan_summary = (
                    f"Two-agent parallel split across {svc_primary} (Implementation) "
                    f"and {svc_secondary} (Verification & Audit) with isolated git worktrees."
                )
                subtasks = [
                    SubtaskSpec(
                        role="Implementation Lead",
                        service=svc_primary,
                        objective=(
                            f"Execute primary implementation for goal: {task.goal}. "
                            "Work strictly inside your assigned workspace directory and keep changes clean and minimal."
                        ),
                        owned_paths=["implementation"],
                    ),
                    SubtaskSpec(
                        role="Verification & Edge-Case Auditor",
                        service=svc_secondary,
                        objective=(
                            f"Independently audit requirements, edge cases, and verification criteria for goal: {task.goal}. "
                            "Produce concise verification notes or companion test checks without conflicting with primary implementation files."
                        ),
                        owned_paths=["verification"],
                    ),
                ]
            return TeamPlanTask(
                workflow_id=task.workflow_id,
                project_id=task.project_id,
                project_name=task.project_name,
                repo_path=task.repo_path,
                default_branch=task.default_branch,
                base_branch=task.base_branch,
                test_command=task.test_command,
                goal=task.goal,
                plan_summary=plan_summary,
                subtasks=subtasks,
                planner_generation=gen,
                session_key=task.session_key,
                round_num=task.round_num,
                max_rounds=task.max_rounds,
                existing_queue_item_id=task.existing_queue_item_id,
            )

        class ContextHarvesterWorker(TaskWorker):
            output_types: List[Type[Task]] = [ProjectContextTask]

            def consume_work(self, task: TeamGoalTask) -> None:
                update_graph_state(
                    "ContextHarvesterWorker",
                    "running",
                    f"Inspecting project '{task.project_name}' at {task.repo_path}",
                    count_visit=True,
                )
                repo = Path(task.repo_path)
                git_summary = "Non-git directory"
                if (repo / ".git").exists():
                    recent = orchestrator._git(repo, "log", "-n", "3", "--oneline").stdout.strip()
                    top_files = [
                        p.name
                        for p in sorted(repo.iterdir(), key=lambda x: x.name)[:18]
                        if not p.name.startswith(".")
                    ]
                    git_summary = f"Branch: {task.base_branch or task.default_branch} | Top entries: {', '.join(top_files)} | Recent commits: {recent}"

                services_info = orchestrator.agent_manager.list_services()
                ready_services = [
                    s["service"] for s in services_info if s.get("dispatch_ready")
                ]
                fitness = orchestrator.store.compute_service_fitness(project_id=task.project_id)
                fitness_map = {
                    f["service"]: f["empirical_pass_rate"]
                    for f in fitness
                    if f["empirical_pass_rate"] is not None
                }
                ready_services.sort(
                    key=lambda s: fitness_map.get(s, 0.5), reverse=True
                )
                if task.preferred_services:
                    valid_pref = [s for s in task.preferred_services if s in ready_services]
                    if valid_pref:
                        ready_services = valid_pref + [
                            s for s in ready_services if s not in valid_pref
                        ]

                fitness_summary = ", ".join(
                    f"{s} (pass_rate={fitness_map[s]:.0%})" if s in fitness_map else f"{s} (ready)"
                    for s in ready_services
                ) or "no dispatch-ready CLI adapters"
                rules_block = orchestrator.evolution_engine.format_rules_block(
                    project_id=task.project_id
                )

                ctx_task = ProjectContextTask(
                    workflow_id=task.workflow_id,
                    project_id=task.project_id,
                    project_name=task.project_name,
                    repo_path=task.repo_path,
                    default_branch=task.default_branch,
                    base_branch=task.base_branch or task.default_branch,
                    test_command=task.test_command,
                    goal=task.goal,
                    git_summary=git_summary,
                    active_rules_block=rules_block,
                    dispatch_services=ready_services,
                    fitness_summary=fitness_summary,
                    session_key=task.session_key,
                    round_num=task.round_num,
                    max_rounds=task.max_rounds,
                    existing_queue_item_id=task.existing_queue_item_id,
                )
                self.publish_work(ctx_task, input_task=task)
                update_graph_state(
                    "ContextHarvesterWorker",
                    "succeeded",
                    f"Ready services: {', '.join(ready_services) or 'none'}",
                    edge_id="e_ctx_plan",
                    metrics={"dispatch_services": ready_services},
                )

        class PlanAILeadPlannerLLMWorker(LLMTaskWorker):
            """Genuine PlanAI `LLMTaskWorker` executing the evolved LeadPlanner prompt."""

            llm_input_type: Type[Task] = ProjectContextTask
            llm_output_type: Type[Task] = LLMTeamPlanTask
            output_types: List[Type[Task]] = [TeamPlanTask]

            def pre_process(self, task: Task) -> Optional[Task]:
                return None

            def format_prompt(self, task: Task) -> str:
                assert isinstance(task, ProjectContextTask)
                pv = orchestrator.store.get_active_prompt("lead_planner")
                template = (
                    str(pv["prompt_template"])
                    if pv
                    else "Decompose goal '{goal}' for {project_name}"
                )
                rendered = (
                    template.replace("{project_name}", task.project_name)
                    .replace("{repo_path}", task.repo_path)
                    .replace("{active_rules_block}", task.active_rules_block)
                    .replace("{services_fitness_block}", task.fitness_summary)
                    .replace("{goal}", task.goal)
                    .replace("{git_context}", task.git_summary)
                )
                return (
                    f"{rendered}\n\n"
                    f"Assign ONLY from dispatch-ready services: {', '.join(task.dispatch_services)}."
                )

            def extra_validation(self, response: Task, input_task: Task) -> Optional[str]:
                if isinstance(response, LLMTeamPlanTask) and len(response.subtasks) < 2:
                    return "LeadPlanner must return at least 2 non-overlapping subtasks."
                return None

            def _invoke_llm(self, task: Task):
                assert isinstance(task, ProjectContextTask)
                update_graph_state(
                    "LeadPlannerWorker",
                    "running",
                    "Decomposing goal via PlanAI LLMTaskWorker",
                    edge_id="e_ctx_plan",
                    count_visit=True,
                )
                if not task.dispatch_services:
                    raise PermissionError(
                        "No dispatch-ready agent services available to execute multi-agent teamwork."
                    )
                try:
                    return super()._invoke_llm(task)
                except Exception:
                    self.post_process(response=None, input_task=task)

            def post_process(self, response: Optional[Task], input_task: Task) -> None:
                assert isinstance(input_task, ProjectContextTask)
                pv = orchestrator.store.get_active_prompt("lead_planner")
                gen = int(pv["generation"]) if pv else 1
                parsed = response if isinstance(response, LLMTeamPlanTask) else None
                plan_task = _build_team_plan_from_parsed(input_task, parsed, gen)
                self.publish_work(task=plan_task, input_task=input_task)
                update_graph_state(
                    "LeadPlannerWorker",
                    "succeeded",
                    f"Planned {len(plan_task.subtasks)} sub-agent roles (Gen v{gen}): "
                    + ", ".join(f"{s.role}→{s.service}" for s in plan_task.subtasks),
                    edge_id="e_plan_fanout",
                    metrics={
                        "planner_generation": gen,
                        "subtasks_count": len(plan_task.subtasks),
                        "llm_worker": "PlanAILeadPlannerLLMWorker",
                        "assignments": [
                            {"role": s.role, "service": s.service}
                            for s in plan_task.subtasks
                        ],
                    },
                )

        class DeterministicLeadPlannerWorker(TaskWorker):
            """Deterministic PlanAI planner used only when local/cloud LLM is explicitly disabled."""

            output_types: List[Type[Task]] = [TeamPlanTask]

            def consume_work(self, task: ProjectContextTask) -> None:
                update_graph_state(
                    "LeadPlannerWorker",
                    "running",
                    "Decomposing goal into parallel sub-agent assignments",
                    edge_id="e_ctx_plan",
                    count_visit=True,
                )
                if not task.dispatch_services:
                    raise PermissionError(
                        "No dispatch-ready agent services available to execute multi-agent teamwork."
                    )
                pv = orchestrator.store.get_active_prompt("lead_planner")
                gen = int(pv["generation"]) if pv else 1
                plan_task = _build_team_plan_from_parsed(task, None, gen)
                self.publish_work(plan_task, input_task=task)
                update_graph_state(
                    "LeadPlannerWorker",
                    "succeeded",
                    f"Planned {len(plan_task.subtasks)} sub-agent roles (Gen v{gen}): "
                    + ", ".join(f"{s.role}→{s.service}" for s in plan_task.subtasks),
                    edge_id="e_plan_fanout",
                    metrics={
                        "planner_generation": gen,
                        "subtasks_count": len(plan_task.subtasks),
                        "llm_worker": "DeterministicLeadPlannerWorker",
                        "assignments": [
                            {"role": s.role, "service": s.service}
                            for s in plan_task.subtasks
                        ],
                    },
                )

        class SubtaskFanOutWorker(TaskWorker):
            output_types: List[Type[Task]] = [SubAgentDirectiveTask]

            def consume_work(self, task: TeamPlanTask) -> None:
                total = len(task.subtasks)
                with state_lock:
                    existing_ids = {n["id"] for n in nodes}
                    for idx, spec in enumerate(task.subtasks):
                        lane_id = f"subagent_{idx + 1}"
                        if lane_id not in existing_ids:
                            nodes.append(
                                {
                                    "id": lane_id,
                                    "label": spec.service,
                                    "kind": "agent",
                                    "worker_class": "MultiAgentDispatchWorker",
                                    "role": spec.role,
                                    "state": "idle",
                                    "lane_index": idx,
                                    "total_lanes": total,
                                    "metrics": {"service": spec.service, "role": spec.role},
                                }
                            )
                            edges.append(
                                {
                                    "id": f"e_fanout_{lane_id}",
                                    "source": "SubtaskFanOutWorker",
                                    "target": lane_id,
                                    "label": spec.role,
                                    "task_type": "SubAgentDirectiveTask",
                                    "active": True,
                                    "is_back_edge": False,
                                }
                            )
                            edges.append(
                                {
                                    "id": f"e_{lane_id}_join",
                                    "source": lane_id,
                                    "target": "TeamSynthesisJoiner",
                                    "label": "result",
                                    "task_type": "SubAgentResultTask",
                                    "active": False,
                                    "is_back_edge": False,
                                }
                            )
                update_graph_state(
                    "SubtaskFanOutWorker",
                    "running",
                    f"Fanning out {total} parallel SubAgentDirectiveTasks",
                    edge_id="e_plan_fanout",
                    count_visit=True,
                )
                for idx, spec in enumerate(task.subtasks):
                    directive = SubAgentDirectiveTask(
                        workflow_id=task.workflow_id,
                        project_id=task.project_id,
                        repo_path=task.repo_path,
                        default_branch=task.default_branch,
                        base_branch=task.base_branch,
                        test_command=task.test_command,
                        goal=task.goal,
                        plan_summary=task.plan_summary,
                        subtask_index=idx + 1,
                        total_subtasks=total,
                        role=spec.role,
                        service=spec.service,
                        objective=spec.objective,
                        owned_paths=spec.owned_paths,
                        session_key=task.session_key,
                        round_num=task.round_num,
                        max_rounds=task.max_rounds,
                        existing_queue_item_id=task.existing_queue_item_id,
                    )
                    self.publish_work(directive, input_task=task)
                update_graph_state(
                    "SubtaskFanOutWorker",
                    "succeeded",
                    f"Dispatched {total} directives to MultiAgentDispatchWorker",
                    edge_id="e_fanout_exec",
                    metrics={"fanned_out": total},
                )

        class MultiAgentDispatchWorker(TaskWorker):
            output_types: List[Type[Task]] = [SubAgentResultTask]

            def consume_work(self, task: SubAgentDirectiveTask) -> None:
                lane_id = f"subagent_{task.subtask_index}"
                update_graph_state(
                    "MultiAgentDispatchWorker",
                    "running",
                    f"Running [{task.subtask_index}/{task.total_subtasks}] {task.role} on {task.service}",
                    edge_id="e_fanout_exec",
                    count_visit=(task.subtask_index == 1),
                )
                repo_path = Path(task.repo_path).resolve()
                wt_dir, branch_name, is_git_wt = orchestrator._prepare_subagent_worktree(
                    repo_path,
                    task.base_branch or task.default_branch,
                    f"{task.workflow_id}_r{task.round_num}",
                    task.subtask_index,
                    task.service,
                )
                update_graph_state(
                    lane_id,
                    "running",
                    f"{task.service} · {task.role} ({branch_name})",
                    edge_id=f"e_fanout_{lane_id}",
                    metrics={
                        "service": task.service,
                        "role": task.role,
                        "branch": branch_name,
                        "round": task.round_num,
                    },
                    count_visit=True,
                )
                run_id = f"run_{uuid.uuid4().hex[:10]}"
                adapter = orchestrator.agent_manager.get_adapter(task.service)
                probe = adapter.probe()
                selected_model = str(probe.get("default_model") or "")

                orchestrator.store.claim_ownership(
                    repo=str(repo_path),
                    worktree=str(wt_dir),
                    branch=branch_name,
                    service=task.service,
                    run_id=run_id,
                    project_id=task.project_id,
                )
                full_prompt = (
                    f"[Teamwork Role: {task.role} ({task.subtask_index}/{task.total_subtasks}) — Round {task.round_num}/{task.max_rounds}]\n"
                    f"Workspace Directory: {wt_dir}\n"
                    f"Overall Goal: {task.goal}\n"
                    f"Your Assigned Objective: {task.objective}\n"
                    f"Owned Scope: {', '.join(task.owned_paths) if task.owned_paths else 'assigned role scope'}\n"
                    f"Operate strictly inside '{wt_dir}' and provide a concise summary of your work."
                )
                run_row = orchestrator.store.create_run(
                    {
                        "id": run_id,
                        "service": task.service,
                        "model": selected_model,
                        "prompt": redact_secrets(full_prompt),
                        "cwd": str(wt_dir),
                        "branch": branch_name,
                        "webclaw_session_key": task.session_key,
                        "project_id": task.project_id,
                        "workflow_id": task.workflow_id,
                        "role": task.role,
                        "state": "running",
                        "metadata": {
                            "teamwork": True,
                            "subtask_index": task.subtask_index,
                            "round": task.round_num,
                        },
                    }
                )
                orchestrator._on_event("run_started", {"run": run_row})

                try:
                    res = adapter.dispatch(
                        prompt=full_prompt,
                        cwd=wt_dir,
                        model=selected_model,
                        timeout=timeout_per_agent,
                    )
                except Exception as exc:
                    from planaieditor.agent_adapters import AdapterRunResult

                    res = AdapterRunResult(
                        passed=False,
                        exit_code=1,
                        model=selected_model,
                        response_text=f"Adapter error: {exc}",
                        stderr_tail=str(exc),
                    )
                finally:
                    orchestrator.store.release_ownership(run_id)

                commit_sha = ""
                changed_files: List[str] = []
                if is_git_wt and res.passed:
                    orchestrator._git(wt_dir, "add", "-A")
                    diff_names = orchestrator._git(
                        wt_dir, "diff", "--cached", "--name-only"
                    ).stdout.splitlines()
                    changed_files = [
                        f.strip()
                        for f in diff_names
                        if f.strip() and not f.strip().startswith(".mimocode")
                    ]
                    if changed_files:
                        orchestrator._git(wt_dir, "config", "user.email", "autoplan@local.invalid")
                        orchestrator._git(wt_dir, "config", "user.name", "AutoPlan Team Agent")
                        orchestrator._git(
                            wt_dir,
                            "commit",
                            "-m",
                            f"feat({task.service},r{task.round_num}): {task.role} for {task.workflow_id}",
                        )
                        commit_sha = orchestrator._git(
                            wt_dir, "rev-parse", "HEAD"
                        ).stdout.strip()
                    else:
                        orchestrator._git(wt_dir, "reset", "--hard", "HEAD")
                        orchestrator._git(wt_dir, "clean", "-fd")

                orchestrator._cleanup_worktree(repo_path, wt_dir)

                updated_run = orchestrator.store.update_run(
                    run_id,
                    session_id=res.session_id,
                    state="succeeded" if res.passed else "failed",
                    exit_code=res.exit_code,
                    response_text=res.response_text,
                    stdout_tail=res.stdout_tail,
                    stderr_tail=res.stderr_tail,
                    metadata={
                        "teamwork": True,
                        "role": task.role,
                        "commit_sha": commit_sha,
                        "changed_files": changed_files,
                        "duration_s": res.duration_s,
                        "round": task.round_num,
                    },
                    finished_at=time.time(),
                )
                orchestrator._on_event("run_updated", {"run": updated_run})
                update_graph_state(
                    lane_id,
                    "succeeded" if res.passed else "failed",
                    (
                        f"Committed {commit_sha[:10]} ({len(changed_files)} files)"
                        if commit_sha
                        else f"Finished ({'ok' if res.passed else 'failed'})"
                    ),
                    edge_id=f"e_{lane_id}_join",
                    metrics={
                        "service": task.service,
                        "role": task.role,
                        "branch": branch_name,
                        "commit_sha": commit_sha[:10] if commit_sha else "",
                        "changed_files": changed_files,
                        "duration_s": res.duration_s,
                    },
                )

                prov = [str(p) for p in getattr(task, "_provenance", [])]
                out_task = SubAgentResultTask(
                    workflow_id=task.workflow_id,
                    project_id=task.project_id,
                    repo_path=task.repo_path,
                    default_branch=task.default_branch,
                    base_branch=task.base_branch,
                    test_command=task.test_command,
                    goal=task.goal,
                    plan_summary=task.plan_summary,
                    subtask_index=task.subtask_index,
                    role=task.role,
                    service=task.service,
                    run_id=run_id,
                    passed=res.passed,
                    branch=branch_name if commit_sha else "",
                    commit_sha=commit_sha,
                    changed_files=changed_files,
                    response_text=res.response_text,
                    duration_s=res.duration_s,
                    session_key=task.session_key,
                    round_num=task.round_num,
                    max_rounds=task.max_rounds,
                    existing_queue_item_id=task.existing_queue_item_id,
                )
                self.publish_work(out_task, input_task=task)
                update_graph_state(
                    "MultiAgentDispatchWorker",
                    "succeeded" if res.passed else "failed",
                    f"Completed {task.role} ({task.service}) in {res.duration_s}s",
                    edge_id="e_exec_join",
                    prov=prov,
                )

        class TeamSynthesisJoiner(JoinedTaskWorker):
            output_types: List[Type[Task]] = [JoinedTeamSynthesisTask]
            join_type: Type[TaskWorker] = InitialTaskWorker

            def consume_work_joined(self, tasks: List[SubAgentResultTask]) -> None:
                update_graph_state(
                    "TeamSynthesisJoiner",
                    "running",
                    f"Joined {len(tasks)} parallel sub-agent results via ProvenanceChain",
                    edge_id="e_exec_join",
                    count_visit=True,
                )
                first = tasks[0]
                repo_path = Path(first.repo_path).resolve()
                committed_tasks = [t for t in tasks if t.commit_sha and t.branch]
                integrated_branch = ""
                integrated_commit = ""
                integrated_wt = ""
                merge_conflicts: List[str] = []
                all_changed: List[str] = []

                start_base = first.base_branch or first.default_branch
                if committed_tasks and (repo_path / ".git").exists():
                    wt_int = (
                        orchestrator.worktrees_root
                        / f"{first.workflow_id}_r{first.round_num}"
                        / "integrated"
                    ).resolve()
                    wt_int.parent.mkdir(parents=True, exist_ok=True)
                    integrated_branch = f"team/{first.workflow_id[-8:]}/integrated"
                    ref_check = orchestrator._git(
                        repo_path, "rev-parse", "--verify", start_base
                    )
                    start_ref = start_base if ref_check.returncode == 0 else "HEAD"
                    add_wt = orchestrator._git(
                        repo_path,
                        "worktree",
                        "add",
                        "-B",
                        integrated_branch,
                        str(wt_int),
                        start_ref,
                    )
                    if add_wt.returncode == 0:
                        integrated_wt = str(wt_int)
                        orchestrator._git(wt_int, "config", "user.email", "autoplan@local.invalid")
                        orchestrator._git(wt_int, "config", "user.name", "AutoPlan Synthesizer")
                        for ct in committed_tasks:
                            m = orchestrator._git(
                                wt_int,
                                "merge",
                                "--no-ff",
                                ct.branch,
                                "-m",
                                f"Merge {ct.role} ({ct.service}) into {integrated_branch}",
                            )
                            if m.returncode != 0:
                                orchestrator._git(wt_int, "merge", "--abort")
                                merge_conflicts.append(
                                    f"{ct.role} ({ct.service}) conflicted on {', '.join(ct.changed_files)}"
                                )
                            else:
                                all_changed.extend(ct.changed_files)
                        diff_all = orchestrator._git(
                            wt_int, "diff", "--name-only", f"{first.default_branch}..HEAD"
                        ).stdout
                        for fn in diff_all.splitlines():
                            if fn.strip():
                                all_changed.append(fn.strip())
                        integrated_commit = orchestrator._git(
                            wt_int, "rev-parse", "HEAD"
                        ).stdout.strip()

                prov = [str(p) for p in getattr(first, "_provenance", [])]
                joined_task = JoinedTeamSynthesisTask(
                    workflow_id=first.workflow_id,
                    project_id=first.project_id,
                    repo_path=first.repo_path,
                    default_branch=first.default_branch,
                    base_branch=first.base_branch,
                    test_command=first.test_command,
                    goal=first.goal,
                    plan_summary=first.plan_summary,
                    integrated_branch=integrated_branch,
                    integrated_commit=integrated_commit,
                    integrated_worktree=integrated_wt,
                    merge_conflicts=merge_conflicts,
                    changed_files=sorted(set(all_changed)),
                    subagent_results=tasks,
                    session_key=first.session_key,
                    round_num=first.round_num,
                    max_rounds=first.max_rounds,
                    existing_queue_item_id=first.existing_queue_item_id,
                )
                self.publish_work(joined_task, input_task=first)
                update_graph_state(
                    "TeamSynthesisJoiner",
                    "succeeded",
                    f"Joined {len(tasks)} agents; {len(set(all_changed))} files integrated",
                    edge_id="e_join_gate",
                    metrics={
                        "joined_agents": len(tasks),
                        "changed_files_count": len(set(all_changed)),
                        "conflicts_count": len(merge_conflicts),
                    },
                    prov=prov,
                )

        class VerificationGateWorker(TaskWorker):
            output_types: List[Type[Task]] = [VerifiedTeamBundleTask]

            def consume_work(self, task: JoinedTeamSynthesisTask) -> None:
                update_graph_state(
                    "VerificationGateWorker",
                    "running",
                    "Running project test_command + Law-2 reality & secret scans",
                    edge_id="e_join_gate",
                    count_visit=True,
                )
                repo_path = Path(task.repo_path).resolve()
                wt_path = Path(task.integrated_worktree) if task.integrated_worktree else None
                exec_cwd = wt_path if (wt_path and wt_path.exists()) else repo_path

                test_report: Dict[str, Any] = {"configured": False, "passed": True}
                if task.test_command.strip() and task.changed_files:
                    started = time.time()
                    try:
                        tokens = shlex.split(task.test_command)
                        cmd_env = dict(os.environ)
                        while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
                            k, v = tokens[0].split("=", 1)
                            if k.isidentifier():
                                cmd_env[k] = v
                                tokens.pop(0)
                            else:
                                break
                        proc = subprocess.run(
                            tokens,
                            cwd=str(exec_cwd),
                            env=cmd_env,
                            capture_output=True,
                            text=True,
                            timeout=300,
                        )
                        test_report = {
                            "configured": True,
                            "command": task.test_command,
                            "exit_code": proc.returncode,
                            "passed": proc.returncode == 0,
                            "stdout_tail": proc.stdout[-2000:],
                            "stderr_tail": proc.stderr[-2000:],
                            "duration_s": round(time.time() - started, 2),
                        }
                    except Exception as test_exc:
                        test_report = {
                            "configured": True,
                            "command": task.test_command,
                            "exit_code": -1,
                            "passed": False,
                            "stderr_tail": str(test_exc),
                        }

                diff_text = ""
                if wt_path and wt_path.exists() and task.changed_files:
                    diff_text = orchestrator._git(
                        wt_path, "diff", f"{task.default_branch}..HEAD"
                    ).stdout

                reality_scan, secret_scan = run_reality_and_secret_scan(diff_text)
                if wt_path and wt_path.exists():
                    orchestrator._cleanup_worktree(repo_path, wt_path)

                all_agents_ok = all(r.passed for r in task.subagent_results)
                gate_passed = (
                    all_agents_ok
                    and len(task.merge_conflicts) == 0
                    and bool(test_report.get("passed", True))
                    and bool(reality_scan["passed"])
                    and bool(secret_scan["passed"])
                )

                verified = VerifiedTeamBundleTask(
                    workflow_id=task.workflow_id,
                    project_id=task.project_id,
                    repo_path=task.repo_path,
                    default_branch=task.default_branch,
                    base_branch=task.base_branch,
                    test_command=task.test_command,
                    goal=task.goal,
                    plan_summary=task.plan_summary,
                    integrated_branch=task.integrated_branch if task.changed_files else "",
                    integrated_commit=task.integrated_commit if task.changed_files else "",
                    changed_files=task.changed_files,
                    merge_conflicts=task.merge_conflicts,
                    test_report=test_report,
                    reality_scan=reality_scan,
                    secret_scan=secret_scan,
                    gate_passed=gate_passed,
                    subagent_results=task.subagent_results,
                    session_key=task.session_key,
                    round_num=task.round_num,
                    max_rounds=task.max_rounds,
                    existing_queue_item_id=task.existing_queue_item_id,
                )
                self.publish_work(verified, input_task=task)
                update_graph_state(
                    "VerificationGateWorker",
                    "succeeded" if gate_passed else "failed",
                    f"Gate {'PASSED' if gate_passed else 'FLAGGED'} (reality={reality_scan['passed']}, secrets={secret_scan['passed']})",
                    edge_id="e_gate_sink",
                    metrics={
                        "gate_passed": gate_passed,
                        "test_passed": test_report.get("passed", True),
                        "reality_passed": reality_scan["passed"],
                        "secret_passed": secret_scan["passed"],
                    },
                )

        class ChiefEscalationSink(TaskWorker):
            output_types: List[Type[Task]] = []

            def consume_work(self, task: VerifiedTeamBundleTask) -> None:
                update_graph_state(
                    "ChiefEscalationSink",
                    "running",
                    "Preparing Chief ReviewItem & recording Evolution telemetry",
                    edge_id="e_gate_sink",
                    count_visit=True,
                )
                services_used = sorted({r.service for r in task.subagent_results})
                source_label = "team:" + "+".join(services_used)
                sections = [
                    f"### PlanAI Multi-Agent Teamwork Summary (`{task.workflow_id}`, Round {task.round_num}/{task.max_rounds})",
                    f"**Plan:** {task.plan_summary}",
                    "",
                    "#### Sub-Agent Outcomes",
                ]
                for r in task.subagent_results:
                    badge = "PASS" if r.passed else "FAIL"
                    commit_note = f" · commit `{r.commit_sha[:10]}`" if r.commit_sha else ""
                    sections.append(
                        f"- **{r.role}** (`{r.service}`, run `{r.run_id}`, {r.duration_s}s) [{badge}]{commit_note}:\n  {(r.response_text or '(no output)').strip()[:600]}"
                    )
                if task.merge_conflicts:
                    sections.append("\n**Merge Conflicts:** " + "; ".join(task.merge_conflicts))
                if not task.reality_scan.get("passed", True):
                    sections.append(
                        "\n**Law-2 Reality Violations:** "
                        + "; ".join(task.reality_scan.get("violations") or [])
                    )

                has_code = bool(task.changed_files and task.integrated_branch)
                item_result_payload: Dict[str, Any] = {
                    "workflow_id": task.workflow_id,
                    "round": task.round_num,
                    "branch_commit": task.integrated_commit,
                    "subagent_runs": [r.run_id for r in task.subagent_results],
                    "reality_scan": task.reality_scan,
                    "secret_scan": task.secret_scan,
                    "gate_test": task.test_report,
                    "changed_files": task.changed_files,
                }
                if task.test_report.get("configured"):
                    item_result_payload["test"] = task.test_report

                if task.existing_queue_item_id and orchestrator.store.get_item(
                    task.existing_queue_item_id
                ):
                    existing = orchestrator.store.get_item(task.existing_queue_item_id) or {}
                    merged_res = {**dict(existing.get("result") or {}), **item_result_payload}
                    refreshed_item = (
                        orchestrator.store.update_item(
                            task.existing_queue_item_id,
                            status="needs_review",
                            branch=task.integrated_branch
                            if has_code
                            else existing.get("branch", ""),
                            body=redact_secrets("\n".join(sections)),
                            result=merged_res,
                        )
                        or existing
                    )
                    orchestrator.store.add_event(
                        task.existing_queue_item_id,
                        "revision_ready",
                        f"Teamwork round {task.round_num} completed on {task.integrated_branch}.",
                    )
                else:
                    item = orchestrator.store.create_item(
                        {
                            "source_agent": source_label,
                            "kind": "code_change" if has_code else "task",
                            "title": f"[{proj['name']}] Team: {task.goal.splitlines()[0][:64]}",
                            "body": redact_secrets("\n".join(sections)),
                            "repo_path": task.repo_path if has_code else "",
                            "branch": task.integrated_branch if has_code else "",
                            "target_branch": task.default_branch,
                            "test_command": task.test_command if has_code else "",
                            "priority": 45 if task.gate_passed else 70,
                            "project_id": task.project_id,
                            "workflow_id": task.workflow_id,
                        }
                    )
                    orchestrator.store.update_item(item["id"], result=item_result_payload)
                    refreshed_item = orchestrator.store.get_item(item["id"]) or item

                orchestrator._on_event("queue_item_created", {"item": refreshed_item})

                if task.gate_passed:
                    orchestrator.store.record_prompt_outcome("lead_planner", passed=True)
                else:
                    reasons: List[str] = []
                    if task.merge_conflicts:
                        reasons.append("cross-agent merge conflict")
                    if not task.reality_scan.get("passed", True):
                        reasons.append("unauthorized mock/placeholder marker in diff")
                    if not task.test_report.get("passed", True):
                        reasons.append("project test_command failed")
                    if not all(r.passed for r in task.subagent_results):
                        reasons.append("sub-agent execution failure")
                    orchestrator.evolution_engine.observe_gate_failure(
                        project_id=task.project_id,
                        workflow_id=task.workflow_id,
                        failure_summary=", ".join(reasons) or "team verification gate failed",
                    )

                final_outcomes.append(
                    {
                        "queue_item_id": refreshed_item["id"],
                        "gate_passed": task.gate_passed,
                        "test_report": task.test_report,
                        "reality_scan": task.reality_scan,
                        "secret_scan": task.secret_scan,
                        "services_used": services_used,
                        "subagent_runs": [
                            {
                                "role": r.role,
                                "service": r.service,
                                "run_id": r.run_id,
                                "passed": r.passed,
                                "commit_sha": r.commit_sha,
                                "duration_s": r.duration_s,
                            }
                            for r in task.subagent_results
                        ],
                        "changed_files": task.changed_files,
                        "integrated_branch": task.integrated_branch,
                        "commit_sha": task.integrated_commit,
                        "repo_path": task.repo_path,
                        "target_branch": task.default_branch,
                        "summary_markdown": "\n".join(sections)
                        + f"\n\nPaused at Human Gate (`{refreshed_item['id']}`).",
                    }
                )
                update_graph_state(
                    "ChiefEscalationSink",
                    "waiting_gate",
                    f"Awaiting Human Gate decision on {refreshed_item['id']} ({len(task.subagent_results)} sub-agents)",
                    metrics={"queue_item_id": refreshed_item["id"], "round": task.round_num},
                )

        try:
            # Build Inner Planning SubGraph using genuine PlanAI LLMTaskWorker when LLM is active
            plan_graph = Graph(name="LeadPlanningSubGraph")
            harvester = ContextHarvesterWorker()
            active_llm = self.llm_manager.get_llm()
            if active_llm is not None:
                planner: TaskWorker = PlanAILeadPlannerLLMWorker(
                    llm=active_llm,
                    prompt="Decompose goal into disjoint multi-agent roles.",
                    system_prompt=(
                        "You are PlanAI LeadPlannerWorker. Decompose the goal into 2 to 3 "
                        "non-overlapping sub-agent assignments with disjoint file scopes."
                    ),
                )
            else:
                planner = DeterministicLeadPlannerWorker()

            plan_graph.add_workers(harvester, planner)
            plan_graph.set_dependency(harvester, planner)
            plan_graph.set_entry(harvester)
            plan_graph.set_exit(planner)

            planning_subgraph = SubGraphWorker(
                name="LeadPlanningSubGraph",
                graph=plan_graph,
                entry_worker=harvester,
                exit_worker=planner,
            )

            # Build Outer Multi-Agent Teamwork Graph
            team_graph = Graph(name="MultiAgentTeamworkGraph")
            fanout = SubtaskFanOutWorker()
            executor = MultiAgentDispatchWorker(num_consumers=3)
            joiner = TeamSynthesisJoiner()
            gate = VerificationGateWorker()
            sink = ChiefEscalationSink()

            team_graph.add_workers(planning_subgraph, fanout, executor, joiner, gate, sink)
            team_graph.set_dependency(planning_subgraph, fanout).next(executor).next(
                joiner
            ).next(gate).next(sink)

            goal_task = TeamGoalTask(
                workflow_id=wf_id,
                project_id=proj["id"],
                project_name=proj["name"],
                repo_path=proj["repo_path"],
                default_branch=proj["default_branch"],
                base_branch=base_branch or proj["default_branch"],
                test_command=proj.get("test_command") or "",
                goal=goal,
                preferred_services=preferred_services,
                session_key=session_key,
                round_num=round_num,
                max_rounds=max_rounds,
                existing_queue_item_id=existing_queue_item_id,
            )
            team_graph.run(
                initial_tasks=[(planning_subgraph, goal_task)], display_terminal=False
            )

            outcome = final_outcomes[0] if final_outcomes else {"gate_passed": False}
            with state_lock:
                result_meta.update(outcome)
                result_meta["visit_counts"] = dict(visit_counts)
                result_meta["round"] = round_num
                result_meta["max_rounds"] = max_rounds
                result_meta["current_state"] = "ChiefEscalationSink"
            for e in edges:
                e["active"] = False
            wf_final = self.store.update_workflow(
                wf_id,
                state="waiting_gate" if outcome.get("queue_item_id") else "failed",
                nodes=nodes,
                edges=edges,
                result=result_meta,
                finished_at=None if outcome.get("queue_item_id") else time.time(),
            )
            if wf_final:
                self._on_event("planai_workflow_updated", {"workflow": wf_final})

            if session_key and outcome.get("summary_markdown"):
                saved_msg = self.store.add_chat_message(
                    session_key=session_key,
                    role="assistant",
                    text=str(outcome["summary_markdown"]),
                    details={
                        "workflowId": wf_id,
                        "queueItemId": outcome.get("queue_item_id"),
                        "services": outcome.get("services_used"),
                        "subagentRuns": outcome.get("subagent_runs"),
                        "round": round_num,
                    },
                    is_error=not bool(outcome.get("gate_passed", True)),
                )
                self._on_event(
                    "webclaw_chat",
                    {
                        "runId": wf_id,
                        "sessionKey": session_key,
                        "state": "final" if outcome.get("gate_passed", True) else "error",
                        "message": saved_msg,
                    },
                )
        except Exception as exc:
            for e in edges:
                e["active"] = False
            for n in nodes:
                if n["id"] == "AbortedTerminal":
                    n["state"] = "failed"
            with state_lock:
                visit_counts["AbortedTerminal"] = (
                    int(visit_counts.get("AbortedTerminal") or 0) + 1
                )
                result_meta["error"] = str(exc)
                result_meta["visit_counts"] = dict(visit_counts)
                result_meta["current_state"] = "AbortedTerminal"
            wf_err = self.store.update_workflow(
                wf_id,
                state="failed",
                nodes=nodes,
                edges=edges,
                result=result_meta,
                finished_at=time.time(),
            )
            if wf_err:
                self._on_event("planai_workflow_updated", {"workflow": wf_err})
            if session_key:
                err_msg = self.store.add_chat_message(
                    session_key=session_key,
                    role="assistant",
                    text=f"PlanAI Teamwork Graph `{wf_id}` failed: {exc}",
                    details={"workflowId": wf_id},
                    is_error=True,
                )
                self._on_event(
                    "webclaw_chat",
                    {
                        "runId": wf_id,
                        "sessionKey": session_key,
                        "state": "error",
                        "message": err_msg,
                    },
                )
        finally:
            shutil.rmtree(self.worktrees_root / f"{wf_id}_r{round_num}", ignore_errors=True)
            shutil.rmtree(self.worktrees_root / wf_id, ignore_errors=True)

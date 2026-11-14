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

from planai import Graph, InitialTaskWorker, JoinedTaskWorker, SubGraphWorker, Task, TaskWorker
from pydantic import BaseModel, Field

from planaieditor.agent_adapters import AgentRunManager, redact_secrets
from planaieditor.evolution_engine import EvolutionEngine
from planaieditor.planai_llm_core import PlanAILLMManager
from planaieditor.queue_store import QueueStore

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
    test_command: str = ""
    goal: str
    preferred_services: List[str] = Field(default_factory=list)
    session_key: str = ""


class ProjectContextTask(Task):
    workflow_id: str
    project_id: str
    project_name: str
    repo_path: str
    default_branch: str
    test_command: str
    goal: str
    git_summary: str
    active_rules_block: str
    dispatch_services: List[str] = Field(default_factory=list)
    fitness_summary: str = ""
    session_key: str = ""


class SubtaskSpec(BaseModel):
    role: str = Field(description="Distinct specialist role name, e.g. Implementer or Verifier")
    service: str = Field(description="Assigned dispatch-ready agent service ID")
    objective: str = Field(description="Focused, concrete instructions for this sub-agent")
    owned_paths: List[str] = Field(
        default_factory=list,
        description="Disjoint files or directories owned by this sub-agent to prevent collisions",
    )


class LLMTeamPlanSchema(BaseModel):
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
    test_command: str
    goal: str
    plan_summary: str
    subtasks: List[SubtaskSpec] = Field(default_factory=list)
    planner_generation: int = 1
    session_key: str = ""


class SubAgentDirectiveTask(Task):
    workflow_id: str
    project_id: str
    repo_path: str
    default_branch: str
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


class SubAgentResultTask(Task):
    workflow_id: str
    project_id: str
    repo_path: str
    default_branch: str
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


class JoinedTeamSynthesisTask(Task):
    workflow_id: str
    project_id: str
    repo_path: str
    default_branch: str
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


class VerifiedTeamBundleTask(Task):
    workflow_id: str
    project_id: str
    repo_path: str
    default_branch: str
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


TEAMWORK_GRAPH_PYTHON_SOURCE = """from planai import Graph, InitialTaskWorker, JoinedTaskWorker, SubGraphWorker, Task, TaskWorker

# Inner Planning SubGraph
plan_graph = Graph(name="LeadPlanningSubGraph")
harvester = ContextHarvesterWorker()
planner = LeadPlannerWorker()
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
joiner = TeamSynthesisJoiner()  # JoinedTaskWorker(join_type=SubtaskFanOutWorker)
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
            "worker_type": "TaskWorker",
            "svelte_type": "taskworker",
            "role": "Submits verified bundle to Chief Queue & feeds EvolutionEngine",
            "state": "idle",
            "position": {"x": 1550, "y": 150},
            "metrics": {},
        },
    ]


def _default_teamwork_edges() -> List[Dict[str, Any]]:
    return [
        {
            "id": "e_ctx_plan",
            "source": "ContextHarvesterWorker",
            "target": "LeadPlannerWorker",
            "task_type": "ProjectContextTask",
            "active": False,
        },
        {
            "id": "e_plan_fanout",
            "source": "LeadPlannerWorker",
            "target": "SubtaskFanOutWorker",
            "task_type": "TeamPlanTask",
            "active": False,
        },
        {
            "id": "e_fanout_exec",
            "source": "SubtaskFanOutWorker",
            "target": "MultiAgentDispatchWorker",
            "task_type": "SubAgentDirectiveTask",
            "active": False,
        },
        {
            "id": "e_exec_join",
            "source": "MultiAgentDispatchWorker",
            "target": "TeamSynthesisJoiner",
            "task_type": "SubAgentResultTask",
            "active": False,
        },
        {
            "id": "e_join_gate",
            "source": "TeamSynthesisJoiner",
            "target": "VerificationGateWorker",
            "task_type": "JoinedTeamSynthesisTask",
            "active": False,
        },
        {
            "id": "e_gate_sink",
            "source": "VerificationGateWorker",
            "target": "ChiefEscalationSink",
            "task_type": "VerifiedTeamBundleTask",
            "active": False,
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
            },
            daemon=True,
            name=f"planai-team-{wf_id}",
        )
        thread.start()
        return wf

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
    ) -> None:
        events: List[Dict[str, Any]] = []
        provenance_log: List[Dict[str, Any]] = []
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
        ) -> None:
            with state_lock:
                for n in nodes:
                    if n["id"] == node_id:
                        n["state"] = new_state
                        if metrics:
                            n["metrics"] = {**n.get("metrics", {}), **metrics}
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
                wf_row = orchestrator.store.update_workflow(
                    wf_id,
                    nodes=nodes,
                    edges=edges,
                    events=events,
                    provenance=provenance_log,
                )
            if wf_row:
                orchestrator._on_event("planai_workflow_updated", {"workflow": wf_row})

        class ContextHarvesterWorker(TaskWorker):
            output_types: List[Type[Task]] = [ProjectContextTask]

            def consume_work(self, task: TeamGoalTask) -> None:
                update_graph_state(
                    "ContextHarvesterWorker",
                    "running",
                    f"Inspecting project '{task.project_name}' at {task.repo_path}",
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
                    git_summary = f"Branch: {task.default_branch} | Top entries: {', '.join(top_files)} | Recent commits: {recent}"

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
                    test_command=task.test_command,
                    goal=task.goal,
                    git_summary=git_summary,
                    active_rules_block=rules_block,
                    dispatch_services=ready_services,
                    fitness_summary=fitness_summary,
                    session_key=task.session_key,
                )
                self.publish_work(ctx_task, input_task=task)
                update_graph_state(
                    "ContextHarvesterWorker",
                    "succeeded",
                    f"Ready services: {', '.join(ready_services) or 'none'}",
                    edge_id="e_ctx_plan",
                    metrics={"dispatch_services": ready_services},
                )

        class LeadPlannerWorker(TaskWorker):
            output_types: List[Type[Task]] = [TeamPlanTask]

            def consume_work(self, task: ProjectContextTask) -> None:
                update_graph_state(
                    "LeadPlannerWorker",
                    "running",
                    "Decomposing goal into parallel sub-agent assignments",
                    edge_id="e_ctx_plan",
                )
                if not task.dispatch_services:
                    raise PermissionError(
                        "No dispatch-ready agent services available to execute multi-agent teamwork."
                    )

                pv = orchestrator.store.get_active_prompt("lead_planner")
                gen = int(pv["generation"]) if pv else 1
                template = (
                    str(pv["prompt_template"])
                    if pv
                    else "Decompose goal '{goal}' for {project_name}"
                )
                rendered_prompt = (
                    template.replace("{project_name}", task.project_name)
                    .replace("{repo_path}", task.repo_path)
                    .replace("{active_rules_block}", task.active_rules_block)
                    .replace("{services_fitness_block}", task.fitness_summary)
                    .replace("{goal}", task.goal)
                    .replace("{git_context}", task.git_summary)
                )

                subtasks: List[SubtaskSpec] = []
                plan_summary = ""
                llm = orchestrator.llm_manager.get_llm()
                if llm is not None:
                    try:
                        parsed = llm.generate_pydantic(
                            prompt_template="{query}",
                            output_schema=LLMTeamPlanSchema,
                            system=(
                                "You are PlanAI LeadPlannerWorker. Decompose the goal into exactly 2 "
                                "non-overlapping sub-agent assignments using ONLY services from: "
                                + ", ".join(task.dispatch_services)
                            ),
                            query=rendered_prompt,
                        )
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
                    except Exception:
                        subtasks = []

                if len(subtasks) < 2:
                    svc_primary = task.dispatch_services[0]
                    svc_secondary = task.dispatch_services[
                        1 % len(task.dispatch_services)
                    ]
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

                plan_task = TeamPlanTask(
                    workflow_id=task.workflow_id,
                    project_id=task.project_id,
                    project_name=task.project_name,
                    repo_path=task.repo_path,
                    default_branch=task.default_branch,
                    test_command=task.test_command,
                    goal=task.goal,
                    plan_summary=plan_summary,
                    subtasks=subtasks,
                    planner_generation=gen,
                    session_key=task.session_key,
                )
                self.publish_work(plan_task, input_task=task)
                update_graph_state(
                    "LeadPlannerWorker",
                    "succeeded",
                    f"Planned {len(subtasks)} sub-agent roles (Gen v{gen}): "
                    + ", ".join(f"{s.role}→{s.service}" for s in subtasks),
                    edge_id="e_plan_fanout",
                    metrics={
                        "planner_generation": gen,
                        "subtasks_count": len(subtasks),
                        "assignments": [
                            {"role": s.role, "service": s.service} for s in subtasks
                        ],
                    },
                )

        class SubtaskFanOutWorker(TaskWorker):
            output_types: List[Type[Task]] = [SubAgentDirectiveTask]

            def consume_work(self, task: TeamPlanTask) -> None:
                update_graph_state(
                    "SubtaskFanOutWorker",
                    "running",
                    f"Fanning out {len(task.subtasks)} parallel SubAgentDirectiveTasks",
                    edge_id="e_plan_fanout",
                )
                total = len(task.subtasks)
                for idx, spec in enumerate(task.subtasks):
                    directive = SubAgentDirectiveTask(
                        workflow_id=task.workflow_id,
                        project_id=task.project_id,
                        repo_path=task.repo_path,
                        default_branch=task.default_branch,
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
                update_graph_state(
                    "MultiAgentDispatchWorker",
                    "running",
                    f"Running [{task.subtask_index}/{task.total_subtasks}] {task.role} on {task.service}",
                    edge_id="e_fanout_exec",
                )
                repo_path = Path(task.repo_path).resolve()
                wt_dir, branch_name, is_git_wt = orchestrator._prepare_subagent_worktree(
                    repo_path,
                    task.default_branch,
                    task.workflow_id,
                    task.subtask_index,
                    task.service,
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
                    f"[Teamwork Role: {task.role} ({task.subtask_index}/{task.total_subtasks})]\n"
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
                        "metadata": {"teamwork": True, "subtask_index": task.subtask_index},
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
                            f"feat({task.service}): {task.role} for {task.workflow_id}",
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
                    },
                    finished_at=time.time(),
                )
                orchestrator._on_event("run_updated", {"run": updated_run})

                prov = [str(p) for p in getattr(task, "_provenance", [])]
                out_task = SubAgentResultTask(
                    workflow_id=task.workflow_id,
                    project_id=task.project_id,
                    repo_path=task.repo_path,
                    default_branch=task.default_branch,
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
                )
                first = tasks[0]
                repo_path = Path(first.repo_path).resolve()
                committed_tasks = [t for t in tasks if t.commit_sha and t.branch]
                integrated_branch = ""
                integrated_commit = ""
                integrated_wt = ""
                merge_conflicts: List[str] = []
                all_changed: List[str] = []

                if committed_tasks and (repo_path / ".git").exists():
                    wt_int = (orchestrator.worktrees_root / first.workflow_id / "integrated").resolve()
                    wt_int.parent.mkdir(parents=True, exist_ok=True)
                    integrated_branch = f"team/{first.workflow_id[-8:]}/integrated"
                    ref_check = orchestrator._git(
                        repo_path, "rev-parse", "--verify", first.default_branch
                    )
                    start_ref = first.default_branch if ref_check.returncode == 0 else "HEAD"
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
                        integrated_commit = orchestrator._git(
                            wt_int, "rev-parse", "HEAD"
                        ).stdout.strip()

                prov = [str(p) for p in getattr(first, "_provenance", [])]
                joined_task = JoinedTeamSynthesisTask(
                    workflow_id=first.workflow_id,
                    project_id=first.project_id,
                    repo_path=first.repo_path,
                    default_branch=first.default_branch,
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

                reality_scan, secret_scan = orchestrator._reality_and_secret_scan(diff_text)
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
                    "Creating project-scoped Chief ReviewItem & recording Evolution telemetry",
                    edge_id="e_gate_sink",
                )
                services_used = sorted({r.service for r in task.subagent_results})
                source_label = "team:" + "+".join(services_used)
                sections = [
                    f"### PlanAI Multi-Agent Teamwork Summary (`{task.workflow_id}`)",
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
                item = orchestrator.store.create_item(
                    {
                        "source_agent": source_label,
                        "kind": "code_change" if has_code else "task",
                        "title": f"[{proj['name']}] Team: {task.goal[:64]}",
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
                orchestrator.store.update_item(
                    item["id"],
                    result={
                        "workflow_id": task.workflow_id,
                        "subagent_runs": [r.run_id for r in task.subagent_results],
                        "reality_scan": task.reality_scan,
                        "secret_scan": task.secret_scan,
                        "gate_test": task.test_report,
                        "changed_files": task.changed_files,
                    },
                )
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
                        "summary_markdown": "\n".join(sections)
                        + f"\n\nQueued for Chief review as `{refreshed_item['id']}`.",
                    }
                )
                update_graph_state(
                    "ChiefEscalationSink",
                    "succeeded",
                    f"Queued ReviewItem {refreshed_item['id']} ({len(task.subagent_results)} sub-agents)",
                    metrics={"queue_item_id": refreshed_item["id"]},
                )

        try:
            # Build Inner Planning SubGraph
            plan_graph = Graph(name="LeadPlanningSubGraph")
            harvester = ContextHarvesterWorker()
            planner = LeadPlannerWorker()
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
                test_command=proj.get("test_command") or "",
                goal=goal,
                preferred_services=preferred_services,
                session_key=session_key,
            )
            team_graph.run(
                initial_tasks=[(planning_subgraph, goal_task)], display_terminal=False
            )

            outcome = final_outcomes[0] if final_outcomes else {"gate_passed": False}
            for e in edges:
                e["active"] = False
            wf_final = self.store.update_workflow(
                wf_id,
                state="succeeded" if outcome.get("gate_passed", True) else "failed",
                nodes=nodes,
                edges=edges,
                result=outcome,
                finished_at=time.time(),
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
            wf_err = self.store.update_workflow(
                wf_id,
                state="failed",
                nodes=nodes,
                edges=edges,
                result={"error": str(exc)},
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
            shutil.rmtree(self.worktrees_root / wf_id, ignore_errors=True)

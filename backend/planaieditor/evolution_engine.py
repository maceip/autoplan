"""PlanAI Bootstrap & Continuous Evolution Engine.

Bootstraps standing rules from real operator transcript breakdown telemetry
(`~/.autoplan/brain/breakdown_trends.json` when present on host) and live
`QueueStore` decisions/runs, then continuously evolves `LeadPlanner` and
`ChiefTriage` prompts + project rules using a real multi-worker `planai.Graph`
(`TraceCollectorWorker` -> `FailureCritiqueWorker` -> `EvolutionCritiqueJoiner`
[`JoinedTaskWorker`] -> `PromptMutationWorker` -> `EvolutionCommitSink`).
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

from planai import Graph, InitialTaskWorker, JoinedTaskWorker, Task, TaskWorker
from pydantic import BaseModel, Field

from planaieditor.planai_llm_core import PlanAILLMManager
from planaieditor.queue_store import QueueStore

DEFAULT_LEAD_PLANNER_PROMPT = """You are the Lead Architect & Multi-Agent Planner for project '{project_name}' ({repo_path}).
Decompose the operator goal into 2 to 3 concrete, non-overlapping sub-agent assignments with isolated scopes so parallel agents never clobber the same files.

Mandatory Engineering & Operator Guardrails:
{active_rules_block}

Available Dispatch-Ready Agent Services (ordered by empirical fitness):
{services_fitness_block}

Goal to decompose:
{goal}

Project Git Context:
{git_context}
"""

DEFAULT_CHIEF_TRIAGE_PROMPT = """You are the Chief of Staff triaging incoming work for one human operator.
Score priority from 0 (low urgency idea) to 100 (critical blocker).
Provide a concise 1-2 sentence recommendation explaining exact impact and verification status.

Active Operator Brain Rules:
{active_rules_block}
"""

_CORPUS_CATEGORY_RULES: Dict[str, tuple[str, str]] = {
    "E3_stall_looping": (
        "anti_loop",
        "Never retry the identical failing command or approach more than twice; inspect root cause or escalate with concrete diagnostics.",
    ),
    "E4_stall_collision": (
        "workspace_isolation",
        "Assign disjoint file paths and isolated git worktrees per sub-agent so concurrent agents never clobber each other's edits.",
    ),
    "F_scope_order_violation": (
        "scope_discipline",
        "Execute requested tasks in exact specified scope without unrequested refactors or silent scope reductions.",
    ),
    "D_false_completion": (
        "verified_completion",
        "Never claim completion without running the project's real test command and verifying actual outputs.",
    ),
    "C_correct_info_defied": (
        "constitutional_compliance",
        "Never introduce fake, mocked, placeholder, or fallback data without a verbatim operator authorization comment.",
    ),
    "G_destructive_unilateral": (
        "git_safety",
        "Never run destructive git history rewrites or delete uncommitted work; commit on isolated branches and merge only via Chief gate.",
    ),
}


# ---- PlanAI Typed Tasks for the Evolution Graph -------------------------


class EvolutionSeedTask(Task):
    workflow_id: str
    project_id: str = "*"
    reason: str = "manual"


class RoleEvolutionInputTask(Task):
    workflow_id: str
    project_id: str
    worker_role: str
    current_generation: int
    current_prompt: str
    recent_failures: List[str] = Field(default_factory=list)
    operator_corrections: List[str] = Field(default_factory=list)
    active_rules: List[str] = Field(default_factory=list)
    service_fitness_summary: str = ""


class RoleCritiqueOutputTask(Task):
    workflow_id: str
    project_id: str
    worker_role: str
    current_generation: int
    current_prompt: str
    weaknesses: List[str] = Field(default_factory=list)
    proposed_rule: str = ""
    improved_prompt: str = ""
    rationale: str = ""


class JoinedEvolutionBundleTask(Task):
    workflow_id: str
    project_id: str
    critiques: List[RoleCritiqueOutputTask] = Field(default_factory=list)


class EvolvedGenerationResultTask(Task):
    workflow_id: str
    project_id: str
    updated_prompts: List[Dict[str, Any]] = Field(default_factory=list)
    added_rules: List[Dict[str, Any]] = Field(default_factory=list)


class LLMCritiqueAndMutateSchema(BaseModel):
    weaknesses: List[str] = Field(
        default_factory=list,
        description="Concrete prompt weaknesses observed from recent operator bounce notes or failed runs",
    )
    proposed_rule: str = Field(
        default="",
        description="One concise standing guardrail distilled from the observed corrections/failures",
    )
    improved_directives: List[str] = Field(
        default_factory=list,
        description="1 to 3 concrete bullet directives to append/integrate into the worker prompt template",
    )
    rationale: str = Field(
        default="",
        description="One-sentence explanation of how this prompt evolution addresses observed failures",
    )


EVOLUTION_GRAPH_PYTHON_SOURCE = """from planai import Graph, InitialTaskWorker, JoinedTaskWorker, Task, TaskWorker

# AutoPlan Continuous Prompt & Rule Evolution Graph (PlanAI)
graph = Graph(name="AutoplanPromptEvolutionGraph")
collector = TraceCollectorWorker()
critic = FailureCritiqueWorker()
joiner = EvolutionCritiqueJoiner()
committer = EvolutionCommitSink()

graph.add_workers(collector, critic, joiner, committer)
graph.set_dependency(collector, critic).next(joiner).next(committer)
"""


def _default_evolution_nodes() -> List[Dict[str, Any]]:
    return [
        {
            "id": "TraceCollectorWorker",
            "label": "TraceCollectorWorker",
            "worker_type": "TaskWorker",
            "svelte_type": "taskworker",
            "role": "Harvests operator decisions, bounce notes, failed runs & service fitness",
            "state": "idle",
            "position": {"x": 60, "y": 140},
            "metrics": {},
        },
        {
            "id": "FailureCritiqueWorker",
            "label": "FailureCritiqueWorker",
            "worker_type": "LLMTaskWorker",
            "svelte_type": "llmtaskworker",
            "role": "Critiques active LeadPlanner & ChiefTriage prompts against empirical traces",
            "state": "idle",
            "position": {"x": 360, "y": 140},
            "metrics": {},
        },
        {
            "id": "EvolutionCritiqueJoiner",
            "label": "EvolutionCritiqueJoiner",
            "worker_type": "JoinedTaskWorker",
            "svelte_type": "joinedtaskworker",
            "role": "Joins parallel role critiques via PlanAI ProvenanceChain",
            "state": "idle",
            "position": {"x": 670, "y": 140},
            "metrics": {},
        },
        {
            "id": "EvolutionCommitSink",
            "label": "EvolutionCommitSink",
            "worker_type": "TaskWorker",
            "svelte_type": "taskworker",
            "role": "Persists Generation N+1 prompt versions and distilled evolution rules",
            "state": "idle",
            "position": {"x": 970, "y": 140},
            "metrics": {},
        },
    ]


def _default_evolution_edges() -> List[Dict[str, Any]]:
    return [
        {
            "id": "e_collect_critique",
            "source": "TraceCollectorWorker",
            "target": "FailureCritiqueWorker",
            "task_type": "RoleEvolutionInputTask",
            "active": False,
        },
        {
            "id": "e_critique_join",
            "source": "FailureCritiqueWorker",
            "target": "EvolutionCritiqueJoiner",
            "task_type": "RoleCritiqueOutputTask",
            "active": False,
        },
        {
            "id": "e_join_commit",
            "source": "EvolutionCritiqueJoiner",
            "target": "EvolutionCommitSink",
            "task_type": "JoinedEvolutionBundleTask",
            "active": False,
        },
    ]


class EvolutionEngine:
    """Bootstraps and continuously evolves prompts, rules, and routing weights on PlanAI."""

    def __init__(
        self,
        store: QueueStore,
        llm_manager: PlanAILLMManager,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        corpus_trends_path: Optional[Path] = None,
        enable_host_corpus: bool = True,
    ) -> None:
        self.store = store
        self.llm_manager = llm_manager
        self._on_event = on_event or (lambda _t, _p: None)
        self._lock = threading.Lock()
        default_corpus = Path.home() / ".autoplan" / "brain" / "breakdown_trends.json"
        self.corpus_trends_path = (
            corpus_trends_path
            if corpus_trends_path is not None
            else (default_corpus if enable_host_corpus else None)
        )
        self.bootstrap_summary = self.bootstrap()

    def bootstrap(self) -> Dict[str, Any]:
        """Seed Generation 1 prompts and ingest real breakdown_trends.json + historical decisions."""
        if not self.store.get_active_prompt("lead_planner"):
            self.store.create_prompt_version(
                worker_role="lead_planner",
                prompt_template=DEFAULT_LEAD_PLANNER_PROMPT,
                rationale="Bootstrap Generation 1 LeadPlanner multi-agent decomposition template.",
            )
        if not self.store.get_active_prompt("chief_triage"):
            self.store.create_prompt_version(
                worker_role="chief_triage",
                prompt_template=DEFAULT_CHIEF_TRIAGE_PROMPT,
                rationale="Bootstrap Generation 1 ChiefOfStaff triage template.",
            )

        corpus_loaded = False
        corpus_total_prompts = 0
        corpus_total_sessions = 0
        seeded_rules = 0

        if self.corpus_trends_path and self.corpus_trends_path.is_file():
            try:
                trends = json.loads(self.corpus_trends_path.read_text(encoding="utf-8"))
                corpus_loaded = True
                corpus_total_prompts = int(trends.get("total_prompts") or 0)
                corpus_total_sessions = int(trends.get("total_sessions") or 0)
                categories = trends.get("categories") or {}
                for cat_key, (rule_cat, rule_text) in _CORPUS_CATEGORY_RULES.items():
                    cat_data = categories.get(cat_key)
                    if isinstance(cat_data, dict) and int(cat_data.get("prompts") or 0) > 0:
                        self.store.upsert_evolution_rule(
                            category=rule_cat,
                            rule_text=rule_text,
                            source_type="operator_corpus_bootstrap",
                            source_ref=f"breakdown_trends:{cat_key}",
                            project_id="*",
                            evidence_count=int(cat_data["prompts"]),
                        )
                        seeded_rules += 1
            except Exception:
                corpus_loaded = False

        # Also ingest any existing operator request_changes / reject notes in QueueStore
        for dec in self.store.list_decisions(limit=100):
            if dec["action"] in ("request_changes", "reject") and str(dec.get("note") or "").strip():
                item = self.store.get_item(dec["item_id"])
                proj_id = (item.get("project_id") if item else "") or "*"
                self.store.upsert_evolution_rule(
                    category="operator_feedback",
                    rule_text=f"Operator correction ({dec['action']}): {str(dec['note']).strip()[:240]}",
                    source_type="operator_decision",
                    source_ref=dec["id"],
                    project_id=proj_id,
                    evidence_count=1,
                )

        return {
            "corpus_loaded": corpus_loaded,
            "corpus_path": str(self.corpus_trends_path) if corpus_loaded else "",
            "corpus_total_prompts": corpus_total_prompts,
            "corpus_total_sessions": corpus_total_sessions,
            "seeded_corpus_rules": seeded_rules,
        }

    def format_rules_block(self, project_id: str = "*", limit: int = 8) -> str:
        rules = self.store.list_evolution_rules(project_id=project_id, active_only=True)[:limit]
        if not rules:
            return "- Verify all changes with real tests and isolated branches."
        return "\n".join(
            f"- [{r['category']} · evidence={r['evidence_count']}] {r['rule_text']}"
            for r in rules
        )

    def observe_decision(self, item: Dict[str, Any], decision: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        action = str(decision.get("action") or "")
        note = str(decision.get("note") or "").strip()
        project_id = str(item.get("project_id") or "*") or "*"
        if action == "approve":
            self.store.record_prompt_outcome("lead_planner", passed=True)
            self.store.record_prompt_outcome("chief_triage", passed=True)
            return None
        if action in ("request_changes", "reject"):
            self.store.record_prompt_outcome("lead_planner", passed=False)
            self.store.record_prompt_outcome("chief_triage", passed=False)
            if note:
                rule = self.store.upsert_evolution_rule(
                    category="operator_feedback",
                    rule_text=f"Operator feedback ({action}): {note[:240]}",
                    source_type="operator_decision",
                    source_ref=str(decision.get("id") or ""),
                    project_id=project_id,
                )
                self._on_event("evolution_rule_learned", {"rule": rule, "item_id": item["id"]})
                return rule
        return None

    def observe_gate_failure(
        self, project_id: str, workflow_id: str, failure_summary: str
    ) -> Dict[str, Any]:
        self.store.record_prompt_outcome("lead_planner", passed=False)
        rule = self.store.upsert_evolution_rule(
            category="verification_gate",
            rule_text=f"Avoid repeat verification failure: {failure_summary.strip()[:240]}",
            source_type="gate_failure",
            source_ref=workflow_id,
            project_id=project_id or "*",
        )
        self._on_event("evolution_rule_learned", {"rule": rule, "workflow_id": workflow_id})
        return rule

    def status(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        lead_pv = self.store.get_active_prompt("lead_planner")
        chief_pv = self.store.get_active_prompt("chief_triage")
        rules = self.store.list_evolution_rules(project_id=project_id, active_only=True)
        fitness = self.store.compute_service_fitness(project_id=project_id)
        evo_workflows = self.store.list_workflows(graph_type="evolution", limit=10)
        return {
            "bootstrap": self.bootstrap_summary,
            "active_generation": int(lead_pv["generation"]) if lead_pv else 1,
            "active_prompts": {
                "lead_planner": lead_pv,
                "chief_triage": chief_pv,
            },
            "prompt_history": self.store.list_prompt_versions(limit=20),
            "rules": rules,
            "rules_count": len(rules),
            "service_fitness": fitness,
            "recent_evolution_workflows": evo_workflows,
        }

    def run_evolution_cycle(
        self, project_id: str = "*", reason: str = "manual"
    ) -> Dict[str, Any]:
        """Execute a real PlanAI Graph (`TraceCollector` -> `FailureCritique` -> `JoinedTaskWorker` -> `Commit`)."""
        wf_id = f"wf_evo_{uuid.uuid4().hex[:8]}"
        lead_pv = self.store.get_active_prompt("lead_planner")
        cur_gen = int(lead_pv["generation"]) if lead_pv else 1
        nodes = _default_evolution_nodes()
        edges = _default_evolution_edges()
        events: List[Dict[str, Any]] = []
        provenance_log: List[Dict[str, Any]] = []

        wf = self.store.create_workflow(
            {
                "id": wf_id,
                "project_id": "" if project_id == "*" else project_id,
                "graph_type": "evolution",
                "title": f"Prompt & Rule Evolution Cycle (Gen v{cur_gen} → v{cur_gen + 1})",
                "goal": f"Evolve LeadPlanner & ChiefTriage prompts from empirical traces (trigger: {reason})",
                "state": "running",
                "nodes": nodes,
                "edges": edges,
                "events": events,
                "provenance": provenance_log,
                "python_code": EVOLUTION_GRAPH_PYTHON_SOURCE,
                "evolution_gen": cur_gen,
            }
        )
        self._on_event("planai_workflow_updated", {"workflow": wf})

        state_lock = threading.Lock()

        def mark_node(
            node_id: str,
            new_state: str,
            detail: str = "",
            edge_id: str = "",
            metrics: Optional[Dict[str, Any]] = None,
            prov_chain: Optional[List[str]] = None,
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
                if prov_chain:
                    provenance_log.append(
                        {"ts": time.time(), "node_id": node_id, "chain": prov_chain}
                    )
                updated = self.store.update_workflow(
                    wf_id,
                    nodes=nodes,
                    edges=edges,
                    events=events,
                    provenance=provenance_log,
                )
            if updated:
                self._on_event("planai_workflow_updated", {"workflow": updated})

        engine = self
        committed_results: List[EvolvedGenerationResultTask] = []

        class TraceCollectorWorker(TaskWorker):
            output_types: List[Type[Task]] = [RoleEvolutionInputTask]

            def consume_work(self, task: EvolutionSeedTask) -> None:
                mark_node(
                    "TraceCollectorWorker",
                    "running",
                    "Collecting failed runs, operator decisions, and service fitness",
                )
                proj_filter = None if task.project_id in ("", "*") else task.project_id
                failed_runs = engine.store.list_runs(
                    state="failed", project_id=proj_filter, limit=10
                )
                failure_texts = [
                    f"[{r['service']}] {(r.get('stderr_tail') or r.get('response_text') or '')[:180]}"
                    for r in failed_runs
                    if (r.get("stderr_tail") or r.get("response_text"))
                ]
                decisions = engine.store.list_decisions(limit=25)
                corrections = [
                    f"{d['action']}: {d['note']}"
                    for d in decisions
                    if d["action"] in ("request_changes", "reject") and str(d.get("note") or "").strip()
                ]
                rules = [
                    r["rule_text"]
                    for r in engine.store.list_evolution_rules(
                        project_id=task.project_id, active_only=True
                    )[:10]
                ]
                fitness = engine.store.compute_service_fitness(project_id=proj_filter)
                fitness_str = ", ".join(
                    f"{f['service']}: {f['succeeded_runs']}/{f['total_runs']} pass"
                    for f in fitness
                ) or "no runs recorded yet"

                published = 0
                for role in ("lead_planner", "chief_triage"):
                    pv = engine.store.get_active_prompt(role)
                    if not pv:
                        continue
                    published += 1
                    self.publish_work(
                        RoleEvolutionInputTask(
                            workflow_id=task.workflow_id,
                            project_id=task.project_id,
                            worker_role=role,
                            current_generation=int(pv["generation"]),
                            current_prompt=str(pv["prompt_template"]),
                            recent_failures=failure_texts[:5],
                            operator_corrections=corrections[:5],
                            active_rules=rules,
                            service_fitness_summary=fitness_str,
                        ),
                        input_task=task,
                    )
                mark_node(
                    "TraceCollectorWorker",
                    "succeeded",
                    f"Published {published} role evolution tasks ({len(corrections)} corrections, {len(failure_texts)} failures)",
                    edge_id="e_collect_critique",
                    metrics={
                        "roles_fanned_out": published,
                        "corrections_found": len(corrections),
                        "failed_runs_found": len(failure_texts),
                    },
                )

        class FailureCritiqueWorker(TaskWorker):
            output_types: List[Type[Task]] = [RoleCritiqueOutputTask]

            def consume_work(self, task: RoleEvolutionInputTask) -> None:
                mark_node(
                    "FailureCritiqueWorker",
                    "running",
                    f"Critiquing & evolving '{task.worker_role}' (Gen v{task.current_generation})",
                    edge_id="e_collect_critique",
                )
                llm = engine.llm_manager.get_llm()
                weaknesses: List[str] = []
                proposed_rule = ""
                directives: List[str] = []
                rationale = ""

                if llm is not None:
                    try:
                        critique_prompt = (
                            f"Analyze worker role '{task.worker_role}' (Generation {task.current_generation}).\n"
                            f"Current prompt template:\n{task.current_prompt}\n\n"
                            f"Recent operator corrections: {task.operator_corrections or ['none']}\n"
                            f"Recent failed runs: {task.recent_failures or ['none']}\n"
                            f"Empirical service fitness: {task.service_fitness_summary}\n"
                            f"Existing rules: {task.active_rules[:5]}\n\n"
                            "Identify concrete prompt weaknesses, propose 1 concise guardrail rule if warranted, "
                            "and provide 1-2 crisp bullet directives to strengthen the prompt without removing placeholders."
                        )
                        parsed = llm.generate_pydantic(
                            prompt_template="{query}",
                            output_schema=LLMCritiqueAndMutateSchema,
                            system="You are PlanAI's evolutionary prompt optimizer. Be concise, empirical, and specific.",
                            query=critique_prompt,
                        )
                        weaknesses = [w.strip() for w in parsed.weaknesses if w.strip()]
                        proposed_rule = parsed.proposed_rule.strip()
                        directives = [d.strip() for d in parsed.improved_directives if d.strip()]
                        rationale = parsed.rationale.strip()
                    except Exception as llm_exc:
                        rationale = f"Empirical trace synthesis (LLM critique skipped: {llm_exc})"

                if not directives:
                    if task.operator_corrections:
                        directives.append(
                            f"Enforce recent operator feedback: {task.operator_corrections[0][:160]}"
                        )
                    if task.recent_failures:
                        directives.append(
                            f"Pre-check against observed run failure: {task.recent_failures[0][:160]}"
                        )
                    if not directives:
                        directives.append(
                            f"Route subtasks preferentially by measured service fitness ({task.service_fitness_summary}) and require clean worktree verification."
                        )
                if not rationale:
                    rationale = (
                        f"Distilled {len(task.operator_corrections)} operator corrections and "
                        f"{len(task.recent_failures)} run failure traces into Generation v{task.current_generation + 1}."
                    )

                marker = "\n# Evolved Directives"
                base_prompt = task.current_prompt.split(marker)[0].rstrip()
                bullet_block = "\n".join(f"- {d.lstrip('- ').strip()}" for d in directives[:3])
                improved_prompt = (
                    f"{base_prompt}{marker} (Gen v{task.current_generation + 1}):\n{bullet_block}\n"
                )

                prov_chain = [str(p) for p in getattr(task, "_provenance", [])]
                out_task = RoleCritiqueOutputTask(
                    workflow_id=task.workflow_id,
                    project_id=task.project_id,
                    worker_role=task.worker_role,
                    current_generation=task.current_generation,
                    current_prompt=task.current_prompt,
                    weaknesses=weaknesses,
                    proposed_rule=proposed_rule,
                    improved_prompt=improved_prompt,
                    rationale=rationale,
                )
                self.publish_work(out_task, input_task=task)
                mark_node(
                    "FailureCritiqueWorker",
                    "succeeded",
                    f"Prepared Gen v{task.current_generation + 1} candidate for '{task.worker_role}'",
                    edge_id="e_critique_join",
                    prov_chain=prov_chain,
                )

        class EvolutionCritiqueJoiner(JoinedTaskWorker):
            output_types: List[Type[Task]] = [JoinedEvolutionBundleTask]
            join_type: Type[TaskWorker] = InitialTaskWorker

            def consume_work_joined(self, tasks: List[RoleCritiqueOutputTask]) -> None:
                mark_node(
                    "EvolutionCritiqueJoiner",
                    "running",
                    f"Joined {len(tasks)} role critiques via PlanAI ProvenanceChain",
                    edge_id="e_critique_join",
                )
                prov_chain = [str(p) for p in getattr(tasks[0], "_provenance", [])] if tasks else []
                bundle = JoinedEvolutionBundleTask(
                    workflow_id=tasks[0].workflow_id if tasks else wf_id,
                    project_id=tasks[0].project_id if tasks else project_id,
                    critiques=tasks,
                )
                self.publish_work(bundle, input_task=tasks[0])
                mark_node(
                    "EvolutionCritiqueJoiner",
                    "succeeded",
                    f"Synchronized {len(tasks)} evolved role specs",
                    edge_id="e_join_commit",
                    metrics={"joined_critiques": len(tasks)},
                    prov_chain=prov_chain,
                )

        class EvolutionCommitSink(TaskWorker):
            output_types: List[Type[Task]] = []

            def consume_work(self, task: JoinedEvolutionBundleTask) -> None:
                mark_node(
                    "EvolutionCommitSink",
                    "running",
                    "Committing evolved prompt versions and learned rules to SQLite store",
                    edge_id="e_join_commit",
                )
                saved_prompts: List[Dict[str, Any]] = []
                saved_rules: List[Dict[str, Any]] = []
                for crit in task.critiques:
                    pv = engine.store.create_prompt_version(
                        worker_role=crit.worker_role,
                        prompt_template=crit.improved_prompt,
                        rationale=crit.rationale,
                        source_workflow_id=wf_id,
                        activate=True,
                    )
                    saved_prompts.append(pv)
                    if crit.proposed_rule and len(crit.proposed_rule) >= 12:
                        rule = engine.store.upsert_evolution_rule(
                            category="evolved_guardrail",
                            rule_text=crit.proposed_rule[:240],
                            source_type="planai_evolution_graph",
                            source_ref=wf_id,
                            project_id=task.project_id or "*",
                        )
                        saved_rules.append(rule)

                res_task = EvolvedGenerationResultTask(
                    workflow_id=wf_id,
                    project_id=task.project_id,
                    updated_prompts=saved_prompts,
                    added_rules=saved_rules,
                )
                committed_results.append(res_task)
                new_gen = (
                    max(int(p["generation"]) for p in saved_prompts)
                    if saved_prompts
                    else cur_gen + 1
                )
                mark_node(
                    "EvolutionCommitSink",
                    "succeeded",
                    f"Activated Generation v{new_gen} ({len(saved_prompts)} prompts, {len(saved_rules)} new rules)",
                    metrics={
                        "new_generation": new_gen,
                        "prompts_updated": len(saved_prompts),
                        "rules_added": len(saved_rules),
                    },
                )

        try:
            graph = Graph(name="AutoplanPromptEvolutionGraph")
            collector = TraceCollectorWorker()
            critic = FailureCritiqueWorker()
            joiner = EvolutionCritiqueJoiner()
            committer = EvolutionCommitSink()
            graph.add_workers(collector, critic, joiner, committer)
            graph.set_dependency(collector, critic).next(joiner).next(committer)

            seed = EvolutionSeedTask(
                workflow_id=wf_id, project_id=project_id or "*", reason=reason
            )
            graph.run(initial_tasks=[(collector, seed)], display_terminal=False)

            final_prompts = committed_results[0].updated_prompts if committed_results else []
            final_rules = committed_results[0].added_rules if committed_results else []
            final_gen = (
                max(int(p["generation"]) for p in final_prompts)
                if final_prompts
                else cur_gen
            )
            for e in edges:
                e["active"] = False
            finished_wf = self.store.update_workflow(
                wf_id,
                state="succeeded",
                nodes=nodes,
                edges=edges,
                evolution_gen=final_gen,
                result={
                    "new_generation": final_gen,
                    "updated_prompts": [
                        {
                            "id": p["id"],
                            "worker_role": p["worker_role"],
                            "generation": p["generation"],
                            "rationale": p["rationale"],
                        }
                        for p in final_prompts
                    ],
                    "added_rules": final_rules,
                    "llm_provider_used": self.llm_manager.last_provider_used,
                },
                finished_at=time.time(),
            )
            if finished_wf:
                self._on_event("planai_workflow_updated", {"workflow": finished_wf})
            return {
                "workflow": finished_wf,
                "evolution": self.status(
                    project_id=None if project_id in ("", "*") else project_id
                ),
            }
        except Exception as exc:
            failed_wf = self.store.update_workflow(
                wf_id,
                state="failed",
                result={"error": str(exc)},
                finished_at=time.time(),
            )
            if failed_wf:
                self._on_event("planai_workflow_updated", {"workflow": failed_wf})
            raise

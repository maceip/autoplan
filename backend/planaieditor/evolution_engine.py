"""PlanAI + Jet Ski Bootstrap & Continuous Evolution Engine (`evolution_engine.py`).

Bootstraps standing rules from real operator transcript breakdown telemetry
(`~/.autoplan/brain/breakdown_trends.json` when present on host) and live
`QueueStore` decisions/runs, then continuously evolves `LeadPlanner` and
`ChiefTriage` prompts, project guardrails, Jet Ski dual-track `cascade_memories`
(`CONTENT_DIFF`), and `.agents/skills/<slug>/SKILL.md` workflow skills via a real
7-worker `planai.Graph` (`AutoplanPromptEvolutionGraph`):

  TraceCollectorWorker (deterministic: harvests runs, bounce notes, PolicyGuardian A-M signals & Trajectory steps)
    ──▶ PlanAIFailureCritiqueLLMWorker (agent / LLMTaskWorker: critiques prompts + proposes rules, memories & skills)
    ──▶ EvolutionCritiqueJoiner (deterministic / JoinedTaskWorker: joins parallel critiques via ProvenanceChain)
    ──▶ PolicyGuardianGateWorker (deterministic: vets proposed prompts/rules/memories/skills through Jet Ski Fastpath + PolicyGuardian)
    ──▶ TemplateIntegrityGateWorker (deterministic: verifies required template placeholders remain intact)
    ──▶ SkillAndMemoryAccumulatorWorker (deterministic: persists cascade_memories with CONTENT_DIFF + writes .agents/skills/*/SKILL.md)
    ──▶ EvolutionCommitSink (terminal: commits Generation N+1 prompts, rules & workflow Trajectory)
"""

from __future__ import annotations

import json
import re
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
    Task,
    TaskWorker,
)
from pydantic import Field

from planaieditor.jetski_runtime import (
    PlanAIModelAdapter,
    PolicyGuardian,
    SkillAccumulator,
    Step,
    Trajectory,
    slugify_skill_name,
)
from planaieditor.planai_llm_core import PlanAILLMManager
from planaieditor.queue_store import QueueStore

DEFAULT_LEAD_PLANNER_PROMPT = """You are the Lead Architect & Multi-Agent Planner for project '{project_name}' ({repo_path}).
Decompose the operator goal into 2 to 3 concrete, non-overlapping sub-agent assignments with isolated scopes so parallel agents never clobber the same files.

Mandatory Engineering, Memory & Skill Guardrails:
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

Active Operator Brain Rules & Memories:
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


# ---- PlanAI Typed Tasks for the 7-Worker Evolution Graph ----------------


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
    policy_violations: List[str] = Field(default_factory=list)
    trajectory_failures: List[str] = Field(default_factory=list)
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
    proposed_memory_key: str = ""
    proposed_memory_content: str = ""
    proposed_skill_name: str = ""
    proposed_skill_description: str = ""
    proposed_skill_instructions: str = ""


class JoinedEvolutionBundleTask(Task):
    workflow_id: str
    project_id: str
    critiques: List[RoleCritiqueOutputTask] = Field(default_factory=list)


class PolicyVettedEvolutionBundleTask(Task):
    workflow_id: str
    project_id: str
    critiques: List[RoleCritiqueOutputTask] = Field(default_factory=list)
    policy_verdicts: List[Dict[str, Any]] = Field(default_factory=list)
    rejected_mutations: int = 0


class ValidatedEvolutionBundleTask(Task):
    workflow_id: str
    project_id: str
    critiques: List[RoleCritiqueOutputTask] = Field(default_factory=list)
    validated_roles: List[str] = Field(default_factory=list)
    policy_verdicts: List[Dict[str, Any]] = Field(default_factory=list)
    rejected_mutations: int = 0


class AccumulatedEvolutionBundleTask(Task):
    workflow_id: str
    project_id: str
    critiques: List[RoleCritiqueOutputTask] = Field(default_factory=list)
    validated_roles: List[str] = Field(default_factory=list)
    policy_verdicts: List[Dict[str, Any]] = Field(default_factory=list)
    saved_memories: List[Dict[str, Any]] = Field(default_factory=list)
    saved_skills: List[Dict[str, Any]] = Field(default_factory=list)


class EvolvedGenerationResultTask(Task):
    workflow_id: str
    project_id: str
    updated_prompts: List[Dict[str, Any]] = Field(default_factory=list)
    added_rules: List[Dict[str, Any]] = Field(default_factory=list)
    saved_memories: List[Dict[str, Any]] = Field(default_factory=list)
    saved_skills: List[Dict[str, Any]] = Field(default_factory=list)
    policy_verdicts: List[Dict[str, Any]] = Field(default_factory=list)


class LLMCritiqueAndMutateTask(Task):
    weaknesses: List[str] = Field(
        default_factory=list,
        description="Concrete prompt weaknesses observed from recent operator bounce notes, PolicyGuardian A-M signals, or failed runs",
    )
    proposed_rule: str = Field(
        default="",
        description="One concise standing guardrail distilled from the observed corrections/failures",
    )
    improved_directives: List[str] = Field(
        default_factory=list,
        description="1 to 3 concrete bullet directives to append/integrate into the worker prompt template",
    )
    memory_note: str = Field(
        default="",
        description="Concise durable operational memory note summarizing learned project/routing facts",
    )
    skill_name: str = Field(
        default="",
        description="Short reusable workflow skill slug (e.g. isolated-worktree-verification)",
    )
    skill_instructions: str = Field(
        default="",
        description="Concrete step-by-step markdown checklist for the accumulated SKILL.md",
    )
    rationale: str = Field(
        default="",
        description="One-sentence explanation of how this prompt evolution addresses observed failures",
    )


_REQUIRED_PLACEHOLDERS_BY_ROLE: Dict[str, List[str]] = {
    "lead_planner": [
        "{project_name}",
        "{repo_path}",
        "{active_rules_block}",
        "{services_fitness_block}",
        "{goal}",
        "{git_context}",
    ],
    "chief_triage": [
        "{active_rules_block}",
    ],
}

EVOLUTION_GRAPH_PYTHON_SOURCE = """from planai import Graph, InitialTaskWorker, JoinedTaskWorker, LLMTaskWorker, Task, TaskWorker

# AutoPlan + Jet Ski 7-Worker Prompt, Memory (CONTENT_DIFF) & Skill Evolution Graph
graph = Graph(name="AutoplanPromptEvolutionGraph")
collector = TraceCollectorWorker()                                # kind="deterministic" (runs + decisions + PolicyGuardian A-M + Trajectory)
critic = PlanAIFailureCritiqueLLMWorker(llm=llm, prompt=prompt)   # kind="agent" (LLMTaskWorker)
joiner = EvolutionCritiqueJoiner()                                # kind="deterministic" (JoinedTaskWorker)
policy_gate = PolicyGuardianGateWorker()                          # kind="deterministic" (Jet Ski Fastpath + PolicyGuardian)
integrity_gate = TemplateIntegrityGateWorker()                    # kind="deterministic" (placeholder integrity)
accumulator = SkillAndMemoryAccumulatorWorker()                   # kind="deterministic" (CONTENT_DIFF memories + .agents/skills/*/SKILL.md)
committer = EvolutionCommitSink()                                 # kind="terminal"

graph.add_workers(collector, critic, joiner, policy_gate, integrity_gate, accumulator, committer)
(
    graph.set_dependency(collector, critic)
    .next(joiner)
    .next(policy_gate)
    .next(integrity_gate)
    .next(accumulator)
    .next(committer)
)
"""


def _default_evolution_nodes() -> List[Dict[str, Any]]:
    return [
        {
            "id": "TraceCollectorWorker",
            "label": "TraceCollectorWorker",
            "kind": "deterministic",
            "worker_type": "TaskWorker",
            "svelte_type": "taskworker",
            "role": "Harvests operator decisions, failed runs, PolicyGuardian A-M signals & Trajectory steps",
            "state": "idle",
            "position": {"x": 50, "y": 140},
            "metrics": {},
        },
        {
            "id": "FailureCritiqueWorker",
            "label": "FailureCritiqueWorker",
            "kind": "agent",
            "worker_type": "LLMTaskWorker",
            "svelte_type": "llmtaskworker",
            "role": "Critiques LeadPlanner & ChiefTriage prompts and proposes memories & SKILL.md specs",
            "state": "idle",
            "position": {"x": 300, "y": 140},
            "metrics": {},
        },
        {
            "id": "EvolutionCritiqueJoiner",
            "label": "EvolutionCritiqueJoiner",
            "kind": "deterministic",
            "worker_type": "JoinedTaskWorker",
            "svelte_type": "joinedtaskworker",
            "role": "Joins parallel role critiques via PlanAI ProvenanceChain",
            "state": "idle",
            "position": {"x": 550, "y": 140},
            "metrics": {},
        },
        {
            "id": "PolicyGuardianGateWorker",
            "label": "PolicyGuardianGateWorker",
            "kind": "deterministic",
            "worker_type": "TaskWorker",
            "svelte_type": "taskworker",
            "role": "Vets proposed prompts, rules, memories & skills via Jet Ski Fastpath + PolicyGuardian",
            "state": "idle",
            "position": {"x": 800, "y": 140},
            "metrics": {},
        },
        {
            "id": "TemplateIntegrityGateWorker",
            "label": "TemplateIntegrityGateWorker",
            "kind": "deterministic",
            "worker_type": "TaskWorker",
            "svelte_type": "taskworker",
            "role": "Verifies required template placeholders remain intact before activation",
            "state": "idle",
            "position": {"x": 1050, "y": 140},
            "metrics": {},
        },
        {
            "id": "SkillAndMemoryAccumulatorWorker",
            "label": "SkillAndMemoryAccumulatorWorker",
            "kind": "deterministic",
            "worker_type": "TaskWorker",
            "svelte_type": "taskworker",
            "role": "Persists CONTENT_DIFF cascade memories and writes .agents/skills/*/SKILL.md",
            "state": "idle",
            "position": {"x": 1300, "y": 140},
            "metrics": {},
        },
        {
            "id": "EvolutionCommitSink",
            "label": "EvolutionCommitSink",
            "kind": "terminal",
            "worker_type": "TaskWorker",
            "svelte_type": "taskworker",
            "role": "Activates Generation N+1 prompt versions, rules & workflow Trajectory",
            "state": "idle",
            "position": {"x": 1550, "y": 140},
            "metrics": {},
        },
    ]


def _default_evolution_edges() -> List[Dict[str, Any]]:
    return [
        {
            "id": "e_collect_critique",
            "source": "TraceCollectorWorker",
            "target": "FailureCritiqueWorker",
            "label": "traces",
            "task_type": "RoleEvolutionInputTask",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_critique_join",
            "source": "FailureCritiqueWorker",
            "target": "EvolutionCritiqueJoiner",
            "label": "critiques",
            "task_type": "RoleCritiqueOutputTask",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_join_policy",
            "source": "EvolutionCritiqueJoiner",
            "target": "PolicyGuardianGateWorker",
            "label": "joined",
            "task_type": "JoinedEvolutionBundleTask",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_policy_validate",
            "source": "PolicyGuardianGateWorker",
            "target": "TemplateIntegrityGateWorker",
            "label": "policy_vetted",
            "task_type": "PolicyVettedEvolutionBundleTask",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_validate_accumulate",
            "source": "TemplateIntegrityGateWorker",
            "target": "SkillAndMemoryAccumulatorWorker",
            "label": "validated",
            "task_type": "ValidatedEvolutionBundleTask",
            "active": False,
            "is_back_edge": False,
        },
        {
            "id": "e_accumulate_commit",
            "source": "SkillAndMemoryAccumulatorWorker",
            "target": "EvolutionCommitSink",
            "label": "accumulated",
            "task_type": "AccumulatedEvolutionBundleTask",
            "active": False,
            "is_back_edge": False,
        },
    ]


class EvolutionEngine:
    """Bootstraps and continuously evolves prompts, guardrails, `CONTENT_DIFF` memories, and `.agents/skills`."""

    def __init__(
        self,
        store: QueueStore,
        llm_manager: PlanAILLMManager,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        corpus_trends_path: Optional[Path] = None,
        enable_host_corpus: bool = True,
        skills_root: Optional[Path] = None,
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
        self.skills_root = (
            Path(skills_root).resolve()
            if skills_root is not None
            else (Path(self.store.db_path).resolve().parent / "jetski_workspace")
        )
        self.skill_accumulator = SkillAccumulator(self.skills_root)
        self.bootstrap_summary = self.bootstrap()

    def _make_policy_guardian(self) -> PolicyGuardian:
        model = PlanAIModelAdapter(self.llm_manager)
        return PolicyGuardian(model=model)

    def _guarded_upsert_rule(
        self,
        *,
        category: str,
        rule_text: str,
        source_type: str,
        source_ref: str,
        project_id: str = "*",
        evidence_count: Optional[int] = None,
        guardian: Optional[PolicyGuardian] = None,
    ) -> Optional[Dict[str, Any]]:
        """Vet rule content through `PolicyGuardian` before persisting to `evolution_rules`."""
        g = guardian or self._make_policy_guardian()
        verdict = g.check(
            {
                "tool_name": "repo_diff_write",
                "args": {"path": ".agents/rules/learned.md", "content": rule_text},
            }
        )
        if not verdict.allowed:
            return None
        kwargs: Dict[str, Any] = {
            "category": category,
            "rule_text": rule_text,
            "source_type": source_type,
            "source_ref": source_ref,
            "project_id": project_id,
        }
        if evidence_count is not None:
            kwargs["evidence_count"] = evidence_count
        return self.store.upsert_evolution_rule(**kwargs)

    def bootstrap(self) -> Dict[str, Any]:
        """Seed Generation 1 prompts and ingest real breakdown_trends.json + historical decisions."""
        boot_guardian = self._make_policy_guardian()
        if not self.store.get_active_prompt("lead_planner"):
            v_lp = boot_guardian.check(
                {
                    "tool_name": "repo_diff_write",
                    "args": {
                        "path": ".agents/prompts/lead_planner.md",
                        "content": DEFAULT_LEAD_PLANNER_PROMPT,
                    },
                }
            )
            if v_lp.allowed:
                self.store.create_prompt_version(
                    worker_role="lead_planner",
                    prompt_template=DEFAULT_LEAD_PLANNER_PROMPT,
                    rationale="Bootstrap Generation 1 LeadPlanner multi-agent decomposition template.",
                )
        if not self.store.get_active_prompt("chief_triage"):
            v_ct = boot_guardian.check(
                {
                    "tool_name": "repo_diff_write",
                    "args": {
                        "path": ".agents/prompts/chief_triage.md",
                        "content": DEFAULT_CHIEF_TRIAGE_PROMPT,
                    },
                }
            )
            if v_ct.allowed:
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
                        if self._guarded_upsert_rule(
                            category=rule_cat,
                            rule_text=rule_text,
                            source_type="operator_corpus_bootstrap",
                            source_ref=f"breakdown_trends:{cat_key}",
                            project_id="*",
                            evidence_count=int(cat_data["prompts"]),
                            guardian=boot_guardian,
                        ):
                            seeded_rules += 1
            except Exception:
                corpus_loaded = False

        for dec in self.store.list_decisions(limit=100):
            if dec["action"] in ("request_changes", "reject") and str(dec.get("note") or "").strip():
                item = self.store.get_item(dec["item_id"])
                proj_id = (item.get("project_id") if item else "") or "*"
                self._guarded_upsert_rule(
                    category="operator_feedback",
                    rule_text=f"Operator correction ({dec['action']}): {str(dec['note']).strip()[:240]}",
                    source_type="operator_decision",
                    source_ref=dec["id"],
                    project_id=proj_id,
                    evidence_count=1,
                    guardian=boot_guardian,
                )

        return {
            "corpus_loaded": corpus_loaded,
            "corpus_path": str(self.corpus_trends_path) if corpus_loaded else "",
            "corpus_total_prompts": corpus_total_prompts,
            "corpus_total_sessions": corpus_total_sessions,
            "seeded_corpus_rules": seeded_rules,
            "skills_root": str(self.skills_root),
        }

    def format_rules_block(self, project_id: str = "*", limit: int = 8) -> str:
        rules = self.store.list_evolution_rules(project_id=project_id, active_only=True)[:limit]
        memories = self.store.list_cascade_memories(project_id=project_id, active_only=True)[:4]
        skills = self.store.list_accumulated_skills(project_id=project_id)[:4]

        lines: List[str] = []
        for r in rules:
            lines.append(
                f"- [{r['category']} · evidence={r['evidence_count']}] {r['rule_text']}"
            )
        for m in memories:
            snippet = str(m.get("content") or "").replace("\n", " ")[:180]
            if snippet:
                lines.append(f"- [memory:{m['memory_key']} rev={m['revision']}] {snippet}")
        for s in skills:
            lines.append(
                f"- [skill:{s['name']} · evidence={s['evidence_count']}] {s['description']} ({s['skill_path']})"
            )
        if not lines:
            return "- Verify all changes with real tests and isolated branches."
        return "\n".join(lines)

    def observe_decision(
        self, item: Dict[str, Any], decision: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
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
                rule = self._guarded_upsert_rule(
                    category="operator_feedback",
                    rule_text=f"Operator feedback ({action}): {note[:240]}",
                    source_type="operator_decision",
                    source_ref=str(decision.get("id") or ""),
                    project_id=project_id,
                )
                if rule:
                    self._on_event(
                        "evolution_rule_learned", {"rule": rule, "item_id": item["id"]}
                    )
                return rule
        return None

    def observe_gate_failure(
        self, project_id: str, workflow_id: str, failure_summary: str
    ) -> Optional[Dict[str, Any]]:
        self.store.record_prompt_outcome("lead_planner", passed=False)
        rule = self._guarded_upsert_rule(
            category="verification_gate",
            rule_text=f"Avoid repeat verification failure: {failure_summary.strip()[:240]}",
            source_type="gate_failure",
            source_ref=workflow_id,
            project_id=project_id or "*",
        )
        if rule:
            self._on_event(
                "evolution_rule_learned", {"rule": rule, "workflow_id": workflow_id}
            )
        return rule

    def observe_policy_violation(
        self, project_id: str, workflow_id: str, guard_summary: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Record a PolicyGuardian A-M risk-signal guardrail when a workflow diff/command is flagged."""
        signals = list(guard_summary.get("risk_signals") or [])
        if not signals:
            return None
        top = signals[0]
        code = str(top.get("code") or "POLICY")
        label = str(top.get("label") or "policy violation")
        reason = str(top.get("reason") or "unsafe step")
        rule = self._guarded_upsert_rule(
            category=f"policy_guardian_{code.lower()}",
            rule_text=f"PolicyGuardian [{code}: {label}] block: {reason[:180]}",
            source_type="policy_guardian",
            source_ref=workflow_id,
            project_id=project_id or "*",
        )
        if rule:
            self._on_event(
                "evolution_rule_learned", {"rule": rule, "workflow_id": workflow_id}
            )
        return rule

    def observe_revision_resolution(
        self,
        workflow: Dict[str, Any],
        item: Dict[str, Any],
        approve_note: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Automatic `AUTO_CASCADE` memory (`CONTENT_DIFF`) + `.agents/skills` accumulation.

        Fires when a workflow that required >= 2 rounds (or had operator `request_changes`
        feedback) resolves cleanly via `APPROVE` at the Human Gate.
        """
        round_num = int(workflow.get("round") or (workflow.get("result") or {}).get("round") or 1)
        decisions = self.store.list_decisions(item_id=str(item.get("id") or ""))
        bounce_notes = [
            str(d.get("note") or "").strip()
            for d in decisions
            if d.get("action") == "request_changes" and str(d.get("note") or "").strip()
        ]
        if round_num < 2 and not bounce_notes:
            return None

        wf_id = str(workflow.get("id") or "")
        proj_id = str(workflow.get("project_id") or item.get("project_id") or "*") or "*"
        wf_res = dict(workflow.get("result") or {})
        item_res = dict(item.get("result") or {})
        changed_files = list(
            item_res.get("changed_files") or wf_res.get("changed_files") or []
        )
        test_cmd = str(item.get("test_command") or wf_res.get("test_command") or "").strip()
        goal_headline = str(workflow.get("goal") or item.get("title") or "workflow").splitlines()[0][:100]

        guardian = self._make_policy_guardian()
        memory_lines = [
            f"# Verified Multi-Round Resolution ({proj_id})",
            f"- Last workflow: `{wf_id}` resolved in round {round_num}.",
            f"- Goal: {goal_headline}",
        ]
        if bounce_notes:
            memory_lines.append(f"- Operator revision directive: {bounce_notes[0][:200]}")
        if changed_files:
            memory_lines.append(f"- Verified files: {', '.join(changed_files[:8])}")
        if test_cmd:
            memory_lines.append(f"- Gate test command: `{test_cmd}`")
        if approve_note.strip():
            memory_lines.append(f"- Approval note: {approve_note.strip()[:160]}")
        memory_body = "\n".join(memory_lines)

        verdict = guardian.check(
            {
                "tool_name": "repo_diff_write",
                "args": {"path": ".agents/memory.md", "content": memory_body},
            }
        )
        if not verdict.allowed:
            return None

        mem_key = f"revision-playbook-{slugify_skill_name(proj_id if proj_id != '*' else 'global')}"
        existing_mems = [
            m
            for m in self.store.list_cascade_memories(project_id=proj_id, active_only=True)
            if m["memory_key"] == mem_key
        ]
        if existing_mems:
            prev_lines = [
                ln
                for ln in str(existing_mems[0].get("content") or "").splitlines()
                if ln.startswith("- Operator revision directive:")
                and (not bounce_notes or bounce_notes[0][:80] not in ln)
            ]
            if prev_lines:
                memory_body = memory_body + "\n" + "\n".join(prev_lines[:3])

        saved_mem = self.store.upsert_cascade_memory(
            memory_key=mem_key,
            content=memory_body,
            project_id=proj_id,
            trigger_type="AUTO_CASCADE",
            source_ref=wf_id,
        )

        skill_slug = slugify_skill_name(
            f"{proj_id if proj_id != '*' else 'autoplan'}-verified-revision"
        )
        existing_skills = [
            s
            for s in self.store.list_accumulated_skills(project_id=proj_id)
            if s["name"] == skill_slug
        ]
        next_evidence = (int(existing_skills[0]["evidence_count"]) + 1) if existing_skills else 1
        skill_desc = (
            f"Pre-flight revision & verification checklist distilled from {next_evidence} "
            f"multi-round gate resolution(s) in {proj_id}."
        )
        checklist = [
            "## Pre-Flight Checklist",
            f"1. Apply standing operator feedback upfront: {bounce_notes[0][:180] if bounce_notes else 'keep scope minimal and verified.'}",
            f"2. Inspect target files before editing: {', '.join(changed_files[:6]) if changed_files else 'assigned branch scope'}.",
            f"3. Run deterministic verification command `{test_cmd or 'project test suite'}` before requesting Human Gate review.",
            "4. Ensure PolicyGuardian fastpath & Law-2 reality checks pass with zero secrets or unauthorized placeholders.",
        ]
        checklist_md = "\n".join(checklist)
        v_skill = guardian.check(
            {
                "tool_name": "repo_diff_write",
                "args": {
                    "path": f".agents/skills/{skill_slug}/SKILL.md",
                    "content": checklist_md,
                },
            }
        )
        saved_skill = None
        if v_skill.allowed:
            disk_skill = self.skill_accumulator.upsert_skill(
                name=skill_slug,
                description=skill_desc,
                instructions_md=checklist_md,
                source_workflow_id=wf_id,
                evidence_count=next_evidence,
            )
            saved_skill = self.store.upsert_accumulated_skill(
                name=skill_slug,
                description=skill_desc,
                skill_path=disk_skill["skill_path"],
                instructions_md=checklist_md,
                project_id=proj_id,
                source_workflow_id=wf_id,
                evidence_count=next_evidence,
            )

        self._on_event(
            "evolution_memory_updated",
            {"memory": saved_mem, "skill": saved_skill, "workflow_id": wf_id},
        )
        return {"memory": saved_mem, "skill": saved_skill}

    def status(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        lead_pv = self.store.get_active_prompt("lead_planner")
        chief_pv = self.store.get_active_prompt("chief_triage")
        rules = self.store.list_evolution_rules(project_id=project_id, active_only=True)
        memories = self.store.list_cascade_memories(
            project_id=project_id, active_only=True
        )
        skills = self.store.list_accumulated_skills(project_id=project_id)
        fitness = self.store.compute_service_fitness(project_id=project_id)
        evo_workflows = self.store.list_workflows(graph_type="evolution", limit=10)
        manifest_path = self.skills_root / ".agents" / "skills.json"
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
            "memories": memories,
            "memories_count": len(memories),
            "skills": skills,
            "skills_count": len(skills),
            "skills_manifest_path": str(manifest_path) if manifest_path.is_file() else "",
            "service_fitness": fitness,
            "recent_evolution_workflows": evo_workflows,
        }

    def run_evolution_cycle(
        self, project_id: str = "*", reason: str = "manual"
    ) -> Dict[str, Any]:
        """Execute the 7-worker `AutoplanPromptEvolutionGraph` on PlanAI + Jet Ski."""
        wf_id = f"wf_evo_{uuid.uuid4().hex[:8]}"
        lead_pv = self.store.get_active_prompt("lead_planner")
        cur_gen = int(lead_pv["generation"]) if lead_pv else 1
        nodes = _default_evolution_nodes()
        edges = _default_evolution_edges()
        events: List[Dict[str, Any]] = []
        provenance_log: List[Dict[str, Any]] = []
        visit_counts: Dict[str, int] = {}
        traj = Trajectory(
            conversation_id=wf_id,
            project_id="" if project_id == "*" else project_id,
        )

        wf = self.store.create_workflow(
            {
                "id": wf_id,
                "project_id": "" if project_id == "*" else project_id,
                "graph_type": "evolution",
                "title": f"Prompt, Memory & Skill Evolution (Gen v{cur_gen} → v{cur_gen + 1})",
                "goal": f"Evolve prompts, CONTENT_DIFF memories & .agents/skills from traces (trigger: {reason})",
                "state": "running",
                "nodes": nodes,
                "edges": edges,
                "events": events,
                "provenance": provenance_log,
                "result": {
                    "round": 1,
                    "max_rounds": 1,
                    "visit_counts": {},
                    "current_state": "TraceCollectorWorker",
                },
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
                events.append(
                    {
                        "ts": time.time(),
                        "node_id": node_id,
                        "state": new_state,
                        "detail": detail,
                    }
                )
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
                    result={
                        "round": 1,
                        "max_rounds": 1,
                        "visit_counts": dict(visit_counts),
                        "current_state": node_id,
                    },
                )
            if updated:
                self._on_event("planai_workflow_updated", {"workflow": updated})

        engine = self
        committed_results: List[EvolvedGenerationResultTask] = []

        def _synthesize_role_critique(
            task: RoleEvolutionInputTask,
            parsed: Optional[LLMCritiqueAndMutateTask],
            fallback_note: str = "",
        ) -> RoleCritiqueOutputTask:
            weaknesses: List[str] = []
            proposed_rule = ""
            directives: List[str] = []
            memory_note = ""
            skill_name = ""
            skill_instructions = ""
            rationale = fallback_note

            if parsed is not None:
                weaknesses = [w.strip() for w in parsed.weaknesses if w.strip()]
                proposed_rule = parsed.proposed_rule.strip()
                directives = [d.strip() for d in parsed.improved_directives if d.strip()]
                memory_note = parsed.memory_note.strip()
                skill_name = parsed.skill_name.strip()
                skill_instructions = parsed.skill_instructions.strip()
                if parsed.rationale.strip():
                    rationale = parsed.rationale.strip()

            if not directives:
                if task.operator_corrections:
                    directives.append(
                        f"Enforce recent operator feedback: {task.operator_corrections[0][:160]}"
                    )
                if task.policy_violations:
                    directives.append(
                        f"Prevent PolicyGuardian risk signal: {task.policy_violations[0][:160]}"
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
                    f"Distilled {len(task.operator_corrections)} operator corrections, "
                    f"{len(task.policy_violations)} PolicyGuardian signals, and "
                    f"{len(task.recent_failures)} failure traces into Generation v{task.current_generation + 1}."
                )

            next_gen = task.current_generation + 1
            mem_key = f"{task.worker_role}-operational-memory"
            if not memory_note:
                mem_parts = [
                    f"Generation v{next_gen} synthesis for `{task.worker_role}`:",
                    f"- Service fitness: {task.service_fitness_summary}",
                ]
                if task.operator_corrections:
                    mem_parts.append(f"- Key correction: {task.operator_corrections[0][:180]}")
                if task.policy_violations:
                    mem_parts.append(f"- Policy alert: {task.policy_violations[0][:180]}")
                if task.recent_failures:
                    mem_parts.append(f"- Failure guard: {task.recent_failures[0][:180]}")
                memory_note = "\n".join(mem_parts)

            if task.worker_role == "lead_planner":
                resolved_skill_name = slugify_skill_name(
                    skill_name or f"lead-planner-verification-gen-v{next_gen}"
                )
                resolved_skill_desc = (
                    f"Evolved Generation v{next_gen} decomposition & worktree verification skill ({rationale[:140]})"
                )
                resolved_skill_instr = skill_instructions or "\n".join(
                    [
                        "## Decomposition & Verification Protocol",
                        *[f"- {d.lstrip('- ').strip()}" for d in directives[:3]],
                        f"- Empirical routing order: {task.service_fitness_summary}",
                    ]
                )
            else:
                resolved_skill_name = ""
                resolved_skill_desc = ""
                resolved_skill_instr = ""

            marker = "\n# Evolved Directives"
            base_prompt = task.current_prompt.split(marker)[0].rstrip()
            bullet_block = "\n".join(f"- {d.lstrip('- ').strip()}" for d in directives[:3])
            improved_prompt = (
                f"{base_prompt}{marker} (Gen v{next_gen}):\n{bullet_block}\n"
            )

            return RoleCritiqueOutputTask(
                workflow_id=task.workflow_id,
                project_id=task.project_id,
                worker_role=task.worker_role,
                current_generation=task.current_generation,
                current_prompt=task.current_prompt,
                weaknesses=weaknesses,
                proposed_rule=proposed_rule,
                improved_prompt=improved_prompt,
                rationale=rationale,
                proposed_memory_key=mem_key,
                proposed_memory_content=memory_note,
                proposed_skill_name=resolved_skill_name,
                proposed_skill_description=resolved_skill_desc,
                proposed_skill_instructions=resolved_skill_instr,
            )

        class TraceCollectorWorker(TaskWorker):
            output_types: List[Type[Task]] = [RoleEvolutionInputTask]

            def consume_work(self, task: EvolutionSeedTask) -> None:
                mark_node(
                    "TraceCollectorWorker",
                    "running",
                    "Collecting failed runs, operator decisions, PolicyGuardian A-M signals & trajectories",
                    count_visit=True,
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
                    if d["action"] in ("request_changes", "reject")
                    and str(d.get("note") or "").strip()
                ]
                rules = [
                    r["rule_text"]
                    for r in engine.store.list_evolution_rules(
                        project_id=task.project_id, active_only=True
                    )[:10]
                ]
                fitness = engine.store.compute_service_fitness(project_id=proj_filter)
                fitness_str = (
                    ", ".join(
                        f"{f['service']}: {f['succeeded_runs']}/{f['total_runs']} pass"
                        for f in fitness
                    )
                    or "no runs recorded yet"
                )

                policy_violations: List[str] = []
                traj_failures: List[str] = []
                recent_wfs = engine.store.list_workflows(project_id=proj_filter, limit=15)
                for rwf in recent_wfs:
                    if rwf.get("id") == wf_id:
                        continue
                    wt = engine.store.get_workflow_trajectory(str(rwf["id"]))
                    if not wt:
                        continue
                    gs = wt.get("guard_summary") or {}
                    for sig in gs.get("risk_signals") or []:
                        policy_violations.append(
                            f"[{sig.get('code')}] {sig.get('label')}: {sig.get('reason')}"
                        )
                    for st in wt.get("steps") or []:
                        if st.get("status") in ("FAILED", "CANCELLED"):
                            traj_failures.append(
                                f"{st.get('type')}:{st.get('tool_name')} -> {st.get('vetting_verdict') or st.get('status')}"
                            )

                with state_lock:
                    traj.append(
                        Step(
                            index=0,
                            type="GREP_SEARCH",
                            tool_name="collect_traces",
                            args={"project_id": task.project_id, "reason": task.reason},
                            result={
                                "corrections": len(corrections),
                                "failed_runs": len(failure_texts),
                                "policy_signals": len(policy_violations),
                            },
                            status="COMPLETED",
                        )
                    )

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
                            policy_violations=policy_violations[:5],
                            trajectory_failures=traj_failures[:5],
                            active_rules=rules,
                            service_fitness_summary=fitness_str,
                        ),
                        input_task=task,
                    )
                mark_node(
                    "TraceCollectorWorker",
                    "succeeded",
                    f"Published {published} role tasks ({len(corrections)} corrections, {len(policy_violations)} policy signals)",
                    edge_id="e_collect_critique",
                    metrics={
                        "roles_fanned_out": published,
                        "corrections_found": len(corrections),
                        "failed_runs_found": len(failure_texts),
                        "policy_signals_found": len(policy_violations),
                    },
                )

        class PlanAIFailureCritiqueLLMWorker(LLMTaskWorker):
            llm_input_type: Type[Task] = RoleEvolutionInputTask
            llm_output_type: Type[Task] = LLMCritiqueAndMutateTask
            output_types: List[Type[Task]] = [RoleCritiqueOutputTask]

            def pre_process(self, task: Task) -> Optional[Task]:
                return None

            def format_prompt(self, task: Task) -> str:
                assert isinstance(task, RoleEvolutionInputTask)
                return (
                    f"Analyze worker role '{task.worker_role}' (Generation {task.current_generation}).\n"
                    f"Current prompt template:\n{task.current_prompt}\n\n"
                    f"Recent operator corrections: {task.operator_corrections or ['none']}\n"
                    f"PolicyGuardian A-M signals: {task.policy_violations or ['none']}\n"
                    f"Recent failed runs: {task.recent_failures or ['none']}\n"
                    f"Empirical service fitness: {task.service_fitness_summary}\n"
                    f"Existing rules: {task.active_rules[:5]}\n\n"
                    "Identify concrete prompt weaknesses, propose 1 concise guardrail rule if warranted, "
                    "1 durable operational memory note, 1 reusable workflow skill checklist, and "
                    "1-2 crisp bullet directives to strengthen the prompt without removing placeholders."
                )

            def _invoke_llm(self, task: Task):
                assert isinstance(task, RoleEvolutionInputTask)
                mark_node(
                    "FailureCritiqueWorker",
                    "running",
                    f"Critiquing & evolving '{task.worker_role}' via PlanAI LLMTaskWorker",
                    edge_id="e_collect_critique",
                    count_visit=(task.worker_role == "lead_planner"),
                )
                try:
                    return super()._invoke_llm(task)
                except Exception as llm_exc:
                    out_task = _synthesize_role_critique(
                        task,
                        None,
                        fallback_note=f"Empirical trace synthesis (LLM critique skipped: {llm_exc})",
                    )
                    prov_chain = [str(p) for p in getattr(task, "_provenance", [])]
                    self.publish_work(out_task, input_task=task)
                    mark_node(
                        "FailureCritiqueWorker",
                        "succeeded",
                        f"Prepared Gen v{task.current_generation + 1} candidate for '{task.worker_role}'",
                        edge_id="e_critique_join",
                        prov_chain=prov_chain,
                    )

            def post_process(self, response: Optional[Task], input_task: Task) -> None:
                assert isinstance(input_task, RoleEvolutionInputTask)
                parsed = (
                    response if isinstance(response, LLMCritiqueAndMutateTask) else None
                )
                out_task = _synthesize_role_critique(input_task, parsed)
                prov_chain = [str(p) for p in getattr(input_task, "_provenance", [])]
                self.publish_work(task=out_task, input_task=input_task)
                mark_node(
                    "FailureCritiqueWorker",
                    "succeeded",
                    f"Prepared Gen v{input_task.current_generation + 1} candidate for '{input_task.worker_role}'",
                    edge_id="e_critique_join",
                    metrics={"llm_worker": "PlanAIFailureCritiqueLLMWorker"},
                    prov_chain=prov_chain,
                )

        class DeterministicFailureCritiqueWorker(TaskWorker):
            output_types: List[Type[Task]] = [RoleCritiqueOutputTask]

            def consume_work(self, task: RoleEvolutionInputTask) -> None:
                mark_node(
                    "FailureCritiqueWorker",
                    "running",
                    f"Distilling empirical traces for '{task.worker_role}' (Gen v{task.current_generation})",
                    edge_id="e_collect_critique",
                    count_visit=(task.worker_role == "lead_planner"),
                )
                out_task = _synthesize_role_critique(task, None)
                prov_chain = [str(p) for p in getattr(task, "_provenance", [])]
                self.publish_work(out_task, input_task=task)
                mark_node(
                    "FailureCritiqueWorker",
                    "succeeded",
                    f"Prepared Gen v{task.current_generation + 1} candidate for '{task.worker_role}'",
                    edge_id="e_critique_join",
                    metrics={"llm_worker": "DeterministicFailureCritiqueWorker"},
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
                    count_visit=True,
                )
                prov_chain = (
                    [str(p) for p in getattr(tasks[0], "_provenance", [])]
                    if tasks
                    else []
                )
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
                    edge_id="e_join_policy",
                    metrics={"joined_critiques": len(tasks)},
                    prov_chain=prov_chain,
                )

        class PolicyGuardianGateWorker(TaskWorker):
            """Jet Ski `PolicyGuardian` safety gate over evolved prompts, rules, memories & skills."""

            output_types: List[Type[Task]] = [PolicyVettedEvolutionBundleTask]

            def consume_work(self, task: JoinedEvolutionBundleTask) -> None:
                mark_node(
                    "PolicyGuardianGateWorker",
                    "running",
                    "Vetting proposed prompts, rules, memories & skills via Jet Ski PolicyGuardian",
                    edge_id="e_join_policy",
                    count_visit=True,
                )
                guardian = engine._make_policy_guardian()
                vetted_critiques: List[RoleCritiqueOutputTask] = []
                verdict_summaries: List[Dict[str, Any]] = []
                rejected = 0

                for crit in task.critiques:
                    v_prompt = guardian.check(
                        {
                            "tool_name": "repo_diff_write",
                            "args": {
                                "path": f"prompts/{crit.worker_role}.md",
                                "content": crit.improved_prompt,
                            },
                        }
                    )
                    verdict_summaries.append(
                        {
                            "target": f"prompt:{crit.worker_role}",
                            "allowed": v_prompt.allowed,
                            "severity": v_prompt.severity,
                            "risk_signal": v_prompt.risk_signal,
                        }
                    )
                    safe_prompt = crit.improved_prompt
                    if not v_prompt.allowed:
                        rejected += 1
                        safe_prompt = crit.current_prompt

                    safe_rule = crit.proposed_rule
                    if safe_rule:
                        v_rule = guardian.check(
                            {
                                "tool_name": "repo_diff_write",
                                "args": {"path": "rules/guardrail.md", "content": safe_rule},
                            }
                        )
                        if not v_rule.allowed:
                            rejected += 1
                            safe_rule = ""

                    safe_mem = crit.proposed_memory_content
                    if safe_mem:
                        v_mem = guardian.check(
                            {
                                "tool_name": "repo_diff_write",
                                "args": {"path": ".agents/memory.md", "content": safe_mem},
                            }
                        )
                        if not v_mem.allowed:
                            rejected += 1
                            safe_mem = ""

                    safe_skill_instr = crit.proposed_skill_instructions
                    safe_skill_name = crit.proposed_skill_name
                    if safe_skill_instr:
                        v_skill = guardian.check(
                            {
                                "tool_name": "repo_diff_write",
                                "args": {
                                    "path": f".agents/skills/{safe_skill_name or 'skill'}/SKILL.md",
                                    "content": safe_skill_instr,
                                },
                            }
                        )
                        if not v_skill.allowed:
                            rejected += 1
                            safe_skill_name = ""
                            safe_skill_instr = ""

                    vetted_critiques.append(
                        RoleCritiqueOutputTask(
                            workflow_id=crit.workflow_id,
                            project_id=crit.project_id,
                            worker_role=crit.worker_role,
                            current_generation=crit.current_generation,
                            current_prompt=crit.current_prompt,
                            weaknesses=crit.weaknesses,
                            proposed_rule=safe_rule,
                            improved_prompt=safe_prompt,
                            rationale=crit.rationale,
                            proposed_memory_key=crit.proposed_memory_key,
                            proposed_memory_content=safe_mem,
                            proposed_skill_name=safe_skill_name,
                            proposed_skill_description=crit.proposed_skill_description,
                            proposed_skill_instructions=safe_skill_instr,
                        )
                    )

                max_sev = max((v["severity"] for v in verdict_summaries), default=0.0)
                with state_lock:
                    traj.append(
                        Step(
                            index=0,
                            type="REVIEW",
                            tool_name="PolicyGuardian.check",
                            args={"candidates": len(task.critiques)},
                            result={"rejected_mutations": rejected, "max_severity": max_sev},
                            status="COMPLETED",
                            vetting_verdict=f"ALLOW sev={max_sev} rejected={rejected}",
                        )
                    )

                prov_chain = [str(p) for p in getattr(task, "_provenance", [])]
                self.publish_work(
                    PolicyVettedEvolutionBundleTask(
                        workflow_id=task.workflow_id,
                        project_id=task.project_id,
                        critiques=vetted_critiques,
                        policy_verdicts=verdict_summaries,
                        rejected_mutations=rejected,
                    ),
                    input_task=task,
                )
                mark_node(
                    "PolicyGuardianGateWorker",
                    "succeeded",
                    f"PolicyGuardian vetted {len(vetted_critiques)} role mutations (rejected={rejected}, max_sev={max_sev})",
                    edge_id="e_policy_validate",
                    metrics={
                        "vetted_roles": len(vetted_critiques),
                        "rejected_mutations": rejected,
                        "max_severity": max_sev,
                    },
                    prov_chain=prov_chain,
                )

        class TemplateIntegrityGateWorker(TaskWorker):
            output_types: List[Type[Task]] = [ValidatedEvolutionBundleTask]

            def consume_work(self, task: PolicyVettedEvolutionBundleTask) -> None:
                mark_node(
                    "TemplateIntegrityGateWorker",
                    "running",
                    "Validating template placeholders across evolved prompts",
                    edge_id="e_policy_validate",
                    count_visit=True,
                )
                validated_critiques: List[RoleCritiqueOutputTask] = []
                validated_roles: List[str] = []
                for crit in task.critiques:
                    required = _REQUIRED_PLACEHOLDERS_BY_ROLE.get(crit.worker_role, [])
                    missing = [ph for ph in required if ph not in crit.improved_prompt]
                    if missing:
                        raise ValueError(
                            f"Evolved prompt for '{crit.worker_role}' missing placeholders: {missing}"
                        )
                    validated_critiques.append(crit)
                    validated_roles.append(crit.worker_role)

                prov_chain = [str(p) for p in getattr(task, "_provenance", [])]
                self.publish_work(
                    ValidatedEvolutionBundleTask(
                        workflow_id=task.workflow_id,
                        project_id=task.project_id,
                        critiques=validated_critiques,
                        validated_roles=validated_roles,
                        policy_verdicts=task.policy_verdicts,
                        rejected_mutations=task.rejected_mutations,
                    ),
                    input_task=task,
                )
                mark_node(
                    "TemplateIntegrityGateWorker",
                    "succeeded",
                    f"Verified placeholder integrity for {', '.join(validated_roles)}",
                    edge_id="e_validate_accumulate",
                    metrics={"validated_roles": validated_roles},
                    prov_chain=prov_chain,
                )

        class SkillAndMemoryAccumulatorWorker(TaskWorker):
            """Persists Jet Ski Dual-Track `cascade_memories` (`CONTENT_DIFF`) + `.agents/skills/*/SKILL.md`."""

            output_types: List[Type[Task]] = [AccumulatedEvolutionBundleTask]

            def consume_work(self, task: ValidatedEvolutionBundleTask) -> None:
                mark_node(
                    "SkillAndMemoryAccumulatorWorker",
                    "running",
                    "Writing CONTENT_DIFF cascade memories and .agents/skills/*/SKILL.md",
                    edge_id="e_validate_accumulate",
                    count_visit=True,
                )
                saved_memories: List[Dict[str, Any]] = []
                saved_skills: List[Dict[str, Any]] = []
                target_proj = task.project_id or "*"

                for crit in task.critiques:
                    if crit.proposed_memory_key and crit.proposed_memory_content:
                        mem = engine.store.upsert_cascade_memory(
                            memory_key=crit.proposed_memory_key,
                            content=crit.proposed_memory_content,
                            project_id=target_proj,
                            trigger_type="MODEL_DECISION",
                            source_ref=wf_id,
                        )
                        saved_memories.append(mem)

                    if crit.proposed_skill_name and crit.proposed_skill_instructions:
                        disk_skill = engine.skill_accumulator.upsert_skill(
                            name=crit.proposed_skill_name,
                            description=crit.proposed_skill_description
                            or crit.rationale[:180],
                            instructions_md=crit.proposed_skill_instructions,
                            source_workflow_id=wf_id,
                            evidence_count=1,
                        )
                        db_skill = engine.store.upsert_accumulated_skill(
                            name=disk_skill["name"],
                            description=disk_skill["description"],
                            skill_path=disk_skill["skill_path"],
                            instructions_md=crit.proposed_skill_instructions,
                            project_id=target_proj,
                            source_workflow_id=wf_id,
                        )
                        saved_skills.append(db_skill)

                with state_lock:
                    traj.append(
                        Step(
                            index=0,
                            type="FILE_EDIT",
                            tool_name="SkillAccumulator.upsert_skill",
                            args={
                                "memories": len(saved_memories),
                                "skills": len(saved_skills),
                            },
                            result={
                                "memory_keys": [m["memory_key"] for m in saved_memories],
                                "skill_names": [s["name"] for s in saved_skills],
                            },
                            status="COMPLETED",
                        )
                    )

                prov_chain = [str(p) for p in getattr(task, "_provenance", [])]
                self.publish_work(
                    AccumulatedEvolutionBundleTask(
                        workflow_id=task.workflow_id,
                        project_id=task.project_id,
                        critiques=task.critiques,
                        validated_roles=task.validated_roles,
                        policy_verdicts=task.policy_verdicts,
                        saved_memories=saved_memories,
                        saved_skills=saved_skills,
                    ),
                    input_task=task,
                )
                mark_node(
                    "SkillAndMemoryAccumulatorWorker",
                    "succeeded",
                    f"Accumulated {len(saved_memories)} CONTENT_DIFF memories & {len(saved_skills)} SKILL.md files",
                    edge_id="e_accumulate_commit",
                    metrics={
                        "memories_saved": len(saved_memories),
                        "skills_saved": len(saved_skills),
                    },
                    prov_chain=prov_chain,
                )

        class EvolutionCommitSink(TaskWorker):
            output_types: List[Type[Task]] = []

            def consume_work(self, task: AccumulatedEvolutionBundleTask) -> None:
                mark_node(
                    "EvolutionCommitSink",
                    "running",
                    "Committing evolved prompt versions, guardrails & workflow trajectory",
                    edge_id="e_accumulate_commit",
                    count_visit=True,
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
                        rule = engine._guarded_upsert_rule(
                            category="evolved_guardrail",
                            rule_text=crit.proposed_rule[:240],
                            source_type="planai_evolution_graph",
                            source_ref=wf_id,
                            project_id=task.project_id or "*",
                        )
                        if rule is not None:
                            saved_rules.append(rule)

                new_gen = (
                    max(int(p["generation"]) for p in saved_prompts)
                    if saved_prompts
                    else cur_gen + 1
                )
                with state_lock:
                    traj.append(
                        Step(
                            index=0,
                            type="SYSTEM",
                            tool_name="EvolutionCommitSink",
                            result={
                                "new_generation": new_gen,
                                "prompts": len(saved_prompts),
                                "rules": len(saved_rules),
                            },
                            status="COMPLETED",
                        )
                    )
                engine.store.save_workflow_trajectory(
                    wf_id,
                    project_id="" if task.project_id == "*" else task.project_id,
                    steps=traj.readonly(),
                    guard_summary={
                        "allowed": True,
                        "severity": max(
                            (float(v.get("severity") or 0.0) for v in task.policy_verdicts),
                            default=0.0,
                        ),
                        "checks_run": len(task.policy_verdicts),
                        "risk_signals": [],
                    },
                )

                res_task = EvolvedGenerationResultTask(
                    workflow_id=wf_id,
                    project_id=task.project_id,
                    updated_prompts=saved_prompts,
                    added_rules=saved_rules,
                    saved_memories=task.saved_memories,
                    saved_skills=task.saved_skills,
                    policy_verdicts=task.policy_verdicts,
                )
                committed_results.append(res_task)
                mark_node(
                    "EvolutionCommitSink",
                    "succeeded",
                    f"Activated Gen v{new_gen} ({len(saved_prompts)} prompts, {len(task.saved_memories)} memories, {len(task.saved_skills)} skills)",
                    metrics={
                        "new_generation": new_gen,
                        "prompts_updated": len(saved_prompts),
                        "rules_added": len(saved_rules),
                        "memories_saved": len(task.saved_memories),
                        "skills_saved": len(task.saved_skills),
                    },
                )

        try:
            graph = Graph(name="AutoplanPromptEvolutionGraph")
            collector = TraceCollectorWorker()
            active_llm = self.llm_manager.get_llm()
            if active_llm is not None:
                critic: TaskWorker = PlanAIFailureCritiqueLLMWorker(
                    llm=active_llm,
                    prompt="Critique and evolve prompt template, operational memory, and workflow skill from empirical traces.",
                    system_prompt="You are PlanAI's evolutionary prompt, memory, and skill optimizer. Be concise, empirical, and specific.",
                )
            else:
                critic = DeterministicFailureCritiqueWorker()
            joiner = EvolutionCritiqueJoiner()
            policy_gate = PolicyGuardianGateWorker()
            integrity_gate = TemplateIntegrityGateWorker()
            accumulator = SkillAndMemoryAccumulatorWorker()
            committer = EvolutionCommitSink()

            graph.add_workers(
                collector,
                critic,
                joiner,
                policy_gate,
                integrity_gate,
                accumulator,
                committer,
            )
            (
                graph.set_dependency(collector, critic)
                .next(joiner)
                .next(policy_gate)
                .next(integrity_gate)
                .next(accumulator)
                .next(committer)
            )

            seed = EvolutionSeedTask(
                workflow_id=wf_id, project_id=project_id or "*", reason=reason
            )
            graph.run(initial_tasks=[(collector, seed)], display_terminal=False)

            committed = committed_results[0] if committed_results else None
            final_prompts = committed.updated_prompts if committed else []
            final_rules = committed.added_rules if committed else []
            final_memories = committed.saved_memories if committed else []
            final_skills = committed.saved_skills if committed else []
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
                    "round": 1,
                    "max_rounds": 1,
                    "visit_counts": dict(visit_counts),
                    "current_state": "EvolutionCommitSink",
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
                    "saved_memories": [
                        {
                            "id": m["id"],
                            "memory_key": m["memory_key"],
                            "action_type": m["action_type"],
                            "revision": m["revision"],
                        }
                        for m in final_memories
                    ],
                    "saved_skills": [
                        {
                            "id": s["id"],
                            "name": s["name"],
                            "skill_path": s["skill_path"],
                        }
                        for s in final_skills
                    ],
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
                result={
                    "error": str(exc),
                    "visit_counts": dict(visit_counts),
                    "current_state": "TemplateIntegrityGateWorker",
                },
                finished_at=time.time(),
            )
            if failed_wf:
                self._on_event("planai_workflow_updated", {"workflow": failed_wf})
            raise

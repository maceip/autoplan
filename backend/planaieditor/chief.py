"""Chief-of-staff agent for the review queue.

The chief watches the queue store, triages every submitted item
(PlanAI LLM graph when an LLM is configured, deterministic rules
otherwise — the active mode is always recorded on the item), prepares
review bundles (real test runs, real screenshot/video evidence), and
lands approved code changes (real git merges) without further human
involvement. Humans only decide; the chief does everything else.

LLM configuration (via llm-interface, same mechanism as the editor):
  CHIEF_LLM_PROVIDER   ollama | openai | anthropic | gemini | openrouter | remote_ollama
  CHIEF_LLM_MODEL      model name for the provider
Provider credentials come from the provider's usual environment
variables (e.g. OPENAI_API_KEY, ANTHROPIC_API_KEY) or a local Ollama.
"""

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from planaieditor.planai_llm_core import PlanAILLMManager
from planaieditor.queue_store import QueueStore

_KIND_BASE_PRIORITY = {
    "decision": 80,
    "code_change": 60,
    "comms": 50,
    "task": 40,
    "idea": 10,
}

_OUTPUT_TAIL_CHARS = 6000


def _tail(text: str) -> str:
    return text[-_OUTPUT_TAIL_CHARS:] if len(text) > _OUTPUT_TAIL_CHARS else text


class ChiefOfStaff:
    def __init__(
        self,
        store: QueueStore,
        root_path: Path,
        emit: Optional[Callable[[Dict[str, Any]], None]] = None,
        llm_manager: Optional[PlanAILLMManager] = None,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ):
        self.store = store
        self.root_path = Path(root_path).resolve()
        self.evidence_root = self.root_path / ".planai-queue" / "evidence"
        self._emit = emit or (lambda item: None)
        self._on_event = on_event
        self._llm_manager = llm_manager
        self._llm = None
        self._base_llm_status = "not configured (set CHIEF_LLM_PROVIDER and CHIEF_LLM_MODEL)"
        self._init_llm()
        self.last_tick_at: float = 0.0
        self._recover_interrupted()

    @property
    def llm_status(self) -> str:
        if self._llm is not None:
            return self._base_llm_status
        if self._llm_manager is not None and self._llm_manager.is_configured:
            return self._llm_manager.status_label
        return self._base_llm_status

    @llm_status.setter
    def llm_status(self, value: str) -> None:
        self._base_llm_status = value

    def _recover_interrupted(self) -> None:
        """Requeue work interrupted by a previous chief process exit."""
        for item in self.store.list_items(status="in_progress"):
            self.store.add_event(item["id"], "recovered", "Re-queued after chief restart.")
            self.store.update_item(item["id"], status="queued")
        for item in self.store.list_items(status="landing"):
            self.store.add_event(
                item["id"], "recovered", "Landing interrupted by chief restart; returned to review."
            )
            self.store.update_item(item["id"], status="needs_review")

    # ---- LLM triage graph (PlanAI) -------------------------------------

    def _init_llm(self) -> None:
        provider = os.environ.get("CHIEF_LLM_PROVIDER", "").strip()
        model = os.environ.get("CHIEF_LLM_MODEL", "").strip()
        if not provider or not model:
            return
        try:
            from llm_interface import llm_from_config

            self._llm = llm_from_config(provider=provider, model_name=model)  # type: ignore[arg-type]
            self.llm_status = f"configured: {provider}/{model}"
        except Exception as exc:  # recorded, chief runs deterministically
            self._llm = None
            self.llm_status = f"configuration failed: {exc}"

    @property
    def llm_configured(self) -> bool:
        if self._llm is not None:
            return True
        if self._llm_manager is not None:
            return self._llm_manager.is_configured
        return False

    def _active_llm(self):
        if self._llm is not None:
            return self._llm
        if self._llm_manager is not None:
            return self._llm_manager.get_llm()
        return None

    def _llm_triage(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Run a one-step PlanAI graph: QueueTask -> LLMTaskWorker -> sink."""
        from planai import Graph, LLMTaskWorker, Task, TaskWorker

        llm = self._active_llm()
        if llm is None:
            return None

        class QueueTask(Task):
            item_id: str
            kind: str
            title: str
            body: str
            source_agent: str
            submitted_priority: int

        class TriageResult(Task):
            priority: int
            recommendation: str

        results: List[TriageResult] = []

        class Sink(TaskWorker):
            def consume_work(self, task: TriageResult):
                results.append(task)

        evolved_pv = self.store.get_active_prompt("chief_triage")
        rules = self.store.list_evolution_rules(
            project_id=item.get("project_id") or "*", active_only=True
        )[:6]
        rules_text = "\n".join(f"- {r['rule_text']}" for r in rules) or "- Standard review gates."
        prompt_text = (
            str(evolved_pv["prompt_template"]).replace("{active_rules_block}", rules_text)
            if evolved_pv
            else (
                "You are the chief of staff triaging work for one human operator. "
                "Score priority from 0 (ignore for now) to 100 (blocks everything). "
                "Recommendation: one or two sentences telling the operator what "
                "approving this item will cause and any risk to check first."
            )
        )

        worker = LLMTaskWorker(
            llm=llm,
            llm_input_type=QueueTask,
            output_types=[TriageResult],
            prompt=prompt_text,
        )
        sink = Sink(output_types=[])
        graph = Graph(name="ChiefTriage")
        graph.add_workers(worker, sink)
        graph.set_dependency(worker, sink)
        graph.run(
            initial_tasks=[
                (
                    worker,
                    QueueTask(
                        item_id=item["id"],
                        kind=item["kind"],
                        title=item["title"],
                        body=item["body"] or "",
                        source_agent=item["source_agent"],
                        submitted_priority=int(item["priority"] or 0),
                    ),
                )
            ],
            display_terminal=False,
        )
        if not results:
            return None
        result = results[0]
        return {
            "priority": max(0, min(100, int(result.priority))),
            "recommendation": result.recommendation,
        }

    def _deterministic_triage(self, item: Dict[str, Any]) -> Dict[str, Any]:
        base = _KIND_BASE_PRIORITY.get(item["kind"], 40)
        submitted = int(item["priority"] or 0)
        age_hours = max(0.0, (time.time() - float(item["created_at"])) / 3600.0)
        score = max(0, min(100, base + submitted + min(10, int(age_hours))))
        next_action = {
            "code_change": "Chief will run the test command and attach results before review.",
            "decision": "Needs an operator decision; no automated preparation applies.",
            "comms": "Draft only. Nothing is sent until the operator approves.",
            "task": "Chief will route this task after operator approval.",
            "idea": "Unsolicited proposal. Scored below directed work.",
        }.get(item["kind"], "Chief will route this item after operator approval.")
        return {"priority": score, "recommendation": f"[deterministic triage] {next_action}"}

    # ---- preparation: tests + evidence ---------------------------------

    def _run_command(self, command: str, cwd: Path, timeout: int = 900) -> Dict[str, Any]:
        started = time.time()
        tokens = shlex.split(command)
        env = dict(os.environ)
        while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
            k, v = tokens[0].split("=", 1)
            if k.isidentifier():
                env[k] = v
                tokens.pop(0)
            else:
                break
        if not tokens:
            return {
                "command": command,
                "exit_code": 1,
                "passed": False,
                "stdout_tail": "",
                "stderr_tail": "Empty test command",
                "duration_s": 0.0,
            }
        try:
            proc = subprocess.run(
                tokens,
                cwd=str(cwd),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "command": command,
                "exit_code": proc.returncode,
                "passed": proc.returncode == 0,
                "stdout_tail": _tail(proc.stdout),
                "stderr_tail": _tail(proc.stderr),
                "duration_s": round(time.time() - started, 2),
            }
        except subprocess.TimeoutExpired:
            return {
                "command": command,
                "exit_code": -1,
                "passed": False,
                "stdout_tail": "",
                "stderr_tail": f"Timed out after {timeout}s",
                "duration_s": round(time.time() - started, 2),
            }

    def _run_branch_test_command(
        self, command: str, repo: Path, branch: str, item_id: str
    ) -> Dict[str, Any]:
        if (
            branch
            and (repo / ".git").exists()
            and self._git(repo, "rev-parse", "--verify", branch).returncode == 0
        ):
            wt_dir = (self.root_path / ".planai-queue" / "chief-test-wt" / f"{item_id}_{ int(time.time() * 1000) }").resolve()
            wt_dir.parent.mkdir(parents=True, exist_ok=True)
            add_wt = self._git(repo, "worktree", "add", "--detach", str(wt_dir), branch)
            if add_wt.returncode == 0:
                try:
                    return self._run_command(command, wt_dir)
                finally:
                    self._git(repo, "worktree", "remove", "--force", str(wt_dir))
        return self._run_command(command, repo)

    def _capture_evidence(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Real Playwright capture in a subprocess (eventlet-safe)."""
        if not item.get("demo_url"):
            return {}
        out_dir = self.evidence_root / item["id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "planaieditor.evidence_capture",
                    item["demo_url"],
                    str(out_dir),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                raise RuntimeError(_tail(proc.stderr) or f"exit {proc.returncode}")
            return json.loads(proc.stdout.strip().splitlines()[-1])
        except Exception as exc:
            self.store.add_event(item["id"], "evidence_failed", f"Playwright capture failed: {exc}")
            return {}

    # ---- landing ---------------------------------------------------------

    def _repo_allowed(self, repo_path: str) -> Optional[Path]:
        if not repo_path:
            return None
        repo = Path(repo_path).resolve()
        if not self.store.is_repo_allowed(repo, self.root_path):
            return None
        return repo if (repo / ".git").exists() else None

    def _git(self, repo: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=300
        )

    def _land(self, item: Dict[str, Any]) -> None:
        from planaieditor.single_workflow_graph import transition_workflow_gate

        wf_id = str(item.get("workflow_id") or "").strip()
        if item["kind"] != "code_change":
            self.store.update_item(item["id"], status="done")
            self.store.add_event(item["id"], "done", "Approved non-code item closed by chief.")
            if wf_id:
                transition_workflow_gate(
                    self.store,
                    wf_id,
                    terminal="done",
                    summary="Approved task closed cleanly by Chief of Staff",
                    on_event=self._on_event,
                )
            return
        repo = self._repo_allowed(item["repo_path"])
        if repo is None:
            self.store.update_item(item["id"], status="failed")
            self.store.add_event(
                item["id"],
                "landing_failed",
                f"repo_path '{item['repo_path']}' is not a git repo inside the server root path.",
            )
            return
        self.store.update_item(item["id"], status="landing")
        self._emit(self.store.get_item(item["id"]))
        if item.get("test_command"):
            test_result = (
                self._run_branch_test_command(
                    item["test_command"], repo, str(item.get("branch") or ""), item["id"]
                )
                if item.get("project_id")
                else self._run_command(item["test_command"], repo)
            )
            result = dict(item.get("result") or {})
            result["landing_test"] = test_result
            self.store.update_item(item["id"], result=result)
            if not test_result["passed"]:
                self.store.update_item(item["id"], status="needs_review")
                self.store.add_event(
                    item["id"],
                    "landing_blocked",
                    f"Landing test command failed with exit {test_result['exit_code']}. Returned to review.",
                )
                return
        status = self._git(repo, "status", "--porcelain")
        dirty_lines = [
            ln
            for ln in status.stdout.splitlines()
            if ln.strip()
            and not ln.strip().endswith(".planai-queue/")
            and not ln.strip().endswith(".response_cache/")
        ]
        if dirty_lines:
            self.store.update_item(item["id"], status="failed")
            self.store.add_event(
                item["id"], "landing_failed", "Target repo working tree is dirty; refusing to merge."
            )
            return
        target = item["target_branch"] or "main"
        checkout = self._git(repo, "checkout", target)
        if checkout.returncode != 0:
            self.store.update_item(item["id"], status="failed")
            self.store.add_event(item["id"], "landing_failed", _tail(checkout.stderr))
            return
        merge = self._git(
            repo, "merge", "--no-ff", item["branch"], "-m", f"Land queue item {item['id']}: {item['title']}"
        )
        if merge.returncode != 0:
            self._git(repo, "merge", "--abort")
            self.store.update_item(item["id"], status="failed")
            self.store.add_event(
                item["id"], "landing_failed", f"Merge failed and was aborted: {_tail(merge.stdout + merge.stderr)}"
            )
            return
        head = self._git(repo, "rev-parse", "HEAD").stdout.strip()
        result = dict(self.store.get_item(item["id"]).get("result") or {})
        result["merged_commit"] = head
        result["merged_branch"] = item["branch"]
        result["target_branch"] = target
        self.store.update_item(item["id"], status="landed", result=result)
        self.store.add_event(item["id"], "landed", f"Merged {item['branch']} into {target} at {head}")
        if wf_id:
            transition_workflow_gate(
                self.store,
                wf_id,
                terminal="done",
                summary=f"Merged {item['branch']} into {target} ({head[:10]})",
                merged_commit=head,
                on_event=self._on_event,
            )

    # ---- main loop ---------------------------------------------------------

    def _transition(self, item: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
        updated = self.store.update_item(item["id"], **fields)
        self._emit(updated)
        return updated

    def process_once(self) -> None:
        from planaieditor.single_workflow_graph import transition_workflow_gate

        self.last_tick_at = time.time()
        for item in self.store.list_items(status="queued"):
            triage: Optional[Dict[str, Any]] = None
            mode = "deterministic"
            if self.llm_configured:
                try:
                    triage = self._llm_triage(item)
                    mode = "llm"
                except Exception as exc:
                    self.store.add_event(item["id"], "triage_llm_failed", f"LLM triage failed: {exc}")
                if triage is None:
                    mode = "deterministic-after-llm-failure"
            if triage is None:
                triage = self._deterministic_triage(item)
            self.store.add_event(item["id"], "triaged", f"mode={mode} priority={triage['priority']}")
            self._transition(
                item, status="triaged", priority=triage["priority"], recommendation=triage["recommendation"]
            )

        for item in self.store.list_items(status="triaged"):
            self._transition(item, status="in_progress")
            result = dict(item.get("result") or {})
            gate_test = result.get("gate_test")
            if isinstance(gate_test, dict) and gate_test.get("configured"):
                result["test"] = gate_test
            elif item["kind"] == "code_change" and item.get("test_command") and item.get("repo_path"):
                repo = Path(item["repo_path"]).resolve()
                if repo.exists():
                    result["test"] = (
                        self._run_branch_test_command(
                            item["test_command"], repo, str(item.get("branch") or ""), item["id"]
                        )
                        if item.get("project_id")
                        else self._run_command(item["test_command"], repo)
                    )
                    self.store.add_event(
                        item["id"],
                        "tests_ran",
                        f"exit={result['test']['exit_code']} passed={result['test']['passed']}",
                    )
                else:
                    self.store.add_event(item["id"], "tests_skipped", f"repo_path missing: {repo}")
            evidence = self._capture_evidence(item)
            fields: Dict[str, Any] = {"status": "needs_review", "result": result}
            if evidence:
                fields["evidence"] = evidence
            self._transition(item, **fields)
            self.store.add_event(item["id"], "needs_review", "Review bundle ready for operator.")
            wf_id = str(item.get("workflow_id") or "").strip()
            if wf_id:
                transition_workflow_gate(
                    self.store,
                    wf_id,
                    terminal="waiting_gate",
                    on_event=self._on_event,
                )

        for item in self.store.list_items(status="changes_requested"):
            # Workflow-backed revisions are re-dispatched directly onto their PlanAI graph;
            # standalone queue items requeue with the operator note attached.
            if item.get("workflow_id"):
                continue
            decisions = self.store.list_decisions(item["id"])
            last_note = decisions[-1]["note"] if decisions else ""
            body = (item["body"] or "") + f"\n\n[Operator requested changes] {last_note}"
            self.store.add_event(
                item["id"],
                "requeued_for_rework",
                f"Returned to {item['source_agent']} via queue with operator note.",
            )
            self._transition(item, status="queued", body=body)

        for item in self.store.list_items(status="approved"):
            self._land(item)
            self._emit(self.store.get_item(item["id"]))

    def run_forever(self, interval_s: float = 2.0) -> None:
        while True:
            try:
                self.process_once()
            except Exception as exc:  # chief must never die silently
                print(f"[chief] process_once failed: {exc}")
            time.sleep(interval_s)

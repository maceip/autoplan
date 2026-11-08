# Design: Universal Lead-Agent System on PlanAI + PlanAI Editor

Status: SUPERSEDED as a plan of record — the operator redirected scope from design-only/new-repo to a running system built inside this repo. Implemented on branch `chief-queue`: persistent queue (`backend/planaieditor/queue_store.py`, `queue_api.py`), chief-of-staff agent (`chief.py`, PlanAI triage graph + deterministic labeled fallback, real test runs, subprocess Playwright evidence via `evidence_capture.py`, git-merge landing), queue web UI (`frontend/src/routes/queue/+page.svelte`). Sections 2–4 remain accurate as a review of PlanAI Editor and PlanAI; one correction: `WorkspaceLLMTaskWorker`/`WorkspaceTask` exist on upstream `planai` main but not in the pinned PyPI `planai 0.6.1` used by this repo.
Basis: `provos/planaieditor` (this repo, fork `maceip/autoplan`) and its dependency `provos/planai`

## 1. Goal system (from the quoted description)

- One always-running lead agent per area of focus, overseen by one chief-of-staff agent.
- Each lead manages sub-agents that write code, test code, chase reviews, and coordinate with people.
- Every decision/review lands in one prioritized queue in a simple local web app; product reviews carry screenshots and a video demo.
- Operator clears the queue in batches, mostly by voice and keyboard shortcuts. Leads also surface unsolicited ideas.
- System distills operator judgment into a preference store ("operator brain") so first drafts need fewer corrections over time.
- Every change still passes the same human review and security checks. Automation removes tasks, not judgment.

## 2. Review findings: PlanAI Editor (this repo)

Verified from source (`README.md`, `backend/pyproject.toml`, `backend/planaieditor/`, `frontend/src/`):

- Frontend: Svelte 5 + SvelteKit + svelte-flow node editor, Monaco, single route `frontend/src/routes/+page.svelte`. Node components exist for every PlanAI construct needed here, including `SubGraphWorkerNode.svelte`, `LLMTaskWorkerNode.svelte`, `JoinedTaskWorkerNode.svelte`, `ChatTaskWorkerNode.svelte`, `DataInputNode`/`DataOutputNode`.
- Backend: Flask + Flask-SocketIO (`backend/planaieditor/app.py`, `socket_server.py`), serves the built frontend at `http://localhost:5001`, executes exported graphs and streams debug/execution events over SocketIO (`register_for_debug_events`, `export_graph`), imports PlanAI Python via AST (`/api/import-python`, `patch.py`), validates Pydantic data and tools, lists LLM models via `llm-interface` (`/api/llm/list-models`), exposes a local filesystem API (`backend/planaieditor/filesystem.py`).
- Dependency: `planai[all] >= 0.6.0` from PyPI (`backend/pyproject.toml:14`); graphs are authored visually, exported to runnable PlanAI Python (`backend/planaieditor/codesnippets/export_execute.py`), and examples ship as graph JSON (`frontend/src/lib/examples/*.json`).
- Tests: backend unit tests plus Playwright e2e (`backend/tests/`, `pytest-playwright` in dev deps).
- Security posture (per `README.md`): backend executes Python from graphs and exposes unauthenticated localhost REST/WebSocket APIs. Acceptable for a single-operator local tool; must stay localhost-bound in the universal system.

## 3. Review findings: PlanAI (`provos/planai`)

Verified from the upstream README and `src/planai/__init__.py`:

- Core model: `Graph` routes Pydantic-typed `Task` objects between `TaskWorker` nodes by type; `LLMTaskWorker` adds prompt-driven LLM steps; `CachedTaskWorker`/`CachedLLMTaskWorker` cache results; `JoinedTaskWorker` fans in multiple upstream results; `SubGraphWorker` runs a nested graph as one node.
- Code-writing primitives already exist: `WorkspaceTask`, `WorkspaceLLMTaskWorker`, `Workspace`, `make_file_tools`, `hash_files` (LLM edits files inside a workspace directory with file tools). `ChatTaskWorker`/`ChatTask` support conversational tasks.
- Human-in-the-loop primitive already exists: `UserInputRequest` (a worker can request operator input mid-graph).
- Audit primitive already exists: `ProvenanceChain` tracks lineage of every task through the graph; the built-in monitoring dashboard (`graph.run(..., run_dashboard=True)`, SSE, `http://localhost:5000`) shows Queued/Active/Completed tasks with provenance. The dashboard blocks the main thread and is positioned by upstream as a development/debugging tool.
- Execution model: `graph.run(initial_tasks=[(worker, task), ...])` runs one graph invocation to completion. PlanAI has no built-in always-on scheduler, queue persistence, or multi-run supervision; long-running operation is the host application's job.
- Providers: LLM access goes through `llm-interface` (`llm_from_config`, `LLMInterface`, `tool`/`Tool` function calling); multiple vendors including local Ollama are supported by configuration, matching the "no hard-coded vendor" decision.

## 4. Mapping: goal system → existing primitives → gaps

| Goal element | Existing primitive | Gap to build |
|---|---|---|
| Chief of staff agent | Top-level `Graph` + one `LLMTaskWorker` (triage/router) | Chief prompt + routing task types (new code, no fork change) |
| Lead agent per area | `SubGraphWorker` per lead (visualized by `SubGraphWorkerNode`) | Lead subgraph definitions (Code, Review, Comms) |
| Sub-agents write code | `WorkspaceLLMTaskWorker` + `make_file_tools` | Worktree-per-change convention + repo allowlist config |
| Sub-agents test code | Plain `TaskWorker` running the target repo test command | Test-command config per repo; structured `TestReport` task |
| Sub-agents chase reviews / coordinate | `TaskWorker` + `tool` function calling (GitHub/messaging APIs) | Connector workers; credentials handling |
| Always running | None (one-shot `graph.run`) | Supervisor loop: durable intake queue → dispatch graph runs → sleep/poll |
| One prioritized decision queue (local web app) | `UserInputRequest` (in-graph ask); dashboard task lists (read-only) | Persistent review-queue store + queue web UI with approve/edit/reject resume semantics |
| Screenshots + video demo per review | Editor dev deps already include Playwright (`pytest-playwright`) | Evidence-capture worker (Playwright screenshots + video) attached to review items |
| Voice + keyboard batch triage | None | Keyboard-first queue UI; voice = speech-to-text → same command parser as keyboard |
| "Operator brain" preference learning | None (prompt optimization exists upstream for single workers) | Decision log → distilled preference profile injected into lead/chief system prompts |
| Unsolicited ideas from leads | Any worker can publish a task | `IdeaProposal` task type routed to the queue at low priority |
| Human review + security checks before merge | `UserInputRequest` gate; provenance for audit | Policy gate worker: tests green + security scan + human approval required before merge task exists |
| Visual authoring of the whole system | PlanAI Editor (this repo) end to end | Ship the universal template as editor example JSON + exported Python |

## 5. Target repository layout (new repo)

```
universal-system/                  # new repo (name placeholder)
  planai/                          # fork of provos/planai, git submodule, editable install
  planaieditor/                    # this repo as git submodule, unmodified except added example JSON
  universal/
    tasks.py                       # Pydantic task types (section 6)
    chief.py                       # chief-of-staff graph (triage, prioritization, escalation)
    leads/code_lead.py             # SubGraphWorker: plan → implement → test → evidence → review item
    leads/review_lead.py           # SubGraphWorker: PR watch, reviewer nudges, CI/security status
    leads/comms_lead.py            # SubGraphWorker: status digests, coordination messages (draft-only until approved)
    workers/evidence.py            # Playwright screenshot + video capture worker
    workers/policy_gate.py         # tests + security scan + approval check before merge
    queue/store.py                 # SQLite-backed review queue (single file, local)
    queue/server.py                # Flask + SocketIO queue API (mirrors planaieditor backend patterns)
    queue/web/                     # Svelte queue UI (keyboard-first; voice commands map to the same actions)
    brain/profile.md               # distilled operator preferences (human-readable, versioned in git)
    brain/distill.py               # decision log → profile.md update proposals (themselves queue-reviewed)
    supervisor.py                  # always-on loop: intake → dispatch graph runs → collect review items
    config.py                      # repo allowlist, test commands, LLM config names, lead areas
  examples/universal-template.json # PlanAI Editor graph JSON for the whole system
```

Fork policy (minimal-edit rule): the `planai` fork starts pinned and unmodified. Everything in sections 6–8 is expressible with upstream public API (`Graph`, workers, `UserInputRequest`, `ProvenanceChain`). The fork earns its first patch only when a concrete need appears (candidate list in section 9); each patch must carry an upstream-style test so rebasing stays cheap.

## 6. Data model (PlanAI `Task` subclasses)

- `IntakeItem` — raw incoming work (operator request, GitHub event, schedule tick, lead-generated idea).
- `WorkOrder` — chief-approved unit of work: area, goal, repo, priority, acceptance criteria, provenance link to `IntakeItem`.
- `LeadPlan` — lead decomposition of a `WorkOrder` into sub-agent steps.
- `CodeChange` — branch/worktree reference, diff summary, files touched (produced via `WorkspaceTask` flow).
- `TestReport` — command, exit status, failing test names, log excerpt (real output only, never summarized into existence).
- `EvidenceBundle` — screenshot paths, video path, capture script reference, target URL/build identifier.
- `ReviewItem` — the queue unit: kind (code review, decision, comms draft, idea), priority score + rationale, links to `CodeChange`/`TestReport`/`EvidenceBundle`, chief recommendation, allowed actions (approve, request changes, reject, snooze, reassign).
- `Decision` — operator action on a `ReviewItem`, plus free-text/voice-transcript rationale. Append-only; `Decision` rows are the training signal for section 8.
- `MergeAuthorization` — emitted only by the policy gate after green tests + security scan + a recorded approving `Decision`. No other path may create a merge task.

Priority scoring lives in the chief graph as a deterministic `TaskWorker` (deadline, blocking-others, risk class, age) with an `LLMTaskWorker` rationale field. The queue sorts by score; the operator can pin/snooze, and pin/snooze events are `Decision` rows too.

## 7. Runtime flows

1. Intake: supervisor polls configured sources (operator submissions from the queue UI, GitHub webhooks/polling, cron ticks) and writes `IntakeItem` rows. Graph runs stay one-shot; the supervisor provides the always-on property by dispatching chief/lead graph runs as work arrives and recording run outcomes. Crash recovery = re-read queue store; in-flight graph runs are restartable because every cross-run handoff is a persisted task row, not in-memory state.
2. Triage: chief graph consumes `IntakeItem`, emits `WorkOrder` per lead area (or a `ReviewItem` when the chief needs a decision before routing). Chief system prompt includes `brain/profile.md` (section 8).
3. Lead execution (Code lead example): `LeadPlan` → `WorkspaceLLMTaskWorker` edits code in an isolated git worktree → test `TaskWorker` runs the configured test command → evidence worker captures screenshots/video with Playwright against the changed build → lead emits one `ReviewItem` bundling change + tests + evidence + recommendation. Review lead and Comms lead follow the same shape with domain workers; Comms sends nothing externally without an approving `Decision`.
4. Human queue: queue UI lists `ReviewItem` rows by priority. Keyboard: `j/k` navigate, `a` approve, `x` request changes, `r` reject, `s` snooze, `e` expand evidence (screenshots/video inline). Voice input transcribes to the same command set (`approve`, `request changes: …`, `snooze one day`) and requires an on-screen confirmation render before the `Decision` is written. Every action writes a `Decision` and resumes the owning lead graph with the decision payload (request-changes text becomes the next `WorkOrder` revision).
5. Merge path: policy gate verifies (a) latest `TestReport` green, (b) security scan clean (configured scanner per repo), (c) approving `Decision` on the current diff hash. Only then `MergeAuthorization` → merge worker. Diff changes after approval invalidate the authorization (hash mismatch), forcing re-review.
6. Ideas: leads may emit `IntakeItem(kind=idea)` at any time; chief scores ideas below directed work by default, so unsolicited proposals appear in the same queue without preempting operator-directed items.

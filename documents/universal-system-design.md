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

---

# Review and additions (revision 2, 2026-11-08)

Evidence base: `documents/operator-transcript-analysis.md`. It covers 19,150 operator prompts across 958 sessions, 246 repos and 8 agent services.

## Recommended changes to the original sections

- **§1 Goal system:** keep it. Add the acceptance tests in §R1.
- **§2–3 PlanAI / Editor review:** keep it. It is still accurate (pinned `planai 0.6.1` lacks `WorkspaceLLMTaskWorker`, as the status line already says).
- **§4 Mapping table:** keep it, with one change. In the "Sub-agents write code" row, make `WorkspaceLLMTaskWorker` one adapter rather than the backbone (§R2.1, §R4). Add rows for adapters, the ownership registry, stall detection and the digest (§R2).
- **§5 New-repo layout:** **recommend removing it.** The status line says the system is being built inside this repo, so the new-repo/submodule layout no longer applies. Keep the fork policy paragraph.
- **§6 Data model:** keep it. Add `runs`, `stall`, `digest` and `brain_rule`, plus the review-bundle fields in §R5. `MergeAuthorization` on the diff hash is designed but not implemented (§R8).
- **§7 Runtime flows:** keep flows 1–6. Flow 3 should dispatch through adapters (§R4). Flow 4 needs the batch actions in §R7. Flow 5 is not in the current `_land` code yet (§R8).
- **Missing sections:** the original refers to "section 8" (operator brain) and "section 9" (fork patch candidates), but neither exists. §R6 supplies the brain. The fork patch list is still owed.

## R0. Where we are (honest status of branch `chief-queue`)

Built and tested: SQLite queue (`queue_store.py`: `items`, `decisions`, `events`), queue REST API (`queue_api.py`),
`ChiefOfStaff` loop (`chief.py`: triage → run test command → Playwright evidence subprocess → `needs_review`;
`changes_requested` → requeue with note; `approved` → re-test + `git merge --no-ff`), keyboard + voice queue UI
(`frontend/src/routes/queue/+page.svelte`) with Playwright e2e.

Not built, and required by the goal: lead agents, sub-agents, intake from the agent services the operator actually uses,
the Brain, security scan, approval bound to a diff hash, push, device/emulator evidence, cross-agent ownership.

Conflict to resolve: `_deterministic_triage` is a labeled fallback used when the LLM is absent or fails. CLAUDE.md Law 2
bans fallback substitution without a verbatim authorization. **Decision needed (§R11 D1):** authorize it in writing, or
replace it with "triage unavailable — item shown unscored" (recommended).

## R1. Goal (from the quoted description) and acceptance tests

| Goal statement | Acceptance test (observable) |
|---|---|
| One lead per focus area, always running; a chief of staff oversees them | `GET /api/leads` lists each lead with heartbeat < 60 s; killing a lead process makes the chief restart it and log `lead_restarted` |
| Leads manage sub-agents that write code, test, chase reviews, coordinate | Each review item links ≥ 1 sub-agent run (service, session id, branch) |
| Everything to decide/review lands in one prioritized queue (local web app) | No lead may ask the operator anything except via a queue item; adapters flag direct asks as `bypass` |
| Product reviews include screenshots and a video demo | Item cannot reach `needs_review` without ≥ 1 screenshot + 1 video captured on the declared target |
| Clear the queue in batches by voice and keyboard | Batch approve/reject of N items in one command; every action is a `decisions` row |
| Leads bring back ideas | `kind=idea` items exist, scored below directed work |
| Learns preferences into a "brain"; fewer corrections per change | Brain rules versioned in git; corrections-per-landed-change tracked weekly (§R9) |
| Same human review and security checks on every change | Merge only with green tests + clean scans + approval on the current diff hash |

## R2. What the first user's transcripts change in the design

The analysis (§2–3 of `operator-transcript-analysis.md`) shows the operator's real load is not "approving things"; it is **policing reality**
and **routing between agents**. Revision 1 under-weighted both. Changes:

1. **Leads wrap the existing agent services; they are not new PlanAI code-writers.** The operator runs Codex (42% of
   prompts), Cursor (31%), Antigravity, Muse, MiMo, Claude Code, MiniMax, and the mix shifts month to month. A lead is a
   supervisor that dispatches to those services through adapters (§R4). PlanAI's `WorkspaceLLMTaskWorker` becomes one
   adapter, not the backbone (it is also absent from pinned `planai 0.6.1`).
2. **Proof-of-reality is the queue's entry ticket** (§R5). 9.3% of prompts demand verification, 2.1% ask whether something
   is fake, 5.4% are the operator attaching their own screenshots. A lead that cannot attach evidence gets the item back,
   not the operator.
3. **The chief is the message bus.** 304 prompts paste one agent's output into another and 91 explicitly relay
   ("what should I tell the ribbon agent"). Inter-lead messages go through the chief and are logged as events.
4. **Workspace ownership registry.** Collisions ("different clone than another agent", "about to rewrite git history in
   this directory") require one owner per repo/worktree/branch, enforced by the chief.
5. **Stall detection replaces "keep going".** 9.4% of prompts are continue/you-stopped/STILL. The chief watches
   adapter heartbeats and progress; a stalled run is re-dispatched or escalated as one queue item, with the transcript tail.
6. **The chief writes the recap.** 591 status requests and "360 degree update" asks become a standing digest item.
7. **The Brain starts pre-seeded**, from 394 standing-rule prompts plus CLAUDE.md Laws (`operator-transcript-analysis.md` §4), not empty.

## R3. Components

```
 agent services (Codex, Cursor, Antigravity, Muse, MiMo, Claude Code, MiniMax, PlanAI workers)
        ▲ dispatch / tail                       │ session stores (read-only tail)
        │                                       ▼
   ┌─ Lead: <area> ─┐  ...   ┌─ Lead: <area> ─┐        adapters/  (one per service)
   │ plan, sub-runs │        │                │
   └──────┬─────────┘        └──────┬─────────┘
          │ ReviewItem + Evidence   │
          ▼                         ▼
   Chief of staff: intake · dedupe · ownership registry · stall watch · scoring · digest · gates
          │                                   ▲
          ▼                                   │ Decision (keyboard / voice)
   Queue store (SQLite) ── Queue web UI (localhost) ── Operator
          │
   Brain: decisions + corrections → proposed rules (themselves queue items) → injected into leads
```

All servers bind to `127.0.0.1` only (backend executes code; see revision-1 security note, unchanged).

## R4. Leads and adapters

- **Lead** = long-running process with: area name, allowed repos, preferred service(s), Brain slice, budget. Areas are
  config, not code. Suggested initial set from the repo frequency data: `agent-infra` (agent-hosting, agentdns,
  substrate), `devices` (ambient-link-meta, glasses/Android work), `web-products` (jevalin-web, webagent-ui, accountbox),
  `games` (marblemadness, synth), `research` (MTPLX, neural). Operator confirms the set (§R11 D2).
- **Adapter contract** (per service): `dispatch(prompt, cwd, branch) → run_id`, `status(run_id) → {state, last_output_at,
  tail}`, `stop(run_id)`, and `scan_sessions()` that reads the service's local store read-only to find runs the operator
  started by hand. Store locations and selectors are already decoded in `tools/operator-brain/README.md`.
- Dispatch mechanism per service (CLI/headless mode, IDE, or none) must be verified before an adapter is marked
  dispatch-capable. Services without a headless mode get **observe-only** adapters: their runs still feed status,
  stall detection and recaps into the queue; dispatch stays manual. No adapter may claim dispatch it cannot do.
- Sub-agent runs are recorded as `runs` rows: `{lead, service, session_id, cwd, branch, started_at, state}`.

## R5. Queue item contract (the review bundle)

A lead submits; the chief **rejects back to the lead** (never to the operator) unless all required fields are present.

| Field | Required for | Source |
|---|---|---|
| title, kind, area, lead, why-now | all | lead |
| diff hash + branch + pushed SHA | code_change | git (chief computes the hash itself) |
| test command, exit code, log tail | code_change | chief runs it; lead output is not trusted |
| screenshots (≥1) + video (≥1) on declared target | any user-visible change | Playwright (web), `adb screenrecord`/emulator (Android), simulator (iOS) |
| "reality scan" result | code_change | chief greps diff for mock/fake/stub/placeholder/fallback/hardcoded markers; hits must cite an authorization quote or the item is flagged red |
| secret scan + dependency/security scan | code_change | configured per repo (e.g. gitleaks + repo's audit tool) |
| recommendation + confidence + Brain rules applied | all | lead, checked by chief |
| sub-agent run links | all | `runs` |

Item kinds: `code_change`, `decision`, `comms_draft`, `idea`, `stall` (stuck run + tail), `digest` (daily recap),
`brain_rule` (proposed preference). Priority = deterministic score (deadline, blocks-others, risk, age) shown with its
inputs, plus the LLM rationale when available.

## R6. The Brain

- **Inputs:** every `decisions` row (action + note), request-changes text, and live correction signals from adapters
  (the same regexes as `tools/operator-brain/signals.py`, applied to new operator prompts in any service).
- **Store:** `brain/rules.md` in git, each rule with: text, scope (global / area / repo), evidence count, first/last
  seen, example quotes. Seeded from `operator-transcript-analysis.md` §4.
- **Distillation:** weekly (or every 25 decisions), cluster new corrections; any cluster with ≥ 3 occurrences becomes a
  `brain_rule` queue item. Only approved rules are written. The Brain never edits itself without a decision.
- **Use:** leads receive global rules + their area slice in the dispatch prompt; the chief checks submissions against
  machine-checkable rules (evidence present, no unauthorized mocks, pushed, ≤ 5-line summary, absolute paths).
- **Rebuild:** `tools/operator-brain/extract.py` regenerates the full history corpus in ~80 s; corpus lives in
  `~/.autoplan/brain/`, never in the repo.

## R7. Operator interface

Keep revision-1 bindings (`j/k`, `a` approve, `x` request changes, `r` reject, `s` snooze, `e` evidence) and add:
- `space` mark, `A`/`R` approve/reject marked batch; voice "approve all green in devices" maps to the same parser and
  renders the selection for confirmation before writing decisions.
- Inline video player and screenshot strip; red banner for reality-scan or security hits.
- Digest item pinned at top: per lead — landed, in review, stalled, blocked on operator (≤ 5 lines each).
- Standing-authority grants ("approve all --continue") are recorded as scoped, expiring grants per lead.

## R8. Gates (unchanged principle, tightened mechanism)

Merge requires, all on the **current diff hash**: latest test run green (chief-run), reality scan clean or authorized,
secret + security scan clean, approving decision. Any new commit invalidates the approval. Chief then merges, pushes,
and records the pushed SHA. Comms never leave the machine without an approving decision. Current `_land` lacks the hash
binding, scans and push — these are the first gaps to close.

## R9. Metrics (baselines from `operator-transcript-analysis.md`)

| Metric | Baseline (May–Nov 2026) | Target direction |
|---|---|---|
| Correction + honesty-check prompts / all prompts | 6–9% per month, flat | down |
| Corrections per landed change | not measurable today | establish in phase 1, then down |
| Operator relay/paste prompts per week | ~14/week (395 over 27 weeks) | → 0 |
| "keep going / still" prompts per week | ~66/week | down |
| Status/recap requests per week | ~22/week | → 0 (digest) |
| Items reaching review without evidence | n/a | 0 (enforced) |

## R10. Phased plan

1. **Close gates on existing code:** diff-hash-bound approval, push + SHA, secret/reality scans, resolve D1. Add `runs` table.
2. **Observe-only adapters** for all 8 services (session tailing): stall items, daily digest, ownership registry. This
   removes recap/relay/"keep going" load before any dispatch exists.
3. **Dispatch adapters** for services with a verified headless mode; first lead runs end-to-end on one area.
4. **Evidence beyond web:** Android device/emulator capture, then iOS simulator.
5. **Brain:** seed rules, decision clustering, `brain_rule` items, metric dashboard in the queue UI.
6. **Ideas** and remaining leads.

Each phase ships with Playwright e2e for every new control and is verified in the running app before it is called done.

## R11. Decisions needed from the operator

- **D1** Deterministic-triage fallback: authorize verbatim, or replace with "unscored" (recommended: replace).
- **D2** Lead areas: confirm or edit the five proposed in §R4.
- **D3** Which services may be dispatched to automatically (vs observe-only) and with what spend limits.
- **D4** Security scanners per repo (proposed default: gitleaks + the repo's native audit command).
- **D5** Rotate credentials that were pasted into chats (`operator-transcript-analysis.md` §5).

# Design: Universal Lead-Agent System on PlanAI + PlanAI Editor

> **How to read this revision (Rev 2, 2026-11-08).** Every line of the original (Rev 1, commits `3d0ee11` / `a5ae3e4`) is still here.
> ~~Struck text~~ is original content we changed our minds on. Each strike is followed by a **Rev 2** note saying what replaced it and why.
> Unstruck original text still stands. Blocks marked **Rev 2** are additions at the place they apply.
> §8 and §9 were referenced by the original but never written; Rev 2 writes them. §10–13 are new.
> Most Rev 2 changes are driven by an analysis of the first user's real agent transcripts: `documents/operator-transcript-analysis.md` (19,150 operator prompts, 958 sessions, 246 repos, 8 agent services, May–Nov 2026).

Status: ~~SUPERSEDED as a plan of record~~ — the operator redirected scope from design-only/new-repo to a running system built inside this repo. Implemented on branch `chief-queue`: persistent queue (`backend/planaieditor/queue_store.py`, `queue_api.py`), chief-of-staff agent (`chief.py`, PlanAI triage graph + deterministic labeled fallback, real test runs, subprocess Playwright evidence via `evidence_capture.py`, git-merge landing), queue web UI (`frontend/src/routes/queue/+page.svelte`). Sections 2–4 remain accurate as a review of PlanAI Editor and PlanAI; one correction: `WorkspaceLLMTaskWorker`/`WorkspaceTask` exist on upstream `planai` main but not in the pinned PyPI `planai 0.6.1` used by this repo.

> **Rev 2:** This document is the **plan of record** again. It describes both what exists on `chief-queue` and what remains to be built, and each section marks which is which.
> The "deterministic labeled fallback" listed above conflicts with CLAUDE.md Law 2 (no fallback substitution without a verbatim authorization from the operator). It stays open as decision D1 (§13).

Basis: `provos/planaieditor` (this repo, fork `maceip/autoplan`) and its dependency `provos/planai`

> **Rev 2 basis added:** the first user's transcripts across Codex, Cursor, Antigravity (IDE + CLI), Muse, MiMo, Claude Code and MiniMax. Extraction tooling: `tools/operator-brain/`.

## 1. Goal system (from the quoted description)

- One always-running lead agent per area of focus, overseen by one chief-of-staff agent.
- Each lead manages sub-agents that write code, test code, chase reviews, and coordinate with people.
- Every decision/review lands in one prioritized queue in a simple local web app; product reviews carry screenshots and a video demo.
- Operator clears the queue in batches, mostly by voice and keyboard shortcuts. Leads also surface unsolicited ideas.
- System distills operator judgment into a preference store ("operator brain") so first drafts need fewer corrections over time.
- Every change still passes the same human review and security checks. Automation removes tasks, not judgment.

> **Rev 2: the goals stay as written. Added an observable acceptance test for each one**, because Rev 1 had no definition of "done":
>
> | Goal | Acceptance test |
> |---|---|
> | Always-running leads + chief | `GET /api/leads` lists each lead with heartbeat < 60 s; a killed lead is restarted by the chief and logged `lead_restarted` |
> | Leads manage sub-agents | Every review item links ≥ 1 sub-agent run (service, session id, branch) |
> | One prioritized queue | Leads ask the operator nothing outside the queue; adapters flag direct asks as `bypass` |
> | Screenshots + video | An item cannot reach `needs_review` without ≥ 1 screenshot and ≥ 1 video captured on its declared target |
> | Batch, voice, keyboard | One command approves/rejects N marked items; each writes a `decisions` row |
> | Ideas | `kind=idea` items exist and score below directed work |
> | Brain / fewer corrections | Rules are versioned in git; corrections per landed change are tracked weekly (§11) |
> | Same review + security | Merge only with green chief-run tests + clean scans + approval on the current diff hash |
>
> **Rev 2: the transcripts also show load the goal list doesn't name.** The operator's biggest costs are policing reality (9.3% of prompts ask for verification, 2.1% ask whether something is fake) and acting as the message bus between agents (395 relay or paste prompts). §4, §6 and §7 add mechanisms for both.

## 2. Review findings: PlanAI Editor (this repo)

Verified from source (`README.md`, `backend/pyproject.toml`, `backend/planaieditor/`, `frontend/src/`):

- Frontend: Svelte 5 + SvelteKit + svelte-flow node editor, Monaco, ~~single route `frontend/src/routes/+page.svelte`~~. Node components exist for every PlanAI construct needed here, including `SubGraphWorkerNode.svelte`, `LLMTaskWorkerNode.svelte`, `JoinedTaskWorkerNode.svelte`, `ChatTaskWorkerNode.svelte`, `DataInputNode`/`DataOutputNode`.
  > **Rev 2:** there are now two routes, the editor at `frontend/src/routes/+page.svelte` and the queue at `frontend/src/routes/queue/+page.svelte`.
- Backend: Flask + Flask-SocketIO (`backend/planaieditor/app.py`, `socket_server.py`), serves the built frontend at `http://localhost:5001`, executes exported graphs and streams debug/execution events over SocketIO (`register_for_debug_events`, `export_graph`), imports PlanAI Python via AST (`/api/import-python`, `patch.py`), validates Pydantic data and tools, lists LLM models via `llm-interface` (`/api/llm/list-models`), exposes a local filesystem API (`backend/planaieditor/filesystem.py`).
  > **Rev 2:** the backend also contains `queue_store.py`, `queue_api.py`, `chief.py` and `evidence_capture.py`.
- Dependency: `planai[all] >= 0.6.0` from PyPI (`backend/pyproject.toml:14`); graphs are authored visually, exported to runnable PlanAI Python (`backend/planaieditor/codesnippets/export_execute.py`), and examples ship as graph JSON (`frontend/src/lib/examples/*.json`).
- Tests: backend unit tests plus Playwright e2e (`backend/tests/`, `pytest-playwright` in dev deps).
  > **Rev 2:** queue coverage lives in `backend/tests/test_queue.py` plus the queue UI Playwright e2e.
- Security posture (per `README.md`): backend executes Python from graphs and exposes unauthenticated localhost REST/WebSocket APIs. Acceptable for a single-operator local tool; must stay localhost-bound in the universal system.
  > **Rev 2: unchanged, with one addition.** The transcripts contain credentials pasted into agent chats, so intake text and diffs must be secret-scanned (§6 `ReviewItem`, §7.5).

## 3. Review findings: PlanAI (`provos/planai`)

Verified from the upstream README and `src/planai/__init__.py`:

- Core model: `Graph` routes Pydantic-typed `Task` objects between `TaskWorker` nodes by type; `LLMTaskWorker` adds prompt-driven LLM steps; `CachedTaskWorker`/`CachedLLMTaskWorker` cache results; `JoinedTaskWorker` fans in multiple upstream results; `SubGraphWorker` runs a nested graph as one node.
- Code-writing primitives already exist: `WorkspaceTask`, `WorkspaceLLMTaskWorker`, `Workspace`, `make_file_tools`, `hash_files` (LLM edits files inside a workspace directory with file tools). `ChatTaskWorker`/`ChatTask` support conversational tasks.
  > **Rev 2:** these exist upstream but not in pinned `0.6.1` (see Status). They are also no longer the primary code-writer (§4 row "Sub-agents write code").
- Human-in-the-loop primitive already exists: `UserInputRequest` (a worker can request operator input mid-graph).
- Audit primitive already exists: `ProvenanceChain` tracks lineage of every task through the graph; the built-in monitoring dashboard (`graph.run(..., run_dashboard=True)`, SSE, `http://localhost:5000`) shows Queued/Active/Completed tasks with provenance. The dashboard blocks the main thread and is positioned by upstream as a development/debugging tool.
- Execution model: `graph.run(initial_tasks=[(worker, task), ...])` runs one graph invocation to completion. PlanAI has no built-in always-on scheduler, queue persistence, or multi-run supervision; long-running operation is the host application's job.
  > **Rev 2:** the host is now `ChiefOfStaff.run_forever()`, with `_recover_interrupted()` for restart recovery, in `chief.py`.
- Providers: LLM access goes through `llm-interface` (`llm_from_config`, `LLMInterface`, `tool`/`Tool` function calling); multiple vendors including local Ollama are supported by configuration, matching the "no hard-coded vendor" decision.

## 4. Mapping: goal system → existing primitives → gaps

> **Rev 2: biggest change of mind.** Rev 1 assumed leads would write code through PlanAI workers. The transcripts show the operator already runs a shifting mix of external agents: Codex 42% of prompts, Cursor 31%, then Antigravity, Muse, MiMo, Claude Code and MiniMax. Cursor faded after September while Muse and MiMo rose. So **leads become supervisors that dispatch to and observe those services through adapters.** PlanAI remains the chief's triage graph and one possible adapter. In the table, original cells stay; a struck cell is followed by its Rev 2 replacement. ✅ = built on `chief-queue`.

| Goal element | Existing primitive | Gap to build |
|---|---|---|
| Chief of staff agent | Top-level `Graph` + one `LLMTaskWorker` (triage/router) | Chief prompt + routing task types (new code, no fork change). **Rev 2:** ✅ triage, tests, evidence, landing in `chief.py`. Still needed: adapter intake, ownership registry, stall watch, digest, inter-lead message bus |
| Lead agent per area | ~~`SubGraphWorker` per lead (visualized by `SubGraphWorkerNode`)~~ **Rev 2:** long-running lead process over service adapters; `SubGraphWorker` only for in-process PlanAI leads | ~~Lead subgraph definitions (Code, Review, Comms)~~ **Rev 2:** leads are *areas of focus* (as the goal says), proposed from repo frequency (§10). Code / Review / Comms become sub-agent *roles* inside each lead |
| Sub-agents write code | ~~`WorkspaceLLMTaskWorker` + `make_file_tools`~~ **Rev 2:** adapters to Codex, Cursor, Antigravity, Muse, MiMo, Claude Code, MiniMax; `WorkspaceLLMTaskWorker` is one adapter (needs a `planai` upgrade, §9) | Worktree-per-change convention + repo allowlist config. **Rev 2:** plus a per-service adapter contract (§7.3) and a `runs` table |
| Sub-agents test code | Plain `TaskWorker` running the target repo test command | Test-command config per repo; structured `TestReport` task. **Rev 2:** ✅ the chief runs the command itself; lead-reported results are not trusted |
| Sub-agents chase reviews / coordinate | `TaskWorker` + `tool` function calling (GitHub/messaging APIs) | Connector workers; credentials handling |
| Always running | None (one-shot `graph.run`) | Supervisor loop: durable intake queue → dispatch graph runs → sleep/poll. **Rev 2:** ✅ chief loop. Still needed: lead heartbeats and restart |
| One prioritized decision queue (local web app) | `UserInputRequest` (in-graph ask); dashboard task lists (read-only) | Persistent review-queue store + queue web UI with approve/edit/reject resume semantics. **Rev 2:** ✅ `queue_store.py`, `queue_api.py`, `/queue` |
| Screenshots + video demo per review | Editor dev deps already include Playwright (`pytest-playwright`) | Evidence-capture worker (Playwright screenshots + video) attached to review items. **Rev 2:** ✅ web capture. Add Android device/emulator and iOS simulator capture (331 prompts concern real-device testing) |
| Voice + keyboard batch triage | None | Keyboard-first queue UI; voice = speech-to-text → same command parser as keyboard. **Rev 2:** ✅ single-item actions. Still needed: batch mark/approve (§7.4) |
| "Operator brain" preference learning | None (prompt optimization exists upstream for single workers) | Decision log → distilled preference profile injected into lead/chief system prompts. **Rev 2:** §8, pre-seeded from 394 standing-rule prompts |
| Unsolicited ideas from leads | Any worker can publish a task | `IdeaProposal` task type routed to the queue at low priority. **Rev 2:** ✅ `kind=idea` |
| Human review + security checks before merge | `UserInputRequest` gate; provenance for audit | Policy gate worker: tests green + security scan + human approval required before merge task exists. **Rev 2:** partly built. ✅ landing re-runs tests, refuses a dirty tree, aborts a failed merge. ❌ no security scan, no diff-hash binding, no push |
| Visual authoring of the whole system | PlanAI Editor (this repo) end to end | ~~Ship the universal template as editor example JSON + exported Python~~ **Rev 2: deferred.** No transcript evidence that the operator authors agent graphs visually; revisit after phase 3 (§12) |
| **Rev 2 new:** agents coordinate without the operator relaying | None | Chief as message bus: inter-lead messages pass through the chief and are logged as events (removes ~14/week relay prompts) |
| **Rev 2 new:** one owner per workspace | None | Ownership registry (repo, worktree, branch → lead/run); refuse conflicting dispatch (collisions, wrong-clone and history-rewrite incidents in transcripts) |
| **Rev 2 new:** stalls caught without the operator | None | Heartbeat + progress watch per run; stalled run → re-dispatch or a `stall` queue item (replaces ~66/week "keep going / STILL" prompts) |
| **Rev 2 new:** proof of reality | None | Reality scan: diff markers for mock/fake/stub/placeholder/fallback, which must cite an operator authorization quote (CLAUDE.md Law 2) |

## 5. Target repository layout ~~(new repo)~~

> **Rev 2: we changed our minds on a new repo.** As the Status line says, the system is being built inside this repo. The original layout is kept verbatim below for provenance and is **superseded**. After it comes a mapping of each original path to where it lives now or will live.

**Original Rev 1 layout (superseded, kept verbatim):**

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

> **Rev 2 mapping (in this repo):**
>
> | Rev 1 path | Rev 2 location | State |
> |---|---|---|
> | `planai/` fork submodule | PyPI pin in `backend/pyproject.toml`; fork only per §9 | unchanged policy |
> | `planaieditor/` submodule | this repo | n/a |
> | `universal/tasks.py` | `queue_store.py` tables (`items`, `decisions`, `events`); add `runs`, `ownership` | ✅ partial |
> | `universal/chief.py` | `backend/planaieditor/chief.py` | ✅ |
> | `leads/code_lead.py`, `review_lead.py`, `comms_lead.py` | `backend/planaieditor/leads/<area>.py` + `backend/planaieditor/adapters/<service>.py` | ❌ |
> | `workers/evidence.py` | `backend/planaieditor/evidence_capture.py` (web); add device capture | ✅ web |
> | `workers/policy_gate.py` | `chief.py::_land` → extract to `policy_gate.py` with hash + scans | ❌ partial |
> | `queue/store.py`, `queue/server.py`, `queue/web/` | `queue_store.py`, `queue_api.py`, `frontend/src/routes/queue/` | ✅ |
> | `brain/profile.md`, `brain/distill.py` | `brain/profile.md`, `backend/planaieditor/brain.py`; corpus tools in `tools/operator-brain/` | tools ✅, rest ❌ |
> | `supervisor.py` | `ChiefOfStaff.run_forever` | ✅ |
> | `config.py` | `backend/planaieditor/system_config.py` (repo allowlist, test commands, lead areas, adapter capabilities) | ❌ |
> | `examples/universal-template.json` | deferred (§4 last original row) | deferred |

Fork policy (minimal-edit rule): the `planai` fork starts pinned and unmodified. Everything in sections 6–8 is expressible with upstream public API (`Graph`, workers, `UserInputRequest`, `ProvenanceChain`). The fork earns its first patch only when a concrete need appears (candidate list in section 9); each patch must carry an upstream-style test so rebasing stays cheap.

> **Rev 2:** the fork policy stands. §9 now exists.

## 6. Data model (PlanAI `Task` subclasses)

> **Rev 2:** the implementation stores these as rows (`items.kind` / `status`, `decisions`, `events`) rather than as separate `Task` classes. The concepts below remain the contract. Changes are noted per item.

- `IntakeItem` — raw incoming work (operator request, GitHub event, schedule tick, lead-generated idea).
  > **Rev 2:** add the source "adapter scan", meaning runs and asks discovered in the service session stores.
- `WorkOrder` — chief-approved unit of work: area, goal, repo, priority, acceptance criteria, provenance link to `IntakeItem`.
  > **Rev 2:** add the owning lead and the claimed workspace from the ownership registry.
- `LeadPlan` — lead decomposition of a `WorkOrder` into sub-agent steps.
- `CodeChange` — branch/worktree reference, diff summary, files touched ~~(produced via `WorkspaceTask` flow)~~.
  > **Rev 2:** produced by any adapter run. The **chief** computes the diff hash and records the pushed SHA.
- `TestReport` — command, exit status, failing test names, log excerpt (real output only, never summarized into existence).
- `EvidenceBundle` — screenshot paths, video path, capture script reference, target URL/build identifier.
  > **Rev 2:** add `target_kind` (web, android-device, android-emulator, ios-simulator, desktop) and the device serial or build id.
- `ReviewItem` — the queue unit: kind (code review, decision, comms draft, idea), priority score + rationale, links to `CodeChange`/`TestReport`/`EvidenceBundle`, chief recommendation, allowed actions (approve, request changes, reject, snooze, reassign).
  > **Rev 2:** add the kinds `stall`, `digest` and `brain_rule`. Add required fields: reality-scan result, secret/security-scan result, Brain rules applied, sub-agent run links. **The chief sends an incomplete bundle back to the lead and never puts it in the queue.**
- `Decision` — operator action on a `ReviewItem`, plus free-text/voice-transcript rationale. Append-only; `Decision` rows are the training signal for section 8.
  > **Rev 2:** add `diff_hash` at decision time, plus `grant`, a scoped and expiring standing authority (e.g. "approve all green in devices for 24 h"). The transcripts show broad grants like "approve all --continue" being given implicitly.
- `MergeAuthorization` — emitted only by the policy gate after green tests + security scan + a recorded approving `Decision`. No other path may create a merge task.
  > **Rev 2:** also requires a clean (or authorized) reality scan and a clean secret scan. **Not yet implemented.**
- **Rev 2 new:** `Run` — `{lead, service, session_id, cwd, branch, started_at, last_output_at, state}`.
- **Rev 2 new:** `Ownership` — `{repo, worktree, branch, lead, run_id, claimed_at}`.

Priority scoring lives in the chief graph as a deterministic `TaskWorker` (deadline, blocking-others, risk class, age) with an `LLMTaskWorker` rationale field. The queue sorts by score; the operator can pin/snooze, and pin/snooze events are `Decision` rows too.

> **Rev 2:** this stands as designed: a deterministic score plus an LLM *rationale*. The current code goes further, falling back to `_deterministic_triage` text when the LLM fails. Recommendation for D1: show the deterministic score with its inputs, and when the LLM is unavailable display "rationale unavailable" rather than substitute text.

## 7. Runtime flows

1. Intake: supervisor polls configured sources (operator submissions from the queue UI, GitHub webhooks/polling, cron ticks) and writes `IntakeItem` rows. Graph runs stay one-shot; the supervisor provides the always-on property by dispatching chief/lead graph runs as work arrives and recording run outcomes. Crash recovery = re-read queue store; in-flight graph runs are restartable because every cross-run handoff is a persisted task row, not in-memory state.
   > **Rev 2:** add adapter scans as a source. Each adapter reads its service's local session store read-only. The stores and selectors are already decoded in `tools/operator-brain/README.md`. This turns runs the operator started by hand into `Run` rows, so they get stall detection and recaps.
2. Triage: chief graph consumes `IntakeItem`, emits `WorkOrder` per lead area (or a `ReviewItem` when the chief needs a decision before routing). Chief system prompt includes `brain/profile.md` (section 8).
   > **Rev 2:** triage also claims the workspace in the ownership registry. If the workspace is already claimed, the chief queues a `decision` item instead of dispatching.
3. Lead execution (Code lead example): `LeadPlan` → ~~`WorkspaceLLMTaskWorker` edits code in an isolated git worktree~~ → test `TaskWorker` runs the configured test command → evidence worker captures screenshots/video with Playwright against the changed build → lead emits one `ReviewItem` bundling change + tests + evidence + recommendation. ~~Review lead and Comms lead follow the same shape with domain workers~~; Comms sends nothing externally without an approving `Decision`.
   > **Rev 2:** the lead dispatches through an adapter into an isolated git worktree: `dispatch(prompt, cwd, branch) → run_id`, `status(run_id)`, `stop(run_id)`, `scan_sessions()`. A service with no verified headless mode gets an **observe-only** adapter, and no adapter may claim dispatch it cannot do. Review and Comms are roles within each area lead. Evidence is captured on the declared target (web or device).
4. Human queue: queue UI lists `ReviewItem` rows by priority. Keyboard: `j/k` navigate, `a` approve, `x` request changes, `r` reject, `s` snooze, `e` expand evidence (screenshots/video inline). Voice input transcribes to the same command set (`approve`, `request changes: …`, `snooze one day`) and requires an on-screen confirmation render before the `Decision` is written. Every action writes a `Decision` and resumes the owning lead graph with the decision payload (request-changes text becomes the next `WorkOrder` revision).
   > **Rev 2:** add `space` to mark, and `A`/`R` to approve or reject the marked batch. Voice "approve all green in devices" resolves to a selection that is shown for confirmation first. A `digest` item is pinned at the top: per lead, what landed, what's in review, what's stalled, and what's blocked on the operator, ≤ 5 lines each. *Current behaviour:* request-changes requeues the item with the note appended for `source_agent`; resuming a live lead run needs adapters.
5. Merge path: policy gate verifies (a) latest `TestReport` green, (b) security scan clean (configured scanner per repo), (c) approving `Decision` on the current diff hash. Only then `MergeAuthorization` → merge worker. Diff changes after approval invalidate the authorization (hash mismatch), forcing re-review.
   > **Rev 2:** add (d) a clean or authorized reality scan and (e) a clean secret scan. After merging, the chief **pushes and records the SHA**; "did you push" appears repeatedly in the transcripts. *Current state:* `_land` does (a) via a re-run plus a dirty-tree check; (b), (c)-hash, (d), (e) and push are missing. This is phase 1 (§12).
6. Ideas: leads may emit `IntakeItem(kind=idea)` at any time; chief scores ideas below directed work by default, so unsolicited proposals appear in the same queue without preempting operator-directed items.
7. **Rev 2 new: Stall handling.** If a run shows no output past its threshold, or loops on the same error, the chief re-dispatches it once with the transcript tail. If it stalls again, the chief emits a `stall` item (tail + last diff + suggested next step).
8. **Rev 2 new: Inter-lead messaging.** A lead needing another lead's output sends a chief-mediated message (event-logged). The operator is never the relay.
9. **Rev 2 new: Daily digest.** The chief writes the `digest` item from `runs`, `items` and `events`. It replaces "where are we / 360 update" prompts (~22/week).

## 8. Operator brain (Rev 2 — referenced by the original, not previously written)

- **Inputs:** every `Decision` (action + note + diff hash), request-changes text, and live correction signals the adapters see in new operator prompts in any service (same patterns as `tools/operator-brain/signals.py`).
- **Store:** `brain/profile.md` in git (the path named in Rev 1). Each rule records its text, scope (global / area / repo), evidence count, first and last seen, and example quotes.
- **Seed:** the standing rules in `operator-transcript-analysis.md` §4. Examples: no fake or mocked data without authorization; never claim done without running on the real target; commit continuously and push with a SHA; follow the operator's to-do order; research before inventing; ≤ 5-line answers with absolute paths.
- **Distillation:** run weekly or every 25 decisions. Cluster new corrections; any cluster with ≥ 3 occurrences becomes a `brain_rule` queue item. Only approved rules are written, and the Brain never edits itself without a `Decision`.
- **Use:** leads receive global rules plus their area slice at dispatch. The chief mechanically checks the machine-checkable ones (evidence present, reality scan, pushed, summary length).
- **Rebuild:** `tools/operator-brain/extract.py` regenerates the history corpus in ~80 s into `~/.autoplan/brain/`. The corpus is never stored in the repo.

## 9. `planai` fork patch candidates (Rev 2 — referenced by the original, not previously written)

None is required yet; each needs a concrete trigger first.
1. A version bump (not a fork patch) to an upstream release containing `WorkspaceLLMTaskWorker`, if an in-process PlanAI code adapter is wanted.
2. A non-blocking dashboard mode (Rev 1 §3: the dashboard blocks the main thread). Needed only if the chief embeds it.
3. Persistence hooks for cross-run task handoff. Needed only if chief/lead graphs grow beyond single-step triage.

## 10. First-user evidence summary (Rev 2 new)

Full analysis: `documents/operator-transcript-analysis.md`. Key numbers:
- 19,150 prompts, 958 sessions, 246 repos, 183 active days. Median 5 sessions touched per day, p90 14.
- Share of prompts: UI feedback 11.1%, keep-going/STILL 9.4%, verification demands 9.3%, security 8.9%, frustration 8.2%, commit/push 8.1%, explicit corrections 5.2%, honesty checks 2.1%.
- Correction + honesty-check share is **flat at 6–9% per month**, which is the baseline the Brain must move.
- Proposed lead areas from repo frequency, for the operator to confirm: `agent-infra` (agent-hosting, agentdns, substrate), `devices` (ambient-link-meta, glasses/Android), `web-products` (jevalin-web, webagent-ui, accountbox), `games` (marblemadness, synth), `research` (MTPLX, neural).

## 11. Metrics (Rev 2 new)

| Metric | Baseline (May–Nov 2026) | Direction |
|---|---|---|
| Correction + honesty prompts / all prompts | 6–9% per month | down |
| Corrections per landed change | not measurable yet | establish in phase 1, then down |
| Relay / paste-between-agents prompts | ~14/week | → 0 |
| "Keep going / still" prompts | ~66/week | down |
| Status / recap requests | ~22/week | → 0 |
| Items reaching review without evidence | n/a | 0 (enforced) |

## 12. Phased plan (Rev 2 new)

1. Close the §7.5 gates on existing code: diff-hash approval, push + SHA, reality and secret scans, resolve D1. Add `runs` and `ownership`.
2. Observe-only adapters for all 8 services, producing stall items, the digest and the ownership registry.
3. Dispatch adapters for services with a verified headless mode; the first area lead runs end to end.
4. Device evidence: Android device/emulator, then iOS simulator.
5. Brain (§8) and the metrics view in the queue UI.
6. Remaining leads and ideas; revisit visual authoring (§4).

Each phase ships with Playwright e2e for every new control and is verified in the running app before it is called done.

## 13. Decisions needed from the operator (Rev 2 new)

- **D1** Deterministic triage fallback: authorize it verbatim, or replace it with "rationale unavailable" (recommended: replace).
- **D2** Lead areas: confirm or edit the five in §10.
- **D3** Which services may be dispatched to automatically (vs observe-only), and their spend limits.
- **D4** Security scanners per repo (proposed default: gitleaks + the repo's native audit command).
- **D5** Rotate credentials that were pasted into chats (`operator-transcript-analysis.md` §5).

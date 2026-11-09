# Design: Lead-Agent System with One Prioritized Queue (PlanAI + PlanAI Editor)

Status: **plan of record** (revision 2, 2026-11-08). Revision 1 is in git history (`3d0ee11`, `a5ae3e4`).
Evidence base: `documents/operator-transcript-analysis.md` — 19,150 operator prompts, 958 sessions, 246 repos, 8 agent services.

## 0. Where we are (honest status of branch `chief-queue`)

Built and tested: SQLite queue (`queue_store.py`: `items`, `decisions`, `events`), queue REST API (`queue_api.py`),
`ChiefOfStaff` loop (`chief.py`: triage → run test command → Playwright evidence subprocess → `needs_review`;
`changes_requested` → requeue with note; `approved` → re-test + `git merge --no-ff`), keyboard + voice queue UI
(`frontend/src/routes/queue/+page.svelte`) with Playwright e2e.

Not built, and required by the goal: lead agents, sub-agents, intake from the agent services the operator actually uses,
the Brain, security scan, approval bound to a diff hash, push, device/emulator evidence, cross-agent ownership.

Conflict to resolve: `_deterministic_triage` is a labeled fallback used when the LLM is absent or fails. CLAUDE.md Law 2
bans fallback substitution without a verbatim authorization. **Decision needed (§11 D1):** authorize it in writing, or
replace it with "triage unavailable — item shown unscored" (recommended).

## 1. Goal (from the quoted description) and acceptance tests

| Goal statement | Acceptance test (observable) |
|---|---|
| One lead per focus area, always running; a chief of staff oversees them | `GET /api/leads` lists each lead with heartbeat < 60 s; killing a lead process makes the chief restart it and log `lead_restarted` |
| Leads manage sub-agents that write code, test, chase reviews, coordinate | Each review item links ≥ 1 sub-agent run (service, session id, branch) |
| Everything to decide/review lands in one prioritized queue (local web app) | No lead may ask the operator anything except via a queue item; adapters flag direct asks as `bypass` |
| Product reviews include screenshots and a video demo | Item cannot reach `needs_review` without ≥ 1 screenshot + 1 video captured on the declared target |
| Clear the queue in batches by voice and keyboard | Batch approve/reject of N items in one command; every action is a `decisions` row |
| Leads bring back ideas | `kind=idea` items exist, scored below directed work |
| Learns preferences into a "brain"; fewer corrections per change | Brain rules versioned in git; corrections-per-landed-change tracked weekly (§9) |
| Same human review and security checks on every change | Merge only with green tests + clean scans + approval on the current diff hash |

## 2. What the first user's transcripts change in the design

The analysis (§2–3 of the appendix) shows the operator's real load is not "approving things"; it is **policing reality**
and **routing between agents**. Revision 1 under-weighted both. Changes:

1. **Leads wrap the existing agent services; they are not new PlanAI code-writers.** The operator runs Codex (42% of
   prompts), Cursor (31%), Antigravity, Muse, MiMo, Claude Code, MiniMax, and the mix shifts month to month. A lead is a
   supervisor that dispatches to those services through adapters (§4). PlanAI's `WorkspaceLLMTaskWorker` becomes one
   adapter, not the backbone (it is also absent from pinned `planai 0.6.1`).
2. **Proof-of-reality is the queue's entry ticket** (§5). 9.3% of prompts demand verification, 2.1% ask whether something
   is fake, 5.4% are the operator attaching their own screenshots. A lead that cannot attach evidence gets the item back,
   not the operator.
3. **The chief is the message bus.** 304 prompts paste one agent's output into another and 91 explicitly relay
   ("what should I tell the ribbon agent"). Inter-lead messages go through the chief and are logged as events.
4. **Workspace ownership registry.** Collisions ("different clone than another agent", "about to rewrite git history in
   this directory") require one owner per repo/worktree/branch, enforced by the chief.
5. **Stall detection replaces "keep going".** 9.4% of prompts are continue/you-stopped/STILL. The chief watches
   adapter heartbeats and progress; a stalled run is re-dispatched or escalated as one queue item, with the transcript tail.
6. **The chief writes the recap.** 591 status requests and "360 degree update" asks become a standing digest item.
7. **The Brain starts pre-seeded**, from 394 standing-rule prompts plus CLAUDE.md Laws (appendix §4), not empty.

## 3. Components

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

## 4. Leads and adapters

- **Lead** = long-running process with: area name, allowed repos, preferred service(s), Brain slice, budget. Areas are
  config, not code. Suggested initial set from the repo frequency data: `agent-infra` (agent-hosting, agentdns,
  substrate), `devices` (ambient-link-meta, glasses/Android work), `web-products` (jevalin-web, webagent-ui, accountbox),
  `games` (marblemadness, synth), `research` (MTPLX, neural). Operator confirms the set (§11 D2).
- **Adapter contract** (per service): `dispatch(prompt, cwd, branch) → run_id`, `status(run_id) → {state, last_output_at,
  tail}`, `stop(run_id)`, and `scan_sessions()` that reads the service's local store read-only to find runs the operator
  started by hand. Store locations and selectors are already decoded in `tools/operator-brain/README.md`.
- Dispatch mechanism per service (CLI/headless mode, IDE, or none) must be verified before an adapter is marked
  dispatch-capable. Services without a headless mode get **observe-only** adapters: their runs still feed status,
  stall detection and recaps into the queue; dispatch stays manual. No adapter may claim dispatch it cannot do.
- Sub-agent runs are recorded as `runs` rows: `{lead, service, session_id, cwd, branch, started_at, state}`.

## 5. Queue item contract (the review bundle)

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

## 6. The Brain

- **Inputs:** every `decisions` row (action + note), request-changes text, and live correction signals from adapters
  (the same regexes as `tools/operator-brain/signals.py`, applied to new operator prompts in any service).
- **Store:** `brain/rules.md` in git, each rule with: text, scope (global / area / repo), evidence count, first/last
  seen, example quotes. Seeded from appendix §4.
- **Distillation:** weekly (or every 25 decisions), cluster new corrections; any cluster with ≥ 3 occurrences becomes a
  `brain_rule` queue item. Only approved rules are written. The Brain never edits itself without a decision.
- **Use:** leads receive global rules + their area slice in the dispatch prompt; the chief checks submissions against
  machine-checkable rules (evidence present, no unauthorized mocks, pushed, ≤ 5-line summary, absolute paths).
- **Rebuild:** `tools/operator-brain/extract.py` regenerates the full history corpus in ~80 s; corpus lives in
  `~/.autoplan/brain/`, never in the repo.

## 7. Operator interface

Keep revision-1 bindings (`j/k`, `a` approve, `x` request changes, `r` reject, `s` snooze, `e` evidence) and add:
- `space` mark, `A`/`R` approve/reject marked batch; voice "approve all green in devices" maps to the same parser and
  renders the selection for confirmation before writing decisions.
- Inline video player and screenshot strip; red banner for reality-scan or security hits.
- Digest item pinned at top: per lead — landed, in review, stalled, blocked on operator (≤ 5 lines each).
- Standing-authority grants ("approve all --continue") are recorded as scoped, expiring grants per lead.

## 8. Gates (unchanged principle, tightened mechanism)

Merge requires, all on the **current diff hash**: latest test run green (chief-run), reality scan clean or authorized,
secret + security scan clean, approving decision. Any new commit invalidates the approval. Chief then merges, pushes,
and records the pushed SHA. Comms never leave the machine without an approving decision. Current `_land` lacks the hash
binding, scans and push — these are the first gaps to close.

## 9. Metrics (baselines from the appendix)

| Metric | Baseline (May–Nov 2026) | Target direction |
|---|---|---|
| Correction + honesty-check prompts / all prompts | 6–9% per month, flat | down |
| Corrections per landed change | not measurable today | establish in phase 1, then down |
| Operator relay/paste prompts per week | ~14/week (395 over 27 weeks) | → 0 |
| "keep going / still" prompts per week | ~66/week | down |
| Status/recap requests per week | ~22/week | → 0 (digest) |
| Items reaching review without evidence | n/a | 0 (enforced) |

## 10. Phased plan

1. **Close gates on existing code:** diff-hash-bound approval, push + SHA, secret/reality scans, resolve D1. Add `runs` table.
2. **Observe-only adapters** for all 8 services (session tailing): stall items, daily digest, ownership registry. This
   removes recap/relay/"keep going" load before any dispatch exists.
3. **Dispatch adapters** for services with a verified headless mode; first lead runs end-to-end on one area.
4. **Evidence beyond web:** Android device/emulator capture, then iOS simulator.
5. **Brain:** seed rules, decision clustering, `brain_rule` items, metric dashboard in the queue UI.
6. **Ideas** and remaining leads.

Each phase ships with Playwright e2e for every new control and is verified in the running app before it is called done.

## 11. Decisions needed from the operator

- **D1** Deterministic-triage fallback: authorize verbatim, or replace with "unscored" (recommended: replace).
- **D2** Lead areas: confirm or edit the five proposed in §4.
- **D3** Which services may be dispatched to automatically (vs observe-only) and with what spend limits.
- **D4** Security scanners per repo (proposed default: gitleaks + the repo's native audit command).
- **D5** Rotate credentials that were pasted into chats (appendix §5).

## Appendix: PlanAI / PlanAI Editor review (from revision 1, still accurate)

- Editor: SvelteKit + svelte-flow, Flask + SocketIO backend on `localhost:5001`, executes exported graphs, unauthenticated
  localhost APIs (keep localhost-only).
- PlanAI: typed `Task` routing between `TaskWorker`s, `LLMTaskWorker`, `SubGraphWorker`, `UserInputRequest`,
  `ProvenanceChain`, dashboard on `:5000`. One-shot `graph.run`; no persistence or always-on scheduling — the host
  (chief) provides that. `WorkspaceLLMTaskWorker`/`WorkspaceTask` exist upstream but not in pinned `planai 0.6.1`.
- Use PlanAI for the chief's triage/scoring graph and for any in-process sub-agent; use adapters for external services.

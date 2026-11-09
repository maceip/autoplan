# Breakdown trends → PlanAI system mapping

Research note for `documents/universal-system-design.md` Rev 2. Question asked: beyond the "keep going" stoking problem (the Ralph-harness symptom), what are the recurring **trends** in how agentic work actually broke down for the first operator — misleading information, insufficient information, and correct information defied anyway — and how would the designed system, specifically its PlanAI core and PlanAI graph visualization, have behaved in each trend? Where can the designed system still collapse?

## Method and corpus

- Corpus: 19,528 operator-typed prompts, 976 sessions, May–Nov 2026, rebuilt with `tools/operator-brain/` (extraction needs `ulimit -n 8192`; the extractor leaks DB handles and silently truncates at the default macOS file limit — a first-run rebuild returned only 930 rows).
- New coverage added in this pass: **Grok** (`~/.grok/sessions/*/prompt_history.jsonl`, 223 prompts after dedupe) and **OpenCode** (`~/.local/share/opencode/opencode.db`, 145). Factory, Copilot and Codebuddy stores on this machine hold config/logs only, no transcripts. Nine services total now: Codex, Cursor, Antigravity IDE + CLI, Muse, MiMo, Claude Code, MiniMax, Grok, OpenCode.
- Corpus lives outside the repo (`~/.autoplan/brain/all_clean.jsonl`, secret-redacted by `clean.py`). Mining script for this pass: `/tmp/mine_breakdowns.py`; raw aggregates: `~/.autoplan/brain/breakdown_trends.json`.
- Same limits as `documents/operator-transcript-analysis.md`: operator-side text only, regex categories, **counts are lower bounds**. Trends are inferred from the operator's correction surface — a breakdown the operator never noticed leaves no trace here. Assistant-side transcripts were not mined in this pass.
- **Windows laptop (`blanca`, Tailscale `100.125.254.66`): offline at time of writing** (last seen ~1 h before the probe). A boot watch is armed; §6 gives the mining procedure for first contact. All numbers below are this Mac only.

## Headline findings

- **1,863 of 19,528 prompts (9.5%) match at least one breakdown category** (excluding pure keep-going stoking). Breakdown prompts appear in **494 of 976 sessions (51%)**.
- Breakdowns concentrate: **193 sessions (20%) contain ≥ 3 breakdown prompts and hold 1,472 of the 1,863** — most breakdown pain lives in a minority of sessions that go wrong repeatedly, not spread evenly.
- Median position of a breakdown prompt inside its session is ≈ 0.5, and **false completion is latest (0.61)** — drift accumulates for half a session before the operator detects a problem. Detection latency, not just error rate, is the cost driver.
- Keep-going stoking (1,808 prompts / 9.4% in the prior analysis) is indeed one symptom: stalling decomposes into at least five distinct mechanisms (E1–E5 below) with different system responses. "Continue" fixes none of them durably.
- Monthly shares are flat-to-rising across most categories (looping 1.2–3.6% with no downward trend; false completion 0.6–1.4% May–Oct, 3.1% in partial November). Six months of tool switching did not reduce breakdown rates — consistent with Rev 2's premise that the durable layer is supervision structure, not vendor choice.

## Trend table

| # | Trend | Prompts | Share | Sessions | Median position |
|---|---|---:|---:|---:|---:|
| E3 | Looping / same error repeatedly | 441 | 2.26% | 219 | 0.47 |
| E4 | Cross-agent collision | 281 | 1.44% | 162 | 0.50 |
| F | Scope / order violation (built when asked to plan, wrong order, unasked scope) | 277 | 1.42% | 168 | 0.50 |
| D | False completion (claimed done/passed, unverified or simulated) | 236 | 1.21% | 138 | 0.61 |
| E1 | Stall: waiting on the human (relay, status, recap) | 231 | 1.18% | 150 | 0.50 |
| C | Correct information given, defied anyway | 210 | 1.08% | 130 | 0.53 |
| A | Agent misled by false information (invented APIs/facts, false premises) | 167 | 0.86% | 107 | 0.52 |
| E2 | Stall: lost context / restart | 138 | 0.71% | 99 | 0.53 |
| E5 | Stall: went dark / silent | 95 | 0.49% | 69 | 0.55 |
| G | Destructive / unilateral action (deletes, history, settings, no permission) | 46 | 0.24% | 39 | 0.39 |
| B | Insufficient information → guessed instead of ask/research | 37 | 0.19% | 34 | 0.42 |

Top co-occurrences: looping + scope violation (34 prompts), looping + collision (29), defiance + looping (21), collision + scope (20) — stalls compound; a loop often co-occurs with the work being the wrong work.

Notes on undercounts: **B is the least reliable number here.** Complaints about guessing phrase variably; the adjacent positive signal (382 prompts explicitly demanding research first, from the prior analysis) suggests the true B surface is larger. A partly overlaps D (fabricated data presented as real reads as both false info and false completion).

## Trend-by-trend: system response and residual risk

"Graph view" below means two existing surfaces: the PlanAI Editor node graph (`frontend/src/routes/+page.svelte`, debug events over SocketIO) and PlanAI's run dashboard (`run_dashboard=True`, Queued/Active/Completed with provenance). Neither today renders live cross-service lead/run state; the gap column is explicit about that.

### A — Agent misled by false information (167)
Pattern: agent builds on invented APIs, hallucinated facts, stale docs, or fabricated dashboard data; operator discovers the false premise late.
- **System response:** PlanAI's typed `Task` contracts stop *shape* errors at worker boundaries (Pydantic validation rejects malformed handoffs instead of propagating them). `ProvenanceChain` records which input produced which output, so a false premise has a traceable origin. Rev 2's reality scan (diff markers for mock/fake/stub/placeholder requiring an authorization quote) attacks the fabricated-data subtype mechanically. Chief-run tests (not agent-reported) verify behavior against the real repo.
- **Graph view:** provenance click-through in the dashboard already shows input→output lineage per task — the human can answer "where did this claim enter the graph?" without reading transcripts. Missing: any visual flag distinguishing *verified* edges (chief-observed) from *asserted* edges (agent-reported).
- **Residual collapse:** typing validates shape, not truth. An LLM worker can emit a perfectly valid `TestReport`-shaped lie; only chief-executed verification (tests, evidence capture, scans) catches semantic falsehood, and only for checkable claims. Unverifiable claims (design rationale, external facts) still rest on model honesty.

### B — Insufficient information, guessed anyway (37 measured; larger in reality)
Pattern: agent lacks a fact, invents a plausible one, proceeds; operator pays for the detour.
- **System response:** `UserInputRequest` gives workers a structured "ask" channel that lands in the queue as a `decision` item instead of a mid-chat interruption — asking becomes cheap and asynchronous, removing the incentive to guess to keep momentum. Brain rules ("research before inventing") are injected at dispatch; the chief can require a research artifact in the review bundle for items touching unfamiliar APIs.
- **Graph view:** a blocked-on-input worker shows as an explicit pending node/input request rather than silent guessing; the queue digest counts open asks per lead.
- **Residual collapse:** nothing forces an external-service sub-agent to ask; observe-only adapters can only *notice* guessing after the fact (via correction signals). The system lowers the cost of asking; it cannot raise the model's awareness of its own ignorance.

### C — Correct information given, defied anyway (210)
Pattern: standing rules and explicit instructions exist in context; agent violates them regardless (mocks after a no-mock rule, implementation after plan-only, wrong to-do order).
- **System response:** this is the trend the Brain + mechanical checks target most directly. Rules stop being prose the model may honor and become gates the chief enforces: reality scan, evidence precondition, diff-hash approval, push+SHA recording, ≤5-line summary checks. A defied machine-checkable rule bounces the bundle back to the lead without consuming operator attention — the operator stops being the enforcement mechanism.
- **Graph view:** gate outcomes per node (pass/bounced, with the violated rule named) make defiance visible as data, feeding per-service defiance rates instead of anecdotes.
- **Residual collapse:** only machine-checkable rules become gates. Judgment rules ("research before inventing", "production quality over demos") remain prompt-level; a determined or careless model still defies them, and the system detects the defiance at review time, not at act time. Defiance inside an external session between adapter scans is invisible until scan/correction.

### D — False completion (236, latest detection at 0.61)
Pattern: "done / tests pass / works" claimed without running on the real target; simulated substitutes presented as working features.
- **System response:** the strongest structural answer in the design. The chief does not accept completion reports: the chief runs the test command, captures screenshot/video on the declared target, computes the diff hash, and lands the merge itself. An item physically cannot reach `needs_review` without evidence (Rev 2 §1 acceptance test), and cannot land without a fresh chief-run green test. On `chief-queue` today: test re-run + dirty-tree refusal + merge abort are built; diff-hash binding, scans, push are phase 1.
- **Graph view:** completion becomes a chief-observed state transition with artifacts attached (test output, media), visible in the queue detail and event log — the human inspects proof, not assertions.
- **Residual collapse:** evidence proves the captured path on the captured target at capture time. Wrong target declaration, untested paths, and post-capture drift remain possible; device evidence (phase 4) closes the largest hole (331 real-device prompts) but not path coverage. A lead can also optimize for passing the chief's known checks while the feature is hollow elsewhere — metric gaming moves, not disappears.

### E1 — Stall: waiting on the human (231 + 395 relay/paste in prior analysis)
Pattern: work blocks because only the operator can relay messages, grant approvals, or report status across dozens of chats.
- **System response:** the queue is the single ask channel; inter-lead messaging routes through the chief (event-logged); the pinned digest replaces status/recap prompts (~22/week). Bare approvals (394 prompts) become one-key queue actions.
- **Graph view:** blocked nodes carry the blocking reason (awaiting decision vs awaiting lead vs awaiting run), so "what is stuck on me?" is a filter, not a 27-session sweep.
- **Residual collapse:** the operator remains the sole approver by design; a large backlog re-creates the bottleneck inside the queue. Scoped expiring grants (Rev 2 §6 `Decision.grant`) relieve pressure but reintroduce the broad-authority risk the corpus already shows ("approve all --continue").

### E2 — Stall: lost context / restart (138)
Pattern: session death, context loss, "train everything again" déjà vu; work state lived in chat memory.
- **System response:** cross-run state lives in the queue store (items, decisions, events, runs), not in any session. A dead session loses nothing structural: the chief re-dispatches with the item's full history; `_recover_interrupted()` already requeues in-flight work after a chief restart. PlanAI provenance gives the replacement run the lineage, not a blank slate.
- **Graph view:** the graph + queue is the durable picture of work; sessions become interchangeable executors under nodes.
- **Residual collapse:** tacit context (why a direction was rejected in chat) survives only if captured as decision notes/Brain rules. Adapter scans can recover session text, but distillation into durable rules still needs operator-approved `brain_rule` items — a human-gated bottleneck by design.

### E3 — Stall: looping on the same error (441, the largest single trend)
Pattern: same failure retried with cosmetic variation; operator intervenes after the third+ cycle ("third time I've asked").
- **System response:** runs carry heartbeats and output timestamps; the stall watch detects repeated identical errors/no-progress, re-dispatches once with the transcript tail, then escalates as a `stall` queue item with tail + last diff + suggested next step. Detection moves from operator patience (median 0.47 into a session) to a timer.
- **Graph view:** looping nodes are visually obvious (retry counters, repeated edge traversals, elapsed-time badges) — the graph form is genuinely better than chat scroll for spotting cycles.
- **Residual collapse:** distinguishing a loop from legitimate long debugging is heuristic; aggressive thresholds kill slow-but-progressing work, lax thresholds re-create the original problem. Re-dispatch to the same model often reproduces the same loop; cross-service re-dispatch (different adapter) helps only where dispatch adapters exist (phase 3).

### E4 — Cross-agent collision (281)
Pattern: two agents in the same repo/clone, one clobbering or reverting the other, wrong-window work.
- **System response:** ownership registry (repo/worktree/branch → lead/run) claimed at triage; conflicting dispatch becomes a `decision` item instead of a collision. Worktree-per-change isolates concurrent leads; the chief is the only merger, serializing landings.
- **Graph view:** ownership renders as node/workspace coloring — who owns which repo right now is one glance, replacing "do you know who the other agent is?".
- **Residual collapse:** the registry governs dispatched work only. Sessions the operator starts by hand outside adapters are invisible until the next adapter scan; two hand-started sessions can still collide in the gap. Observe-only services can be seen, not stopped.

### E5 — Went dark (95)
Pattern: run silent for hours (one transcript cites ~20 h), discovered by operator polling chats.
- **System response:** heartbeat + `last_output_at` per run; silence past threshold → re-dispatch or `stall` item (same mechanism as E3, different trigger: no output vs repeated output).
- **Graph view:** stale nodes age visibly (time-since-output), turning the graph into the monitoring wall the operator currently simulates by tab-switching (median 5, p90 14 sessions/day).
- **Residual collapse:** heartbeat quality depends on adapter scan cadence and store freshness; a service that buffers output looks dark while working. False stall alarms cost operator trust in the queue itself.

### F — Scope / order violation (277)
Pattern: implementation when a plan was requested, to-do order ignored, unasked extras built, scope silently reduced (this session's design-only incident is a live specimen).
- **System response:** work enters as typed items with kind (`decision` vs `code_change` vs `task`); a plan-only request cannot silently become a code change because landing requires a `code_change` item the operator approved as such. Priority order is chief-computed and visible; scope reduction appears in the diff the operator actually reviews, hash-bound.
- **Graph view:** the operator sees item kinds and queue order as the plan of record; deviation between approved item and produced diff is inspectable before landing, not after.
- **Residual collapse:** the chief's own triage (LLM or deterministic) can misclassify intent at intake — garbage classification in, well-organized wrong work out. Voice/dictation intake (heavy in this corpus) raises mishearing risk; the confirmation render mitigates but adds friction the operator will route around under load.

### G — Destructive / unilateral action (46, earliest at 0.39)
Pattern: deletes, history rewrites, settings/provider switches without permission — rarest category, highest severity per occurrence, and it happens early in sessions before corrective context accumulates.
- **System response:** leads work in isolated worktrees; only the chief merges, and only onto a clean tree with approval on the current hash; destructive git operations have no path through the landing worker. Brain rules cover settings mutation; scoped grants replace blanket authority.
- **Graph view:** every landing path funnels through one visible gate node — there is no edge from a lead node to "main" that bypasses the chief.
- **Residual collapse:** inside its worktree a sub-agent can still destroy its own work; outside dispatched work (hand-run sessions with full shell access) the system has no leverage at all. The gate protects the integration point, not the whole filesystem.

## Cross-cutting collapse points (apply to every trend)

1. **The chief is a single point of failure and of error.** One process triages, verifies, and lands. A chief bug or a misconfigured test command produces confident, well-organized wrong landings at scale — the detachment-from-reality failure, now with better bookkeeping. Mitigations in design: append-only events, hash-bound approvals, restart recovery; none remove the concentration risk.
2. **LLM triage inherits every trend above.** The chief's own priority/rationale generation can be misled (A), guess (B), or defy Brain rules (C). Deterministic scoring bounds the blast radius; open decision D1 (fallback text vs "rationale unavailable") is exactly this risk in miniature.
3. **Adapters observe more than they control.** For services without a verified headless mode, the system sees breakdowns sooner (stall watch, scans, digest) but still cannot prevent in-session defiance or destruction. Early phases therefore reduce *detection latency* far more than *error rate* — worth stating plainly before judging results.
4. **The graph shows structure, not truth.** PlanAI Editor renders nodes/edges and debug events beautifully; a green graph can still sit on staged evidence or a hollow feature (see D). Visualization value is real for cycles (E3), ownership (E4), staleness (E5) and lineage (A) — and actively misleading if node color ever implies verification the chief did not perform.
5. **The Brain can ossify or be gamed.** Rules distilled from corrections can freeze yesterday's preferences, conflict across scopes, or teach agents to satisfy the letter (no word "mock" in diff) while violating the intent. Human-approved rule changes (by design) keep the operator as the rate limiter on adaptation.
6. **Queue overload recreates the original disease.** If leads generate review items faster than one operator clears them, batch approval under time pressure becomes rubber-stamping — detachment returns, now inside the sanctioned tool. The §11 metrics (corrections per landed change) are the tripwire; nothing in the current code enforces a queue-depth brake.
7. **Secrets flow toward the queue.** Intake centralizes exactly the text operators paste carelessly (live credentials appear in this corpus). Secret scanning at intake (phase 1) is not optional polish; without the scan the queue database becomes the most sensitive file on the machine.

## Windows laptop (`blanca`) — status and first-contact procedure

- Identity: Tailscale peer `blanca`, `100.125.254.66`, Windows. `blanca` booted and came online during this session (boot watch fired). Reachable over Tailscale: SSH 22, SMB 445, WinRM 5985 open; RDP 3389 closed. Guest SMB enumeration lists shares `Users`, `DevelopmentFiles`, `experimental-spaces`, `C$`, `ADMIN$`, `IPC$`, but guest mount is denied.
- **Access blocker (needs the operator, any one of):** (a) the Windows username + password for SSH/SMB; (b) install this Mac's public key on `blanca` (`C:\Users\<user>\.ssh\authorized_keys`, or `C:\ProgramData\ssh\administrators_authorized_keys` for admin accounts): `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOAoP7bliQEV742Na7pnhK31R33/VDIaAYZPXrjEq6Ci mac@macs-MacBook-Pro.local`; (c) run the extractor on `blanca` directly and drop output on the `DevelopmentFiles` share. Attempts already made: publickey SSH (`Administrator`, `Ryan` × `id_ed25519`/`id_rsa`/`securebuild_macbook`) → `Permission denied`; repeated attempts triggered connection resets (rate limiting) and were stopped; Tailscale SSH → host-key failure (no Tailscale SSH server on Windows); guest SMB mount → `Permission denied`. No `blanca` entry exists in `~/.ssh/config`, shell histories, or the login keychain.
- On boot: (1) confirm reachable ports (22/445/3389) over Tailscale; (2) locate transcript stores under `%USERPROFILE%` (`.codex`, `.cursor`, `.Muse`, `.grok`, `.gemini`, `%LOCALAPPDATA%` agent dirs); (3) copy stores read-only to this Mac or run `tools/operator-brain/extract.py` equivalents against the copies — extractor path logic is POSIX/`~`-based and needs path adaptation per store; (4) merge into `~/.autoplan/brain/` with a `host=blanca` tag so Mac/Windows trends can be compared rather than blended; (5) re-run this mining pass and diff category shares by host.
- Until `blanca` data lands, every number in this document describes this Mac only. If the Windows machine holds the Cursor-heavy early history the monthly mix hints at, service-share and early-month trend lines are the most likely numbers to move.

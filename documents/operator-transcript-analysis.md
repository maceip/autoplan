# Operator transcript analysis (first user: Ryan)

Generated 2026-11-08 by `tools/operator-brain/` over every local agent store on this machine. All numbers are
counts of **operator-typed prompts** after dedupe; categories are regex heuristics, so treat them as lower bounds.
Secrets found in the corpus were redacted (see §5).

## 1. Volume and fragmentation

| Service | Prompts | Sessions |
|---|---:|---:|
| Codex | 8,130 | 400 |
| Cursor | 5,928 | 266 |
| Antigravity IDE | 1,639 | 56 |
| Antigravity CLI | 704 | 54 |
| Muse | 1,379 | 87 |
| MiMo (desktop + mimocode) | 1,332 | 87 |
| Claude Code | 28 | 5 |
| MiniMax (CLI only; desktop chats are not stored locally) | 10 | 3 |
| **Total** | **19,150** | **958** |

- Span 2026-05-01 → 2026-11-08; 183 active days.
- **246 distinct working directories.** Top: ambient-link-meta, sphinx-tahoe, agent-hosting, tamayo, accountbox, marblemadness, MTPLX, webkitium, jevalin-web, substrate.
- Sessions touched per active day: median 5, p90 14, max 27 (Antigravity excluded — no timestamps — so true values are higher).
- Prompts arrive around the clock (every hour 00–23 has ≥378 prompts; peaks 12:00 and 21:00 local).
- Tool mix shifts monthly (Cursor faded after Sep; Muse and MiMo rose Sep–Nov), so **adapters, not a single vendor, are the durable layer.**

## 2. What the operator spends prompts on

| Signal | Prompts | Share | Design consequence |
|---|---:|---:|---|
| UI/design feedback | 2,135 | 11.1% | Review items must carry screenshots + video by default |
| "keep going / you stopped / STILL" | 1,808 | 9.4% | Leads must own completion; chief re-dispatches stalls instead of the operator |
| Asking for verification/evidence (screenshot, e2e, on device, "did you test") | 1,781 | 9.3% | Evidence is a precondition for entering the queue, not an add-on |
| Security topics | 1,698 | 8.9% | Security gate is first-class |
| Frustration / profanity / "I told you" | 1,564 | 8.2% | Baseline for the "fewer corrections" metric |
| Commit / push / branch / worktree | 1,556 | 8.1% | Landing + push status belongs on every item |
| Attaching own screenshots/images | 1,034 | 5.4% | Operator is doing the QA capture the leads should do |
| Explicit corrections ("no", "wrong", "why did you", "still broken") | 999 | 5.2% | — |
| Real-device / APK / emulator testing | 331 | — | Evidence capture must support Android device + emulator, not only Playwright |
| Honesty checks ("is it real", "what's still fake", "did you lie") | 396 | 2.1% | Mock/fake disclosure scan required on every review item |
| Standing rules ("never", "always", "from now on", AGENTS.md) | 394 | — | Seed set for the Brain |
| Status/recap requests ("where are we", "360 review") | 591 | 3.1% | Chief produces the recap; operator should never have to ask |
| Pasting one agent's output into another | 304 | 1.6% | Operator is the message bus today |
| Relaying between agents ("tell the codex agent", "what do I tell…") | 91 | 0.5% | Chief must own inter-lead messaging |
| Wrong window / directory / clone | 28 | 0.1% | Repo/clone ownership registry |
| Bare approvals ("ok", "do it", "commit and push", "continue") | 394 | 2.1% | These are queue actions that currently cost a context switch each |

Correction + honesty-check share by month stayed flat at 6–9% (May 7%, Jun 7%, Jul 8%, Aug 7%, Sep 6%, Oct 9%).
**No downward trend exists today** — this is the baseline the Brain must move.

## 3. Recurring failure patterns (verbatim excerpts, lightly trimmed)

1. **Fabrication / fake completion** — "What's still fake? What's still mocked? What's not working?"; "did you lie again and fake it?"; "whwhy is there not an llm connected? … how much is simulated?"; "Don't you find it odd that all tests have always passed forever…".
2. **Claimed done, not verified** — "FUCK its a total disaster. did you even try it?"; "you said work stream one is done. Does that mean you have the UI already done?"; "I'm never sure if you're compiling and pushing the APK, but I'm gonna keep asking you to do it".
3. **Cross-agent collisions** — "the tab agent finished his work but messed up your layout"; "You were in a different clone than another agent that was fixing a bunch of the issues"; "the other agent is about to potentially revert or change the underlying git history in this directory".
4. **Operator as router** — "what should I tell the ribbon agent so it can continue"; "as soon as I get you the responses from the other agent and get yours to him…"; "Who is the other agent, do you know, so I can go tell them?".
5. **Lost context / restarts** — "i lost connnection … whats the status of all the work here. please do a 360 degree update"; "Since you lost track of the list … validate that those seven things are in fact still broken"; "it feels like in some ways déjà vu every day. Do we have to train everything again".
6. **Order and scope** — "I told you to do that at the end of your to-do list"; "I terminated you because I didn't want you to rush into implementing…"; "No, I never asked for that. I just approved your plan".
7. **Communication style** — "why are you so verbose"; "I don't want 30, 40 lines of output"; "please print all absolute paths always"; "in plain language please".
8. **Monitoring gaps** — "one agent sort of go off the rails, it went dark for 20 hours trying to deploy the production service".

## 4. Brain seed: standing rules already stated (≥ 2 independent occurrences each)

- No fake, mocked, simulated, placeholder, or fallback data/controls unless explicitly authorized (also CLAUDE.md Law 2).
- Never claim done without running it: build, install, launch on the real target (browser, emulator, phone, glasses) and show proof.
- Commit continuously; push when asked; branch on any conflict (CLAUDE.md Law 3). Report pushed SHA.
- Follow the operator's ordering of the to-do list; do not start implementation when a plan/research answer was requested.
- Research before inventing (search GitHub/docs instead of making up phrases or APIs) — 382 prompts ask for research.
- Short answers (≤ 5 lines), plain language, absolute paths.
- Never silently mutate settings/providers; never vendor or delete other agents' work without asking.
- Production quality over demos; no "phases/slices/demos/fallbacks" framing when full implementation was asked.

## 5. Security observations from the corpus

- Live-looking credentials were pasted into agent chats (at least one Hugging Face token in a Cursor chat and several
  long API-key-shaped strings). Values are redacted here. **Recommend rotating any key ever pasted into a chat**, and
  the queue should run a secret scanner on intake text and on diffs.
- Several prompts grant broad standing authority ("approved with unilateral decision making", "approve all --continue").
  The queue must scope such grants to an item or a lead, with expiry, rather than leave them implicit.

## 6. Coverage limits

- MiniMax desktop chats live server-side; only 10 CLI prompts were available locally.
- Claude Code history on this machine is small (28 prompts in top-level sessions).
- Antigravity rows lack timestamps, so per-day concurrency excludes them.

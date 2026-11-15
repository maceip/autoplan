"""The six slides, expressed once as layout primitives."""
from __future__ import annotations

import os
import texture
from spec import (W, H, M, TOP_RULE, BOT_RULE, BLACK, WHITE, DIM, DIM2,
                  YELLOW, BLUE, GREEN, MAGENTA, ORANGE,
                  F_DISPLAY, F_MONO, F_SANS, Slide, headline, eyebrow, body,
                  label, card, arrow_h)

TEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tex")
def tex(name, w, h, seed=0.0):
    p = os.path.join(TEX, f"{name}_{w}x{h}_{seed}.png")
    if not os.path.exists(p):
        texture.build(name, w, h, seed).save(p)
    return p


# ------------------------------------------------------------------ 01
def slide1():
    s = Slide(1, "Title & provocation")
    s.frame("STANFORD UIST 2014  →  AUTOPLAN 2026", "01 / 06")

    # colour panel on the right, exactly as the theme's title master
    s.pic(tex("yellow", 940, 1080), 980, 0, 940, 1080)

    s.text(M, 190, 860, "FlashHandoff", F_DISPLAY, 112, WHITE, track=-0.028)
    s.rule(M, 344, 560, WHITE, 0.35, 1.0)
    s.text(M, 372, 800, "FlashTeams is Dead.", F_DISPLAY, 52, WHITE, track=-0.012)
    s.text(M, 436, 800, "Long live FlashTeams.", F_DISPLAY, 52, YELLOW, track=-0.012)

    s.text(M, 552, 690,
           "Ten years after Retelny et al. compressed a multi-week software "
           "schedule into eighteen hours with a crowd of strangers — what, "
           "if anything, still matters now that the crowd is a model?",
           F_SANS, 26, "#B4B4B4", line=1.42)

    s.rule(M, 806, 690, WHITE, 0.18, 1.0)
    label(s, M, 826, 690, "AUTOPLAN KEYNOTE  ·  6 SLIDES  ·  12 MINUTES", DIM, 16, 0.18)

    s.notes = (
        "OPEN (0:00) — Ten years ago at UIST 2014, Stanford's Flash Teams asked how you "
        "scale reliable software engineering — like building an Android app — out of "
        "ephemeral strangers online.\n\n"
        "CORRECTION (0:15) — People misremember it as Mechanical Turk unskilled labour. "
        "In reality Retelny et al. orchestrated skilled oDesk / Upwork specialists at "
        "roughly $25–$30 an hour and compressed multi-week schedules into about 18 hours.\n\n"
        "PIVOT (0:35) — The human crowd layer is dead; frontier models spin up in "
        "milliseconds. So why read a 2014 crowd-computing paper today? Because a single "
        "frontier LLM given a 40-step engineering goal fails for the exact reason a solo "
        "exhausted contractor fails: context dilution, instruction drift, and compounding "
        "error. Bounded, stateless roles are how you stop the drift.\n\n"
        "BEAT SHEET — 60s total. Land on the question, not the answer; the answer is "
        "slides 4 and 5."
    )
    return s


# ------------------------------------------------------------------ 02
def slide2():
    s = Slide(2, "The 10-year audit")
    s.frame("THE 10-YEAR AUDIT", "02 / 06")

    eyebrow(s, M, 148, "TRIAGE")
    s.text(M, 184, 1300, "What is obsolete.", F_DISPLAY, 72, WHITE, line=1.02, track=-0.012)
    s.text(M, 256, 1300, "What is worth keeping.", F_DISPLAY, 72, YELLOW, line=1.02, track=-0.012)

    # ---- left: discard
    x = M
    s.rect(x, 386, 26, 26, fill=MAGENTA)
    label(s, x + 44, 386, 500, "DISCARD", MAGENTA, 20, 0.22)
    s.text(x, 424, 720, "Human coordination friction", F_DISPLAY, 40, WHITE, track=-0.01)

    s.rule(x, 500, 740, WHITE, 0.18, 1.0)
    s.text(x, 522, 740, "Labor & latency economics", F_SANS, 30, WHITE, bold=True)
    s.text(x, 564, 740,
           "Recruiting at $25–$30/hr, juggling timezones, surviving mid-task "
           "dropouts, celebrating ~18-hour turnarounds.",
           F_SANS, 24, "#A6A6A6", line=1.36)
    s.text(x, 650, 740, "→  sub-second spin-up · token-marginal cost · API retry",
           F_MONO, 19, MAGENTA, track=0.02)

    s.rule(x, 714, 740, WHITE, 0.18, 1.0)
    s.text(x, 736, 740, "Human-centric Foundry UI", F_SANS, 30, WHITE, bold=True)
    s.text(x, 778, 740,
           "Gantt timelines and morale briefs so contractors feel oriented "
           "without meetings.",
           F_SANS, 24, "#A6A6A6", line=1.36)
    s.text(x, 864, 740, "→  agents need state machines, not status decks",
           F_MONO, 19, MAGENTA, track=0.02)

    s.vrule(896, 386, 556, WHITE, 0.16, 1.0)

    # ---- right: keep
    x = 960
    s.rect(x, 386, 26, 26, fill=GREEN)
    label(s, x + 44, 386, 500, "KEEP", GREEN, 20, 0.22)
    s.text(x, 424, 800, "Four computational primitives", F_DISPLAY, 40, WHITE, track=-0.01)

    items = [
        ("01", "Typed I/O contracts",
         "Sub-agents as typed functions. Downstream ingests the schema — never the upstream reasoning."),
        ("02", "Automated team composition",
         "STRIPS pre/post-conditions compile a custom DAG instead of a hardcoded pipeline."),
        ("03", "Structured handoffs & leadership",
         "Stateless async artifact transfer, with explicit escalation when inputs break."),
        ("04", "Dynamic elasticity (fork / join)",
         "Instant parallel fan-out for multi-perspective work, then merge-back synthesis."),
    ]
    y = 502
    for num, t, d in items:
        s.text(x, y - 4, 70, num, F_DISPLAY, 34, GREEN, track=-0.02)
        s.text(x + 78, y - 2, 780, t, F_SANS, 28, WHITE, bold=True)
        s.text(x + 78, y + 38, 780, d, F_SANS, 21, "#9E9E9E", line=1.30)
        y += 122
        if num != "04":
            s.rule(x, y - 26, 856, WHITE, 0.12, 1.0)

    s.notes = (
        "DISMISS THE DEAD WEIGHT FIRST (0:00) — Half of the 2014 paper solved human "
        "coordination friction: recruiting at $25–$30 an hour, surviving contractor "
        "dropouts across timezones, and rendering Gantt charts in Foundry so humans "
        "didn't need status meetings. Throw all of that away. An agent abandonment is "
        "just an HTTP timeout and a retry.\n\n"
        "THE FOUR SURVIVORS (0:40) — Keep the four computational bones. One: typed I/O "
        "blocks, so downstream workers consume clean schemas and never upstream "
        "chain-of-thought sludge. Two: STRIPS-style precondition/postcondition planning "
        "that synthesizes DAGs dynamically. Three: structured handoffs with distributed "
        "leadership. Four: dynamic fork/join elasticity.\n\n"
        "BEAT SHEET — 75s total. Do not read the bullets; the deck already has them. "
        "Say the trade loudly once, then move."
    )
    return s


# ------------------------------------------------------------------ 03
def slide3():
    s = Slide(3, "Deterministic verification gates")
    s.frame("THE 2014 BLIND SPOT", "03 / 06")

    eyebrow(s, M, 148, "CLOSING THE GAP")
    headline(s, 186, "Deterministic verification\nat every boundary", 74, WHITE, w=1200, line=1.02)

    s.rect(M, 376, 8, 74, fill=YELLOW)
    s.text(M + 34, 372, 1180,
           "Typed handoffs without deterministic gates\njust accelerate cascading hallucination.",
           F_DISPLAY, 40, YELLOW, line=1.18, track=-0.005)
    s.text(M + 34, 480, 1100,
           "The FlashHandoff law.  2014 trusted a human expert to notice a broken "
           "handoff; a stochastic model will not.",
           F_SANS, 22, "#9E9E9E", line=1.3)

    # ---------------- gate diagram
    gy, gh = 556, 104
    # upstream
    card(s, M, gy, 300, gh)
    label(s, M + 24, gy + 22, 260, "UPSTREAM BLOCK", WHITE, 18, 0.16)
    s.text(M + 24, gy + 50, 260, "typed planai.Task\n+ git commit", F_MONO, 19, "#C9C9C9", line=1.3)

    arrow_h(s, M + 310, 548, gy + gh // 2, WHITE, 0.5)

    # gate
    s.rect(560, gy - 14, 372, gh + 28, fill="#121200", line=YELLOW, lw=2.0)
    s.text(584, gy + 2, 320, "DETERMINISTIC GATE", F_MONO, 19, YELLOW, track=0.16, caps=True)
    s.text(584, gy + 36, 330, "tests · AST + secret scan\n· PolicyGuardian A–M",
           F_SANS, 21, "#DCDCDC", line=1.32)

    arrow_h(s, 942, 1108, gy + gh // 2, WHITE, 0.5)

    card(s, 1118, gy, 330, gh)
    label(s, 1142, gy + 22, 280, "DOWNSTREAM / MERGE", WHITE, 18, 0.16)
    s.text(1142, gy + 50, 280, "state advances only\non exit_code == 0", F_MONO, 19, "#C9C9C9", line=1.3)

    # fail path
    s.arrow(746, gy + gh + 16, 746, 736, YELLOW, 0.75, 1.8, 10, dashed=True)
    s.rect(560, 744, 372, 72, fill="#140E00", line=YELLOW, lw=1.2)
    s.text(584, 760, 330, "FORCE_REVISION  →  round r+1", F_MONO, 19, YELLOW, track=0.06)
    s.text(584, 788, 330, "structured critique, not a chat log", F_SANS, 19, "#9E9E9E")

    # return path
    s.arrow(552, 780, 262, 780, YELLOW, 0.55, 1.6, 9, dashed=True)
    s.arrow(254, 774, 254, gy + gh + 6, YELLOW, 0.55, 1.6, 9, dashed=True)

    # ---------------- three checks
    cy = 884
    s.rule(M, cy - 26, W - 2 * M, WHITE, 0.14, 1.0)
    checks = [
        ("test_command", "real execution inside an isolated\nGit worktree · exit_code == 0"),
        ("reality + secret scan", "AST & diff reality, blocks placeholder\nstubs and leaked credentials"),
        ("PolicyGuardian", "risk categories A–M vetted\npre-commit, before state advances"),
    ]
    cx = M
    for name, desc in checks:
        s.text(cx, cy, 520, name, F_MONO, 20, YELLOW, track=0.10)
        s.text(cx, cy + 30, 520, desc, F_SANS, 21, "#A8A8A8", line=1.3)
        cx += 560

    s.notes = (
        "THE WALL (0:00) — Most multi-agent frameworks today reinvent Flash Teams badly "
        "and hit a wall. Why? Because in 2014, when an upstream designer handed off a "
        "broken wireframe, a human engineer implicitly spotted the nonsense.\n\n"
        "STOCHASTIC TRAP (0:20) — Models don't. They will pass a syntactically valid "
        "Pydantic object full of hallucinated imports, silent regressions, placeholder "
        "stubs, or leaked credentials — and the downstream agent will dutifully build "
        "on top of the lie.\n\n"
        "THE LAW (0:40) — Typed handoffs are necessary, not sufficient. Every block "
        "boundary needs a deterministic compiler, test runner, and policy analyser: "
        "VerificationGateWorker in teamwork_graph.py, run_reality_and_secret_scan and "
        "run_shell_test_command in single_workflow_graph.py, and PolicyGuardian's A–M "
        "risk categories in jetski_runtime.py.\n\n"
        "BEAT SHEET — 60s. This is the hinge of the talk: slides 4 and 5 are only "
        "credible because this gate exists."
    )
    return s


# ------------------------------------------------------------------ 04
def slide4():
    s = Slide(4, "Pillar I — handoffs & leadership")
    s.frame("AUTOPLAN  ·  PILLAR I", "04 / 06")

    eyebrow(s, M, 148, "STRUCTURED HANDOFFS")
    headline(s, 186, "Distributed leadership,\nzero shared transcripts", 70, WHITE, w=1240, line=1.02)
    s.text(M, 330, 1200,
           "Typed artifacts travel forward; explicit escalation travels backward. "
           "No worker ever ingests another worker's reasoning.",
           F_SANS, 24, "#A6A6A6", line=1.34)

    # ---------------- chain
    cy, ch = 500, 104
    nodes = [
        ("LEAD PLANNER", "PlanAILeadPlannerLLMWorker", 300),
        ("FAN-OUT", "SubtaskFanOutWorker", 260),
        ("CLI WORKERS", "SubAgentDirectiveTask", 260),
        ("GATE + CRITIC", "VerificationGate · CriticWorker", 330),
        ("CHIEF OF STAFF", "ChiefOfStaff", 250),
    ]
    gap = 26
    x = M
    xs = []
    for title, sub, w in nodes:
        accent = YELLOW if "CHIEF" in title else None
        card(s, x, cy, w, ch, accent=accent)
        label(s, x + 20, cy + 22, w - 40, title, WHITE, 17, 0.14)
        s.text(x + 20, cy + 52, w - 40, sub, F_MONO, 14, "#8E8E8E", line=1.28)
        xs.append((x, w))
        x += w + gap

    for i in range(len(nodes) - 1):
        arrow_h(s, xs[i][0] + xs[i][1] + 3, xs[i + 1][0] - 3, cy + ch // 2, WHITE, 0.42, head=8)

    # return path for FORCE_REVISION
    s.arrow(1660, cy - 40, 200, cy - 40, YELLOW, 0.55, 1.6, 9, dashed=True)
    s.arrow(200, cy - 40, 200, cy - 6, YELLOW, 0.55, 1.6, 9, dashed=True)
    s.text(700, cy - 74, 700, "FORCE_REVISION  ·  Trajectory.revert_to_step",
           F_MONO, 17, YELLOW, track=0.10, caps=True)

    # ---------------- three columns
    ty = 668
    s.rule(M, ty - 30, W - 2 * M, WHITE, 0.14, 1.0)
    cols = [
        ("TYPED STATELESS HANDOFFS",
         "ProjectContextTask → TeamPlanTask → SubAgentDirectiveTask",
         "The directive carries only objective, base branch and disjoint owned_paths. "
         "The return is a SubAgentResultTask: commit_sha, changed_files, unified diff."),
        ("DISTRIBUTED LEADERSHIP",
         "compute_service_fitness · Board · CriticWorker",
         "Lead Planner weights roles by empirical pass rates; Board enforces "
         "single-coordinator channel cursors; CriticWorker audits blind spots; "
         "ChiefOfStaff runs landing tests and merges to main."),
        ("ESCALATION OVER APPEND",
         "FORCE_REVISION · Trajectory.revert_to_step",
         "A failing or underspecified artifact re-enters round r+1 on the same branch "
         "with a concise delta note, not another thousand-token transcript."),
    ]
    cx = M
    for i, (h, mono, d) in enumerate(cols):
        s.text(cx, ty, 500, f"0{i+1}", F_DISPLAY, 30, YELLOW, track=-0.02)
        label(s, cx, ty + 46, 500, h, WHITE, 19, 0.16)
        s.text(cx, ty + 80, 500, mono, F_MONO, 15, YELLOW, line=1.34)
        s.text(cx, ty + 132, 500, d, F_SANS, 21, "#A2A2A2", line=1.36)
        cx += 560

    s.notes = (
        "STATELESS CONTEXT TRANSFER (0:00) — In AutoPlan, sub-agents share zero "
        "conversation memory. SubtaskFanOutWorker emits a SubAgentDirectiveTask "
        "containing only the role objective, the repo base branch, and disjoint "
        "owned_paths. When the worker finishes it returns a SubAgentResultTask — a "
        "verifiable commit SHA, a changed-file list, and a concise summary. Never its "
        "internal reasoning trace.\n\n"
        "DISTRIBUTED LEADERSHIP (0:35) — Authority is split across specialised leaders: "
        "PlanAILeadPlannerLLMWorker assigns roles weighted by empirical service pass "
        "rates; jetski_runtime.Board enforces single-coordinator channel cursors; "
        "CriticWorker runs adversarial blind-spot review; ChiefOfStaff autonomously runs "
        "landing tests and merges approved branches.\n\n"
        "ESCALATION OVER APPEND (1:05) — When an artifact is underspecified or fails "
        "review, POST /api/planai/workflows/<id>/gate triggers FORCE_REVISION with "
        "optional Trajectory.revert_to_step rollback, routing a concise delta note into "
        "round r+1 on the same branch.\n\n"
        "BEAT SHEET — 90s. Point at the dotted line when you say FORCE_REVISION."
    )
    return s


# ------------------------------------------------------------------ 05
def slide5():
    s = Slide(5, "Pillar II — dynamic elasticity")
    s.frame("AUTOPLAN  ·  PILLAR II", "05 / 06")

    eyebrow(s, M, 148, "DYNAMIC ELASTICITY")
    headline(s, 186, "Fork / join across worktrees", 70, WHITE, w=1500, line=1.02)
    s.text(M, 276, 1300,
           "Sub-second spin-up turns the 2014 crowd's human branching into parallel "
           "worktree fan-out — with deterministic merge-back.",
           F_SANS, 24, "#A6A6A6", line=1.34)

    # ---------------- fan-out diagram
    bh, mid = 96, 480
    top = mid - bh // 2

    card(s, M, top, 240, bh)
    label(s, M + 18, top + 20, 204, "CONTEXT", WHITE, 16, 0.14)
    s.text(M + 18, top + 46, 204, "decide_spawn", F_MONO, 18, "#C9C9C9")

    card(s, 392, top, 250, bh)
    label(s, 410, top + 20, 214, "FAN-OUT", WHITE, 16, 0.14)
    s.text(410, top + 46, 214, "SubAgentHub · max 128", F_MONO, 16, "#C9C9C9")

    lanes = [("subagent_1", "Claude · backend"), ("subagent_2", "Codex · frontend"),
             ("subagent_N", "Gemini · tests")]
    for i, (n, r) in enumerate(lanes):
        yy = 372 + i * 76
        s.rect(700, yy, 310, 64, fill="#0E0E0E", line=WHITE, lw=1.0)
        s.text(718, yy + 9, 274, n, F_MONO, 18, WHITE)
        s.text(718, yy + 34, 274, r, F_SANS, 17, "#8E8E8E")
        s.arrow(646, mid, 696, yy + 32, WHITE, 0.34, 1.4, 7)

    card(s, 1056, top, 250, bh)
    label(s, 1074, top + 20, 214, "JOIN", WHITE, 16, 0.14)
    s.text(1074, top + 46, 214, "TeamSynthesisJoiner", F_MONO, 18, "#C9C9C9")

    card(s, 1352, top, 250, bh, accent=YELLOW)
    label(s, 1370, top + 20, 214, "GATE", WHITE, 16, 0.14)
    s.text(1370, top + 46, 214, "VerificationGate", F_MONO, 18, "#C9C9C9")

    arrow_h(s, M + 244, 388, mid, WHITE, 0.42, head=8)
    for i in range(3):
        s.arrow(1014, 372 + i * 76 + 32, 1052, mid, WHITE, 0.30, 1.3, 6)
    arrow_h(s, 1310, 1348, mid, WHITE, 0.42, head=8)

    s.text(700, 604, 310, "isolated git worktree\n+ claim_ownership lock", F_MONO, 15, "#6E6E6E", line=1.4)
    s.text(1056, 604, 300, "ProvenanceChain · --no-ff\n→ team/<id>/integrated", F_MONO, 15, "#6E6E6E", line=1.4)

    # ---------------- three columns
    ty = 706
    s.rule(M, ty - 34, W - 2 * M, WHITE, 0.14, 1.0)
    cols = [
        ("ON-DEMAND FORK",
         "decide_spawn evaluates complexity in microseconds; SubtaskFanOutWorker mutates "
         "the live SvelteFlow graph and spawns subagent_1..N lanes."),
        ("FILESYSTEM ISOLATION",
         "Every MultiAgentDispatchWorker provisions its own worktree and takes an SQLite "
         "ownership lock before running a single command."),
        ("RECURSIVE ELASTICITY",
         "The same primitive fans critiques across planner, triage and critic in "
         "AutoplanPromptEvolutionGraph, joining into .agents/skills."),
    ]
    cx = M
    for i, (h, d) in enumerate(cols):
        s.text(cx, ty, 500, f"0{i+1}", F_DISPLAY, 30, YELLOW, track=-0.02)
        label(s, cx, ty + 46, 500, h, WHITE, 19, 0.16)
        s.text(cx, ty + 82, 500, d, F_SANS, 22, "#A2A2A2", line=1.38)
        cx += 560

    s.notes = (
        "ON-DEMAND FORK (0:00) — Where Foundry needed 15–30 minutes to recruit parallel "
        "human contractors, AutoPlan's decide_spawn evaluates task complexity in "
        "microseconds and SubtaskFanOutWorker dynamically mutates the live SvelteFlow "
        "graph — spawning parallel subagent_1..N lanes through SubAgentHub up to 128 "
        "concurrent workers.\n\n"
        "FILESYSTEM ISOLATION (0:35) — Parallel agents fail if they stomp on the same "
        "working tree. Each forked MultiAgentDispatchWorker provisions its own Git "
        "worktree (_prepare_subagent_worktree) and acquires an SQLite ownership lock "
        "(claim_ownership) before running a single command.\n\n"
        "PROVENANCE JOIN + EVOLUTION (1:05) — TeamSynthesisJoiner tracks PlanAI "
        "ProvenanceChain lineage, merges every passing worktree --no-ff into "
        "team/<id>/integrated, and flags cross-lane conflicts deterministically. We "
        "reuse the exact fork/join primitive in AutoplanPromptEvolutionGraph: fan out "
        "failure traces across planner, triage and critic, join them with "
        "EvolutionCritiqueJoiner into versioned .agents/skills and CONTENT_DIFF "
        "memories.\n\n"
        "BEAT SHEET — 90s. The live graph behind you should be forking while you talk."
    )
    return s


# ------------------------------------------------------------------ 06
def slide6():
    s = Slide(6, "Synthesis & demo cue")
    s.frame("LONG LIVE FLASHTEAMS", "06 / 06")

    eyebrow(s, M, 148, "SYNTHESIS")
    headline(s, 186, "FlashTeams is dead.\nLong live FlashHandoff.", 74, WHITE, w=1300, line=1.02)

    rows = [
        ("WORKER POOL", "Upwork / oDesk contractors, $25–$30/hr",
         "Ephemeral multi-model CLI sub-agents, tokens/ms"),
        ("BLOCK CONTRACT", "Prose brief + uploaded deliverable",
         "planai.Task Pydantic schema + git commit SHA"),
        ("CONTEXT TRANSFER", "Shared project brief + handoff note",
         "Zero shared chat · verifiable diff + Board cursor"),
        ("ELASTICITY", "~18-hour human parallel branches",
         "Sub-second worktree fork/join, JoinedTaskWorker"),
        ("BOUNDARY TRUST", "Implicit human sanity check",
         "VerificationGate + PolicyGuardian + CriticWorker"),
    ]
    ty = 378
    colx = (M, 620, 1180)
    label(s, colx[0], ty, 400, "DIMENSION", DIM, 16, 0.18)
    label(s, colx[1], ty, 540, "STANFORD FOUNDRY  ·  UIST 2014", DIM, 16, 0.18)
    label(s, colx[2], ty, 600, "AUTOPLAN FLASHHANDOFF  ·  2026", YELLOW, 16, 0.18)
    s.rule(M, ty + 30, W - 2 * M, WHITE, 0.30, 1.0)

    y = ty + 44
    for i, (dim, old, new) in enumerate(rows):
        s.text(colx[0], y + 8, 460, dim, F_MONO, 19, "#B0B0B0", track=0.10, caps=True)
        s.text(colx[1], y + 4, 520, old, F_SANS, 22, "#7C7C7C", line=1.26)
        s.text(colx[2], y + 4, 600, new, F_SANS, 22, "#EDEDED", line=1.26)
        y += 68
        s.rule(M, y - 16, W - 2 * M, WHITE, 0.12 if i < 4 else 0.30, 1.0)

    # takeaway
    s.rect(M, 758, 8, 96, fill=YELLOW)
    s.text(M + 34, 754, 1620,
           "Stop building multi-agent systems as giant group chats. Keep stateless typed "
           "handoffs and elastic fork/join DAGs, then replace human boundary judgement "
           "with deterministic gates.",
           F_DISPLAY, 28, WHITE, line=1.26, track=-0.004)

    # live workbench callout — three columns of the running app
    label(s, M, 852, 700, "LIVE DEMO  ·  POST /API/PLANAI/TEAMWORK", YELLOW, 15, 0.18)
    panels = [
        ("PROJECT RAIL", "goal, run history,\npaused workflows"),
        ("LIVE FORK / JOIN DAG", "SvelteFlow lanes, x2\nrevision badges"),
        ("GATE REVIEW", "diff + PolicyGuardian,\ntrajectory revert"),
    ]
    px, pw, gap = M, 552, 20
    for name, desc in panels:
        s.rect(px, 882, pw, 88, fill="#0C0C0C", line=WHITE, lw=1.0)
        s.text(px + 18, 898, pw - 36, name, F_MONO, 16, WHITE, track=0.14, caps=True)
        s.text(px + 18, 924, pw - 36, desc, F_SANS, 17, "#8E8E8E", line=1.28)
        px += pw + gap

    s.notes = (
        "THESIS (0:00) — Group chats don't ship software; typed DAGs with deterministic "
        "gates do. The 2014 contribution was never the crowd — it was the decomposition, "
        "the handoff contract, and the elasticity.\n\n"
        "TRANSITION TO DEMO (0:20) — Everything on this slide is running right now in the "
        "AutoPlan workbench: project rail on the left, live fork/join DAG in the centre, "
        "gate review and trajectory revert on the right.\n\n"
        "LIVE DEMO CUE (final 30s on stage) —\n"
        "1. Dispatch a multi-agent teamwork goal (POST /api/planai/teamwork) and watch "
        "SubtaskFanOutWorker fork parallel worktree lanes live in SvelteFlow.\n"
        "2. Inspect the TeamSynthesisJoiner → VerificationGateWorker → CriticWorker "
        "handoff bundle: commit SHAs, unified diff, PolicyGuardian score, zero chat "
        "transcript.\n"
        "3. Trigger FORCE_REVISION (the x2 cyclic badge) or APPROVE, and watch "
        "ChiefOfStaff merge onto main while AutoplanPromptEvolutionGraph distils the run "
        "into .agents/skills.\n\n"
        "CLOSE — Long live FlashTeams: not the crowd, the architecture."
    )
    return s


def all_slides():
    return [slide1(), slide2(), slide3(), slide4(), slide5(), slide6()]

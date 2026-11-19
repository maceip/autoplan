"""The eleven slides."""
from __future__ import annotations

import os
import patterns
from theme import *
from layout import Slide, headline, subhead, kicker, text_width, wrap, T_MICRO, T_NANO

HERE = os.path.dirname(os.path.abspath(__file__))


def pat(hue, w, h, **kw):
    return patterns.get(hue, patterns.PALETTE[hue], w, h, **kw)


def fit(sl: Slide, x, y, w, s, size, font=F_DISPLAY, color=INK, track=-0.02,
        line=1.0):
    """Display type that shrinks until it fits its column."""
    while size > 12 and text_width(s, font, size, track) > w:
        size -= 1
    return sl.text(x, y, w, s, font, size, color, track=track, line=line, explicit=True)


def header(sl: Slide, kick: str, head: str, sub: str = "", hsize=62,
           sub_w=1240, gap=50):
    """Standard slide head. Returns the y where content may start."""
    sl.frame(kick)
    sl.text(M, 112, CW, head, F_DISPLAY, hsize, INK, line=1.03, track=-0.018)
    y = 112 + hsize * 1.03 * (head.count("\n") + 1) + 20
    if sub:
        t = sl.text(M, y, sub_w, sub, F_SANS, 24, DIM, line=1.44)
        y += t.h
    return y + gap


def on_line(sl: Slide, x, y, w, s, color=LIME, size=15, pad=12):
    """A mono caption that knocks a gap in the rule it sits on."""
    t = sl.text(x + pad, y - size * 0.62, w, s, F_MONO, size, color,
                track=0.10, caps=True)
    sl.rect(x, y - 1.5, t.widest + pad * 2, 3, fill=BLACK)
    return t


# =====================================================================  01
def s01():
    sl = Slide(1, "Title")
    sl.rect(0, 0, W, H, fill=BLACK)
    sl.pic(pat("lime", 930, 1080), 990, 0, 930, 1080)

    sl.text(M, 40, 760, "STANFORD UIST 2014  →  AUTOPLAN 2026", F_MONO, T_MICRO,
            DIM, track=0.17, caps=True)
    sl.text(W - M - 120, 40, 120, "01", F_MONO, T_MICRO, DIM, track=0.17, align="r")

    fit(sl, M, 146, 850, "FlashHandoff", 122, track=-0.032)
    sl.rule(M, 316, 540, WHITE, 0.30)
    sl.text(M, 344, 840, "FlashTeams is Dead.", F_DISPLAY, 52, INK, line=1.12, track=-0.012)
    sl.text(M, 406, 840, "Long live FlashTeams.", F_DISPLAY, 52, LIME, line=1.12, track=-0.012)

    sl.text(M, 494, 790,
            "Ten years ago Retelny et al. shipped an Android app in eighteen hours "
            "with a crowd of strangers. The crowd is gone. The question isn't.",
            F_SANS, 24, DIM, line=1.46)

    sl.rule(M, 786, 800, WHITE, 0.16)
    rows = [("MYTH", "Mechanical Turk microtaskers building an Android app.", DIM, DIMMER),
            ("REAL", "oDesk / Upwork specialists at $25–30/hr, eighteen-hour sprints.", DIM, DIMMER),
            ("LIVE", "The crowd died. The architecture survived.", INK, LIME)]
    y = 810
    for i, (k, v, col, kcol) in enumerate(rows):
        sl.text(M, y + 3, 130, k, F_MONO, 15, kcol, track=0.17, caps=True)
        sl.text(M + 140, y, 660, v, F_SANS, 21, col, line=1.4)
        y += 62
        if i < 2:
            sl.rule(M, y - 16, 800, WHITE, 0.10)

    sl.notes = (
        "OPEN — Ten years ago at UIST 2014, Stanford's Flash Teams asked how you scale reliable "
        "software engineering out of ephemeral strangers. They built an Android app in about "
        "eighteen hours.\n\n"
        "CORRECTION — It is usually misremembered as Mechanical Turk microtasking. Retelny et al. "
        "coordinated skilled oDesk/Upwork specialists at $25–30 an hour.\n\n"
        "PIVOT — The human crowd layer is dead: frontier models spin up in milliseconds. So why "
        "read a 2014 crowd-computing paper today? Because a single frontier model given a 40-step "
        "engineering goal fails for the same reason a solo contractor fails — context dilution, "
        "instruction drift, compounding error. Bounded, stateless roles are how you stop the drift.\n\n"
        "BEAT — 60s. Land on the question, not the answer."
    )
    return sl


# =====================================================================  02
def s02():
    sl = Slide(2, "The 10-year audit")
    y = header(sl, "01 / THE 10-YEAR AUDIT  ·  STANFORD UIST 2014",
               "Obsolete friction vs. enduring primitives",
               "Foundry spent half its effort on human coordination. Contemporary agent frameworks "
               "rebuild its four computational primitives — and keep the coordination too.",
               hsize=58, sub_w=1330)

    grid_top = y + 6
    grid_h = 536
    slot = grid_h / 3

    # ---------------------------------------------------------- discard
    x, cw = M, 452
    sl.rect(x, grid_top, 10, 10, fill=MAGENTA)
    sl.text(x + 22, grid_top - 3, 300, "DISCARD", F_MONO, T_MICRO, MAGENTA,
            track=0.18, caps=True)

    dead = [
        ("Labor & latency", "Recruiting at $25–30/hr, timezones, dropouts, "
                            "eighteen-hour turnarounds.", "Now: a timeout and a retry."),
        ("Human-centric UI", "Gantt charts and onboarding briefs so contractors felt "
                             "oriented without a meeting.", "Agents do not need to feel oriented."),
        ("The crowd itself", "Strangers assembled on demand, then dissolved back into "
                             "the marketplace.", "Spin-up is now a function call."),
    ]
    for i, (h, b, mono) in enumerate(dead):
        ty = grid_top + 40 + i * slot
        sl.text(x, ty, cw, h, F_SANS, 27, INK, bold=True, line=1.24)
        sl.text(x, ty + 40, cw, b, F_SANS, 19, DIM, line=1.44)
        sl.text(x, ty + 130, cw, mono, F_MONO, 16, MAGENTA, line=1.4)
        if i < 2:
            sl.rule(x, ty + slot - 34, cw, WHITE, 0.12)

    sl.vrule(600, grid_top - 2, grid_h + 24, WHITE, 0.14)

    # ---------------------------------------------------------- keep
    kx, kw = 648, 1184
    sl.rect(kx, grid_top, 10, 10, fill=GREEN)
    sl.text(kx + 22, grid_top - 3, 300, "KEEP", F_MONO, T_MICRO, GREEN, track=0.18, caps=True)

    keep = [
        ("01", "Typed I/O contracts",
         "A sub-agent is a typed function. Downstream reads the schema, never the reasoning.",
         "planai.Task", BLUE),
        ("02", "Dynamic composition",
         "Pre- and post-conditions compile a DAG per goal instead of one hardcoded pipeline.",
         "STRIPS → DAG", ORANGE),
        ("03", "Structured handoffs",
         "Artifacts move forward. Escalations come back. No shared transcript.",
         "SubAgentDirectiveTask", GREEN),
        ("04", "Fork / join",
         "Parallel branches on isolated worktrees, merged deterministically.",
         "best-of-N", PURPLE),
    ]
    cwid = kw // 2 - 16
    for i, (n, t, d, tag, hue) in enumerate(keep):
        cx = kx + (i % 2) * (kw // 2 + 16)
        cy = grid_top + 34 + (i // 2) * (grid_h // 2 - 12)
        sl.card(cx, cy, cwid, 244, fill=CARD_NEUTRAL, accent=hue)
        sl.text(cx + 26, cy + 24, 60, n, F_DISPLAY, 28, hue, track=-0.02, explicit=True)
        sl.text(cx + 26, cy + 68, cwid - 52, t, F_SANS, 25, INK, bold=True, line=1.24)
        sl.text(cx + 26, cy + 108, cwid - 52, d, F_SANS, 19, DIM, line=1.46)
        sl.text(cx + 26, cy + 202, cwid - 52, tag, F_MONO, 16, hue, track=0.04)

    sl.notes = (
        "DISMISS THE DEAD WEIGHT (0:00) — Half of the 2014 paper solved human coordination: "
        "recruiting at $25–30 an hour, contractor dropouts across timezones, Gantt charts so humans "
        "did not need status meetings. Throw all of it away. An agent abandonment is an HTTP timeout.\n\n"
        "THE FOUR SURVIVORS (0:45) — Keep the computational bones. One: typed I/O, so downstream "
        "workers consume clean schemas and never upstream chain-of-thought sludge. Two: STRIPS-style "
        "pre/post-conditions that synthesize a DAG instead of a hardcoded pipeline. Three: structured "
        "handoffs with distributed leadership. Four: fork/join elasticity.\n\n"
        "BEAT — 75s. Say the trade loudly once, then move."
    )
    return sl


# =====================================================================  03
def s03():
    sl = Slide(3, "The evidence")
    y = header(sl, "02 / THE EVIDENCE  ·  19,528 PROMPTS  ·  976 SESSIONS",
               "Nine services. One failure pattern.",
               "A year of this operator's typed prompts across every major agent CLI. 1,863 of them "
               "are the human catching the agent. Six months of switching vendors moved none of it.",
               hsize=58, sub_w=1260)

    rows = [
        ("Looping on the same error", 441, "2.3%"),
        ("Two agents colliding", 281, "1.4%"),
        ("Scope / order violation", 277, "1.4%"),
        ("False completion", 236, "1.2%"),
        ("Stalled on the human", 231, "1.2%"),
        ("Told correctly, defied", 210, "1.1%"),
        ("Misled by false info", 167, "0.9%"),
        ("Lost context, restarted", 138, "0.7%"),
    ]
    top = y + 24
    rowh = 58
    barx, barmax = 462, 396
    for i, (name, n, pct) in enumerate(rows):
        yy = top + i * rowh
        sl.text(M, yy + 9, 350, name, F_MONO, 16, INK if i == 0 else DIM, track=0.02)
        sl.rect(barx, yy + 12, barmax, 14, fill="#26262E")
        sl.rect(barx, yy + 12, barmax * (n / 441), 14, fill=LIME if i == 0 else "#6E6E7C")
        sl.text(barx + barmax + 22, yy + 9, 90, str(n), F_MONO, 16, INK, track=0.02)
        sl.text(barx + barmax + 112, yy + 9, 80, pct, F_MONO, 16, DIMMER, track=0.02)

    sl.text(M, top + 8 * rowh + 16, 760,
            "COUNTS ARE LOWER BOUNDS  ·  OPERATOR-SIDE TEXT ONLY",
            F_MONO, T_NANO, FAINT, track=0.16, caps=True)

    # ---------------------------------------------------------- right rail
    rx, rw = 1096, 736
    sl.rule(rx, top + 4, rw, WHITE, 0.16)
    stats = [
        ("51%", "of sessions contain at least one breakdown.", LIME),
        ("20%", "of sessions hold 79% of every breakdown prompt.", INK),
        ("0.61", "median detection point for false completion — the latest of any category.", INK),
    ]
    for i, (big, cap, col) in enumerate(stats):
        sy = top + 26 + i * 118
        sl.text(rx, sy, 200, big, F_DISPLAY, 60, col, track=-0.02, explicit=True)
        sl.text(rx + 216, sy + 12, rw - 216, cap, F_SANS, 20, DIM, line=1.44)
        if i:
            sl.rule(rx, sy - 20, rw, WHITE, 0.10)

    sl.rule(M, 898, CW, LIME, 0.55, 1.2)
    sl.text(M, 916, CW, "Vendor choice is not the variable. Supervision structure is.",
            F_DISPLAY, 34, INK, track=-0.012)

    sl.notes = (
        "THE EVIDENCE (0:00) — Before the architecture, the reason for it. 19,528 operator-typed "
        "prompts across 976 sessions and nine agent services, May to November 2026. 1,863 of those "
        "prompts — 9.5% — are the human catching the agent doing something wrong.\n\n"
        "CONCENTRATION (0:35) — Breakdowns are not spread evenly. 20% of sessions hold 79% of them. "
        "Most pain lives in a minority of sessions that go wrong repeatedly.\n\n"
        "LATENCY (0:55) — The median breakdown prompt sits at the halfway point of its session. "
        "False completion is detected latest — at 0.61 — because the agent reports success and the "
        "human only finds out later. Detection latency, not error rate, is the cost driver.\n\n"
        "THE POINT (1:15) — Monthly shares are flat to rising across every category. Six months of "
        "tool switching did not reduce breakdown rates. The durable layer is supervision structure, "
        "not vendor choice."
    )
    return sl


# =====================================================================  04
def s04():
    sl = Slide(4, "The law")
    y = header(sl, "03 / THE 2014 BLIND SPOT",
               "Deterministic verification at every boundary",
               "In 2014 a human engineer caught a broken wireframe by reading it. A model reads a "
               "schema-valid lie and builds on it.",
               hsize=58, sub_w=1260, gap=34)

    # ---------------------------------------------------------- the law
    sl.rect(M, y - 4, 8, 112, fill=LIME)
    sl.text(M + 34, y - 8, 1500,
            "Typed handoffs without deterministic gates\njust accelerate cascading hallucination.",
            F_DISPLAY, 38, LIME, line=1.20, track=-0.008)
    sl.text(M + 34, y + 96, 1500,
            "THE FLASHHANDOFF LAW  ·  2014 assumed a human would catch a broken handoff.",
            F_MONO, 15, DIMMER, track=0.12, caps=True)

    # ---------------------------------------------------------- diagram
    dy, dh = y + 210, 120
    sl.card(M, dy, 316, dh, fill=CARD_NEUTRAL)
    sl.text(M + 24, dy + 22, 270, "UPSTREAM BLOCK", F_MONO, 15, DIMMER, track=0.16, caps=True)
    sl.text(M + 24, dy + 50, 270, "typed planai.Task\n+ git commit", F_MONO, 17, INK, line=1.36)

    sl.arrow(M + 322, dy + dh // 2, M + 382, dy + dh // 2, WHITE, 0.45, 1.5, 9)

    gx, gw, gh = M + 390, 404, dh + 40
    sl.pic(pat("lime", gw, gh, contrast=0.16), gx, dy - 20, gw, gh)
    sl.text(gx + 24, dy + 6, 356, "DETERMINISTIC GATE", F_MONO, 15, BLACK, track=0.18, caps=True)
    sl.text(gx + 24, dy + 34, 360, "tests  ·  AST + secret scan\n·  PolicyGuardian A–M",
            F_SANS, 20, BLACK, line=1.42, bold=True)

    sl.arrow(gx + gw + 8, dy + dh // 2, gx + gw + 66, dy + dh // 2, WHITE, 0.45, 1.5, 9)

    dx = gx + gw + 74
    sl.card(dx, dy, 300, dh, fill=CARD_NEUTRAL)
    sl.text(dx + 24, dy + 22, 252, "DOWNSTREAM / MERGE", F_MONO, 15, DIMMER, track=0.16, caps=True)
    sl.text(dx + 24, dy + 50, 252, "state advances only\non exit_code == 0", F_MONO, 17, INK, line=1.36)

    # fail path
    fy = dy + dh + 96
    sl.arrow(gx + gw // 2, dy + dh + 4, gx + gw // 2, fy - 4, LIME, 0.6, 1.6, 9, dashed=True)
    sl.rect(gx, fy, gw, 84, fill="#15160A", line=LIME, lw=1.0)
    sl.text(gx + 24, fy + 16, 356, "FORCE_REVISION  →  round r+1", F_MONO, 17, LIME, track=0.06)
    sl.text(gx + 24, fy + 46, 356, "a structured critique, not a chat log", F_SANS, 18, DIM)
    sl.arrow(gx - 6, fy + 42, M + 158, fy + 42, LIME, 0.55, 1.5, 9, dashed=True)
    sl.arrow(M + 158, fy + 36, M + 158, dy + dh + 4, LIME, 0.55, 1.5, 9, dashed=True)

    # ---------------------------------------------------------- checks
    cy = fy + 118
    sl.rule(M, cy - 24, CW, WHITE, 0.14)
    checks = [
        ("test_command", "Real execution inside an isolated Git worktree. Nothing advances on a "
                         "self-report."),
        ("reality + secret scan", "AST and diff reality check. Blocks placeholder stubs, mocked "
                                  "paths, leaked credentials."),
        ("PolicyGuardian A–M", "Thirteen risk categories vetted before commit, not after merge."),
    ]
    cwid = 548
    for i, (n, d) in enumerate(checks):
        cx = M + i * (cwid + 50)
        sl.text(cx, cy, cwid, n, F_MONO, 17, LIME, track=0.10)
        sl.text(cx, cy + 28, cwid, d, F_SANS, 19, DIM, line=1.46)

    sl.notes = (
        "BRIDGE — Four bones survived. This is the one the paper never wrote down.\n\n"
        "THE WALL (0:00) — Most multi-agent frameworks reinvent Flash Teams badly and hit a wall. "
        "In 2014, when an upstream designer handed off a broken wireframe, a human engineer spotted "
        "the nonsense.\n\n"
        "STOCHASTIC TRAP (0:25) — Models do not. They will pass a syntactically valid Pydantic object "
        "full of hallucinated imports, silent regressions, placeholder stubs or leaked credentials, "
        "and the downstream agent will dutifully build on the lie.\n\n"
        "THE LAW (0:50) — Typed handoffs are necessary, not sufficient. Every block boundary needs a "
        "deterministic compiler, test runner and policy analyser: VerificationGateWorker in "
        "teamwork_graph.py, run_reality_and_secret_scan and run_shell_test_command in "
        "single_workflow_graph.py, PolicyGuardian's A–M categories in jetski_runtime.py.\n\n"
        "BEAT — 60s. This is the hinge: the next slides are only credible because this gate exists."
    )
    return sl


# =====================================================================  05
def s05():
    sl = Slide(5, "The machine")
    y = header(sl, "04 / THE MACHINE  ·  AUTOPLAN FLASHHANDOFF",
               "Four primitives, one loop.",
               "Compose a typed plan, fork it across isolated worktrees, gate every artifact, merge "
               "only what passes. Everything else is implementation detail.",
               hsize=58, sub_w=1300, gap=56)

    cy, ch = y + 58, 104
    stations = [
        (M, 150, "GOAL", "one sentence", None),
        (268, 234, "PLAN", "PlanAILeadPlanner", None),
        (534, 196, "FAN OUT", "decide_spawn", None),
        (1160, 216, "JOIN", "TeamSynthesisJoiner", None),
        (1408, 200, "GATE", "VerificationGate", LIME),
        (1640, 192, "MERGE", "ChiefOfStaff", None),
    ]
    for (sx, sw, t, sub, accent) in stations:
        sl.card(sx, cy, sw, ch, fill=CARD_NEUTRAL, accent=accent)
        sl.text(sx + 20, cy + 24, sw - 36, t, F_MONO, 15, INK, track=0.16, caps=True)
        sl.text(sx + 20, cy + 54, sw - 36, sub, F_MONO, 14, DIMMER, line=1.34)

    for (a, aw), (b, bw) in [((M, 150), (268, 234)), ((268, 234), (534, 196)),
                             ((1160, 216), (1408, 200)), ((1408, 200), (1640, 192))]:
        sl.arrow(a + aw + 5, cy + ch // 2, b - 7, cy + ch // 2, WHITE, 0.4, 1.4, 8)

    # lanes inside a container
    lx, lw = 786, 330
    sl.rect(lx - 16, cy - 132, lw + 32, 288, line=WHITE, lw=1.0, alpha=0.10)
    lanes = [("subagent_1", "Claude · backend", BLUE, cy - 100),
             ("subagent_2", "Codex · frontend", ORANGE, cy),
             ("subagent_N", "Gemini · tests", GREEN, cy + 100)]
    for name, role, hue, ly in lanes:
        sl.card(lx, ly, lw, 80, fill=CARD_NEUTRAL)
        sl.rect(lx, ly, 5, 80, fill=hue)
        sl.text(lx + 22, ly + 16, lw - 40, name, F_MONO, 16, hue)
        sl.text(lx + 22, ly + 44, lw - 40, role, F_SANS, 17, DIM)
        sl.arrow(738, cy + ch // 2, lx - 20, ly + 40, WHITE, 0.26, 1.2, 7)
        sl.arrow(lx + lw + 20, ly + 40, 1152, cy + ch // 2, WHITE, 0.26, 1.2, 7)

    sl.text(lx - 16, cy + 176, lw + 32, "one worktree each  ·  disjoint owned_paths",
            F_MONO, 14, FAINT)

    # return path
    ry = cy + ch + 118
    sl.arrow(1508, cy + ch + 4, 1508, ry - 4, LIME, 0.5, 1.5, 9, dashed=True)
    sl.arrow(1502, ry, 384, ry, LIME, 0.5, 1.5, 9, dashed=True)
    sl.arrow(380, ry + 6, 380, cy + ch + 4, LIME, 0.5, 1.5, 9, dashed=True)
    on_line(sl, 700, ry, 720, "FORCE_REVISION  ·  round r+1  ·  revert_to_step")

    # invariants
    iy = ry + 62
    sl.rule(M, iy, CW, WHITE, 0.14)
    inv = [
        ("TYPED", "A Pydantic Task at every edge. Prose is not a contract."),
        ("DISJOINT", "One worktree, one ownership lock, no file clobbering."),
        ("GATED", "exit_code == 0 or the round is rejected."),
        ("PROVENANCED", "Commit SHA plus lineage. Never a transcript."),
    ]
    iw = CW // 4
    for i, (k, v) in enumerate(inv):
        cx = M + i * iw
        sl.text(cx, iy + 30, iw - 44, k, F_MONO, 15, LIME, track=0.18, caps=True)
        sl.text(cx, iy + 58, iw - 44, v, F_SANS, 19, DIM, line=1.44)

    sl.notes = (
        "THE MAP (0:00) — Here is the whole machine in one line. A goal becomes a typed plan, the "
        "plan fans out into isolated worktrees, every artifact crosses a deterministic gate, and "
        "only what passes merges.\n\n"
        "FOUR INVARIANTS (0:40) — Typed: a Pydantic Task at every edge, prose is not a contract. "
        "Disjoint: one worktree and one ownership lock per worker. Gated: exit_code == 0 or the round "
        "is rejected. Provenanced: a commit SHA and lineage, never a transcript.\n\n"
        "THE RETURN EDGE (1:10) — The dotted line is the part most frameworks omit. A failed gate "
        "does not append a complaint to a chat; it reverts to round r+1 on the same branch with a "
        "concise delta note.\n\n"
        "BEAT — 60s. Point at the four invariants; the next two slides zoom into two of them."
    )
    return sl


# =====================================================================  06
def s06():
    sl = Slide(6, "Pillar I")
    y = header(sl, "05 / PILLAR I  ·  STRUCTURED HANDOFFS",
               "Distributed leadership,\nzero shared transcripts",
               "Artifacts go forward. Escalations come back. No worker ever reads another worker's "
               "reasoning.", hsize=54, sub_w=1180, gap=58)

    cy, ch = y + 22, 96
    nodes = [("LEAD PLANNER", "PlanAILeadPlannerLLMWorker", 330),
             ("FAN-OUT", "SubtaskFanOutWorker", 296),
             ("CLI WORKERS", "SubAgentDirectiveTask", 296),
             ("GATE + CRITIC", "VerificationGate · CriticWorker", 400),
             ("CHIEF OF STAFF", "ChiefOfStaff", 310)]
    gap = 28
    x = M
    spans = []
    hues = [BLUE, PURPLE, GREEN, ORANGE, MAGENTA]
    for i, (t, sub, w) in enumerate(nodes):
        sl.card(x, cy, w, ch, fill=CARD_NEUTRAL, accent=hues[i])
        sl.text(x + 20, cy + 26, w - 36, t, F_MONO, 15, INK, track=0.14, caps=True)
        sl.text(x + 20, cy + 54, w - 36, sub, F_MONO, 13, DIMMER, line=1.36)
        spans.append((x, w))
        x += w + gap

    for i in range(len(nodes) - 1):
        sl.arrow(spans[i][0] + spans[i][1] + 5, cy + ch // 2,
                 spans[i + 1][0] - 7, cy + ch // 2, WHITE, 0.38, 1.4, 8)

    ry = cy - 46
    lastx = spans[-1][0] + spans[-1][1] // 2
    sl.arrow(lastx, cy - 6, lastx, ry + 4, LIME, 0.5, 1.5, 8, dashed=True)
    sl.arrow(lastx - 6, ry, spans[0][0] + 40, ry, LIME, 0.5, 1.5, 8, dashed=True)
    sl.arrow(spans[0][0] + 40, ry + 6, spans[0][0] + 40, cy - 6, LIME, 0.5, 1.5, 8, dashed=True)
    on_line(sl, spans[0][0] + 120, ry, 620, "FORCE_REVISION  ·  revert_to_step")

    # ---------------------------------------------------------- columns
    ty = cy + ch + 78
    sl.rule(M, ty - 30, CW, WHITE, 0.14)
    cols = [
        ("TYPED STATELESS HANDOFFS",
         "ProjectContextTask → TeamPlanTask → SubAgentDirectiveTask",
         "The directive carries only the objective, the base branch and disjoint owned_paths. "
         "The return is a SubAgentResultTask: commit_sha, changed_files, unified diff."),
        ("DISTRIBUTED LEADERSHIP",
         "compute_service_fitness · Board · CriticWorker",
         "The lead planner weights roles by empirical pass rates. Board enforces one coordinator "
         "per channel. The critic audits blind spots before the chief lands anything."),
        ("ESCALATION OVER APPEND",
         "FORCE_REVISION · revert_to_step",
         "A failing artifact re-enters round r+1 on the same branch with a concise delta note, "
         "not another thousand-token transcript."),
    ]
    cw = 544
    for i, (h, mono, d) in enumerate(cols):
        cx = M + i * (cw + 48)
        sl.text(cx, ty, 60, f"0{i+1}", F_DISPLAY, 26, LIME, track=-0.02, explicit=True)
        sl.text(cx + 62, ty + 2, cw - 62, h, F_MONO, 15, INK, track=0.14, caps=True)
        sl.text(cx, ty + 42, cw, mono, F_MONO, 14, LIME, line=1.44)
        sl.text(cx, ty + 104, cw, d, F_SANS, 19, DIM, line=1.48)

    # ---------------------------------------------------------- purple band
    by = 872
    sl.rect(M, by, CW, 122, fill=PURPLE)
    sl.text(M + 28, by + 20, 900, "COMMUNICATION  ·  NUCLEUS + BOARD (BAND LAYER)",
            F_MONO, 15, "#2A1F52", track=0.16, caps=True)
    sl.text(M + 28, by + 48, 1120,
            "Agents find each other, divide disjoint owned_paths, and hand off verified commits.",
            F_SANS, 21, "#1A1333", line=1.36)
    sl.text(M + 1180, by + 44, 520,
            "One macOS app coordinates\nClaude, Codex and Gemini at once.",
            F_SANS, 19, "#2A1F52", line=1.42)

    sl.notes = (
        "BRIDGE — Every boundary has a gate. The next question is what crosses it.\n\n"
        "STATELESS TRANSFER (0:00) — Sub-agents share zero conversation memory. SubtaskFanOutWorker "
        "emits a SubAgentDirectiveTask carrying only the role objective, the repo base branch and "
        "disjoint owned_paths. The worker returns a SubAgentResultTask: a verifiable commit SHA, a "
        "changed-file list, a concise summary. Never its reasoning trace.\n\n"
        "DISTRIBUTED LEADERSHIP (0:35) — PlanAILeadPlannerLLMWorker assigns roles weighted by "
        "empirical service pass rates. jetski_runtime.Board enforces single-coordinator channel "
        "cursors. CriticWorker runs adversarial blind-spot review. ChiefOfStaff runs landing tests "
        "and merges.\n\n"
        "ESCALATION OVER APPEND (1:05) — A failing artifact triggers FORCE_REVISION with optional "
        "Trajectory.revert_to_step, routing a delta note into round r+1 on the same branch.\n\n"
        "BEAT — 90s. Point at the dotted line when you say FORCE_REVISION."
    )
    return sl


# =====================================================================  07
def s07():
    sl = Slide(7, "Pillar II")
    y = header(sl, "06 / PILLAR II  ·  DYNAMIC ELASTICITY",
               "Fork / join across worktrees",
               "The crowd branched in hours. Agents branch in milliseconds. Merging is still the "
               "hard part.", hsize=58, sub_w=1180, gap=64)

    mid = y + 118
    bh = 104
    top = mid - bh // 2

    sl.card(M, top, 210, bh, fill=CARD_NEUTRAL)
    sl.text(M + 20, top + 24, 174, "CONTEXT", F_MONO, 15, DIMMER, track=0.16, caps=True)
    sl.text(M + 20, top + 52, 174, "decide_spawn", F_MONO, 16, INK)

    sl.card(352, top, 236, bh, fill=CARD_NEUTRAL)
    sl.text(372, top + 24, 200, "FAN-OUT", F_MONO, 15, DIMMER, track=0.16, caps=True)
    sl.text(372, top + 52, 200, "SubAgentHub ≤ 128", F_MONO, 16, INK)

    lanes = [("subagent_1", "Claude · backend", BLUE, top - 112),
             ("subagent_2", "Codex · frontend", ORANGE, top),
             ("subagent_N", "Gemini · tests", GREEN, top + 112)]
    lx, lw = 676, 340
    sl.rect(lx - 16, top - 140, lw + 32, 300, line=WHITE, lw=1.0, alpha=0.10)
    for name, role, hue, ly in lanes:
        sl.card(lx, ly, lw, 88, fill=CARD_NEUTRAL)
        sl.rect(lx, ly, 5, 88, fill=hue)
        sl.text(lx + 22, ly + 18, lw - 40, name, F_MONO, 16, hue)
        sl.text(lx + 22, ly + 48, lw - 40, role, F_SANS, 17, DIM)
        sl.arrow(596, mid, lx - 20, ly + 44, WHITE, 0.26, 1.2, 7)
        sl.arrow(lx + lw + 20, ly + 44, 1108, mid, WHITE, 0.26, 1.2, 7)

    sl.card(1116, top, 240, bh, fill=CARD_NEUTRAL)
    sl.text(1136, top + 24, 204, "JOIN", F_MONO, 15, DIMMER, track=0.16, caps=True)
    sl.text(1136, top + 52, 204, "TeamSynthesisJoiner", F_MONO, 15, INK)

    sl.card(1400, top, 200, bh, fill=CARD_NEUTRAL, accent=LIME)
    sl.text(1420, top + 24, 164, "GATE", F_MONO, 15, DIMMER, track=0.16, caps=True)
    sl.text(1420, top + 52, 164, "VerificationGate", F_MONO, 15, INK)

    sl.arrow(1364, mid, 1394, mid, WHITE, 0.4, 1.4, 8)
    sl.text(1400, top + bh + 20, 360, "→ team/<id>/integrated  ·  --no-ff", F_MONO, 14, FAINT)

    # ---------------------------------------------------------- columns
    ty = top + 300
    sl.rule(M, ty, CW, WHITE, 0.14)
    cols = [
        ("ON-DEMAND FORK",
         "decide_spawn evaluates complexity in microseconds and mutates the live SvelteFlow graph, "
         "spawning subagent_1..N lanes."),
        ("FILESYSTEM ISOLATION",
         "Every MultiAgentDispatchWorker provisions its own worktree and takes an SQLite ownership "
         "lock before running one command."),
        ("RECURSIVE ELASTICITY",
         "The same primitive fans critiques across planner, triage and critic, joining into "
         "versioned .agents/skills."),
    ]
    cw = 544
    for i, (h, d) in enumerate(cols):
        cx = M + i * (cw + 48)
        sl.text(cx, ty + 26, 60, f"0{i+1}", F_DISPLAY, 26, LIME, track=-0.02, explicit=True)
        sl.text(cx + 62, ty + 28, cw - 62, h, F_MONO, 15, INK, track=0.14, caps=True)
        sl.text(cx, ty + 72, cw, d, F_SANS, 19, DIM, line=1.48)

    by = 872
    sl.rect(M, by, CW, 122, fill=PURPLE)
    sl.text(M + 28, by + 20, 900, "MEMORY  ·  SHARED EVOLUTION GRAPH",
            F_MONO, 15, "#2A1F52", track=0.16, caps=True)
    sl.text(M + 28, by + 48, 1120,
            "Every search, trajectory and gate decision lands in one graph, distilled into "
            "CONTENT_DIFF memories.",
            F_SANS, 21, "#1A1333", line=1.36)
    sl.text(M + 1180, by + 44, 520,
            "Reusable .agents/skills\nthat every agent reads back.",
            F_SANS, 19, "#2A1F52", line=1.42)

    sl.notes = (
        "BRIDGE — One planner, one fan-out. Now let the fan-out run at the same time.\n\n"
        "ON-DEMAND FORK (0:00) — Where Foundry needed 15–30 minutes to recruit parallel contractors, "
        "decide_spawn evaluates complexity in microseconds and SubtaskFanOutWorker mutates the live "
        "SvelteFlow graph, spawning parallel lanes through SubAgentHub up to 128 concurrent workers.\n\n"
        "FILESYSTEM ISOLATION (0:35) — Parallel agents fail if they stomp the same working tree. Each "
        "forked MultiAgentDispatchWorker provisions its own worktree and takes a SQLite ownership "
        "lock before running a single command.\n\n"
        "PROVENANCE JOIN (1:05) — TeamSynthesisJoiner tracks ProvenanceChain lineage, merges every "
        "passing worktree --no-ff into team/<id>/integrated, and flags cross-lane conflicts "
        "deterministically.\n\n"
        "RECURSIVE REUSE (1:25) — The same primitive runs in AutoplanPromptEvolutionGraph: fan out "
        "failure traces across planner, triage and critic, join into versioned skills.\n\n"
        "BEAT — 90s. The live graph behind you should be forking while you talk."
    )
    return sl


# =====================================================================  08
def s08():
    sl = Slide(8, "Frontier check")
    y = header(sl, "07 / FRONTIER CHECK  ·  ANTIGRAVITY 2.0 JETSKI",
               "Check the frontier.",
               "We took apart Antigravity's agent runtime — internal name Jetski — to see which of "
               "the four primitives actually shipped.", hsize=58, sub_w=1240, gap=46)

    cols = (M, M + 76, M + 452, W - M - 190)
    ty = y + 6
    for cx, cwid, lab, col in [(cols[0], 60, "#", DIMMER),
                               (cols[1], 360, "FLASH TEAMS  ·  2014", DIMMER),
                               (cols[2], 900, "JETSKI  ·  WHAT THE BINARY DOES", LIME),
                               (cols[3], 180, "STATUS", DIMMER)]:
        sl.text(cx, ty, cwid, lab, F_MONO, 14, col, track=0.16, caps=True)
    sl.rule(M, ty + 30, CW, WHITE, 0.28)

    rows = [
        ("01", "Typed I/O contracts",
         "SubagentSpec{Role, SystemPrompt, Workspace} + typed stage_artifact file",
         "Only the artifact crosses the boundary, never the upstream reasoning trace.",
         "SHIPPED", GREEN),
        ("02", "Automated composition",
         "Stage DAG · goal_template · decide_spawn table · re-partition past 32 nodes",
         "A language model compiles the graph from a template; no planner derives it.",
         "PARTIAL", ORANGE),
        ("03", "Structured handoffs",
         "HandoffStep / HandbackStep / ReviewStep + handoff.md, BRIEFING.md",
         "Escalation ladder Retry → Replace → Degrade; self-succession at 16 spawns.",
         "SHIPPED", GREEN),
        ("04", "Dynamic elasticity",
         "Battle Mode best-of-N · ForkConversation · swarm lanes 1/3/5/9",
         "Tournament tree [32,16,8,5,1]; invoke_subagent dispatches in batches of 16.",
         "SHIPPED", GREEN),
    ]
    ry = ty + 52
    for i, (n, name, mono, desc, status, col) in enumerate(rows):
        sl.text(cols[0], ry + 2, 60, n, F_DISPLAY, 22, DIMMER, track=-0.02, explicit=True)
        sl.text(cols[1], ry, 360, name, F_SANS, 23, INK, bold=True, line=1.24)
        sl.text(cols[2], ry - 2, 900, mono, F_MONO, 15, INK, line=1.38)
        sl.text(cols[2], ry + 24, 900, desc, F_SANS, 18, DIM, line=1.40)
        sl.rect(cols[3], ry + 6, 10, 10, fill=col)
        sl.text(cols[3] + 20, ry, 160, status, F_MONO, 14, col, track=0.14)
        ry += 110
        sl.rule(M, ry - 26, CW, WHITE, 0.10 if i < 3 else 0.28)

    sl.rect(M, 862, 8, 100, fill=LIME)
    sl.text(M + 34, 858, 1620,
            "Three of four shipped. The missing one is the interesting one: Jetski builds its "
            "pipeline from a prompt template and a spawn heuristic. No planner derives it.",
            F_DISPLAY, 26, INK, line=1.30, track=-0.006)

    sl.notes = (
        "BRIDGE — That is our stack. Time to check it against someone else's.\n\n"
        "FRAME (0:00) — Flash Teams proposed four mechanisms for assembling ephemeral expert teams. "
        "We reverse-engineered the Antigravity agent runtime — internal name Jetski — and three of "
        "the four are in production under different names.\n\n"
        "1. TYPED I/O (0:15) — SubagentSpec carries Role, SystemPrompt and Workspace; stage output "
        "is a typed file consumed via {stage_artifact.<stage_name>} substitution. Only the artifact "
        "crosses the boundary.\n\n"
        "2. STRIPS PLANNING (0:40) — The honest gap. Pipeline templates define a stage DAG with "
        "goal_template; decide_spawn implements the When-to-Spawn table; teamwork_layer re-partitions "
        "past 32 nodes. DAG synthesis exists, but a language model compiles it from a template — no "
        "planner derives it. Say this plainly.\n\n"
        "3. STRUCTURED HANDOFFS (1:05) — HandoffStep / HandbackStep / ReviewStep with handoff.md and "
        "BRIEFING.md as shared state, an escalation ladder Retry → Replace → Degrade, self-succession "
        "at 16 spawns.\n\n"
        "4. FORK / JOIN (1:25) — Battle Mode is best-of-N with ForkConversation and per-arm workspace "
        "clones. Swarm lanes sized 1/3/5/9, tournament tree [32,16,8,5,1], batch-16 dispatch.\n\n"
        "BEAT — 90s. Do not oversell: three of four, and the missing one is the planner."
    )
    return sl


# =====================================================================  09
def s09():
    sl = Slide(9, "Live demo")
    y = header(sl, "08 / LIVE  ·  NUCLEUS MACOS WORKBENCH",
               "Structured handoff, in the app.",
               "A native macOS coordinator running fork/join, critic review and gate approval.",
               hsize=58, sub_w=1100, gap=40)

    vx, vy, vw = M, y + 6, 1000
    vh = int(vw * 9 / 16)
    sl.rect(vx - 1, vy - 1, vw + 2, vh + 2, line=WHITE, lw=1.0, alpha=0.18)
    sl.video(os.path.join(HERE, "media", "nucleus_demo.mp4"),
             os.path.join(HERE, "media", "poster.png"), vx, vy, vw, vh)
    sl.text(vx, vy + vh + 18, vw, "NUCLEUS.APP  ·  127.0.0.1:5051  ·  FLASHHANDOFF-DEMO",
            F_MONO, 14, FAINT, track=0.14, caps=True)

    cx, cw = 1140, 692
    items = [
        ("01", "DESKTOP MULTI-AGENT SPLIT",
         "Nucleus coordinates Antigravity and Xiaomi-MiMo lanes in isolated Git worktrees on "
         "flashhandoff-demo."),
        ("02", "TYPED ARTIFACT SYNTHESIS",
         "TeamSynthesisJoiner merges SubAgentResultTask commits --no-ff, then runs "
         "VerificationGateWorker."),
        ("03", "CRITIC, THEN GATE",
         "CriticWorker flags blind spots on greet.py and test_farewell. You either request revision "
         "or approve the merge."),
    ]
    yy = vy
    for i, (n, h, d) in enumerate(items):
        sl.text(cx, yy, 46, n, F_DISPLAY, 24, LIME, track=-0.02, explicit=True)
        sl.text(cx + 52, yy + 2, cw - 52, h, F_MONO, 15, INK, track=0.14, caps=True)
        t = sl.text(cx + 52, yy + 32, cw - 52, d, F_SANS, 20, DIM, line=1.46)
        yy += 44 + t.h + 40
        if i < 2:
            sl.rule(cx, yy - 28, cw, WHITE, 0.10)

    sl.rect(cx, 892, cw, 88, fill="#15160A", line=LIME, lw=1.0)
    sl.text(cx + 24, 910, cw - 48, "REQUEST REVISION  →  FORCE_REVISION  ·  round r+1",
            F_MONO, 15, LIME, track=0.08)
    sl.text(cx + 24, 938, cw - 48, "or APPROVE & MERGE  →  ChiefOfStaff lands on main",
            F_SANS, 17, DIM)

    sl.notes = (
        "LIVE DEMO (0:00) — Everything on the last six slides is running in this window. Left rail: "
        "projects. Centre: the live fork/join DAG. Right: the gate review bundle.\n\n"
        "WHAT TO WATCH (0:20) —\n"
        "1. Dispatch a multi-agent goal and watch SubtaskFanOutWorker fork worktree lanes live in "
        "SvelteFlow.\n"
        "2. Inspect the handoff bundle: commit SHAs, unified diff, PolicyGuardian score, zero chat "
        "transcript.\n"
        "3. Trigger FORCE_REVISION on the x2 cyclic badge, or approve, and watch ChiefOfStaff merge "
        "onto main.\n\n"
        "FALLBACK — If the live app fails, the recording on this slide carries the same three beats. "
        "Narrate it exactly as if it were live; do not apologise for the recording.\n\n"
        "BEAT — 2–3 min. Stop talking for the merge."
    )
    return sl


# =====================================================================  10
def s10():
    sl = Slide(10, "What still breaks")
    y = header(sl, "09 / WHAT STILL BREAKS",
               "Where this still fails",
               "A system that hides its own failure modes is a demo. These are the five that remain.",
               hsize=58, sub_w=1240, gap=40)

    items = [
        ("01", "THE CHIEF IS A SINGLE POINT OF FAILURE",
         "One process triages, verifies and lands. A bad test command produces confident, "
         "well-organised wrong landings at scale."),
        ("02", "THE GRAPH SHOWS STRUCTURE, NOT TRUTH",
         "A green node means a task completed, not that the work is real. Colour must never imply "
         "a verification the chief did not perform."),
        ("03", "ADAPTERS OBSERVE MORE THAN THEY CONTROL",
         "For services without a verified headless mode we see breakdowns sooner. We still cannot "
         "prevent in-session defiance."),
        ("04", "QUEUE OVERLOAD RECREATES THE DISEASE",
         "If leads generate review items faster than one human clears them, batch approval becomes "
         "rubber-stamping."),
        ("05", "SECRETS FLOW TOWARD THE QUEUE",
         "Intake centralises exactly the text operators paste carelessly. Without scanning at "
         "intake, the queue becomes the most sensitive file on the machine."),
    ]
    ry = y + 8
    for i, (n, h, d) in enumerate(items):
        sl.text(M, ry, 56, n, F_DISPLAY, 24, FAINT, track=-0.02, explicit=True)
        sl.text(M + 70, ry + 4, 700, h, F_MONO, 15, LIME, track=0.13, caps=True)
        sl.text(M + 70, ry + 34, 1560, d, F_SANS, 20, DIM, line=1.46)
        ry += 118
        sl.rule(M, ry - 22, CW, WHITE, 0.10)

    sl.rule(M, 900, CW, LIME, 0.55, 1.2)
    sl.text(M, 918, CW, "The win so far is detection latency. It is not yet error rate.",
            F_DISPLAY, 34, INK, track=-0.012)

    sl.notes = (
        "HONESTY BEAT (0:00) — Every one of these is in the design doc, not discovered on stage.\n\n"
        "1. THE CHIEF — One process triages, verifies and lands. That concentration is the price of "
        "deterministic landing. Mitigations: append-only events, hash-bound approvals, restart "
        "recovery. None remove the risk.\n\n"
        "2. THE GRAPH — PlanAI Editor renders structure beautifully. A green graph can still sit on "
        "staged evidence. If node colour ever implies verification the chief did not perform, the "
        "visualisation is actively misleading.\n\n"
        "3. ADAPTERS — Observe-only services are seen, not stopped. Early phases reduce detection "
        "latency far more than error rate.\n\n"
        "4. QUEUE OVERLOAD — If leads generate review items faster than one operator clears them, "
        "batch approval becomes rubber-stamping and detachment returns inside the sanctioned tool.\n\n"
        "5. SECRETS — The queue centralises the text operators paste carelessly. Live credentials "
        "appear in the corpus.\n\n"
        "BEAT — 60s. Do not rush this one; it buys the credibility for the close."
    )
    return sl


# =====================================================================  11
def s11():
    sl = Slide(11, "Synthesis")
    y = header(sl, "10 / SYNTHESIS",
               "FlashTeams is dead. Long live FlashHandoff.",
               "The 2014 contribution was never the crowd. It was the decomposition, the handoff "
               "contract and the elasticity.", hsize=56, sub_w=1300, gap=44)

    cards = [
        ("COMMUNICATION", "Nucleus + Board",
         "Agents find each other, divide disjoint owned_paths, hand off verified diffs."),
        ("ELASTICITY", "Fork / Join DAG",
         "decide_spawn forks up to 128 worktrees in milliseconds; JoinedTaskWorker merges --no-ff."),
        ("VERIFICATION", "Boundary Gates",
         "Per-worktree tests, AST and secret scans, PolicyGuardian A–M, FORCE_REVISION."),
        ("MEMORY & SKILLS", "Evolution Graph",
         "Every search, trajectory and gate decision distilled into CONTENT_DIFF and skills."),
    ]
    cw = 412
    cy = y + 4
    for i, (k, h, d) in enumerate(cards):
        cx = M + i * (cw + 32)
        sl.rect(cx, cy, cw, 214, fill=PURPLE)
        sl.text(cx + 24, cy + 24, cw - 48, k, F_MONO, 14, "#2A1F52", track=0.16, caps=True)
        sl.text(cx + 24, cy + 52, cw - 48, h, F_DISPLAY, 26, "#140F2B", line=1.14, track=-0.012)
        sl.text(cx + 24, cy + 100, cw - 48, d, F_SANS, 17, "#241B45", line=1.44)

    # ---------------------------------------------------------- ledger
    ly = cy + 250
    sl.rule(M, ly, CW, WHITE, 0.22)
    for lab, hx, hw in [("DIMENSION", M, 340), ("STANFORD FOUNDRY  ·  2014", 470, 460),
                        ("AUTOPLAN FLASHHANDOFF  ·  2026", 1000, 700)]:
        sl.text(hx, ly + 14, hw, lab, F_MONO, 13, DIMMER, track=0.16, caps=True)
    sl.rule(M, ly + 40, CW, WHITE, 0.10)

    rows = [
        ("WORKER POOL", "Upwork / oDesk specialists, $25–30/hr",
         "Multi-model CLI agents, tokens and milliseconds"),
        ("BLOCK CONTRACT", "Prose brief + uploaded deliverable",
         "planai.Task schema + commit SHA"),
        ("CONTEXT", "Shared brief and handoff note",
         "Zero shared chat · verifiable diff + Board cursor"),
        ("TRUST", "Implicit human sanity check",
         "VerificationGate + PolicyGuardian + CriticWorker"),
    ]
    ry = ly + 58
    for i, (d, old, new) in enumerate(rows):
        sl.text(M, ry, 360, d, F_MONO, 14, DIM, track=0.14, caps=True)
        sl.text(470, ry - 3, 480, old, F_SANS, 20, "#6E6E78", line=1.30)
        sl.text(1000, ry - 3, 740, new, F_SANS, 20, INK, line=1.30)
        ry += 64
        if i < 3:
            sl.rule(M, ry - 16, CW, WHITE, 0.08)

    # ---------------------------------------------------------- close
    sl.pic(pat("lime", 1920, 112, contrast=0.14), 0, 968, 1920, 112)
    sl.text(M, 990, 1420,
            "Stop building multi-agent systems as group chats. Keep the typed handoffs and the "
            "fork/join. Put a gate where the human used to stand.",
            F_DISPLAY, 22, BLACK, line=1.26, track=-0.006)
    sl.text(W - M - 420, 998, 420, "DEMO  ·  POST /API/PLANAI/TEAMWORK",
            F_MONO, 13, "#2A2800", track=0.12, caps=True, align="r")

    sl.notes = (
        "THESIS (0:00) — Group chats do not ship software; typed DAGs with deterministic gates do. "
        "The 2014 contribution was never the crowd — it was the decomposition, the handoff contract "
        "and the elasticity.\n\n"
        "THE FOUR (0:20) — Communication, elasticity, verification, memory. Four purple squares: that "
        "is the whole agent stack.\n\n"
        "THE LEDGER (0:45) — Read one row out loud, not four. Worker pool is the row that lands.\n\n"
        "CLOSE — Long live FlashTeams: not the crowd, the architecture.\n\n"
        "BEAT — 45s, then stop. Do not take questions on this slide."
    )
    return sl


def all_slides():
    return [s01(), s02(), s03(), s04(), s05(), s06(), s07(), s08(), s09(), s10(), s11()]

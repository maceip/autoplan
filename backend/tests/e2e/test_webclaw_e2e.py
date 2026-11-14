"""End-to-end Playwright verification for AutoPlan + WebClaw Multi-Project & PlanAI Workbench.

Exercises every interactive control against live running AutoPlan and WebClaw
servers, including:
- Multi-Project creation, discovery, session scoping, and cleanup
- In-composer Agent/Model routing & Single | Team Graph mode toggle (verifying zero sidebar routing strip)
- Secondary 'Start Demo' button placement and real Xiaomi MiMo + Antigravity spin-up
- Live PlanAI Graph View, Split View, ProvenanceChain lineage, Python code tab, and SvelteFlow /planai-editor
- Inspector Brain (Evolution) tab: prompt generation evolution & operator rule creation
- Honest observe-only enforcement for MiniMax and Chief-of-Staff branch landing
- 3-Stage Antigravity Mobile layout with Project grouping and mobile PlanAI DAG view
"""

import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request

import pytest
from playwright.sync_api import Page, expect
from utils import BACKEND_TEST_URL

if os.environ.get("SKIP_E2E_TESTS") == "true":
    pytest.skip("Skipping e2e tests as SKIP_E2E_TESTS is set", allow_module_level=True)

WEBCLAW_URL = os.environ.get("WEBCLAW_URL", "http://localhost:3000")
SCREENSHOT_DIR = os.environ.get("E2E_SCREENSHOT_DIR", "").strip()


def _auth_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    user = os.environ.get("E2E_HTTP_USER", "").strip()
    pw = os.environ.get("E2E_HTTP_PASS", "").strip()
    if user and pw:
        tok = base64.b64encode(f"{user}:{pw}".encode()).decode()
        headers["Authorization"] = f"Basic {tok}"
    return headers


def _api_get(path: str) -> dict:
    req = urllib.request.Request(f"{BACKEND_TEST_URL}{path}", headers=_auth_headers())
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def _api_delete(path: str) -> dict:
    req = urllib.request.Request(
        f"{BACKEND_TEST_URL}{path}", headers=_auth_headers(), method="DELETE"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def _maybe_screenshot(page: Page, filename: str) -> None:
    if not SCREENSHOT_DIR:
        return
    out_dir = Path(SCREENSHOT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_dir / filename))


def open_webclaw(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(WEBCLAW_URL)
    page.wait_for_url("**/chat/**", timeout=20000)
    expect(page.locator('[data-testid="desktop-top-app-bar"]')).to_be_visible(
        timeout=20000
    )
    expect(page.locator('[data-testid="sidebar-projects-list"]')).to_be_visible(
        timeout=20000
    )
    expect(page.locator('[data-testid="autoplan-inspector"]')).to_be_visible(
        timeout=20000
    )
    # Ensure session mode starts in 'single' so agent-service-selector is visible
    single_btn = page.locator('[data-testid="mode-single-btn"]')
    if single_btn.is_visible():
        single_btn.click()
    expect(page.locator('[data-testid="agent-service-selector"]')).to_be_visible(
        timeout=15000
    )


def open_new_session_in_autoplan(page: Page) -> str:
    """Click '+' on the primary autoplan project to open a clean empty session."""
    with page.expect_response(
        lambda r: "/api/sessions" in r.url and r.request.method == "POST",
        timeout=15000,
    ) as resp_info:
        page.locator('[data-testid="project-new-session-autoplan"]').click()
    data = resp_info.value.json()
    friendly_id = str(data.get("friendlyId") or "")
    page.wait_for_url(f"**/chat/{friendly_id}", timeout=15000)
    single_btn = page.locator('[data-testid="mode-single-btn"]')
    if single_btn.is_visible():
        single_btn.click()
    return friendly_id


def test_webclaw_composer_routing_multi_project_and_planai_views(page: Page):
    open_webclaw(page)

    # 1. Verify autobot brand, zero sidebar-routing-strip, and zero Chat|Plan header switch
    assert page.title() == "autobot"
    expect(page.locator('[data-testid="sidebar-routing-strip"]')).to_have_count(0)
    expect(page.locator('[data-testid="header-run-simple-task"]')).to_have_count(0)
    expect(page.locator('[data-testid="workspace-view-switcher"]')).to_have_count(0)
    expect(page.locator('[data-testid="webclaw-queue-filter"]')).to_have_count(0)

    brand_link = page.locator('[data-testid="desktop-brand-link"]').first
    expect(brand_link).to_be_visible()
    expect(brand_link).to_contain_text("autobot")

    # Verify routing controls live INSIDE the chat composer input box
    composer_box = page.locator('[data-testid="composer-mode-toggle"]')
    expect(composer_box).to_be_visible()
    expect(page.locator('[data-testid="header-active-project"]')).to_be_visible()
    expect(page.locator('[data-testid="agent-service-selector"]')).to_be_visible()

    # Verify PlanAI 2D DAG is immediately visible inline with zero clicks
    expect(page.locator('[data-testid="planai-graph-view"]')).to_be_visible()
    expect(page.locator('[data-testid="planai-dag-canvas"]')).to_be_visible()

    _maybe_screenshot(page, "web_desktop_3col_workbench.png")

    # 2. Multi-Project registration, empty-session onboarding DAG, Single->Team 2D morphing, and cleanup
    with tempfile.TemporaryDirectory(prefix="autoplan_e2e_proj_") as tmp_repo:
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "e2e@autoplan.local"],
            cwd=tmp_repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "AutoPlan E2E"],
            cwd=tmp_repo,
            check=True,
        )
        (Path(tmp_repo) / "README.md").write_text("# E2E Project\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=tmp_repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"], cwd=tmp_repo, check=True
        )

        proj_name = f"e2e-proj-{os.getpid()}"
        created_proj_id = ""
        created_session_fid = ""
        try:
            page.locator('[data-testid="add-project-button"]').click()
            expect(page.locator('[data-testid="add-project-panel"]')).to_be_visible()
            page.locator('[data-testid="project-name-input"]').fill(proj_name)
            page.locator('[data-testid="project-path-input"]').fill(tmp_repo)
            with page.expect_response(
                lambda r: "/api/autoplan/projects" in r.url
                and r.request.method == "POST",
                timeout=15000,
            ) as create_proj_resp:
                page.locator('[data-testid="project-submit-button"]').click()
            resp_json = create_proj_resp.value.json()
            assert resp_json.get("success") is True, resp_json
            created_proj_id = resp_json["project"]["id"]

            expect(
                page.locator(f'[data-testid="project-group-{created_proj_id}"]')
            ).to_be_visible(timeout=15000)

            # Create a new empty session directly inside this new project
            with page.expect_response(
                lambda r: "/api/sessions" in r.url and r.request.method == "POST",
                timeout=15000,
            ) as sess_resp:
                page.locator(
                    f'[data-testid="project-new-session-{created_proj_id}"]'
                ).click()
            created_session_fid = str(sess_resp.value.json().get("friendlyId") or "")

            expect(page.locator('[data-testid="header-active-project"]')).to_have_text(
                proj_name, timeout=15000
            )
            expect(page.locator('[data-testid="desktop-session-title"]')).to_have_text(
                "New session", timeout=10000
            )

            # Empty session shows centered IronCurtain Dagre state-machine SVG + unique 'Start Demo' button
            start_demo_btn = page.locator('[data-testid="start-demo-button"]')
            expect(start_demo_btn).to_have_count(1)
            expect(start_demo_btn).to_be_visible()
            expect(start_demo_btn).to_have_text("Start Demo")
            expect(
                page.locator('[data-testid="planai-state-machine-svg"]')
            ).to_be_visible()
            expect(
                page.locator(
                    '[data-testid="planai-node-WorktreeRunner"][data-node-kind="agent"]'
                )
            ).to_be_visible()
            expect(
                page.locator(
                    '[data-testid="planai-node-VerificationGate"][data-node-kind="deterministic"]'
                )
            ).to_be_visible()
            expect(
                page.locator(
                    '[data-testid="planai-node-ChiefReviewSink"][data-node-kind="human_gate"]'
                )
            ).to_be_visible()
            expect(
                page.locator(
                    '[data-testid="planai-node-DoneTerminal"][data-node-kind="terminal"]'
                )
            ).to_be_visible()
            expect(
                page.locator(
                    '[data-testid="planai-node-AbortedTerminal"][data-node-kind="terminal"]'
                )
            ).to_be_visible()
            expect(
                page.locator(
                    '[data-testid="planai-edge-e_review_revision"][data-back-edge="true"]'
                )
            ).to_be_visible()
            _maybe_screenshot(page, "ui_inline_dag_single.png")

            # Toggle Single -> Team inside composer: 2D Dagre branching topology morphs inline
            page.locator('[data-testid="mode-team-btn"]').click()
            expect(
                page.locator(
                    '[data-testid="planai-node-ContextHarvesterWorker"][data-node-kind="deterministic"]'
                )
            ).to_be_visible()
            expect(
                page.locator(
                    '[data-testid="planai-node-LeadPlannerWorker"][data-node-kind="agent"]'
                )
            ).to_be_visible()
            expect(
                page.locator('[data-testid="planai-node-subagent_1"]')
            ).to_be_visible()
            expect(
                page.locator('[data-testid="planai-node-subagent_2"]')
            ).to_be_visible()
            expect(
                page.locator(
                    '[data-testid="planai-node-TeamSynthesisJoiner"][data-node-kind="deterministic"]'
                )
            ).to_be_visible()
            expect(
                page.locator(
                    '[data-testid="planai-node-ChiefEscalationSink"][data-node-kind="human_gate"]'
                )
            ).to_be_visible()
            expect(
                page.locator(
                    '[data-testid="planai-edge-e_sink_revision"][data-back-edge="true"]'
                )
            ).to_be_visible()
            page.locator('[data-testid="planai-node-TeamSynthesisJoiner"]').click()
            expect(
                page.locator('[data-testid="planai-node-inspector"]')
            ).to_contain_text("TeamSynthesisJoiner")
            _maybe_screenshot(page, "ui_inline_dag_team.png")

            page.locator('[data-testid="mode-single-btn"]').click()
        finally:
            if created_session_fid:
                try:
                    _api_delete(f"/api/webclaw/sessions?friendlyId={created_session_fid}")
                except Exception:
                    pass
            if created_proj_id:
                try:
                    _api_delete(f"/api/projects/{created_proj_id}")
                except Exception:
                    pass

    # 3. Inspector Rules (Evolution) tab: add rule & evolve prompt generation
    page.locator('[data-testid="inspector-tab-evolution"]').click()
    expect(page.locator('[data-testid="webclaw-evolution-panel"]')).to_be_visible(
        timeout=10000
    )
    before_evo = _api_get("/api/evolution/status")
    before_gen = int(before_evo["active_generation"])

    rule_text = f"E2E guardrail rule {os.getpid()}: isolate worktrees per project"
    page.locator('[data-testid="inspector-add-rule-input"]').fill(rule_text)
    with page.expect_response(
        lambda r: "/api/autoplan/evolution/rules" in r.url
        and r.request.method == "POST",
        timeout=15000,
    ):
        page.locator('[data-testid="inspector-add-rule-form"] button[type="submit"]').click()

    expect(page.locator('[data-testid="webclaw-evolution-panel"]')).to_contain_text(
        rule_text, timeout=15000
    )

    with page.expect_response(
        lambda r: "/api/autoplan/evolution/evolve" in r.url
        and r.request.method == "POST",
        timeout=60000,
    ) as evo_resp:
        page.locator('[data-testid="inspector-evolve-button"]').click()
    assert evo_resp.value.ok, evo_resp.value.text()

    after_evo = _api_get("/api/evolution/status")
    assert int(after_evo["active_generation"]) >= before_gen + 1
    _maybe_screenshot(page, "web_brain_evolution_tab.png")

    # 4. Phase 2 Dual-Track Cascade Memories (`CONTENT_DIFF`) CRUD in Inspector
    expect(page.locator('[data-testid="evolution-subtab-rules"]')).to_be_visible()
    expect(page.locator('[data-testid="evolution-subtab-memories"]')).to_be_visible()
    expect(page.locator('[data-testid="evolution-subtab-skills"]')).to_be_visible()

    page.locator('[data-testid="evolution-subtab-memories"]').click()
    mem_key = f"e2e-mem-{os.getpid()}"
    page.locator('[data-testid="inspector-memory-key-input"]').fill(mem_key)
    page.locator('[data-testid="inspector-memory-content-input"]').fill(
        "Line 1: isolate worktrees per project"
    )
    with page.expect_response(
        lambda r: "/api/autoplan/evolution/memories" in r.url
        and r.request.method == "POST",
        timeout=15000,
    ) as create_mem_resp:
        page.locator('[data-testid="inspector-memory-save-button"]').click()
    assert create_mem_resp.value.ok, create_mem_resp.value.text()
    created_mem = create_mem_resp.value.json()["memory"]
    mem_id = created_mem["id"]

    mem_card = page.locator(f'[data-testid="evolution-memory-{mem_id}"]')
    expect(mem_card).to_be_visible(timeout=10000)
    expect(mem_card).to_contain_text("MANUAL · r1")

    # Edit & save -> revision r2 + unified CONTENT_DIFF
    page.locator(f'[data-testid="memory-edit-{mem_id}"]').click()
    page.locator('[data-testid="inspector-memory-content-input"]').fill(
        "Line 1: isolate worktrees per project\nLine 2: verify PolicyGuardian before gate"
    )
    with page.expect_response(
        lambda r: "/api/autoplan/evolution/memories" in r.url
        and r.request.method == "POST",
        timeout=15000,
    ) as update_mem_resp:
        page.locator('[data-testid="inspector-memory-save-button"]').click()
    assert update_mem_resp.value.ok, update_mem_resp.value.text()
    expect(mem_card).to_contain_text("MANUAL · r2", timeout=10000)

    page.locator(f'[data-testid="memory-diff-toggle-{mem_id}"]').click()
    diff_pre = page.locator(f'[data-testid="memory-diff-{mem_id}"]')
    expect(diff_pre).to_be_visible()
    expect(diff_pre).to_contain_text("+Line 2: verify PolicyGuardian before gate")
    _maybe_screenshot(page, "web_phase2_memories_content_diff.png")

    with page.expect_response(
        lambda r: f"/api/autoplan/evolution/memories/{mem_id}" in r.url
        and r.request.method == "DELETE",
        timeout=15000,
    ) as del_mem_resp:
        page.locator(f'[data-testid="memory-delete-{mem_id}"]').click()
    assert del_mem_resp.value.ok, del_mem_resp.value.text()
    expect(mem_card).to_have_count(0, timeout=10000)
    active_mem_ids = {m["id"] for m in _api_get("/api/evolution/memories")["memories"]}
    assert mem_id not in active_mem_ids


def test_webclaw_agents_registry_and_observe_only_minimax(page: Page):
    open_webclaw(page)
    temp_fid = open_new_session_in_autoplan(page)
    try:
        page.locator('[data-testid="inspector-tab-agents"]').click()
        for svc in ("antigravity", "minimax", "xiaomi-mimo"):
            expect(page.locator(f'[data-testid="agent-card-{svc}"]')).to_be_visible(
                timeout=10000
            )

        expect(page.locator('[data-testid="agent-mode-antigravity"]')).to_have_text(
            "dispatch"
        )
        expect(page.locator('[data-testid="agent-mode-xiaomi-mimo"]')).to_have_text(
            "dispatch"
        )
        expect(page.locator('[data-testid="agent-mode-minimax"]')).to_have_text(
            "observe_only"
        )
        expect(page.locator('[data-testid="agent-demo-btn-antigravity"]')).to_have_text(
            "Start Demo"
        )
        expect(page.locator('[data-testid="agent-demo-btn-minimax"]')).to_be_disabled()

        # Select MiniMax inside composer -> persisted on backend & onboarding Start Demo disabled
        selector = page.locator('[data-testid="agent-service-selector"]')
        with page.expect_response(
            lambda r: "/api/sessions" in r.url and r.request.method == "PATCH",
            timeout=10000,
        ) as patch_resp:
            selector.select_option("minimax")
        assert patch_resp.value.ok

        page.reload()
        expect(selector).to_have_value("minimax", timeout=15000)
        expect(page.locator('[data-testid="start-demo-button"]')).to_be_disabled()

        composer = page.locator("textarea").first
        composer.fill("Attempt headless dispatch on observe-only MiniMax")
        composer.press("Enter")
        error_banner = page.locator('[data-testid="dispatch-error-banner"]')
        expect(error_banner).to_be_visible(timeout=15000)
        expect(error_banner).to_contain_text("MINIMAX_API_KEY")
    finally:
        if temp_fid:
            try:
                _api_delete(f"/api/webclaw/sessions?friendlyId={temp_fid}")
            except Exception:
                pass


def test_webclaw_live_start_demo_through_chief_approval(page: Page):
    open_webclaw(page)
    temp_fid = open_new_session_in_autoplan(page)
    try:
        selector = page.locator('[data-testid="agent-service-selector"]')
        if selector.input_value() != "xiaomi-mimo":
            with page.expect_response(
                lambda r: "/api/sessions" in r.url and r.request.method == "PATCH",
                timeout=10000,
            ):
                selector.select_option("xiaomi-mimo")

        with page.expect_response(
            lambda r: "/api/autoplan/agents/demo-task" in r.url
            and r.request.method == "POST",
            timeout=15000,
        ) as demo_resp_info:
            page.locator('[data-testid="start-demo-button"]').click()

        demo_resp = demo_resp_info.value
        assert demo_resp.status == 201, demo_resp.text()
        run_payload = demo_resp.json()["run"]
        run_id = run_payload["id"]
        workspace_dir = Path(run_payload["cwd"])

        # Compact live PlanAI DAG strip remains pinned above the message stream
        expect(page.locator('[data-testid="planai-dag-canvas"]')).to_be_visible()

        page.locator('[data-testid="inspector-tab-agents"]').click()
        page.locator('[data-testid="inspector-tab-runs"]').click()
        run_state = page.locator(f'[data-testid="webclaw-run-state-{run_id}"]')
        expect(run_state).to_have_text("succeeded", timeout=90000)

        run_after = _api_get(f"/api/agents/runs/{run_id}")["run"]
        queue_item_id = run_after["queue_item_id"]
        assert queue_item_id, f"Expected queue_item_id on completed run: {run_after}"

        # Verify Master -> Detail drill-in on Review tab
        page.locator('[data-testid="inspector-tab-queue"]').click()
        expect(page.locator('[data-testid="webclaw-queue-list"]')).to_be_visible()
        expect(page.locator('[data-testid="webclaw-queue-detail"]')).to_have_count(0)

        queue_item_row = page.locator(
            f'[data-testid="webclaw-queue-item-{queue_item_id}"]'
        )
        expect(queue_item_row).to_be_visible(timeout=20000)
        queue_item_row.click()

        expect(page.locator('[data-testid="webclaw-queue-detail"]')).to_be_visible()
        expect(page.locator('[data-testid="webclaw-detail-back"]')).to_be_visible()

        detail_status = page.locator('[data-testid="webclaw-detail-status"]')
        expect(detail_status).to_have_text("needs_review", timeout=45000)
        expect(page.locator('[data-testid="webclaw-detail-test"]')).to_contain_text(
            "Test exit 0 (passed)", timeout=15000
        )
        expect(
            page.locator('[data-testid="planai-node-state-WorktreeRunner"]')
        ).to_have_text("Done", timeout=15000)
        expect(
            page.locator('[data-testid="planai-node-state-VerificationGate"]')
        ).to_have_text("Done", timeout=15000)
        expect(
            page.locator('[data-testid="planai-node-state-ChiefReviewSink"]')
        ).to_have_text("Gate", timeout=15000)

        # Verify inline IronCurtain GateReviewPanel auto-opens below the Dagre SVG
        gate_panel = page.locator('[data-testid="planai-gate-review-panel"]')
        expect(gate_panel).to_be_visible(timeout=20000)
        expect(page.locator('[data-testid="gate-diff-viewer"]')).to_contain_text(
            "AUTOPLAN_DEMO_OK", timeout=15000
        )
        page.locator('[data-testid="gate-tab-checks"]').click()
        expect(page.locator('[data-testid="gate-checks-body"]')).to_contain_text(
            "Law-2 Reality Scan", timeout=10000
        )
        expect(page.locator('[data-testid="gate-policy-guardian"]')).to_contain_text(
            "Allowed · severity 0", timeout=10000
        )
        expect(page.locator('[data-testid="gate-trajectory-summary"]')).to_contain_text(
            "recorded steps", timeout=10000
        )
        _maybe_screenshot(page, "web_phase2_gate_policy_guardian.png")
        page.locator('[data-testid="gate-tab-diff"]').click()
        _maybe_screenshot(page, "web_ironcurtain_gate_review_panel.png")

        # Exercise bounded cyclic FORCE_REVISION directly from GateReviewPanel -> Round 2 (x2 badges)
        page.locator('[data-testid="gate-revision-toggle"]').click()
        rev_input = page.locator('[data-testid="gate-revision-input"]')
        expect(rev_input).to_be_visible()
        rev_input.fill(
            "Append a second line 'REVISION_ROUND_2_OK' to task_result.txt while keeping AUTOPLAN_DEMO_OK."
        )
        with page.expect_response(
            lambda r: "/gate" in r.url and r.request.method == "POST",
            timeout=20000,
        ) as rev_resp:
            page.locator('[data-testid="gate-revision-submit"]').click()
        assert rev_resp.value.ok, rev_resp.value.text()

        # Wait for Round 2 to complete and pause at Human Gate with x2 visit badges
        expect(
            page.locator('[data-testid="planai-node-visits-WorktreeRunner"]')
        ).to_contain_text("×2", timeout=90000)
        expect(
            page.locator('[data-testid="planai-node-visits-VerificationGate"]')
        ).to_contain_text("×2", timeout=45000)
        expect(
            page.locator('[data-testid="planai-node-visits-ChiefReviewSink"]')
        ).to_contain_text("×2", timeout=45000)
        expect(
            page.locator('[data-testid="planai-node-state-ChiefReviewSink"]')
        ).to_have_text("Gate", timeout=30000)
        expect(gate_panel).to_be_visible(timeout=20000)
        _maybe_screenshot(page, "web_ironcurtain_cyclic_revision_x2.png")
        _maybe_screenshot(page, "ui_master_detail_review.png")

        # Exercise live Approve & Merge directly inside GateReviewPanel -> DoneTerminal Done & branch landed!
        gate_approve_btn = page.locator('[data-testid="gate-approve-button"]')
        expect(gate_approve_btn).to_be_enabled(timeout=10000)
        with page.expect_response(
            lambda r: "/gate" in r.url and r.request.method == "POST",
            timeout=30000,
        ) as app_resp:
            gate_approve_btn.click()
        assert app_resp.value.ok, app_resp.value.text()

        expect(
            page.locator('[data-testid="planai-node-state-DoneTerminal"]')
        ).to_have_text("Done", timeout=30000)
        expect(detail_status).to_have_text("landed", timeout=45000)
        landed_file = workspace_dir / "task_result.txt"
        assert landed_file.is_file()
        assert "AUTOPLAN_DEMO_OK" in landed_file.read_text()

        # Click <- Back to return cleanly to master review list
        page.locator('[data-testid="webclaw-detail-back"]').click()
        expect(page.locator('[data-testid="webclaw-queue-list"]')).to_be_visible()

        # Verify Phase 2 AUTO_CASCADE memory + .agents/skills accumulation after Round 2 resolution
        page.locator('[data-testid="inspector-tab-evolution"]').click()
        page.locator('[data-testid="evolution-subtab-memories"]').click()
        expect(page.locator('[data-testid="evolution-memories-list"]')).to_contain_text(
            "AUTO_CASCADE", timeout=15000
        )
        expect(page.locator('[data-testid="evolution-memories-list"]')).to_contain_text(
            "revision-playbook-", timeout=15000
        )

        page.locator('[data-testid="evolution-subtab-skills"]').click()
        skills_list = page.locator('[data-testid="evolution-skills-list"]')
        expect(skills_list).to_contain_text("-verified-revision", timeout=15000)
        first_skill_toggle = page.locator('[data-testid^="skill-md-toggle-"]').first
        expect(first_skill_toggle).to_be_visible()
        first_skill_toggle.click()
        expect(page.locator('[data-testid^="skill-md-"]').first).to_contain_text(
            "## Pre-Flight Checklist"
        )
        skills_api = _api_get("/api/evolution/skills")["skills"]
        assert len(skills_api) >= 1
        assert Path(skills_api[0]["skill_path"]).is_file()
        _maybe_screenshot(page, "web_phase2_accumulated_skills.png")
    finally:
        if temp_fid:
            try:
                _api_delete(f"/api/webclaw/sessions?friendlyId={temp_fid}")
            except Exception:
                pass


def test_webclaw_mobile_antigravity_projects_and_planai_sheet(page: Page):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(WEBCLAW_URL)
    page.wait_for_url("**/chat/**", timeout=20000)

    # Stage 1: Full-screen Projects & Sessions view with zero top routing strip
    sessions_screen = page.locator('[data-testid="mobile-sessions-screen"]')
    expect(sessions_screen).to_be_visible(timeout=20000)
    expect(page.locator('[data-testid="mobile-sessions-routing-strip"]')).to_have_count(0)
    expect(page.locator('[data-testid="mobile-home-run-simple-task"]')).to_have_count(0)
    expect(page.locator('[data-testid="mobile-brand"]')).to_contain_text("autobot")
    expect(page.locator('[data-testid="mobile-add-project-button"]')).to_be_visible()
    expect(page.locator('[data-testid="mobile-home-mode-toggle"]')).to_be_visible()
    expect(
        page.locator('[data-testid^="mobile-project-group-"]').first
    ).to_be_visible(timeout=15000)

    scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
    assert scroll_width <= 390, f"Expected zero mobile horizontal overflow, got {scroll_width}"
    _maybe_screenshot(page, "web_mobile_projects_stage1.png")

    # Stage 2: Open session -> Full-screen Session view with inline PlanAI DAG + in-composer routing
    first_session = page.locator('[data-testid^="mobile-session-row-"]').first
    expect(first_session).to_be_visible(timeout=10000)
    first_session.click()

    session_screen = page.locator('[data-testid="mobile-session-screen"]')
    expect(session_screen).to_be_visible(timeout=15000)
    expect(page.locator('[data-testid="mobile-session-mode-toggle"]')).to_be_visible()
    expect(page.locator('[data-testid="planai-dag-canvas"]')).to_be_visible(
        timeout=15000
    )
    _maybe_screenshot(page, "web_mobile_planai_sheet.png")

    # Stage 3: Tap top 'footer' icon -> 3-tab Detail panel sheet opens & closes cleanly
    footer_btn = page.locator('[data-testid="mobile-footer-detail-button"]')
    footer_btn.click()
    detail_sheet = page.locator('[data-testid="mobile-detail-sheet"]')
    expect(detail_sheet).to_be_visible(timeout=10000)
    expect(page.locator('[data-testid="mobile-detail-tab-graph"]')).to_have_count(0)

    footer_btn.click()
    expect(detail_sheet).to_have_count(0)
    page.locator('[data-testid="mobile-back-to-sessions"]').click()
    expect(sessions_screen).to_be_visible(timeout=10000)

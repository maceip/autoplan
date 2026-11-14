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


def test_webclaw_composer_routing_multi_project_and_planai_views(page: Page):
    open_webclaw(page)

    # 1. Verify autobot brand, transparent icon bg, and ZERO sidebar-routing-strip
    assert page.title() == "autobot"
    expect(page.locator('[data-testid="sidebar-routing-strip"]')).to_have_count(0)
    expect(page.locator('[data-testid="header-run-simple-task"]')).to_have_count(0)

    brand_link = page.locator('[data-testid="desktop-brand-link"]').first
    expect(brand_link).to_be_visible()
    expect(brand_link).to_contain_text("autobot")

    # Verify routing controls live INSIDE the chat composer input box
    composer_box = page.locator('[data-testid="composer-mode-toggle"]')
    expect(composer_box).to_be_visible()
    expect(page.locator('[data-testid="composer-project-pill"]')).to_be_visible()
    expect(page.locator('[data-testid="agent-service-selector"]')).to_be_visible()

    # Verify 'Start Demo' is in secondary sidebar footer (not 'Simple Task')
    start_demo_btn = page.locator('[data-testid="start-demo-button"]')
    expect(start_demo_btn).to_be_visible()
    expect(start_demo_btn).to_have_text("Start Demo")

    _maybe_screenshot(page, "web_desktop_3col_workbench.png")

    # 2. Multi-Project registration, session creation inside project, and cleanup
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

            # Create a new session directly inside this new project
            with page.expect_response(
                lambda r: "/api/sessions" in r.url and r.request.method == "POST",
                timeout=15000,
            ):
                page.locator(
                    f'[data-testid="project-new-session-{created_proj_id}"]'
                ).click()

            expect(page.locator('[data-testid="header-active-project"]')).to_have_text(
                proj_name, timeout=15000
            )
            expect(page.locator('[data-testid="composer-project-pill"]')).to_contain_text(
                proj_name, timeout=15000
            )
        finally:
            if created_proj_id:
                try:
                    _api_delete(f"/api/projects/{created_proj_id}")
                except Exception:
                    pass

    # 3. Switch Workspace View -> PlanAI Graph & Split View & SvelteFlow Editor
    page.locator('[data-testid="view-mode-graph"]').click()
    expect(page.locator('[data-testid="planai-graph-view"]')).to_be_visible(
        timeout=15000
    )
    expect(page.locator('[data-testid="planai-dag-canvas"]')).to_be_visible()
    expect(
        page.locator('[data-testid="planai-node-TeamSynthesisJoiner"]')
    ).to_be_visible()
    page.locator('[data-testid="planai-node-TeamSynthesisJoiner"]').click()
    expect(page.locator('[data-testid="planai-node-inspector"]')).to_contain_text(
        "TeamSynthesisJoiner"
    )
    _maybe_screenshot(page, "web_planai_graph_view.png")

    page.locator('[data-testid="planai-subtab-provenance"]').click()
    expect(page.locator('[data-testid="planai-provenance-panel"]')).to_be_visible()
    page.locator('[data-testid="planai-subtab-python"]').click()
    expect(page.locator('[data-testid="planai-python-panel"]')).to_contain_text(
        "JoinedTaskWorker"
    )
    page.locator('[data-testid="planai-subtab-canvas"]').click()

    page.locator('[data-testid="view-mode-split"]').click()
    expect(page.locator('[data-testid="planai-graph-view"]')).to_be_visible()
    expect(page.locator('[data-testid="composer-mode-toggle"]')).to_be_visible()
    _maybe_screenshot(page, "web_split_view.png")

    page.locator('[data-testid="view-mode-workbench"]').click()

    # 4. Inspector Brain (Evolution) tab: add rule & evolve prompt generation
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

    # 5. Verify SvelteFlow /planai-editor loads cleanly
    page.goto(f"{WEBCLAW_URL}/planai-editor")
    expect(page.locator('[data-testid="toolshelf-container"]')).to_be_visible(
        timeout=20000
    )


def test_webclaw_agents_registry_and_observe_only_minimax(page: Page):
    open_webclaw(page)

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

    # Select MiniMax inside composer -> persisted on backend & Start Demo disabled
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

    with page.expect_response(
        lambda r: "/api/sessions" in r.url and r.request.method == "PATCH",
        timeout=10000,
    ):
        selector.select_option("xiaomi-mimo")
    expect(page.locator('[data-testid="start-demo-button"]')).to_be_enabled()


def test_webclaw_live_start_demo_through_chief_approval(page: Page):
    open_webclaw(page)

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

    page.locator('[data-testid="inspector-tab-runs"]').click()
    run_state = page.locator(f'[data-testid="webclaw-run-state-{run_id}"]')
    expect(run_state).to_have_text("succeeded", timeout=90000)

    run_after = _api_get(f"/api/agents/runs/{run_id}")["run"]
    queue_item_id = run_after["queue_item_id"]
    assert queue_item_id, f"Expected queue_item_id on completed run: {run_after}"

    page.locator('[data-testid="inspector-tab-queue"]').click()
    queue_item_row = page.locator(f'[data-testid="webclaw-queue-item-{queue_item_id}"]')
    expect(queue_item_row).to_be_visible(timeout=20000)
    queue_item_row.click()

    detail_status = page.locator('[data-testid="webclaw-detail-status"]')
    expect(detail_status).to_have_text("needs_review", timeout=45000)
    expect(page.locator('[data-testid="webclaw-detail-test"]')).to_contain_text(
        "Test exit 0 (passed)", timeout=15000
    )

    approve_btn = page.locator('[data-testid="webclaw-approve-button"]')
    expect(approve_btn).to_be_enabled(timeout=10000)
    approve_btn.click()

    expect(detail_status).to_have_text("landed", timeout=45000)
    expect(approve_btn).to_be_disabled()
    landed_file = workspace_dir / "task_result.txt"
    assert landed_file.is_file()
    assert "AUTOPLAN_DEMO_OK" in landed_file.read_text()


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

    # Stage 2: Open session -> Full-screen Session view with in-composer mode + agent picker
    first_session = page.locator('[data-testid^="mobile-session-row-"]').first
    expect(first_session).to_be_visible(timeout=10000)
    first_session.click()

    session_screen = page.locator('[data-testid="mobile-session-screen"]')
    expect(session_screen).to_be_visible(timeout=15000)
    expect(page.locator('[data-testid="mobile-session-mode-toggle"]')).to_be_visible()

    # Stage 3: Tap top 'footer' icon -> Detail panel sheet opens with PlanAI DAG tab
    footer_btn = page.locator('[data-testid="mobile-footer-detail-button"]')
    footer_btn.click()
    detail_sheet = page.locator('[data-testid="mobile-detail-sheet"]')
    expect(detail_sheet).to_be_visible(timeout=10000)

    page.locator('[data-testid="mobile-detail-tab-graph"]').click()
    expect(page.locator('[data-testid="planai-graph-view"]')).to_be_visible(
        timeout=15000
    )
    _maybe_screenshot(page, "web_mobile_planai_sheet.png")

    footer_btn.click()
    expect(detail_sheet).to_have_count(0)
    page.locator('[data-testid="mobile-back-to-sessions"]').click()
    expect(sessions_screen).to_be_visible(timeout=10000)

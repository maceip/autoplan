"""End-to-end Playwright verification for WebClaw + AutoPlan multi-agent workbench.

Exercises every interactive control against live running AutoPlan (:5001) and
WebClaw (:3000) servers, including real subprocess spin-up of Xiaomi MiMo and
Antigravity agents, honest observe-only enforcement for MiniMax, Chief-of-Staff
test triage, and branch merge landing on operator approval.
"""

import base64
import json
import os
from pathlib import Path
import urllib.request

import pytest
from playwright.sync_api import Page, expect
from utils import BACKEND_TEST_URL

if os.environ.get("SKIP_E2E_TESTS") == "true":
    pytest.skip("Skipping e2e tests as SKIP_E2E_TESTS is set", allow_module_level=True)

WEBCLAW_URL = os.environ.get("WEBCLAW_URL", "http://localhost:3000")


def _api_get(path: str) -> dict:
    headers = {}
    user = os.environ.get("E2E_HTTP_USER", "").strip()
    pw = os.environ.get("E2E_HTTP_PASS", "").strip()
    if user and pw:
        tok = base64.b64encode(f"{user}:{pw}".encode()).decode()
        headers["Authorization"] = f"Basic {tok}"
    req = urllib.request.Request(f"{BACKEND_TEST_URL}{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def open_webclaw(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(WEBCLAW_URL)
    page.wait_for_url("**/chat/**", timeout=20000)
    expect(page.locator('[data-testid="agent-service-selector"]')).to_be_visible(
        timeout=20000
    )
    expect(page.locator('[data-testid="autoplan-inspector"]')).to_be_visible(
        timeout=20000
    )


def test_webclaw_agents_registry_and_session_scan(page: Page):
    open_webclaw(page)

    # Switch to Agents tab in Right Inspector and verify all 3 target services
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
    expect(page.locator('[data-testid="agent-demo-btn-minimax"]')).to_be_disabled()

    # Inspect real local sessions for MiniMax and Xiaomi MiMo
    page.locator('[data-testid="agent-scan-btn-minimax"]').click()
    expect(page.locator('[data-testid="agent-scanned-list-minimax"]')).to_be_visible(
        timeout=10000
    )
    expect(
        page.locator('[data-testid="agent-scanned-list-minimax"]')
    ).not_to_contain_text("No sessions found")

    page.locator('[data-testid="agent-scan-btn-xiaomi-mimo"]').click()
    expect(
        page.locator('[data-testid="agent-scanned-list-xiaomi-mimo"]')
    ).to_be_visible(timeout=10000)
    expect(
        page.locator('[data-testid="agent-scanned-list-xiaomi-mimo"]')
    ).not_to_contain_text("No sessions found")

    # Verify Inspector toggle persists across page reload via localStorage
    page.locator('[data-testid="toggle-inspector"]').click()
    expect(page.locator('[data-testid="autoplan-inspector"]')).to_have_count(0)
    page.reload()
    expect(page.locator('[data-testid="agent-service-selector"]')).to_be_visible(
        timeout=15000
    )
    expect(page.locator('[data-testid="autoplan-inspector"]')).to_have_count(0)
    page.locator('[data-testid="toggle-inspector"]').click()
    expect(page.locator('[data-testid="autoplan-inspector"]')).to_be_visible(
        timeout=10000
    )


def test_webclaw_observe_only_minimax_honest_guardrail(page: Page):
    open_webclaw(page)

    selector = page.locator('[data-testid="agent-service-selector"]')
    with page.expect_response(
        lambda r: "/api/sessions" in r.url and r.request.method == "PATCH",
        timeout=10000,
    ) as patch_resp:
        selector.select_option("minimax")
    assert patch_resp.value.ok

    # Reload and verify backend persisted the selected service in SQLite chat_sessions
    page.reload()
    expect(selector).to_have_value("minimax", timeout=15000)

    # Run Simple Task button is honestly disabled for observe-only service
    expect(page.locator('[data-testid="header-run-simple-task"]')).to_be_disabled()

    # Sending a chat message to observe-only MiniMax surfaces a real HTTP 409 error banner
    composer = page.locator("textarea").first
    composer.fill("Attempt headless dispatch on observe-only MiniMax")
    composer.press("Enter")
    error_banner = page.locator('[data-testid="dispatch-error-banner"]')
    expect(error_banner).to_be_visible(timeout=15000)
    expect(error_banner).to_contain_text("MINIMAX_API_KEY")

    # Restore dispatch-ready service
    with page.expect_response(
        lambda r: "/api/sessions" in r.url and r.request.method == "PATCH",
        timeout=10000,
    ):
        selector.select_option("xiaomi-mimo")
    expect(page.locator('[data-testid="header-run-simple-task"]')).to_be_enabled()


def test_webclaw_live_simple_agent_task_through_chief_approval(page: Page):
    open_webclaw(page)

    selector = page.locator('[data-testid="agent-service-selector"]')
    if selector.input_value() != "xiaomi-mimo":
        with page.expect_response(
            lambda r: "/api/sessions" in r.url and r.request.method == "PATCH",
            timeout=10000,
        ):
            selector.select_option("xiaomi-mimo")

    # Click 'Run Simple Task' in header and capture created run_id
    with page.expect_response(
        lambda r: "/api/autoplan/agents/demo-task" in r.url
        and r.request.method == "POST",
        timeout=15000,
    ) as demo_resp_info:
        page.locator('[data-testid="header-run-simple-task"]').click()

    demo_resp = demo_resp_info.value
    assert demo_resp.status == 201, demo_resp.text()
    run_payload = demo_resp.json()["run"]
    run_id = run_payload["id"]
    workspace_dir = Path(run_payload["cwd"])

    # Switch to Runs tab and wait for real Xiaomi MiMo subprocess to succeed
    page.locator('[data-testid="inspector-tab-runs"]').click()
    run_state = page.locator(f'[data-testid="webclaw-run-state-{run_id}"]')
    expect(run_state).to_have_text("succeeded", timeout=90000)

    # Fetch updated run to get queue_item_id and verify chat streamed assistant completion
    run_after = _api_get(f"/api/agents/runs/{run_id}")["run"]
    queue_item_id = run_after["queue_item_id"]
    assert queue_item_id, f"Expected queue_item_id on completed run: {run_after}"

    expect(page.locator("main")).to_contain_text(queue_item_id, timeout=20000)

    # Switch to Queue tab, select the item, and wait for Chief of Staff triage -> needs_review
    page.locator('[data-testid="inspector-tab-queue"]').click()
    queue_item_row = page.locator(f'[data-testid="webclaw-queue-item-{queue_item_id}"]')
    expect(queue_item_row).to_be_visible(timeout=20000)
    queue_item_row.click()

    detail_status = page.locator('[data-testid="webclaw-detail-status"]')
    expect(detail_status).to_have_text("needs_review", timeout=45000)
    expect(page.locator('[data-testid="webclaw-detail-test"]')).to_contain_text(
        "Test exit 0 (passed)", timeout=15000
    )

    # Click Approve in WebClaw and wait for Chief of Staff to merge onto main -> landed
    approve_btn = page.locator('[data-testid="webclaw-approve-button"]')
    expect(approve_btn).to_be_enabled(timeout=10000)
    approve_btn.click()

    expect(detail_status).to_have_text("landed", timeout=45000)
    expect(page.locator('[data-testid="webclaw-merged-commit"]')).to_contain_text(
        "Landed commit:", timeout=15000
    )

    # Verify task_result.txt actually landed on main branch on disk!
    landed_file = workspace_dir / "task_result.txt"
    assert landed_file.is_file(), f"Expected {landed_file} on main after landing"
    assert "AUTOPLAN_DEMO_OK" in landed_file.read_text()


def test_webclaw_live_antigravity_simple_task_spinup(page: Page):
    open_webclaw(page)

    page.locator('[data-testid="inspector-tab-agents"]').click()
    with page.expect_response(
        lambda r: "/api/autoplan/agents/demo-task" in r.url
        and r.request.method == "POST",
        timeout=15000,
    ) as agy_resp_info:
        page.locator('[data-testid="agent-demo-btn-antigravity"]').click()

    agy_resp = agy_resp_info.value
    assert agy_resp.status == 201, agy_resp.text()
    run_id = agy_resp.json()["run"]["id"]

    page.locator('[data-testid="inspector-tab-runs"]').click()
    expect(page.locator(f'[data-testid="webclaw-run-state-{run_id}"]')).to_have_text(
        "succeeded", timeout=90000
    )
    run_after = _api_get(f"/api/agents/runs/{run_id}")["run"]
    assert run_after["queue_item_id"], f"Expected queue_item_id for antigravity run: {run_after}"


def test_webclaw_mobile_antigravity_three_stage_flow(page: Page):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(WEBCLAW_URL)
    page.wait_for_url("**/chat/**", timeout=20000)

    # Stage 1: Full-screen All Sessions view with Antigravity #002b36 token palette
    sessions_screen = page.locator('[data-testid="mobile-sessions-screen"]')
    expect(sessions_screen).to_be_visible(timeout=20000)
    expect(page.locator('[data-testid="autoplan-inspector"]')).to_have_count(0)

    bg_color = sessions_screen.evaluate("el => getComputedStyle(el).backgroundColor")
    assert bg_color == "rgb(0, 43, 54)", f"Expected Antigravity #002b36 bg, got {bg_color}"
    scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
    assert scroll_width <= 390, f"Expected zero mobile horizontal overflow, got {scroll_width}"

    # Verify all 3 lead agent groups appear on the mobile All Sessions screen
    for svc in ("antigravity", "xiaomi-mimo", "minimax"):
        expect(page.locator(f'[data-testid="mobile-service-group-{svc}"]')).to_be_visible(
            timeout=10000
        )

    # Exercise search toggle & live session filtering
    page.locator('[data-testid="mobile-search-toggle"]').click()
    search_input = page.locator('[data-testid="mobile-search-input"]')
    expect(search_input).to_be_visible()
    search_input.fill("Chief")
    search_input.fill("")
    page.locator('[data-testid="mobile-search-toggle"]').click()

    # Exercise local CLI session expansion on mobile home
    page.locator('[data-testid="mobile-observed-toggle-minimax"]').click()

    # Stage 2: Click a session -> Full-screen Session view
    first_session = page.locator('[data-testid^="mobile-session-row-"]').first
    expect(first_session).to_be_visible(timeout=10000)
    first_session.click()

    session_screen = page.locator('[data-testid="mobile-session-screen"]')
    expect(session_screen).to_be_visible(timeout=15000)
    expect(sessions_screen).to_have_count(0)
    expect(page.locator('[data-testid="mobile-back-to-sessions"]')).to_be_visible()
    expect(page.locator('[data-testid="mobile-footer-detail-button"]')).to_be_visible()
    expect(page.locator('[data-testid="mobile-session-composer"]')).to_be_visible()

    session_box = session_screen.bounding_box()
    assert session_box is not None and abs(session_box["width"] - 390) <= 2

    # Stage 3: Tap top 'footer' icon -> Detail panel sheet opens over session
    footer_btn = page.locator('[data-testid="mobile-footer-detail-button"]')
    footer_btn.click()

    detail_sheet = page.locator('[data-testid="mobile-detail-sheet"]')
    expect(detail_sheet).to_be_visible(timeout=10000)
    expect(page.locator('[data-testid="mobile-overview-agents-row"]')).to_be_visible()
    expect(page.locator('[data-testid="mobile-overview-queue-row"]')).to_be_visible()
    expect(page.locator('[data-testid="mobile-overview-runs-row"]')).to_be_visible()

    # Expand Lead Agents inside Detail Sheet and verify real modes
    page.locator('[data-testid="mobile-overview-agents-row"]').click()
    expect(page.locator('[data-testid="mobile-agent-mode-antigravity"]')).to_have_text(
        "dispatch"
    )
    expect(page.locator('[data-testid="mobile-agent-mode-minimax"]')).to_have_text(
        "observe_only"
    )

    # Switch between Queue and Runs tabs inside Detail Sheet
    page.locator('[data-testid="mobile-detail-tab-queue"]').click()
    page.locator('[data-testid="mobile-detail-tab-runs"]').click()
    page.locator('[data-testid="mobile-detail-tab-overview"]').click()

    # Tap top 'footer' icon again -> closes Detail Sheet back to Session view
    footer_btn.click()
    expect(detail_sheet).to_have_count(0)

    # Tap Back arrow -> returns to full-screen All Sessions view
    page.locator('[data-testid="mobile-back-to-sessions"]').click()
    expect(sessions_screen).to_be_visible(timeout=10000)

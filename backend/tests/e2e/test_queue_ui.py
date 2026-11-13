"""E2E tests for the chief-of-staff queue UI at /queue.

Requires the standard e2e servers (frontend dev server on :5173 with
backendUrl pointing at the backend on :5001, backend in development
mode so the chief-of-staff loop is running).
"""

import base64
import json
import os
import urllib.request

import pytest
from playwright.sync_api import Page, expect
from utils import BACKEND_TEST_URL, FRONTEND_URL

# Skip e2e tests if SKIP_E2E_TESTS is set
if os.environ.get("SKIP_E2E_TESTS") == "true":
    pytest.skip("Skipping e2e tests as SKIP_E2E_TESTS is set", allow_module_level=True)


def _auth_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    user = os.environ.get("E2E_HTTP_USER", "").strip()
    pw = os.environ.get("E2E_HTTP_PASS", "").strip()
    if user and pw:
        tok = base64.b64encode(f"{user}:{pw}".encode()).decode()
        headers["Authorization"] = f"Basic {tok}"
    return headers


def submit_via_api(title: str, kind: str = "decision") -> str:
    request = urllib.request.Request(
        f"{BACKEND_TEST_URL}/api/queue/items",
        data=json.dumps(
            {"source_agent": "e2e-agent", "kind": kind, "title": title, "body": "seeded by e2e"}
        ).encode(),
        headers=_auth_headers(),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)["item"]["id"]


def open_queue(page: Page) -> None:
    page.goto(f"{FRONTEND_URL}/queue")
    expect(page.locator('[data-testid="queue-list"]')).to_be_visible(timeout=15000)
    expect(page.locator('[data-testid="chief-llm-status"]')).to_contain_text(
        "Chief LLM:", timeout=15000
    )


def test_queue_approve_flow(page: Page):
    item_id = submit_via_api("E2E approve decision")
    open_queue(page)
    page.locator(f'[data-testid="queue-item-{item_id}"]').click()
    # Chief prepares the item; approve becomes available in needs_review.
    expect(page.locator('[data-testid="detail-status"]')).to_have_text(
        "needs_review", timeout=30000
    )
    page.locator('[data-testid="approve-button"]').click()
    expect(page.locator('[data-testid="detail-status"]')).to_have_text("done", timeout=30000)


def test_queue_submit_form_and_keyboard(page: Page):
    open_queue(page)
    page.locator('[data-testid="submit-title"]').fill("E2E form submission")
    page.locator('[data-testid="submit-source"]').fill("e2e-form")
    page.locator('[data-testid="submit-button"]').click()
    expect(page.locator('[data-testid="queue-list"]')).to_contain_text(
        "E2E form submission", timeout=15000
    )
    expect(page.locator('[data-testid="detail-status"]')).to_have_text(
        "needs_review", timeout=30000
    )
    # Keyboard: snooze with "s", then wake via button.
    page.locator("body").click()
    page.keyboard.press("s")
    expect(page.locator('[data-testid="detail-status"]')).to_have_text("snoozed", timeout=15000)
    page.locator('[data-testid="wake-button"]').click()
    expect(page.locator('[data-testid="detail-status"]')).not_to_have_text(
        "snoozed", timeout=15000
    )


def test_queue_request_changes_flow(page: Page):
    item_id = submit_via_api("E2E changes decision")
    open_queue(page)
    page.locator(f'[data-testid="queue-item-{item_id}"]').click()
    expect(page.locator('[data-testid="detail-status"]')).to_have_text(
        "needs_review", timeout=30000
    )
    page.locator('[data-testid="request-changes-button"]').click()
    page.locator('[data-testid="changes-note"]').fill("Needs more detail")
    page.locator('[data-testid="changes-submit"]').click()
    expect(page.locator('[data-testid="detail-status"]')).not_to_have_text(
        "needs_review", timeout=15000
    )
    expect(page.locator('[data-testid="queue-detail"]')).to_contain_text(
        "Needs more detail", timeout=30000
    )

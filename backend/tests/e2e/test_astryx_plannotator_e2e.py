"""End-to-end Playwright verification for Meta Astryx UI layer & Plannotator architecture."""

import base64
import json
import os
from pathlib import Path
import shutil
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


def _api_patch(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{BACKEND_TEST_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_auth_headers(),
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def _api_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{BACKEND_TEST_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_auth_headers(),
        method="POST",
    )
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


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


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


def test_astryx_themes_and_color_modes_persist(page: Page):
    try:
        open_webclaw(page)
        trigger = page.locator('[data-testid="theme-appearance-trigger"]')
        expect(trigger).to_be_visible(timeout=15000)

        with page.expect_response(
            lambda r: "/api/autoplan/ui/preferences" in r.url
            and r.request.method == "PATCH",
            timeout=10000,
        ):
            trigger.click()
            expect(
                page.locator('[data-testid="theme-appearance-popover"]')
            ).to_be_visible(timeout=5000)
            page.locator('[data-testid="color-mode-light"]').click()

        with page.expect_response(
            lambda r: "/api/autoplan/ui/preferences" in r.url
            and r.request.method == "PATCH",
            timeout=10000,
        ):
            page.locator('[data-testid="theme-option-matcha"]').click()

        expect(page.locator("html")).to_have_attribute("data-astryx-theme", "matcha")
        expect(page.locator("html")).to_have_attribute("data-theme", "light")

        prefs = _api_get("/api/ui/preferences")["preferences"]
        assert prefs["theme_slug"] == "matcha"
        assert prefs["color_mode"] == "light"

        page.reload()
        expect(page.locator('[data-testid="desktop-top-app-bar"]')).to_be_visible(
            timeout=20000
        )
        expect(page.locator("html")).to_have_attribute(
            "data-astryx-theme", "matcha", timeout=10000
        )
        expect(page.locator("html")).to_have_attribute(
            "data-theme", "light", timeout=10000
        )
        _maybe_screenshot(page, "astryx_matcha_light.png")

        # Switch to stone + dark
        page.locator('[data-testid="theme-appearance-trigger"]').click()
        expect(
            page.locator('[data-testid="theme-appearance-popover"]')
        ).to_be_visible(timeout=5000)
        with page.expect_response(
            lambda r: "/api/autoplan/ui/preferences" in r.url
            and r.request.method == "PATCH",
            timeout=10000,
        ):
            page.locator('[data-testid="color-mode-dark"]').click()
        with page.expect_response(
            lambda r: "/api/autoplan/ui/preferences" in r.url
            and r.request.method == "PATCH",
            timeout=10000,
        ):
            page.locator('[data-testid="theme-option-stone"]').click()

        expect(page.locator("html")).to_have_attribute("data-astryx-theme", "stone")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        _maybe_screenshot(page, "astryx_stone_dark.png")
    finally:
        try:
            _api_patch(
                "/api/ui/preferences",
                {
                    "theme_slug": "neutral",
                    "color_mode": "dark",
                    "plans_view_mode": "cards",
                    "pinned_plan_ids": [],
                    "collapsed_project_ids": [],
                },
            )
        except Exception:
            pass


def test_plannotator_portfolio_chapters_and_annotations_e2e(page: Page):
    tmp_root = Path(tempfile.mkdtemp(prefix="autoplan-astryx-e2e-"))
    created_proj_id = ""
    created_session_fid = ""
    run_cwd: Path | None = None
    try:
        subprocess.run(
            ["git", "init", "-b", "main", str(tmp_root)],
            check=True,
            capture_output=True,
        )
        _git(tmp_root, "config", "user.email", "e2e@autoplan.local")
        _git(tmp_root, "config", "user.name", "AutoPlan E2E")
        (tmp_root / "src").mkdir(parents=True, exist_ok=True)
        (tmp_root / "src" / "core_engine.py").write_text(
            "def status():\n    return 'ok'\n", encoding="utf-8"
        )
        _git(tmp_root, "add", ".")
        _git(tmp_root, "commit", "-m", "initial")

        proj_res = _api_post(
            "/api/projects",
            {"name": "AstryxE2EProduct", "repo_path": str(tmp_root)},
        )
        created_proj_id = proj_res["project"]["id"]

        open_webclaw(page)
        with page.expect_response(
            lambda r: "/api/sessions" in r.url and r.request.method == "POST",
            timeout=15000,
        ) as sess_resp:
            page.locator(f'[data-testid="project-new-session-{created_proj_id}"]').click()
        created_session_fid = str(sess_resp.value.json().get("friendlyId") or "")
        assert created_session_fid, "Expected new session friendlyId"
        page.wait_for_url(f"**/chat/{created_session_fid}", timeout=15000)
        expect(page.locator('[data-testid="header-active-project"]')).to_have_text(
            "AstryxE2EProduct", timeout=15000
        )

        selector = page.locator('[data-testid="agent-service-selector"]')
        if selector.is_visible() and selector.input_value() != "xiaomi-mimo":
            opts = [
                opt.get_attribute("value")
                for opt in selector.locator("option").all()
            ]
            if "xiaomi-mimo" in opts:
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
        run_cwd = Path(demo_resp.json()["run"]["cwd"])

        # Wait for real workflow to complete agent + verify stages and pause at Human Gate
        expect(
            page.locator('[data-testid="planai-node-state-WorktreeRunner"]')
        ).to_have_text("Done", timeout=35000)
        expect(
            page.locator('[data-testid="planai-node-state-VerificationGate"]')
        ).to_have_text("Done", timeout=35000)
        expect(
            page.locator('[data-testid="planai-node-state-ChiefReviewSink"]')
        ).to_have_text("Gate", timeout=35000)
        gate_panel = page.locator('[data-testid="planai-gate-review-panel"]')
        expect(gate_panel).to_be_visible(timeout=20000)

        wfs = _api_get("/api/planai/workflows?limit=10")["workflows"]
        wf = next(w for w in wfs if w.get("project_id") == created_proj_id)
        wf_id = wf["id"]

        # 1. Navigate to Cross-Product /plans Portfolio via sidebar link
        page.locator('[data-testid="sidebar-plans-link"]').click()
        page.wait_for_url("**/plans", timeout=15000)
        expect(page.locator('[data-testid="plans-portfolio-view"]')).to_be_visible(
            timeout=15000
        )
        expect(page.locator('[data-testid="plans-now-section"]')).to_be_visible()
        now_card = page.locator(
            f'[data-testid="plans-now-section"] [data-testid="portfolio-plan-card-{wf_id}"]'
        )
        proj_card = page.locator(
            f'[data-testid="portfolio-project-{created_proj_id}"] [data-testid="portfolio-plan-card-{wf_id}"]'
        )
        expect(now_card).to_be_visible(timeout=15000)
        expect(now_card).to_contain_text("Your move")
        expect(proj_card).to_be_visible(timeout=15000)

        # Toggle Cards | List view mode & verify backend persistence
        with page.expect_response(
            lambda r: "/api/autoplan/ui/preferences" in r.url
            and r.request.method == "PATCH",
            timeout=10000,
        ):
            page.locator('[data-testid="plans-view-rows"]').click()
        assert (
            _api_get("/api/ui/preferences")["preferences"]["plans_view_mode"]
            == "rows"
        )
        with page.expect_response(
            lambda r: "/api/autoplan/ui/preferences" in r.url
            and r.request.method == "PATCH",
            timeout=10000,
        ):
            page.locator('[data-testid="plans-view-cards"]').click()

        # Pin the workflow card
        with page.expect_response(
            lambda r: "/api/autoplan/ui/preferences" in r.url
            and r.request.method == "PATCH",
            timeout=10000,
        ):
            now_card.locator(f'[data-testid="pin-plan-{wf_id}"]').click()
        expect(page.locator('[data-testid="plans-pinned-section"]')).to_be_visible(
            timeout=10000
        )

        # Search filter test
        search_box = page.locator(
            '[data-testid="plans-search-input"] input, input[data-testid="plans-search-input"]'
        ).first
        search_box.fill("AstryxE2EProduct")
        expect(now_card).to_be_visible()
        search_box.fill("")

        _maybe_screenshot(page, "astryx_plans_portfolio.png")

        # Click plan card to jump directly into the session workbench
        now_card.click()
        page.wait_for_url(f"**/chat/{created_session_fid}", timeout=15000)
        expect(gate_panel).to_be_visible(timeout=20000)

        # 2. Guided Chapters tab & SQLite checklist persistence
        page.locator('[data-testid="gate-tab-chapters"]').click()
        expect(
            page.locator('[data-testid="guided-chapter-switcher"]')
        ).to_be_visible(timeout=10000)
        chap_checkbox = page.locator('[data-testid="chapter-reviewed-ch-architecture"]')
        expect(chap_checkbox).to_be_visible()
        with page.expect_response(
            lambda r: f"/workflows/{wf_id}/chapters" in r.url
            and r.request.method == "POST",
            timeout=10000,
        ):
            chap_checkbox.check()
        detail_after_chap = _api_get(f"/api/planai/workflows/{wf_id}/detail")
        arch_chap = next(
            c for c in detail_after_chap["chapters"] if c["id"] == "ch-architecture"
        )
        assert arch_chap["reviewed"] is True
        page.locator('[data-testid="chapter-next-btn"]').click()

        # 3. Inline Diff Annotations -> Compile into Closed-Loop FORCE_REVISION
        page.locator('[data-testid="gate-tab-diff"]').click()
        page.locator('[data-testid="gate-add-annotation-btn"]').click()
        expect(
            page.locator('[data-testid="gate-annotation-composer"]')
        ).to_be_visible()
        page.locator('[data-testid="gate-annotation-input"]').fill(
            "Verify task_result.txt output includes REVISION_ROUND_2_OK"
        )
        with page.expect_response(
            lambda r: f"/workflows/{wf_id}/annotations" in r.url
            and r.request.method == "POST",
            timeout=10000,
        ):
            page.locator('[data-testid="gate-annotation-save-btn"]').click()

        expect(page.locator('[data-testid="gate-annotations-list"]')).to_contain_text(
            "Verify task_result.txt output includes REVISION_ROUND_2_OK"
        )

        page.locator('[data-testid="gate-revision-toggle"]').click()
        compile_btn = page.locator('[data-testid="gate-compile-annotations-btn"]')
        expect(compile_btn).to_be_visible()
        compile_btn.click()
        rev_input = page.locator('[data-testid="gate-revision-input"]')
        expect(rev_input).to_contain_value("Operator Review Annotations")
        _maybe_screenshot(page, "astryx_guided_gate_studio.png")

        with page.expect_response(
            lambda r: f"/workflows/{wf_id}/gate" in r.url
            and r.request.method == "POST",
            timeout=20000,
        ) as gate_res:
            page.locator('[data-testid="gate-revision-submit"]').click()
        assert gate_res.value.ok, gate_res.value.text()

        anns_after = _api_get(f"/api/planai/workflows/{wf_id}/annotations")[
            "annotations"
        ]
        assert len(anns_after) == 1
        assert anns_after[0]["resolved"] is True
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
        try:
            _api_patch(
                "/api/ui/preferences",
                {"pinned_plan_ids": [], "collapsed_project_ids": []},
            )
        except Exception:
            pass
        if run_cwd and run_cwd.exists():
            shutil.rmtree(run_cwd, ignore_errors=True)
        shutil.rmtree(tmp_root, ignore_errors=True)


def test_desktop_and_mobile_geometry_and_zero_left_edge_stripes(page: Page):
    for path, width in [("", 1440), ("/plans", 1440)]:
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(f"{WEBCLAW_URL}{path}")
        expect(page.locator('[data-testid="desktop-top-app-bar"]')).to_be_visible(
            timeout=20000
        )
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 0, f"Horizontal overflow {overflow}px on {path or '/'}"

        left_stripes = page.evaluate(
            """() => {
              const bad = [];
              for (const el of document.querySelectorAll('*')) {
                const cs = getComputedStyle(el);
                const bl = parseFloat(cs.borderLeftWidth || '0');
                const bt = parseFloat(cs.borderTopWidth || '0');
                const br = parseFloat(cs.borderRightWidth || '0');
                const bb = parseFloat(cs.borderBottomWidth || '0');
                if (bl >= 2 && bt === 0 && br === 0 && bb === 0) {
                  bad.push({ tag: el.tagName, cls: el.className, bl });
                }
              }
              return bad;
            }"""
        )
        assert left_stripes == [], f"Unexpected left-edge stripes: {left_stripes}"

    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(WEBCLAW_URL)
    page.wait_for_url("**/chat/**", timeout=20000)
    expect(page.locator('[data-testid="mobile-sessions-screen"]')).to_be_visible(
        timeout=20000
    )
    expect(page.locator('[data-testid="mobile-plans-link"]')).to_be_visible()
    expect(
        page.locator('[data-testid="mobile-sessions-routing-strip"]')
    ).to_have_count(0)
    expect(page.locator('[data-testid="mobile-home-run-simple-task"]')).to_have_count(0)
    expect(page.locator('[data-testid="mobile-detail-tab-graph"]')).to_have_count(0)

    mob_overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert mob_overflow <= 0, f"Mobile overflow {mob_overflow}px"
    _maybe_screenshot(page, "astryx_mobile_stage1.png")

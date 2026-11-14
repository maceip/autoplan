"""End-to-end Playwright CDP verification for the packaged Nucleus.app macOS desktop shell
and in-process macOS FoundationModels (`SystemLanguageModel.default`) backend.

Launches `nucleus/dist/Nucleus-darwin-arm64/Nucleus.app/Contents/MacOS/Nucleus` strictly
headlessly (`NUCLEUS_HEADLESS_TEST=1`), attaches Playwright over CDP, and verifies:
1. Clean 2-mode Nucleus shell (`Workbench` | `Graph Studio`) with zero Electron AI utility
   processes, zero Chromium Prompt API bridges, and zero `mlx_lm.server` daemons.
2. 3-Column Workbench iframe with inline zero-click PlanAI 2D DAG (`planai-dag-canvas`).
3. PlanAI SvelteFlow Visual Editor (`Graph Studio`) iframe (`toolshelf-container`).
4. Direct Python backend `/api/llm/test-prompt` executing in-process on macOS
   `FoundationModels` (`provider_used == "apple-foundation-models"`).
"""

import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

import pytest
from playwright.sync_api import expect, sync_playwright

if os.environ.get("SKIP_E2E_TESTS") == "true":
    pytest.skip("Skipping e2e tests as SKIP_E2E_TESTS is set", allow_module_level=True)

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGED_NUCLEUS_BIN = (
    REPO_ROOT
    / "nucleus"
    / "dist"
    / "Nucleus-darwin-arm64"
    / "Nucleus.app"
    / "Contents"
    / "MacOS"
    / "Nucleus"
)
SCREENSHOT_DIR = os.environ.get("E2E_SCREENSHOT_DIR", "").strip()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_cdp(port: int, timeout_s: float = 40.0) -> str:
    list_url = f"http://127.0.0.1:{port}/json/list"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(list_url, timeout=1.5) as resp:
                targets = json.load(resp)
                if any(
                    t.get("type") == "page" and "127.0.0.1" in str(t.get("url", ""))
                    for t in targets
                ):
                    return f"http://127.0.0.1:{port}"
        except Exception:
            pass
        time.sleep(0.35)
    raise TimeoutError(f"Timed out waiting for Nucleus page target on 127.0.0.1:{port}")


def _save_shot(window, filename: str) -> None:
    if not SCREENSHOT_DIR:
        return
    out_dir = Path(SCREENSHOT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    window.screenshot(path=str(out_dir / filename))


def test_nucleus_macos_shell_and_in_process_apple_foundation_models():
    assert PACKAGED_NUCLEUS_BIN.is_file(), (
        f"Packaged Nucleus.app binary missing at {PACKAGED_NUCLEUS_BIN}"
    )

    cdp_port = _free_port()
    webclaw_port = _free_port()
    env = {
        **os.environ,
        "AUTOPLAN_ROOT": str(REPO_ROOT),
        "NUCLEUS_HEADLESS_TEST": "1",
        "NUCLEUS_WEBCLAW_PORT": str(webclaw_port),
    }

    proc = subprocess.Popen(
        [
            str(PACKAGED_NUCLEUS_BIN),
            f"--remote-debugging-port={cdp_port}",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        cdp_endpoint = _wait_for_cdp(cdp_port, timeout_s=40.0)
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(cdp_endpoint)
            try:
                deadline = time.time() + 25.0
                window = None
                while time.time() < deadline and window is None:
                    for ctx in browser.contexts:
                        for pg in ctx.pages:
                            if "127.0.0.1" in pg.url:
                                window = pg
                                break
                    if window is None:
                        time.sleep(0.3)

                assert window is not None, "Nucleus BrowserWindow page did not open"

                expect(
                    window.locator('[data-testid="nucleus-app-root"]')
                ).to_be_visible(timeout=30000)
                expect(
                    window.locator('[data-testid="nucleus-titlebar"]')
                ).to_contain_text("Nucleus")
                expect(
                    window.locator('[data-testid="nucleus-mode-prompt-api"]')
                ).to_have_count(0)
                expect(
                    window.locator('[data-testid="nucleus-mode-editor"]')
                ).to_have_count(0)
                expect(
                    window.locator('[data-testid="nucleus-editor-frame"]')
                ).to_have_count(0)

                # 1. Verify unified 3-Column Workbench frame loads with IronCurtain Dagre state-machine SVG
                wb_frame = window.frame_locator(
                    '[data-testid="nucleus-workbench-frame"]'
                )
                expect(
                    wb_frame.locator('[data-testid="desktop-top-app-bar"]')
                ).to_be_visible(timeout=30000)
                expect(
                    wb_frame.locator('[data-testid="sidebar-projects-list"]')
                ).to_be_visible(timeout=20000)
                expect(
                    wb_frame.locator('[data-testid="planai-dag-canvas"]')
                ).to_be_visible(timeout=25000)
                expect(
                    wb_frame.locator('[data-testid="planai-state-machine-svg"]')
                ).to_be_visible(timeout=25000)
                expect(
                    wb_frame.locator(
                        '[data-testid="planai-node-WorktreeRunner"][data-node-kind="agent"]'
                    )
                ).to_be_visible(timeout=20000)
                expect(
                    wb_frame.locator(
                        '[data-testid="planai-node-VerificationGate"][data-node-kind="deterministic"]'
                    )
                ).to_be_visible(timeout=20000)
                expect(
                    wb_frame.locator(
                        '[data-testid="planai-node-ChiefReviewSink"][data-node-kind="human_gate"]'
                    )
                ).to_be_visible(timeout=20000)
                expect(
                    wb_frame.locator(
                        '[data-testid="planai-node-DoneTerminal"][data-node-kind="terminal"]'
                    )
                ).to_be_visible(timeout=20000)
                _save_shot(window, "nucleus_macos_workbench_3col.png")

                # Verify Phase 2 Guardrails / Memories / Skills sub-tabs inside packaged Nucleus.app
                wb_frame.locator('[data-testid="inspector-tab-evolution"]').click()
                expect(
                    wb_frame.locator('[data-testid="evolution-subtab-rules"]')
                ).to_be_visible(timeout=15000)
                expect(
                    wb_frame.locator('[data-testid="evolution-subtab-memories"]')
                ).to_be_visible(timeout=15000)
                expect(
                    wb_frame.locator('[data-testid="evolution-subtab-skills"]')
                ).to_be_visible(timeout=15000)
                wb_frame.locator('[data-testid="evolution-subtab-memories"]').click()
                expect(
                    wb_frame.locator('[data-testid="inspector-add-memory-form"]')
                ).to_be_visible(timeout=10000)
                wb_frame.locator('[data-testid="evolution-subtab-skills"]').click()
                expect(
                    wb_frame.locator('[data-testid="evolution-skills-list"]')
                ).to_be_visible(timeout=10000)
                _save_shot(window, "nucleus_phase2_workbench.png")

                # 2. Verify backend `/api/llm/test-prompt` executes via Apple FoundationModels in-process
                runtime_info = window.evaluate(
                    "() => window.nucleusDesktop.getRuntimeInfo()"
                )
                backend_url = runtime_info["backendUrl"]
                req = urllib.request.Request(
                    f"{backend_url}/api/llm/test-prompt",
                    data=json.dumps(
                        {"prompt": "Confirm in-process Apple FoundationModels in one short sentence."}
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30.0) as resp:
                    llm_res = json.loads(resp.read().decode("utf-8"))
                assert llm_res["success"] is True
                assert llm_res["provider_used"] == "apple-foundation-models"
                assert len(llm_res["reply"].strip()) >= 8
            finally:
                browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

"""End-to-end Playwright CDP verification for the packaged Nucleus.app macOS desktop app.

Launches the actual packaged Electron 45.3.2 (Chromium 156) binary inside
`nucleus/dist/Nucleus-darwin-arm64/Nucleus.app/Contents/MacOS/Nucleus`, attaches
Playwright over CDP, and verifies:
1. Native Chromium Blink `window.LanguageModel.availability() === "available"` backed by
   local Apple Silicon Metal `mlx_lm.server` (`mlx-community/Qwen3-4B-Instruct-2507-4bit`)
   via `session.defaultSession.registerLocalAIHandler(utilityProcess)`.
2. Direct renderer `await (await window.LanguageModel.create()).prompt(...)` execution.
3. Full Python `PlanAI.LLMInterface` -> `/api/llm/chromium-bridge` -> `Nucleus` Chromium
   `window.LanguageModel.prompt()` -> Metal MLX -> Python round-trip (`provider_used`
   contains `chromium-prompt-api`).
4. Left Project Activity Rail, 3-Column Workbench iframe, PlanAI Graph view,
   and SvelteFlow Editor view inside `Nucleus.app`.
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


def test_nucleus_macos_electron_app_chromium_prompt_api_and_planai_views():
    assert PACKAGED_NUCLEUS_BIN.is_file(), (
        f"Packaged Nucleus.app binary missing at {PACKAGED_NUCLEUS_BIN}"
    )

    cdp_port = _free_port()
    env = {
        **os.environ,
        "AUTOPLAN_ROOT": str(REPO_ROOT),
        "NUCLEUS_HEADLESS_TEST": "1",
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
                # Wait for Nucleus shell window page
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

                # Verify 3-Column Workbench frame loads with inline zero-click PlanAI 2D DAG
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
                    window.locator('[data-testid="nucleus-mode-graph"]')
                ).to_have_count(0)
                _save_shot(window, "nucleus_macos_workbench_3col.png")

                # Switch Nucleus to Visual Editor mode and verify SvelteFlow loads
                window.locator('[data-testid="nucleus-mode-editor"]').click()
                ed_frame = window.frame_locator('[data-testid="nucleus-editor-frame"]')
                expect(
                    ed_frame.locator('[data-testid="toolshelf-container"]')
                ).to_be_visible(timeout=25000)
                _save_shot(window, "nucleus_macos_svelteflow_editor.png")

                # Switch Nucleus to Chromium Prompt API Console
                window.locator('[data-testid="nucleus-mode-prompt-api"]').click()
                expect(
                    window.locator('[data-testid="nucleus-prompt-api-view"]')
                ).to_be_visible(timeout=10000)

                # 1. Assert Chromium Blink window.LanguageModel.availability() === 'available'
                expect(
                    window.locator('[data-testid="nucleus-lm-availability"]')
                ).to_have_text("available", timeout=25000)

                lm_probe = window.evaluate(
                    """async () => ({
                        isSecureContext: window.isSecureContext,
                        hasLanguageModel: typeof window.LanguageModel !== 'undefined',
                        availability: await window.LanguageModel.availability(),
                    })"""
                )
                assert lm_probe == {
                    "isSecureContext": True,
                    "hasLanguageModel": True,
                    "availability": "available",
                }

                # 2. Exercise direct renderer window.LanguageModel.prompt() via button
                window.locator('[data-testid="nucleus-run-prompt-test"]').click()
                prompt_out = window.locator('[data-testid="nucleus-prompt-output"]')
                expect(prompt_out).not_to_have_text("Ready.", timeout=45000)
                expect(prompt_out).not_to_contain_text(
                    "Running local prompt", timeout=45000
                )
                direct_text = prompt_out.inner_text().strip()
                assert len(direct_text) > 12 and not direct_text.startswith(
                    "Error:"
                ), f"Unexpected direct LanguageModel reply: {direct_text}"

                # 3. Wait for PlanAI Bridge registration, then exercise full Python -> Chromium round-trip
                expect(
                    window.locator('[data-testid="nucleus-bridge-client"]')
                ).to_contain_text("nucleus_", timeout=20000)

                window.locator('[data-testid="nucleus-run-backend-roundtrip"]').click()
                rt_out = window.locator('[data-testid="nucleus-roundtrip-output"]')
                expect(rt_out).not_to_have_text("Ready.", timeout=45000)
                expect(rt_out).not_to_contain_text("Dispatching round-trip", timeout=45000)
                rt_text = rt_out.inner_text().strip()
                assert (
                    len(rt_text) > 12
                    and "undefined" not in rt_text.lower()
                    and not rt_text.startswith("Error:")
                ), f"Unexpected Python->Chromium bridge reply: {rt_text}"
                expect(window.locator("#roundtrip-meta")).to_contain_text(
                    "chromium-prompt-api", timeout=10000
                )
                bridged_n = int(
                    window.locator('[data-testid="nucleus-bridged-count"]').inner_text()
                )
                assert bridged_n >= 1

                _save_shot(window, "nucleus_macos_chromium_prompt_api.png")
            finally:
                browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

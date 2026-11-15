"""End-to-end Playwright test verifying the 6-slide FlashHandoff Keynote HTML export."""

from __future__ import annotations

import functools
import http.server
import json
import socketserver
import threading
import time
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PRESO_DIR = REPO_ROOT / "preso" / "3D Pattern Design"
KEY_FILE = REPO_ROOT / "preso" / "3D Pattern Design.key"


def test_keynote_archive_and_html_manifest_present() -> None:
    assert KEY_FILE.is_file() and KEY_FILE.stat().st_size > 100_000
    assert (PRESO_DIR / "index.html").is_file()

    header = json.loads((PRESO_DIR / "assets" / "header.json").read_text(encoding="utf-8"))
    assert header["slideCount"] == 6
    assert header["slideWidth"] == 1920
    assert header["slideHeight"] == 1080
    assert len(header["slideList"]) == 6

    for sid in header["slideList"]:
        slide_dir = PRESO_DIR / "assets" / sid
        assert (slide_dir / f"{sid}.json").is_file()
        assert (slide_dir / "thumbnail.jpeg").is_file()
        pdf_asset = slide_dir / "assets" / f"{sid}.pdf"
        assert pdf_asset.is_file() and pdf_asset.stat().st_size > 5_000


def test_keynote_html_player_playwright_navigation() -> None:
    playwright = pytest.importorskip("playwright.sync_api")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(PRESO_DIR))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        page_errors: list[str] = []
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))

            page.goto(f"http://127.0.0.1:{port}/index.html", wait_until="networkidle")
            stage = page.locator("#stage")
            stage.wait_for(state="visible", timeout=10_000)
            page.wait_for_function("() => window.location.hash === '#0'", timeout=10_000)
            box = stage.bounding_box()
            assert box is not None and box["width"] > 0 and box["height"] > 0

            for expected_idx in range(1, 6):
                page.keyboard.press("ArrowRight")
                page.wait_for_function(
                    "(idx) => window.location.hash === '#' + idx",
                    arg=expected_idx,
                    timeout=10_000,
                )
                step_box = stage.bounding_box()
                assert step_box is not None and step_box["width"] > 0 and step_box["height"] > 0

            page.keyboard.press("ArrowLeft")
            page.wait_for_function("() => window.location.hash === '#4'", timeout=10_000)

            browser.close()
        httpd.shutdown()
        assert not page_errors, f"Unexpected browser page errors: {page_errors}"

"""Playwright evidence capture, run as a subprocess by the chief.

Usage: python -m planaieditor.evidence_capture <demo_url> <out_dir>
Prints one JSON line: {"screenshot": "demo.png", "video": "<file>.webm"}

Runs out-of-process because the editor backend monkey-patches eventlet,
and Playwright's sync API (greenlet-based) deadlocks under eventlet.
"""

import json
import sys
from pathlib import Path


def main() -> None:
    demo_url, out_dir = sys.argv[1], Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    evidence = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(record_video_dir=str(out_dir))
        page = context.new_page()
        page.goto(demo_url, wait_until="load", timeout=30000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(out_dir / "demo.png"), full_page=True)
        video = page.video
        context.close()
        browser.close()
        evidence["screenshot"] = "demo.png"
        if video is not None:
            evidence["video"] = Path(video.path()).name
        evidence["demo_url"] = demo_url
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()

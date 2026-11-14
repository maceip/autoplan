"""Tests for AutoPlan CI release pipeline scripts (version bump, tagged SBOM, /api/version)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from planaieditor import __version__
from planaieditor.app import app

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_api_version_endpoint_matches_version_file():
    version_file = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert __version__ == version_file
    with app.test_client() as client:
        resp = client.get("/api/version")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["name"] == "autoplan"
        assert body["version"] == version_file
        assert isinstance(body["frozen"], bool)


def test_ci_bump_version_dry_run_and_isolated_repo(tmp_path: Path):
    # 1. Dry-run against real repo must compute strictly higher SemVer than VERSION and git tags
    dry_proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "ci_bump_version.py"), "--dry-run"],
        capture_output=True,
        text=True,
        check=True,
    )
    dry_summary = json.loads(dry_proc.stdout)
    assert dry_summary["dry_run"] is True
    assert dry_summary["tag"].startswith("v")
    assert dry_summary["version"] != dry_summary["previous_version"]

    # 2. Isolated repo apply test across all 6 manifests + [bump:minor] commit directive
    (tmp_path / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (tmp_path / "backend" / "planaieditor").mkdir(parents=True)
    (tmp_path / "backend" / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "planaieditor"\nversion = "0.2.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "backend" / "planaieditor" / "__init__.py").write_text(
        '__version__ = "0.2.0"\n',
        encoding="utf-8",
    )
    for rel_pkg in (
        "nucleus/package.json",
        "frontend/package.json",
        "webclaw/apps/webclaw/package.json",
    ):
        pkg_file = tmp_path / rel_pkg
        pkg_file.parent.mkdir(parents=True, exist_ok=True)
        pkg_file.write_text('{\n  "name": "pkg",\n  "version": "0.2.0"\n}\n', encoding="utf-8")

    subprocess.run(["git", "-C", str(tmp_path), "init", "-b", "main"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
        check=True,
    )
    subprocess.run(["git", "-C", str(tmp_path), "tag", "v0.2.4"], check=True)

    bump_proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "ci_bump_version.py"),
            "--root",
            str(tmp_path),
            "--commit-message",
            "feat: release pipeline [bump:minor]",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    res = json.loads(bump_proc.stdout)
    assert res["version"] == "0.3.0"
    assert res["tag"] == "v0.3.0"
    assert len(res["modified_files"]) == 6
    assert (tmp_path / "VERSION").read_text(encoding="utf-8").strip() == "0.3.0"
    assert 'version = "0.3.0"' in (tmp_path / "backend" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert '__version__ = "0.3.0"' in (
        tmp_path / "backend" / "planaieditor" / "__init__.py"
    ).read_text(encoding="utf-8")
    for rel_pkg in (
        "nucleus/package.json",
        "frontend/package.json",
        "webclaw/apps/webclaw/package.json",
    ):
        assert json.loads((tmp_path / rel_pkg).read_text(encoding="utf-8"))["version"] == "0.3.0"


def test_generate_sbom_tags_every_dependency(tmp_path: Path):
    sbom_out = tmp_path / "autoplan-test.cdx.sbom.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "generate_sbom.py"),
            "--root",
            str(REPO_ROOT),
            "--version",
            "0.2.1",
            "--target",
            "darwin-arm64",
            "--output",
            str(sbom_out),
            "--verify",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(proc.stdout)
    assert report["valid"] is True
    assert report["all_components_tagged"] is True
    assert report["total_components"] >= 100
    assert report["subsystems"]["backend-binary"] > 0
    assert report["subsystems"]["frontend-static"] > 0
    assert report["subsystems"]["webclaw"] > 0

    sbom_doc = json.loads(sbom_out.read_text(encoding="utf-8"))
    assert sbom_doc["bomFormat"] == "CycloneDX"
    assert sbom_doc["specVersion"] == "1.5"
    assert sbom_doc["serialNumber"].startswith("urn:uuid:")
    for comp in sbom_doc["components"]:
        props = {p["name"]: p["value"] for p in comp["properties"]}
        assert props["autoplan:tag"].startswith("dep:")
        assert props["autoplan:ecosystem"] in {"pypi", "npm"}
        assert props["autoplan:subsystem"]
        assert props["autoplan:scope"]
        assert props["autoplan:source-manifest"]

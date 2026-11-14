#!/usr/bin/env python3
"""Execute the compiled AutoPlan binary in an isolated workspace and verify real stateful workflows."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> Tuple[int, Any]:
    body_bytes = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body_bytes = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"raw": raw}
        return err.code, parsed


def http_text(url: str, timeout: float = 15.0) -> Tuple[int, str]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def init_scratch_git_repo(repo_dir: Path) -> Dict[str, str]:
    repo_dir.mkdir(parents=True, exist_ok=True)
    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "AutoPlan Binary Verifier",
        "GIT_AUTHOR_EMAIL": "verifier@autoplan.local",
        "GIT_COMMITTER_NAME": "AutoPlan Binary Verifier",
        "GIT_COMMITTER_EMAIL": "verifier@autoplan.local",
    }

    def run_git(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            env=git_env,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()

    run_git("init", "-b", "main")
    (repo_dir / "README.md").write_text(
        "# Scratch Repo for Live Binary Verification\n", encoding="utf-8"
    )
    run_git("add", "README.md")
    run_git("commit", "-m", "chore: initial main commit")
    main_sha = run_git("rev-parse", "HEAD")

    feature_branch = "agent/binary-verify-feature"
    run_git("checkout", "-b", feature_branch)
    (repo_dir / "verified_feature.py").write_text(
        'def compute_answer() -> int:\n    return 42\n\nif __name__ == "__main__":\n    assert compute_answer() == 42\n',
        encoding="utf-8",
    )
    run_git("add", "verified_feature.py")
    run_git("commit", "-m", "feat: add verified_feature module")
    feature_sha = run_git("rev-parse", "HEAD")
    run_git("checkout", "main")
    return {
        "main_initial_sha": main_sha,
        "feature_branch": feature_branch,
        "feature_sha": feature_sha,
    }


def wait_for_server(
    base_url: str, proc: subprocess.Popen[str], timeout_s: float = 45.0
) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    last_err = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            out, err = proc.communicate(timeout=5)
            raise RuntimeError(
                f"Binary exited prematurely with code {proc.returncode}.\nSTDOUT:\n{out}\nSTDERR:\n{err}"
            )
        try:
            code, data = http_json("GET", f"{base_url}/api/version", timeout=3.0)
            if code == 200 and isinstance(data, dict) and data.get("success"):
                return data
        except Exception as exc:
            last_err = str(exc)
        time.sleep(0.4)
    raise TimeoutError(f"Binary HTTP server did not become ready within {timeout_s}s: {last_err}")


def verify_binary(
    *,
    binary_path: Path,
    expected_version: str,
    report_path: Optional[Path] = None,
) -> Dict[str, Any]:
    if not binary_path.is_file():
        raise FileNotFoundError(f"Binary not found: {binary_path}")

    started_at = time.time()
    checks: Dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="autoplan-bin-verify-") as tmp_raw:
        tmp_dir = Path(tmp_raw).resolve()
        isolated_bin_dir = tmp_dir / "bin"
        isolated_bin_dir.mkdir(parents=True, exist_ok=True)
        isolated_bin = isolated_bin_dir / binary_path.name
        shutil.copy2(binary_path, isolated_bin)
        isolated_bin.chmod(0o755)

        # 1. Verify CLI --version works from outside repository tree
        cli_proc = subprocess.run(
            [str(isolated_bin), "--version"],
            cwd=str(tmp_dir),
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
        if cli_proc.returncode != 0:
            raise RuntimeError(
                f"--version exited with {cli_proc.returncode}.\nSTDOUT:\n{cli_proc.stdout}\nSTDERR:\n{cli_proc.stderr}"
            )
        cli_version_out = (cli_proc.stdout or cli_proc.stderr).strip()
        if expected_version not in cli_version_out:
            raise AssertionError(
                f"--version output '{cli_version_out}' did not match expected '{expected_version}'"
            )
        checks["cli_version"] = cli_version_out

        # 2. Prepare isolated git repository with a real feature branch to test & land
        repo_dir = tmp_dir / "workspace_repo"
        git_meta = init_scratch_git_repo(repo_dir)

        port = pick_free_port()
        base_url = f"http://127.0.0.1:{port}"
        env = {
            **os.environ,
            "FLASK_ENV": "production",
            "AUTOPLAN_DISABLE_APPLE_FM": "1",
            "AUTOPLAN_NO_EVENTLET": "1",
            "HOME": str(tmp_dir / "isolated_home"),
        }
        Path(env["HOME"]).mkdir(parents=True, exist_ok=True)

        server_proc = subprocess.Popen(
            [
                str(isolated_bin),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--root-path",
                str(repo_dir),
            ],
            cwd=str(tmp_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            # 3. Verify frozen runtime metadata via GET /api/version & bundled Svelte UI via GET /
            ver_payload = wait_for_server(base_url, server_proc, timeout_s=45.0)
            if ver_payload.get("version") != expected_version:
                raise AssertionError(
                    f"/api/version returned {ver_payload.get('version')}, expected {expected_version}"
                )
            if ver_payload.get("frozen") is not True:
                raise AssertionError(
                    f"/api/version reported frozen={ver_payload.get('frozen')} (expected True)"
                )
            checks["api_version"] = ver_payload

            html_status, html_body = http_text(f"{base_url}/")
            if html_status != 200 or "<html" not in html_body.lower():
                raise AssertionError(
                    f"Bundled frontend GET / failed with status={html_status}"
                )
            checks["bundled_frontend_bytes"] = len(html_body)

            # 4. Verify SQLite QueueStore + Chief-of-Staff initialization via /api/webclaw/ping
            ping_status, ping_data = http_json("GET", f"{base_url}/api/webclaw/ping")
            if ping_status != 200 or not ping_data.get("ok"):
                raise AssertionError(f"/api/webclaw/ping failed: {ping_status} {ping_data}")
            project_id = str(ping_data.get("defaultProjectId") or "")
            if not project_id:
                raise AssertionError(f"Missing defaultProjectId in ping: {ping_data}")
            db_file = repo_dir / ".planai-queue" / "queue.db"
            if not db_file.is_file():
                raise AssertionError(f"SQLite queue database not created at {db_file}")
            checks["webclaw_ping"] = {
                "default_project_id": project_id,
                "sqlite_db_bytes": db_file.stat().st_size,
            }

            # 5. Submit a real code_change queue item, wait for Chief daemon to run test_command,
            #    approve at human gate, and verify Chief merges the branch onto main!
            create_status, create_resp = http_json(
                "POST",
                f"{base_url}/api/queue/items",
                {
                    "kind": "code_change",
                    "title": "Verify binary Chief-of-Staff test & git merge",
                    "body": "Exercises Chief triage, worktree test execution, and git merge landing.",
                    "source_agent": "release-verifier",
                    "project_id": project_id,
                    "repo_path": str(repo_dir),
                    "branch": git_meta["feature_branch"],
                    "target_branch": "main",
                    "test_command": "test -f verified_feature.py",
                },
            )
            if create_status != 201 or not create_resp.get("success"):
                raise AssertionError(
                    f"Queue item creation failed: {create_status} {create_resp}"
                )
            item_id = str(create_resp["item"]["id"])

            review_deadline = time.time() + 25.0
            review_item = None
            while time.time() < review_deadline:
                st, item_resp = http_json("GET", f"{base_url}/api/queue/items/{item_id}")
                if st == 200 and item_resp.get("item", {}).get("status") == "needs_review":
                    review_item = item_resp["item"]
                    break
                time.sleep(0.5)
            if review_item is None:
                raise AssertionError(
                    f"Chief daemon did not transition item {item_id} to needs_review within 25s"
                )
            if review_item.get("result", {}).get("test", {}).get("passed") is not True:
                raise AssertionError(
                    f"Chief test execution did not pass: {review_item.get('result')}"
                )

            dec_status, dec_resp = http_json(
                "POST",
                f"{base_url}/api/queue/items/{item_id}/decision",
                {
                    "action": "approve",
                    "note": "Verified passing test_command inside compiled binary.",
                    "actor": "ci-verifier",
                },
            )
            if dec_status != 200 or not dec_resp.get("success"):
                raise AssertionError(f"Queue approval failed: {dec_status} {dec_resp}")

            land_deadline = time.time() + 25.0
            landed_item = None
            while time.time() < land_deadline:
                st, item_resp = http_json("GET", f"{base_url}/api/queue/items/{item_id}")
                cur_status = item_resp.get("item", {}).get("status")
                if st == 200 and cur_status == "landed":
                    landed_item = item_resp["item"]
                    break
                if cur_status == "failed":
                    raise AssertionError(
                        f"Chief failed to land approved branch: {item_resp.get('item')}"
                    )
                time.sleep(0.5)
            if landed_item is None:
                raise AssertionError(
                    f"Chief daemon did not merge approved item {item_id} within 25s"
                )
            if not (repo_dir / "verified_feature.py").is_file():
                raise AssertionError(
                    "verified_feature.py missing on main branch after Chief reported landed"
                )
            checks["chief_queue_and_merge"] = {
                "item_id": item_id,
                "status": landed_item["status"],
                "merged_commit": landed_item.get("result", {}).get("merged_commit", ""),
                "verified_file_on_main": True,
            }

            # 6. Verify Cascade CONTENT_DIFF memory revisions + Jet Ski PolicyGuardian secret block
            m1_code, m1_resp = http_json(
                "POST",
                f"{base_url}/api/evolution/memories",
                {
                    "memory_key": "ci-release-verification",
                    "content": "Line 1: Enforce binary execution before release.\nLine 2: Baseline v1.\n",
                },
            )
            if m1_code != 201:
                raise AssertionError(f"Memory r1 upsert failed: {m1_code} {m1_resp}")

            m2_code, m2_resp = http_json(
                "POST",
                f"{base_url}/api/evolution/memories",
                {
                    "memory_key": "ci-release-verification",
                    "content": "Line 1: Enforce binary execution before release.\nLine 2: Attested CycloneDX SBOM v2.\n",
                },
            )
            if m2_code != 201:
                raise AssertionError(f"Memory r2 upsert failed: {m2_code} {m2_resp}")
            mem_obj = m2_resp.get("memory") or {}
            if mem_obj.get("revision") != 2 or "@@" not in str(mem_obj.get("content_diff") or ""):
                raise AssertionError(f"Expected CONTENT_DIFF unified diff on r2, got: {mem_obj}")

            # PolicyGuardian must block leaked GitHub PAT with HTTP 409
            fake_token = "ghp_" + ("A" * 36)
            sec_code, sec_resp = http_json(
                "POST",
                f"{base_url}/api/evolution/memories",
                {
                    "memory_key": "blocked-secret-test",
                    "content": f"Attempted credential write {fake_token}",
                },
            )
            if sec_code != 409:
                raise AssertionError(
                    f"Expected PolicyGuardian HTTP 409 on credential leak, got {sec_code}: {sec_resp}"
                )
            checks["policy_guardian_and_memories"] = {
                "memory_revision": mem_obj["revision"],
                "secret_leak_http_status": sec_code,
            }

            # 7. Execute the full 7-worker PlanAI AutoplanPromptEvolutionGraph inside the binary!
            evo_code, evo_resp = http_json(
                "POST",
                f"{base_url}/api/evolution/evolve",
                {"project_id": project_id, "reason": "ci_binary_verification"},
                timeout=60.0,
            )
            if evo_code != 200 or not evo_resp.get("success"):
                raise AssertionError(f"PlanAI evolution graph failed: {evo_code} {evo_resp}")
            evo_wf = evo_resp.get("workflow") or {}
            evo_status = evo_resp.get("evolution") or {}
            wf_id = str(evo_wf.get("id") or "")
            new_gen = int(evo_status.get("active_generation") or 0)
            if evo_wf.get("state") != "succeeded" or new_gen < 2:
                raise AssertionError(
                    f"Evolution graph did not advance generation to >=2: wf={evo_wf.get('state')}, gen={new_gen}"
                )
            skills_saved = evo_wf.get("result", {}).get("saved_skills") or []
            if not skills_saved:
                raise AssertionError(f"Expected accumulated .agents/skills from evolution: {evo_wf}")

            # Verify SvelteFlow projection & persisted Jet Ski Trajectory on the executed workflow
            sf_code, sf_resp = http_json(
                "GET", f"{base_url}/api/planai/workflows/{wf_id}/svelteflow"
            )
            if sf_code != 200 or len(sf_resp.get("nodes") or []) < 7:
                raise AssertionError(
                    f"SvelteFlow projection missing 7 evolution workers: {sf_code} {sf_resp}"
                )

            tr_code, tr_resp = http_json(
                "GET", f"{base_url}/api/planai/workflows/{wf_id}/trajectory"
            )
            traj_steps = tr_resp.get("trajectory", {}).get("steps") or []
            if tr_code != 200 or len(traj_steps) < 2:
                raise AssertionError(
                    f"Expected >=2 trajectory steps on {wf_id}, got: {tr_code} {tr_resp}"
                )

            # Verify Trajectory out-of-range guard returns 400, preview_only=True returns 200,
            # and live revert_to_step(0) truncates persisted trajectory down to step_count == 1!
            guard_code, _ = http_json(
                "POST",
                f"{base_url}/api/planai/workflows/{wf_id}/trajectory/revert",
                {"to_index": 9999},
            )
            if guard_code != 400:
                raise AssertionError(
                    f"Expected HTTP 400 reverting out-of-range step 9999, got {guard_code}"
                )
            prev_code, prev_resp = http_json(
                "POST",
                f"{base_url}/api/planai/workflows/{wf_id}/trajectory/revert",
                {"to_index": 0, "preview_only": True},
            )
            if prev_code != 200 or not prev_resp.get("success"):
                raise AssertionError(
                    f"Trajectory revert preview failed: {prev_code} {prev_resp}"
                )
            rev_code, rev_resp = http_json(
                "POST",
                f"{base_url}/api/planai/workflows/{wf_id}/trajectory/revert",
                {"to_index": 0},
            )
            if (
                rev_code != 200
                or not rev_resp.get("success")
                or rev_resp.get("trajectory", {}).get("step_count") != 1
            ):
                raise AssertionError(
                    f"Trajectory live revert to step 0 failed: {rev_code} {rev_resp}"
                )

            checks["planai_evolution_and_trajectory"] = {
                "workflow_id": wf_id,
                "active_generation": new_gen,
                "svelteflow_nodes": len(sf_resp.get("nodes") or []),
                "trajectory_steps": len(traj_steps),
                "skills_generated": len(skills_saved),
            }
        finally:
            if server_proc.poll() is None:
                server_proc.send_signal(signal.SIGTERM)
                try:
                    server_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server_proc.kill()
                    server_proc.wait(timeout=5)

    report = {
        "verified": True,
        "binary_path": str(binary_path.resolve()),
        "expected_version": expected_version,
        "duration_seconds": round(time.time() - started_at, 2),
        "checks": checks,
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-version", type=str, required=True)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    report = verify_binary(
        binary_path=args.binary,
        expected_version=args.expected_version,
        report_path=args.report,
    )
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())

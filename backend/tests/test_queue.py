"""Tests for the chief-of-staff review queue (store, API, chief loop)."""

import subprocess
from pathlib import Path

import pytest
from flask import Flask

from planaieditor.queue_api import setup_queue
from planaieditor.queue_store import QueueStore


def make_client(tmp_path):
    app = Flask(__name__)
    store, chief = setup_queue(app, None, tmp_path, start_chief=False)
    return app.test_client(), store, chief


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def make_repo_with_branch(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "file.txt").write_text("base\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    git(repo, "checkout", "-b", "feature-1")
    (repo / "file.txt").write_text("base\nfeature\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "feature change")
    git(repo, "checkout", "main")
    return repo


def test_store_create_list_decide(tmp_path):
    store = QueueStore(tmp_path / "queue.db")
    item = store.create_item(
        {"source_agent": "claude-code", "kind": "task", "title": "Do a thing", "priority": 5}
    )
    assert item["status"] == "queued"
    assert store.list_items()[0]["id"] == item["id"]
    store.add_decision(item["id"], "approve", note="looks good")
    assert store.list_decisions(item["id"])[0]["action"] == "approve"
    assert store.counts()["queued"] == 1


def test_api_submit_and_decision_flow(tmp_path):
    client, store, chief = make_client(tmp_path)
    resp = client.post(
        "/api/queue/items",
        json={"source_agent": "codex", "kind": "decision", "title": "Ship it?"},
    )
    assert resp.status_code == 201
    item_id = resp.get_json()["item"]["id"]

    # Chief triages and prepares the item for review.
    chief.process_once()
    item = client.get(f"/api/queue/items/{item_id}").get_json()["item"]
    assert item["status"] == "needs_review"
    assert item["recommendation"]

    # Invalid duplicate-style transition is rejected honestly.
    resp = client.post(f"/api/queue/items/{item_id}/decision", json={"action": "wake"})
    assert resp.status_code == 400

    resp = client.post(f"/api/queue/items/{item_id}/decision", json={"action": "approve"})
    assert resp.status_code == 200
    chief.process_once()
    item = store.get_item(item_id)
    assert item["status"] == "done"

    stats = client.get("/api/queue/stats").get_json()
    assert stats["counts"]["done"] == 1
    assert "llm_status" in stats["chief"]


def test_chief_lands_approved_code_change(tmp_path):
    client, store, chief = make_client(tmp_path)
    repo = make_repo_with_branch(tmp_path)
    resp = client.post(
        "/api/queue/items",
        json={
            "source_agent": "claude-code",
            "kind": "code_change",
            "title": "Add feature line",
            "repo_path": str(repo),
            "branch": "feature-1",
            "target_branch": "main",
            "test_command": "grep -q feature file.txt",
        },
    )
    item_id = resp.get_json()["item"]["id"]

    chief.process_once()
    item = store.get_item(item_id)
    assert item["status"] == "needs_review"
    # Test ran on main (feature not present yet) — real failing result recorded.
    assert item["result"]["test"]["exit_code"] == 1

    client.post(f"/api/queue/items/{item_id}/decision", json={"action": "approve"})
    chief.process_once()
    # Landing re-runs tests on main first; grep still fails, so landing is blocked.
    item = store.get_item(item_id)
    assert item["status"] == "needs_review"

    # Fix the test command to one that passes pre-merge, re-approve, expect a real merge.
    store.update_item(item_id, test_command="true")
    client.post(f"/api/queue/items/{item_id}/decision", json={"action": "approve"})
    chief.process_once()
    item = store.get_item(item_id)
    assert item["status"] == "landed"
    assert item["result"]["merged_commit"]
    assert "feature" in (repo / "file.txt").read_text()
    assert git(repo, "log", "--oneline", "-1", "--format=%s").startswith("Land queue item")


def test_request_changes_requeues_with_note(tmp_path):
    client, store, chief = make_client(tmp_path)
    resp = client.post(
        "/api/queue/items",
        json={"source_agent": "cursor", "kind": "task", "title": "Write docs", "body": "v1"},
    )
    item_id = resp.get_json()["item"]["id"]
    chief.process_once()
    client.post(
        f"/api/queue/items/{item_id}/decision",
        json={"action": "request_changes", "note": "Add examples"},
    )
    chief.process_once()
    item = store.get_item(item_id)
    assert item["status"] in {"queued", "triaged", "needs_review"}
    assert "Add examples" in item["body"]


def test_landing_refuses_repo_outside_root(tmp_path):
    client, store, chief = make_client(tmp_path)
    outside = tmp_path.parent / "outside-repo"
    outside.mkdir(exist_ok=True)
    resp = client.post(
        "/api/queue/items",
        json={
            "source_agent": "rogue-agent",
            "kind": "code_change",
            "title": "Escape attempt",
            "repo_path": str(outside),
            "branch": "x",
        },
    )
    item_id = resp.get_json()["item"]["id"]
    chief.process_once()
    client.post(f"/api/queue/items/{item_id}/decision", json={"action": "approve"})
    chief.process_once()
    assert store.get_item(item_id)["status"] == "failed"


@pytest.mark.parametrize("payload", [{}, {"kind": "bogus", "title": "x"}])
def test_api_rejects_invalid_submissions(tmp_path, payload):
    client, _, _ = make_client(tmp_path)
    assert client.post("/api/queue/items", json=payload).status_code == 400

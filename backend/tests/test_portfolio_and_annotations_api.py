"""Tests for cross-product Portfolio Plans Home, Guided Review Chapters, Annotations, and Astryx UI Preferences."""

from __future__ import annotations

import subprocess
from pathlib import Path

from flask import Flask

from planaieditor.queue_api import setup_queue


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def _init_repo(path: Path, files: dict[str, str], branch_files: dict[str, str]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    _git(path, "config", "user.email", "test@autoplan.local")
    _git(path, "config", "user.name", "AutoPlan Test")
    for rel, content in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "initial main")
    _git(path, "checkout", "-b", "feat/guided-demo")
    for rel, content in branch_files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "feature changes across core ui and tests")
    _git(path, "checkout", "main")
    return path


def _make_client(tmp_path: Path):
    _init_repo(
        tmp_path,
        {"README.md": "# Root\n"},
        {"README.md": "# Root\nUpdated\n"},
    )
    app = Flask(__name__)
    store, _chief = setup_queue(app, None, tmp_path, start_chief=False)
    return app.test_client(), store


def test_ui_preferences_persistence_and_validation(tmp_path: Path):
    client, _store = _make_client(tmp_path)

    res0 = client.get("/api/ui/preferences")
    assert res0.status_code == 200
    prefs0 = res0.get_json()["preferences"]
    assert prefs0 == {
        "theme_slug": "neutral",
        "color_mode": "dark",
        "plans_view_mode": "cards",
        "pinned_plan_ids": [],
        "collapsed_project_ids": [],
    }

    res1 = client.patch(
        "/api/ui/preferences",
        json={
            "theme_slug": "matcha",
            "color_mode": "light",
            "plans_view_mode": "rows",
            "pinned_plan_ids": ["wf_1", "wf_2", "wf_1"],
            "collapsed_project_ids": ["proj_a"],
        },
    )
    assert res1.status_code == 200
    prefs1 = res1.get_json()["preferences"]
    assert prefs1["theme_slug"] == "matcha"
    assert prefs1["color_mode"] == "light"
    assert prefs1["plans_view_mode"] == "rows"
    assert prefs1["pinned_plan_ids"] == ["wf_1", "wf_2"]
    assert prefs1["collapsed_project_ids"] == ["proj_a"]

    bad = client.patch("/api/ui/preferences", json={"theme_slug": "invalid-theme"})
    assert bad.status_code == 400
    assert "Invalid theme_slug" in bad.get_json()["error"]


def test_portfolio_guided_chapters_and_annotations_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AUTOPLAN_ROOT", str(tmp_path))
    app = Flask(__name__)
    root_repo = _init_repo(
        tmp_path / "root-app",
        {"backend/core.py": "def v():\n    return 1\n"},
        {
            "backend/core.py": "def v():\n    return 2\n",
            "src/components/App.tsx": "export const App = () => null;\n",
            "tests/test_core.py": "def test_v():\n    assert True\n",
        },
    )
    store, _chief = setup_queue(app, None, root_repo, start_chief=False)
    client = app.test_client()

    second_repo = _init_repo(
        tmp_path / "billing-svc",
        {"service.py": "x = 1\n"},
        {"service.py": "x = 2\n"},
    )
    proj_resp = client.post(
        "/api/projects",
        json={"name": "billing-svc", "repo_path": str(second_repo)},
    )
    assert proj_resp.status_code == 201
    second_proj_id = proj_resp.get_json()["project"]["id"]

    sess = store.create_chat_session(
        {"project_id": "autoplan", "label": "Refactor core + UI"}
    )
    item = store.create_item(
        {
            "project_id": "autoplan",
            "source_agent": "antigravity",
            "kind": "code_change",
            "title": "Refactor core + UI",
            "repo_path": str(root_repo),
            "branch": "feat/guided-demo",
            "target_branch": "main",
        }
    )
    store.update_item(item["id"], status="needs_review")
    wf = store.create_workflow(
        {
            "project_id": "autoplan",
            "session_key": sess["key"],
            "graph_type": "teamwork",
            "title": "Multi-layer guided feature",
            "goal": "Update core.py, App.tsx, and tests",
            "state": "waiting_gate",
            "nodes": [
                {"id": "LeadPlannerWorker", "label": "Lead Planner", "state": "succeeded"},
                {"id": "ChiefEscalationSink", "label": "Human Gate", "state": "waiting_gate"},
            ],
            "result": {
                "queue_item_id": item["id"],
                "round": 2,
                "max_rounds": 3,
                "handoffs": [
                    {
                        "ts": 1000.0,
                        "from_node": "LeadPlannerWorker",
                        "to_node": "subagent_1",
                        "task_type": "SubAgentDirectiveTask",
                        "round_num": 1,
                        "payload": {"objective": "Update core runtime", "role": "Core engineer"},
                    }
                ],
            },
        }
    )
    wf2 = store.create_workflow(
        {
            "project_id": second_proj_id,
            "session_key": "agent:antigravity:billing",
            "graph_type": "single",
            "title": "Invoice ledger fix",
            "goal": "Fix billing rounding",
            "state": "running",
        }
    )

    # Pin the first workflow
    client.patch("/api/ui/preferences", json={"pinned_plan_ids": [wf["id"]]})

    # 1. Portfolio endpoint aggregates cross-product "Now" + "By Product"
    port_res = client.get("/api/planai/portfolio")
    assert port_res.status_code == 200
    port = port_res.get_json()
    assert len(port["now"]) == 2
    assert {p["id"] for p in port["now"]} == {wf["id"], wf2["id"]}
    wf_card = next(p for p in port["now"] if p["id"] == wf["id"])
    assert wf_card["action_state"] == "your_move"
    assert wf_card["status_line"] == "Your move · Round 2/3"
    assert wf_card["pinned"] is True
    assert wf_card["session_friendly_id"] == sess["friendlyId"]
    assert any(g["project"]["name"] == "billing-svc" and len(g["plans"]) == 1 for g in port["by_project"])

    # 2. Annotations CRUD + markdown compilation
    ann_post = client.post(
        f"/api/planai/workflows/{wf['id']}/annotations",
        json={
            "kind": "must_change",
            "target_type": "diff_file",
            "file_path": "backend/core.py",
            "line_range": "1-2",
            "selected_text": "return 2",
            "comment_text": "Return structured VersionInfo instead of raw int 2",
        },
    )
    assert ann_post.status_code == 201
    ann = ann_post.get_json()["annotation"]
    assert ann["kind"] == "must_change"
    assert "backend/core.py" in ann_post.get_json()["compiled_markdown"]

    # 3. Mark Guided Chapter as reviewed
    chap_res = client.post(
        f"/api/planai/workflows/{wf['id']}/chapters",
        json={"chapter_id": "ch-core", "reviewed": True},
    )
    assert chap_res.status_code == 200
    assert chap_res.get_json()["reviewed_chapters"]["ch-core"] is True

    # 4. Detail endpoint returns ordered chapters (Core -> UI -> Verification -> Gates), annotations & round_history
    detail_res = client.get(f"/api/planai/workflows/{wf['id']}/detail")
    assert detail_res.status_code == 200
    detail = detail_res.get_json()
    chapter_ids = [c["id"] for c in detail["chapters"]]
    assert chapter_ids == ["ch-architecture", "ch-core", "ch-ui", "ch-verification", "ch-gates"]
    core_chap = next(c for c in detail["chapters"] if c["id"] == "ch-core")
    assert core_chap["reviewed"] is True
    assert len(core_chap["files"]) == 1 and core_chap["files"][0]["path"] == "backend/core.py"
    assert len(detail["round_history"]) == 2
    assert len(detail["annotations"]) == 1
    assert "Return structured VersionInfo" in detail["compiled_annotations_markdown"]

    # 5. Toggle annotation resolved + delete
    patch_res = client.patch(
        f"/api/planai/workflows/{wf['id']}/annotations/{ann['id']}",
        json={"resolved": True},
    )
    assert patch_res.status_code == 200
    assert patch_res.get_json()["annotation"]["resolved"] is True

    del_res = client.delete(f"/api/planai/workflows/{wf['id']}/annotations/{ann['id']}")
    assert del_res.status_code == 200
    assert client.get(f"/api/planai/workflows/{wf['id']}/annotations").get_json()["annotations"] == []

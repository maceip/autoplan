"""End-to-end unit & integration tests for Multi-Project registry, PlanAI Teamwork Graph,
Continuous Evolution Engine, and In-Process macOS FoundationModels (`SystemLanguageModel`).
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
from flask import Flask

from planaieditor.evolution_engine import EvolutionEngine
from planaieditor.queue_api import setup_queue


def _init_git_repo(repo_dir: Path, initial_files: dict[str, str] | None = None) -> Path:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(repo_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.email", "test@autoplan.local"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.name", "AutoPlan Test"],
        check=True,
        capture_output=True,
    )
    (repo_dir / ".gitignore").write_text(".mimocode/\n.DS_Store\n", encoding="utf-8")
    for rel, content in (initial_files or {"README.md": "# Test Repo\n"}).items():
        target = repo_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo_dir), "commit", "-m", "chore: initial commit"],
        check=True,
        capture_output=True,
    )
    return repo_dir


def _make_app(root_path: Path):
    app = Flask(__name__)
    store, chief = setup_queue(app, None, root_path, start_chief=False)
    return (
        app.test_client(),
        store,
        chief,
        app.config["TEAMWORK_ORCHESTRATOR"],
        app.config["EVOLUTION_ENGINE"],
        app.config["LLM_MANAGER"],
    )


def test_multi_project_registry_discover_and_external_repo_landing(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("AUTOPLAN_DISABLE_APPLE_FM", "1")
    workspace_parent = tmp_path / "workspace"
    root_repo = _init_git_repo(workspace_parent / "autoplan_root")
    ext_repo = _init_git_repo(
        workspace_parent / "external_alpha",
        {"README.md": "# External Alpha\n", "app.py": "VERSION = 1\n"},
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    agy_exec = bin_dir / "agy_ext_cli"
    agy_exec.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "if '--version' in sys.argv:\n"
        "    print('2.0.0-test')\n"
        "    sys.exit(0)\n"
        "pathlib.Path('feature_alpha.txt').write_text('alpha external project worktree verified\\n')\n"
        "print(json.dumps({'conversation_id': 'conv_ext_1', 'status': 'SUCCESS', 'response': 'Added feature_alpha.txt in external_alpha.'}))\n",
        encoding="utf-8",
    )
    agy_exec.chmod(agy_exec.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("AGY_BIN", str(agy_exec))

    client, store, chief, _, _, _ = _make_app(root_repo)

    # 1. Discover sibling git repositories
    disc = client.get(f"/api/projects/discover?dir={workspace_parent}").get_json()
    assert disc["success"] is True
    found_names = {r["name"] for r in disc["repositories"]}
    assert {"autoplan_root", "external_alpha"} <= found_names

    # 2. Register external_alpha (which is OUTSIDE root_repo!)
    reg = client.post(
        "/api/projects",
        json={
            "name": "External Alpha",
            "repo_path": str(ext_repo),
            "default_branch": "main",
            "test_command": "test -f feature_alpha.txt",
            "default_service": "antigravity",
        },
    )
    assert reg.status_code == 201
    alpha_proj = reg.get_json()["project"]
    assert alpha_proj["id"] == "external-alpha"

    # 3. Create a project-scoped WebClaw session and dispatch work in external_alpha
    sess_res = client.post(
        "/api/webclaw/sessions",
        json={
            "label": "Alpha Feature Session",
            "service": "antigravity",
            "projectId": alpha_proj["id"],
        },
    ).get_json()
    assert sess_res["entry"]["projectId"] == alpha_proj["id"]
    sess_key = sess_res["sessionKey"]

    send_res = client.post(
        "/api/webclaw/send",
        json={
            "sessionKey": sess_key,
            "projectId": alpha_proj["id"],
            "service": "antigravity",
            "mode": "single",
            "message": "Create feature_alpha.txt",
        },
    )
    assert send_res.status_code == 200
    run_id = send_res.get_json()["runId"]

    deadline = time.time() + 10.0
    run = store.get_run(run_id)
    while run and run["state"] == "running" and time.time() < deadline:
        time.sleep(0.05)
        run = store.get_run(run_id)

    assert run is not None and run["state"] == "succeeded"
    assert run["project_id"] == alpha_proj["id"]
    assert run["queue_item_id"]

    # 4. Chief triages external_alpha code_change, human approves, Chief merges onto external_alpha/main!
    chief.process_once()
    q_item = store.get_item(run["queue_item_id"])
    assert q_item is not None
    assert q_item["kind"] == "code_change"
    assert q_item["project_id"] == alpha_proj["id"]
    assert q_item["status"] == "needs_review"
    assert q_item["result"]["test"]["passed"] is True

    dec = client.post(
        f"/api/queue/items/{q_item['id']}/decision",
        json={"action": "approve", "note": "Ship external project change"},
    )
    assert dec.status_code == 200
    chief.process_once()

    landed = store.get_item(q_item["id"])
    assert landed is not None and landed["status"] == "landed"
    assert (ext_repo / "feature_alpha.txt").is_file()
    assert "alpha external project" in (ext_repo / "feature_alpha.txt").read_text(
        encoding="utf-8"
    )

    # 5. Default project cannot be deleted, external project can be deleted
    default_id = client.get("/api/webclaw/ping").get_json()["defaultProjectId"]
    assert client.delete(f"/api/projects/{default_id}").status_code == 409
    assert client.delete(f"/api/projects/{alpha_proj['id']}").status_code == 200


def test_planai_multi_agent_teamwork_graph_and_svelteflow_projection(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("AUTOPLAN_DISABLE_APPLE_FM", "1")
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    root_repo = _init_git_repo(tmp_path / "autoplan_root")
    team_repo = _init_git_repo(
        tmp_path / "team_service_repo",
        {"README.md": "# Team Service\n", "src/core.py": "def value():\n    return 42\n"},
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # Antigravity sub-agent writes impl_module.py
    agy_exec = bin_dir / "agy_team_cli"
    agy_exec.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "if '--version' in sys.argv:\n"
        "    print('2.0.0-test')\n"
        "    sys.exit(0)\n"
        "pathlib.Path('src/impl_module.py').write_text('TEAM_IMPL_READY = True\\n')\n"
        "print(json.dumps({'conversation_id': 'conv_team_agy', 'status': 'SUCCESS', 'response': 'Implemented src/impl_module.py cleanly.'}))\n",
        encoding="utf-8",
    )
    agy_exec.chmod(agy_exec.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("AGY_BIN", str(agy_exec))

    # Xiaomi MiMo sub-agent writes tests/verify_team.py (disjoint file!)
    mimo_exec = bin_dir / "mimo_team_cli"
    mimo_exec.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "if '--version' in sys.argv:\n"
        "    print('0.1.15')\n"
        "    sys.exit(0)\n"
        "p = pathlib.Path('tests/verify_team.py')\n"
        "p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_text('from src.impl_module import TEAM_IMPL_READY\\nassert TEAM_IMPL_READY is True\\n')\n"
        "print(json.dumps({'type': 'step_start', 'sessionID': 'ses_team_mimo'}))\n"
        "print(json.dumps({'type': 'text', 'sessionID': 'ses_team_mimo', 'part': {'type': 'text', 'text': 'Added tests/verify_team.py verification suite.'}}))\n",
        encoding="utf-8",
    )
    mimo_exec.chmod(mimo_exec.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("MIMO_BIN", str(mimo_exec))
    monkeypatch.setenv("MIMO_DEFAULT_MODEL", "xiaomi/mimo-v2.6-flash")

    client, store, chief, _, _, _ = _make_app(root_repo)

    proj = client.post(
        "/api/projects",
        json={
            "name": "Team Service",
            "repo_path": str(team_repo),
            "default_branch": "main",
            "test_command": "PYTHONPATH=. python3 tests/verify_team.py",
        },
    ).get_json()["project"]

    sess = client.post(
        "/api/webclaw/sessions",
        json={"label": "Team Graph Session", "projectId": proj["id"], "mode": "team"},
    ).get_json()
    sess_key = sess["sessionKey"]

    sent = client.post(
        "/api/webclaw/send",
        json={
            "sessionKey": sess_key,
            "projectId": proj["id"],
            "mode": "team",
            "service": "antigravity",
            "message": "Build src/impl_module.py and verify in tests/verify_team.py",
        },
    )
    assert sent.status_code == 200
    wf_id = sent.get_json()["workflowId"]
    assert wf_id.startswith("wf_team_")

    deadline = time.time() + 20.0
    wf = store.get_workflow(wf_id)
    while wf and wf["state"] == "running" and time.time() < deadline:
        time.sleep(0.1)
        wf = store.get_workflow(wf_id)

    assert wf is not None
    assert wf["state"] == "succeeded", f"Workflow failed: {wf}"
    assert wf["queue_item_id"]

    # Every worker + dynamic parallel sub-agent branch lane ran and succeeded!
    states_by_id = {n["id"]: n["state"] for n in wf["nodes"]}
    assert states_by_id == {
        "ContextHarvesterWorker": "succeeded",
        "LeadPlannerWorker": "succeeded",
        "SubtaskFanOutWorker": "succeeded",
        "MultiAgentDispatchWorker": "succeeded",
        "subagent_1": "succeeded",
        "subagent_2": "succeeded",
        "TeamSynthesisJoiner": "succeeded",
        "VerificationGateWorker": "succeeded",
        "ChiefEscalationSink": "succeeded",
    }
    joiner_node = next(n for n in wf["nodes"] if n["id"] == "TeamSynthesisJoiner")
    assert joiner_node["metrics"]["joined_agents"] == 2
    assert len(wf["provenance"]) >= 2

    # SvelteFlow projection endpoint returns live nodes + typed Task edges + Python source
    sf = client.get(f"/api/planai/workflows/{wf_id}/svelteflow").get_json()
    assert sf["success"] is True
    assert len(sf["nodes"]) == 9
    assert len(sf["edges"]) == 10
    assert "JoinedTaskWorker" in sf["pythonCode"]

    # Chief reviews and lands the integrated branch combining BOTH sub-agents' commits!
    chief.process_once()
    item = store.get_item(wf["queue_item_id"])
    assert item is not None and item["status"] == "needs_review"

    client.post(
        f"/api/queue/items/{item['id']}/decision",
        json={"action": "approve", "note": "Approve synthesized multi-agent team bundle"},
    )
    chief.process_once()

    landed = store.get_item(item["id"])
    assert landed is not None and landed["status"] == "landed"
    assert (team_repo / "src" / "impl_module.py").is_file()
    assert (team_repo / "tests" / "verify_team.py").is_file()


def test_teamwork_reality_scan_catches_unapproved_mock_and_allows_verbatim_quote(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("AUTOPLAN_DISABLE_APPLE_FM", "1")
    root_repo = _init_git_repo(tmp_path / "root")
    _, _, _, orchestrator, _, _ = _make_app(root_repo)

    bad_diff = (
        "diff --git a/ui.tsx b/ui.tsx\n"
        "+++ b/ui.tsx\n"
        "+const metrics = MOCK_DATA;\n"
    )
    reality_bad, secrets_bad = orchestrator._reality_and_secret_scan(bad_diff)
    assert reality_bad["passed"] is False
    assert len(reality_bad["violations"]) == 1
    assert secrets_bad["passed"] is True

    authorized_diff = (
        "diff --git a/ui.tsx b/ui.tsx\n"
        "+++ b/ui.tsx\n"
        '+// RYAN EXPLICIT MOCK/FALLBACK AUTHORIZATION: "use fixture in test"\n'
        "+const metrics = MOCK_DATA;\n"
    )
    reality_ok, _ = orchestrator._reality_and_secret_scan(authorized_diff)
    assert reality_ok["passed"] is True


@pytest.mark.skipif(sys.platform != "darwin", reason="FoundationModels requires macOS")
def test_apple_foundation_models_in_process_and_evolution_engine_planai_graph(
    tmp_path: Path, monkeypatch
):
    monkeypatch.delenv("AUTOPLAN_DISABLE_APPLE_FM", raising=False)
    monkeypatch.setenv("AUTOPLAN_ENABLE_TEST_LLM", "1")
    monkeypatch.delenv("CHIEF_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("CHIEF_LLM_MODEL", raising=False)
    root_repo = _init_git_repo(tmp_path / "root")

    corpus_file = tmp_path / "breakdown_trends.json"
    corpus_file.write_text(
        json.dumps(
            {
                "total_prompts": 19528,
                "total_sessions": 976,
                "categories": {
                    "E4_stall_collision": {"prompts": 250},
                    "D_false_completion": {"prompts": 552},
                },
            }
        ),
        encoding="utf-8",
    )

    client, store, _, _, _, llm_manager = _make_app(root_repo)

    evo = EvolutionEngine(
        store=store,
        llm_manager=llm_manager,
        corpus_trends_path=corpus_file,
        enable_host_corpus=False,
    )
    assert evo.bootstrap_summary["corpus_loaded"] is True
    assert evo.bootstrap_summary["seeded_corpus_rules"] == 2

    # 1. Verify /api/llm/test-prompt runs directly in-process on macOS SystemLanguageModel
    test_llm = client.post(
        "/api/llm/test-prompt",
        json={"prompt": "Reply in one short sentence confirming FoundationModels is online."},
    )
    assert test_llm.status_code == 200
    llm_body = test_llm.get_json()
    assert llm_body["provider_used"] == "apple-foundation-models"
    assert len(llm_body["reply"].strip()) >= 8
    assert llm_body["diagnostics"]["apple_foundation_models"]["available"] is True
    assert llm_body["diagnostics"]["total_calls"] >= 1

    # 2. Submit a queue item and trigger operator request_changes -> live rule learned
    q_item = client.post(
        "/api/queue/items",
        json={"title": "Draft API update", "kind": "decision"},
    ).get_json()["item"]
    store.update_item(q_item["id"], status="needs_review")

    dec_res = client.post(
        f"/api/queue/items/{q_item['id']}/decision",
        json={
            "action": "request_changes",
            "note": "Always attach latency measurements before requesting approval",
        },
    )
    assert dec_res.status_code == 200
    rules_now = store.list_evolution_rules(active_only=True)
    assert any("latency measurements" in r["rule_text"] for r in rules_now)

    # 3. Run full PlanAI AutoplanPromptEvolutionGraph via /api/evolution/evolve on Apple FoundationModels
    evolve_res = client.post(
        "/api/evolution/evolve",
        json={"project_id": "*", "reason": "operator_bounce_cycle"},
    )
    assert evolve_res.status_code == 200
    evo_data = evolve_res.get_json()
    assert evo_data["workflow"]["state"] == "succeeded"
    assert evo_data["workflow"]["result"]["llm_provider_used"] == "apple-foundation-models"

    evo_node_states = {n["id"]: n["state"] for n in evo_data["workflow"]["nodes"]}
    assert evo_node_states == {
        "TraceCollectorWorker": "succeeded",
        "FailureCritiqueWorker": "succeeded",
        "EvolutionCritiqueJoiner": "succeeded",
        "EvolutionCommitSink": "succeeded",
    }

    evo_joiner = next(
        n for n in evo_data["workflow"]["nodes"] if n["id"] == "EvolutionCritiqueJoiner"
    )
    assert evo_joiner["metrics"]["joined_critiques"] == 2

    lead_gen = store.get_active_prompt("lead_planner")
    chief_gen = store.get_active_prompt("chief_triage")
    assert lead_gen is not None and lead_gen["generation"] == 2
    assert chief_gen is not None and chief_gen["generation"] == 2
    assert "Evolved Directives (Gen v2)" in lead_gen["prompt_template"]

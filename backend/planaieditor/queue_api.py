"""HTTP/SocketIO/SSE API for Multi-Project, PlanAI Teamwork, Evolution, Chromium LLM Bridge, Queue & WebClaw."""

from __future__ import annotations

import json
import os
import queue
import threading
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from flask import (
    Flask,
    Response,
    jsonify,
    request,
    send_from_directory,
    stream_with_context,
)

from planaieditor.agent_adapters import AgentRunManager, redact_secrets
from planaieditor.chief import ChiefOfStaff
from planaieditor.evolution_engine import EvolutionEngine
from planaieditor.planai_llm_core import PlanAILLMManager
from planaieditor.queue_store import KINDS, QueueStore
from planaieditor.single_workflow_graph import transition_workflow_gate
from planaieditor.teamwork_graph import TeamworkOrchestrator, workflow_to_svelteflow

_DECISION_TO_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "request_changes": "changes_requested",
    "snooze": "snoozed",
}

_ALLOWED_FROM = {
    "approve": {"needs_review"},
    "reject": {"needs_review", "queued", "triaged", "in_progress"},
    "request_changes": {"needs_review"},
    "snooze": {"needs_review", "queued", "triaged"},
}

_LOCALHOST_ORIGINS = {
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5198",
    "http://127.0.0.1:5198",
    "http://localhost:5001",
    "http://127.0.0.1:5001",
    "http://localhost:5051",
    "http://127.0.0.1:5051",
}


def setup_queue(
    app: Flask,
    socketio: Any,
    root_path: Path,
    start_chief: bool = True,
) -> Tuple[QueueStore, ChiefOfStaff]:
    root_path = Path(root_path).resolve()
    store = QueueStore(root_path / ".planai-queue" / "queue.db")

    sse_subscribers: List[queue.Queue] = []
    sse_lock = threading.Lock()
    seq_counter = {"n": 0}

    def broadcast_sse(event_name: str, payload: Dict[str, Any]) -> None:
        with sse_lock:
            seq_counter["n"] += 1
            envelope = {
                "event": event_name,
                "payload": payload,
                "seq": seq_counter["n"],
                "stateVersion": seq_counter["n"],
            }
            dead: List[queue.Queue] = []
            for sub in sse_subscribers:
                try:
                    sub.put_nowait(envelope)
                except queue.Full:
                    dead.append(sub)
            for d in dead:
                if d in sse_subscribers:
                    sse_subscribers.remove(d)

    def emit_update(item: Optional[Dict[str, Any]]) -> None:
        if item is None:
            return
        broadcast_sse(
            "queue_updated",
            {"item_id": item["id"], "status": item["status"], "item": item},
        )
        if socketio is None:
            return
        try:
            socketio.emit(
                "queue_updated",
                {"item_id": item["id"], "status": item["status"], "item": item},
            )
        except Exception:
            pass

    def on_system_event(event_type: str, payload: Dict[str, Any]) -> None:
        if event_type == "webclaw_chat":
            broadcast_sse("chat", payload)
        elif event_type == "queue_item_created":
            emit_update(payload.get("item"))
        else:
            broadcast_sse(event_type, payload)
        if socketio is not None:
            try:
                socketio.emit("agent_event", {"type": event_type, **payload})
                if event_type == "planai_workflow_updated":
                    wf = payload.get("workflow") or {}
                    socketio.emit("planai_workflow_updated", wf)
                    # Also emit PlanAI Editor debug events for live node animation
                    events = wf.get("events") or []
                    if events:
                        latest = events[-1]
                        socketio.emit(
                            "planai_debug_event",
                            {
                                "type": latest.get("state", "running"),
                                "data": {
                                    "workflow_id": wf.get("id"),
                                    "node_name": latest.get("node_id"),
                                    "detail": latest.get("detail"),
                                },
                            },
                        )
            except Exception:
                pass

    enable_auto_local = start_chief or (
        os.environ.get("AUTOPLAN_ENABLE_TEST_LLM", "").strip() == "1"
    )
    llm_manager = PlanAILLMManager(root_path, enable_auto_local=enable_auto_local)
    agent_manager = AgentRunManager(store, root_path, on_event=on_system_event)
    default_proj = store.ensure_default_project(
        root_path, default_service=agent_manager.default_dispatch_service()
    )
    evolution_engine = EvolutionEngine(
        store,
        llm_manager,
        on_event=on_system_event,
        enable_host_corpus=start_chief,
    )
    teamwork_orchestrator = TeamworkOrchestrator(
        store=store,
        root_path=root_path,
        agent_manager=agent_manager,
        llm_manager=llm_manager,
        evolution_engine=evolution_engine,
        on_event=on_system_event,
    )
    chief = ChiefOfStaff(
        store,
        root_path,
        emit=emit_update,
        llm_manager=llm_manager,
        on_event=on_system_event,
    )

    app.config["QUEUE_STORE"] = store
    app.config["CHIEF"] = chief
    app.config["AGENT_MANAGER"] = agent_manager
    app.config["LLM_MANAGER"] = llm_manager
    app.config["EVOLUTION_ENGINE"] = evolution_engine
    app.config["TEAMWORK_ORCHESTRATOR"] = teamwork_orchestrator

    @app.after_request
    def add_localhost_cors(response: Response) -> Response:
        origin = request.headers.get("Origin", "")
        if (
            origin in _LOCALHOST_ORIGINS
            or origin.startswith("file://")
            or origin.startswith("http://127.0.0.1:")
            or origin.startswith("http://localhost:")
        ):
            response.headers["Access-Control-Allow-Origin"] = origin or "*"
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Authorization"
            )
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PATCH, DELETE, OPTIONS"
            )
        return response

    @app.route("/queue", methods=["GET"])
    @app.route("/planai-editor", methods=["GET"])
    def svelte_spa_routes():
        if app.static_folder and (Path(app.static_folder) / "index.html").is_file():
            return send_from_directory(app.static_folder, "index.html")
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Static Svelte UI is served by the frontend dev server in development mode.",
                }
            ),
            404,
        )

    # ---- Multi-Project Registry API -------------------------------------

    @app.route("/api/projects", methods=["GET", "POST"])
    def projects_collection():
        if request.method == "GET":
            store.ensure_default_project(
                root_path, default_service=agent_manager.default_dispatch_service()
            )
            return jsonify({"success": True, "projects": store.list_projects()})

        data = request.get_json(silent=True) or {}
        try:
            proj = store.create_project(
                data, require_git=bool(data.get("require_git", True))
            )
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        broadcast_sse("projects_updated", {"project": proj})
        return jsonify({"success": True, "project": proj}), 201

    @app.route("/api/projects/discover", methods=["GET"])
    def projects_discover():
        raw_dir = (request.args.get("dir") or "").strip()
        search_dir = Path(raw_dir).expanduser() if raw_dir else root_path.parent
        repos = store.discover_git_repos(search_dir, limit=int(request.args.get("limit") or 25))
        return jsonify(
            {
                "success": True,
                "search_dir": str(search_dir.resolve()) if search_dir.exists() else str(search_dir),
                "repositories": repos,
            }
        )

    @app.route("/api/projects/<project_id>", methods=["GET", "PATCH", "DELETE"])
    def project_detail(project_id: str):
        if request.method == "GET":
            proj = store.get_project(project_id)
            if not proj:
                return jsonify({"success": False, "error": "Project not found"}), 404
            return jsonify({"success": True, "project": proj})

        if request.method == "PATCH":
            data = request.get_json(silent=True) or {}
            updated = store.update_project(project_id, **data)
            if not updated:
                return jsonify({"success": False, "error": "Project not found"}), 404
            broadcast_sse("projects_updated", {"project": updated})
            return jsonify({"success": True, "project": updated})

        if project_id == default_proj["id"]:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Cannot delete primary workspace root project.",
                    }
                ),
                409,
            )
        try:
            deleted = store.delete_project(project_id)
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 409
        if not deleted:
            return jsonify({"success": False, "error": "Project not found"}), 404
        broadcast_sse("projects_updated", {"deleted_id": project_id})
        return jsonify({"success": True, "deleted": project_id})

    # ---- PlanAI Workflows, Visualizations & Multi-Agent Teamwork --------

    @app.route("/api/planai/workflows", methods=["GET"])
    def planai_list_workflows():
        project_id = request.args.get("project_id") or None
        session_key = request.args.get("session_key") or None
        graph_type = request.args.get("graph_type") or None
        limit = int(request.args.get("limit") or 30)
        workflows = store.list_workflows(
            project_id=project_id,
            session_key=session_key,
            graph_type=graph_type,
            limit=limit,
        )
        return jsonify({"success": True, "workflows": workflows})

    @app.route("/api/planai/workflows/<wf_id>", methods=["GET"])
    def planai_get_workflow(wf_id: str):
        wf = store.get_workflow(wf_id)
        if not wf:
            return jsonify({"success": False, "error": "Workflow not found"}), 404
        return jsonify(
            {
                "success": True,
                "workflow": wf,
                "svelteflow": workflow_to_svelteflow(wf),
            }
        )

    @app.route("/api/planai/workflows/<wf_id>/svelteflow", methods=["GET"])
    def planai_workflow_svelteflow(wf_id: str):
        wf = store.get_workflow(wf_id)
        if not wf:
            return jsonify({"success": False, "error": "Workflow not found"}), 404
        return jsonify({"success": True, **workflow_to_svelteflow(wf)})

    @app.route("/api/planai/workflows/<wf_id>/detail", methods=["GET"])
    def planai_workflow_detail(wf_id: str):
        wf = store.get_workflow(wf_id)
        if not wf:
            return jsonify({"success": False, "error": "Workflow not found"}), 404
        wf_res = dict(wf.get("result") or {})
        q_id = str(wf.get("queue_item_id") or wf_res.get("queue_item_id") or "").strip()
        item = store.get_item(q_id) if q_id else None
        decisions = store.list_decisions(q_id) if q_id else []
        item_res = dict((item or {}).get("result") or {})

        repo_raw = str(
            (item or {}).get("repo_path") or wf_res.get("repo_path") or ""
        ).strip()
        branch = str(
            (item or {}).get("branch")
            or wf_res.get("integrated_branch")
            or wf_res.get("branch")
            or ""
        ).strip()
        target_branch = str(
            (item or {}).get("target_branch") or wf_res.get("target_branch") or "main"
        ).strip()

        diff_text = ""
        changed_files: List[str] = list(
            item_res.get("changed_files") or wf_res.get("changed_files") or []
        )
        if repo_raw and branch and branch != target_branch:
            repo_path = Path(repo_raw).resolve()
            if (repo_path / ".git").exists() and store.is_repo_allowed(repo_path, root_path):
                try:
                    merged_sha = str(item_res.get("merged_commit") or wf_res.get("merged_commit") or "").strip()
                    diff_spec = (
                        f"{merged_sha}^1..{merged_sha}"
                        if merged_sha
                        else f"{target_branch}..{branch}"
                    )
                    diff_proc = subprocess.run(
                        ["git", "-C", str(repo_path), "diff", diff_spec],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    if diff_proc.returncode == 0:
                        diff_text = redact_secrets(diff_proc.stdout[:60000])
                    if not changed_files:
                        names_proc = subprocess.run(
                            ["git", "-C", str(repo_path), "diff", "--name-only", diff_spec],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        if names_proc.returncode == 0:
                            changed_files = [
                                f.strip() for f in names_proc.stdout.splitlines() if f.strip()
                            ]
                except Exception:
                    pass

        test_report = (
            item_res.get("landing_test")
            or item_res.get("test")
            or item_res.get("gate_test")
            or wf_res.get("test_report")
            or {}
        )
        reality_scan = item_res.get("reality_scan") or wf_res.get("reality_scan") or {}
        secret_scan = item_res.get("secret_scan") or wf_res.get("secret_scan") or {}

        return jsonify(
            {
                "success": True,
                "workflow": wf,
                "item": item,
                "decisions": decisions,
                "changed_files": changed_files,
                "diff_text": diff_text,
                "test_report": test_report,
                "reality_scan": reality_scan,
                "secret_scan": secret_scan,
            }
        )

    @app.route("/api/planai/workflows/<wf_id>/gate", methods=["POST"])
    def planai_workflow_gate(wf_id: str):
        wf = store.get_workflow(wf_id)
        if not wf:
            return jsonify({"success": False, "error": "Workflow not found"}), 404

        data = request.get_json(silent=True) or {}
        gate_event = str(data.get("event") or "").strip().upper()
        note = str(data.get("note") or data.get("prompt") or "").strip()
        actor = str(data.get("actor") or "human").strip() or "human"

        if gate_event not in {"APPROVE", "FORCE_REVISION", "ABORT"}:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "event must be one of ['ABORT', 'APPROVE', 'FORCE_REVISION']",
                    }
                ),
                400,
            )

        q_id = str(wf.get("queue_item_id") or "").strip()
        item = store.get_item(q_id) if q_id else None
        if item and item["status"] in {"queued", "triaged", "in_progress"}:
            chief.process_once()
            item = store.get_item(q_id)

        if item is None:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Workflow '{wf_id}' has no active review item at gate.",
                    }
                ),
                409,
            )

        if gate_event == "APPROVE":
            if item["status"] != "needs_review":
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Cannot APPROVE item in status '{item['status']}'",
                        }
                    ),
                    409,
                )
            decision = store.add_decision(item["id"], "approve", note=note, actor=actor)
            approved = store.update_item(item["id"], status="approved")
            if approved:
                evolution_engine.observe_decision(approved, decision)
                emit_update(approved)
            chief.process_once()
            final_item = store.get_item(item["id"])
            final_wf = store.get_workflow(wf_id)
            return jsonify(
                {
                    "success": True,
                    "event": "APPROVE",
                    "workflow": final_wf,
                    "item": final_item,
                }
            )

        if gate_event == "FORCE_REVISION":
            if not note:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Revision feedback note is required for FORCE_REVISION.",
                        }
                    ),
                    400,
                )
            if item["status"] != "needs_review":
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Cannot FORCE_REVISION when item status is '{item['status']}'",
                        }
                    ),
                    409,
                )
            decision = store.add_decision(
                item["id"], "request_changes", note=note, actor=actor
            )
            bounced = store.update_item(item["id"], status="changes_requested")
            if bounced:
                evolution_engine.observe_decision(bounced, decision)
                emit_update(bounced)
            try:
                if wf.get("graph_type") == "teamwork":
                    teamwork_orchestrator.resume_revision_async(
                        wf_id=wf_id, item=bounced or item, revision_note=note
                    )
                else:
                    agent_manager.resume_revision_async(
                        wf_id=wf_id, item=bounced or item, revision_note=note
                    )
            except (PermissionError, ValueError) as exc:
                store.update_item(item["id"], status="needs_review")
                return jsonify({"success": False, "error": str(exc)}), 409

            return jsonify(
                {
                    "success": True,
                    "event": "FORCE_REVISION",
                    "workflow": store.get_workflow(wf_id),
                    "item": store.get_item(item["id"]),
                }
            )

        # ABORT
        if item["status"] not in {"needs_review", "queued", "triaged", "in_progress"}:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Cannot ABORT item in status '{item['status']}'",
                    }
                ),
                409,
            )
        decision = store.add_decision(
            item["id"],
            "reject",
            note=note or "Aborted at human gate",
            actor=actor,
        )
        rejected = store.update_item(item["id"], status="rejected")
        if rejected:
            evolution_engine.observe_decision(rejected, decision)
            emit_update(rejected)
        aborted_wf = transition_workflow_gate(
            store,
            wf_id,
            terminal="aborted",
            summary=f"Aborted at Human Gate{f': {note[:80]}' if note else ''}",
            on_event=on_system_event,
        )
        return jsonify(
            {
                "success": True,
                "event": "ABORT",
                "workflow": aborted_wf or store.get_workflow(wf_id),
                "item": rejected,
            }
        )

    @app.route("/api/planai/teamwork", methods=["POST"])
    def planai_start_teamwork():
        data = request.get_json(silent=True) or {}
        goal = str(data.get("goal") or data.get("prompt") or "").strip()
        if not goal:
            return jsonify({"success": False, "error": "Missing required field: goal"}), 400
        project_id = str(data.get("project_id") or data.get("projectId") or "").strip()
        session_key = str(data.get("session_key") or data.get("sessionKey") or "").strip()
        preferred = data.get("services") if isinstance(data.get("services"), list) else []
        timeout_s = int(data.get("timeout") or 180)
        try:
            wf = teamwork_orchestrator.start_teamwork_async(
                goal=goal,
                project_id=project_id,
                preferred_services=[str(s) for s in preferred],
                session_key=session_key,
                timeout_per_agent=timeout_s,
            )
        except (PermissionError, ValueError) as exc:
            return jsonify({"success": False, "error": str(exc)}), 409
        return jsonify({"success": True, "workflow": wf}), 201

    # ---- Evolution & Continuous Learning API ----------------------------

    @app.route("/api/evolution/status", methods=["GET"])
    def evolution_status():
        project_id = request.args.get("project_id") or None
        return jsonify(
            {"success": True, **evolution_engine.status(project_id=project_id)}
        )

    @app.route("/api/evolution/evolve", methods=["POST"])
    def evolution_run():
        data = request.get_json(silent=True) or {}
        project_id = str(data.get("project_id") or "*").strip() or "*"
        reason = str(data.get("reason") or "manual").strip() or "manual"
        result = evolution_engine.run_evolution_cycle(
            project_id=project_id, reason=reason
        )
        return jsonify({"success": True, **result})

    @app.route("/api/evolution/rules", methods=["POST"])
    def evolution_add_rule():
        data = request.get_json(silent=True) or {}
        rule_text = str(data.get("rule_text") or "").strip()
        if not rule_text:
            return jsonify({"success": False, "error": "Missing required field: rule_text"}), 400
        rule = store.upsert_evolution_rule(
            category=str(data.get("category") or "operator_rule").strip(),
            rule_text=rule_text,
            source_type="operator_manual",
            project_id=str(data.get("project_id") or "*").strip() or "*",
        )
        return jsonify({"success": True, "rule": rule}), 201

    # ---- Chromium Prompt API Bridge & PlanAI LLM Core API ---------------

    @app.route("/api/llm/status", methods=["GET"])
    def llm_status():
        return jsonify({"success": True, **llm_manager.full_diagnostics()})

    @app.route("/api/llm/test-prompt", methods=["POST"])
    def llm_test_prompt():
        data = request.get_json(silent=True) or {}
        prompt = str(data.get("prompt") or "Reply in one short sentence confirming PlanAI LLM Core is online.").strip()
        llm = llm_manager.get_llm()
        if llm is None:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": llm_manager.status_label,
                    }
                ),
                409,
            )
        try:
            reply = llm.chat(
                [{"role": "user", "content": prompt}],
                allow_json_mode=False,
            )
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 502
        return jsonify(
            {
                "success": True,
                "reply": reply,
                "provider_used": llm_manager.last_provider_used
                or llm_manager.status_label,
                "diagnostics": llm_manager.full_diagnostics(),
            }
        )

    # ---- Chief-of-Staff Review Queue API --------------------------------

    @app.route("/api/queue/items", methods=["POST"])
    def queue_create_item():
        data = request.get_json(silent=True) or {}
        if not data.get("title"):
            return (
                jsonify({"success": False, "error": "Missing required field: title"}),
                400,
            )
        if data.get("kind") and data["kind"] not in KINDS:
            return (
                jsonify({"success": False, "error": f"kind must be one of {KINDS}"}),
                400,
            )
        item = store.create_item(data)
        emit_update(item)
        return jsonify({"success": True, "item": item}), 201

    @app.route("/api/queue/items", methods=["GET"])
    def queue_list_items():
        items = store.list_items(
            status=request.args.get("status") or None,
            project_id=request.args.get("project_id") or None,
        )
        return jsonify({"success": True, "items": items})

    @app.route("/api/queue/items/<item_id>", methods=["GET"])
    def queue_get_item(item_id: str):
        item = store.get_item(item_id)
        if item is None:
            return jsonify({"success": False, "error": "Item not found"}), 404
        return jsonify(
            {
                "success": True,
                "item": item,
                "decisions": store.list_decisions(item_id),
                "events": store.list_events(item_id),
            }
        )

    @app.route("/api/queue/items/<item_id>/decision", methods=["POST"])
    def queue_decide(item_id: str):
        item = store.get_item(item_id)
        if item is None:
            return jsonify({"success": False, "error": "Item not found"}), 404
        data = request.get_json(silent=True) or {}
        action = data.get("action", "")
        if action not in _DECISION_TO_STATUS:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"action must be one of {sorted(_DECISION_TO_STATUS)}",
                    }
                ),
                400,
            )
        if item["status"] not in _ALLOWED_FROM[action]:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Cannot {action} an item in status '{item['status']}'",
                    }
                ),
                409,
            )
        note_text = str(data.get("note") or "").strip()
        decision = store.add_decision(
            item_id,
            action,
            note=note_text,
            actor=data.get("actor", "human"),
        )
        updated = store.update_item(item_id, status=_DECISION_TO_STATUS[action])
        if updated:
            evolution_engine.observe_decision(updated, decision)
            linked_wf_id = str(updated.get("workflow_id") or "").strip()
            if linked_wf_id:
                if action == "reject":
                    transition_workflow_gate(
                        store,
                        linked_wf_id,
                        terminal="aborted",
                        summary=f"Rejected in review{f': {note_text[:80]}' if note_text else ''}",
                        on_event=on_system_event,
                    )
                elif action == "request_changes" and note_text:
                    linked_wf = store.get_workflow(linked_wf_id)
                    if linked_wf and int(linked_wf.get("round") or 1) < int(
                        linked_wf.get("max_rounds") or 3
                    ):
                        try:
                            if linked_wf.get("graph_type") == "teamwork":
                                teamwork_orchestrator.resume_revision_async(
                                    wf_id=linked_wf_id,
                                    item=updated,
                                    revision_note=note_text,
                                )
                            elif linked_wf.get("graph_type") == "single":
                                agent_manager.resume_revision_async(
                                    wf_id=linked_wf_id,
                                    item=updated,
                                    revision_note=note_text,
                                )
                            updated = store.get_item(item_id) or updated
                        except Exception:
                            pass
        emit_update(updated)
        return jsonify({"success": True, "item": updated})

    @app.route("/api/queue/items/<item_id>/wake", methods=["POST"])
    def queue_wake(item_id: str):
        item = store.get_item(item_id)
        if item is None:
            return jsonify({"success": False, "error": "Item not found"}), 404
        if item["status"] not in {"snoozed", "failed"}:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Cannot wake an item in status '{item['status']}'",
                    }
                ),
                409,
            )
        store.add_event(item_id, "woken", f"Re-queued from {item['status']}")
        updated = store.update_item(item_id, status="queued")
        emit_update(updated)
        return jsonify({"success": True, "item": updated})

    @app.route("/api/queue/stats", methods=["GET"])
    def queue_stats():
        project_id = request.args.get("project_id") or None
        lead_pv = store.get_active_prompt("lead_planner")
        return jsonify(
            {
                "success": True,
                "counts": store.counts(project_id=project_id),
                "chief": {
                    "llm_configured": chief.llm_configured,
                    "llm_status": chief.llm_status,
                    "last_tick_at": chief.last_tick_at,
                },
                "evolution": {
                    "generation": int(lead_pv["generation"]) if lead_pv else 1,
                    "rules_count": len(
                        store.list_evolution_rules(project_id=project_id, active_only=True)
                    ),
                },
                "projects_count": len(store.list_projects()),
            }
        )

    @app.route("/api/queue/evidence/<item_id>/<path:filename>", methods=["GET"])
    def queue_evidence(item_id: str, filename: str):
        evidence_dir = (chief.evidence_root / item_id).resolve()
        requested = (evidence_dir / filename).resolve()
        if evidence_dir not in requested.parents and requested != evidence_dir:
            return jsonify({"success": False, "error": "Invalid evidence path"}), 400
        if not requested.is_file():
            return jsonify({"success": False, "error": "Evidence file not found"}), 404
        return send_from_directory(str(evidence_dir), filename)

    # ---- Multi-agent adapters & runs API --------------------------------

    @app.route("/api/agents", methods=["GET"])
    def agents_list():
        return jsonify(
            {
                "success": True,
                "services": agent_manager.list_services(),
                "default_service": agent_manager.default_dispatch_service(),
                "llm_core": llm_manager.full_diagnostics(),
            }
        )

    @app.route("/api/agents/<service_id>/sessions", methods=["GET"])
    def agents_scan_sessions(service_id: str):
        limit = int(request.args.get("limit") or 15)
        try:
            sessions = agent_manager.scan_sessions(service_id, limit=limit)
        except KeyError as exc:
            return jsonify({"success": False, "error": str(exc)}), 404
        return jsonify({"success": True, "service": service_id, "sessions": sessions})

    @app.route("/api/agents/runs", methods=["GET"])
    def agents_list_runs():
        service = request.args.get("service") or None
        state = request.args.get("state") or None
        project_id = request.args.get("project_id") or None
        workflow_id = request.args.get("workflow_id") or None
        limit = int(request.args.get("limit") or 50)
        return jsonify(
            {
                "success": True,
                "runs": store.list_runs(
                    service=service,
                    state=state,
                    project_id=project_id,
                    workflow_id=workflow_id,
                    limit=limit,
                ),
            }
        )

    @app.route("/api/agents/runs/<run_id>", methods=["GET"])
    def agents_get_run(run_id: str):
        run = store.get_run(run_id)
        if run is None:
            return jsonify({"success": False, "error": "Run not found"}), 404
        return jsonify({"success": True, "run": run})

    @app.route("/api/agents/runs", methods=["POST"])
    def agents_dispatch_run():
        data = request.get_json(silent=True) or {}
        service = (
            str(data.get("service") or "").strip()
            or agent_manager.default_dispatch_service()
        )
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            return (
                jsonify({"success": False, "error": "Missing required field: prompt"}),
                400,
            )
        project_id = str(data.get("project_id") or "").strip()
        cwd_raw = str(data.get("cwd") or "").strip()
        cwd_path: Optional[Path] = None
        if cwd_raw:
            candidate = Path(cwd_raw).resolve()
            if not store.is_repo_allowed(candidate, root_path):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"cwd '{cwd_raw}' is not inside server root '{root_path}' or any registered project.",
                        }
                    ),
                    400,
                )
            cwd_path = candidate
        try:
            run = agent_manager.dispatch_async(
                service=service,
                prompt=prompt,
                cwd=cwd_path,
                branch=str(data.get("branch") or ""),
                model=str(data.get("model") or ""),
                webclaw_session_key=str(data.get("webclaw_session_key") or ""),
                project_id=project_id,
                submit_to_queue=bool(data.get("submit_to_queue", True)),
                queue_title=str(data.get("title") or ""),
                timeout=int(data.get("timeout") or 180),
            )
        except KeyError as exc:
            return jsonify({"success": False, "error": str(exc)}), 404
        except PermissionError as exc:
            return jsonify({"success": False, "error": str(exc)}), 409
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 409
        return jsonify({"success": True, "run": run}), 201

    @app.route("/api/agents/demo-task", methods=["POST"])
    def agents_demo_task():
        data = request.get_json(silent=True) or {}
        service = str(data.get("service") or "").strip() or None
        prompt = str(data.get("prompt") or "").strip()
        webclaw_session_key = str(data.get("webclaw_session_key") or "").strip()
        try:
            run = agent_manager.start_simple_demo_task(
                service=service,
                custom_prompt=prompt,
                webclaw_session_key=webclaw_session_key,
            )
        except KeyError as exc:
            return jsonify({"success": False, "error": str(exc)}), 404
        except PermissionError as exc:
            return jsonify({"success": False, "error": str(exc)}), 409
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 409
        return jsonify({"success": True, "run": run}), 201

    @app.route("/api/agents/runs/<run_id>/stop", methods=["POST"])
    def agents_stop_run(run_id: str):
        updated = agent_manager.stop_run(run_id)
        if updated is None:
            return jsonify({"success": False, "error": "Run not found"}), 404
        return jsonify({"success": True, "run": updated})

    @app.route("/api/ownership", methods=["GET"])
    def ownership_list():
        project_id = request.args.get("project_id") or None
        return jsonify(
            {"success": True, "ownership": store.list_ownership(project_id=project_id)}
        )

    # ---- WebClaw persisted session & stream API -------------------------

    @app.route("/api/webclaw/ping", methods=["GET"])
    def webclaw_ping():
        return jsonify(
            {
                "ok": True,
                "rootPath": str(root_path),
                "defaultProjectId": default_proj["id"],
                "chief": {
                    "llm_configured": chief.llm_configured,
                    "llm_status": chief.llm_status,
                    "last_tick_at": chief.last_tick_at,
                },
                "defaultService": agent_manager.default_dispatch_service(),
            }
        )

    @app.route("/api/webclaw/sessions", methods=["GET", "POST", "PATCH", "DELETE"])
    def webclaw_sessions():
        default_svc = agent_manager.default_dispatch_service()
        if request.method == "GET":
            store.get_or_create_main_chat_session(
                default_service=default_svc, default_project_id=default_proj["id"]
            )
            project_filter = request.args.get("projectId") or None
            return jsonify(
                {
                    "sessions": store.list_chat_sessions(
                        project_id=project_filter, limit=80
                    )
                }
            )

        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            sess = store.create_chat_session(
                {
                    "friendly_id": body.get("friendlyId") or body.get("key") or "",
                    "label": body.get("label") or "",
                    "service": body.get("service") or default_svc,
                    "model": body.get("model") or "",
                    "cwd": body.get("cwd") or "",
                    "project_id": body.get("projectId")
                    or body.get("project_id")
                    or default_proj["id"],
                    "mode": body.get("mode") or "single",
                }
            )
            return jsonify(
                {
                    "ok": True,
                    "sessionKey": sess["key"],
                    "friendlyId": sess["friendlyId"],
                    "entry": sess,
                }
            )

        if request.method == "PATCH":
            body = request.get_json(silent=True) or {}
            ident = str(body.get("sessionKey") or body.get("friendlyId") or "").strip()
            if not ident:
                return jsonify({"ok": False, "error": "sessionKey required"}), 400
            sess = store.update_chat_session(
                ident,
                label=body.get("label"),
                service=body.get("service"),
                model=body.get("model"),
                cwd=body.get("cwd"),
                project_id=body.get("projectId") or body.get("project_id"),
                mode=body.get("mode"),
            )
            if sess is None:
                return jsonify({"ok": False, "error": "session not found"}), 404
            return jsonify({"ok": True, "sessionKey": sess["key"], "entry": sess})

        ident = (
            request.args.get("sessionKey") or request.args.get("friendlyId") or ""
        ).strip()
        if not ident:
            return jsonify({"ok": False, "error": "sessionKey required"}), 400
        deleted = store.delete_chat_session(ident)
        if not deleted:
            return jsonify({"ok": False, "error": "session not found"}), 404
        return jsonify({"ok": True, "sessionKey": ident})

    @app.route("/api/webclaw/history", methods=["GET"])
    def webclaw_history():
        default_svc = agent_manager.default_dispatch_service()
        limit = int(request.args.get("limit") or 200)
        raw_key = (request.args.get("sessionKey") or "").strip()
        friendly_id = (request.args.get("friendlyId") or "").strip()
        ident = raw_key or friendly_id or "main"
        sess = store.get_chat_session(ident)
        if sess is None and ident == "main":
            sess = store.get_or_create_main_chat_session(
                default_service=default_svc, default_project_id=default_proj["id"]
            )
        if sess is None:
            return jsonify({"error": "session not found"}), 404
        return jsonify(
            {
                "sessionKey": sess["key"],
                "sessionId": sess["friendlyId"],
                "service": sess["service"],
                "model": sess["model"],
                "projectId": sess.get("projectId") or default_proj["id"],
                "mode": sess.get("mode") or "single",
                "messages": store.list_chat_messages(sess["key"], limit=limit),
            }
        )

    @app.route("/api/webclaw/send", methods=["POST"])
    def webclaw_send():
        body = request.get_json(silent=True) or {}
        message = str(body.get("message") or "").strip()
        if not message:
            return jsonify({"ok": False, "error": "message required"}), 400

        default_svc = agent_manager.default_dispatch_service()
        raw_key = str(body.get("sessionKey") or "").strip()
        friendly_id = str(body.get("friendlyId") or "").strip()
        ident = raw_key or friendly_id or "main"
        sess = store.get_chat_session(ident)
        if sess is None and ident == "main":
            sess = store.get_or_create_main_chat_session(
                default_service=default_svc, default_project_id=default_proj["id"]
            )
        if sess is None:
            sess = store.create_chat_session(
                {
                    "friendly_id": friendly_id or ident,
                    "service": body.get("service") or default_svc,
                    "project_id": body.get("projectId") or default_proj["id"],
                    "mode": body.get("mode") or "single",
                }
            )

        requested_service = str(
            body.get("service") or sess["service"] or default_svc
        ).strip()
        requested_model = str(body.get("model") or sess["model"] or "").strip()
        requested_mode = str(body.get("mode") or sess.get("mode") or "single").strip()
        requested_project = str(
            body.get("projectId") or sess.get("projectId") or default_proj["id"]
        ).strip()

        sess = (
            store.update_chat_session(
                sess["key"],
                service=requested_service,
                model=requested_model,
                mode=requested_mode,
                project_id=requested_project,
            )
            or sess
        )

        store.add_chat_message(
            session_key=sess["key"],
            role="user",
            text=message,
            details={
                "service": requested_service,
                "model": requested_model,
                "mode": requested_mode,
                "projectId": requested_project,
            },
        )

        if requested_mode == "team":
            try:
                wf = teamwork_orchestrator.start_teamwork_async(
                    goal=message,
                    project_id=requested_project,
                    preferred_services=[requested_service] if requested_service else [],
                    session_key=sess["key"],
                )
            except (PermissionError, ValueError) as exc:
                err_msg = store.add_chat_message(
                    session_key=sess["key"],
                    role="assistant",
                    text=f"Cannot launch PlanAI Team Graph: {exc}",
                    details={"mode": "team"},
                    is_error=True,
                )
                broadcast_sse(
                    "chat",
                    {
                        "runId": "rejected",
                        "sessionKey": sess["key"],
                        "state": "error",
                        "message": err_msg,
                    },
                )
                return jsonify({"ok": False, "error": str(exc)}), 409
            return jsonify(
                {
                    "ok": True,
                    "runId": wf["id"],
                    "workflowId": wf["id"],
                    "sessionKey": sess["key"],
                }
            )

        try:
            run = agent_manager.dispatch_async(
                service=requested_service,
                prompt=message,
                model=requested_model,
                webclaw_session_key=sess["key"],
                project_id=requested_project,
                submit_to_queue=bool(body.get("submitToQueue", True)),
                queue_title=f"[{requested_service}] {message[:60]}",
                is_demo_repo=bool(body.get("isDemoRepo", False)),
            )
        except (KeyError, PermissionError, ValueError) as exc:
            err_msg = store.add_chat_message(
                session_key=sess["key"],
                role="assistant",
                text=f"Cannot dispatch to `{requested_service}`: {exc}",
                details={"service": requested_service},
                is_error=True,
            )
            broadcast_sse(
                "chat",
                {
                    "runId": "rejected",
                    "sessionKey": sess["key"],
                    "state": "error",
                    "message": err_msg,
                },
            )
            return jsonify({"ok": False, "error": str(exc)}), 409

        return jsonify({"ok": True, "runId": run["id"], "sessionKey": sess["key"]})

    @app.route("/api/webclaw/stream", methods=["GET"])
    def webclaw_stream():
        session_key = (request.args.get("sessionKey") or "").strip()
        friendly_id = (request.args.get("friendlyId") or "").strip()
        sub_queue: queue.Queue = queue.Queue(maxsize=256)
        with sse_lock:
            sse_subscribers.append(sub_queue)

        def generate():
            try:
                ident = session_key or friendly_id
                if ident:
                    sess = store.get_chat_session(ident)
                    if sess:
                        initial = {
                            "event": "chat.history",
                            "payload": {
                                "sessionKey": sess["key"],
                                "messages": store.list_chat_messages(
                                    sess["key"], limit=200
                                ),
                            },
                            "seq": 0,
                            "stateVersion": 0,
                        }
                        yield f"data: {json.dumps(initial)}\n\n"
                while True:
                    try:
                        envelope = sub_queue.get(timeout=12.0)
                        yield f"data: {json.dumps(envelope)}\n\n"
                    except queue.Empty:
                        yield "event: ping\ndata: {}\n\n"
            finally:
                with sse_lock:
                    if sub_queue in sse_subscribers:
                        sse_subscribers.remove(sub_queue)

        return Response(
            stream_with_context(generate()),
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    if start_chief:
        thread = threading.Thread(
            target=chief.run_forever, daemon=True, name="chief-of-staff"
        )
        thread.start()
        print(f"[chief] Chief-of-staff agent started. LLM: {chief.llm_status}")

    return store, chief

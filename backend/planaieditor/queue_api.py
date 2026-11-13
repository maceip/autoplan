"""HTTP/SocketIO/SSE API for the chief-of-staff review queue, agent adapters, and WebClaw.

Any agent or UI submits work or dispatches live runs over localhost HTTP:
  - /api/queue/*      -> Chief-of-Staff persistent review queue & decisions
  - /api/agents/*     -> Antigravity, MiniMax, and Xiaomi MiMo probes, session scans, runs, and simple demo task
  - /api/ownership    -> Active workspace ownership claims
  - /api/webclaw/*    -> Persisted sessions, history, real agent send, and SSE stream for maceip/webclaw
"""

import json
import queue
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

from planaieditor.agent_adapters import AgentRunManager
from planaieditor.chief import ChiefOfStaff
from planaieditor.queue_store import KINDS, QueueStore

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

# Any localhost origin may call the API: the server binds to localhost and the
# dev ports drift (3000/3050 WebClaw, 5173 Svelte dev, 5001/5051 backend).
_LOCALHOST_ORIGIN_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d{1,5})?$")


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
        broadcast_sse("queue_updated", {"item_id": item["id"], "status": item["status"], "item": item})
        if socketio is None:
            return
        try:
            socketio.emit(
                "queue_updated",
                {"item_id": item["id"], "status": item["status"], "item": item},
            )
        except Exception:
            pass

    def on_agent_event(event_type: str, payload: Dict[str, Any]) -> None:
        if event_type == "webclaw_chat":
            broadcast_sse("chat", payload)
        elif event_type == "queue_item_created":
            emit_update(payload.get("item"))
        else:
            broadcast_sse(event_type, payload)
        if socketio is not None:
            try:
                socketio.emit("agent_event", {"type": event_type, **payload})
            except Exception:
                pass

    chief = ChiefOfStaff(store, root_path, emit=emit_update)
    agent_manager = AgentRunManager(store, root_path, on_event=on_agent_event)
    chief.rework_dispatcher = agent_manager.start_rework_for_item
    app.config["QUEUE_STORE"] = store
    app.config["CHIEF"] = chief
    app.config["AGENT_MANAGER"] = agent_manager

    @app.after_request
    def add_localhost_cors(response: Response) -> Response:
        origin = request.headers.get("Origin", "")
        if _LOCALHOST_ORIGIN_RE.match(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        return response

    @app.route("/queue", methods=["GET"])
    def queue_page():
        if app.static_folder and (Path(app.static_folder) / "index.html").is_file():
            return send_from_directory(app.static_folder, "index.html")
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Queue UI is served by the frontend dev server in development mode.",
                }
            ),
            404,
        )

    @app.route("/api/queue/items", methods=["POST"])
    def queue_create_item():
        data = request.get_json(silent=True) or {}
        if not data.get("title"):
            return jsonify({"success": False, "error": "Missing required field: title"}), 400
        if data.get("kind") and data["kind"] not in KINDS:
            return jsonify({"success": False, "error": f"kind must be one of {KINDS}"}), 400
        item = store.create_item(data)
        emit_update(item)
        return jsonify({"success": True, "item": item}), 201

    @app.route("/api/queue/items", methods=["GET"])
    def queue_list_items():
        items = store.list_items(status=request.args.get("status") or None)
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
        store.add_decision(
            item_id, action, note=data.get("note", ""), actor=data.get("actor", "human")
        )
        updated = store.update_item(item_id, status=_DECISION_TO_STATUS[action])
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
                    {"success": False, "error": f"Cannot wake an item in status '{item['status']}'"}
                ),
                409,
            )
        store.add_event(item_id, "woken", f"Re-queued from {item['status']}")
        updated = store.update_item(item_id, status="queued")
        emit_update(updated)
        return jsonify({"success": True, "item": updated})

    @app.route("/api/queue/stats", methods=["GET"])
    def queue_stats():
        return jsonify(
            {
                "success": True,
                "counts": store.counts(),
                "chief": {
                    "llm_configured": chief.llm_configured,
                    "llm_status": chief.llm_status,
                    "last_tick_at": chief.last_tick_at,
                },
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
        limit = int(request.args.get("limit") or 50)
        return jsonify(
            {
                "success": True,
                "runs": store.list_runs(service=service, state=state, limit=limit),
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
        service = str(data.get("service") or "").strip() or agent_manager.default_dispatch_service()
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"success": False, "error": "Missing required field: prompt"}), 400
        cwd_raw = str(data.get("cwd") or "").strip()
        cwd_path: Optional[Path] = None
        if cwd_raw:
            candidate = Path(cwd_raw).resolve()
            try:
                candidate.relative_to(root_path)
            except ValueError:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"cwd '{cwd_raw}' must be inside server root '{root_path}'",
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
        return jsonify({"success": True, "ownership": store.list_ownership()})

    # ---- WebClaw persisted session & stream API -------------------------

    @app.route("/api/webclaw/ping", methods=["GET"])
    def webclaw_ping():
        return jsonify(
            {
                "ok": True,
                "rootPath": str(root_path),
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
            store.get_or_create_main_chat_session(default_service=default_svc)
            return jsonify({"sessions": store.list_chat_sessions(limit=50)})

        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            sess = store.create_chat_session(
                {
                    "friendly_id": body.get("friendlyId") or body.get("key") or "",
                    "label": body.get("label") or "",
                    "service": body.get("service") or default_svc,
                    "model": body.get("model") or "",
                    "cwd": body.get("cwd") or "",
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
            )
            if sess is None:
                return jsonify({"ok": False, "error": "session not found"}), 404
            return jsonify({"ok": True, "sessionKey": sess["key"], "entry": sess})

        # DELETE
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
            sess = store.get_or_create_main_chat_session(default_service=default_svc)
        if sess is None:
            return jsonify({"error": "session not found"}), 404
        return jsonify(
            {
                "sessionKey": sess["key"],
                "sessionId": sess["friendlyId"],
                "service": sess["service"],
                "model": sess["model"],
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
            sess = store.get_or_create_main_chat_session(default_service=default_svc)
        if sess is None:
            sess = store.create_chat_session(
                {"friendly_id": friendly_id or ident, "service": body.get("service") or default_svc}
            )

        requested_service = str(body.get("service") or sess["service"] or default_svc).strip()
        requested_model = str(body.get("model") or sess["model"] or "").strip()
        if requested_service != sess["service"] or (requested_model and requested_model != sess["model"]):
            sess = store.update_chat_session(
                sess["key"], service=requested_service, model=requested_model
            ) or sess

        store.add_chat_message(
            session_key=sess["key"],
            role="user",
            text=message,
            details={"service": requested_service, "model": requested_model},
        )

        try:
            run = agent_manager.dispatch_async(
                service=requested_service,
                prompt=message,
                model=requested_model,
                webclaw_session_key=sess["key"],
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
                                "messages": store.list_chat_messages(sess["key"], limit=200),
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
        thread = threading.Thread(target=chief.run_forever, daemon=True, name="chief-of-staff")
        thread.start()
        print(f"[chief] Chief-of-staff agent started. LLM: {chief.llm_status}")

    return store, chief

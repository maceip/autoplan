"""HTTP/SocketIO API for the chief-of-staff review queue.

Any agent the operator uses (Claude Code, Codex, Cursor, cron, a shell
script) submits work with one POST:

  curl -X POST localhost:5001/api/queue/items -H 'Content-Type: application/json' \
    -d '{"source_agent":"claude-code","kind":"code_change","title":"Fix login",
         "repo_path":"/path/repo","branch":"fix-login","test_command":"pytest -q"}'

The chief-of-staff agent triages, tests, and prepares the review
bundle; the operator approves/rejects in the /queue web UI (or with a
POST to /decision); the chief then lands approved code changes.
"""

import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from flask import Flask, jsonify, request, send_from_directory

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


def setup_queue(
    app: Flask,
    socketio: Any,
    root_path: Path,
    start_chief: bool = True,
) -> Tuple[QueueStore, ChiefOfStaff]:
    root_path = Path(root_path).resolve()
    store = QueueStore(root_path / ".planai-queue" / "queue.db")

    def emit_update(item: Optional[Dict[str, Any]]) -> None:
        if socketio is None or item is None:
            return
        try:
            socketio.emit(
                "queue_updated",
                {"item_id": item["id"], "status": item["status"], "item": item},
            )
        except Exception:
            pass

    chief = ChiefOfStaff(store, root_path, emit=emit_update)
    app.config["QUEUE_STORE"] = store
    app.config["CHIEF"] = chief

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

    if start_chief:
        thread = threading.Thread(target=chief.run_forever, daemon=True, name="chief-of-staff")
        thread.start()
        print(f"[chief] Chief-of-staff agent started. LLM: {chief.llm_status}")

    return store, chief

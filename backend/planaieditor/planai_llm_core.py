"""PlanAI LLM Core & Electron Chromium Prompt API Bridge.

Connects PlanAI (`LLMTaskWorker`, `CachedLLMTaskWorker`, `ChiefOfStaff`,
`TeamworkGraph`, and `EvolutionEngine`) to:
  1. Live Electron Chromium `window.LanguageModel` Prompt API sessions bridged
     from the Nucleus macOS desktop app (`provider="chromium-prompt-api"`),
  2. Local on-device Apple Silicon Metal `mlx_lm.server` (`Qwen3-4B-Instruct-2507-4bit`)
     when available on host (`provider="local-mlx"`), or
  3. Explicit `CHIEF_LLM_PROVIDER` / `CHIEF_LLM_MODEL` (`llm_from_config`).

Reports exact, non-fabricated capability telemetry including whether Google's
proprietary `OptGuideOnDeviceModel` Gemini Nano weights exist locally.
"""

from __future__ import annotations

import atexit
import glob
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm_interface import LLMInterface, ListResponse, llm_from_config

_THINK_TAG_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)


def _strip_think_blocks(text: str) -> str:
    if not text:
        return ""
    cleaned = _THINK_TAG_RE.sub("", text).strip()
    return cleaned or text.strip()


def probe_chrome_gemini_nano_weights() -> Dict[str, Any]:
    """Check whether branded Google Chrome has downloaded OptimizationGuide Gemini Nano weights."""
    home = Path.home()
    candidates = sorted(
        glob.glob(
            str(
                home
                / "Library"
                / "Application Support"
                / "Google"
                / "Chrome*"
                / "OptGuideOnDeviceModel"
                / "**"
                / "*weights*"
            ),
            recursive=True,
        )
    )
    opt_dirs = sorted(
        glob.glob(
            str(
                home
                / "Library"
                / "Application Support"
                / "Google"
                / "Chrome*"
                / "OptGuideOnDeviceModel"
            )
        )
    )
    weights_path = candidates[0] if candidates else ""
    return {
        "weights_present": bool(weights_path),
        "weights_path": weights_path,
        "checked_directories": opt_dirs,
        "electron_can_auto_download_gemini_nano": False,
        "reason": (
            "Gemini Nano weights found in local Chrome profile."
            if weights_path
            else "Unbranded Electron Chromium omits Google Chrome's proprietary OptimizationGuide component_updater keys and OptGuideOnDeviceModel weights directory is empty on this host; Electron instead exposes Chromium's Blink LanguageModel Prompt API via session.registerLocalAIHandler(utilityProcess)."
        ),
    }


def find_local_mlx_runtime() -> Dict[str, Any]:
    """Detect real local mlx_lm.server binary and cached HuggingFace MLX model snapshot."""
    if os.environ.get("AUTOPLAN_DISABLE_LOCAL_MLX", "").strip() == "1":
        return {"available": False, "server_bin": "", "model_id": "", "reason": "Disabled via AUTOPLAN_DISABLE_LOCAL_MLX=1"}

    server_bin = shutil.which("mlx_lm.server") or ""
    if not server_bin:
        candidate = Path.home() / ".local" / "bin" / "mlx_lm.server"
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            server_bin = str(candidate)

    preferred_model = os.environ.get(
        "AUTOPLAN_MLX_MODEL", "mlx-community/Qwen3-4B-Instruct-2507-4bit"
    ).strip()
    hf_hub = Path.home() / ".cache" / "huggingface" / "hub"
    slug = "models--" + preferred_model.replace("/", "--")
    snapshots_dir = hf_hub / slug / "snapshots"
    cached = False
    if snapshots_dir.is_dir():
        for snap in snapshots_dir.iterdir():
            if (snap / "config.json").exists():
                cached = True
                break

    available = bool(server_bin and cached)
    return {
        "available": available,
        "server_bin": server_bin,
        "model_id": preferred_model if available else "",
        "cached_snapshot": cached,
        "reason": (
            f"Local Apple Silicon Metal MLX runtime ready ({preferred_model})"
            if available
            else "mlx_lm.server or cached MLX snapshot not present on host",
        ),
    }


class ChromiumPromptBridge:
    """RPC bridge between Python PlanAI workers and Electron Chromium's `window.LanguageModel` Prompt API."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._clients: Dict[str, Dict[str, Any]] = {}
        self._pending_queues: Dict[str, "queue.Queue[Dict[str, Any]]"] = {}
        self._waiters: Dict[str, Dict[str, Any]] = {}
        self.total_bridged_calls = 0
        self.last_call_latency_ms: Optional[float] = None
        self.last_error: str = ""

    def register_client(self, info: Dict[str, Any]) -> Dict[str, Any]:
        client_id = str(info.get("client_id") or f"nucleus_{uuid.uuid4().hex[:8]}")
        now = time.time()
        record = {
            "client_id": client_id,
            "app_name": str(info.get("app_name") or "Nucleus"),
            "electron_version": str(info.get("electron_version") or ""),
            "chrome_version": str(info.get("chrome_version") or ""),
            "language_model_availability": str(
                info.get("language_model_availability") or "unavailable"
            ),
            "local_backend_model": str(info.get("local_backend_model") or ""),
            "registered_at": now,
            "last_seen_at": now,
        }
        with self._lock:
            self._clients[client_id] = record
            if client_id not in self._pending_queues:
                self._pending_queues[client_id] = queue.Queue(maxsize=64)
        return record

    def heartbeat(self, client_id: str, availability: Optional[str] = None) -> bool:
        with self._lock:
            rec = self._clients.get(client_id)
            if not rec:
                return False
            rec["last_seen_at"] = time.time()
            if availability:
                rec["language_model_availability"] = availability
            return True

    def active_client(self) -> Optional[Dict[str, Any]]:
        cutoff = time.time() - 20.0
        with self._lock:
            alive = [
                c
                for c in self._clients.values()
                if float(c["last_seen_at"]) >= cutoff
                and c.get("language_model_availability") == "available"
            ]
            if not alive:
                return None
            return sorted(alive, key=lambda x: float(x["last_seen_at"]), reverse=True)[0]

    def poll_request(self, client_id: str, timeout_s: float = 8.0) -> Optional[Dict[str, Any]]:
        self.heartbeat(client_id)
        with self._lock:
            q = self._pending_queues.get(client_id)
        if q is None:
            return None
        try:
            req = q.get(timeout=timeout_s)
            self.heartbeat(client_id)
            with self._lock:
                slot = self._waiters.get(str(req.get("request_id") or ""))
                if slot is not None and "picked_up" in slot:
                    slot["picked_up"].set()
            return req
        except queue.Empty:
            self.heartbeat(client_id)
            return None

    def unregister_client(self, client_id: str) -> None:
        with self._lock:
            self._clients.pop(client_id, None)
            self._pending_queues.pop(client_id, None)

    def submit_response(
        self,
        request_id: str,
        content: str = "",
        error: str = "",
        metrics: Optional[Dict[str, Any]] = None,
    ) -> bool:
        with self._lock:
            slot = self._waiters.get(request_id)
            if not slot:
                return False
            slot["content"] = content
            slot["error"] = error
            slot["metrics"] = metrics or {}
            slot["event"].set()
            return True

    def execute_prompt(
        self,
        messages: List[Dict[str, str]],
        response_schema_json: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
        timeout_s: float = 60.0,
        pickup_timeout_s: float = 3.0,
    ) -> Dict[str, Any]:
        client = self.active_client()
        if not client:
            raise RuntimeError("No active Electron Chromium LanguageModel bridge connected.")
        client_id = client["client_id"]
        req_id = f"lmreq_{uuid.uuid4().hex[:10]}"
        picked_up_event = threading.Event()
        done_event = threading.Event()
        slot: Dict[str, Any] = {
            "picked_up": picked_up_event,
            "event": done_event,
            "content": "",
            "error": "",
            "metrics": {},
        }
        payload = {
            "request_id": req_id,
            "messages": messages,
            "response_constraint": response_schema_json,
            "temperature": temperature,
            "created_at": time.time(),
        }
        started = time.time()
        with self._lock:
            q = self._pending_queues.get(client_id)
            if q is None:
                raise RuntimeError("Bridge client queue missing.")
            self._waiters[req_id] = slot
            q.put(payload)

        try:
            if not picked_up_event.wait(timeout=pickup_timeout_s):
                self.unregister_client(client_id)
                self.last_error = (
                    f"Chromium LanguageModel client {client_id} did not pick up request within {pickup_timeout_s}s"
                )
                raise TimeoutError(self.last_error)
            if not done_event.wait(timeout=timeout_s):
                self.last_error = f"Timed out after {timeout_s}s waiting for Chromium LanguageModel"
                raise TimeoutError(self.last_error)
            if slot["error"]:
                self.last_error = str(slot["error"])
                raise RuntimeError(self.last_error)
            elapsed_ms = round((time.time() - started) * 1000.0, 1)
            with self._lock:
                self.total_bridged_calls += 1
                self.last_call_latency_ms = elapsed_ms
                self.last_error = ""
            return {
                "content": str(slot["content"]),
                "latency_ms": elapsed_ms,
                "client_id": client_id,
                "metrics": slot["metrics"],
            }
        finally:
            with self._lock:
                self._waiters.pop(req_id, None)

    def status(self) -> Dict[str, Any]:
        active = self.active_client()
        with self._lock:
            return {
                "connected": active is not None,
                "active_client": active,
                "registered_clients_count": len(self._clients),
                "total_bridged_calls": self.total_bridged_calls,
                "last_call_latency_ms": self.last_call_latency_ms,
                "last_error": self.last_error,
            }


class LocalMLXDaemon:
    """Manages a single local `mlx_lm.server` process on localhost for on-device inference."""

    def __init__(self, port: int = 18089) -> None:
        self.port = int(os.environ.get("AUTOPLAN_MLX_PORT") or port)
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        atexit.register(self.stop)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def is_listening(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.4):
                return True
        except OSError:
            return False

    def ensure_running(self, timeout_s: float = 25.0) -> str:
        info = find_local_mlx_runtime()
        if not info["available"]:
            raise RuntimeError(info["reason"])
        model_id = info["model_id"]
        if self.is_listening():
            return model_id
        with self._lock:
            if self.is_listening():
                return model_id
            self._proc = subprocess.Popen(
                [
                    info["server_bin"],
                    "--model",
                    model_id,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self.port),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.is_listening():
                return model_id
            if self._proc and self._proc.poll() is not None:
                raise RuntimeError(f"mlx_lm.server exited early with code {self._proc.returncode}")
            time.sleep(0.25)
        raise TimeoutError(f"mlx_lm.server did not listen on 127.0.0.1:{self.port} within {timeout_s}s")

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> Dict[str, Any]:
        model_id = self.ensure_running()
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90.0) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        choices = raw.get("choices") or []
        content = ""
        if choices:
            content = str((choices[0].get("message") or {}).get("content") or "")
        usage = raw.get("usage") or {}
        return {
            "content": _strip_think_blocks(content),
            "usage": usage,
            "model": model_id,
        }

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass


class AutoplanHybridClient:
    """`LLMInterface`-compatible client routing to Chromium Prompt API first, then local MLX."""

    def __init__(self, bridge: ChromiumPromptBridge, mlx_daemon: LocalMLXDaemon) -> None:
        self.bridge = bridge
        self.mlx_daemon = mlx_daemon
        self.last_provider_used: str = "none"
        self.total_calls: int = 0

    def list(self) -> ListResponse:
        models: List[Dict[str, Any]] = []
        if self.bridge.active_client():
            models.append({"model": "chromium-language-model"})
        mlx_info = find_local_mlx_runtime()
        if mlx_info["available"]:
            models.append({"model": mlx_info["model_id"]})
        return ListResponse(models=models)  # type: ignore[arg-type]

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        schema_obj = kwargs.get("response_schema")
        schema_json: Optional[Dict[str, Any]] = None
        if schema_obj is not None and hasattr(schema_obj, "model_json_schema"):
            schema_json = schema_obj.model_json_schema()
        elif isinstance(kwargs.get("format"), dict):
            schema_json = kwargs["format"]

        prepared_messages = [
            {"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")}
            for m in messages
        ]
        if (kwargs.get("format") == "json" or schema_json) and prepared_messages:
            last_text = prepared_messages[-1]["content"]
            if "JSON" not in last_text and "json" not in last_text:
                prepared_messages[-1] = {
                    **prepared_messages[-1],
                    "content": last_text + "\n\nRespond strictly with valid JSON only (no markdown fences).",
                }

        temperature = 0.2
        if isinstance(kwargs.get("options"), dict) and "temperature" in kwargs["options"]:
            temperature = float(kwargs["options"]["temperature"])

        # 1. Prefer live Electron Chromium `window.LanguageModel` Prompt API bridge when connected!
        if self.bridge.active_client() is not None:
            try:
                bridged = self.bridge.execute_prompt(
                    messages=prepared_messages,
                    response_schema_json=schema_json,
                    temperature=temperature,
                )
                self.last_provider_used = "chromium-prompt-api"
                self.total_calls += 1
                cleaned = _strip_think_blocks(bridged["content"])
                return {
                    "message": {"role": "assistant", "content": cleaned},
                    "usage": bridged.get("metrics", {}).get("usage", {}),
                }
            except Exception as bridge_exc:
                # Fall through to local MLX only if available; otherwise return explicit error
                if not find_local_mlx_runtime()["available"]:
                    return {"error": f"Chromium Prompt API bridge failed: {bridge_exc}"}

        # 2. Local Apple Silicon Metal MLX runtime
        try:
            out = self.mlx_daemon.chat_completion(
                messages=prepared_messages, temperature=temperature
            )
            self.last_provider_used = "local-mlx"
            self.total_calls += 1
            return {
                "message": {"role": "assistant", "content": out["content"]},
                "usage": out.get("usage") or {},
            }
        except Exception as exc:
            return {"error": str(exc)}


class PlanAILLMManager:
    """Central manager providing a live `LLMInterface` to Chief, TeamworkGraph, and EvolutionEngine."""

    def __init__(self, root_path: Path, enable_auto_local: bool = True) -> None:
        self.root_path = Path(root_path).resolve()
        self.bridge = ChromiumPromptBridge()
        self.mlx_daemon = LocalMLXDaemon()
        self.hybrid_client = AutoplanHybridClient(self.bridge, self.mlx_daemon)
        self._explicit_llm: Optional[LLMInterface] = None
        self._explicit_status: str = ""
        self._enable_auto_local = enable_auto_local
        self._init_explicit_env_llm()

    def _init_explicit_env_llm(self) -> None:
        provider = os.environ.get("CHIEF_LLM_PROVIDER", "").strip()
        model = os.environ.get("CHIEF_LLM_MODEL", "").strip()
        if not provider or not model:
            return
        try:
            self._explicit_llm = llm_from_config(provider=provider, model_name=model)  # type: ignore[arg-type]
            self._explicit_status = f"configured: {provider}/{model}"
        except Exception as exc:
            self._explicit_llm = None
            self._explicit_status = f"configuration failed: {exc}"

    def get_llm(self) -> Optional[LLMInterface]:
        if self._explicit_llm is not None:
            return self._explicit_llm
        if self.bridge.active_client() is not None:
            return LLMInterface(
                model_name="chromium-language-model",
                client=self.hybrid_client,
                support_json_mode=True,
                support_structured_outputs=False,
                use_cache=False,
                log_dir=str(self.root_path / ".planai-queue" / "logs"),
            )
        if self._enable_auto_local and find_local_mlx_runtime()["available"]:
            mlx_info = find_local_mlx_runtime()
            return LLMInterface(
                model_name=mlx_info["model_id"],
                client=self.hybrid_client,
                support_json_mode=True,
                support_structured_outputs=False,
                use_cache=False,
                log_dir=str(self.root_path / ".planai-queue" / "logs"),
            )
        return None

    @property
    def is_configured(self) -> bool:
        return self.get_llm() is not None

    @property
    def status_label(self) -> str:
        if self._explicit_llm is not None:
            return self._explicit_status
        active_bridge = self.bridge.active_client()
        if active_bridge is not None:
            backend = active_bridge.get("local_backend_model") or "local-ai"
            return f"chromium-prompt-api ({active_bridge['app_name']} Chrome {active_bridge['chrome_version']} -> {backend})"
        if self._enable_auto_local:
            mlx_info = find_local_mlx_runtime()
            if mlx_info["available"]:
                state = "listening" if self.mlx_daemon.is_listening() else "ready-on-demand"
                return f"local-mlx ({mlx_info['model_id']}, {state})"
        if self._explicit_status:
            return self._explicit_status
        return "not configured (set CHIEF_LLM_PROVIDER + CHIEF_LLM_MODEL or connect Nucleus Chromium Prompt API)"

    def full_diagnostics(self) -> Dict[str, Any]:
        mlx_info = find_local_mlx_runtime()
        return {
            "configured": self.is_configured,
            "status_label": self.status_label,
            "last_provider_used": self.hybrid_client.last_provider_used,
            "total_hybrid_calls": self.hybrid_client.total_calls,
            "chromium_prompt_bridge": self.bridge.status(),
            "gemini_nano_investigation": probe_chrome_gemini_nano_weights(),
            "local_mlx": {
                **mlx_info,
                "listening": self.mlx_daemon.is_listening(),
                "endpoint": f"{self.mlx_daemon.base_url}/v1",
            },
        }

"""PlanAI LLM Core — In-Process macOS SystemLanguageModel (`FoundationModels`).

Connects PlanAI (`LLMTaskWorker`, `CachedLLMTaskWorker`, `ChiefOfStaff`,
`TeamworkGraph`, and `EvolutionEngine`) directly in-process to:
  1. macOS's built-in OS-managed `SystemLanguageModel.default`
     (`FoundationModels.framework` loaded via `ctypes` C-ABI `libapple_fm.dylib`)
     with zero background servers, zero HTTP bridges, and zero Electron machinery, or
  2. Explicit `CHIEF_LLM_PROVIDER` / `CHIEF_LLM_MODEL` (`llm_from_config`).
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm_interface import LLMInterface, ListResponse, llm_from_config

_THINK_TAG_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*([\s\S]*?)\s*```$", re.IGNORECASE)
_SWIFT_BRIDGE_SRC = Path(__file__).with_name("apple_fm_bridge.swift")


def _clean_model_output(text: str, expect_json: bool = False) -> str:
    if not text:
        return ""
    cleaned = _THINK_TAG_RE.sub("", text).strip()
    if expect_json:
        m = _CODE_FENCE_RE.match(cleaned)
        if m:
            cleaned = m.group(1).strip()
    return cleaned or text.strip()


class AppleFoundationModelsRuntime:
    """Loads `apple_fm_bridge.swift` into the Python process via `ctypes.CDLL`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lib: Optional[ctypes.CDLL] = None
        self._dylib_path: str = ""
        self._compile_error: str = ""

    def is_disabled_by_env(self) -> bool:
        return os.environ.get("AUTOPLAN_DISABLE_APPLE_FM", "").strip() == "1"

    def _ensure_loaded(self) -> Optional[ctypes.CDLL]:
        if self.is_disabled_by_env():
            return None
        if sys.platform != "darwin":
            self._compile_error = f"FoundationModels requires macOS (current platform: {sys.platform})"
            return None
        if self._lib is not None:
            return self._lib

        with self._lock:
            if self._lib is not None:
                return self._lib
            if not _SWIFT_BRIDGE_SRC.is_file():
                self._compile_error = f"Missing Swift bridge source: {_SWIFT_BRIDGE_SRC}"
                return None
            swiftc_bin = shutil.which("swiftc")
            if not swiftc_bin:
                self._compile_error = "swiftc not found on host"
                return None

            src_bytes = _SWIFT_BRIDGE_SRC.read_bytes()
            digest = hashlib.sha256(src_bytes).hexdigest()[:12]
            cache_dir = Path(tempfile.gettempdir()) / "autoplan_apple_fm"
            cache_dir.mkdir(parents=True, exist_ok=True)
            dylib_file = cache_dir / f"libapple_fm_{digest}.dylib"

            if not dylib_file.is_file():
                tmp_out = cache_dir / f"libapple_fm_{digest}.{os.getpid()}.tmp.dylib"
                proc = subprocess.run(
                    [
                        swiftc_bin,
                        "-O",
                        "-emit-library",
                        str(_SWIFT_BRIDGE_SRC),
                        "-o",
                        str(tmp_out),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=45,
                )
                if proc.returncode != 0 or not tmp_out.is_file():
                    self._compile_error = (
                        proc.stderr.strip() or f"swiftc exited with {proc.returncode}"
                    )[:400]
                    return None
                tmp_out.replace(dylib_file)

            try:
                lib = ctypes.CDLL(str(dylib_file))
                lib.apple_fm_availability.argtypes = []
                lib.apple_fm_availability.restype = ctypes.c_void_p
                lib.apple_fm_generate.argtypes = [
                    ctypes.c_char_p,
                    ctypes.c_char_p,
                    ctypes.c_double,
                ]
                lib.apple_fm_generate.restype = ctypes.c_void_p
                lib.apple_fm_free.argtypes = [ctypes.c_void_p]
                lib.apple_fm_free.restype = None
                self._lib = lib
                self._dylib_path = str(dylib_file)
                self._compile_error = ""
                return lib
            except Exception as exc:
                self._compile_error = str(exc)
                return None

    def _consume_c_string(self, lib: ctypes.CDLL, ptr: Optional[int]) -> str:
        if not ptr:
            return ""
        try:
            raw = ctypes.string_at(ptr)
            return raw.decode("utf-8", errors="replace")
        finally:
            lib.apple_fm_free(ptr)

    def availability_info(self) -> Dict[str, Any]:
        if self.is_disabled_by_env():
            return {
                "available": False,
                "availability": "disabled",
                "dylib_path": "",
                "reason": "Disabled via AUTOPLAN_DISABLE_APPLE_FM=1",
            }
        lib = self._ensure_loaded()
        if lib is None:
            return {
                "available": False,
                "availability": "unavailable",
                "dylib_path": "",
                "reason": self._compile_error or "FoundationModels bridge unavailable",
            }
        status = self._consume_c_string(lib, lib.apple_fm_availability())
        return {
            "available": status == "available",
            "availability": status,
            "dylib_path": self._dylib_path,
            "model_id": "apple-system-language-model" if status == "available" else "",
            "reason": (
                "In-process macOS FoundationModels (SystemLanguageModel.default) active"
                if status == "available"
                else f"SystemLanguageModel reported {status}"
            ),
        }

    def generate(
        self, instructions: str, prompt: str, temperature: float = 0.2
    ) -> Dict[str, Any]:
        lib = self._ensure_loaded()
        if lib is None:
            raise RuntimeError(
                self._compile_error or "Apple FoundationModels dylib not available"
            )
        started = time.time()
        enc_inst = instructions.encode("utf-8")
        enc_prompt = prompt.encode("utf-8")
        c_temp = float(temperature)

        def _invoke_c_abi() -> str:
            return self._consume_c_string(
                lib,
                lib.apple_fm_generate(enc_inst, enc_prompt, c_temp),
            )

        if "eventlet.patcher" in sys.modules:
            from eventlet import tpool  # type: ignore[import-not-found]

            raw_json = tpool.execute(_invoke_c_abi)
        else:
            raw_json = _invoke_c_abi()
        elapsed_ms = round((time.time() - started) * 1000.0, 1)
        parsed = json.loads(raw_json) if raw_json else {"ok": False, "error": "empty_bridge_response"}
        if not parsed.get("ok"):
            raise RuntimeError(str(parsed.get("error") or "FoundationModels generation failed"))
        return {
            "content": str(parsed.get("content") or ""),
            "latency_ms": elapsed_ms,
        }


_SHARED_APPLE_FM = AppleFoundationModelsRuntime()


class AppleFoundationModelClient:
    """`LLMInterface`-compatible client calling macOS `FoundationModels` in-process."""

    MODEL_ID = "apple-system-language-model"

    def __init__(self, runtime: AppleFoundationModelsRuntime = _SHARED_APPLE_FM) -> None:
        self.runtime = runtime
        self.last_provider_used: str = "none"
        self.last_call_latency_ms: Optional[float] = None
        self.total_calls: int = 0
        self.last_error: str = ""

    def list(self) -> ListResponse:
        info = self.runtime.availability_info()
        models: List[Dict[str, Any]] = []
        if info["available"]:
            models.append({"model": self.MODEL_ID})
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

        expect_json = bool(kwargs.get("format") == "json" or schema_json)

        system_parts: List[str] = []
        turn_parts: List[str] = []
        for msg in messages:
            role = str(msg.get("role") or "user").strip().lower()
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            if role == "system":
                system_parts.append(content)
            elif role == "assistant":
                turn_parts.append(f"Assistant:\n{content}")
            else:
                turn_parts.append(content)

        prompt_text = "\n\n".join(turn_parts).strip()
        if schema_json is not None:
            prompt_text += (
                "\n\nRespond strictly with a single valid JSON object conforming to this JSON Schema "
                "(no markdown fences, no commentary):\n"
                + json.dumps(schema_json)
            )
        elif expect_json and "json" not in prompt_text.lower():
            prompt_text += "\n\nRespond strictly with valid JSON only (no markdown fences)."

        temperature = 0.2
        if isinstance(kwargs.get("options"), dict) and "temperature" in kwargs["options"]:
            temperature = float(kwargs["options"]["temperature"])

        try:
            out = self.runtime.generate(
                instructions="\n\n".join(system_parts),
                prompt=prompt_text,
                temperature=temperature,
            )
            self.last_provider_used = "apple-foundation-models"
            self.last_call_latency_ms = out["latency_ms"]
            self.total_calls += 1
            self.last_error = ""
            cleaned = _clean_model_output(out["content"], expect_json=expect_json)
            return {
                "message": {"role": "assistant", "content": cleaned},
                "usage": {},
            }
        except Exception as exc:
            self.last_error = str(exc)
            return {"error": str(exc)}


class PlanAILLMManager:
    """Central manager providing a live `LLMInterface` to Chief, TeamworkGraph, and EvolutionEngine."""

    def __init__(self, root_path: Path, enable_auto_local: bool = True) -> None:
        self.root_path = Path(root_path).resolve()
        self.apple_client = AppleFoundationModelClient()
        self._explicit_llm: Optional[LLMInterface] = None
        self._explicit_provider_label: str = ""
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
            self._explicit_provider_label = f"{provider}/{model}"
            self._explicit_status = f"configured: {provider}/{model}"
        except Exception as exc:
            self._explicit_llm = None
            self._explicit_status = f"configuration failed: {exc}"

    def get_llm(self) -> Optional[LLMInterface]:
        if self._explicit_llm is not None:
            return self._explicit_llm
        if self._enable_auto_local:
            info = self.apple_client.runtime.availability_info()
            if info["available"]:
                return LLMInterface(
                    model_name=AppleFoundationModelClient.MODEL_ID,
                    client=self.apple_client,
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
    def last_provider_used(self) -> str:
        if self._explicit_llm is not None:
            return self._explicit_provider_label
        return self.apple_client.last_provider_used

    @property
    def status_label(self) -> str:
        if self._explicit_llm is not None:
            return self._explicit_status
        if self._enable_auto_local:
            info = self.apple_client.runtime.availability_info()
            if info["available"]:
                return f"apple-foundation-models ({AppleFoundationModelClient.MODEL_ID}, in-process)"
        if self._explicit_status:
            return self._explicit_status
        return "not configured (set CHIEF_LLM_PROVIDER + CHIEF_LLM_MODEL or enable macOS Apple Intelligence)"

    def full_diagnostics(self) -> Dict[str, Any]:
        fm_info = self.apple_client.runtime.availability_info()
        return {
            "configured": self.is_configured,
            "status_label": self.status_label,
            "last_provider_used": self.last_provider_used,
            "total_calls": self.apple_client.total_calls,
            "last_call_latency_ms": self.apple_client.last_call_latency_ms,
            "last_error": self.apple_client.last_error,
            "apple_foundation_models": fm_info,
        }

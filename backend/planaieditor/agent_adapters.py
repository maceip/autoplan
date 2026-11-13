"""Real adapters and run supervisor for Antigravity, MiniMax, and Xiaomi MiMo.

Implements the Rev 2 adapter contract from documents/universal-system-design.md:
  - probe()          -> live capability, auth, model, and session-store check
  - scan_sessions()  -> read-only scan of the service's local session store
  - dispatch()       -> real headless execution in a target workspace directory
  - stop()           -> terminate an active subprocess and release workspace ownership

No adapter ever claims dispatch capability when headless credentials or binaries
are unavailable; services without headless dispatch credentials report
mode='observe_only' with the exact missing requirement.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from planaieditor.queue_store import QueueStore


def _parse_minimax_yaml(raw: str) -> Dict[str, Any]:
    """Parse ~/.minimax/config.yaml with PyYAML when present, else stdlib indentation parser."""
    try:
        import yaml  # type: ignore[import-untyped]

        loaded = yaml.safe_load(raw)
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass

    result: Dict[str, Any] = {}
    section = ""
    subsection = ""
    options: Dict[str, str] = {}
    models: Dict[str, Dict[str, Any]] = {}
    for raw_line in raw.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if indent == 0 and ":" in stripped:
            k, v = stripped.split(":", 1)
            val = v.strip().strip("'\"")
            if val:
                result[k.strip()] = val
            section = k.strip()
            subsection = ""
        elif section == "provider" and indent == 2 and stripped.startswith("minimax:"):
            section = "provider.minimax"
            subsection = ""
        elif section == "provider" and indent == 2 and ":" in stripped:
            subsection = ""
        elif section == "provider.minimax":
            if indent <= 2 and not stripped.startswith("minimax:"):
                section = ""
                subsection = ""
                continue
            if indent == 4 and ":" in stripped:
                k, _ = stripped.split(":", 1)
                subsection = k.strip()
            elif indent == 6 and subsection == "options" and ":" in stripped:
                k, v = stripped.split(":", 1)
                options[k.strip()] = v.strip().strip("'\"")
            elif indent == 6 and subsection == "models" and stripped.endswith(":"):
                models[stripped[:-1].strip().strip("'\"")] = {}

    if options or models:
        result["provider"] = {"minimax": {"options": options, "models": models}}
    return result

_OUTPUT_TAIL_CHARS = 8000

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._-]{16,}"),
]

# RYAN EXPLICIT MOCK/FALLBACK AUTHORIZATION: "a dummy agent task that spins up an agent with a simple task"
SIMPLE_DEMO_TASK_TITLE = "Simple agent demo task: write task_result.txt"
SIMPLE_DEMO_TASK_TOKEN = "AUTOPLAN_DEMO_OK"


def redact_secrets(text: str) -> str:
    if not text:
        return ""
    cleaned = text
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[REDACTED]", cleaned)
    return cleaned


def _tail(text: str, limit: int = _OUTPUT_TAIL_CHARS) -> str:
    if not text:
        return ""
    redacted = redact_secrets(text)
    return redacted[-limit:] if len(redacted) > limit else redacted


def _ro_sqlite(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)


@dataclass
class AdapterRunResult:
    passed: bool
    exit_code: int
    session_id: str = ""
    model: str = ""
    response_text: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_s: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentAdapter:
    service_id: str = ""
    display_name: str = ""

    def probe(self) -> Dict[str, Any]:
        raise NotImplementedError

    def scan_sessions(self, limit: int = 15) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def dispatch(
        self,
        prompt: str,
        cwd: Path,
        model: str = "",
        timeout: int = 180,
        on_proc: Optional[Callable[[subprocess.Popen], None]] = None,
    ) -> AdapterRunResult:
        raise NotImplementedError


class AntigravityAdapter(AgentAdapter):
    service_id = "antigravity"
    display_name = "Antigravity"

    def __init__(self) -> None:
        self._cached_version: Optional[str] = None

    def _find_binary(self) -> str:
        env_bin = os.environ.get("AGY_BIN", "").strip()
        if env_bin and os.path.isfile(env_bin) and os.access(env_bin, os.X_OK):
            return env_bin
        found = shutil.which("agy")
        if found:
            return found
        fallback = Path.home() / ".local" / "bin" / "agy"
        if fallback.is_file() and os.access(str(fallback), os.X_OK):
            return str(fallback)
        return ""

    def _version(self, binary: str) -> str:
        if not binary:
            return ""
        if self._cached_version is not None:
            return self._cached_version
        try:
            proc = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=5
            )
            self._cached_version = (proc.stdout or proc.stderr).strip().splitlines()[0]
        except Exception:
            self._cached_version = ""
        return self._cached_version or ""

    def _conversation_dbs(self) -> List[str]:
        home = str(Path.home())
        return sorted(
            glob.glob(f"{home}/.gemini/antigravity*/conversations/*.db"),
            key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0.0,
            reverse=True,
        )

    def probe(self) -> Dict[str, Any]:
        binary = self._find_binary()
        dbs = self._conversation_dbs()
        installed = bool(binary) or len(dbs) > 0
        dispatch_ready = bool(binary)
        return {
            "service": self.service_id,
            "display_name": self.display_name,
            "installed": installed,
            "executable": binary,
            "version": self._version(binary),
            "dispatch_ready": dispatch_ready,
            "mode": "dispatch" if dispatch_ready else "observe_only",
            "auth_status": (
                "agy CLI available and ready for headless --print execution"
                if dispatch_ready
                else "agy CLI binary not found on PATH or ~/.local/bin/agy"
            ),
            "default_model": "default",
            "available_models": ["default"],
            "observed_sessions_count": len(dbs),
            "store_path": str(Path.home() / ".gemini" / "antigravity" / "conversations"),
        }

    def scan_sessions(self, limit: int = 15) -> List[Dict[str, Any]]:
        sessions: List[Dict[str, Any]] = []
        for db_file in self._conversation_dbs()[: max(1, int(limit))]:
            path = Path(db_file)
            session_id = path.stem
            mtime = path.stat().st_mtime if path.exists() else 0.0
            preview = ""
            try:
                conn = _ro_sqlite(path)
                try:
                    rows = conn.execute(
                        "SELECT step_payload FROM steps WHERE step_type = 14 ORDER BY idx DESC LIMIT 3"
                    ).fetchall()
                    for (payload,) in rows:
                        if not payload:
                            continue
                        runs = re.findall(rb"[\x20-\x7e\n\t\xc2-\xf4\x80-\xbf]{8,}", payload)
                        decoded = [
                            s.decode("utf-8", "ignore").strip()
                            for s in runs
                            if not re.fullmatch(rb"[\s\S]{0,4}[0-9a-f-]{20,40}", s)
                        ]
                        decoded = [
                            s for s in decoded if len(s) >= 8 and not s.startswith(("<system", "<user_info"))
                        ]
                        if decoded:
                            preview = redact_secrets(max(decoded, key=len))[:200]
                            break
                finally:
                    conn.close()
            except Exception:
                pass
            sessions.append(
                {
                    "service": self.service_id,
                    "session_id": session_id,
                    "cwd": "",
                    "updated_at": mtime,
                    "preview": preview,
                }
            )
        return sessions

    def dispatch(
        self,
        prompt: str,
        cwd: Path,
        model: str = "",
        timeout: int = 180,
        on_proc: Optional[Callable[[subprocess.Popen], None]] = None,
    ) -> AdapterRunResult:
        binary = self._find_binary()
        if not binary:
            raise RuntimeError("Antigravity CLI (agy) is not installed.")
        cwd = Path(cwd).resolve()
        cwd.mkdir(parents=True, exist_ok=True)
        cmd = [
            binary,
            f"--print-timeout={int(timeout)}s",
            "--output-format=json",
            "--dangerously-skip-permissions",
            f"--add-dir={cwd}",
        ]
        if model and model != "default":
            cmd.append(f"--model={model}")
        cmd.append(f"-p={prompt}")

        started = time.time()
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if on_proc:
            on_proc(proc)
        try:
            stdout, stderr = proc.communicate(timeout=timeout + 15)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            return AdapterRunResult(
                passed=False,
                exit_code=-1,
                model=model or "default",
                stdout_tail=_tail(stdout),
                stderr_tail=f"Timed out after {timeout}s\n{_tail(stderr)}",
                duration_s=round(time.time() - started, 2),
            )

        duration = round(time.time() - started, 2)
        parsed: Dict[str, Any] = {}
        for line in reversed((stdout or "").strip().splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    parsed = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue

        status_ok = proc.returncode == 0 and parsed.get("status", "SUCCESS") == "SUCCESS"
        response_text = str(parsed.get("response") or "").strip() or (stdout or "").strip()
        session_id = str(parsed.get("conversation_id") or "")
        metadata: Dict[str, Any] = {}
        if parsed.get("usage"):
            metadata["usage"] = parsed["usage"]
        if parsed.get("num_turns") is not None:
            metadata["num_turns"] = parsed["num_turns"]

        return AdapterRunResult(
            passed=status_ok,
            exit_code=proc.returncode,
            session_id=session_id,
            model=model or "default",
            response_text=redact_secrets(response_text),
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
            duration_s=duration,
            metadata=metadata,
        )


class XiaomiMimoAdapter(AgentAdapter):
    service_id = "xiaomi-mimo"
    display_name = "Xiaomi MiMo"

    def __init__(self) -> None:
        self._cached_version: Optional[str] = None

    def _find_binary(self) -> str:
        env_bin = os.environ.get("MIMO_BIN", "").strip()
        if env_bin and os.path.isfile(env_bin) and os.access(env_bin, os.X_OK):
            return env_bin
        found = shutil.which("mimo")
        if found:
            return found
        fallback = Path.home() / ".mimocode" / "bin" / "mimo"
        if fallback.is_file() and os.access(str(fallback), os.X_OK):
            return str(fallback)
        return ""

    def _version(self, binary: str) -> str:
        if not binary:
            return ""
        if self._cached_version is not None:
            return self._cached_version
        try:
            proc = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=5
            )
            self._cached_version = (proc.stdout or proc.stderr).strip().splitlines()[0]
        except Exception:
            self._cached_version = ""
        return self._cached_version or ""

    def _db_path(self) -> Path:
        return Path.home() / ".local" / "share" / "mimocode" / "mimocode.db"

    def _configured_models(self) -> Tuple_Models:
        """Inspect mimocode auth/config without exposing secret values."""
        models: List[str] = []
        default_model = ""
        auth_notes: List[str] = []

        if os.environ.get("XIAOMI_API_KEY", "").strip() or os.environ.get("MIMO_API_KEY", "").strip():
            models.extend(["xiaomi/mimo-v2.6-flash", "xiaomi/mimo-v2.6-pro"])
            default_model = "xiaomi/mimo-v2.6-flash"
            auth_notes.append("XIAOMI_API_KEY environment variable")

        auth_json = Path.home() / ".local" / "share" / "mimocode" / "auth.json"
        if auth_json.is_file():
            try:
                auth_data = json.loads(auth_json.read_text(errors="ignore"))
                if isinstance(auth_data, dict):
                    for provider_id in auth_data.keys():
                        auth_notes.append(f"auth.json:{provider_id}")
                        if provider_id == "xiaomi" and not default_model:
                            default_model = "xiaomi/mimo-v2.6-flash"
                            models.append("xiaomi/mimo-v2.6-flash")
            except Exception:
                pass

        jsonc_path = Path.home() / ".config" / "mimocode" / "mimocode.jsonc"
        if jsonc_path.is_file():
            raw = jsonc_path.read_text(errors="ignore")
            # Detect configured provider blocks with non-empty apiKey without reading key values.
            for provider_name, candidate_models in [
                ("xiaomi", ["xiaomi/mimo-v2.6-flash", "xiaomi/mimo-v2.6-pro"]),
                ("morph", ["morph/morph-dsv41flash", "morph/morph-v3-fast"]),
            ]:
                if re.search(rf'"{provider_name}"\s*:\s*\{{[\s\S]*?"apiKey"\s*:\s*"[^"]+"', raw):
                    for m in candidate_models:
                        if m not in models:
                            models.append(m)
                    if not default_model:
                        default_model = candidate_models[0]
                    auth_notes.append(f"mimocode.jsonc:{provider_name}")

        override_model = os.environ.get("MIMO_DEFAULT_MODEL", "").strip()
        if override_model:
            default_model = override_model
            if override_model not in models:
                models.insert(0, override_model)

        return default_model, models, auth_notes

    def _session_count(self) -> int:
        db = self._db_path()
        if not db.is_file():
            return 0
        try:
            conn = _ro_sqlite(db)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM session WHERE parent_id IS NULL"
                ).fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()
        except Exception:
            return 0

    def probe(self) -> Dict[str, Any]:
        binary = self._find_binary()
        db = self._db_path()
        default_model, models, auth_notes = self._configured_models()
        installed = bool(binary) or db.is_file()
        dispatch_ready = bool(binary) and bool(default_model)
        return {
            "service": self.service_id,
            "display_name": self.display_name,
            "installed": installed,
            "executable": binary,
            "version": self._version(binary),
            "dispatch_ready": dispatch_ready,
            "mode": "dispatch" if dispatch_ready else "observe_only",
            "auth_status": (
                f"mimo CLI ready ({', '.join(auth_notes)})"
                if dispatch_ready
                else "mimo CLI installed; configure XIAOMI_API_KEY or `mimo providers` credentials for headless dispatch"
            ),
            "default_model": default_model,
            "available_models": models,
            "observed_sessions_count": self._session_count(),
            "store_path": str(db),
        }

    def scan_sessions(self, limit: int = 15) -> List[Dict[str, Any]]:
        db = self._db_path()
        if not db.is_file():
            return []
        sessions: List[Dict[str, Any]] = []
        try:
            conn = _ro_sqlite(db)
            try:
                rows = conn.execute(
                    """SELECT s.id, s.directory, s.title, s.time_updated
                       FROM session s
                       WHERE s.parent_id IS NULL
                       ORDER BY s.time_updated DESC
                       LIMIT ?""",
                    (max(1, int(limit)),),
                ).fetchall()
                for sess_id, directory, title, time_updated in rows:
                    ts = float(time_updated or 0)
                    if ts > 1e12:
                        ts = ts / 1000.0
                    sessions.append(
                        {
                            "service": self.service_id,
                            "session_id": str(sess_id),
                            "cwd": str(directory or ""),
                            "updated_at": ts,
                            "preview": redact_secrets(str(title or ""))[:200],
                        }
                    )
            finally:
                conn.close()
        except Exception:
            pass
        return sessions

    def dispatch(
        self,
        prompt: str,
        cwd: Path,
        model: str = "",
        timeout: int = 180,
        on_proc: Optional[Callable[[subprocess.Popen], None]] = None,
    ) -> AdapterRunResult:
        binary = self._find_binary()
        if not binary:
            raise RuntimeError("Xiaomi MiMo CLI (mimo) is not installed.")
        default_model, _, _ = self._configured_models()
        selected_model = (model or default_model).strip()
        if not selected_model:
            raise RuntimeError(
                "Xiaomi MiMo headless dispatch has no configured model credentials. Set XIAOMI_API_KEY or configure ~/.config/mimocode/mimocode.jsonc."
            )
        cwd = Path(cwd).resolve()
        cwd.mkdir(parents=True, exist_ok=True)
        cmd = [
            binary,
            "run",
            "--dir",
            str(cwd),
            "--dangerously-skip-permissions",
            "--format",
            "json",
            "-m",
            selected_model,
            prompt,
        ]
        started = time.time()
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if on_proc:
            on_proc(proc)
        try:
            stdout, stderr = proc.communicate(timeout=timeout + 15)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            return AdapterRunResult(
                passed=False,
                exit_code=-1,
                model=selected_model,
                stdout_tail=_tail(stdout),
                stderr_tail=f"Timed out after {timeout}s\n{_tail(stderr)}",
                duration_s=round(time.time() - started, 2),
            )

        duration = round(time.time() - started, 2)
        session_id = ""
        text_parts: List[str] = []
        error_messages: List[str] = []
        total_tokens = 0
        total_cost = 0.0
        tool_uses: List[str] = []

        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("sessionID") and not session_id:
                session_id = str(event["sessionID"])
            etype = event.get("type")
            if etype == "error":
                err_obj = event.get("error") or {}
                msg = (
                    (err_obj.get("data") or {}).get("message")
                    or err_obj.get("message")
                    or json.dumps(err_obj)
                )
                error_messages.append(str(msg))
            elif etype == "text":
                part = event.get("part") or {}
                if part.get("text"):
                    text_parts.append(str(part["text"]))
            elif etype == "tool_use":
                part = event.get("part") or {}
                if part.get("tool"):
                    tool_uses.append(str(part["tool"]))
            elif etype == "step_finish":
                part = event.get("part") or {}
                tokens = part.get("tokens") or {}
                total_tokens += int(tokens.get("total") or 0)
                total_cost += float(part.get("cost") or 0.0)

        passed = proc.returncode == 0 and len(error_messages) == 0
        response_text = "\n".join(text_parts).strip()
        if error_messages:
            err_joined = "; ".join(error_messages)
            stderr = f"{stderr}\n{err_joined}".strip()
            if not response_text:
                response_text = f"Error: {err_joined}"

        return AdapterRunResult(
            passed=passed,
            exit_code=proc.returncode if not error_messages else 1,
            session_id=session_id,
            model=selected_model,
            response_text=redact_secrets(response_text),
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
            duration_s=duration,
            metadata={
                "total_tokens": total_tokens,
                "cost_usd": round(total_cost, 6),
                "tools_used": tool_uses,
            },
        )


Tuple_Models = tuple[str, List[str], List[str]]


class MiniMaxAdapter(AgentAdapter):
    service_id = "minimax"
    display_name = "MiniMax"

    def _data_dir(self) -> Path:
        return Path(os.environ.get("MINIMAX_DATA_DIR") or (Path.home() / ".minimax"))

    def _config(self) -> Dict[str, Any]:
        cfg_path = self._data_dir() / "config.yaml"
        if not cfg_path.is_file():
            return {}
        try:
            return _parse_minimax_yaml(cfg_path.read_text(errors="ignore"))
        except Exception:
            return {}

    @staticmethod
    def _clean_api_key(raw_key: str) -> str:
        key = (raw_key or "").strip()
        if not key:
            return ""
        if key.lower() in {
            "sk-xxx",
            "sk-xxxx",
            "your-api-key",
            "your_api_key",
            "placeholder",
            "none",
            "null",
        } or len(key) < 12:
            return ""
        return key

    def _api_credentials(self) -> tuple[str, str, str, List[str]]:
        """Return (api_key, base_url, default_model, available_models)."""
        cfg = self._config()
        providers = cfg.get("provider") or {}
        mm = providers.get("minimax") if isinstance(providers, dict) else {}
        mm = mm if isinstance(mm, dict) else {}
        options = mm.get("options") if isinstance(mm.get("options"), dict) else {}
        models_dict = mm.get("models") if isinstance(mm.get("models"), dict) else {}
        models = [f"minimax/{m}" for m in models_dict.keys()] or [
            "minimax/MiniMax-M3",
            "minimax/MiniMax-M3.1-Flash",
        ]
        default_model = str(cfg.get("defaultModel") or models[0])
        env_key = self._clean_api_key(os.environ.get("MINIMAX_API_KEY", ""))
        cfg_key = self._clean_api_key(str(options.get("apiKey") or ""))
        api_key = env_key or cfg_key
        cfg_base = str(options.get("baseURL") or "").strip()
        if env_key and not os.environ.get("MINIMAX_BASE_URL", "").strip() and "/mavis/" in cfg_base:
            cfg_base = ""
        base_url = (
            os.environ.get("MINIMAX_BASE_URL", "").strip()
            or cfg_base
            or "https://api.minimax.io/anthropic/v1"
        )
        return api_key, base_url, default_model, models

    def _broker_status(self) -> str:
        tool = self._data_dir() / "bin" / "mcode-tools-global"
        if not tool.is_file() or not os.access(str(tool), os.X_OK):
            return ""
        try:
            proc = subprocess.run(
                [str(tool), "auth", "status"],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if proc.returncode == 0 and proc.stdout.strip().startswith("{"):
                payload = json.loads(proc.stdout.strip().splitlines()[-1])
                return str(payload.get("status") or "")
        except Exception:
            pass
        return ""

    def _session_files(self) -> List[str]:
        pattern = str(self._data_dir() / "v2" / "sessions" / "**" / "messages.jsonl")
        return sorted(
            glob.glob(pattern, recursive=True),
            key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0.0,
            reverse=True,
        )

    def probe(self) -> Dict[str, Any]:
        data_dir = self._data_dir()
        app_bundle = Path("/Applications/MiniMax Code.app")
        session_files = self._session_files()
        api_key, base_url, default_model, models = self._api_credentials()
        broker = self._broker_status()
        installed = data_dir.is_dir() or app_bundle.is_dir() or bool(api_key)
        dispatch_ready = bool(api_key)
        if dispatch_ready:
            auth_status = f"MiniMax API key configured ({base_url})"
        elif broker == "authenticated":
            auth_status = (
                "MiniMax Code desktop shared-broker authenticated (observe-only); "
                "set MINIMAX_API_KEY or provider.minimax.options.apiKey in ~/.minimax/config.yaml for headless dispatch"
            )
        else:
            auth_status = (
                "Set MINIMAX_API_KEY or provider.minimax.options.apiKey in ~/.minimax/config.yaml for headless dispatch"
            )
        return {
            "service": self.service_id,
            "display_name": self.display_name,
            "installed": installed,
            "executable": str(app_bundle) if app_bundle.is_dir() else "",
            "version": "MiniMax Code v2" if data_dir.is_dir() else "",
            "dispatch_ready": dispatch_ready,
            "mode": "dispatch" if dispatch_ready else "observe_only",
            "auth_status": auth_status,
            "default_model": default_model,
            "available_models": models,
            "observed_sessions_count": len(session_files),
            "store_path": str(data_dir / "v2" / "sessions"),
        }

    def scan_sessions(self, limit: int = 15) -> List[Dict[str, Any]]:
        sessions: List[Dict[str, Any]] = []
        for filepath in self._session_files():
            if len(sessions) >= max(1, int(limit)):
                break
            path = Path(filepath)
            session_id = path.parent.name
            mtime = path.stat().st_mtime if path.exists() else 0.0
            is_root: Optional[bool] = None
            last_user_text = ""
            try:
                with path.open("r", errors="ignore") as handle:
                    for line in handle:
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        msg = entry.get("message") or {}
                        if msg.get("role") != "user":
                            continue
                        content = msg.get("content")
                        parts = (
                            content
                            if isinstance(content, list)
                            else [{"type": "text", "text": content}]
                        )
                        for part in parts:
                            text = part.get("text") if isinstance(part, dict) else ""
                            if not text:
                                continue
                            if is_root is None and "SESSION ROLE:" in text:
                                is_root = "SESSION ROLE: root" in text
                            if is_root is False:
                                break
                            if not text.startswith(("<system-reminder", "SESSION ROLE:")):
                                last_user_text = text.strip()
                        if is_root is False:
                            break
            except Exception:
                continue
            if is_root is False:
                continue
            sessions.append(
                {
                    "service": self.service_id,
                    "session_id": session_id,
                    "cwd": "",
                    "updated_at": mtime,
                    "preview": redact_secrets(last_user_text)[:200],
                }
            )
        return sessions

    def _safe_workspace_path(self, cwd: Path, rel_path: str) -> Path:
        candidate = (cwd / rel_path).resolve()
        cwd_resolved = cwd.resolve()
        if candidate != cwd_resolved and cwd_resolved not in candidate.parents:
            raise ValueError(f"Path '{rel_path}' escapes workspace '{cwd_resolved}'")
        return candidate

    def dispatch(
        self,
        prompt: str,
        cwd: Path,
        model: str = "",
        timeout: int = 180,
        on_proc: Optional[Callable[[subprocess.Popen], None]] = None,
    ) -> AdapterRunResult:
        api_key, base_url, default_model, _ = self._api_credentials()
        if not api_key:
            raise RuntimeError(
                "MiniMax headless dispatch requires MINIMAX_API_KEY or provider.minimax.options.apiKey in ~/.minimax/config.yaml."
            )
        selected = (model or default_model).strip()
        model_id = selected.split("/", 1)[1] if "/" in selected else selected
        cwd = Path(cwd).resolve()
        cwd.mkdir(parents=True, exist_ok=True)
        url = f"{base_url.rstrip('/')}/messages"

        tools = [
            {
                "name": "write_file",
                "description": "Write UTF-8 text content to a relative file path inside the workspace.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "read_file",
                "description": "Read UTF-8 text content from a relative file path inside the workspace.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        ]

        messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]
        started = time.time()
        session_id = f"minimax_{uuid.uuid4().hex[:10]}"
        final_texts: List[str] = []

        for _turn in range(6):
            body = json.dumps(
                {
                    "model": model_id,
                    "max_tokens": 2048,
                    "messages": messages,
                    "tools": tools,
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "Authorization": f"Bearer {api_key}",
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="ignore")
                return AdapterRunResult(
                    passed=False,
                    exit_code=1,
                    session_id=session_id,
                    model=selected,
                    response_text=f"MiniMax HTTP {exc.code}: {redact_secrets(err_body)}",
                    stderr_tail=_tail(err_body),
                    duration_s=round(time.time() - started, 2),
                )

            blocks = payload.get("content") or []
            messages.append({"role": "assistant", "content": blocks})
            tool_results: List[Dict[str, Any]] = []
            for block in blocks:
                if block.get("type") == "text" and block.get("text"):
                    final_texts.append(str(block["text"]))
                elif block.get("type") == "tool_use":
                    tname = block.get("name")
                    tinput = block.get("input") or {}
                    tid = block.get("id") or uuid.uuid4().hex[:8]
                    try:
                        if tname == "write_file":
                            target = self._safe_workspace_path(cwd, str(tinput["path"]))
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_text(str(tinput["content"]), encoding="utf-8")
                            out_text = f"Wrote {len(str(tinput['content']))} chars to {tinput['path']}"
                        elif tname == "read_file":
                            target = self._safe_workspace_path(cwd, str(tinput["path"]))
                            out_text = target.read_text(encoding="utf-8")
                        else:
                            out_text = f"Unsupported tool: {tname}"
                        tool_results.append(
                            {"type": "tool_result", "tool_use_id": tid, "content": out_text}
                        )
                    except Exception as tool_exc:
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tid,
                                "content": str(tool_exc),
                                "is_error": True,
                            }
                        )
            if not tool_results:
                break
            messages.append({"role": "user", "content": tool_results})

        joined = "\n".join(final_texts).strip()
        return AdapterRunResult(
            passed=True,
            exit_code=0,
            session_id=session_id,
            model=selected,
            response_text=redact_secrets(joined),
            stdout_tail=_tail(joined),
            duration_s=round(time.time() - started, 2),
        )


class AgentRunManager:
    """Supervises adapter probes, session scans, live runs, and simple demo tasks."""

    def __init__(
        self,
        store: QueueStore,
        root_path: Path,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        self.store = store
        self.root_path = Path(root_path).resolve()
        self.demo_workspaces_root = self.root_path / ".planai-queue" / "demo-workspaces"
        self._on_event = on_event or (lambda _evt, _payload: None)
        self.adapters: Dict[str, AgentAdapter] = {
            "antigravity": AntigravityAdapter(),
            "minimax": MiniMaxAdapter(),
            "xiaomi-mimo": XiaomiMimoAdapter(),
        }
        self._active_procs: Dict[str, subprocess.Popen] = {}
        self._proc_lock = threading.Lock()
        self._recover_interrupted_runs()

    def _recover_interrupted_runs(self) -> None:
        for run in self.store.list_runs(state="running", limit=200):
            self.store.release_ownership(run["id"])
            self.store.update_run(
                run["id"],
                state="failed",
                stderr_tail=(run.get("stderr_tail") or "") + "\nInterrupted by server restart.",
                finished_at=time.time(),
            )

    def get_adapter(self, service: str) -> AgentAdapter:
        adapter = self.adapters.get(service)
        if adapter is None:
            raise KeyError(
                f"Unknown agent service '{service}'. Supported: {sorted(self.adapters.keys())}"
            )
        return adapter

    def list_services(self) -> List[Dict[str, Any]]:
        active_by_service: Dict[str, int] = {}
        for run in self.store.list_runs(state="running", limit=100):
            svc = run["service"]
            active_by_service[svc] = active_by_service.get(svc, 0) + 1
        services: List[Dict[str, Any]] = []
        for service_id in ("antigravity", "minimax", "xiaomi-mimo"):
            info = self.adapters[service_id].probe()
            info["active_runs"] = active_by_service.get(service_id, 0)
            services.append(info)
        return services

    def default_dispatch_service(self) -> str:
        for svc in ("antigravity", "xiaomi-mimo", "minimax"):
            if self.adapters[svc].probe().get("dispatch_ready"):
                return svc
        return "antigravity"

    def scan_sessions(self, service: str, limit: int = 15) -> List[Dict[str, Any]]:
        return self.get_adapter(service).scan_sessions(limit=limit)

    def _git(self, repo: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def _init_demo_repo(self, run_id: str, service: str) -> tuple[Path, str]:
        repo = (self.demo_workspaces_root / run_id).resolve()
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "init", "-b", "main", str(repo)],
            check=True,
            capture_output=True,
            text=True,
        )
        self._git(repo, "config", "user.email", "autoplan@local.invalid")
        self._git(repo, "config", "user.name", "AutoPlan Supervisor")
        (repo / ".gitignore").write_text(".mimocode/\n.DS_Store\n", encoding="utf-8")
        (repo / "README.md").write_text(
            f"# AutoPlan Demo Workspace ({run_id})\n\nTarget service: {service}\n",
            encoding="utf-8",
        )
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-m", "chore: initialize isolated demo workspace")
        branch = f"agent/simple-task-{run_id[-6:]}"
        self._git(repo, "checkout", "-b", branch)
        return repo, branch

    def _finalize_demo_repo_commit(
        self, repo: Path, branch: str, run_id: str, service: str
    ) -> tuple[bool, str, str]:
        head_branch = self._git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        active_branch = (
            head_branch if head_branch and head_branch not in {"main", "HEAD"} else branch
        )
        if head_branch == "main":
            self._git(repo, "checkout", active_branch)

        self._git(repo, "add", "-A")
        diff_cached = self._git(repo, "diff", "--cached", "--name-only")
        changed_files = [f.strip() for f in diff_cached.stdout.splitlines() if f.strip()]
        if changed_files:
            self._git(
                repo,
                "commit",
                "-m",
                f"feat({service}): complete simple task for {run_id}",
            )

        ahead_raw = self._git(repo, "rev-list", "--count", f"main..{active_branch}").stdout.strip()
        try:
            ahead_count = int(ahead_raw or "0")
        except ValueError:
            ahead_count = 0

        if ahead_count <= 0:
            self._git(repo, "checkout", "main")
            self._git(repo, "clean", "-fd")
            return False, "", active_branch

        sha = self._git(repo, "rev-parse", active_branch).stdout.strip()
        self._git(repo, "checkout", "main")
        # Remove untracked agent scratch dirs so Chief's clean-tree check passes on main.
        self._git(repo, "clean", "-fd")
        return True, sha, active_branch

    def dispatch_async(
        self,
        *,
        service: str,
        prompt: str,
        cwd: Optional[Path] = None,
        branch: str = "",
        model: str = "",
        webclaw_session_key: str = "",
        submit_to_queue: bool = False,
        queue_title: str = "",
        is_demo_repo: bool = False,
        timeout: int = 180,
    ) -> Dict[str, Any]:
        adapter = self.get_adapter(service)
        probe = adapter.probe()
        if not probe.get("dispatch_ready"):
            raise PermissionError(probe.get("auth_status") or f"{service} is observe-only")

        run_id = f"run_{uuid.uuid4().hex[:10]}"
        if is_demo_repo:
            workspace_dir, branch_name = self._init_demo_repo(run_id, service)
        else:
            workspace_dir = (
                Path(cwd).resolve()
                if cwd
                else (self.demo_workspaces_root / run_id).resolve()
            )
            workspace_dir.mkdir(parents=True, exist_ok=True)
            branch_name = branch or "workspace"

        self.store.claim_ownership(
            repo=str(workspace_dir),
            worktree=str(workspace_dir),
            branch=branch_name,
            service=service,
            run_id=run_id,
        )

        effective_prompt = prompt.replace("{WORKSPACE_DIR}", str(workspace_dir))
        selected_model = model or str(probe.get("default_model") or "")
        run = self.store.create_run(
            {
                "id": run_id,
                "service": service,
                "model": selected_model,
                "prompt": redact_secrets(effective_prompt),
                "cwd": str(workspace_dir),
                "branch": branch_name,
                "webclaw_session_key": webclaw_session_key,
                "state": "running",
                "metadata": {"is_demo_repo": is_demo_repo},
            }
        )
        self._on_event("run_started", {"run": run})

        if webclaw_session_key:
            self._on_event(
                "webclaw_chat",
                {
                    "runId": run_id,
                    "sessionKey": webclaw_session_key,
                    "state": "delta",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Running `{service}` ({selected_model or 'default'}) in `{workspace_dir}`…",
                            }
                        ],
                        "timestamp": int(time.time() * 1000),
                    },
                },
            )

        def _worker() -> None:
            def _register_proc(proc: subprocess.Popen) -> None:
                with self._proc_lock:
                    self._active_procs[run_id] = proc

            try:
                result = adapter.dispatch(
                    prompt=effective_prompt,
                    cwd=workspace_dir,
                    model=selected_model,
                    timeout=timeout,
                    on_proc=_register_proc,
                )
            except Exception as exc:
                result = AdapterRunResult(
                    passed=False,
                    exit_code=1,
                    model=selected_model,
                    response_text=f"Dispatch error: {exc}",
                    stderr_tail=str(exc),
                )
            finally:
                with self._proc_lock:
                    self._active_procs.pop(run_id, None)
                self.store.release_ownership(run_id)

            current = self.store.get_run(run_id)
            if current and current["state"] == "stopped":
                return

            committed = False
            commit_sha = ""
            queue_item_id = ""
            final_branch = branch_name
            if is_demo_repo and result.passed:
                committed, commit_sha, final_branch = self._finalize_demo_repo_commit(
                    workspace_dir, branch_name, run_id, service
                )
                if committed and submit_to_queue:
                    q_item = self.store.create_item(
                        {
                            "source_agent": service,
                            "kind": "code_change",
                            "title": queue_title or f"[{service}] {SIMPLE_DEMO_TASK_TITLE}",
                            "body": (
                                f"Agent `{service}` (`{result.model}`) completed run `{run_id}` "
                                f"in `{workspace_dir}` on branch `{final_branch}` (commit `{commit_sha[:10]}`).\n\n"
                                f"Agent response:\n{result.response_text}"
                            ),
                            "repo_path": str(workspace_dir),
                            "branch": final_branch,
                            "target_branch": "main",
                            "test_command": f"git grep -q {SIMPLE_DEMO_TASK_TOKEN} {final_branch} -- task_result.txt",
                            "priority": 25,
                        }
                    )
                    queue_item_id = q_item["id"]
                    self._on_event("queue_item_created", {"item": q_item})
            elif submit_to_queue and result.passed:
                q_item = self.store.create_item(
                    {
                        "source_agent": service,
                        "kind": "task",
                        "title": queue_title or f"[{service}] {prompt[:64]}",
                        "body": (
                            f"Run `{run_id}` (`{service}` / `{result.model}`)\n\n"
                            f"{result.response_text}"
                        ),
                        "priority": 15,
                    }
                )
                queue_item_id = q_item["id"]
                self._on_event("queue_item_created", {"item": q_item})

            meta = dict(result.metadata or {})
            meta["is_demo_repo"] = is_demo_repo
            meta["duration_s"] = result.duration_s
            if commit_sha:
                meta["branch_commit"] = commit_sha

            final_state = "succeeded" if result.passed else "failed"
            updated_run = self.store.update_run(
                run_id,
                session_id=result.session_id,
                queue_item_id=queue_item_id,
                state=final_state,
                exit_code=result.exit_code,
                response_text=result.response_text,
                stdout_tail=result.stdout_tail,
                stderr_tail=result.stderr_tail,
                metadata=meta,
                finished_at=time.time(),
            )
            self._on_event("run_updated", {"run": updated_run})

            if webclaw_session_key:
                summary_lines = [result.response_text or "(no text output)"]
                if commit_sha:
                    summary_lines.append(
                        f"\n\nCommitted `{commit_sha[:10]}` on `{branch_name}` in `{workspace_dir}`."
                    )
                if queue_item_id:
                    summary_lines.append(
                        f"Queued for Chief of Staff review as item `{queue_item_id}`."
                    )
                if not result.passed and result.stderr_tail:
                    summary_lines.append(f"\n\nStderr:\n```\n{result.stderr_tail[-800:]}\n```")

                saved_msg = self.store.add_chat_message(
                    session_key=webclaw_session_key,
                    role="assistant",
                    text="\n".join(summary_lines).strip(),
                    details={
                        "runId": run_id,
                        "service": service,
                        "model": result.model,
                        "sessionId": result.session_id,
                        "queueItemId": queue_item_id,
                        "exitCode": result.exit_code,
                        "durationS": result.duration_s,
                    },
                    is_error=not result.passed,
                )
                self._on_event(
                    "webclaw_chat",
                    {
                        "runId": run_id,
                        "sessionKey": webclaw_session_key,
                        "state": "final" if result.passed else "error",
                        "message": saved_msg,
                    },
                )

        thread = threading.Thread(target=_worker, daemon=True, name=f"agent-run-{run_id}")
        thread.start()
        return run

    def start_simple_demo_task(
        self,
        service: Optional[str] = None,
        custom_prompt: str = "",
        webclaw_session_key: str = "",
    ) -> Dict[str, Any]:
        chosen_service = (service or "").strip() or self.default_dispatch_service()
        resolved_session_key = (webclaw_session_key or "").strip()
        if resolved_session_key and resolved_session_key != "new":
            sess = self.store.get_chat_session(resolved_session_key)
            if sess is None and resolved_session_key == "main":
                sess = self.store.get_or_create_main_chat_session(default_service=chosen_service)
            if sess is not None:
                resolved_session_key = sess["key"]
        elif resolved_session_key == "new":
            resolved_session_key = ""

        prompt = custom_prompt.strip() or (
            f"Create the file '{{WORKSPACE_DIR}}/task_result.txt' inside workspace directory '{{WORKSPACE_DIR}}' "
            f"containing exact single-line text '{SIMPLE_DEMO_TASK_TOKEN} generated by {chosen_service}' "
            f"and then reply with a short one-sentence confirmation. Do not write outside '{{WORKSPACE_DIR}}'."
        )
        if resolved_session_key:
            self.store.add_chat_message(
                session_key=resolved_session_key,
                role="user",
                text=f"[Simple Task → {chosen_service}] {prompt}",
                details={"service": chosen_service, "kind": "demo_task"},
            )
        return self.dispatch_async(
            service=chosen_service,
            prompt=prompt,
            webclaw_session_key=resolved_session_key,
            submit_to_queue=True,
            queue_title=f"[{chosen_service}] {SIMPLE_DEMO_TASK_TITLE}",
            is_demo_repo=True,
        )

    def stop_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        run = self.store.get_run(run_id)
        if not run:
            return None
        with self._proc_lock:
            proc = self._active_procs.pop(run_id, None)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        self.store.release_ownership(run_id)
        updated = self.store.update_run(
            run_id,
            state="stopped",
            finished_at=time.time(),
        )
        self._on_event("run_updated", {"run": updated})
        return updated

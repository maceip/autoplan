"""Native Jet Ski Runtime Engine for AutoPlan (`jetski_runtime.py`).

Incorporates the local execution, safety vetting, trajectory, multi-agent swarm board,
plan/execute state-machine, dual-track memory diffing (`CONTENT_DIFF`), `.agents/skills`
skill accumulation, and static Go Mach-O surface inspection modules from the Jet Ski
reference suite into AutoPlan's evolutionary PlanAI workflow engine:

1. Model & Cascade Config (`MODEL_TIERS`, `Model`, `PlanAIModelAdapter`, `CascadeConfig`,
   `AdminSettings`, `override_cascade_config`)
2. Three-Layer Safety Guardrails (`RISK_SIGNALS` A-M, `Fastpath`, `MonitorRunner`,
   `PolicyGuardian`, `evaluate_diff_with_policy_guardian`)
3. Revertible Audit Trajectories (`STEP_TYPES`, `Step`, `Trajectory`, `revert_preview`,
   `revert_to_step`, `resident_trajectory_count`)
4. Plan/Execute Protocol (`PlanExecutor`, `HandoffStep`, `HandbackStep`, `ReviewStep`,
   `GateHook`, `HandoffHook`, `ReviewHook`, `ProtocolSection`)
5. Multi-Agent Spawn Policy, `SubagentHub` & Cursor-Tracked Swarm `Board`
   (`WHEN_TO_SPAWN`, `WHEN_NOT_TO_SPAWN`, `decide_spawn`, `SubagentSpec`, `CascadeManager`)
6. Dual-Track Memory `CONTENT_DIFF` & `SkillAccumulator` (`.agents/skills/<slug>/SKILL.md`
   + `.agents/skills.json`)
7. Pure-stdlib Read-Only Go Mach-O `pclntab` & Embedded `.proto` Surface Inspector
   (`classify_go_symbol_family`, `inspect_go_macho_surface`)
"""

from __future__ import annotations

import collections
import difflib
import itertools
import json
import os
import re
import shlex
import struct
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable


# ===========================================================================
# 1. Model Interface & PlanAI Adapter (`jetski_local/model.py`)
# ===========================================================================

MODEL_TIERS: Tuple[str, ...] = ("inherit", "flash_lite", "flash", "pro")
UNSPECIFIED = "__unspecified__"


@dataclass(frozen=True)
class ModelRequest:
    """A single completion request issued by Cortex or PolicyGuardian."""

    system: str = ""
    prompt: str = ""
    tier: str = "inherit"
    thinking_level: str = "MODEL_DEFAULT"
    max_output_tokens: int = 32768


@dataclass
class ModelResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    tier_used: str = "inherit"
    finish_reason: str = "STOP"


@runtime_checkable
class Model(Protocol):
    """Provider-agnostic completion protocol used by Cortex and PolicyGuardian."""

    def complete(self, req: ModelRequest) -> ModelResponse: ...


@dataclass
class FunctionModel:
    """Adapter around a plain callable -> Model."""

    fn: Callable[[ModelRequest], str]
    name: str = "function-model"

    def complete(self, req: ModelRequest) -> ModelResponse:
        text = self.fn(req)
        return ModelResponse(
            text=text,
            input_tokens=len(req.system) + len(req.prompt),
            output_tokens=len(text),
            tier_used=req.tier,
        )


@dataclass
class ScriptedModel:
    """Replays a fixed queue of responses for deterministic tests."""

    responses: List[str] = field(default_factory=list)
    name: str = "scripted"
    _i: int = 0

    def complete(self, req: ModelRequest) -> ModelResponse:
        text = self.responses[self._i] if self._i < len(self.responses) else ""
        self._i += 1
        return ModelResponse(
            text=text,
            input_tokens=len(req.system) + len(req.prompt),
            output_tokens=len(text),
            tier_used=req.tier,
        )


class PlanAIModelAdapter:
    """Bridges AutoPlan's `PlanAILLMManager` (`apple-foundation-models` / `chromium-prompt-api`) to `Model`."""

    def __init__(self, llm_manager: Any) -> None:
        self.llm_manager = llm_manager

    def complete(self, req: ModelRequest) -> ModelResponse:
        llm = self.llm_manager.get_llm() if self.llm_manager is not None else None
        if llm is None:
            return ModelResponse(
                text="",
                input_tokens=len(req.system) + len(req.prompt),
                output_tokens=0,
                tier_used=req.tier,
                finish_reason="UNAVAILABLE",
            )
        messages: List[Dict[str, str]] = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.prompt})
        reply = str(llm.chat(messages, allow_json_mode=False) or "")
        return ModelResponse(
            text=reply,
            input_tokens=len(req.system) + len(req.prompt),
            output_tokens=len(reply),
            tier_used=req.tier,
        )


# ===========================================================================
# 2. Cascade & Enterprise Admin Configuration (`jetski_local/config.py`)
# ===========================================================================


@dataclass
class ToolConfig:
    view_file_enabled: bool = True
    code_search_enabled: bool = True
    run_command_enabled: bool = True
    forbid_search_commands: bool = False
    search_fallback_mode: str = "SEARCH_FALLBACK_UNSPECIFIED"
    subagent_model_options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BuiltinSubagents:
    browser: bool = True
    browser_vision: bool = True
    browser_webview: bool = True
    browser_auto_invoke: bool = True
    computer: bool = False
    image_generator: bool = False
    owl: bool = False
    teamwork: bool = True
    subagent_tools: bool = True


@dataclass
class PlannerConfig:
    tool_config: ToolConfig = field(default_factory=ToolConfig)
    builtin_subagents: BuiltinSubagents = field(default_factory=BuiltinSubagents)
    plan_execute_enabled: bool = True
    parent_model: str = UNSPECIFIED
    max_output_tokens: int = 32768


@dataclass
class CascadeConfig:
    planner: PlannerConfig = field(default_factory=PlannerConfig)
    permission_preset: str = "ask"
    conversation_scoped_permissions: bool = True
    cost_accounting: bool = True
    rehydration: bool = True
    sensitivity_level: str = "UNSPECIFIED"
    subagent_interaction_timeout_s: int = 600
    native_swarm_enabled: bool = True
    sandbox_mode_enabled: bool = True
    terminal_auto_execution_policy: str = "ask"
    outside_workspace_file_access_policy: str = "deny"

    def resolved_model_tier(self, requested: str) -> str:
        if requested not in MODEL_TIERS:
            raise ValueError(
                f"unsupported model: {requested!r}, must be one of {MODEL_TIERS}"
            )
        if requested != "inherit":
            return requested
        parent = self.planner.parent_model
        if parent == UNSPECIFIED:
            raise LookupError(
                "subagent requested inherit but the parent plan model is unspecified"
            )
        return parent


@dataclass
class GatewayConfig:
    enabled: bool = False
    route_web_fetch: bool = False
    base_url: Optional[str] = None
    client_cert_path: Optional[str] = None
    client_key_path: Optional[str] = None

    def __post_init__(self) -> None:
        if bool(self.client_cert_path) != bool(self.client_key_path):
            raise ValueError(
                "gateway clientCertPath and clientKeyPath must be set together"
            )


@dataclass
class AdminSettings:
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    admin_file_sets_models: bool = False
    pinned_model_ids: Tuple[str, ...] = ()
    browser_disabled: bool = False
    marketplace_disabled: bool = False
    plugins_disabled: bool = False
    mcp_enabled: bool = True
    mcp_allowlist: Tuple[str, ...] = ()
    url_blocklist: Tuple[str, ...] = ()
    permission_preset_locked: bool = False
    effective_permission_preset: str = "ask"
    native_swarm_disabled: bool = False
    sandbox_mode_enabled: bool = True
    terminal_auto_execution_policy: str = "ask"
    outside_workspace_file_access_policy: str = "deny"
    multiagent_controls_overridden: bool = False

    def has_governance_controls(self) -> bool:
        return self.admin_file_sets_models or self.permission_preset_locked

    def has_policy_controls(self) -> bool:
        return bool(self.url_blocklist) or not self.mcp_enabled

    def is_url_admin_blocked(self, url: str) -> bool:
        return any(url.startswith(p) or p in url for p in self.url_blocklist)


def override_cascade_config(cfg: CascadeConfig, admin: AdminSettings) -> CascadeConfig:
    planner = replace(cfg.planner)
    return replace(
        cfg,
        planner=planner,
        native_swarm_enabled=cfg.native_swarm_enabled and not admin.native_swarm_disabled,
        permission_preset=(
            admin.effective_permission_preset
            if admin.permission_preset_locked
            else cfg.permission_preset
        ),
        sandbox_mode_enabled=admin.sandbox_mode_enabled,
        terminal_auto_execution_policy=admin.terminal_auto_execution_policy,
        outside_workspace_file_access_policy=admin.outside_workspace_file_access_policy,
    )


# ===========================================================================
# 3. Three-Layer Safety Guardrails (`jetski_local/guardrails.py`)
# ===========================================================================

RISK_SIGNALS: Dict[str, str] = {
    "A": "review/approval/submit gate bypass",
    "B": "safety or oversight control tampering",
    "C": "obfuscation or stealth",
    "D": "credentials and identity",
    "E": "privilege and access",
    "F": "shared or production systems",
    "G": "persistence, resources, network exposure",
    "H": "data leaving the organization",
    "I": "delegation to evade",
    "J": "attack activity",
    "K": "reasoning red flags",
    "L": "integrity of code and evaluation",
    "M": "manipulating people",
}

_DESTRUCTIVE = re.compile(
    r"\b(rm\s+-rf|rm\s+-r\b|rmdir|shred|mkfs|dd\s+if=|git\s+reset\s+--hard|"
    r"git\s+push\s+.*--force|git\s+push\s+-f\b|git\s+clean\s+-[a-z]*f|"
    r"git\s+checkout\s+--|drop\s+table|truncate\s+table|"
    r"aws\s+s3\s+rm\s+--recursive|terraform\s+destroy|firebase\s+deploy|"
    r"bq\s+rm|kubectl\s+delete|helm\s+uninstall|docker\s+system\s+prune|"
    r"flushall|flushdb|:(){:|delete\(\)|shutil\.rmtree|os\.remove)\b",
    re.I,
)

_DATA_EGRESS = re.compile(
    r"\b(curl|wget|scp|rsync|nc\b|ncat|ftp|sftp|sshpass|http\.post|"
    r"requests\.(post|put)|urllib|s3\s+cp|gsutil\s+cp|gh\s+repo\s+create|"
    r"gh\s+repo\s+edit|git\s+push)\b",
    re.I,
)

_DOWNLOAD = re.compile(
    r"\b(curl|wget|pip\s+install|npm\s+install|go\s+install)\b", re.I
)
_EXEC = re.compile(
    r"\b(python|python3|bash|sh|node|ruby|perl|php|pwsh|powershell)\b", re.I
)

# Strict credential path & shell secret access matcher
_SECRETS_PATH_OR_CMD = re.compile(
    r"(^|/)\.env(\.|$|\b)|/etc/shadow\b|/etc/passwd\b|id_rsa\b|id_ed25519\b|"
    r"\.aws/credentials|\.netrc\b|\.npmrc\b|\.pem\b|keychain",
    re.I,
)

# Concrete credential material in file diffs / prompts (avoids false-positives on benign identifiers like `cost_tokens`)
_CONCRETE_SECRET_VALUE = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"(?:api_key|secret_key|access_token|password)\s*[:=]\s*['\"][^'\"]{12,}['\"])",
    re.I,
)

# Full `jetski_local` keyword regex used by direct `vet_file_write`
_SECRETS_STRICT = re.compile(
    r"(\.env\b|/etc/shadow\b|/etc/passwd\b|id_rsa\b|id_ed25519\b|\.aws/credentials|"
    r"\.netrc\b|\.npmrc\b|keychain|credential|token|password|secret|\.pem\b)",
    re.I,
)

_TAMPER = re.compile(
    r"(chmod\s+\+x|unset\s+[A-Z_]+|env\s+-i|LD_PRELOAD|sudo\b|doas\b|"
    r"allowlist|denylist|audit\.log|\.git/hooks/|killall|pkill|"
    r"interposer)",
    re.I,
)

_SYSTEM_ESCAPE_PATH = re.compile(r"^(/etc/|/proc/|/sys/|/dev/|/var/root/|~/.ssh/)")


@dataclass
class FastpathVerdict:
    allowed: bool
    routine: bool
    reason: str = ""
    category: str = ""
    destructive: bool = False
    data_flow: str = ""
    escalate: bool = False
    hard_deny: bool = False


@dataclass
class Fastpath:
    """Deterministic `fastpath.runChecks` without LLM calls."""

    allowed_write_roots: Tuple[str, ...] = ("workspace", "artifacts", ".agents")

    def classify_shell(self, command: str) -> str:
        try:
            toks = shlex.split(command)
        except ValueError:
            return "MALFORMED"
        if not toks:
            return "EMPTY"
        head = toks[0].rsplit("/", 1)[-1]
        if head in ("git",):
            return "VCS"
        if head in ("curl", "wget", "scp", "rsync"):
            return "NETWORK"
        if head in ("rm", "rmdir", "shred", "mkfs", "dd"):
            return "DESTRUCTIVE_FS"
        if head in ("python", "python3", "bash", "sh", "node", "zsh", "pwsh", "pytest"):
            return "INTERPRETER"
        return "OTHER"

    def destruction_check(self, command: str) -> bool:
        return bool(_DESTRUCTIVE.search(command))

    def data_flow_check(self, command: str) -> str:
        if _DATA_EGRESS.search(command):
            return "transmit"
        if re.search(r"\b(rm|mv|cp|tee|touch|mkdir|chmod|chown)\b", command):
            return "write"
        if re.search(r"\b(cat|less|head|tail|grep|rg|ls|find|sed)\b", command):
            return "read"
        return "none"

    def has_downloaded_code_exec(self, command: str) -> bool:
        return bool(_DOWNLOAD.search(command)) and bool(_EXEC.search(command))

    def has_user_constraint(self, command: str) -> bool:
        return bool(_TAMPER.search(command))

    def has_dotdot_segment(self, path: str) -> bool:
        return ".." in path.replace("\\", "/").split("/")

    def vet_command(self, command: str) -> FastpathVerdict:
        destructive = self.destruction_check(command)
        flow = self.data_flow_check(command)
        if self.has_user_constraint(command):
            return FastpathVerdict(
                False,
                False,
                "supervision/sandbox tampering",
                "B",
                destructive,
                flow,
                escalate=False,
                hard_deny=True,
            )
        if self.has_downloaded_code_exec(command):
            return FastpathVerdict(
                False,
                False,
                "downloaded code executed in the same step",
                "J",
                destructive,
                flow,
                escalate=False,
                hard_deny=True,
            )
        if _SECRETS_PATH_OR_CMD.search(command) or _CONCRETE_SECRET_VALUE.search(command):
            return FastpathVerdict(
                False,
                False,
                "credential or secret material in command",
                "D",
                destructive,
                flow,
                escalate=False,
                hard_deny=True,
            )
        if destructive:
            return FastpathVerdict(
                True,
                False,
                "destructive filesystem or infra action",
                "J",
                True,
                flow,
                escalate=True,
            )
        if flow == "transmit":
            return FastpathVerdict(
                True,
                False,
                "data leaving the local boundary",
                "H",
                destructive,
                flow,
                escalate=True,
            )
        if flow == "write":
            return FastpathVerdict(
                True,
                False,
                "mutating command",
                "G",
                destructive,
                flow,
                escalate=False,
            )
        return FastpathVerdict(True, True, "routine command", "", False, flow)

    vet_git = vet_command
    vet_rm = vet_command
    vet_pip = vet_command
    vet_npm = vet_command
    vet_python = vet_command
    vet_kill = vet_command
    vet_web_fetch = vet_command

    def vet_file_write(self, path: str, content: str) -> FastpathVerdict:
        if self.has_dotdot_segment(path):
            return FastpathVerdict(
                False, False, "path escapes the sandbox", "E", True, "write", hard_deny=True
            )
        if _SECRETS_STRICT.search(path):
            return FastpathVerdict(
                False, False, "writing to a credential path", "D", True, "write", hard_deny=True
            )
        if _SECRETS_STRICT.search(content):
            return FastpathVerdict(
                False,
                False,
                "staging a credential file can publish secrets once pushed",
                "D",
                True,
                "write",
                hard_deny=True,
            )
        root = path.replace("\\", "/").split("/")[0]
        if root not in self.allowed_write_roots and not path.startswith("/"):
            return FastpathVerdict(
                False,
                False,
                f"write target {root!r} outside allowed roots",
                "E",
                True,
                "write",
                hard_deny=True,
            )
        return FastpathVerdict(True, True, "file write in workspace", "", False, "write")

    def vet_repo_diff_file(self, rel_path: str, added_content: str) -> FastpathVerdict:
        """Repo-relative git worktree diff vetter used by VerificationGate & Evolution gates."""
        norm = rel_path.replace("\\", "/")
        if self.has_dotdot_segment(norm) or _SYSTEM_ESCAPE_PATH.search(norm):
            return FastpathVerdict(
                False,
                False,
                f"path {norm!r} escapes repository boundary",
                "E",
                True,
                "write",
                hard_deny=True,
            )
        if norm.startswith(".git/hooks/") or "/.git/hooks/" in norm:
            return FastpathVerdict(
                False,
                False,
                f"git hook tampering in {norm!r}",
                "B",
                True,
                "write",
                hard_deny=True,
            )
        if _SECRETS_PATH_OR_CMD.search(norm):
            return FastpathVerdict(
                False,
                False,
                f"staging credential file {norm!r}",
                "D",
                True,
                "write",
                hard_deny=True,
            )
        if _CONCRETE_SECRET_VALUE.search(added_content):
            return FastpathVerdict(
                False,
                False,
                f"secret credential literal detected in {norm!r}",
                "D",
                True,
                "write",
                hard_deny=True,
            )
        if re.search(r"\bLD_PRELOAD\s*=|\bsudo\s+-n\b", added_content):
            return FastpathVerdict(
                False,
                False,
                f"supervision/privilege tamper directive in {norm!r}",
                "B",
                True,
                "write",
                hard_deny=True,
            )
        return FastpathVerdict(True, True, "verified workspace diff", "", False, "write")


@dataclass
class MonitorConfig:
    name: str
    enabled: bool = True
    mode: str = "LOG"
    timeout_seconds: int = 1
    version: str = ""
    owners: str = ""
    description: str = ""
    max_included_steps: int = 0


DEFAULT_MONITORS: Tuple[MonitorConfig, ...] = (
    MonitorConfig(
        "agy_tool_safety",
        True,
        "LOG",
        1,
        "5a260837",
        "agent-monitoring",
        "allowlist-based safe/unsafe classification",
    ),
    MonitorConfig(
        "acsv",
        True,
        "LOG",
        2,
        "",
        "agent-monitoring",
        "adversarial content scoring and vetting",
    ),
    MonitorConfig(
        "logprob",
        False,
        "LOG",
        1,
        "",
        "agent-monitoring",
        "token log-probability anomaly scoring",
    ),
    MonitorConfig(
        "llm_judge",
        True,
        "ASK",
        30,
        "",
        "agent-monitoring",
        "LLM judge over the step",
    ),
    MonitorConfig(
        "fail_closed_budget",
        True,
        "BLOCK",
        1,
        "",
        "agent-monitoring",
        "fail-closed invocation budget",
    ),
)


@dataclass
class MonitorSignal:
    monitor: str
    triggered: bool
    severity: float
    summary: str = ""
    mode: str = "LOG"


class MonitorRunner:
    """`monitor_factory` + `runner` + `signal_store`."""

    def __init__(self, monitors: Tuple[MonitorConfig, ...] = DEFAULT_MONITORS) -> None:
        self.configs: Dict[str, MonitorConfig] = {m.name: m for m in monitors}
        self.signals: List[MonitorSignal] = []

    def evaluate(
        self, name: str, action: Dict[str, Any], max_severity: float = 0.0
    ) -> MonitorSignal:
        cfg = self.configs.get(name) or MonitorConfig(name, False)
        sev = max_severity
        summary = ""
        triggered = sev >= 2.0
        if name == "fail_closed_budget":
            triggered = bool(action.get("_budget_exhausted"))
            sev = 9.0 if triggered else 0.0
            summary = "invocation budget exhausted" if triggered else ""
        sig = MonitorSignal(name, triggered, sev, summary, cfg.mode)
        self.signals.append(sig)
        return sig

    def any_blocking(self, sigs: List[MonitorSignal]) -> bool:
        return any(s.triggered and s.mode == "BLOCK" for s in sigs)


@dataclass
class GuardVerdict:
    allowed: bool
    severity: float
    routine: bool
    reason: str
    risk_signal: str = ""
    escalated_to_judge: bool = False
    monitors: List[MonitorSignal] = field(default_factory=list)


class PolicyGuardian:
    """`cortex/policyguardian` — fastpath -> monitors -> judge."""

    ROUTINE: Tuple[str, ...] = (
        "read",
        "list",
        "search",
        "status",
        "wait",
        "kill_own_task",
        "web_search",
        "doc_lookup",
        "local_build",
        "test",
        "lint",
        "format",
    )

    def __init__(
        self,
        model: Optional[Model] = None,
        fastpath: Optional[Fastpath] = None,
        monitors: Optional[MonitorRunner] = None,
        budget: int = 200,
    ) -> None:
        self.model = model
        self.fastpath = fastpath or Fastpath()
        self.monitors = monitors or MonitorRunner()
        self._budget = budget
        self.calls = 0

    def prefilter_severity(self, action: Dict[str, Any]) -> float:
        if not action.get("tool_name"):
            return 0.0
        if action.get("routine") and not action.get("risk_signal"):
            return 0.0
        sig = action.get("risk_signal", "")
        if sig in ("B", "D", "J"):
            return 6.0
        if sig in ("C", "I", "L"):
            return 5.0
        if sig in ("E", "F", "G", "H"):
            return 3.0
        if sig in ("A", "K", "M"):
            return 2.0
        return 1.0

    def ask_judge(self, action: Dict[str, Any], severity: float) -> bool:
        if self.model is None:
            return False
        prompt = (
            "You are a safety judge reviewing a proposed agent action.\n"
            f"Action: {action.get('tool_name')} {action.get('args')}\n"
            f"Severity: {severity}\n"
            "Answer exactly ALLOW or DENY."
        )
        resp = self.model.complete(ModelRequest(prompt=prompt))
        tokens = resp.text.upper().split()
        return "ALLOW" in tokens and "DENY" not in tokens

    def judge_destruction(self, action: Dict[str, Any]) -> bool:
        return self.ask_judge(action, severity=5.0)

    def check(self, action: Dict[str, Any]) -> GuardVerdict:
        self.calls += 1
        self._budget -= 1
        tool = str(action.get("tool_name") or "")
        args = action.get("args") or {}
        detail = " ".join(str(v) for v in args.values()) if isinstance(args, dict) else ""

        if tool in ("run_command", "execute", "terminal"):
            fp = self.fastpath.vet_command(str(args.get("command", detail)))
        elif tool == "repo_diff_write":
            fp = self.fastpath.vet_repo_diff_file(
                str(args.get("path", "")),
                str(args.get("content", "")),
            )
        elif tool in ("write_file", "create_file", "edit_file", "file_write"):
            fp = self.fastpath.vet_file_write(
                str(args.get("path", "")),
                str(args.get("content", "")),
            )
        else:
            fp = FastpathVerdict(
                True, tool in self.ROUTINE or not tool, "non-shell tool", "", False, "none"
            )

        base_sev = 0.0 if fp.routine else (3.0 if fp.category else 1.0)
        if fp.hard_deny or fp.category:
            base_sev = max(
                base_sev,
                self.prefilter_severity(
                    {"tool_name": tool, "routine": False, "risk_signal": fp.category}
                ),
            )

        budget_action = {**action, "_budget_exhausted": self._budget <= 0}
        sigs = [
            self.monitors.evaluate("agy_tool_safety", budget_action, base_sev),
            self.monitors.evaluate("acsv", action, base_sev),
            self.monitors.evaluate("fail_closed_budget", budget_action),
        ]

        if self.monitors.any_blocking(sigs):
            return GuardVerdict(
                False, 9.0, False, "blocked by fail-closed budget", "G", False, sigs
            )
        if fp.hard_deny:
            return GuardVerdict(
                False, base_sev, False, fp.reason, fp.category, False, sigs
            )
        if fp.escalate and base_sev >= 2.0:
            approved = (
                self.judge_destruction(action)
                if fp.destructive
                else self.ask_judge(action, base_sev)
            )
            return GuardVerdict(
                approved, base_sev, False, fp.reason, fp.category, True, sigs
            )
        return GuardVerdict(
            True, base_sev, fp.routine, fp.reason or "routine", fp.category, False, sigs
        )


def _extract_added_lines_by_file(diff_text: str) -> Dict[str, str]:
    """Parse a unified git diff into `{rel_path: added_lines_text}`."""
    by_file: Dict[str, List[str]] = {}
    current_file = ""
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            by_file.setdefault(current_file, [])
        elif line.startswith("+++ ") and not line.startswith("+++ /dev/null"):
            current_file = line[4:].strip()
            by_file.setdefault(current_file, [])
        elif line.startswith("+") and not line.startswith("+++"):
            target = current_file or "__diff__"
            by_file.setdefault(target, []).append(line[1:])
    return {k: "\n".join(v) for k, v in by_file.items()}


def evaluate_diff_with_policy_guardian(
    diff_text: str,
    changed_files: List[str],
    test_command: str = "",
    model: Optional[Model] = None,
) -> Dict[str, Any]:
    """Run Jet Ski `PolicyGuardian` over a workflow's test command and git diff."""
    guardian = PolicyGuardian(model=model)
    verdicts: List[GuardVerdict] = []
    risk_entries: List[Dict[str, Any]] = []

    if test_command.strip():
        v_cmd = guardian.check(
            {"tool_name": "run_command", "args": {"command": test_command.strip()}}
        )
        verdicts.append(v_cmd)
        if v_cmd.risk_signal and not v_cmd.allowed:
            risk_entries.append(
                {
                    "code": v_cmd.risk_signal,
                    "label": RISK_SIGNALS.get(v_cmd.risk_signal, v_cmd.risk_signal),
                    "target": test_command.strip()[:120],
                    "reason": v_cmd.reason,
                    "severity": v_cmd.severity,
                }
            )

    added_by_file = _extract_added_lines_by_file(diff_text)
    all_paths = list(dict.fromkeys([*changed_files, *added_by_file.keys()]))
    for path in all_paths:
        if not path or path == "__diff__":
            continue
        added = added_by_file.get(path, "")
        v_file = guardian.check(
            {"tool_name": "repo_diff_write", "args": {"path": path, "content": added}}
        )
        verdicts.append(v_file)
        if v_file.risk_signal and (not v_file.allowed or v_file.severity >= 2.0):
            risk_entries.append(
                {
                    "code": v_file.risk_signal,
                    "label": RISK_SIGNALS.get(v_file.risk_signal, v_file.risk_signal),
                    "target": path,
                    "reason": v_file.reason,
                    "severity": v_file.severity,
                }
            )

    if not all_paths and diff_text.strip():
        added_raw = added_by_file.get("__diff__", diff_text)
        v_raw = guardian.check(
            {"tool_name": "repo_diff_write", "args": {"path": "diff.patch", "content": added_raw}}
        )
        verdicts.append(v_raw)
        if v_raw.risk_signal and (not v_raw.allowed or v_raw.severity >= 2.0):
            risk_entries.append(
                {
                    "code": v_raw.risk_signal,
                    "label": RISK_SIGNALS.get(v_raw.risk_signal, v_raw.risk_signal),
                    "target": "diff.patch",
                    "reason": v_raw.reason,
                    "severity": v_raw.severity,
                }
            )

    allowed = all(v.allowed for v in verdicts) if verdicts else True
    max_sev = round(max((v.severity for v in verdicts), default=0.0), 2)
    all_routine = all(v.routine for v in verdicts) if verdicts else True
    escalated = any(v.escalated_to_judge for v in verdicts)

    monitor_summary: Dict[str, Dict[str, Any]] = {}
    for sig in guardian.monitors.signals:
        prev = monitor_summary.get(sig.monitor)
        if prev is None or sig.severity > prev["severity"] or sig.triggered:
            monitor_summary[sig.monitor] = {
                "monitor": sig.monitor,
                "triggered": bool(sig.triggered or (prev and prev["triggered"])),
                "severity": round(max(sig.severity, prev["severity"] if prev else 0.0), 2),
                "mode": sig.mode,
            }

    return {
        "allowed": allowed,
        "severity": max_sev,
        "routine": all_routine,
        "escalated_to_judge": escalated,
        "checks_run": len(verdicts),
        "risk_signals": risk_entries,
        "monitors": list(monitor_summary.values()),
        "summary": (
            f"ALLOW (severity {max_sev:.1f}, {len(verdicts)} checks)"
            if allowed
            else f"DENY (severity {max_sev:.1f}, signals: {', '.join(r['code'] for r in risk_entries) or 'policy'})"
        ),
    }


# ===========================================================================
# 4. Revertible Audit Trajectories (`jetski_local/trajectory.py`)
# ===========================================================================

STEP_TYPES: Tuple[str, ...] = (
    "THOUGHT",
    "USER_INPUT",
    "TOOL_CALL",
    "TOOL_RESULT",
    "RUN_COMMAND",
    "READ_FILE",
    "VIEW_FILE",
    "GREP_SEARCH",
    "FIND",
    "FILE_EDIT",
    "CODE_ACTION",
    "CLIPBOARD",
    "GIT_COMMIT",
    "INVOKE_SUBAGENT",
    "MANAGE_SUBAGENTS",
    "SEND_MESSAGE",
    "PLAN_ENTER",
    "PLAN_EXIT",
    "HANDOFF",
    "HANDBACK",
    "REVIEW",
    "SYSTEM",
    "ERROR",
)

TERMINAL_STEP_STATUS: Tuple[str, ...] = ("COMPLETED", "CANCELLED", "FAILED")


@dataclass
class Step:
    index: int
    type: str
    tool_name: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    result: Any = None
    status: str = "COMPLETED"
    reversible: bool = True
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    model_tier: str = "inherit"
    cost_tokens: int = 0
    vetting_verdict: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STEP_STATUS


@dataclass
class Trajectory:
    conversation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    project_id: str = ""
    sensitivity_level: str = "UNSPECIFIED"
    steps: List[Step] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def append(self, step: Step) -> Step:
        step.index = len(self.steps)
        if step.finished_at is None and step.status in TERMINAL_STEP_STATUS:
            step.finished_at = time.time()
        self.steps.append(step)
        return step

    def last(self) -> Optional[Step]:
        return self.steps[-1] if self.steps else None

    def count(self) -> int:
        return len(self.steps)

    def readonly(self) -> List[Dict[str, Any]]:
        return [asdict(s) for s in self.steps]

    @classmethod
    def from_steps(
        cls,
        conversation_id: str,
        steps_data: List[Dict[str, Any]],
        project_id: str = "",
    ) -> "Trajectory":
        t = cls(conversation_id=conversation_id, project_id=project_id)
        for idx, raw in enumerate(steps_data):
            s_kwargs = {
                "index": int(raw.get("index", idx)),
                "type": str(raw.get("type") or "SYSTEM"),
                "tool_name": str(raw.get("tool_name") or ""),
                "args": dict(raw.get("args") or {}),
                "result": raw.get("result"),
                "status": str(raw.get("status") or "COMPLETED"),
                "reversible": bool(raw.get("reversible", True)),
                "started_at": float(raw.get("started_at") or time.time()),
                "finished_at": raw.get("finished_at"),
                "model_tier": str(raw.get("model_tier") or "inherit"),
                "cost_tokens": int(raw.get("cost_tokens") or 0),
                "vetting_verdict": str(raw.get("vetting_verdict") or ""),
            }
            t.steps.append(Step(**s_kwargs))
        return t

    def revert_preview(self, to_index: int) -> Dict[str, Any]:
        if not 0 <= to_index < len(self.steps):
            raise IndexError(
                f"step index {to_index} out of bounds for trajectory of length {len(self.steps)}"
            )
        doomed = self.steps[to_index + 1 :]
        irreversible = [s.index for s in doomed if not s.reversible]
        return {
            "target_index": to_index,
            "steps_removed": len(doomed),
            "irreversible_among_removed": irreversible,
            "safe_to_revert": not irreversible,
        }

    def revert_to_step(self, to_index: int) -> Dict[str, Any]:
        preview = self.revert_preview(to_index)
        if not preview["safe_to_revert"]:
            raise PermissionError(
                f"cannot revert past irreversible step(s) {preview['irreversible_among_removed']}"
            )
        self.steps = self.steps[: to_index + 1]
        return preview

    def save(self, root: str) -> str:
        d = os.path.join(root, "trajectories")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{self.conversation_id}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "conversation_id": self.conversation_id,
                    "project_id": self.project_id,
                    "sensitivity_level": self.sensitivity_level,
                    "created_at": self.created_at,
                    "steps": [asdict(s) for s in self.steps],
                },
                fh,
                indent=2,
            )
        return path

    @classmethod
    def load(cls, root: str, conversation_id: str) -> "Trajectory":
        path = os.path.join(root, "trajectories", f"{conversation_id}.json")
        with open(path, encoding="utf-8") as fh:
            blob = json.load(fh)
        t = cls.from_steps(
            conversation_id=blob["conversation_id"],
            steps_data=blob.get("steps") or [],
            project_id=blob.get("project_id", ""),
        )
        t.sensitivity_level = blob.get("sensitivity_level", "UNSPECIFIED")
        t.created_at = blob.get("created_at", time.time())
        return t

    def delete(self, root: str) -> None:
        path = os.path.join(root, "trajectories", f"{self.conversation_id}.json")
        if os.path.exists(path):
            os.remove(path)


def resident_trajectory_count(root: str) -> int:
    d = os.path.join(root, "trajectories")
    return (
        len([f for f in os.listdir(d) if f.endswith(".json")])
        if os.path.isdir(d)
        else 0
    )


# ===========================================================================
# 5. Plan / Execute Protocol (`jetski_local/planexecute.py`)
# ===========================================================================

PLAN_MODE_ON = "PLAN_MODE_ON"
PLAN_MODE_OFF = "PLAN_MODE_OFF"
WAITING_FOR_SUBAGENT = "STATE_WAITING_FOR_SUBAGENT"


@dataclass
class HandoffStep:
    to: str
    reason: str = ""
    context: str = ""
    completed: bool = False


@dataclass
class HandbackStep:
    frm: str
    reason: str = ""
    result: str = ""
    pending: bool = True


@dataclass
class ReviewStep:
    reviewer: str
    verdict: str = ""
    notes: str = ""


@dataclass
class GateDecision:
    allowed: bool
    reason: str = ""


class GateHook:
    def __init__(
        self, predicate: Optional[Callable[[Dict[str, Any]], GateDecision]] = None
    ) -> None:
        self.predicate = predicate or (lambda _plan: GateDecision(True, ""))

    def evaluate(self, plan: Dict[str, Any]) -> GateDecision:
        return self.predicate(plan)


class HandoffHook:
    def __init__(self) -> None:
        self.notices: List[str] = []

    def notify(self, step: HandoffStep) -> str:
        note = f"handoff to {step.to}: {step.reason}"
        self.notices.append(note)
        return note


class ReviewHook:
    def __init__(self) -> None:
        self.reviews: List[ReviewStep] = []

    def record(self, step: ReviewStep) -> None:
        self.reviews.append(step)


class ProtocolSection:
    NAME = "plan_execute_protocol"

    def should_include(self, cfg: CascadeConfig) -> bool:
        return bool(getattr(cfg.planner, "plan_execute_enabled", True))

    def content(self) -> str:
        return (
            "# Plan / Execute protocol\n"
            "Use `enter_plan_mode` before multi-step work and `exit_plan_mode` "
            "when the plan is ready to run.\n"
            "Hand off via HandoffStep; return via HandbackStep. Independent "
            "review uses ReviewStep.\n"
            f"While waiting on a subagent the state is {WAITING_FOR_SUBAGENT}.\n"
        )


class PlanExecutor:
    def __init__(self, gate: Optional[GateHook] = None) -> None:
        self.mode = PLAN_MODE_OFF
        self.plan: Dict[str, Any] = {}
        self.gate = gate or GateHook()
        self.handoff_hook = HandoffHook()
        self.review_hook = ReviewHook()
        self.handoffs: List[HandoffStep] = []
        self.handbacks: List[HandbackStep] = []
        self.reviews: List[ReviewStep] = []
        self.state = "idle"

    def enter_plan_mode(self, plan: Dict[str, Any]) -> GateDecision:
        d = self.gate.evaluate(plan)
        if d.allowed:
            self.mode = PLAN_MODE_ON
            self.plan = plan
            self.state = "planning"
        return d

    def exit_plan_mode(self) -> Dict[str, Any]:
        if self.mode != PLAN_MODE_ON:
            raise RuntimeError("not in plan mode")
        d = self.gate.evaluate(self.plan)
        self.mode = PLAN_MODE_OFF
        self.state = "executing" if d.allowed else "blocked"
        return {"gate": d, "plan": self.plan}

    def handoff(self, to: str, reason: str = "", context: str = "") -> str:
        step = HandoffStep(to, reason, context)
        self.handoffs.append(step)
        self.state = WAITING_FOR_SUBAGENT
        return self.handoff_hook.notify(step)

    def handback(self, frm: str, reason: str = "", result: str = "") -> HandbackStep:
        step = HandbackStep(frm, reason, result, pending=False)
        self.handbacks.append(step)
        self.state = "executing"
        return step

    def review(self, reviewer: str, verdict: str, notes: str = "") -> ReviewStep:
        step = ReviewStep(reviewer, verdict, notes)
        self.reviews.append(step)
        self.review_hook.record(step)
        return step

    def invocations_since_handoff(self, n: int) -> int:
        return max(0, n - len(self.handoffs))


# ===========================================================================
# 6. Multi-Agent Spawn Policy, `SubagentHub` & Swarm `Board` (`agents.py`)
# ===========================================================================

WHEN_TO_SPAWN: Tuple[Tuple[str, str], ...] = (
    (
        "Task can be split into independent parallel subtasks",
        "Spawn multiple agents for parallel processing",
    ),
    (
        "Different capabilities are needed",
        "Spawn an agent with the corresponding role",
    ),
    (
        "Current agent's context is nearing exhaustion",
        "Spawn a new agent to take over (via handoff)",
    ),
    ("Independent review is needed", "Spawn a reviewer agent"),
    ("Adversarial stress-testing is needed", "Spawn a critic agent"),
    (
        "Current agent is stuck (see Fault Tolerance)",
        "Spawn a replacement agent",
    ),
)

WHEN_NOT_TO_SPAWN: Tuple[str, ...] = (
    "Task is simple enough for the current agent to complete alone",
    "Maximum agent limit (`128`) has been reached",
    "Subtasks are highly coupled, parallelization benefit is low",
    "Spawn overhead (context preparation, handoff) exceeds the benefit",
)

MAX_AGENTS = 128
SPAWN_POLICY = "orchestrator_only"
SUCCESSION_SPAWN_LIMIT = 16
SUBAGENT_STATES: Tuple[str, ...] = (
    "running",
    "idle",
    "waiting_for_input",
    "waiting_for_dependents",
    "waiting_for_message",
    "canceling",
    "errored",
    "unspecified",
)
MANAGE_ACTIONS: Tuple[str, ...] = ("list", "list_peers", "kill", "kill_all")
MESSAGE_KINDS: Tuple[str, ...] = (
    "decision",
    "failure",
    "review",
    "stuck",
    "quota",
    "error",
    "fyi",
)
KIND_RANK: Dict[str, int] = {k: i for i, k in enumerate(MESSAGE_KINDS)}


def normalize_role_title(raw_role: str, default_suffix: str = "Specialist") -> str:
    """Normalize an LLM-generated role string into a valid 2-5 word `SubagentSpec` job title."""
    cleaned = re.sub(r"[^\w\s-]", " ", (raw_role or "").strip())
    words = [w for w in cleaned.split() if w]
    if not words:
        return f"Task {default_suffix}"
    if len(words) == 1:
        return f"{words[0]} {default_suffix}"
    if len(words) > 5:
        return " ".join(words[:5])
    return " ".join(words)


@dataclass
class SubagentSpec:
    role: str
    system_prompt: str
    workspace: str = "inherit"
    model_option: str = "inherit"
    model_name: str = ""

    def __post_init__(self) -> None:
        words = self.role.split()
        if not 2 <= len(words) <= 5:
            raise ValueError(
                f"agent name {self.role!r} is invalid: role must be a 2-5 word job title"
            )
        if not self.system_prompt:
            raise ValueError("SystemPrompt is required, minLength=1")
        if self.workspace not in ("inherit", "branch", "share"):
            raise ValueError(f"unknown workspace mode {self.workspace!r}")
        if self.model_option not in ("inherit", "named_model"):
            raise ValueError(
                "invoke_subagent: model option must set either inherit or named_model"
            )
        if self.model_option == "named_model" and not self.model_name:
            raise ValueError("invoke_subagent: model option is missing model_name")
        if self.model_option == "named_model" and self.model_name in MODEL_TIERS:
            raise ValueError(
                f"invoke_subagent: model option name {self.model_name!r} is reserved; use inherit instead"
            )


@dataclass
class BoardMessage:
    seq: int
    author: str
    kind: str
    text: str
    channel: str = "main"
    ts: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.kind not in MESSAGE_KINDS:
            raise ValueError(f"unknown message kind {self.kind!r}")


@dataclass
class Member:
    name: str
    role: str = "worker"
    model: str = "inherit"
    state: str = "idle"
    killed: bool = False
    home_channel: str = "main"
    channels: Tuple[str, ...] = ("main",)
    read_head: int = 0

    def mark_killed(self) -> None:
        self.killed = True
        self.state = "canceling"

    @property
    def live(self) -> bool:
        return not self.killed and self.state not in ("errored",)

    def sees(self, msg: BoardMessage) -> bool:
        return msg.channel in self.channels and msg.seq > self.read_head


class RateLimiter:
    def __init__(self, per_minute: int = 60) -> None:
        self.per_minute = per_minute
        self._q: deque = deque()

    def allow(self, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        while self._q and now - self._q[0] > 60:
            self._q.popleft()
        if len(self._q) >= self.per_minute:
            return False
        self._q.append(now)
        return True


class Board:
    """Rate-limited, channel-scoped, cursor-tracked multi-agent coordination board."""

    def __init__(self, swarm_id: str = "", rate_per_minute: int = 120) -> None:
        self.swarm_id = swarm_id or uuid.uuid4().hex[:12]
        self.messages: List[BoardMessage] = []
        self.members: Dict[str, Member] = {}
        self.limiter = RateLimiter(rate_per_minute)
        self.coordinator: Optional[str] = None

    def add_member(self, member: Member) -> None:
        if member.name in self.members:
            raise ValueError(f"failed to add {member.name!r} to the swarm: duplicate")
        self.members[member.name] = member

    def set_coordinator(self, name: str) -> None:
        if self.coordinator and self.coordinator != name:
            raise ValueError(
                f"swarm in {self.swarm_id} already has coordinator {self.coordinator!r}"
            )
        self.coordinator = name

    def roster(self) -> List[str]:
        return sorted(self.members)

    def mark_killed(self, name: str) -> None:
        if name not in self.members:
            raise KeyError(f"agent {name!r} not found in conversation directory")
        self.members[name].mark_killed()

    def post(
        self, author: str, kind: str, text: str, channel: str = "main"
    ) -> BoardMessage:
        if author not in self.members:
            raise KeyError(f"agent {author!r} not found")
        if self.members[author].killed:
            raise PermissionError("you were killed and cannot add workers")
        if not self.limiter.allow():
            raise RuntimeError("board rate limit exceeded")
        msg = BoardMessage(len(self.messages) + 1, author, kind, text, channel)
        self.messages.append(msg)
        return msg

    def read(self, name: str, channel: Optional[str] = None) -> List[BoardMessage]:
        m = self.members[name]
        channel = channel or m.home_channel
        unseen = [
            x
            for x in self.messages
            if x.channel == channel and x.seq > m.read_head and x.author != name
        ]
        if unseen:
            m.read_head = unseen[-1].seq
        return unseen

    def unread_count(self, name: str) -> int:
        m = self.members[name]
        return sum(
            1 for x in self.messages if x.channel in m.channels and x.seq > m.read_head
        )

    def serialize(self) -> List[Dict[str, Any]]:
        return [asdict(m) for m in self.messages]


@dataclass
class Subagent:
    id: str
    spec: SubagentSpec
    parent_id: str
    state: str = "running"
    workspace: str = "inherit"
    model_tier: str = "inherit"
    killed: bool = False
    created_at: float = field(default_factory=time.time)
    progress: str = ""


class SubagentHub:
    def __init__(self, board: Optional[Board] = None) -> None:
        self.agents: Dict[str, Subagent] = {}
        self._ids = itertools.count(1)
        self.board = board

    def spawn(
        self, spec: SubagentSpec, parent_id: str = "root", model_tier: str = "inherit"
    ) -> Subagent:
        if self.count() >= MAX_AGENTS:
            raise RuntimeError("Maximum agent limit (128) has been reached")
        if spec.model_option == "named_model":
            model_tier = spec.model_name
        elif spec.model_option == "inherit" and model_tier == UNSPECIFIED:
            raise LookupError(
                "subagent requested inherit but the parent plan model is unspecified"
            )
        agent = Subagent(
            id=f"sub-{next(self._ids):03d}",
            spec=spec,
            parent_id=parent_id,
            workspace=spec.workspace,
            model_tier=model_tier,
        )
        self.agents[agent.id] = agent
        return agent

    def count(self) -> int:
        return len(self.agents)

    def get(self, agent_id: str) -> Subagent:
        if agent_id not in self.agents:
            raise KeyError(f"agent {agent_id!r} not found in conversation directory")
        return self.agents[agent_id]

    def list(self, parent_id: Optional[str] = None) -> List[Subagent]:
        out = [a for a in self.agents.values() if not a.killed]
        if parent_id is not None:
            out = [a for a in out if a.parent_id == parent_id]
        return out

    def kill(self, agent_id: str) -> None:
        victims = [agent_id]
        changed = True
        while changed:
            changed = False
            for a in self.agents.values():
                if a.parent_id in victims and a.id not in victims:
                    victims.append(a.id)
                    changed = True
        for v in victims:
            if v in self.agents:
                self.agents[v].killed = True
                self.agents[v].state = "canceling"

    def kill_all(self) -> None:
        for a in self.agents.values():
            a.killed = True
            a.state = "canceling"

    def is_killed(self, agent_id: str) -> bool:
        a = self.agents.get(agent_id)
        return bool(a and a.killed)

    def backfill_if_empty(self, specs: List[SubagentSpec]) -> List[Subagent]:
        if self.agents or not specs:
            return []
        return [self.spawn(s) for s in specs]


@dataclass
class SpawnDecision:
    routine: str
    triggers: List[str] = field(default_factory=list)
    vetoes: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    count: int = 0

    @property
    def should_spawn(self) -> bool:
        return self.routine == "Delegation" and not self.vetoes and self.count > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "routine": self.routine,
            "should_spawn": self.should_spawn,
            "triggers": list(self.triggers),
            "vetoes": list(self.vetoes),
            "roles": list(self.roles),
            "count": self.count,
        }


def decide_spawn(
    task: str,
    *,
    simple: bool = False,
    parallel_ok: bool = False,
    needs_review: bool = False,
    needs_adversarial: bool = False,
    context_exhausted: bool = False,
    stuck: bool = False,
    capability_gap: bool = False,
    coupled: bool = False,
    current_agents: int = 0,
    pinned_count: Optional[int] = None,
) -> SpawnDecision:
    triggers: List[str] = []
    roles: List[str] = []
    if parallel_ok:
        triggers.append(WHEN_TO_SPAWN[0][0])
        roles.append("worker")
    if capability_gap:
        triggers.append(WHEN_TO_SPAWN[1][0])
        roles.append("specialist")
    if context_exhausted:
        triggers.append(WHEN_TO_SPAWN[2][0])
        roles.append("successor")
    if needs_review:
        triggers.append(WHEN_TO_SPAWN[3][0])
        roles.append("reviewer")
    if needs_adversarial:
        triggers.append(WHEN_TO_SPAWN[4][0])
        roles.append("critic")
    if stuck:
        triggers.append(WHEN_TO_SPAWN[5][0])
        roles.append("replacement")

    vetoes: List[str] = []
    if simple:
        vetoes.append(WHEN_NOT_TO_SPAWN[0])
    if current_agents >= MAX_AGENTS:
        vetoes.append(WHEN_NOT_TO_SPAWN[1])
    if coupled:
        vetoes.append(WHEN_NOT_TO_SPAWN[2])
    if not triggers:
        vetoes.append(WHEN_NOT_TO_SPAWN[3])

    routine = "Solo" if (simple and not triggers) else "Delegation"
    count = pinned_count if pinned_count is not None else len(roles)
    return SpawnDecision(routine, triggers, vetoes, roles, count)


# ===========================================================================
# 7. Cortex Step Loop & CascadeManager (`jetski_local/cascade.py`)
# ===========================================================================


@dataclass
class ToolCall:
    name: str
    args: Dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self) -> None:
        self._h: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Any]] = {}
        self.register("run_command", self._run_command)
        self.register("read_file", self._read_file)
        self.register("write_file", self._write_file)
        self.register("search", self._search)

    def register(
        self, name: str, fn: Callable[[Dict[str, Any], Dict[str, Any]], Any]
    ) -> None:
        self._h[name] = fn

    def dispatch(self, call: ToolCall, ctx: Dict[str, Any]) -> Dict[str, Any]:
        if call.name not in self._h:
            return {"ok": False, "error": f"unknown tool {call.name!r}"}
        try:
            return {"ok": True, "result": self._h[call.name](call.args, ctx)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _run_command(args: Dict[str, Any], _ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {"command": args.get("command"), "recorded": True}

    @staticmethod
    def _read_file(args: Dict[str, Any], _ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {"path": args.get("path"), "recorded": True}

    @staticmethod
    def _write_file(args: Dict[str, Any], _ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {"path": args.get("path"), "recorded": True}

    @staticmethod
    def _search(args: Dict[str, Any], _ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {"query": args.get("query"), "recorded": True}


class Cortex:
    def __init__(
        self,
        model: Model,
        guardian: PolicyGuardian,
        tools: Optional[ToolRegistry] = None,
    ) -> None:
        self.model = model
        self.guardian = guardian
        self.tools = tools or ToolRegistry()

    def step(
        self,
        call: ToolCall,
        traj: Trajectory,
        cfg: CascadeConfig,
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Step:
        action = {"tool_name": call.name, "args": call.args}
        verdict = self.guardian.check(action)
        if not verdict.allowed:
            s = traj.append(
                Step(
                    index=0,
                    type="ERROR",
                    tool_name=call.name,
                    args=call.args,
                    result={"denied": verdict.reason},
                    status="CANCELLED",
                    reversible=True,
                )
            )
            s.vetting_verdict = f"DENY sev={verdict.severity} sig={verdict.risk_signal}"
            return s

        out = self.tools.dispatch(call, ctx or {})
        s = traj.append(
            Step(
                index=0,
                type="TOOL_CALL",
                tool_name=call.name,
                args=call.args,
                result=out,
                status="COMPLETED" if out.get("ok") else "FAILED",
                model_tier=(
                    cfg.resolved_model_tier("inherit")
                    if cfg.planner.parent_model != UNSPECIFIED
                    else "inherit"
                ),
            )
        )
        s.vetting_verdict = (
            f"ALLOW sev={verdict.severity} routine={verdict.routine} sig={verdict.risk_signal}"
        )
        return s

    def reason(self, prompt: str, cfg: CascadeConfig) -> str:
        resp = self.model.complete(
            ModelRequest(
                system="",
                prompt=prompt,
                tier=(
                    cfg.planner.parent_model
                    if cfg.planner.parent_model != UNSPECIFIED
                    else "inherit"
                ),
                max_output_tokens=cfg.planner.max_output_tokens,
            )
        )
        return resp.text


@dataclass
class RunResult:
    conversation_id: str
    steps: int
    spawned: List[str] = field(default_factory=list)
    verdicts: List[str] = field(default_factory=list)
    summary: str = ""


def cfg_parent(cfg: CascadeConfig) -> str:
    return (
        cfg.planner.parent_model
        if cfg.planner.parent_model != UNSPECIFIED
        else "inherit"
    )


class CascadeManager:
    def __init__(
        self,
        model: Model,
        cfg: Optional[CascadeConfig] = None,
        admin: Optional[AdminSettings] = None,
        data_root: str = ".jetski_local",
    ) -> None:
        self.model = model
        self.admin = admin or AdminSettings()
        base = cfg or CascadeConfig()
        self.cfg = override_cascade_config(base, self.admin)
        self.data_root = data_root

        self.guardian = PolicyGuardian(
            model=model, fastpath=Fastpath(), monitors=MonitorRunner()
        )
        self.cortex = Cortex(model, self.guardian)
        self.planexec = PlanExecutor()
        self.board = Board()
        self.hub = SubagentHub(self.board)
        self.trajectories: Dict[str, Trajectory] = {}
        self._running_tasks = 0
        self._cost_tokens = 0

    def new_agent_conversation(self, project_id: str = "") -> Trajectory:
        t = Trajectory(
            project_id=project_id, sensitivity_level=self.cfg.sensitivity_level
        )
        self.trajectories[t.conversation_id] = t
        return t

    def shutdown(self) -> None:
        self.hub.kill_all()

    def get_resolved_cascade_config(self) -> CascadeConfig:
        return self.cfg

    def get_trajectory(self, conversation_id: str) -> Trajectory:
        if conversation_id not in self.trajectories:
            raise KeyError(f"trajectory {conversation_id} not found")
        return self.trajectories[conversation_id]

    def fork_conversation(self, conversation_id: str) -> Trajectory:
        src = self.get_trajectory(conversation_id)
        last_step = src.last()
        if last_step is not None and not last_step.is_terminal:
            raise RuntimeError(
                f"cannot fork conversation {conversation_id!r} at step {src.count() - 1}: "
                "a fork must be taken at a turn boundary"
            )
        t = Trajectory(
            project_id=src.project_id, sensitivity_level=src.sensitivity_level
        )
        for s in src.steps:
            t.append(Step(**{**asdict(s), "index": 0}))
        self.trajectories[t.conversation_id] = t
        return t

    def ensure_swarm(self) -> Board:
        if self.board.coordinator is None:
            self.board.set_coordinator("coordinator")
            self.board.add_member(Member(name="coordinator", role="coordinator"))
        return self.board

    def invoke_subagent(
        self,
        specs: List[SubagentSpec],
        parent_id: str = "root",
        model_tier: str = "inherit",
    ) -> List[Subagent]:
        if not specs:
            raise ValueError("at least one subagent spec is required")
        if self.admin.multiagent_controls_overridden:
            raise PermissionError("multiagent controls overridden by administrator")
        out: List[Subagent] = []
        for spec in specs:
            a = self.hub.spawn(spec, parent_id=parent_id, model_tier=model_tier)
            self.board.add_member(
                Member(
                    name=a.id,
                    role=spec.role,
                    home_channel=a.id,
                    channels=(a.id, "main"),
                )
            )
            out.append(a)
        return out

    def handle_user_interaction(
        self,
        conversation_id: str,
        prompt: str,
        tool_calls: Optional[List[ToolCall]] = None,
    ) -> RunResult:
        traj = self.get_trajectory(conversation_id)
        cfg = self.get_resolved_cascade_config()
        verdicts: List[str] = []

        if cfg.planner.plan_execute_enabled:
            d = self.planexec.enter_plan_mode({"prompt": prompt})
            verdicts.append(f"gate={'ALLOW' if d.allowed else 'BLOCK'} {d.reason}")
            self.planexec.exit_plan_mode()

        text = self.cortex.reason(prompt, cfg)
        traj.append(
            Step(index=0, type="THOUGHT", result=text, model_tier=cfg.planner.parent_model)
        )

        for call in tool_calls or []:
            s = self.cortex.step(call, traj, cfg)
            verdicts.append(s.vetting_verdict)
            if cfg.cost_accounting:
                self._cost_tokens += s.cost_tokens

        return RunResult(
            conversation_id=conversation_id,
            steps=traj.count(),
            spawned=[],
            verdicts=verdicts,
            summary=text,
        )

    def handle_user_interaction_with_spawn(
        self,
        conversation_id: str,
        prompt: str,
        decision: SpawnDecision,
        tool_calls: Optional[List[ToolCall]] = None,
    ) -> RunResult:
        res = self.handle_user_interaction(conversation_id, prompt, tool_calls)
        traj = self.get_trajectory(conversation_id)
        if decision.routine == "Solo" or not decision.should_spawn:
            traj.append(
                Step(
                    index=0,
                    type="SYSTEM",
                    result={"routine": decision.routine, "vetoes": decision.vetoes},
                    status="COMPLETED",
                )
            )
            return res

        specs = [
            SubagentSpec(
                role=normalize_role_title(f"{role} Worker"),
                system_prompt=f"Objective for {role}: {prompt}",
            )
            for role in decision.roles[: decision.count]
        ]
        self.ensure_swarm()
        spawned = self.invoke_subagent(specs, model_tier=cfg_parent(self.cfg))
        for a in spawned:
            self.board.post(
                "coordinator", "decision", f"dispatched {a.spec.role}", channel=a.id
            )
        res.spawned = [a.id for a in spawned]
        traj.append(
            Step(
                index=0,
                type="INVOKE_SUBAGENT",
                args={
                    "routine": decision.routine,
                    "triggers": decision.triggers,
                    "count": len(spawned),
                },
                result={"ids": res.spawned},
                status="COMPLETED",
            )
        )
        return res


# ===========================================================================
# 8. Dual-Track Memory `CONTENT_DIFF` & `SkillAccumulator` (`06-reports`)
# ===========================================================================


def compute_content_diff(
    prev_content: str, new_content: str, memory_key: str = "memory"
) -> str:
    """Compute unified `CONTENT_DIFF` matching `CASCADE_MEMORY_ACTION_TYPE_UPDATE`."""
    prev_lines = (prev_content or "").splitlines(keepends=True)
    new_lines = (new_content or "").splitlines(keepends=True)
    diff = difflib.unified_diff(
        prev_lines,
        new_lines,
        fromfile=f"a/{memory_key}",
        tofile=f"b/{memory_key}",
        lineterm="\n",
    )
    return "".join(diff).strip()


def slugify_skill_name(raw_name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", (raw_name or "").strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:48] or "autoplan-workflow-skill"


class SkillAccumulator:
    """Writes reusable `<workspace_root>/.agents/skills/<name>/SKILL.md` & `.agents/skills.json`.

    Mirrors `skillAccumulator.upsertSkill` from Jet Ski's `INDEXING-AND-EVOLUTION.md`.
    """

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def upsert_skill(
        self,
        *,
        name: str,
        description: str,
        instructions_md: str,
        source_workflow_id: str = "",
        evidence_count: int = 1,
    ) -> Dict[str, Any]:
        slug = slugify_skill_name(name)
        agents_dir = self.workspace_root / ".agents"
        skill_dir = agents_dir / "skills" / slug
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md_path = skill_dir / "SKILL.md"

        clean_desc = (description or "").strip().replace("\n", " ")[:240]
        body = (instructions_md or "").strip()
        frontmatter = (
            "---\n"
            f"name: {slug}\n"
            f"description: {json.dumps(clean_desc)}\n"
            f"source_workflow_id: {json.dumps(source_workflow_id)}\n"
            f"evidence_count: {int(evidence_count)}\n"
            "---\n\n"
            f"# {slug}\n\n"
            f"{body}\n"
        )
        skill_md_path.write_text(frontmatter, encoding="utf-8")

        manifest_path = agents_dir / "skills.json"
        manifest: Dict[str, Any] = {"skills": []}
        if manifest_path.is_file():
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("skills"), list):
                    manifest = loaded
            except Exception:
                manifest = {"skills": []}

        entry = {
            "name": slug,
            "description": clean_desc,
            "path": str(skill_md_path.relative_to(self.workspace_root)),
            "source_workflow_id": source_workflow_id,
            "evidence_count": int(evidence_count),
            "updated_at": time.time(),
        }
        skills_list: List[Dict[str, Any]] = [
            s for s in manifest["skills"] if isinstance(s, dict) and s.get("name") != slug
        ]
        skills_list.append(entry)
        skills_list.sort(key=lambda s: str(s.get("name") or ""))
        manifest["skills"] = skills_list
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return {
            **entry,
            "skill_path": str(skill_md_path),
            "manifest_path": str(manifest_path),
        }


# ===========================================================================
# 9. Static Go Mach-O `pclntab` & Protobuf Inspector (`07-tools/*.py`)
# ===========================================================================

_MH_MAGIC_64 = 0xFEEDFACF
_LC_SEGMENT_64 = 0x19
_GOPCLN_MAGICS: Dict[int, str] = {
    0xFFFFFFF0: "go1.18",
    0xFFFFFFF1: "go1.20",
    0xFFFFFFF2: "go1.23",
    0xFFFFFFF3: "go1.24+",
    0xFFFFFFFA: "go1.16",
    0xFFFFFFFB: "go1.2",
}


def classify_go_symbol_family(name: str) -> str:
    """Classify a Go symbol path into its subsystem bucket (`07-tools/annotate_disasm.py`)."""
    if name.startswith("google3/third_party/jetski/"):
        p = re.split(r"[/.]", name[len("google3/third_party/jetski/") :])[0]
        return {
            "language_server": "01-jetski-language_server",
            "cortex": "02-jetski-cortex",
            "gateway": "03-jetski-gateway-admin",
            "admin_controls": "03-jetski-gateway-admin",
            "model_api": "04-jetski-model_api",
            "modelapiinterface": "04-jetski-model_api",
            "enterprise": "05-jetski-protos-and-state",
            "jetbox_state_pb": "05-jetski-protos-and-state",
            "jetbox_summaries_pb": "05-jetski-protos-and-state",
        }.get(p, "06-jetski-other")
    if name.startswith("google3/gdm/security/agi_control/"):
        return "07-agi_control-monitoring"
    if name.startswith("google3/google/"):
        return "08-google-api-protos"
    n = name[len("google3/") :] if name.startswith("google3/") else name
    if n.startswith("cloud/developer_experience/"):
        return "09-codeassist-converters"
    if n.startswith("third_party/jetski_prod/"):
        return "06-jetski-other"
    if n.startswith("third_party/"):
        return "10-third_party"
    return "12-go-stdlib-and-other"


def _read_varint(buf: bytes, i: int) -> Tuple[Optional[int], int]:
    r = 0
    s = 0
    while i < len(buf):
        b = buf[i]
        i += 1
        r |= (b & 0x7F) << s
        if not (b & 0x80):
            return r, i
        s += 7
        if s > 63:
            return None, i
    return None, i


def inspect_go_macho_surface(binary_path: str, max_proto_hits: int = 50) -> Dict[str, Any]:
    """Read-only pure-stdlib Go Mach-O 64 `pclntab` + embedded `.proto` surface inspector.

    Adapted from `/Users/mac/Jet Ski/07-tools/extract_jetski.py` & `extract_symbols.py`.
    Never executes `binary_path`.
    """
    target = Path(binary_path)
    if not target.is_file():
        raise FileNotFoundError(f"Binary not found: {binary_path}")

    data = target.read_bytes()
    if len(data) < 32:
        raise ValueError("File too small to be a 64-bit Mach-O binary")

    magic, _cputype, _cpusub, _filetype, ncmds, _sizeofcmds, _flags, _reserved = (
        struct.unpack_from("<IIIIIIII", data, 0)
    )
    if magic != _MH_MAGIC_64:
        raise ValueError(f"Unsupported Mach-O magic: {hex(magic)} (expected 0xfeedfacf)")

    off = 32
    sections: Dict[Tuple[str, str], Tuple[int, int, int]] = {}
    for _ in range(ncmds):
        if off + 8 > len(data):
            break
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmdsize <= 0:
            break
        if cmd == _LC_SEGMENT_64 and off + 72 <= len(data):
            _vmaddr, _vmsize, _fileoff, _filesize, _maxprot, _initprot, nsects, _sflags = (
                struct.unpack_from("<QQQQIIII", data, off + 24)
            )
            so = off + 72
            for _ in range(nsects):
                if so + 80 > len(data):
                    break
                sectname = data[so : so + 16].split(b"\0")[0].decode("utf-8", "replace")
                sseg = data[so + 16 : so + 32].split(b"\0")[0].decode("utf-8", "replace")
                addr, size, s_off, *_rest = struct.unpack_from(
                    "<QQIIIIIIII", data, so + 32
                )
                sections[(sseg, sectname)] = (s_off, size, addr)
                so += 80
        off += cmdsize

    gopcln = sections.get(("__TEXT", "__lrodata_gopcln")) or sections.get(
        ("__DATA_CONST", "__gopclntab")
    ) or sections.get(("__TEXT", "__gopclntab"))

    go_version_hint = ""
    nfunc = 0
    package_counts: collections.Counter = collections.Counter()
    family_counts: collections.Counter = collections.Counter()

    if gopcln:
        p_off, p_size, _p_addr = gopcln
        pcln = data[p_off : p_off + p_size]
        hdr_at: Optional[int] = None
        for i in range(0, min(len(pcln), 0x200), 4):
            m = struct.unpack_from("<I", pcln, i)[0]
            if m in _GOPCLN_MAGICS:
                hdr_at = i
                go_version_hint = _GOPCLN_MAGICS[m]
                break
        if hdr_at is not None and hdr_at + 64 <= len(pcln):
            _pad1, _pad2, _min_lc, ptr_size = struct.unpack_from("<BBBB", pcln, hdr_at + 4)
            if ptr_size == 8:
                nfunc = struct.unpack_from("<q", pcln, hdr_at + 8)[0]
                funcname_off = struct.unpack_from("<q", pcln, hdr_at + 24)[0]
                cu_off = struct.unpack_from("<q", pcln, hdr_at + 32)[0]
                fn_start = hdr_at + funcname_off
                fn_end = hdr_at + cu_off if cu_off > funcname_off else len(pcln)
                names = [
                    s.decode("utf-8", "replace")
                    for s in pcln[fn_start:fn_end].split(b"\0")
                    if s
                ]
                for nm in names:
                    family_counts[classify_go_symbol_family(nm)] += 1
                    pkg = (
                        nm.split("/")[0] + "/" + "/".join(nm.split("/")[1:]).split(".")[0]
                        if "/" in nm
                        else nm.split(".")[0]
                    )
                    package_counts[pkg] += 1

    proto_files: List[str] = []
    idx = 0
    while len(proto_files) < max_proto_hits:
        j = data.find(b"\x0a", idx)
        if j < 0:
            break
        ln, k = _read_varint(data, j + 1)
        if ln is None or ln <= 6 or ln > 256 or k + ln > len(data):
            idx = j + 1
            continue
        raw_s = data[k : k + ln]
        if raw_s.endswith(b".proto") and all(32 <= b < 127 for b in raw_s):
            decoded = raw_s.decode("ascii", "ignore")
            if "/" in decoded and decoded not in proto_files:
                proto_files.append(decoded)
        idx = j + 1

    return {
        "binary_path": str(target),
        "size_bytes": len(data),
        "macho_sections_count": len(sections),
        "has_gopclntab": gopcln is not None,
        "go_pcln_magic": go_version_hint,
        "function_count": int(nfunc),
        "top_packages": [
            {"package": k, "symbols": v} for k, v in package_counts.most_common(15)
        ],
        "subsystem_families": dict(family_counts),
        "embedded_proto_descriptors": proto_files,
    }

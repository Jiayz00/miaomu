#!/usr/bin/env python3
"""Project-local development Harness for the ShopXO nursery adaptation.

The CLI intentionally depends only on Python 3.11+ standard-library modules.
Task contracts are JSON, commands are always argv arrays, and test execution
never uses a shell.
"""

from __future__ import annotations

import sys


_ISOLATED_CLI_COMMANDS = frozenset(
    {"remote-actions", "remote-exec", "release-seal", "release-check"}
)
_ISOLATED_CLI_REQUEST = (
    __name__ == "__main__"
    and len(sys.argv) > 1
    and sys.argv[1] in _ISOLATED_CLI_COMMANDS
)
if _ISOLATED_CLI_REQUEST and not (
    sys.flags.isolated
    and sys.flags.no_site
    and sys.flags.dont_write_bytecode
):
    sys.stderr.write(
        "Sensitive Harness commands require isolated startup: "
        "python -I -S -B scripts/harness.py <command> ...\n"
    )
    raise SystemExit(2)

import argparse
import contextlib
import copy
import dataclasses
import datetime as dt
import errno
import hashlib
import importlib.util
import ipaddress
import json
import os
import platform
import re
import signal
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import tomllib
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence

if _ISOLATED_CLI_REQUEST:
    _missing_verified_context = object()
    _verified_remote_context = globals().pop(
        "_HARNESS_VERIFIED_REMOTE_CONTEXT",
        _missing_verified_context,
    )
    if _verified_remote_context is not _missing_verified_context:
        if (
            not isinstance(_verified_remote_context, tuple)
            or len(_verified_remote_context) != 2
        ):
            raise ImportError("内部 verified broker 上下文格式无效")
        _verified_token, _remote_module = _verified_remote_context
        if (
            sys.modules.get("harness_remote") is not _remote_module
            or getattr(
                _remote_module,
                "_shopxo_verified_launcher_token",
                None,
            )
            is not _verified_token
        ):
            raise ImportError("内部 verified broker 对象身份校验失败")
    else:
        _remote_path = Path(__file__).with_name("harness_remote.py")
        _remote_spec = importlib.util.spec_from_file_location(
            "_shopxo_nursery_harness_remote",
            _remote_path,
        )
        if _remote_spec is None or _remote_spec.loader is None:
            raise ImportError(f"无法创建远程 broker 模块规格：{_remote_path}")
        _remote_module = importlib.util.module_from_spec(_remote_spec)
        sys.modules[_remote_spec.name] = _remote_module
        try:
            _remote_spec.loader.exec_module(_remote_module)
        except BaseException:
            sys.modules.pop(_remote_spec.name, None)
            raise
    RemoteBrokerError = _remote_module.RemoteBrokerError
    RemoteExecutionBroker = _remote_module.RemoteExecutionBroker
else:
    from harness_remote import RemoteBrokerError, RemoteExecutionBroker


MIN_PYTHON = (3, 11)
REPOSITORY_BASELINE_POLICY_VERSION = 1
WORKFLOW_LOCK_WAIT_SECONDS = 15.0
WORKFLOW_LOCK_STALE_SECONDS = 600.0
HARD_MAX_TEST_TIMEOUT_SECONDS = 3600
HARD_MAX_CAPTURED_OUTPUT_BYTES = 1024 * 1024
POST_IMPLEMENTATION_PLAN_CHANGE_MODE = (
    "warn_plan_artifacts_and_require_merge_review"
)
ROOT = Path(os.path.abspath(__file__)).parents[1]
HARNESS_DIR = ROOT / ".harness"
TASKS_DIR = HARNESS_DIR / "tasks"
RUNS_DIR = HARNESS_DIR / "runs"
REPORTS_DIR = HARNESS_DIR / "reports"
STATE_FILE = HARNESS_DIR / "state" / "active-task.json"
CONFIG_FILE = HARNESS_DIR / "harness.json"

TASK_ID_RE = re.compile(
    r"^NUR-(?:FEAT|BUG|UI|DATA|SEC|OPS|DOC|REFACTOR|HARNESS)-\d{3}$"
)
REQUIREMENT_ID_RE = re.compile(
    r"\b(?:BR|FR|NFR|DATA|METRIC|AC)(?:-[A-Z]+)*-\d{3}\b", re.I
)
CODEX_AGENT_TASK_RE = re.compile(r"^/root(?:/[a-z0-9_]+)*$")
CODEX_THREAD_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
APPROVAL_STAGES = ("plan", "merge", "release")
APPROVAL_ARTIFACT_NAMES = {
    stage: f"approval-{stage}.json" for stage in APPROVAL_STAGES
}

# Keep this tuple byte-for-byte compatible with the project hook.
IMMUTABLE_CONTRACT_KEYS = (
    "schema_version",
    "id",
    "title",
    "type",
    "priority",
    "phase",
    "risk_level",
    "requirement_ids",
    "decision_ids",
    "business_goal",
    "in_scope",
    "out_of_scope",
    "business_invariants",
    "dependencies",
    "allowed_paths",
    "forbidden_paths",
    "shopxo_core_change",
    "database_change",
    "required_tests",
    "codex_role_bindings",
    "owner",
    "reviewer",
    "release_approver",
)

# Keep this tuple byte-for-byte compatible with the project hook. These fields
# are locked separately from lifecycle-managed approval results.
POLICY_EXTENSION_KEYS = (
    "new_dependency_allowed",
    "network_access_required",
    "remote_execution",
    "rollback",
)

REMOTE_FORBIDDEN_ACTIONS = frozenset(
    {
        "read_private_key",
        "ssh_config_override",
        "proxy_command",
        "uncontracted_host",
        "unmanaged_remote_path",
        "arbitrary_shell_command",
        "sensitive_cli_argument",
        "destructive_system_action",
    }
)
REMOTE_TRANSPORTS = frozenset({"ssh", "scp"})
REMOTE_ACTION_MODES = frozenset({"read_only", "mutating"})
PROTECTED_REMOTE_ROOTS = frozenset(
    {
        "/",
        "/bin",
        "/boot",
        "/dev",
        "/etc",
        "/home",
        "/opt",
        "/proc",
        "/root",
        "/run",
        "/sbin",
        "/srv",
        "/sys",
        "/tmp",
        "/usr",
        "/var",
    }
)

RISK_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4}
L4_REQUIREMENT_IDS = {"FR-USER-001", "FR-USER-002"}
TASK_STATUSES = (
    "draft",
    "ready_for_analysis",
    "awaiting_plan_approval",
    "approved_for_implementation",
    "implementing",
    "verifying",
    "awaiting_review",
    "approved_for_merge",
    "closed",
    "blocked",
    "cancelled",
)

TASK_TYPE_BY_ID_TOKEN = {
    "FEAT": "feature",
    "BUG": "bug",
    "UI": "ui",
    "DATA": "data",
    "SEC": "security",
    "OPS": "operations",
    "DOC": "documentation",
    "REFACTOR": "refactor",
    "HARNESS": "harness",
}

HARNESS_POLICY_PATTERNS = (
    ".codex/**",
    ".agents/**",
    ".harness/**",
    ".github/**",
    "AGENTS.md",
    "HARNESS.md",
    "shopxo_nursery_harness_spec.md",
    "ShopXO苗木平台需求规格说明书_V1.0.md",
    "docs/product/BUSINESS_RULES.md",
    "docs/product/REQUIREMENTS_TRACEABILITY.md",
    "docs/architecture/SHOPXO_BOUNDARY.md",
    "scripts/harness.py",
    "scripts/harness_remote.py",
    "scripts/harness_remote_selftest.py",
    "scripts/harness_selftest.py",
    "scripts/harness.ps1",
    "scripts/harness.sh",
    ".gitignore",
)

PLAN_ARTIFACT_NAMES = (
    "requirement.md",
    "impact-analysis.md",
    "implementation-plan.md",
    "test-plan.md",
)

TASK_RUNTIME_PATTERN_TEMPLATES = (
    ".harness/tasks/{task_id}/task.json",
    ".harness/tasks/{task_id}/workflow-history.json",
    ".harness/tasks/{task_id}/requirement.md",
    ".harness/tasks/{task_id}/impact-analysis.md",
    ".harness/tasks/{task_id}/implementation-plan.md",
    ".harness/tasks/{task_id}/test-plan.md",
    ".harness/tasks/{task_id}/evidence.md",
    ".harness/tasks/{task_id}/review.md",
    ".harness/tasks/{task_id}/release-note.md",
    ".harness/tasks/{task_id}/approval-plan.json",
    ".harness/tasks/{task_id}/approval-merge.json",
    ".harness/tasks/{task_id}/approval-release.json",
    ".harness/runs/{task_id}/**",
    ".harness/reports/{task_id}/**",
    ".harness/state/active-task.json",
)

NETWORK_CLIENT_EXECUTABLES = {
    "curl",
    "curl.exe",
    "wget",
    "wget.exe",
    "ftp",
    "ftp.exe",
    "ssh",
    "ssh.exe",
    "scp",
    "scp.exe",
    "sftp",
    "sftp.exe",
    "nc",
    "nc.exe",
    "ncat",
    "ncat.exe",
    "telnet",
    "telnet.exe",
}

COMMAND_WRAPPER_EXECUTABLES = {
    "env",
    "env.exe",
    "nice",
    "nice.exe",
    "timeout",
    "timeout.exe",
    "nohup",
    "nohup.exe",
    "stdbuf",
    "stdbuf.exe",
    "xargs",
    "xargs.exe",
    "sudo",
    "sudo.exe",
    "doas",
    "doas.exe",
    "chrt",
    "ionice",
    "setsid",
    "busybox",
    "busybox.exe",
    "npx",
    "npx.cmd",
    "bunx",
    "bunx.exe",
    "uvx",
    "uvx.exe",
}

SENSITIVE_ENV_NAME_RE = re.compile(
    r"(?i)(password|passwd|pwd|token|secret|api_?key|access_?key|private_?key|credential|authorization|cookie|dsn|database_?url)"
)
SENSITIVE_ARGUMENT_NAME_RE = re.compile(
    r"(?i)(?:^|[_-])(?:password|passwd|pwd|token|secret|api[_-]?key|"
    r"access[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|"
    r"private[_-]?key|credential|authorization|cookie|dsn|database[_-]?url)$"
)

SAFE_STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("ready_for_analysis", "cancelled"),
    "ready_for_analysis": ("awaiting_plan_approval", "blocked", "cancelled"),
    "awaiting_plan_approval": (
        "ready_for_analysis",
        "approved_for_implementation",
        "blocked",
        "cancelled",
    ),
    "approved_for_implementation": ("implementing", "blocked", "cancelled"),
    "implementing": ("verifying", "blocked", "cancelled"),
    "verifying": ("implementing", "awaiting_review", "blocked", "cancelled"),
    "awaiting_review": (
        "implementing",
        "verifying",
        "approved_for_merge",
        "blocked",
        "cancelled",
    ),
    "approved_for_merge": ("awaiting_review", "closed", "blocked"),
    "blocked": (
        "ready_for_analysis",
        "awaiting_plan_approval",
        "approved_for_implementation",
        "implementing",
        "verifying",
        "awaiting_review",
        "cancelled",
    ),
    "closed": (),
    "cancelled": (),
}

PLACEHOLDER_MARKERS = (
    "<!-- TODO",
    "待填写",
    "replace_me",
    "CHANGEME",
    "TBD",
)

SHELL_EXECUTABLES = {
    "bash",
    "bash.exe",
    "sh",
    "sh.exe",
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
}

DANGEROUS_COMMAND_PATTERNS = (
    re.compile(r"\bgit\s+reset\s+--hard\b", re.I),
    re.compile(r"\bgit\s+clean\s+-[^\s]*f", re.I),
    re.compile(r"\bgit\s+push\b.*(?:--force|-f\b)", re.I),
    re.compile(r"\b(?:drop\s+database|drop\s+table|truncate\s+table)\b", re.I),
    re.compile(r"\b(?:terraform\s+destroy|kubectl\s+delete)\b", re.I),
    re.compile(r"\b(?:vercel|netlify)\b.*\b(?:--prod|production)\b", re.I),
    re.compile(r"\brm\s+-rf\s+(?:/|~|\$HOME)(?:\s|$)", re.I),
    re.compile(r"\bRemove-Item\b.*-Recurse", re.I),
)

SECRET_KEY_PATTERN = (
    r"(?:password|passwd|pwd|token|access[_-]?token|refresh[_-]?token|"
    r"id[_-]?token|secret|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|authorization|cookie|credential|dsn|database[_-]?url)"
)
JSON_DOUBLE_SECRET_RE = re.compile(
    rf'(?i)("{SECRET_KEY_PATTERN}"\s*:\s*")((?:\\.|[^"\\])*)(")'
)
JSON_SINGLE_SECRET_RE = re.compile(
    rf"(?i)('{SECRET_KEY_PATTERN}'\s*:\s*')((?:\\.|[^'\\])*)(')"
)
ASSIGNMENT_SECRET_RE = re.compile(
    rf"(?im)(\b{SECRET_KEY_PATTERN}\b\s*[:=]\s*)([^\s,;]+)"
)
BEARER_SECRET_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/]+=*")
URL_USERINFO_SECRET_RE = re.compile(
    r"(?i)(\b[a-z][a-z0-9+.-]*://)[^\s/?#@]+@"
)
SENSITIVE_HEADER_SECRET_RE = re.compile(
    r"(?im)(\b(?:authorization|proxy-authorization|cookie|set-cookie)\b\s*[:=]\s*)([^\r\n]+)"
)
PRIVATE_KEY_SECRET_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
    r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)
PHONE_SECRET_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

SECRET_SCAN_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("hardcoded-json-secret", JSON_DOUBLE_SECRET_RE),
    ("hardcoded-json-secret", JSON_SINGLE_SECRET_RE),
    ("hardcoded-secret", ASSIGNMENT_SECRET_RE),
)

DEBUG_SCAN_PATTERNS = (
    ("php-var-dump", re.compile(r"\bvar_dump\s*\(")),
    ("php-die-dump", re.compile(r"\bdd\s*\(")),
    ("debugger", re.compile(r"\bdebugger\s*;")),
)

DEPENDENCY_MANIFEST_BASENAMES = {
    "composer.json",
    "composer.lock",
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "pyproject.toml",
    "poetry.lock",
    "uv.lock",
    "pipfile",
    "pipfile.lock",
    "setup.py",
    "setup.cfg",
    "gemfile",
    "gemfile.lock",
    "go.mod",
    "go.sum",
    "cargo.toml",
    "cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "gradle.lockfile",
}


class HarnessError(RuntimeError):
    """A user-facing Harness failure."""


class WorkflowLockError(HarnessError):
    """Raised when a per-task workflow mutation lock cannot be acquired."""


class DuplicateKeyError(ValueError):
    """Raised when JSON contains duplicate object keys."""


@dataclasses.dataclass
class GateResult:
    name: str
    errors: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)
    data: dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def merge(self, other: "GateResult", *, prefix: str | None = None) -> None:
        label = prefix or other.name
        self.errors.extend(f"[{label}] {item}" for item in other.errors)
        self.warnings.extend(f"[{label}] {item}" for item in other.warnings)
        self.data[label] = other.as_dict()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "data": self.data,
        }


@dataclasses.dataclass(frozen=True)
class GitChange:
    status: str
    paths: tuple[str, ...]
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "paths": list(self.paths), "source": self.source}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_rfc3339(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes

            synchronize = 0x00100000
            wait_timeout = 0x00000102
            handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
            if not handle:
                # Access-denied or another inspection failure must not make a
                # live owner look dead. ERROR_INVALID_PARAMETER is the normal
                # signal for a PID that no longer exists.
                error = ctypes.windll.kernel32.GetLastError()
                return error != 87
            try:
                wait_result = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
                if wait_result == wait_timeout:
                    return True
                if wait_result == 0:
                    return False
                return True
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except (AttributeError, OSError):
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def process_instance_id(pid: int) -> str | None:
    """Return a best-effort process start fingerprint to detect PID reuse."""

    if pid <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes

            class FileTime(ctypes.Structure):
                _fields_ = [
                    ("low", ctypes.c_uint32),
                    ("high", ctypes.c_uint32),
                ]

            query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                query_limited_information, False, pid
            )
            if not handle:
                return None
            try:
                creation = FileTime()
                exit_time = FileTime()
                kernel = FileTime()
                user = FileTime()
                if not ctypes.windll.kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(creation),
                    ctypes.byref(exit_time),
                    ctypes.byref(kernel),
                    ctypes.byref(user),
                ):
                    return None
                value = (int(creation.high) << 32) | int(creation.low)
                return f"windows-filetime:{value}"
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except (AttributeError, OSError):
            return None
    if sys.platform.startswith("linux"):
        try:
            payload = Path(f"/proc/{pid}/stat").read_text(
                encoding="ascii", errors="replace"
            )
            fields = payload.rsplit(") ", 1)[1].split()
            return f"linux-starttime:{fields[19]}"
        except (IndexError, OSError):
            return None
    return None


def run_id(command: str) -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}-{command}"


def no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def path_is_link_like(path: Path) -> bool:
    """Treat symlinks, junctions, and unknown Windows reparse points as unsafe."""

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if stat.S_ISLNK(info.st_mode):
        return True
    if os.name == "nt":
        reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if getattr(info, "st_file_attributes", 0) & reparse_attribute:
            return True
    try:
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())
    except OSError:
        return True


def lexical_path_components(path: Path) -> tuple[Path, tuple[Path, ...]]:
    """Return an absolute lexical path and its existing-root component chain."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    components: list[Path] = []
    current = absolute
    while current.parent != current:
        components.append(current)
        current = current.parent
    components.reverse()
    return absolute, tuple(components)


def reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def json_loads_strict(text: str, *, source: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=no_duplicate_object,
            parse_constant=reject_json_constant,
        )
    except (json.JSONDecodeError, DuplicateKeyError, ValueError) as exc:
        raise HarnessError(f"JSON 无法解析（{source}）：{exc}") from exc


def read_json(path: Path) -> Any:
    if path_is_link_like(path):
        raise HarnessError(f"拒绝读取符号链接 JSON 或目录联接 JSON：{display_path(path)}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HarnessError(f"无法读取 {display_path(path)}：{exc}") from exc
    return json_loads_strict(text, source=display_path(path))


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise


def write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def display_path(path: Path) -> str:
    try:
        return path.absolute().relative_to(ROOT.absolute()).as_posix()
    except (OSError, ValueError):
        return str(path)


def canonical_json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_json_file_sha256(path: Path, *, label: str) -> tuple[Any, str]:
    try:
        value = read_json(path)
    except HarnessError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"无法读取 {label}：{exc}") from exc
    return value, canonical_json_hash(value)


def canonical_utf8_text_bytes(payload: bytes, *, label: str) -> bytes:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HarnessError(f"{label} 必须是 UTF-8 文本：{exc}") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def canonical_text_file_sha256(path: Path, *, label: str) -> str:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise HarnessError(f"无法读取 {label}：{exc}") from exc
    return hashlib.sha256(
        canonical_utf8_text_bytes(payload, label=label)
    ).hexdigest()


def immutable_contract(task: dict[str, Any]) -> dict[str, Any]:
    value = {key: task.get(key) for key in IMMUTABLE_CONTRACT_KEYS}
    criteria = task.get("acceptance_criteria")
    if isinstance(criteria, list):
        value["acceptance_criteria"] = [
            {
                "id": item.get("id"),
                "requirement_ids": item.get("requirement_ids"),
                "description": item.get("description"),
            }
            if isinstance(item, dict)
            else item
            for item in criteria
        ]
    else:
        value["acceptance_criteria"] = criteria

    approvals = task.get("manual_approvals")
    if isinstance(approvals, dict):
        plan = approvals.get("plan")
        merge = approvals.get("merge")
        release = approvals.get("release")
        value["manual_approvals"] = {
            "plan": plan,
            "merge": {"required": merge.get("required")} if isinstance(merge, dict) else merge,
            "release": {"required": release.get("required")} if isinstance(release, dict) else release,
        }
    else:
        value["manual_approvals"] = approvals
    return value


def policy_contract(task: dict[str, Any]) -> dict[str, Any]:
    value = immutable_contract(task)
    value.update({key: task.get(key) for key in POLICY_EXTENSION_KEYS})
    return value


def immutable_contract_hash(task: dict[str, Any]) -> str:
    return canonical_json_hash(immutable_contract(task))


def policy_contract_hash(task: dict[str, Any]) -> str:
    return canonical_json_hash(policy_contract(task))


def plan_review_task(task: dict[str, Any]) -> dict[str, Any]:
    """Remove lifecycle results while retaining which approvals are required."""

    value = copy.deepcopy(task)
    approvals = value.get("manual_approvals")
    if isinstance(approvals, dict):
        for stage in ("plan", "merge", "release"):
            approval = approvals.get(stage)
            approvals[stage] = (
                {"required": approval.get("required")}
                if isinstance(approval, dict)
                else approval
            )
    return value


def plan_review_contract_hash(task: dict[str, Any]) -> str:
    return immutable_contract_hash(plan_review_task(task))


def plan_review_policy_hash(task: dict[str, Any]) -> str:
    return policy_contract_hash(plan_review_task(task))


def normalize_repo_path(value: str, *, allow_glob: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError("path must be a string")
    raw = value.strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw:
        raise ValueError("path must not be empty")
    if "\x00" in raw:
        raise ValueError("path contains NUL")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw) or raw.startswith("~"):
        raise ValueError("path must be repository-relative")
    segments = raw.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise ValueError("path contains an empty, dot, or parent segment")
    if not allow_glob and any(char in raw for char in "*?["):
        raise ValueError("concrete path must not contain glob characters")
    return raw


def resolve_repo_path(root: Path, value: str, *, must_exist: bool = False) -> Path:
    root_absolute, _root_components = lexical_path_components(root)
    raw = value.strip().replace("\\", "/")
    if raw in (".", "./"):
        lexical_candidate = root_absolute
    else:
        normalized = normalize_repo_path(value, allow_glob=False)
        lexical_candidate = root_absolute / Path(*normalized.split("/"))
    safety_error = repo_path_safety_error(root, lexical_candidate)
    if safety_error:
        raise ValueError(safety_error)
    try:
        relative = lexical_candidate.relative_to(root_absolute)
        resolved_root = root_absolute.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise ValueError("repository root cannot be resolved safely") from exc
    candidate = resolved_root.joinpath(*relative.parts)
    if must_exist and not candidate.exists():
        raise ValueError("path does not exist")
    return candidate


def repo_path_safety_error(root: Path, path: Path) -> str | None:
    """Reject lexical escapes, link-like components, and resolved escapes.

    Resolve only components that actually exist.  On Windows, concurrently
    creating a shared parent directory can make ``Path.resolve(strict=False)``
    transiently return an unrelated fallback path for a non-existent child.
    Inspecting existing components with strict resolution avoids that false
    escape while retaining the symlink/junction boundary.
    """

    root_absolute, root_components = lexical_path_components(root)
    path_absolute, _path_components = lexical_path_components(path)
    for component in root_components:
        if path_is_link_like(component):
            return f"repository root contains symlink/junction component: {component.name}"
    try:
        relative = path_absolute.relative_to(root_absolute)
    except ValueError:
        return "path is outside repository"
    try:
        resolved_root = root_absolute.resolve(strict=True)
    except OSError:
        return "repository root cannot be resolved safely"

    # A component may disappear between lstat() and strict resolve while a
    # lock is being created or released.  Retry that narrow race; persistent
    # churn remains a safe failure instead of being accepted silently.
    for _attempt in range(4):
        current = root_absolute
        retry = False
        for segment in relative.parts:
            current = current / segment
            if path_is_link_like(current):
                return f"path contains symlink/junction component: {segment}"
            try:
                current.lstat()
            except FileNotFoundError:
                continue
            except OSError:
                return f"path component cannot be inspected safely: {segment}"
            try:
                resolved_current = current.resolve(strict=True)
            except FileNotFoundError:
                retry = True
                break
            except OSError:
                return f"path component cannot be resolved safely: {segment}"
            try:
                resolved_current.relative_to(resolved_root)
            except ValueError:
                return "path resolves outside repository"
        if not retry:
            return None
        time.sleep(0)
    return "path changed during safety check"


def ensure_repo_path_safe(root: Path, path: Path, *, label: str) -> None:
    error = repo_path_safety_error(root, path)
    if error:
        raise HarnessError(f"{label} 不安全：{error}")


@contextlib.contextmanager
def advisory_lock_guard(
    root: Path,
    path: Path,
    *,
    deadline: float,
    label: str,
    anchor: Path | None = None,
) -> Iterable[None]:
    """Serialize lock-file inspection with an OS-released advisory guard."""

    lock_target = path
    try:
        ensure_repo_path_safe(root, path, label=f"{label}路径")
        if os.name == "nt":
            path.parent.mkdir(parents=True, exist_ok=True)
            ensure_repo_path_safe(root, path.parent, label=f"{label}目录")
            ensure_repo_path_safe(root, path, label=f"{label}路径")
            flags = os.O_CREAT | os.O_RDWR
            descriptor = os.open(path, flags, 0o600)
        else:
            lock_target = anchor if anchor is not None else path.parent
            ensure_repo_path_safe(root, lock_target, label=f"{label} anchor")
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(lock_target, flags)
    except (HarnessError, OSError) as exc:
        raise WorkflowLockError(f"无法准备或打开{label}：{exc}") from exc

    try:
        if os.name == "nt":
            try:
                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"\x00")
                    os.fsync(descriptor)
            except OSError as exc:
                raise WorkflowLockError(f"无法初始化{label}：{exc}") from exc

        while True:
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                contention = exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}
                if not contention:
                    raise WorkflowLockError(f"无法取得{label}：{exc}") from exc
                if time.monotonic() >= deadline:
                    raise WorkflowLockError(
                        f"等待{label} {WORKFLOW_LOCK_WAIT_SECONDS:g} 秒后仍未取得"
                    ) from exc
                time.sleep(0.05)

        try:
            current = lock_target.stat()
            if not os.path.samestat(os.fstat(descriptor), current):
                raise WorkflowLockError(f"{label}在取得期间被替换")
            ensure_repo_path_safe(root, lock_target, label=f"{label}锁定目标")
        except (HarnessError, OSError) as exc:
            if isinstance(exc, WorkflowLockError):
                raise
            raise WorkflowLockError(f"无法复核{label}：{exc}") from exc
        try:
            yield
        finally:
            try:
                current = lock_target.stat()
                if not os.path.samestat(os.fstat(descriptor), current):
                    raise WorkflowLockError(f"{label}在持有期间被替换")
                ensure_repo_path_safe(root, lock_target, label=f"{label}锁定目标")
            except (HarnessError, OSError) as exc:
                if isinstance(exc, WorkflowLockError):
                    raise
                raise WorkflowLockError(f"无法完成{label}退出复核：{exc}") from exc
    finally:
        os.close(descriptor)


def release_owner_lock(
    root: Path,
    path: Path,
    guard_path: Path,
    *,
    token: str,
    label: str,
    anchor: Path,
) -> None:
    """Release an owned lock under the same serialized guard used to acquire it."""

    deadline = time.monotonic() + WORKFLOW_LOCK_WAIT_SECONDS
    try:
        with advisory_lock_guard(
            root,
            guard_path,
            deadline=deadline,
            label=f"{label} release guard",
            anchor=anchor,
        ):
            if not path.is_file():
                raise WorkflowLockError(f"{label}在释放前已消失")
            current = read_json(path)
            if not isinstance(current, dict) or current.get("token") != token:
                raise WorkflowLockError(f"{label}在释放前已被替换")
            path.unlink()
    except WorkflowLockError:
        raise
    except (HarnessError, OSError) as exc:
        raise WorkflowLockError(f"无法释放{label}：{exc}") from exc


def path_matches(path: str, patterns: Iterable[str]) -> bool:
    normalized = normalize_repo_path(path, allow_glob=False).casefold()
    for raw_pattern in patterns:
        pattern = str(raw_pattern).replace("\\", "/").casefold()
        expression = []
        index = 0
        while index < len(pattern):
            char = pattern[index]
            if char == "*":
                if index + 1 < len(pattern) and pattern[index + 1] == "*":
                    expression.append(".*")
                    index += 2
                else:
                    expression.append("[^/]*")
                    index += 1
            elif char == "?":
                expression.append("[^/]")
                index += 1
            else:
                expression.append(re.escape(char))
                index += 1
        if re.fullmatch("".join(expression), normalized):
            return True
    return False


def glob_static_prefix(pattern: str) -> str:
    """Return the normalized literal prefix before the first glob token."""

    normalized = normalize_repo_path(pattern, allow_glob=True).casefold()
    match = re.search(r"[*?\[]", normalized)
    prefix = normalized[: match.start()] if match else normalized
    return prefix.rstrip("/")


def pattern_targets_harness_policy(pattern: str) -> bool:
    """Conservatively detect an allowed glob that can reach Harness policy files."""

    normalized = normalize_repo_path(pattern, allow_glob=True)
    prefix = glob_static_prefix(normalized)
    if not prefix:
        return True
    for protected in HARNESS_POLICY_PATTERNS:
        protected_normalized = normalize_repo_path(protected, allow_glob=True).casefold()
        protected_prefix = glob_static_prefix(protected_normalized)
        if protected_normalized.endswith("/**"):
            if prefix == protected_prefix or prefix.startswith(protected_prefix + "/"):
                return True
        else:
            try:
                if path_matches(protected_normalized, (normalized,)):
                    return True
            except ValueError:
                return True
    return False


def pattern_within_namespaces(pattern: str, namespaces: Iterable[str]) -> bool:
    """Conservatively prove that a task glob stays inside an allowed namespace."""

    normalized = normalize_repo_path(pattern, allow_glob=True)
    has_glob = any(char in normalized for char in "*?[")
    if not has_glob:
        return path_matches(normalized, namespaces)
    prefix = glob_static_prefix(normalized)
    if not prefix:
        return False
    for namespace in namespaces:
        candidate = normalize_repo_path(str(namespace), allow_glob=True).casefold()
        if not candidate.endswith("/**"):
            continue
        namespace_prefix = glob_static_prefix(candidate)
        if prefix == namespace_prefix or prefix.startswith(namespace_prefix + "/"):
            return True
    return False


def is_dependency_manifest_path(path: str) -> bool:
    normalized = normalize_repo_path(path, allow_glob=False)
    basename = normalized.rsplit("/", 1)[-1].casefold()
    if basename in DEPENDENCY_MANIFEST_BASENAMES:
        return True
    if re.fullmatch(r"requirements(?:[-_.][a-z0-9_.-]+)?\.txt", basename):
        return True
    return basename.endswith(".gemspec")


def redact_text(value: str) -> str:
    redacted = JSON_DOUBLE_SECRET_RE.sub(r"\1[REDACTED]\3", value)
    redacted = JSON_SINGLE_SECRET_RE.sub(r"\1[REDACTED]\3", redacted)
    redacted = PRIVATE_KEY_SECRET_RE.sub("[REDACTED PRIVATE KEY]", redacted)
    redacted = SENSITIVE_HEADER_SECRET_RE.sub(r"\1[REDACTED]", redacted)
    redacted = BEARER_SECRET_RE.sub("Bearer [REDACTED]", redacted)
    redacted = URL_USERINFO_SECRET_RE.sub(r"\1[REDACTED]@", redacted)
    redacted = PHONE_SECRET_RE.sub("[REDACTED PHONE]", redacted)
    redacted = ASSIGNMENT_SECRET_RE.sub(lambda match: f"{match.group(1)}[REDACTED]", redacted)
    return redacted


def truncate_utf8(value: str, limit_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= limit_bytes:
        return value, False
    suffix = b"\n[HARNESS OUTPUT TRUNCATED]\n"
    kept = encoded[: max(0, limit_bytes - len(suffix))] + suffix
    return kept.decode("utf-8", errors="replace"), True


def sanitize_remote_url(value: str | None) -> str | None:
    if not value:
        return value
    return re.sub(r"(?i)((?:https?|ssh)://)[^\s/@]+@", r"\1[REDACTED]@", value)


def json_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def validate_json_schema(value: Any, schema: dict[str, Any], location: str = "$") -> list[str]:
    """Validate the JSON-Schema subset used by task.schema.json."""

    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        expected_types = expected if isinstance(expected, list) else [expected]
        if not any(json_type_matches(value, item) for item in expected_types):
            errors.append(f"{location}: 类型应为 {'/'.join(expected_types)}")
            return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{location}: 值不在允许集合 {schema['enum']}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{location}: 缺少必填字段 {key}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{location}: 不允许字段 {key}")
        for key, child in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                errors.extend(validate_json_schema(child, child_schema, f"{location}.{key}"))

    if isinstance(value, list):
        minimum = schema.get("minItems")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{location}: 至少需要 {minimum} 项")
        maximum = schema.get("maxItems")
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(f"{location}: 最多允许 {maximum} 项")
        if schema.get("uniqueItems"):
            seen: set[str] = set()
            for index, item in enumerate(value):
                marker = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if marker in seen:
                    errors.append(f"{location}[{index}]: 与前项重复")
                seen.add(marker)
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(validate_json_schema(item, item_schema, f"{location}[{index}]"))

    if isinstance(value, str):
        minimum = schema.get("minLength")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{location}: 长度至少为 {minimum}")
        maximum = schema.get("maxLength")
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(f"{location}: 长度最多为 {maximum}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
            errors.append(f"{location}: 不匹配格式 {pattern}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{location}: 不得小于 {minimum}")
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{location}: 不得大于 {maximum}")
    return errors


def print_gate(result: GateResult, *, json_output: bool = False) -> int:
    if json_output:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return 0 if result.ok else 1
    mark = "PASS" if result.ok else "FAIL"
    print(f"[{mark}] {result.name}")
    for warning in result.warnings:
        print(f"  [WARN] {warning}")
    for error in result.errors:
        print(f"  [ERROR] {error}")
    if result.data.get("verification_contract_sha256"):
        print(
            "  VERIFY_CONTRACT_SHA256: "
            f"{result.data['verification_contract_sha256']}"
        )
    if result.data.get("summary"):
        print(f"  {result.data['summary']}")
    return 0 if result.ok else 1


def command_text(argv: Sequence[str]) -> str:
    return json.dumps(list(argv), ensure_ascii=False)


def test_command_policy_errors(argv: Sequence[str]) -> list[str]:
    if not argv:
        return ["测试命令不能为空"]
    errors: list[str] = []
    executable = Path(str(argv[0])).name.casefold()
    arguments = [str(item) for item in argv[1:]]
    if executable in NETWORK_CLIENT_EXECUTABLES:
        errors.append(f"禁止网络客户端作为 required_tests 命令：{argv[0]}")
    if executable in COMMAND_WRAPPER_EXECUTABLES:
        errors.append(
            "required_tests 禁止通用命令包装器；请直接声明实际测试运行器 argv"
        )
    for argument in arguments:
        stripped = argument.strip()
        name = stripped
        if "=" in stripped:
            name = stripped.split("=", 1)[0]
        elif ":" in stripped and stripped.startswith(("--", "/")):
            name = stripped.split(":", 1)[0]
        option_name = name.lstrip("-/")
        if SENSITIVE_ARGUMENT_NAME_RE.search(option_name):
            errors.append("required_tests argv 禁止密钥、令牌、口令或凭据参数")
            break
        if BEARER_SECRET_RE.search(stripped) or URL_USERINFO_SECRET_RE.search(stripped):
            errors.append("required_tests argv 禁止内嵌 Authorization 或 URL 凭据")
            break
    if executable in {"mysql", "mysql.exe", "mysqldump", "mysqldump.exe"} and any(
        argument.casefold() == "-p" or argument.casefold().startswith("-p")
        for argument in arguments
    ):
        errors.append("required_tests argv 禁止 MySQL -p/--password 凭据参数")
    inline_flags = {
        "python": {"-c"},
        "python.exe": {"-c"},
        "python3": {"-c"},
        "python3.exe": {"-c"},
        "py": {"-c"},
        "py.exe": {"-c"},
        "php": {"-r"},
        "php.exe": {"-r"},
        "node": {"-e", "--eval"},
        "node.exe": {"-e", "--eval"},
        "ruby": {"-e"},
        "ruby.exe": {"-e"},
        "perl": {"-e"},
        "perl.exe": {"-e"},
    }
    forbidden_flags = inline_flags.get(executable, set())
    if any(argument.casefold() in forbidden_flags for argument in arguments):
        errors.append("required_tests 禁止解释器内联代码")
    if executable in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}:
        for index, argument in enumerate(arguments[:-1]):
            if argument == "-m" and arguments[index + 1].casefold() in {"http.server", "pip"}:
                errors.append(f"required_tests 禁止网络/安装模块：{arguments[index + 1]}")
    mutating_verbs = {
        "composer": {"install", "update", "require", "remove", "create-project", "dump-autoload"},
        "composer.phar": {"install", "update", "require", "remove", "create-project", "dump-autoload"},
        "npm": {"install", "i", "ci", "update", "add", "remove", "uninstall", "publish", "login"},
        "npm.cmd": {"install", "i", "ci", "update", "add", "remove", "uninstall", "publish", "login"},
        "pnpm": {"install", "i", "update", "add", "remove", "publish", "login", "dlx"},
        "pnpm.cmd": {"install", "i", "update", "add", "remove", "publish", "login", "dlx"},
        "yarn": {"install", "update", "add", "remove", "publish", "login", "dlx"},
        "yarn.cmd": {"install", "update", "add", "remove", "publish", "login", "dlx"},
        "pip": {"install", "uninstall", "download", "wheel"},
        "pip.exe": {"install", "uninstall", "download", "wheel"},
        "pip3": {"install", "uninstall", "download", "wheel"},
        "pip3.exe": {"install", "uninstall", "download", "wheel"},
        "uv": {"add", "remove", "sync", "lock", "pip"},
        "uv.exe": {"add", "remove", "sync", "lock", "pip"},
        "git": {"clone", "fetch", "pull", "push", "checkout", "restore", "reset", "clean", "commit", "merge", "rebase", "cherry-pick", "revert", "stash", "apply", "am"},
        "git.exe": {"clone", "fetch", "pull", "push", "checkout", "restore", "reset", "clean", "commit", "merge", "rebase", "cherry-pick", "revert", "stash", "apply", "am"},
    }
    first_verb = next((item.casefold() for item in arguments if not item.startswith("-")), "")
    if first_verb and first_verb in mutating_verbs.get(executable, set()):
        errors.append("required_tests 禁止安装、发布或联网变更命令")
    return errors


def subprocess_text(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: int = 10,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        shell=False,
    )


def bounded_subprocess(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    max_output_bytes: int,
    environment: dict[str, str],
) -> tuple[int | None, bytes, bytes, bool, bool, bool]:
    """Run without a shell while bounding memory and terminating noisy tests."""

    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        env=environment,
        start_new_session=os.name != "nt",
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP
            if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP")
            else 0
        ),
    )
    assert process.stdout is not None and process.stderr is not None
    buffers = [bytearray(), bytearray()]
    exceeded = [False, False]
    limit_event = threading.Event()

    def drain(stream: Any, index: int) -> None:
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                remaining = max(0, max_output_bytes - len(buffers[index]))
                if remaining:
                    buffers[index].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    exceeded[index] = True
                    limit_event.set()
        except (OSError, ValueError):
            return

    readers = [
        threading.Thread(target=drain, args=(process.stdout, 0), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, 1), daemon=True),
    ]
    for reader in readers:
        reader.start()

    timed_out = False
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        if limit_event.is_set():
            break
        if time.monotonic() >= deadline:
            timed_out = True
            break
        time.sleep(0.02)

    if process.poll() is None and (timed_out or limit_event.is_set()):
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
    else:
        process.wait()

    for reader, stream in zip(readers, (process.stdout, process.stderr)):
        reader.join(timeout=2)
        try:
            stream.close()
        except OSError:
            pass
        if reader.is_alive():
            reader.join(timeout=1)
    return (
        process.returncode,
        bytes(buffers[0]),
        bytes(buffers[1]),
        timed_out,
        exceeded[0],
        exceeded[1],
    )


def tool_probe(name: str, version_args: Sequence[str]) -> dict[str, Any]:
    executable = shutil.which(name)
    if not executable:
        return {"status": "not_available", "path": None, "version": None}
    try:
        result = subprocess_text([executable, *version_args], cwd=ROOT, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "blocked", "path": executable, "version": None, "error": str(exc)}
    combined = (result.stdout or result.stderr).strip().splitlines()
    return {
        "status": "confirmed" if result.returncode == 0 else "blocked",
        "path": executable,
        "version": redact_text(combined[0]) if combined else None,
        "exit_code": result.returncode,
    }


class Harness:
    def __init__(self, root: Path = ROOT) -> None:
        self.root, _root_components = lexical_path_components(root)
        ensure_repo_path_safe(self.root, self.root, label="仓库根目录")
        self.harness_dir = self.root / ".harness"
        self.tasks_dir = self.harness_dir / "tasks"
        self.runs_dir = self.harness_dir / "runs"
        self.reports_dir = self.harness_dir / "reports"
        self.state_file = self.harness_dir / "state" / "active-task.json"
        self.config_file = self.harness_dir / "harness.json"
        ensure_repo_path_safe(self.root, self.harness_dir, label=".harness")
        if not self.config_file.is_file():
            raise HarnessError(f"缺少 Harness 配置：{display_path(self.config_file)}")
        config = read_json(self.config_file)
        if not isinstance(config, dict):
            raise HarnessError(".harness/harness.json 顶层必须是 JSON object")
        self.config: dict[str, Any] = config
        self._workflow_lock_local = threading.local()
        for directory in (
            self.tasks_dir,
            self.runs_dir,
            self.reports_dir,
            self.harness_dir / "state",
            self.harness_dir / "templates",
            self.harness_dir / "schemas",
            self.harness_dir / "baselines",
        ):
            ensure_repo_path_safe(
                self.root,
                directory,
                label=f"Harness 关键目录 {display_path(directory)}",
            )

    def status_transitions(self) -> dict[str, tuple[str, ...]]:
        workflow = self.config.get("workflow", {})
        configured = workflow.get("status_transitions") if isinstance(workflow, dict) else None
        if not isinstance(configured, dict):
            raise HarnessError("workflow.status_transitions 必须是 object")
        if set(configured) != set(SAFE_STATUS_TRANSITIONS):
            missing = sorted(set(SAFE_STATUS_TRANSITIONS) - set(configured))
            extra = sorted(set(configured) - set(SAFE_STATUS_TRANSITIONS))
            detail = []
            if missing:
                detail.append("缺少 " + ", ".join(missing))
            if extra:
                detail.append("未知 " + ", ".join(extra))
            raise HarnessError("status_transitions 状态集合不安全：" + "；".join(detail))
        for source, expected in SAFE_STATUS_TRANSITIONS.items():
            targets = configured.get(source)
            if not isinstance(targets, list):
                raise HarnessError(f"status_transitions.{source} 必须是 array")
            normalized = tuple(str(item) for item in targets)
            if len(normalized) != len(set(normalized)):
                raise HarnessError(f"status_transitions.{source} 包含重复目标")
            if set(normalized) != set(expected):
                raise HarnessError(
                    f"status_transitions.{source} 必须固定为安全边：{', '.join(expected) or '<none>'}"
                )
        return SAFE_STATUS_TRANSITIONS

    def workflow_transaction_path(self, task_id: str) -> Path:
        normalized = self.validate_task_id(task_id)
        path = self.harness_dir / "state" / "workflow-transactions" / f"{normalized}.json"
        ensure_repo_path_safe(self.root, path, label="工作流事务日志路径")
        return path

    def workflow_lock_path(self, task_id: str) -> Path:
        normalized = self.validate_task_id(task_id)
        path = self.harness_dir / "state" / "workflow-locks" / f"{normalized}.lock"
        try:
            ensure_repo_path_safe(self.root, path, label="工作流锁路径")
        except HarnessError as exc:
            raise WorkflowLockError(str(exc)) from exc
        return path

    @contextlib.contextmanager
    def workflow_lock(self, task_id: str) -> Iterable[None]:
        normalized = self.validate_task_id(task_id)
        held = getattr(self._workflow_lock_local, "held", None)
        if held is None:
            held = {}
            self._workflow_lock_local.held = held
        if normalized in held:
            held[normalized] += 1
            try:
                yield
            finally:
                held[normalized] -= 1
            return
        path = self.workflow_lock_path(normalized)
        guard_path = path.with_name(f".{path.name}.guard")
        token = uuid.uuid4().hex
        deadline = time.monotonic() + WORKFLOW_LOCK_WAIT_SECONDS
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkflowLockError(f"无法创建任务工作流锁目录：{exc}") from exc
        try:
            ensure_repo_path_safe(self.root, path.parent, label="工作流锁目录")
            ensure_repo_path_safe(self.root, path, label="工作流锁路径")
        except HarnessError as exc:
            raise WorkflowLockError(str(exc)) from exc
        while True:
            acquired = False
            with advisory_lock_guard(
                self.root,
                guard_path,
                deadline=deadline,
                label=f"任务 {normalized} 工作流锁 guard",
                anchor=self.harness_dir / "state",
            ):
                try:
                    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    try:
                        lock_stat = path.stat()
                        age = time.time() - lock_stat.st_mtime
                    except FileNotFoundError:
                        continue
                    except OSError as exc:
                        raise WorkflowLockError(f"无法检查任务工作流锁：{exc}") from exc
                    try:
                        owner = read_json(path)
                    except HarnessError:
                        owner = None
                    owner_pid = owner.get("pid") if isinstance(owner, dict) else None
                    owner_token = owner.get("token") if isinstance(owner, dict) else None
                    owner_instance = (
                        owner.get("process_instance") if isinstance(owner, dict) else None
                    )
                    owner_dead = isinstance(owner_pid, int) and not process_is_alive(owner_pid)
                    observed_instance = (
                        process_instance_id(owner_pid)
                        if isinstance(owner_pid, int) and isinstance(owner_instance, str)
                        else None
                    )
                    owner_reused = bool(
                        isinstance(owner_instance, str)
                        and observed_instance
                        and owner_instance != observed_instance
                    )
                    invalid_and_stale = (
                        not isinstance(owner_pid, int)
                        and age > WORKFLOW_LOCK_STALE_SECONDS
                    )
                    if owner_dead or owner_reused or invalid_and_stale:
                        try:
                            if owner_token:
                                current = read_json(path)
                                if (
                                    isinstance(current, dict)
                                    and current.get("token") != owner_token
                                ):
                                    continue
                            path.unlink()
                        except FileNotFoundError:
                            continue
                        except (OSError, HarnessError) as exc:
                            raise WorkflowLockError(
                                f"无法清理过期任务工作流锁：{exc}"
                            ) from exc
                        continue
                    if time.monotonic() >= deadline:
                        raise WorkflowLockError(
                            f"任务 {normalized} 正由另一进程更新；等待 "
                            f"{WORKFLOW_LOCK_WAIT_SECONDS:g} 秒后仍未释放"
                        )
                except OSError as exc:
                    raise WorkflowLockError(f"无法创建任务工作流锁：{exc}") from exc
                else:
                    try:
                        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                            handle.write(
                                json.dumps(
                                    {
                                        "schema_version": 1,
                                        "task_id": normalized,
                                        "token": token,
                                        "pid": os.getpid(),
                                        "process_instance": process_instance_id(os.getpid()),
                                        "acquired_at": utc_now(),
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                            handle.flush()
                            os.fsync(handle.fileno())
                    except BaseException as exc:
                        try:
                            path.unlink(missing_ok=True)
                        except OSError as cleanup_error:
                            exc.add_note(
                                "创建任务工作流锁失败后无法清理残留锁："
                                f"{cleanup_error}"
                            )
                        raise
                    acquired = True
            if acquired:
                break
            time.sleep(0.05)
        held[normalized] = 1
        try:
            yield
        finally:
            try:
                release_owner_lock(
                    self.root,
                    path,
                    guard_path,
                    token=token,
                    label=f"任务 {normalized} 工作流锁",
                    anchor=self.harness_dir / "state",
                )
            finally:
                held.pop(normalized, None)

    def active_state_lock_path(self) -> Path:
        path = self.harness_dir / "state" / "active-state.lock"
        try:
            ensure_repo_path_safe(self.root, path, label="全局 active state 锁路径")
        except HarnessError as exc:
            raise WorkflowLockError(str(exc)) from exc
        return path

    @contextlib.contextmanager
    def active_state_lock(self) -> Iterable[None]:
        depth = getattr(self._workflow_lock_local, "active_state_depth", 0)
        if depth:
            self._workflow_lock_local.active_state_depth = depth + 1
            try:
                yield
            finally:
                self._workflow_lock_local.active_state_depth -= 1
            return
        path = self.active_state_lock_path()
        guard_path = path.with_name(f".{path.name}.guard")
        token = uuid.uuid4().hex
        deadline = time.monotonic() + WORKFLOW_LOCK_WAIT_SECONDS
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkflowLockError(f"无法创建全局 active state 锁目录：{exc}") from exc
        try:
            ensure_repo_path_safe(self.root, path.parent, label="全局 active state 锁目录")
            ensure_repo_path_safe(self.root, path, label="全局 active state 锁路径")
        except HarnessError as exc:
            raise WorkflowLockError(str(exc)) from exc
        while True:
            acquired = False
            with advisory_lock_guard(
                self.root,
                guard_path,
                deadline=deadline,
                label="全局 active state 锁 guard",
                anchor=self.harness_dir / "state",
            ):
                try:
                    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    try:
                        lock_stat = path.stat()
                        age = time.time() - lock_stat.st_mtime
                        owner = read_json(path)
                    except FileNotFoundError:
                        continue
                    except HarnessError:
                        # The stat above already captured age.  Treat unreadable
                        # content as an invalid owner without a second racy stat.
                        owner = None
                    except OSError as exc:
                        raise WorkflowLockError(
                            f"无法检查全局 active state 锁：{exc}"
                        ) from exc
                    owner_pid = owner.get("pid") if isinstance(owner, dict) else None
                    owner_token = owner.get("token") if isinstance(owner, dict) else None
                    owner_instance = (
                        owner.get("process_instance") if isinstance(owner, dict) else None
                    )
                    owner_dead = isinstance(owner_pid, int) and not process_is_alive(owner_pid)
                    observed_instance = (
                        process_instance_id(owner_pid)
                        if isinstance(owner_pid, int) and isinstance(owner_instance, str)
                        else None
                    )
                    owner_reused = bool(
                        isinstance(owner_instance, str)
                        and observed_instance
                        and owner_instance != observed_instance
                    )
                    invalid_and_stale = (
                        not isinstance(owner_pid, int)
                        and age > WORKFLOW_LOCK_STALE_SECONDS
                    )
                    if owner_dead or owner_reused or invalid_and_stale:
                        try:
                            if owner_token:
                                current = read_json(path)
                                if (
                                    isinstance(current, dict)
                                    and current.get("token") != owner_token
                                ):
                                    continue
                            path.unlink()
                        except FileNotFoundError:
                            continue
                        except (OSError, HarnessError) as exc:
                            raise WorkflowLockError(
                                f"无法清理过期全局 active state 锁：{exc}"
                            ) from exc
                        continue
                    if time.monotonic() >= deadline:
                        raise WorkflowLockError(
                            "全局 active state 正由另一进程更新；等待 "
                            f"{WORKFLOW_LOCK_WAIT_SECONDS:g} 秒后仍未释放"
                        )
                except OSError as exc:
                    raise WorkflowLockError(f"无法创建全局 active state 锁：{exc}") from exc
                else:
                    try:
                        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                            handle.write(
                                json.dumps(
                                    {
                                        "schema_version": 1,
                                        "name": "active-state",
                                        "token": token,
                                        "pid": os.getpid(),
                                        "process_instance": process_instance_id(os.getpid()),
                                        "acquired_at": utc_now(),
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                            handle.flush()
                            os.fsync(handle.fileno())
                    except BaseException as exc:
                        try:
                            path.unlink(missing_ok=True)
                        except OSError as cleanup_error:
                            exc.add_note(
                                "创建全局 active state 锁失败后无法清理残留锁："
                                f"{cleanup_error}"
                            )
                        raise
                    acquired = True
            if acquired:
                break
            time.sleep(0.05)
        self._workflow_lock_local.active_state_depth = 1
        try:
            yield
        finally:
            try:
                release_owner_lock(
                    self.root,
                    path,
                    guard_path,
                    token=token,
                    label="全局 active state 锁",
                    anchor=self.harness_dir / "state",
                )
            finally:
                self._workflow_lock_local.active_state_depth = 0

    def recover_workflow_transaction(self, task_id: str) -> None:
        normalized = self.validate_task_id(task_id)
        with self.workflow_lock(normalized):
            self._recover_workflow_transaction_locked(normalized)

    def _recover_workflow_transaction_locked(self, task_id: str) -> None:
        normalized = self.validate_task_id(task_id)
        journal_path = self.workflow_transaction_path(normalized)
        if not journal_path.is_file():
            return
        journal = read_json(journal_path)
        if (
            not isinstance(journal, dict)
            or journal.get("schema_version") != 1
            or journal.get("task_id") != normalized
            or not isinstance(journal.get("original_task"), str)
            or not isinstance(journal.get("new_task"), dict)
            or not isinstance(journal.get("new_history"), dict)
            or not (
                journal.get("original_history") is None
                or isinstance(journal.get("original_history"), str)
            )
        ):
            raise HarnessError(f"工作流事务日志无效：{display_path(journal_path)}")

        task_path = self.task_path(normalized)
        history_path = self.task_dir(normalized) / "workflow-history.json"
        try:
            current_task = task_path.read_text(encoding="utf-8") if task_path.is_file() else None
            current_history = history_path.read_text(encoding="utf-8") if history_path.is_file() else None
        except OSError as exc:
            raise HarnessError(f"无法检查工作流事务恢复状态：{exc}") from exc

        original_task = journal["original_task"]
        original_history = journal.get("original_history")
        new_task = json.dumps(journal["new_task"], ensure_ascii=False, indent=2) + "\n"
        new_history = json.dumps(journal["new_history"], ensure_ascii=False, indent=2) + "\n"

        if current_task == new_task and current_history == new_history:
            recovery = "已提交"
        elif current_task == original_task and current_history == original_history:
            recovery = "未开始"
        elif current_task in {original_task, new_task} and current_history in {
            original_history,
            new_history,
        }:
            try:
                atomic_write_text(task_path, original_task)
                if original_history is None:
                    history_path.unlink(missing_ok=True)
                else:
                    atomic_write_text(history_path, original_history)
            except OSError as exc:
                raise HarnessError(f"工作流半提交回滚失败：{exc}") from exc
            recovery = "已回滚"
        else:
            raise HarnessError(
                "工作流事务中断后 task/history 又被外部修改；拒绝自动覆盖，请人工审查 "
                + display_path(journal_path)
            )
        try:
            journal_path.unlink()
        except OSError as exc:
            raise HarnessError(f"工作流事务{recovery}但日志无法清理：{exc}") from exc

    # ---------- Git and source facts ----------

    def git(self, *args: str, timeout: int = 15, check: bool = False) -> subprocess.CompletedProcess[str]:
        executable = shutil.which("git")
        if not executable:
            raise HarnessError("Git 不可用")
        try:
            result = subprocess_text([executable, *args], cwd=self.root, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise HarnessError(f"Git 命令超时：git {' '.join(args)}") from exc
        except OSError as exc:
            raise HarnessError(f"Git 命令无法执行：{exc}") from exc
        if check and result.returncode != 0:
            detail = redact_text((result.stderr or result.stdout).strip())
            raise HarnessError(f"Git 命令失败：git {' '.join(args)}：{detail}")
        return result

    def git_value(self, *args: str) -> str | None:
        try:
            result = self.git(*args)
        except HarnessError:
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def is_git_repository(self) -> bool:
        value = self.git_value("rev-parse", "--is-inside-work-tree")
        return value == "true"

    def branch(self) -> str | None:
        value = self.git_value("branch", "--show-current")
        return value or None

    def head(self) -> str | None:
        return self.git_value("rev-parse", "HEAD")

    def git_object_exists(self, value: str) -> bool:
        result = self.git("cat-file", "-e", f"{value}^{{commit}}")
        return result.returncode == 0

    def is_ancestor(self, base: str, head: str = "HEAD") -> bool:
        return self.git("merge-base", "--is-ancestor", base, head).returncode == 0

    def source_status(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for spec in self.config.get("source", {}).get("required_paths", []):
            rel = str(spec.get("path", ""))
            kind = str(spec.get("kind", "file"))
            try:
                normalized = normalize_repo_path(rel, allow_glob=False)
            except ValueError as exc:
                entries.append(
                    {
                        "path": rel,
                        "kind": kind,
                        "status": "blocked",
                        "detail": f"invalid configured path: {exc}",
                    }
                )
                continue
            path = self.root / Path(*normalized.split("/"))
            path_error = repo_path_safety_error(self.root, path)
            if path_error:
                entries.append(
                    {
                        "path": normalized,
                        "kind": kind,
                        "status": "blocked",
                        "detail": path_error,
                    }
                )
                continue
            if kind == "file":
                exists = path.is_file()
            elif kind == "directory":
                exists = path.is_dir()
            else:
                entries.append(
                    {
                        "path": normalized,
                        "kind": kind,
                        "status": "blocked",
                        "detail": "kind must be file or directory",
                    }
                )
                continue
            entries.append(
                {
                    "path": normalized,
                    "kind": kind,
                    "status": "confirmed" if exists else "not_available",
                }
            )
        return entries

    def pinned_source_commit(self) -> str | None:
        source = self.config.get("source", {})
        value = source.get("pinned_commit") if isinstance(source, dict) else None
        return str(value) if isinstance(value, str) and value else None

    def repository_baseline_facts(self) -> dict[str, Any]:
        source = self.config.get("source", {})
        configured_upstream = source.get("upstream_remote") if isinstance(source, dict) else None
        shopxo_version = source.get("shopxo_version") if isinstance(source, dict) else None
        return {
            "repository_baseline_policy_version": REPOSITORY_BASELINE_POLICY_VERSION,
            "configured_upstream_remote": sanitize_remote_url(
                str(configured_upstream) if configured_upstream else None
            ),
            "actual_upstream_remote": sanitize_remote_url(
                self.git_value("remote", "get-url", "upstream")
            ),
            "shopxo_version": str(shopxo_version) if shopxo_version is not None else None,
            "pinned_commit": self.pinned_source_commit(),
            "required_source_paths": self.source_status(),
        }

    def current_toolchain(self) -> dict[str, Any]:
        return {
            "python": {
                "status": "confirmed" if sys.version_info >= MIN_PYTHON else "blocked",
                "path": sys.executable,
                "version": platform.python_version(),
            },
            "git": tool_probe("git", ["--version"]),
            "php": tool_probe("php", ["--version"]),
            "composer": tool_probe("composer", ["--version"]),
            "mysql": tool_probe("mysql", ["--version"]),
            "psql": tool_probe("psql", ["--version"]),
            "sqlite3": tool_probe("sqlite3", ["--version"]),
        }

    def project_toolchain_requirements(self) -> dict[str, Any]:
        return {
            "php": ">=8.0.2",
            "database": "MySQL 8.0 recommended for the reproducible development baseline",
            "evidence": [
                "composer.json",
                "public/core.php",
                "vendor/composer/platform_check.php",
            ],
        }

    def composer_file_status(self) -> dict[str, Any]:
        def file_fact(name: str) -> dict[str, Any]:
            path = self.root / name
            if repo_path_safety_error(self.root, path) or not path.is_file():
                return {"present": False, "sha256": None}
            try:
                digest = canonical_text_file_sha256(path, label=name)
            except HarnessError:
                digest = None
            return {"present": True, "sha256": digest}

        composer_json = file_fact("composer.json")
        composer_lock = file_fact("composer.lock")
        return {
            "status": "confirmed" if composer_json["present"] else "not_available",
            "composer_json": composer_json,
            "composer_lock": composer_lock,
            "hash_mode": "utf8-lf-v1",
        }

    def portable_toolchain_facts(self) -> dict[str, Any]:
        return {
            "project_requirements": self.project_toolchain_requirements(),
            "composer_files": self.composer_file_status(),
        }

    def migration_mechanism_facts(self) -> dict[str, Any]:
        paths = (
            "app/install/controller/Index.php",
            "app/service/SystemUpgradeService.php",
            "app/service/PluginsAdminService.php",
            "app/service/SqlConsoleService.php",
        )
        files: dict[str, dict[str, Any]] = {}
        for rel in paths:
            path = self.root / rel
            path_error = repo_path_safety_error(self.root, path)
            if path_error or not path.is_file():
                files[rel] = {"present": False, "sha256": None}
                continue
            try:
                digest = canonical_text_file_sha256(path, label=rel)
            except HarnessError:
                digest = None
            files[rel] = {"present": True, "sha256": digest}
        return {
            "policy_version": 1,
            "hash_mode": "utf8-lf-v1",
            "files": files,
        }

    def discovered_test_files(self) -> list[str]:
        candidates: list[str] = []
        for pattern in ("phpunit.xml*", "tests/**", "test/**"):
            for path in self.root.glob(pattern):
                if ".git" in path.parts or "vendor" in path.parts:
                    continue
                if repo_path_safety_error(self.root, path) is None and path.is_file():
                    candidates.append(path.relative_to(self.root).as_posix())
        return sorted(set(candidates))[:500]

    def repository_dirty_paths(self) -> list[str]:
        if not self.is_git_repository():
            return []
        result = self.git("status", "--porcelain=v1", "-z", "--untracked-files=all", check=True)
        entries = result.stdout.split("\x00")
        paths: list[str] = []
        index = 0
        while index < len(entries):
            record = entries[index]
            index += 1
            if not record:
                continue
            if len(record) < 4:
                paths.append(record)
                continue
            code = record[:2]
            path = record[3:]
            if code[0] in ("R", "C") or code[1] in ("R", "C"):
                if index < len(entries) and entries[index]:
                    paths.extend([path, entries[index]])
                    index += 1
            else:
                paths.append(path)
        return sorted(set(item.replace("\\", "/") for item in paths if item))

    # ---------- Contracts and requirements ----------

    def validate_task_id(self, task_id: str) -> str:
        normalized = task_id.strip().upper()
        if not TASK_ID_RE.fullmatch(normalized):
            raise HarnessError(
                "任务编号格式错误，应为 NUR-(FEAT|BUG|UI|DATA|SEC|OPS|DOC|REFACTOR|HARNESS)-NNN"
            )
        return normalized

    def task_dir(self, task_id: str) -> Path:
        directory = self.tasks_dir / self.validate_task_id(task_id)
        ensure_repo_path_safe(self.root, directory, label="任务目录")
        return directory

    def task_path(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "task.json"

    def plan_artifacts_sha256(self, task_id: str) -> str:
        """Hash the four reviewed planning artifacts using repo-portable names and bytes."""

        normalized = self.validate_task_id(task_id)
        digest = hashlib.sha256()
        directory = self.task_dir(normalized)
        for name in PLAN_ARTIFACT_NAMES:
            path = directory / name
            ensure_repo_path_safe(self.root, path, label=f"计划制品 {name}")
            try:
                raw_payload = path.read_bytes()
            except OSError as exc:
                raise HarnessError(
                    f"无法读取计划制品 {display_path(path)}：{exc}"
                ) from exc
            payload = canonical_utf8_text_bytes(
                raw_payload,
                label=f"计划制品 {display_path(path)}",
            )
            digest.update(name.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(str(len(payload)).encode("ascii"))
            digest.update(b"\x00")
            digest.update(payload)
            digest.update(b"\x00")
        return digest.hexdigest()

    def load_task(self, task_id: str) -> dict[str, Any]:
        normalized = self.validate_task_id(task_id)
        with self.workflow_lock(normalized):
            self._recover_workflow_transaction_locked(normalized)
            path = self.task_path(normalized)
            if not path.is_file():
                raise HarnessError(f"任务合同不存在：{display_path(path)}")
            value = read_json(path)
            if not isinstance(value, dict):
                raise HarnessError(f"任务合同顶层必须是 JSON object：{display_path(path)}")
            return value

    def requirements_path(self) -> Path:
        rel = self.config.get("project", {}).get(
            "requirements_file", "ShopXO苗木平台需求规格说明书_V1.0.md"
        )
        return self.root / str(rel)

    def known_requirement_ids(self) -> set[str]:
        path = self.requirements_path()
        if not path.is_file():
            raise HarnessError(f"需求文档不存在：{display_path(path)}")
        ensure_repo_path_safe(self.root, path, label="需求文档")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HarnessError(f"无法读取需求文档：{exc}") from exc
        return {match.upper() for match in REQUIREMENT_ID_RE.findall(text)}

    def decisions(self) -> list[dict[str, Any]]:
        rel = self.config.get("project", {}).get(
            "decisions_file", ".harness/requirements-decisions.json"
        )
        path = self.root / str(rel)
        if not path.is_file():
            raise HarnessError(f"开放决策文件不存在：{display_path(path)}")
        value = read_json(path)
        if not isinstance(value, dict) or not isinstance(value.get("decisions"), list):
            raise HarnessError("requirements-decisions.json 必须包含 decisions array")
        decisions: list[dict[str, Any]] = []
        for index, item in enumerate(value["decisions"]):
            if not isinstance(item, dict):
                raise HarnessError(f"decisions[{index}] 必须是 object")
            decisions.append(item)
        return decisions

    def decision_map(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in self.decisions():
            decision_id = str(item.get("id", "")).strip().upper()
            if not decision_id or decision_id in result:
                raise HarnessError(f"决策编号缺失或重复：{decision_id or '<empty>'}")
            result[decision_id] = item
        return result

    def decision_context_sha256(self, task: dict[str, Any]) -> str:
        decisions = self.decision_map()
        selected: dict[str, dict[str, Any]] = {}
        for raw_id in task.get("decision_ids", []):
            decision_id = str(raw_id).strip().upper()
            if decision_id not in decisions:
                raise HarnessError(f"无法计算决策上下文，未知决策编号：{decision_id}")
            selected[decision_id] = decisions[decision_id]
        return canonical_json_hash(selected)

    def related_decision_ids(self, requirement_ids: Iterable[str]) -> list[str]:
        requirements = {item.upper() for item in requirement_ids}
        related: list[str] = []
        for item in self.decisions():
            affected = {str(value).upper() for value in item.get("affected_requirement_ids", [])}
            if requirements & affected:
                related.append(str(item.get("id", "")).upper())
        return sorted(set(related))

    def task_schema(self) -> dict[str, Any]:
        rel = self.config.get("project", {}).get(
            "task_schema", ".harness/schemas/task.schema.json"
        )
        value = read_json(self.root / str(rel))
        if not isinstance(value, dict):
            raise HarnessError("task.schema.json 顶层必须是 object")
        return value

    def check_approval_object(
        self,
        name: str,
        approval: Any,
        result: GateResult,
    ) -> None:
        if not isinstance(approval, dict):
            return
        required = approval.get("required")
        status = approval.get("status")
        approved_by = approval.get("approved_by")
        approved_at = approval.get("approved_at")
        if required is True and status == "not_required":
            result.errors.append(f"manual_approvals.{name} 已声明 required，状态不能是 not_required")
        if required is False and status not in ("not_required", "pending"):
            result.errors.append(f"manual_approvals.{name} 非必需，不应伪造批准状态 {status}")
        if status == "approved":
            if not isinstance(approved_by, str) or not approved_by.strip():
                result.errors.append(f"manual_approvals.{name} approved 缺少 approved_by")
            if not isinstance(approved_at, str) or not approved_at.strip():
                result.errors.append(f"manual_approvals.{name} approved 缺少 approved_at")
        elif approved_by is not None or approved_at is not None:
            result.errors.append(
                f"manual_approvals.{name} 未 approved 时 approved_by/approved_at 必须为 null"
            )

    @staticmethod
    def expected_approval_actor(task: dict[str, Any], stage: str) -> str:
        if stage == "release":
            return str(task.get("release_approver") or "").strip()
        return str(task.get("reviewer") or "").strip()

    @staticmethod
    def codex_role_binding(
        task: dict[str, Any], stage: str
    ) -> dict[str, Any] | None:
        bindings = task.get("codex_role_bindings")
        if not isinstance(bindings, dict):
            return None
        value = bindings.get(stage)
        return value if isinstance(value, dict) else None

    def check_codex_role_bindings(
        self,
        task: dict[str, Any],
        approvals: Any,
        result: GateResult,
    ) -> None:
        bindings = task.get("codex_role_bindings")
        if not isinstance(bindings, dict):
            return
        implementation = bindings.get("implementation")
        stage_values = {stage: bindings.get(stage) for stage in APPROVAL_STAGES}
        if implementation is None:
            populated = [stage for stage, value in stage_values.items() if value is not None]
            if populated:
                result.errors.append(
                    "codex_role_bindings.implementation 为 null 时 plan/merge/release 也必须为 null"
                )
            return
        if not isinstance(implementation, dict):
            return

        implementation_task = str(implementation.get("agent_task", "")).strip()
        implementation_thread = str(implementation.get("thread_id", "")).strip()
        if not CODEX_AGENT_TASK_RE.fullmatch(implementation_task):
            result.errors.append(
                "codex_role_bindings.implementation.agent_task 必须是 canonical /root task"
            )
        if not CODEX_THREAD_ID_RE.fullmatch(implementation_thread):
            result.errors.append(
                "codex_role_bindings.implementation.thread_id 必须是 Codex task UUID"
            )

        approval_values = approvals if isinstance(approvals, dict) else {}
        for stage in APPROVAL_STAGES:
            approval = approval_values.get(stage)
            required = isinstance(approval, dict) and approval.get("required") is True
            binding = stage_values[stage]
            if required and not isinstance(binding, dict):
                result.errors.append(
                    f"自动审批任务的 required {stage} 必须声明 codex_role_bindings.{stage}"
                )
            if not isinstance(binding, dict):
                continue
            agent_task = str(binding.get("agent_task", "")).strip()
            if not CODEX_AGENT_TASK_RE.fullmatch(agent_task):
                result.errors.append(
                    f"codex_role_bindings.{stage}.agent_task 必须是 canonical /root task"
                )
            if agent_task and agent_task == implementation_task:
                result.errors.append(
                    f"codex_role_bindings.{stage}.agent_task 必须与 implementation 不同"
                )

        release = stage_values.get("release")
        if isinstance(release, dict):
            release_task = str(release.get("agent_task", "")).strip()
            for stage in ("plan", "merge"):
                binding = stage_values.get(stage)
                if (
                    isinstance(binding, dict)
                    and release_task
                    and release_task == str(binding.get("agent_task", "")).strip()
                ):
                    result.errors.append(
                        f"codex_role_bindings.release.agent_task 必须与 {stage} 不同"
                    )

    @staticmethod
    def approval_resets_for_transition(target_status: str) -> tuple[str, ...]:
        if target_status in {"ready_for_analysis", "awaiting_plan_approval"}:
            return ("plan", "merge", "release")
        if target_status in {
            "approved_for_implementation",
            "implementing",
            "verifying",
            "awaiting_review",
        }:
            return ("merge", "release")
        return ()

    @staticmethod
    def reset_approval_values(task: dict[str, Any], stages: Iterable[str]) -> None:
        approvals = task.get("manual_approvals")
        if not isinstance(approvals, dict):
            return
        for stage in stages:
            approval = approvals.get(stage)
            if not isinstance(approval, dict):
                continue
            approval["status"] = "pending" if approval.get("required") is True else "not_required"
            approval["approved_by"] = None
            approval["approved_at"] = None

    def approval_artifact_path(self, task_id: str, stage: str) -> Path:
        normalized = self.validate_task_id(task_id)
        if stage not in APPROVAL_ARTIFACT_NAMES:
            raise HarnessError(f"不支持的审批阶段：{stage}")
        path = self.task_dir(normalized) / APPROVAL_ARTIFACT_NAMES[stage]
        ensure_repo_path_safe(self.root, path, label=f"{stage} 审查制品")
        return path

    def approval_workspace_fingerprint(self, task_id: str, base: str) -> str:
        """Use the same stable business-diff fingerprint as verify/review gates."""

        return self.workspace_fingerprint(task_id, base)

    def review_stage_context_sources(
        self, task_id: str, task: dict[str, Any]
    ) -> dict[str, Any]:
        normalized = self.validate_task_id(task_id)
        pack_path = self.latest_review_pack(normalized)
        if pack_path is None:
            raise HarnessError("merge/release 审批缺少 review-pack.json")
        ensure_repo_path_safe(self.root, pack_path, label="review-pack.json")
        if path_is_link_like(pack_path) or not pack_path.is_file():
            raise HarnessError("review-pack.json 必须是仓库内普通文件")
        pack, pack_hash = canonical_json_file_sha256(
            pack_path, label="review-pack.json"
        )
        if not isinstance(pack, dict):
            raise HarnessError("review-pack.json 顶层必须是 object")
        if pack.get("task_id") != normalized or pack.get("ready_for_review") is not True:
            raise HarnessError("review-pack.json 不属于当前任务或未通过自动门禁")
        if pack.get("contract_sha256") != immutable_contract_hash(task):
            raise HarnessError("review-pack.json 属于旧任务合同")
        if pack.get("policy_sha256") != policy_contract_hash(task):
            raise HarnessError("review-pack.json 属于旧执行策略")
        base = str(pack.get("scope_base_commit", ""))
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", base):
            raise HarnessError("review-pack.json 缺少有效 scope_base_commit")
        state = self.read_active_state()
        if isinstance(state, dict):
            if state.get("task_id") != normalized:
                raise HarnessError("active state 属于其他任务")
            if state.get("scope_base_commit") != base:
                raise HarnessError("review-pack.json 与 active state 的范围基准不一致")
        elif task.get("status") not in {"approved_for_merge", "closed"}:
            raise HarnessError("merge/release 审批缺少当前任务的 active state")

        evidence_path = self.task_dir(normalized) / "evidence.md"
        ensure_repo_path_safe(self.root, evidence_path, label="evidence.md")
        if path_is_link_like(evidence_path) or not evidence_path.is_file():
            raise HarnessError("merge/release 审批缺少普通文件 evidence.md")
        return {
            "contract_sha256": immutable_contract_hash(task),
            "policy_sha256": policy_contract_hash(task),
            "review_pack_path": display_path(pack_path),
            "review_pack_sha256": pack_hash,
            "workspace_sha256": self.approval_workspace_fingerprint(normalized, base),
            "evidence_sha256": canonical_text_file_sha256(
                evidence_path, label="evidence.md"
            ),
            "verification_contract_sha256": self.verification_contract_sha256(
                normalized, task
            ),
        }

    def approval_context(self, task_id: str, task: dict[str, Any], stage: str) -> dict[str, Any]:
        normalized = self.validate_task_id(task_id)
        if stage == "plan":
            return {
                "schema_version": 1,
                "task_id": normalized,
                "stage": stage,
                "contract_sha256": plan_review_contract_hash(task),
                "policy_sha256": plan_review_policy_hash(task),
                "plan_artifacts_sha256": self.plan_artifacts_sha256(normalized),
                "decision_context_sha256": self.decision_context_sha256(task),
            }
        if stage not in {"merge", "release"}:
            raise HarnessError(f"不支持的审批阶段：{stage}")
        sources = self.review_stage_context_sources(normalized, task)
        context: dict[str, Any] = {
            "schema_version": 1,
            "task_id": normalized,
            "stage": stage,
            **sources,
        }
        if stage == "release":
            approvals = task.get("manual_approvals")
            merge = approvals.get("merge") if isinstance(approvals, dict) else None
            reviewer = self.expected_approval_actor(task, "merge")
            if not self.approval_is_valid(merge, reviewer):
                raise HarnessError("release 审批前必须已有有效 merge 审批")
            review_path = self.task_dir(normalized) / "review.md"
            release_note_path = self.task_dir(normalized) / "release-note.md"
            for path, label in (
                (review_path, "review.md"),
                (release_note_path, "release-note.md"),
            ):
                ensure_repo_path_safe(self.root, path, label=label)
                if path_is_link_like(path) or not path.is_file():
                    raise HarnessError(f"release 审批缺少普通文件 {label}")
            readiness_errors = self.markdown_check(
                review_path,
                required_headings=("## 审查范围", "## 发现", "## 审查结论"),
                minimum_chars=300,
            )
            readiness_errors.extend(
                self.markdown_check(
                    release_note_path,
                    required_headings=(
                        "## 变更摘要",
                        "## 发布前提",
                        "## 发布步骤",
                        "## 回滚触发与步骤",
                        "## 发布后验证",
                    ),
                    minimum_chars=450,
                )
            )
            if readiness_errors:
                raise HarnessError("release readiness 未通过：" + "; ".join(readiness_errors))
            review_text = review_path.read_text(encoding="utf-8")
            if not re.search(r"(?m)^\s*REVIEW_RESULT:\s*APPROVED\s*$", review_text):
                raise HarnessError("release 审批要求 review.md 标记 REVIEW_RESULT: APPROVED")
            if reviewer and not re.search(
                rf"(?im)^\s*REVIEWER:\s*{re.escape(reviewer)}\s*$",
                review_text,
            ):
                raise HarnessError("release 审批要求 review.md 匹配当前 reviewer")
            if not re.search(r"(?im)^\s*REVIEWED_AT:\s*\S.+$", review_text):
                raise HarnessError("release 审批要求 review.md 记录 REVIEWED_AT")
            context.update(
                {
                    "merge_approval": {
                        "approved_by": merge.get("approved_by"),
                        "approved_at": merge.get("approved_at"),
                    },
                    "review_sha256": canonical_text_file_sha256(
                        review_path, label="review.md"
                    ),
                    "release_note_sha256": canonical_text_file_sha256(
                        release_note_path, label="release-note.md"
                    ),
                    "remote_execution_sha256": canonical_json_hash(
                        task.get("remote_execution")
                    ),
                }
            )
        return context

    def validate_approval_artifact(
        self,
        task_id: str,
        task: dict[str, Any],
        *,
        stage: str,
        status: str,
        actor: str,
        agent_task: str,
        codex_thread_id: str,
    ) -> tuple[dict[str, Any], Path, str, str]:
        context_hash = canonical_json_hash(self.approval_context(task_id, task, stage))
        path = self.approval_artifact_path(task_id, stage)
        if path_is_link_like(path) or not path.is_file():
            raise HarnessError(
                f"自动审批必须提供普通 JSON 审查制品 {display_path(path)}；"
                f"approval_context_sha256={context_hash}"
            )
        artifact, artifact_hash = canonical_json_file_sha256(
            path, label=f"{stage} 审查制品"
        )
        if not isinstance(artifact, dict):
            raise HarnessError(f"{display_path(path)} 顶层必须是 object")
        expected_keys = {
            "schema_version",
            "task_id",
            "stage",
            "decision",
            "actor",
            "agent_task",
            "codex_thread_id",
            "result_marker",
            "approval_context_sha256",
            "reviewed_at",
            "findings",
            "summary",
        }
        if set(artifact) != expected_keys:
            missing = sorted(expected_keys - set(artifact))
            extra = sorted(set(artifact) - expected_keys)
            raise HarnessError(
                f"{display_path(path)} 字段不符合最小 schema；missing={missing} extra={extra}"
            )
        expected_marker = "APPROVED" if status == "approved" else "REJECTED"
        exact_values = {
            "schema_version": 1,
            "task_id": task_id,
            "stage": stage,
            "decision": status,
            "actor": actor,
            "agent_task": agent_task,
            "codex_thread_id": codex_thread_id,
            "result_marker": expected_marker,
            "approval_context_sha256": context_hash,
        }
        for field, expected in exact_values.items():
            if artifact.get(field) != expected:
                raise HarnessError(
                    f"{display_path(path)}.{field} 必须等于 {expected!r}"
                )
        reviewed_at = str(artifact.get("reviewed_at", "")).strip()
        parsed_at = parse_rfc3339(reviewed_at)
        if parsed_at is None:
            raise HarnessError(f"{display_path(path)}.reviewed_at 必须是 RFC3339 时间")
        findings = artifact.get("findings")
        if (
            not isinstance(findings, list)
            or len(findings) > 100
            or any(
                not isinstance(item, str) or not item.strip() or len(item) > 2000
                for item in findings
            )
        ):
            raise HarnessError(
                f"{display_path(path)}.findings 必须是最多 100 项的非空字符串数组"
            )
        if status == "rejected" and not findings:
            raise HarnessError(f"{display_path(path)} rejected 必须至少记录一项 finding")
        summary = artifact.get("summary")
        if not isinstance(summary, str) or not 10 <= len(summary.strip()) <= 4000:
            raise HarnessError(
                f"{display_path(path)}.summary 必须是 10..4000 字符的具体结论"
            )
        return artifact, path, artifact_hash, context_hash

    def remote_execution_contract_errors(self, task: dict[str, Any]) -> list[str]:
        network_required = task.get("network_access_required") is True
        remote = task.get("remote_execution")
        if not network_required:
            if remote is not None:
                return ["network_access_required=false 时不得声明 remote_execution"]
            return []

        errors: list[str] = []
        if task.get("type") != "operations" or task.get("risk_level") != "L4":
            errors.append("远程执行只允许 type=operations 且 risk_level=L4 的任务")
        if not isinstance(remote, dict):
            return errors + ["网络任务必须声明 remote_execution 合同"]

        authorization = remote.get("authorization")
        if not isinstance(authorization, dict):
            errors.append("remote_execution.authorization 必须记录用户授权上下文")
        else:
            if authorization.get("mode") != "user_explicit":
                errors.append("remote_execution.authorization.mode 必须为 user_explicit")
            thread_id = str(authorization.get("thread_id", ""))
            if not re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                thread_id,
            ):
                errors.append("remote_execution.authorization.thread_id 必须是 Codex task UUID")
            if parse_rfc3339(str(authorization.get("authorized_at", ""))) is None:
                errors.append("remote_execution.authorization.authorized_at 必须是 RFC3339 时间")
            scope = str(authorization.get("scope", "")).strip()
            if len(scope) < 20 or len(scope) > 500:
                errors.append("remote_execution.authorization.scope 必须具体记录用户授权范围")
        if remote.get("environment") != "authorized_personal_site":
            errors.append("remote_execution.environment 必须为 authorized_personal_site")

        host = str(remote.get("host", "")).strip()
        if not re.fullmatch(
            r"(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|(?:[0-9]{1,3}\.){3}[0-9]{1,3})",
            host,
        ):
            errors.append("remote_execution.host 必须是单一主机名或 IPv4 地址")
        elif re.fullmatch(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}", host):
            try:
                ipaddress.ip_address(host)
            except ValueError:
                errors.append("remote_execution.host IPv4 地址无效")
        port = remote.get("port")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            errors.append("remote_execution.port 必须在 1..65535")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,31}", str(remote.get("user", ""))):
            errors.append("remote_execution.user 格式无效")

        fingerprint = str(remote.get("host_key_fingerprint", ""))
        if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", fingerprint):
            errors.append("remote_execution.host_key_fingerprint 必须固定 SHA256 主机指纹")
        credential_pattern = r"user-ssh-file:[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
        identity_reference = str(remote.get("identity_reference", ""))
        known_hosts_reference = str(remote.get("known_hosts_reference", ""))
        for field, value in (
            ("identity_reference", identity_reference),
            ("known_hosts_reference", known_hosts_reference),
        ):
            if not re.fullmatch(credential_pattern, value):
                errors.append(
                    f"remote_execution.{field} 只能按文件名引用用户 .ssh 中的仓库外普通文件"
                )
        if identity_reference and identity_reference == known_hosts_reference:
            errors.append("SSH identity 与 known_hosts 必须使用不同外部文件")

        def normalized_remote_path(value: Any, field: str) -> PurePosixPath | None:
            raw = str(value)
            candidate = PurePosixPath(raw)
            if (
                not raw.startswith("/")
                or raw == "/"
                or candidate.as_posix() != raw
                or ".." in candidate.parts
                or any(character in raw for character in ("\r", "\n", "\x00"))
            ):
                errors.append(f"remote_execution.{field} 必须是规范、非根目录的绝对路径")
                return None
            if candidate.as_posix() in PROTECTED_REMOTE_ROOTS:
                errors.append(f"remote_execution.{field} 范围过宽，不能是系统顶级目录")
                return None
            return candidate

        deployment_root = str(remote.get("deployment_root", ""))
        deployment_path = normalized_remote_path(deployment_root, "deployment_root")
        managed_values = remote.get("managed_roots")
        managed_paths: list[PurePosixPath] = []
        if not isinstance(managed_values, list) or not managed_values:
            errors.append("remote_execution.managed_roots 必须声明至少一个受管根")
        else:
            for index, value in enumerate(managed_values):
                path = normalized_remote_path(value, f"managed_roots[{index}]")
                if path is not None:
                    managed_paths.append(path)
            if len(set(managed_paths)) != len(managed_paths):
                errors.append("remote_execution.managed_roots 不得重复")
            for index, root in enumerate(managed_paths):
                for other in managed_paths[index + 1 :]:
                    if root in other.parents or other in root.parents:
                        errors.append("remote_execution.managed_roots 不得互相包含以隐式扩大范围")
                        break
        if deployment_path is not None and deployment_path not in managed_paths:
            errors.append("remote_execution.deployment_root 必须精确列入 managed_roots")

        def path_is_managed(value: Any, field: str) -> bool:
            candidate = normalized_remote_path(value, field)
            if candidate is None:
                return False
            return any(candidate == root or root in candidate.parents for root in managed_paths)

        actions = remote.get("allowed_actions")
        action_ids: set[str] = set()
        if not isinstance(actions, list) or not actions:
            errors.append("remote_execution.allowed_actions 必须声明结构化动作")
        else:
            for index, action in enumerate(actions):
                label = f"allowed_actions[{index}]"
                if not isinstance(action, dict):
                    errors.append(f"remote_execution.{label} 必须是 object")
                    continue
                action_id = str(action.get("id", ""))
                if not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", action_id):
                    errors.append(f"remote_execution.{label}.id 格式无效")
                elif action_id in action_ids:
                    errors.append(f"remote_execution.allowed_actions id 重复：{action_id}")
                action_ids.add(action_id)
                transport = action.get("transport")
                mode = action.get("mode")
                timeout = action.get("timeout_seconds")
                if transport not in REMOTE_TRANSPORTS:
                    errors.append(f"remote_execution.{label}.transport 无效")
                if mode not in REMOTE_ACTION_MODES:
                    errors.append(f"remote_execution.{label}.mode 无效")
                if (
                    not isinstance(timeout, int)
                    or isinstance(timeout, bool)
                    or not 1 <= timeout <= 1800
                ):
                    errors.append(f"remote_execution.{label}.timeout_seconds 必须在 1..1800")
                if transport == "ssh":
                    if not path_is_managed(action.get("cwd"), f"{label}.cwd"):
                        errors.append(f"remote_execution.{label}.cwd 不在 managed_roots")
                    argv = action.get("argv")
                    if not isinstance(argv, list) or not argv:
                        errors.append(f"remote_execution.{label}.argv 必须是非空数组")
                    elif any(
                        not isinstance(item, str)
                        or not item
                        or any(character in item for character in ("\r", "\n", "\x00"))
                        for item in argv
                    ):
                        errors.append(f"remote_execution.{label}.argv 含空值、换行或 NUL")
                    if any(key in action for key in ("direction", "source", "destination")):
                        errors.append(f"remote_execution.{label} ssh 动作不得声明 scp 字段")
                elif transport == "scp":
                    if any(key in action for key in ("cwd", "argv")):
                        errors.append(f"remote_execution.{label} scp 动作不得声明 ssh 字段")
                    direction = action.get("direction")
                    source = action.get("source")
                    destination = action.get("destination")
                    if direction not in {"upload", "download"}:
                        errors.append(f"remote_execution.{label}.direction 无效")
                    elif direction == "upload":
                        if not isinstance(source, str) or not source:
                            errors.append(f"remote_execution.{label}.source 必须是仓库内相对路径")
                        else:
                            try:
                                source_path = normalize_repo_path(source, allow_glob=False)
                            except ValueError:
                                errors.append(
                                    f"remote_execution.{label}.source 必须是仓库内相对路径"
                                )
                            else:
                                if not source_path.startswith(
                                    f".harness/runs/{task.get('id')}/"
                                ):
                                    errors.append(
                                        f"remote_execution.{label}.source 只能读取当前任务 .harness/runs/**"
                                    )
                        if not path_is_managed(destination, f"{label}.destination"):
                            errors.append(f"remote_execution.{label}.destination 不在 managed_roots")
                    else:
                        if not path_is_managed(source, f"{label}.source"):
                            errors.append(f"remote_execution.{label}.source 不在 managed_roots")
                        if not isinstance(destination, str) or not destination:
                            errors.append(f"remote_execution.{label}.destination 必须是仓库内相对路径")
                        else:
                            try:
                                destination_path = normalize_repo_path(
                                    destination, allow_glob=False
                                )
                            except ValueError:
                                errors.append(
                                    f"remote_execution.{label}.destination 必须是仓库内相对路径"
                                )
                                destination_path = ""
                            if destination_path and not destination_path.startswith(
                                f".harness/runs/{task.get('id')}/"
                            ):
                                errors.append(
                                    f"remote_execution.{label}.destination 只能写入当前任务 .harness/runs/**"
                                )

        forbidden = remote.get("forbidden_actions")
        if not isinstance(forbidden, list) or set(forbidden) != REMOTE_FORBIDDEN_ACTIONS:
            errors.append("remote_execution.forbidden_actions 必须完整声明固定拒绝能力")
        approvals = task.get("manual_approvals")
        release = approvals.get("release") if isinstance(approvals, dict) else None
        if not isinstance(release, dict) or release.get("required") is not True:
            errors.append("远程执行任务必须启用 release approval")
        rollback = task.get("rollback")
        if not isinstance(rollback, dict) or rollback.get("required") is not True:
            errors.append("远程执行任务必须声明必需回滚")
        return errors

    def task_check(
        self,
        task_id: str,
        *,
        block_open_decisions: bool = False,
        allow_stale_plan_context: bool = False,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("task-check")
        try:
            task = self.load_task(normalized)
            schema = self.task_schema()
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result

        result.errors.extend(validate_json_schema(task, schema))
        if task.get("id") != normalized:
            result.errors.append(f"task.json id 必须与目录一致：{normalized}")
        id_token = normalized.split("-")[1]
        expected_type = TASK_TYPE_BY_ID_TOKEN[id_token]
        if task.get("type") != expected_type:
            result.errors.append(
                f"任务编号 {id_token} 必须使用 type={expected_type}，当前为 {task.get('type')}"
            )

        requirement_ids = [str(item).upper() for item in task.get("requirement_ids", []) if isinstance(item, str)]
        try:
            known = self.known_requirement_ids()
        except HarnessError as exc:
            result.errors.append(str(exc))
            known = set()
        unknown = sorted(set(requirement_ids) - known)
        if unknown:
            result.errors.append(f"需求文档中不存在这些编号：{', '.join(unknown)}")

        try:
            decisions = self.decision_map()
        except HarnessError as exc:
            result.errors.append(str(exc))
            decisions = {}
        declared_decisions = {
            str(item).upper() for item in task.get("decision_ids", []) if isinstance(item, str)
        }
        unknown_decisions = sorted(declared_decisions - set(decisions))
        if unknown_decisions:
            result.errors.append(f"未知决策编号：{', '.join(unknown_decisions)}")
        applicable: set[str] = set()
        for decision_id, decision in decisions.items():
            affected = {
                str(item).upper()
                for item in decision.get("affected_requirement_ids", [])
                if isinstance(item, str)
            }
            if set(requirement_ids) & affected:
                applicable.add(decision_id)
        missing_decisions = sorted(applicable - declared_decisions)
        if missing_decisions:
            result.errors.append(f"任务未登记受影响决策：{', '.join(missing_decisions)}")
        for decision_id in sorted(applicable | declared_decisions):
            decision = decisions.get(decision_id)
            if not decision:
                continue
            status = str(decision.get("status", "")).lower()
            if status == "open":
                message = f"开放决策 {decision_id} 尚未解决，阻止进入实现"
                if block_open_decisions:
                    result.errors.append(message)
                else:
                    result.warnings.append(message + "；当前仅允许分析和计划")
            elif status != "resolved":
                result.errors.append(f"决策 {decision_id} 状态无效或未完成：{status or '<empty>'}")
            elif not all(decision.get(field) for field in ("resolution", "approved_by", "approved_at")):
                result.errors.append(f"已解决决策 {decision_id} 缺少 resolution/approved_by/approved_at")

        all_patterns: list[tuple[str, str]] = []
        for field in ("allowed_paths", "forbidden_paths"):
            values = task.get(field, [])
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, str):
                    continue
                try:
                    normalized_pattern = normalize_repo_path(value, allow_glob=True)
                except ValueError as exc:
                    result.errors.append(f"{field} 路径无效 {value!r}：{exc}")
                else:
                    all_patterns.append((field, normalized_pattern))
        allowed = {value for field, value in all_patterns if field == "allowed_paths"}
        forbidden = {value for field, value in all_patterns if field == "forbidden_paths"}
        duplicates = sorted(allowed & forbidden)
        if duplicates:
            result.errors.append(f"路径同时出现在 allowed_paths 与 forbidden_paths：{', '.join(duplicates)}")
        task_type = str(task.get("type", "")).casefold()
        if task_type != "harness":
            unsafe_allowed = sorted(
                pattern for pattern in allowed if pattern_targets_harness_policy(pattern)
            )
            if unsafe_allowed:
                result.errors.append(
                    "非 NUR-HARNESS 任务不得把 Harness 策略/执行面加入 allowed_paths："
                    + ", ".join(unsafe_allowed)
                )
        else:
            bootstrap_namespaces = [
                normalize_repo_path(str(item), allow_glob=True)
                for item in self.config.get("paths", {}).get("bootstrap_allowed", [])
            ]
            outside_bootstrap = sorted(
                pattern
                for pattern in allowed
                if not pattern_within_namespaces(pattern, bootstrap_namespaces)
            )
            if outside_bootstrap:
                result.errors.append(
                    "NUR-HARNESS 任务的 allowed_paths 必须限制在 bootstrap_allowed："
                    + ", ".join(outside_bootstrap)
                )

        placeholders = []
        for field in ("title", "business_goal", "owner"):
            value = task.get(field)
            if isinstance(value, str) and any(marker.casefold() in value.casefold() for marker in PLACEHOLDER_MARKERS):
                placeholders.append(field)
        for field in ("in_scope", "out_of_scope", "business_invariants"):
            values = task.get(field, [])
            if isinstance(values, list) and any(
                isinstance(value, str)
                and any(marker.casefold() in value.casefold() for marker in PLACEHOLDER_MARKERS)
                for value in values
            ):
                placeholders.append(field)
        if placeholders:
            result.errors.append(f"任务合同仍含模板占位内容：{', '.join(sorted(set(placeholders)))}")

        criteria = task.get("acceptance_criteria", [])
        criterion_ids: set[str] = set()
        mapped_requirements: set[str] = set()
        if isinstance(criteria, list):
            for index, criterion in enumerate(criteria):
                if not isinstance(criterion, dict):
                    continue
                criterion_id = str(criterion.get("id", ""))
                if criterion_id in criterion_ids:
                    result.errors.append(f"acceptance_criteria id 重复：{criterion_id}")
                criterion_ids.add(criterion_id)
                mapped_requirements.update(
                    str(item).upper()
                    for item in criterion.get("requirement_ids", [])
                    if isinstance(item, str)
                )
                description = str(criterion.get("description", ""))
                if any(marker.casefold() in description.casefold() for marker in PLACEHOLDER_MARKERS):
                    result.errors.append(f"acceptance_criteria[{index}] 仍含占位内容")
        missing_mapping = sorted(set(requirement_ids) - mapped_requirements)
        if missing_mapping:
            result.errors.append(f"验收标准未映射全部需求：{', '.join(missing_mapping)}")
        unknown_criterion_requirements = sorted(mapped_requirements - known)
        if unknown_criterion_requirements:
            result.errors.append(
                "验收标准引用需求文档外编号："
                + ", ".join(unknown_criterion_requirements)
            )
        external_criterion_requirements = sorted(
            mapped_requirements - set(requirement_ids)
        )
        if external_criterion_requirements:
            result.errors.append(
                "验收标准不得引入任务合同 requirement_ids 之外的编号："
                + ", ".join(external_criterion_requirements)
            )

        tests = task.get("required_tests", [])
        test_ids: set[str] = set()
        if isinstance(tests, list):
            for index, test in enumerate(tests):
                if not isinstance(test, dict):
                    continue
                test_id = str(test.get("id", ""))
                if test_id in test_ids:
                    result.errors.append(f"required_tests id 重复：{test_id}")
                test_ids.add(test_id)
                if test_id == "replace_me":
                    result.errors.append("required_tests 仍包含 replace_me 占位测试")
                description = str(test.get("description", ""))
                if any(marker.casefold() in description.casefold() for marker in PLACEHOLDER_MARKERS):
                    result.errors.append(f"required_tests[{index}].description 仍含占位内容")
                command = test.get("command")
                if isinstance(command, list) and command:
                    command_strings = [str(item) for item in command]
                    executable_name = Path(command_strings[0]).name.casefold()
                    if executable_name in SHELL_EXECUTABLES:
                        result.errors.append(
                            f"required_tests[{index}] 禁止使用 shell 解释器：{command_strings[0]}"
                        )
                    joined = " ".join(command_strings)
                    if any(pattern.search(joined) for pattern in DANGEROUS_COMMAND_PATTERNS):
                        result.errors.append(f"required_tests[{index}] 包含禁止的破坏性命令")
                    if any("\x00" in item or "\r" in item or "\n" in item for item in command_strings):
                        result.errors.append(f"required_tests[{index}] argv 不得包含换行或 NUL")
                    for policy_error in test_command_policy_errors(command_strings):
                        result.errors.append(f"required_tests[{index}] {policy_error}")
                cwd = test.get("cwd")
                if isinstance(cwd, str):
                    try:
                        resolve_repo_path(self.root, cwd)
                    except ValueError as exc:
                        result.errors.append(f"required_tests[{index}].cwd 无效：{exc}")

        risk = str(task.get("risk_level", ""))
        approvals = task.get("manual_approvals", {})
        if isinstance(approvals, dict):
            for name in ("plan", "merge", "release"):
                self.check_approval_object(name, approvals.get(name), result)
            if not isinstance(approvals.get("merge"), dict) or approvals["merge"].get("required") is not True:
                result.errors.append("所有任务都必须声明 manual_approvals.merge.required=true")
        self.check_codex_role_bindings(task, approvals, result)
        independent_risks = {
            str(item)
            for item in self.config.get("workflow", {}).get("independent_review_risks", [])
        }
        if risk in independent_risks:
            if not isinstance(approvals, dict) or approvals.get("plan", {}).get("required") is not True:
                result.errors.append(f"{risk} 必须声明独立计划审批")
            if not isinstance(approvals, dict) or approvals.get("merge", {}).get("required") is not True:
                result.errors.append(f"{risk} 必须声明独立合并审批")
        if risk == "L4":
            if not isinstance(approvals, dict) or approvals.get("release", {}).get("required") is not True:
                result.errors.append("L4 必须声明独立发布审批")

        high_risk_requirement = any(
            requirement.startswith(("NFR-SEC-", "FR-DASH-", "METRIC-", "DATA-"))
            or requirement in {"FR-USER-005", "FR-FAV-003", "FR-FAV-005"}
            or requirement.startswith("FR-INQ-")
            or requirement.startswith("FR-ADMIN-INQ-")
            for requirement in requirement_ids
        )
        db_change = task.get("database_change", {})
        core_change = task.get("shopxo_core_change", {})
        if high_risk_requirement and RISK_ORDER.get(risk, -1) < RISK_ORDER["L3"]:
            result.errors.append("权限、询价、统计或数据口径任务风险等级不得低于 L3")
        l4_requirements = sorted(set(requirement_ids) & L4_REQUIREMENT_IDS)
        if l4_requirements and RISK_ORDER.get(risk, -1) < RISK_ORDER["L4"]:
            result.errors.append(
                "注册/登录认证基础任务风险等级必须为 L4："
                + ", ".join(l4_requirements)
            )
        if isinstance(db_change, dict) and db_change.get("required"):
            if RISK_ORDER.get(risk, -1) < RISK_ORDER["L3"]:
                result.errors.append("数据库变更风险等级不得低于 L3")
            if not db_change.get("affected_tables"):
                result.errors.append("数据库变更缺少 affected_tables")
            if not db_change.get("migration_paths"):
                result.errors.append("数据库变更缺少 migration_paths")
            migration_paths: list[str] = []
            for migration_path in db_change.get("migration_paths", []):
                try:
                    normalized_migration = normalize_repo_path(
                        str(migration_path), allow_glob=True
                    )
                except ValueError as exc:
                    result.errors.append(
                        f"数据库 migration_paths 路径无效 {migration_path!r}：{exc}"
                    )
                else:
                    migration_paths.append(normalized_migration)
            baseline_only = bool(migration_paths) and all(
                pattern.casefold() == "config/shopxo.sql"
                for pattern in migration_paths
            )
            baseline_exception = db_change.get(
                "fresh_install_baseline_exception", {}
            )
            exception_requested = bool(
                isinstance(baseline_exception, dict)
                and baseline_exception.get("requested") is True
            )
            exception_reason = (
                str(baseline_exception.get("reason", "")).strip()
                if isinstance(baseline_exception, dict)
                else ""
            )
            if baseline_only and not exception_requested:
                result.errors.append(
                    "config/shopxo.sql 是全量安装基线，不能作为唯一 forward migration；"
                    "请增加版本化增量迁移，或显式申请 fresh_install_baseline_exception"
                )
            if exception_requested:
                if not baseline_only:
                    result.errors.append(
                        "fresh_install_baseline_exception 仅适用于 config/shopxo.sql 是唯一迁移路径的任务"
                    )
                if len(exception_reason) < 20 or any(
                    marker.casefold() in exception_reason.casefold()
                    for marker in PLACEHOLDER_MARKERS
                ):
                    result.errors.append(
                        "fresh_install_baseline_exception.reason 必须给出至少 20 字符的具体理由"
                    )
                if RISK_ORDER.get(risk, -1) < RISK_ORDER["L4"]:
                    result.errors.append("fresh-install 数据库基线例外风险等级必须为 L4")
            if not str(db_change.get("rollback_plan", "")).strip():
                result.errors.append("数据库变更缺少 rollback_plan")
            if not str(db_change.get("verification", "")).strip():
                result.errors.append("数据库变更缺少 verification")
        if isinstance(core_change, dict) and core_change.get("required"):
            if RISK_ORDER.get(risk, -1) < RISK_ORDER["L3"]:
                result.errors.append("ShopXO 核心修改风险等级不得低于 L3")
            if not core_change.get("paths"):
                result.errors.append("核心修改声明缺少 paths")
            for core_path in core_change.get("paths", []):
                try:
                    normalize_repo_path(str(core_path), allow_glob=True)
                except ValueError as exc:
                    result.errors.append(
                        f"核心修改声明路径无效 {core_path!r}：{exc}"
                    )
            if not str(core_change.get("reason", "")).strip():
                result.errors.append("核心修改声明缺少不可使用插件/钩子的具体 reason")
            registration = str(core_change.get("registration", ""))
            if ".harness/core-changes/REGISTER.md" not in registration:
                result.errors.append("核心修改必须引用 .harness/core-changes/REGISTER.md 登记")

        rollback = task.get("rollback", {})
        if isinstance(rollback, dict) and rollback.get("required"):
            if not str(rollback.get("plan", "")).strip() or any(
                marker.casefold() in str(rollback.get("plan", "")).casefold()
                for marker in PLACEHOLDER_MARKERS
            ):
                result.errors.append("必需回滚任务缺少可执行 rollback.plan")
            if not str(rollback.get("verification", "")).strip() or any(
                marker.casefold() in str(rollback.get("verification", "")).casefold()
                for marker in PLACEHOLDER_MARKERS
            ):
                result.errors.append("必需回滚任务缺少 rollback.verification")

        result.errors.extend(self.remote_execution_contract_errors(task))

        owner = str(task.get("owner", "")).strip()
        reviewer = str(task.get("reviewer", "")).strip()
        release_approver = str(task.get("release_approver") or "").strip()
        merge_required = bool(
            isinstance(approvals, dict)
            and isinstance(approvals.get("merge"), dict)
            and approvals["merge"].get("required")
        )
        if risk in independent_risks or merge_required or (
            isinstance(db_change, dict) and db_change.get("required")
        ) or (isinstance(core_change, dict) and core_change.get("required")):
            if not reviewer:
                result.errors.append("需独立合并审批的任务必须指定 reviewer 角色")
            elif owner.casefold() == reviewer.casefold():
                result.errors.append("任务 owner 与独立 reviewer 必须不同")

        release_required = bool(
            isinstance(approvals, dict)
            and isinstance(approvals.get("release"), dict)
            and approvals["release"].get("required") is True
        )
        if release_required:
            if not release_approver:
                result.errors.append("需独立发布审批的任务必须指定 release_approver 角色")
            elif release_approver.casefold() in {owner.casefold(), reviewer.casefold()}:
                result.errors.append("release_approver 必须与 owner、reviewer 均不同")
        elif release_approver:
            result.warnings.append("release 审批未启用，但 task.json 已预留 release_approver")

        if isinstance(approvals, dict):
            for stage in ("plan", "merge", "release"):
                approval = approvals.get(stage)
                if not isinstance(approval, dict) or approval.get("status") != "approved":
                    continue
                expected_actor = self.expected_approval_actor(task, stage)
                approved_by = str(approval.get("approved_by") or "").strip()
                if not expected_actor or approved_by.casefold() != expected_actor.casefold():
                    result.errors.append(
                        f"manual_approvals.{stage}.approved_by 必须与合同中的阶段审批人一致"
                    )

        history_gate = self.workflow_history_check(
            normalized,
            task,
            allow_stale_plan_context=allow_stale_plan_context,
        )
        result.errors.extend(history_gate.errors)
        result.warnings.extend(history_gate.warnings)

        result.data.update(
            {
                "task_id": normalized,
                "contract_sha256": immutable_contract_hash(task),
                "policy_sha256": policy_contract_hash(task),
                "requirement_count": len(requirement_ids),
                "test_count": len(tests) if isinstance(tests, list) else 0,
                "summary": f"需求 {len(requirement_ids)} 项，测试 {len(tests) if isinstance(tests, list) else 0} 项",
            }
        )
        return result

    def render_template(self, name: str, replacements: dict[str, str]) -> str:
        path = self.harness_dir / "templates" / name
        if not path.is_file():
            raise HarnessError(f"缺少任务模板：{display_path(path)}")
        ensure_repo_path_safe(self.root, path, label=f"任务模板 {name}")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HarnessError(f"无法读取任务模板 {name}：{exc}") from exc
        for key, value in replacements.items():
            text = text.replace("{{" + key + "}}", value)
        unresolved = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", text)))
        if unresolved:
            raise HarnessError(f"模板 {name} 仍有未替换变量：{', '.join(unresolved)}")
        return text

    def task_create(
        self,
        task_id: str,
        *,
        title: str,
        risk: str,
        priority: str,
        phase: int,
        requirements: Sequence[str],
        task_type: str | None,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("task-create")
        directory = self.task_dir(normalized)
        if directory.exists():
            result.errors.append(f"任务目录已存在，拒绝覆盖：{display_path(directory)}")
            return result
        requirement_ids = [item.strip().upper() for item in requirements if item.strip()]
        if not requirement_ids:
            result.errors.append("task-create 至少需要一个 --requirement")
            return result
        try:
            known = self.known_requirement_ids()
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result
        unknown = sorted(set(requirement_ids) - known)
        if unknown:
            result.errors.append(f"需求文档中不存在这些编号：{', '.join(unknown)}")
            return result
        if len(requirement_ids) != len(set(requirement_ids)):
            result.errors.append("--requirement 不得重复")
            return result

        token = normalized.split("-")[1]
        selected_type = task_type or TASK_TYPE_BY_ID_TOKEN[token]
        if selected_type != TASK_TYPE_BY_ID_TOKEN[token]:
            result.errors.append(
                f"任务编号 {token} 只能创建 type={TASK_TYPE_BY_ID_TOKEN[token]}，不能使用 {selected_type}"
            )
            return result
        created = utc_now()
        decision_ids = self.related_decision_ids(requirement_ids)
        independent_risks = {
            str(item)
            for item in self.config.get("workflow", {}).get("independent_review_risks", [])
        }
        plan_required = risk in independent_risks
        release_required = risk == "L4"
        replacements = {
            "TASK_ID": normalized,
            "TITLE": title.strip() or "待填写任务标题",
            "TYPE": selected_type,
            "PRIORITY": priority,
            "PHASE": str(phase),
            "RISK_LEVEL": risk,
            "REQUIREMENT_IDS": json.dumps(requirement_ids, ensure_ascii=False),
            "DECISION_IDS": json.dumps(decision_ids, ensure_ascii=False),
            "ROLLBACK_REQUIRED": "true" if risk in ("L2", "L3", "L4") else "false",
            "PLAN_APPROVAL_REQUIRED": "true" if plan_required else "false",
            "PLAN_APPROVAL_STATUS": "pending" if plan_required else "not_required",
            "RELEASE_APPROVAL_REQUIRED": "true" if release_required else "false",
            "RELEASE_APPROVAL_STATUS": "pending" if release_required else "not_required",
            "CREATED_AT": created,
            "REQUIREMENT_LIST": "\n".join(f"- `{item}`" for item in requirement_ids),
            "DECISION_LIST": (
                "\n".join(f"- `{item}`（状态以 requirements-decisions.json 为准）" for item in decision_ids)
                if decision_ids
                else "- 无已识别决策；仍需人工核对需求冲突。"
            ),
        }
        template_names = (
            "task.json",
            "requirement.md",
            "impact-analysis.md",
            "implementation-plan.md",
            "test-plan.md",
            "evidence.md",
            "review.md",
            "release-note.md",
        )
        rendered: dict[str, str] = {}
        try:
            task_value = read_json(self.harness_dir / "templates" / "task.json")
            if not isinstance(task_value, dict):
                raise HarnessError("任务 JSON 模板顶层必须是 object")
            criteria = task_value.get("acceptance_criteria")
            rollback = task_value.get("rollback")
            approvals = task_value.get("manual_approvals")
            if not isinstance(criteria, list) or not criteria or not isinstance(criteria[0], dict):
                raise HarnessError("任务 JSON 模板缺少 acceptance_criteria[0]")
            if not isinstance(rollback, dict):
                raise HarnessError("任务 JSON 模板缺少 rollback object")
            if not isinstance(approvals, dict) or not all(
                isinstance(approvals.get(name), dict) for name in ("plan", "merge", "release")
            ):
                raise HarnessError("任务 JSON 模板缺少 manual_approvals plan/merge/release")

            task_value.update(
                {
                    "id": normalized,
                    "title": title.strip() or "待填写任务标题",
                    "type": selected_type,
                    "priority": priority,
                    "phase": phase,
                    "risk_level": risk,
                    "requirement_ids": requirement_ids,
                    "decision_ids": decision_ids,
                    "created_at": created,
                    "updated_at": created,
                }
            )
            criteria[0]["requirement_ids"] = requirement_ids
            rollback["required"] = risk in ("L2", "L3", "L4")
            approvals["plan"].update(
                {"required": plan_required, "status": "pending" if plan_required else "not_required"}
            )
            approvals["release"].update(
                {"required": release_required, "status": "pending" if release_required else "not_required"}
            )
            rendered["task.json"] = json.dumps(task_value, ensure_ascii=False, indent=2)
            for name in template_names[1:]:
                rendered[name] = self.render_template(name, replacements)
            json_loads_strict(rendered["task.json"], source="rendered task template")
            directory.mkdir(parents=True, exist_ok=False)
            for name, text_value in rendered.items():
                atomic_write_text(directory / name, text_value if text_value.endswith("\n") else text_value + "\n")
        except Exception as exc:
            if directory.exists():
                # The directory did not exist before this method. Remove only files
                # created from the fixed template list, then the empty directory.
                for name in template_names:
                    try:
                        (directory / name).unlink(missing_ok=True)
                    except OSError:
                        pass
                try:
                    directory.rmdir()
                except OSError:
                    pass
            result.errors.append(str(exc))
            return result

        result.data.update(
            {
                "task_id": normalized,
                "path": display_path(directory),
                "related_decisions": decision_ids,
                "summary": "任务草稿已创建；补全合同与计划后再运行 task-check。",
            }
        )
        if decision_ids:
            result.warnings.append(
                "任务命中需求决策；open 决策允许分析/计划，但会阻止批准实现和后续门禁。"
            )
        return result

    def workflow_status_gate(
        self,
        task: dict[str, Any],
        config_key: str,
        gate_name: str,
    ) -> GateResult:
        result = GateResult(gate_name)
        allowed = self.config.get("workflow", {}).get(config_key, [])
        allowed_statuses = {str(item) for item in allowed} if isinstance(allowed, list) else set()
        status = str(task.get("status", ""))
        if not allowed_statuses:
            result.errors.append(f"Harness 配置缺少 workflow.{config_key}")
        elif status not in allowed_statuses:
            result.errors.append(
                f"任务状态 {status or '<empty>'} 不允许 {gate_name}；允许：{', '.join(sorted(allowed_statuses))}"
            )
        return result

    def workflow_history_value(self, task_id: str) -> dict[str, Any]:
        normalized = self.validate_task_id(task_id)
        with self.workflow_lock(normalized):
            self._recover_workflow_transaction_locked(normalized)
            path = self.task_dir(normalized) / "workflow-history.json"
            if path.is_file():
                value = read_json(path)
                if (
                    not isinstance(value, dict)
                    or value.get("schema_version") != 1
                    or value.get("task_id") != normalized
                    or not isinstance(value.get("events"), list)
                ):
                    raise HarnessError(f"工作流历史无效：{display_path(path)}")
            else:
                value = {"schema_version": 1, "task_id": normalized, "events": []}
            return value

    def workflow_history_check(
        self,
        task_id: str,
        task: dict[str, Any],
        *,
        allow_stale_plan_context: bool = False,
    ) -> GateResult:
        result = GateResult("workflow-history")
        path = self.task_dir(task_id) / "workflow-history.json"
        try:
            history = self.workflow_history_value(task_id)
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result
        events = history.get("events", [])
        approvals = task.get("manual_approvals", {})
        approval_values = approvals if isinstance(approvals, dict) else {}
        has_recorded_approval = any(
            isinstance(approval_values.get(stage), dict)
            and approval_values[stage].get("status") in {"approved", "rejected"}
            for stage in ("plan", "merge", "release")
        )
        if not path.is_file():
            if task.get("status") != "draft" or has_recorded_approval:
                result.errors.append("非 draft 状态或已决审批缺少 workflow-history.json")
            return result

        try:
            transitions = self.status_transitions()
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result
        derived_status = "draft"
        latest_approvals: dict[str, dict[str, Any]] = {}
        implementation_started = False
        approval_statuses = {
            "plan": {"awaiting_plan_approval"},
            "merge": {"awaiting_review"},
            "release": {"awaiting_review", "approved_for_merge"},
        }
        previous_at: dt.datetime | None = None
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                result.errors.append(f"workflow-history events[{index}] 必须是 object")
                continue
            event_type = event.get("type")
            actor = str(event.get("by", "")).strip()
            occurred_at = str(event.get("at", "")).strip()
            if not actor or not occurred_at:
                result.errors.append(f"workflow-history events[{index}] 缺少 by/at")
            parsed_at = parse_rfc3339(occurred_at) if occurred_at else None
            if occurred_at and parsed_at is None:
                result.errors.append(f"workflow-history events[{index}] at 不是带时区的 RFC3339 时间")
            elif parsed_at is not None:
                if previous_at is not None and parsed_at < previous_at:
                    result.errors.append(f"workflow-history events[{index}] 时间早于前一事件")
                previous_at = parsed_at
            if event_type == "transition":
                source = str(event.get("from", ""))
                target = str(event.get("to", ""))
                if source != derived_status:
                    result.errors.append(
                        f"workflow-history events[{index}] from={source}，期望 {derived_status}"
                    )
                allowed = transitions.get(derived_status, ())
                if target not in allowed:
                    result.errors.append(
                        f"workflow-history events[{index}] 非法迁移 {derived_status} -> {target}"
                    )
                if target in {"blocked", "cancelled", "closed"} and not str(
                    event.get("reason", "")
                ).strip():
                    result.errors.append(f"workflow-history events[{index}] {target} 缺少 reason")
                if target == "approved_for_implementation":
                    plan = approval_values.get("plan")
                    if isinstance(plan, dict) and plan.get("required") is True:
                        latest_plan = latest_approvals.get("plan")
                        if not isinstance(latest_plan, dict) or latest_plan.get("status") != "approved":
                            result.errors.append(
                                f"workflow-history events[{index}] 进入 approved_for_implementation 前缺少已批准 plan 事件"
                            )
                if target == "approved_for_merge":
                    latest_merge = latest_approvals.get("merge")
                    if not isinstance(latest_merge, dict) or latest_merge.get("status") != "approved":
                        result.errors.append(
                            f"workflow-history events[{index}] 进入 approved_for_merge 前缺少已批准 merge 事件"
                        )
                    release = approval_values.get("release")
                    if isinstance(release, dict) and release.get("required") is True:
                        latest_release = latest_approvals.get("release")
                        if (
                            not isinstance(latest_release, dict)
                            or latest_release.get("status") != "approved"
                        ):
                            result.errors.append(
                                f"workflow-history events[{index}] 进入 approved_for_merge 前缺少已批准 release 事件"
                            )
                if target == "implementing":
                    implementation_started = True
                derived_status = target
                for stage in self.approval_resets_for_transition(target):
                    latest_approvals.pop(stage, None)
            elif event_type == "approval":
                stage = str(event.get("stage", ""))
                approval_status = str(event.get("status", ""))
                if stage not in approval_statuses:
                    result.errors.append(f"workflow-history events[{index}] approval stage 无效")
                    continue
                if derived_status not in approval_statuses[stage]:
                    result.errors.append(
                        f"workflow-history events[{index}] 状态 {derived_status} 不允许 {stage} 审批"
                    )
                if approval_status not in {"approved", "rejected"}:
                    result.errors.append(f"workflow-history events[{index}] approval status 无效")
                if approval_status == "rejected" and not str(event.get("reason", "")).strip():
                    result.errors.append(f"workflow-history events[{index}] rejected 缺少 reason")
                approval = approval_values.get(stage)
                if not isinstance(approval, dict) or approval.get("required") is not True:
                    result.errors.append(
                        f"workflow-history events[{index}] 为未声明 required 的 {stage} 记录审批"
                    )
                recorded_expected_actor = str(event.get("expected_actor", "")).strip()
                if recorded_expected_actor and actor.casefold() != recorded_expected_actor.casefold():
                    result.errors.append(
                        f"workflow-history events[{index}] {stage} 审批人不符合事件锁定角色"
                    )
                latest_approvals[stage] = event
            else:
                result.errors.append(f"workflow-history events[{index}] type 无效：{event_type}")

        if derived_status != task.get("status"):
            result.errors.append(
                f"workflow-history 派生状态 {derived_status} 与 task.json.status={task.get('status')} 不一致"
            )
        workflow = self.config.get("workflow", {})
        latest_plan_event = latest_approvals.get("plan")
        post_implementation_plan_artifact_warning = bool(
            implementation_started
            and isinstance(latest_plan_event, dict)
            and latest_plan_event.get("status") == "approved"
            and isinstance(workflow, dict)
            and workflow.get("post_implementation_plan_changes")
            == POST_IMPLEMENTATION_PLAN_CHANGE_MODE
        )
        plan_artifact_drift = False
        if (
            isinstance(latest_plan_event, dict)
            and latest_plan_event.get("status") == "approved"
        ):
            def plan_context_problem(
                message: str,
                *,
                allow_post_implementation_plan_artifact_drift: bool = False,
            ) -> None:
                if allow_stale_plan_context or (
                    allow_post_implementation_plan_artifact_drift
                    and post_implementation_plan_artifact_warning
                ):
                    suffix = (
                        "；任务已开始实现，更新后的计划制品必须由 merge 审查重新核验"
                        if allow_post_implementation_plan_artifact_drift
                        and post_implementation_plan_artifact_warning
                        else "；当前仅允许退回计划阶段或重新记录 plan 审批"
                    )
                    result.warnings.append(
                        message + suffix
                    )
                else:
                    result.errors.append(message)

            recorded_plan_hash = latest_plan_event.get("plan_artifacts_sha256")
            if not isinstance(recorded_plan_hash, str) or not re.fullmatch(
                r"[0-9a-f]{64}", recorded_plan_hash
            ):
                plan_context_problem("最新 plan 批准事件缺少有效 plan_artifacts_sha256")
            else:
                try:
                    current_plan_hash = self.plan_artifacts_sha256(task_id)
                except HarnessError as exc:
                    plan_context_problem(str(exc))
                else:
                    if recorded_plan_hash != current_plan_hash:
                        plan_artifact_drift = True
                        plan_context_problem(
                            "计划制品在 plan 批准后发生变化，旧审批已失效",
                            allow_post_implementation_plan_artifact_drift=True,
                        )
            recorded_decision_hash = latest_plan_event.get("decision_context_sha256")
            if not isinstance(recorded_decision_hash, str) or not re.fullmatch(
                r"[0-9a-f]{64}", recorded_decision_hash
            ):
                plan_context_problem("最新 plan 批准事件缺少有效 decision_context_sha256")
            else:
                try:
                    current_decision_hash = self.decision_context_sha256(task)
                except HarnessError as exc:
                    plan_context_problem(str(exc))
                else:
                    if recorded_decision_hash != current_decision_hash:
                        plan_context_problem("关联需求决策在 plan 批准后发生变化，旧审批已失效")
            for field, current_hash, description in (
                (
                    "contract_sha256",
                    plan_review_contract_hash(task),
                    "任务授权合同",
                ),
                (
                    "policy_sha256",
                    plan_review_policy_hash(task),
                    "任务执行策略",
                ),
            ):
                recorded_hash = latest_plan_event.get(field)
                if not isinstance(recorded_hash, str) or not re.fullmatch(
                    r"[0-9a-f]{64}", recorded_hash
                ):
                    plan_context_problem(f"最新 plan 批准事件缺少有效 {field}")
                elif recorded_hash != current_hash:
                    plan_context_problem(f"{description}在 plan 批准后发生变化，旧审批已失效")
        for stage in ("plan", "merge", "release"):
            approval = approval_values.get(stage)
            if not isinstance(approval, dict):
                continue
            latest = latest_approvals.get(stage)
            current_status = approval.get("status")
            if latest is None:
                if current_status in {"approved", "rejected"}:
                    result.errors.append(f"manual_approvals.{stage} 缺少对应历史事件")
                continue
            expected_actor = self.expected_approval_actor(task, stage)
            latest_actor = str(latest.get("by", "")).strip()
            if not expected_actor or latest_actor.casefold() != expected_actor.casefold():
                result.errors.append(
                    f"manual_approvals.{stage} 最新审批人不符合当前任务合同"
                )
            binding = self.codex_role_binding(task, stage)
            if isinstance(binding, dict):
                def approval_binding_problem(
                    message: str,
                    *,
                    plan_artifact_context_only: bool = False,
                ) -> None:
                    if stage == "plan" and (
                        allow_stale_plan_context
                        or (
                            plan_artifact_context_only
                            and plan_artifact_drift
                            and post_implementation_plan_artifact_warning
                        )
                    ):
                        suffix = (
                            "；任务已开始实现，更新后的计划制品必须由 merge 审查重新核验"
                            if plan_artifact_context_only
                            and plan_artifact_drift
                            and post_implementation_plan_artifact_warning
                            else "；当前仅允许重新记录 plan 审批"
                        )
                        result.warnings.append(
                            message + suffix
                        )
                    else:
                        result.errors.append(message)

                expected_agent_task = str(binding.get("agent_task", "")).strip()
                observed_agent_task = str(
                    latest.get("observed_agent_task", "")
                ).strip()
                observed_thread = str(
                    latest.get("observed_codex_thread_id", "")
                ).strip()
                implementation = self.codex_role_binding(task, "implementation")
                implementation_thread = (
                    str(implementation.get("thread_id", "")).strip()
                    if isinstance(implementation, dict)
                    else ""
                )
                if latest.get("expected_agent_task") != expected_agent_task:
                    approval_binding_problem(
                        f"workflow-history 最新 {stage} 事件 expected_agent_task 与绑定不一致"
                    )
                if observed_agent_task != expected_agent_task:
                    approval_binding_problem(
                        f"workflow-history 最新 {stage} 事件 observed_agent_task 与绑定不一致"
                    )
                if not CODEX_THREAD_ID_RE.fullmatch(observed_thread):
                    approval_binding_problem(
                        f"workflow-history 最新 {stage} 事件缺少有效 observed_codex_thread_id"
                    )
                elif observed_thread == implementation_thread:
                    approval_binding_problem(
                        f"workflow-history 最新 {stage} 审批 thread 与 implementation 相同"
                    )
                expected_path = display_path(self.approval_artifact_path(task_id, stage))
                if latest.get("review_artifact_path") != expected_path:
                    approval_binding_problem(
                        f"workflow-history 最新 {stage} 事件 review_artifact_path 无效"
                    )
                try:
                    artifact, artifact_path, artifact_hash, context_hash = (
                        self.validate_approval_artifact(
                            task_id,
                            task,
                            stage=stage,
                            status=str(latest.get("status", "")),
                            actor=latest_actor,
                            agent_task=observed_agent_task,
                            codex_thread_id=observed_thread,
                        )
                    )
                except (HarnessError, OSError, UnicodeError) as exc:
                    plan_context_mismatch_only = bool(
                        stage == "plan"
                        and ".approval_context_sha256 必须等于" in str(exc)
                    )
                    if plan_context_mismatch_only:
                        try:
                            stale_artifact, stale_artifact_hash = (
                                canonical_json_file_sha256(
                                    self.approval_artifact_path(task_id, stage),
                                    label=f"{stage} 审查制品",
                                )
                            )
                        except (HarnessError, OSError, UnicodeError):
                            plan_context_mismatch_only = False
                        else:
                            plan_context_mismatch_only = bool(
                                isinstance(stale_artifact, dict)
                                and stale_artifact_hash
                                == latest.get("review_artifact_sha256")
                                and stale_artifact.get("approval_context_sha256")
                                == latest.get("approval_context_sha256")
                            )
                    approval_binding_problem(
                        f"workflow-history 最新 {stage} 审查制品失效：{exc}",
                        plan_artifact_context_only=plan_context_mismatch_only,
                    )
                else:
                    if latest.get("review_artifact_path") != display_path(artifact_path):
                        approval_binding_problem(
                            f"workflow-history 最新 {stage} 事件制品路径与实际路径不一致"
                        )
                    if latest.get("review_artifact_sha256") != artifact_hash:
                        approval_binding_problem(
                            f"workflow-history 最新 {stage} 事件制品 canonical SHA 已失效"
                        )
                    if latest.get("approval_context_sha256") != context_hash:
                        approval_binding_problem(
                            f"workflow-history 最新 {stage} 事件 approval context 已失效"
                        )
                    if latest.get("reviewed_at") != artifact.get("reviewed_at"):
                        approval_binding_problem(
                            f"workflow-history 最新 {stage} 事件 reviewed_at 与制品不一致"
                        )
            if current_status != latest.get("status"):
                result.errors.append(f"manual_approvals.{stage} 与最新历史事件状态不一致")
            if current_status == "approved":
                if approval.get("approved_by") != latest.get("by"):
                    result.errors.append(f"manual_approvals.{stage}.approved_by 与历史不一致")
                if approval.get("approved_at") != latest.get("at"):
                    result.errors.append(f"manual_approvals.{stage}.approved_at 与历史不一致")
            elif approval.get("approved_by") is not None or approval.get("approved_at") is not None:
                result.errors.append(f"manual_approvals.{stage} rejected 时身份/时间必须仅保留在历史中")
        return result

    def write_task_workflow_update(
        self,
        task_id: str,
        task: dict[str, Any],
        event: dict[str, Any],
    ) -> str | None:
        normalized = self.validate_task_id(task_id)
        with self.workflow_lock(normalized):
            return self._write_task_workflow_update_locked(normalized, task, event)

    def _write_task_workflow_update_locked(
        self,
        task_id: str,
        task: dict[str, Any],
        event: dict[str, Any],
    ) -> str | None:
        normalized = self.validate_task_id(task_id)
        self.recover_workflow_transaction(normalized)
        task_path = self.task_path(normalized)
        history_path = self.task_dir(normalized) / "workflow-history.json"
        try:
            original_task = task_path.read_text(encoding="utf-8")
            original_history = history_path.read_text(encoding="utf-8") if history_path.is_file() else None
        except OSError as exc:
            raise HarnessError(f"无法读取任务/历史原值：{exc}") from exc
        history = self.workflow_history_value(normalized)
        history["events"].append(event)
        journal_path = self.workflow_transaction_path(normalized)
        journal = {
            "schema_version": 1,
            "task_id": normalized,
            "prepared_at": utc_now(),
            "original_task": original_task,
            "original_history": original_history,
            "new_task": task,
            "new_history": history,
        }
        try:
            write_json(journal_path, journal)
            write_json(history_path, history)
            write_json(task_path, task)
        except BaseException as exc:
            rollback_errors: list[str] = []
            try:
                atomic_write_text(task_path, original_task)
            except OSError as rollback_exc:
                rollback_errors.append(f"task={rollback_exc}")
            try:
                if original_history is None:
                    history_path.unlink(missing_ok=True)
                else:
                    atomic_write_text(history_path, original_history)
            except OSError as rollback_exc:
                rollback_errors.append(f"history={rollback_exc}")
            try:
                journal_path.unlink(missing_ok=True)
            except OSError as rollback_exc:
                rollback_errors.append(f"journal={rollback_exc}")
            if rollback_errors:
                raise HarnessError(
                    f"任务/历史写入中断且回滚不完整：{exc}; rollback={'; '.join(rollback_errors)}"
                ) from exc
            raise
        try:
            journal_path.unlink()
        except OSError as exc:
            return f"工作流已提交，但事务日志清理失败；下次命令会恢复检查：{exc}"
        return None

    def task_approval(
        self,
        task_id: str,
        *,
        stage: str,
        status: str,
        actor: str,
        reason: str,
        agent_task: str = "",
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        try:
            with self.workflow_lock(normalized):
                with self.active_state_lock():
                    return self._task_approval_locked(
                        normalized,
                        stage=stage,
                        status=status,
                        actor=actor,
                        reason=reason,
                        agent_task=agent_task,
                    )
        except WorkflowLockError as exc:
            result = GateResult("task-approval")
            result.errors.append(f"无法取得任务工作流锁：{exc}")
            return result

    def _task_approval_locked(
        self,
        task_id: str,
        *,
        stage: str,
        status: str,
        actor: str,
        reason: str,
        agent_task: str,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("task-approval")
        actor = actor.strip()
        reason = reason.strip()
        if not actor:
            result.errors.append("--by 必须记录实际审批人")
            return result
        if status == "rejected" and not reason:
            result.errors.append("拒绝审批必须提供 --reason")
            return result
        agent_task = agent_task.strip()
        codex_thread_id = str(os.environ.get("CODEX_THREAD_ID", "")).strip()
        allow_stale = stage == "plan"
        contract = self.task_check(
            normalized,
            block_open_decisions=True,
            allow_stale_plan_context=allow_stale,
        )
        if not contract.ok:
            result.merge(contract)
            return result
        result.warnings.extend(contract.warnings)
        task = self.load_task(normalized)
        current_status = str(task.get("status", ""))
        if stage in {"merge", "release"}:
            state_gate = self.validate_active_state(normalized, task, required=True)
            if not state_gate.ok:
                result.merge(state_gate)
                return result
        allowed_statuses = {
            "plan": {"awaiting_plan_approval"},
            "merge": {"awaiting_review"},
            "release": {"awaiting_review", "approved_for_merge"},
        }[stage]
        if current_status not in allowed_statuses:
            result.errors.append(
                f"任务状态 {current_status} 不允许记录 {stage} 审批；允许：{', '.join(sorted(allowed_statuses))}"
            )
            return result
        if stage == "plan" and self.state_file.is_file():
            result.errors.append("plan 审批在 preflight 后已锁定；先修订计划并重新 preflight")
            return result
        expected_actor = self.expected_approval_actor(task, stage)
        if not expected_actor or actor.casefold() != expected_actor.casefold():
            field = "release_approver" if stage == "release" else "reviewer"
            result.errors.append(f"审批人必须与 task.json 中的 {field} 一致")
            return result
        approvals = task.get("manual_approvals")
        approval = approvals.get(stage) if isinstance(approvals, dict) else None
        if not isinstance(approval, dict) or approval.get("required") is not True:
            result.errors.append(f"manual_approvals.{stage}.required 未声明为 true")
            return result

        binding = self.codex_role_binding(task, stage)
        implementation_binding = self.codex_role_binding(task, "implementation")
        automated_approval = isinstance(binding, dict)
        if not automated_approval:
            result.errors.append(
                f"task-approval 要求预先声明 codex_role_bindings.{stage}；"
                "legacy/null binding 只能回放旧历史，不能记录新审批"
            )
            return result
        expected_agent_task = str(binding.get("agent_task", "")).strip()
        implementation_thread = (
            str(implementation_binding.get("thread_id", "")).strip()
            if isinstance(implementation_binding, dict)
            else ""
        )
        if agent_task != expected_agent_task:
            result.errors.append(
                f"--agent-task 必须精确匹配 codex_role_bindings.{stage}.agent_task"
            )
        if not CODEX_THREAD_ID_RE.fullmatch(codex_thread_id):
            result.errors.append("自动审批缺少有效 CODEX_THREAD_ID UUID")
        elif codex_thread_id == implementation_thread:
            result.errors.append("审批 CODEX_THREAD_ID 必须与 implementation thread 不同")
        if result.errors:
            return result

        plan_artifacts_hash: str | None = None
        decision_context_hash: str | None = None
        reviewed_contract_hash: str | None = None
        reviewed_policy_hash: str | None = None
        review_artifact: dict[str, Any] | None = None
        review_artifact_path: Path | None = None
        review_artifact_hash: str | None = None
        approval_context_hash: str | None = None
        if stage == "plan" and status == "approved":
            plan_gate = self.plan_check(
                normalized,
                allow_stale_plan_context=allow_stale,
            )
            if not plan_gate.ok:
                result.merge(plan_gate)
                return result
            result.warnings.extend(plan_gate.warnings)
            try:
                plan_artifacts_hash = self.plan_artifacts_sha256(normalized)
                decision_context_hash = self.decision_context_sha256(task)
                reviewed_contract_hash = plan_review_contract_hash(task)
                reviewed_policy_hash = plan_review_policy_hash(task)
            except HarnessError as exc:
                result.errors.append(str(exc))
                return result

        if automated_approval:
            try:
                (
                    review_artifact,
                    review_artifact_path,
                    review_artifact_hash,
                    approval_context_hash,
                ) = self.validate_approval_artifact(
                    normalized,
                    task,
                    stage=stage,
                    status=status,
                    actor=actor,
                    agent_task=agent_task,
                    codex_thread_id=codex_thread_id,
                )
            except (HarnessError, OSError, UnicodeError) as exc:
                result.errors.append(str(exc))
                return result

        changed_at = utc_now()
        approval["status"] = status
        approval["approved_by"] = actor if status == "approved" else None
        approval["approved_at"] = changed_at if status == "approved" else None
        task["updated_at"] = changed_at
        try:
            approval_event = {
                "type": "approval",
                "stage": stage,
                "status": status,
                "by": actor,
                "expected_actor": expected_actor,
                "agent_task": agent_task or None,
                "codex_thread_id": codex_thread_id or None,
                "expected_agent_task": expected_agent_task or None,
                "observed_agent_task": agent_task or None,
                "observed_codex_thread_id": codex_thread_id or None,
                "reason": reason,
                "at": changed_at,
            }
            if review_artifact is not None and review_artifact_path is not None:
                approval_event.update(
                    {
                        "review_artifact_path": display_path(review_artifact_path),
                        "review_artifact_sha256": review_artifact_hash,
                        "approval_context_sha256": approval_context_hash,
                        "reviewed_at": review_artifact.get("reviewed_at"),
                    }
                )
            if plan_artifacts_hash is not None:
                approval_event["plan_artifacts_sha256"] = plan_artifacts_hash
            if decision_context_hash is not None:
                approval_event["decision_context_sha256"] = decision_context_hash
            if reviewed_contract_hash is not None:
                approval_event["contract_sha256"] = reviewed_contract_hash
            if reviewed_policy_hash is not None:
                approval_event["policy_sha256"] = reviewed_policy_hash
            transaction_warning = self.write_task_workflow_update(
                normalized,
                task,
                approval_event,
            )
        except (OSError, HarnessError) as exc:
            result.errors.append(f"无法记录任务审批：{exc}")
            return result
        if transaction_warning:
            result.warnings.append(transaction_warning)
        result.data.update(
            {
                "task_id": normalized,
                "stage": stage,
                "status": status,
                "summary": "审批记录及 Codex 审计上下文已写入；字段本身不构成密码学身份。",
            }
        )
        return result

    def task_transition(
        self,
        task_id: str,
        *,
        target_status: str,
        actor: str,
        reason: str,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        try:
            with self.workflow_lock(normalized):
                with self.active_state_lock():
                    return self._task_transition_locked(
                        normalized,
                        target_status=target_status,
                        actor=actor,
                        reason=reason,
                    )
        except WorkflowLockError as exc:
            result = GateResult("task-transition")
            result.errors.append(f"无法取得任务工作流锁：{exc}")
            return result

    def _task_transition_locked(
        self,
        task_id: str,
        *,
        target_status: str,
        actor: str,
        reason: str,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("task-transition")
        actor = actor.strip()
        reason = reason.strip()
        if not actor:
            result.errors.append("--by 必须记录执行状态变更的人")
            return result
        if target_status in {"blocked", "cancelled", "closed"} and not reason:
            result.errors.append(f"进入 {target_status} 必须提供 --reason")
            return result
        try:
            task = self.load_task(normalized)
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result
        history_gate = self.workflow_history_check(
            normalized,
            task,
            allow_stale_plan_context=target_status
            in {"ready_for_analysis", "awaiting_plan_approval"},
        )
        if not history_gate.ok:
            result.merge(history_gate)
            return result
        result.warnings.extend(history_gate.warnings)
        current_status = str(task.get("status", ""))
        try:
            transitions = self.status_transitions()
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result
        allowed_targets = set(transitions.get(current_status, ()))
        if target_status not in allowed_targets:
            result.errors.append(
                f"非法状态迁移 {current_status} -> {target_status}；允许：{', '.join(sorted(allowed_targets)) or '<none>'}"
            )
            return result

        if target_status == "awaiting_plan_approval":
            gate = self.plan_check(normalized)
            if not gate.ok:
                result.merge(gate)
            else:
                result.warnings.extend(gate.warnings)
        elif target_status == "approved_for_implementation":
            contract = self.task_check(normalized, block_open_decisions=True)
            plan = self.plan_check(normalized)
            for gate in (contract, plan):
                if not gate.ok:
                    result.merge(gate)
            reviewer = str(task.get("reviewer", "")).strip()
            approvals = task.get("manual_approvals", {})
            plan_approval = approvals.get("plan") if isinstance(approvals, dict) else None
            if isinstance(plan_approval, dict) and plan_approval.get("required"):
                if not self.approval_is_valid(plan_approval, reviewer):
                    result.errors.append("缺少独立 reviewer 的计划审批")
        elif target_status == "implementing":
            gate = self.validate_active_state(normalized, task, required=True)
            if not gate.ok:
                result.merge(gate)
        elif target_status == "verifying":
            gate = self.scope_check(normalized, base_ref=None, bootstrap=False, require_state=True)
            if not gate.ok:
                result.merge(gate)
        elif target_status == "awaiting_review":
            gate = self.evidence_check(normalized, base_ref=None, require_state=True)
            if not gate.ok:
                result.merge(gate)
        elif target_status == "approved_for_merge":
            gate = self.release_check(
                normalized,
                base_ref=None,
                require_state=True,
                allow_pretransition=True,
            )
            if not gate.ok:
                result.merge(gate)

        if result.errors:
            return result
        changed_at = utc_now()
        self.reset_approval_values(task, self.approval_resets_for_transition(target_status))
        task["status"] = target_status
        task["updated_at"] = changed_at
        try:
            transaction_warning = self.write_task_workflow_update(
                normalized,
                task,
                {
                    "type": "transition",
                    "from": current_status,
                    "to": target_status,
                    "by": actor,
                    "reason": reason,
                    "at": changed_at,
                },
            )
        except (OSError, HarnessError) as exc:
            result.errors.append(f"无法记录状态迁移：{exc}")
            return result
        if transaction_warning:
            result.warnings.append(transaction_warning)

        state_cleared = False
        if target_status in {
            "ready_for_analysis",
            "awaiting_plan_approval",
            "closed",
            "cancelled",
        } and self.state_file.is_file():
            try:
                state = self.read_active_state()
                if isinstance(state, dict) and state.get("task_id") == normalized:
                    self.state_file.unlink()
                    state_cleared = True
            except (OSError, HarnessError) as exc:
                result.warnings.append(
                    "状态迁移已提交，但 active-task.json 清理失败；"
                    f"请使用 state-recover 受控恢复后复核：{exc}"
                )
        result.data.update(
            {
                "task_id": normalized,
                "from": current_status,
                "to": target_status,
                "active_state_cleared": state_cleared,
                "summary": f"任务状态已更新为 {target_status}。",
            }
        )
        return result

    # ---------- Project discovery ----------

    def project_check(self) -> GateResult:
        result = GateResult("project-check")
        required = self.config.get("project_check", {}).get("required_files", [])
        if not isinstance(required, list):
            result.errors.append("harness.json project_check.required_files 必须是 array")
            return result
        for rel in required:
            try:
                normalized = normalize_repo_path(str(rel), allow_glob=False)
            except ValueError as exc:
                result.errors.append(f"项目 Harness 必需文件路径无效 {rel!r}：{exc}")
                continue
            path = self.root / Path(*normalized.split("/"))
            path_error = repo_path_safety_error(self.root, path)
            if path_error:
                result.errors.append(
                    f"项目 Harness 必需文件路径不安全 {normalized}：{path_error}"
                )
                continue
            if not path.is_file():
                result.errors.append(f"缺少项目 Harness 文件：{normalized}")

        json_files = (
            self.config_file,
            self.harness_dir / "requirements-decisions.json",
            self.harness_dir / "schemas" / "task.schema.json",
            self.harness_dir / "templates" / "task.json",
            self.root / ".codex" / "hooks.json",
        )
        for path in json_files:
            path_error = repo_path_safety_error(self.root, path)
            if path_error:
                result.errors.append(
                    f"项目 JSON 路径不安全 {display_path(path)}：{path_error}"
                )
                continue
            if not path.is_file():
                continue
            try:
                read_json(path)
            except HarnessError as exc:
                result.errors.append(str(exc))
        toml_path = self.root / ".codex" / "config.toml"
        toml_error = repo_path_safety_error(self.root, toml_path)
        if toml_error:
            result.errors.append(f".codex/config.toml 路径不安全：{toml_error}")
        elif toml_path.is_file():
            try:
                with toml_path.open("rb") as handle:
                    codex_config = tomllib.load(handle)
            except (OSError, tomllib.TOMLDecodeError) as exc:
                result.errors.append(f".codex/config.toml 无法解析：{exc}")
            else:
                if codex_config.get("sandbox_mode") != "workspace-write":
                    result.errors.append(".codex/config.toml sandbox_mode 必须为 workspace-write")
                sandbox = codex_config.get("sandbox_workspace_write")
                if not isinstance(sandbox, dict) or sandbox.get("network_access") is not False:
                    result.errors.append(
                        ".codex/config.toml 必须保持 network_access=false；远程权限由外层会话显式授予"
                    )
                features = codex_config.get("features")
                if not isinstance(features, dict) or features.get("hooks") is not True:
                    result.errors.append(".codex/config.toml 必须启用项目 Hook")

        execution = self.config.get("execution", {})
        if not isinstance(execution, dict):
            result.errors.append("harness.json execution 必须是 object")
        else:
            expected_execution = {
                "production_access": "task_scoped_explicit",
                "secret_access": "external_reference_only",
                "network_access": "task_scoped_explicit",
            }
            for key, expected in expected_execution.items():
                if execution.get(key) != expected:
                    result.errors.append(f"execution.{key} 必须固定为 {expected}")
            if execution.get("max_test_timeout_seconds") != HARD_MAX_TEST_TIMEOUT_SECONDS:
                result.errors.append(
                    f"execution.max_test_timeout_seconds 必须固定为 {HARD_MAX_TEST_TIMEOUT_SECONDS}"
                )
            if execution.get("max_captured_output_bytes") != HARD_MAX_CAPTURED_OUTPUT_BYTES:
                result.errors.append(
                    f"execution.max_captured_output_bytes 必须固定为 {HARD_MAX_CAPTURED_OUTPUT_BYTES}"
                )
        for entry in self.source_status():
            if entry.get("status") == "blocked" and entry.get("detail"):
                result.errors.append(
                    f"ShopXO 必需源码路径不安全 {entry['path']}：{entry['detail']}"
                )
        source_config = self.config.get("source", {})
        pinned_commit = source_config.get("pinned_commit") if isinstance(source_config, dict) else None
        if not isinstance(pinned_commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", pinned_commit):
            result.errors.append("source.pinned_commit 必须是固定的 Git commit")
        try:
            self.status_transitions()
        except HarnessError as exc:
            result.errors.append(str(exc))
        workflow = self.config.get("workflow", {})
        if not isinstance(workflow, dict) or workflow.get("preflight_statuses") != [
            "approved_for_implementation"
        ]:
            result.errors.append("workflow.preflight_statuses 必须固定为 approved_for_implementation")
        if (
            not isinstance(workflow, dict)
            or workflow.get("post_implementation_plan_changes")
            != POST_IMPLEMENTATION_PLAN_CHANGE_MODE
        ):
            result.errors.append(
                "workflow.post_implementation_plan_changes 必须固定为 "
                + POST_IMPLEMENTATION_PLAN_CHANGE_MODE
            )
        if not isinstance(workflow, dict) or workflow.get("release_statuses") != [
            "approved_for_merge",
            "closed",
        ]:
            result.errors.append(
                "workflow.release_statuses 必须固定为 approved_for_merge, closed"
            )
        paths_config = self.config.get("paths", {})
        configured_bootstrap = (
            paths_config.get("bootstrap_allowed", [])
            if isinstance(paths_config, dict)
            else []
        )
        try:
            normalized_bootstrap = {
                normalize_repo_path(str(item), allow_glob=True)
                for item in configured_bootstrap
            }
        except ValueError as exc:
            result.errors.append(f"paths.bootstrap_allowed 包含无效路径：{exc}")
            normalized_bootstrap = set()
        if normalized_bootstrap != set(HARNESS_POLICY_PATTERNS):
            result.errors.append(
                "paths.bootstrap_allowed 必须与代码固定的 Harness 策略路径完全一致"
            )
        configured_runtime = (
            paths_config.get("task_runtime_allowed", [])
            if isinstance(paths_config, dict)
            else []
        )
        if tuple(str(item) for item in configured_runtime) != TASK_RUNTIME_PATTERN_TEMPLATES:
            result.errors.append(
                "paths.task_runtime_allowed 必须与代码固定的当前任务制品清单完全一致"
            )

        for dirname in ("tasks", "runs", "reports", "state", "templates", "schemas"):
            path = self.harness_dir / dirname
            path_error = repo_path_safety_error(self.root, path)
            if path_error:
                result.errors.append(f"Harness 目录不安全 .harness/{dirname}：{path_error}")
            elif not path.is_dir():
                result.errors.append(f"缺少 Harness 目录：.harness/{dirname}")

        if not self.requirements_path().is_file():
            result.errors.append(f"缺少需求文档：{display_path(self.requirements_path())}")
        else:
            try:
                count = len(self.known_requirement_ids())
            except HarnessError as exc:
                result.errors.append(str(exc))
                count = 0
            if count == 0:
                result.errors.append("未从中文需求文档提取到任何需求 ID")
            result.data["requirement_id_count"] = count

        guard_path = self.root / ".codex" / "hooks" / "harness_guard.py"
        guard_error = repo_path_safety_error(self.root, guard_path)
        if guard_error:
            result.errors.append(f"harness_guard.py 路径不安全：{guard_error}")
        elif guard_path.is_file():
            try:
                guard = guard_path.read_text(encoding="utf-8")
            except OSError as exc:
                result.errors.append(f"无法读取 harness_guard.py：{exc}")
            else:
                for marker in (
                    "active-task.json",
                    "contract_sha256",
                    "policy_sha256",
                    "plan_artifacts_sha256",
                    "decision_context_sha256",
                    "canonical_json_hash",
                ):
                    if marker not in guard:
                        result.errors.append(f"harness_guard.py 缺少兼容标记：{marker}")

        if sys.version_info < MIN_PYTHON:
            result.errors.append("Harness 要求 Python 3.11+")
        result.data["summary"] = (
            f"项目级 Harness 文件检查完成，提取需求 ID {result.data.get('requirement_id_count', 0)} 个。"
        )
        return result

    def doctor(self, *, strict: bool) -> GateResult:
        result = GateResult("doctor --strict" if strict else "doctor")
        tools = self.current_toolchain()
        if tools["python"]["status"] != "confirmed":
            result.errors.append("Python 版本低于 3.11")
        if tools["git"]["status"] != "confirmed":
            result.errors.append("Git 不可用，Harness 无法计算范围和证据")
        for name in ("php", "composer"):
            if tools[name]["status"] != "confirmed":
                result.warnings.append(f"{name} 不可用；需要该工具的测试将被标记 blocked")
        if all(tools[name]["status"] != "confirmed" for name in ("mysql", "psql", "sqlite3")):
            result.warnings.append("未发现数据库客户端；数据库验证当前不可执行")

        source = self.source_status()
        for entry in source:
            if entry["status"] != "confirmed":
                if entry.get("detail"):
                    result.warnings.append(
                        f"ShopXO 源码路径不安全：{entry['path']}（{entry['detail']}）"
                    )
                elif entry["path"] == "app/common.php":
                    result.warnings.append("app/common.php 缺失（当前 Git 状态显示上游公共入口被删除）")
                else:
                    result.warnings.append(f"ShopXO 源码组件缺失：{entry['path']}")

        writable = os.access(self.harness_dir, os.W_OK) if self.harness_dir.exists() else os.access(self.root, os.W_OK)
        if not writable:
            result.errors.append(".harness 目录不可写")
        if not self.is_git_repository():
            result.errors.append("当前目录不是 Git 工作树")
        else:
            dirty = self.repository_dirty_paths()
            if dirty:
                result.warnings.append(f"工作区存在 {len(dirty)} 个变更路径")

        markers = self.config.get("execution", {}).get("production_environment_markers", {})
        production_hits: list[str] = []
        if isinstance(markers, dict):
            for key, values in markers.items():
                current = os.environ.get(str(key), "").strip().casefold()
                allowed_values = {str(item).casefold() for item in values} if isinstance(values, list) else set()
                if current and current in allowed_values:
                    production_hits.append(str(key))
        if production_hits:
            result.errors.append(f"检测到生产环境标记：{', '.join(production_hits)}")

        secret_names = sorted(
            name
            for name in os.environ
            if re.search(r"(?i)(password|token|secret|api_?key|private_?key)", name)
        )
        if secret_names:
            result.warnings.append(
                f"进程环境中存在 {len(secret_names)} 个疑似密钥变量；Harness 仅报告名称数量，不读取或输出值"
            )

        result.data.update(
            {
                "strict": strict,
                "tools": tools,
                "source": source,
                "workspace_writable": writable,
                "production_markers": production_hits,
            }
        )
        if strict and result.warnings:
            result.errors.extend(f"严格模式警告升级：{warning}" for warning in list(result.warnings))
        result.data["summary"] = "环境检查完成；非严格模式保留警告，严格模式将警告视为失败。"
        return result

    def baseline(self) -> GateResult:
        result = GateResult("baseline")
        generated_at = utc_now()
        baselines = self.harness_dir / "baselines"
        try:
            ensure_repo_path_safe(self.root, baselines, label="baseline 目录")
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result
        try:
            baselines.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            result.errors.append(f"无法创建 baselines 目录：{exc}")
            return result

        source_commit = self.pinned_source_commit()
        generated_from_head = self.head()
        source_config = self.config.get("source", {})

        def metadata(invalidated_by: list[str]) -> dict[str, Any]:
            return {
                "schema_version": 1,
                "generated_at": generated_at,
                "source_commit": source_commit,
                "generated_from_head": generated_from_head,
                "upstream_remote": (
                    source_config.get("upstream_remote") if isinstance(source_config, dict) else None
                ),
                "shopxo_version": (
                    source_config.get("shopxo_version") if isinstance(source_config, dict) else None
                ),
                "invalidated_by": invalidated_by,
            }

        git_root = self.git_value("rev-parse", "--show-toplevel")
        remotes: dict[str, str] = {}
        remote_names = self.git_value("remote")
        if remote_names:
            for name in remote_names.splitlines():
                value = self.git_value("remote", "get-url", name.strip())
                if value:
                    remotes[name.strip()] = sanitize_remote_url(value) or ""
        source = self.source_status()
        repository_freshness = self.repository_baseline_facts()
        repository = {
            **metadata(
                [
                    "source.pinned_commit or upstream remote changes",
                    "required ShopXO source paths change",
                    "repository baseline policy changes",
                ]
            ),
            "facts": {
                "git_repository": {
                    "status": "confirmed" if git_root else "not_available",
                    "value": git_root,
                    "evidence": "git rev-parse --show-toplevel",
                },
                "branch": {
                    "status": "confirmed" if self.branch() else "unknown",
                    "value": self.branch(),
                    "evidence": "git branch --show-current",
                },
                "commit": {
                    "status": "confirmed" if self.head() else "unknown",
                    "value": self.head(),
                    "evidence": "git rev-parse HEAD",
                },
                "remotes": {
                    "status": "confirmed" if remotes else "not_available",
                    "value": remotes,
                    "evidence": "git remote/get-url (credentials redacted)",
                },
                "shopxo_source": {
                    "status": "confirmed" if all(item["status"] == "confirmed" for item in source) else "blocked",
                    "value": source,
                    "evidence": "required path existence checks",
                },
                "worktree": {
                    "status": "confirmed" if git_root else "blocked",
                    "value": {"changed_paths": len(self.repository_dirty_paths()) if git_root else None},
                    "evidence": "git status --porcelain=v1 -z",
                },
            },
            "freshness_facts": repository_freshness,
            "facts_sha256": canonical_json_hash(repository_freshness),
        }
        tool_values = self.current_toolchain()
        composer_files = self.composer_file_status()
        project_requirements = self.project_toolchain_requirements()
        portable_toolchain = self.portable_toolchain_facts()
        toolchain = {
            **metadata(
                [
                    "source.pinned_commit changes",
                    "project PHP/database requirements change",
                    "composer.json or composer.lock content/presence changes",
                ]
            ),
            "project_requirements": project_requirements,
            "tools": tool_values,
            "composer_files": composer_files,
            "host_facts_sha256": canonical_json_hash(
                {"tools": tool_values, "composer_files": composer_files}
            ),
            "portable_facts_sha256": canonical_json_hash(portable_toolchain),
        }
        sql_path = self.root / "config" / "shopxo.sql"
        table_count: int | None = None
        sql_sha: str | None = None
        sql_path_error = repo_path_safety_error(self.root, sql_path)
        if sql_path_error is None and sql_path.is_file():
            try:
                raw = sql_path.read_bytes()
                canonical_sql = canonical_utf8_text_bytes(
                    raw, label="config/shopxo.sql"
                )
                sql_sha = hashlib.sha256(canonical_sql).hexdigest()
                table_count = len(
                    re.findall(rb"(?i)\bCREATE\s+TABLE\b", canonical_sql)
                )
            except (OSError, HarnessError):
                pass
        migration_evidence = [
            "app/install/controller/Index.php",
            "app/service/SystemUpgradeService.php",
            "app/service/PluginsAdminService.php",
            "app/service/SqlConsoleService.php",
        ]
        migration_confirmed = all(
            repo_path_safety_error(self.root, self.root / path) is None
            and (self.root / path).is_file()
            for path in migration_evidence
        )
        migration_facts = self.migration_mechanism_facts()
        database = {
            **metadata(
                [
                    "source.pinned_commit changes",
                    "config/shopxo.sql content changes",
                    "database engine/version or migration mechanism changes",
                ]
            ),
            "shopxo_sql": {
                "status": "confirmed" if sql_sha else "not_available",
                "path": "config/shopxo.sql",
                "sha256": sql_sha,
                "hash_mode": "utf8-lf-v1",
                "create_table_statements": table_count,
            },
            "migration_mechanism": {
                "status": "confirmed" if migration_confirmed else "unknown",
                "value": {
                    "fresh_install": "config/shopxo.sql",
                    "system_upgrade": ["update.sql", "power.sql"],
                    "plugin": ["install.sql", "update.sql", "uninstall.sql"],
                    "standard_migration_ledger": False,
                    "project_policy": "维护项目级版本台账；不得直接修改完整 shopxo.sql 充当增量迁移",
                } if migration_confirmed else None,
                "evidence": migration_evidence if migration_confirmed else "接入版本的升级入口不完整",
                "facts_sha256": canonical_json_hash(migration_facts),
                "facts": migration_facts,
            },
            "production_connection": {
                "status": "blocked",
                "value": None,
                "evidence": "Harness policy denies production database access",
            },
        }
        test_candidates = self.discovered_test_files()
        tests = {
            **metadata(
                [
                    "source.pinned_commit changes",
                    "test configuration or discovered test file inventory changes",
                    "test runner/toolchain baseline changes",
                ]
            ),
            "inventory_sha256": canonical_json_hash(test_candidates),
            "discovered_files": {
                "status": "confirmed" if test_candidates else "not_available",
                "value": test_candidates,
                "evidence": "repository glob; vendor excluded",
            },
            "executed": {
                "status": "not_available",
                "value": False,
                "evidence": "baseline is read-only discovery and does not claim tests passed",
            },
        }
        values = {
            "repository.json": repository,
            "toolchain.json": toolchain,
            "database.json": database,
            "tests.json": tests,
        }
        try:
            for name, value in values.items():
                write_json(baselines / name, value)
        except OSError as exc:
            result.errors.append(f"写入基线失败：{exc}")
            return result
        result.data.update(
            {
                "files": [display_path(baselines / name) for name in values],
                "summary": "四份事实基线已更新；未知和缺失项未被标记为 confirmed。",
            }
        )
        return result

    def source_baseline_check(self) -> GateResult:
        """CI-safe source and portable baseline freshness gate."""

        result = GateResult("source-baseline-check")
        if not self.is_git_repository():
            result.errors.append("当前目录不是 Git 工作树")

        source = self.source_status()
        missing_source = [item["path"] for item in source if item["status"] != "confirmed"]
        if missing_source:
            result.errors.append(
                "ShopXO 源码未达到业务开发基线，缺少：" + ", ".join(missing_source)
            )

        pinned_commit = self.pinned_source_commit()
        if not pinned_commit or not self.git_object_exists(pinned_commit):
            result.errors.append("source.pinned_commit 在当前仓库中不存在")
        elif not self.is_ancestor(pinned_commit):
            result.errors.append("source.pinned_commit 不是当前 HEAD 的祖先")

        baseline_files = self.config.get("workflow", {}).get("baseline_files", [])
        loaded: dict[str, dict[str, Any]] = {}
        for rel in baseline_files:
            path = self.root / str(rel)
            try:
                ensure_repo_path_safe(self.root, path, label=f"基线 {rel}")
            except HarnessError as exc:
                result.errors.append(str(exc))
                continue
            if not path.is_file():
                result.errors.append(f"缺少基线文件：{rel}；先运行 baseline")
                continue
            try:
                value = read_json(path)
            except HarnessError as exc:
                result.errors.append(str(exc))
                continue
            if not isinstance(value, dict):
                result.errors.append(f"基线顶层必须是 object：{rel}")
                continue
            loaded[str(rel)] = value
            if value.get("source_commit") != pinned_commit:
                result.errors.append(
                    f"基线 {rel} 不属于当前 source.pinned_commit；重新运行 baseline"
                )
            invalidated_by = value.get("invalidated_by")
            if not isinstance(invalidated_by, list) or not invalidated_by:
                result.errors.append(f"基线 {rel} 缺少 invalidated_by")

        toolchain = loaded.get(".harness/baselines/toolchain.json")
        if toolchain:
            current_signature = canonical_json_hash(self.portable_toolchain_facts())
            if toolchain.get("portable_facts_sha256") != current_signature:
                result.errors.append(
                    "项目工具链要求或 Composer 内容相对 baseline 已变化；重新运行 baseline"
                )

        database = loaded.get(".harness/baselines/database.json")
        if database:
            sql_path = self.root / "config" / "shopxo.sql"
            sql_path_error = repo_path_safety_error(self.root, sql_path)
            if sql_path_error:
                result.errors.append(
                    f"config/shopxo.sql 路径不安全：{sql_path_error}"
                )
                current_sql_sha = None
            else:
                try:
                    current_sql_sha = canonical_text_file_sha256(
                        sql_path, label="config/shopxo.sql"
                    )
                except HarnessError:
                    current_sql_sha = None
            shopxo_sql = database.get("shopxo_sql")
            recorded_sql_sha = (
                shopxo_sql.get("sha256") if isinstance(shopxo_sql, dict) else None
            )
            if not current_sql_sha or recorded_sql_sha != current_sql_sha:
                result.errors.append(
                    "config/shopxo.sql 相对 database baseline 已变化；重新运行 baseline"
                )
            migration = database.get("migration_mechanism")
            recorded_migration_sha = (
                migration.get("facts_sha256") if isinstance(migration, dict) else None
            )
            current_migration_sha = canonical_json_hash(
                self.migration_mechanism_facts()
            )
            if recorded_migration_sha != current_migration_sha:
                result.errors.append(
                    "ShopXO 迁移机制事实相对 database baseline 已变化；重新运行 baseline"
                )

        tests = loaded.get(".harness/baselines/tests.json")
        if tests:
            current_inventory_sha = canonical_json_hash(self.discovered_test_files())
            if tests.get("inventory_sha256") != current_inventory_sha:
                result.errors.append("测试文件清单相对 tests baseline 已变化；重新运行 baseline")

        repository = loaded.get(".harness/baselines/repository.json")
        if repository:
            source_config = self.config.get("source", {})
            expected_upstream = (
                source_config.get("upstream_remote")
                if isinstance(source_config, dict)
                else None
            )
            actual_upstream = sanitize_remote_url(
                self.git_value("remote", "get-url", "upstream")
            )
            if expected_upstream and actual_upstream != expected_upstream:
                result.errors.append("upstream remote 与固定 source 配置不一致")
            current_repository_signature = canonical_json_hash(
                self.repository_baseline_facts()
            )
            if repository.get("facts_sha256") != current_repository_signature:
                result.errors.append(
                    "仓库来源、ShopXO 版本或必需源码路径状态相对 repository baseline 已变化；"
                    "重新审查并运行 baseline"
                )

        result.data.update(
            {
                "source": source,
                "pinned_commit": pinned_commit,
                "baseline_files": sorted(loaded),
                "summary": "ShopXO 必需源码、固定上游和可移植基线已检查。",
            }
        )
        return result

    # ---------- Plan gate ----------

    def markdown_check(
        self,
        path: Path,
        *,
        required_headings: Sequence[str],
        minimum_chars: int,
    ) -> list[str]:
        errors: list[str] = []
        if not path.is_file():
            return [f"缺少文档：{display_path(path)}"]
        path_error = repo_path_safety_error(self.root, path)
        if path_error:
            return [f"文档路径不安全 {display_path(path)}：{path_error}"]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return [f"无法读取 {display_path(path)}：{exc}"]
        if len(text.strip()) < minimum_chars:
            errors.append(f"{display_path(path)} 内容过短（至少 {minimum_chars} 字符）")
        for heading in required_headings:
            if heading not in text:
                errors.append(f"{display_path(path)} 缺少标题：{heading}")
        for marker in PLACEHOLDER_MARKERS:
            if marker.casefold() in text.casefold():
                errors.append(f"{display_path(path)} 仍含模板占位标记：{marker}")
                break
        return errors

    def plan_check(
        self,
        task_id: str,
        *,
        allow_stale_plan_context: bool = False,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("plan-check")
        contract = self.task_check(
            normalized,
            allow_stale_plan_context=allow_stale_plan_context,
        )
        if not contract.ok:
            result.merge(contract)
            return result
        result.warnings.extend(contract.warnings)
        task = self.load_task(normalized)
        directory = self.task_dir(normalized)
        checks = {
            "requirement.md": (["## 关联需求", "## 任务路由", "## 业务目标", "## 明确不做", "## 开放决策"], 260),
            "impact-analysis.md": (
                ["## 需求与当前事实", "## 当前调用链与数据", "## 影响范围", "## 方案比较", "## 风险与边界", "## 预计文件"],
                600 if RISK_ORDER.get(str(task.get("risk_level")), 0) >= 2 else 350,
            ),
            "implementation-plan.md": (
                ["## 实施步骤", "## 验证顺序", "## 数据库与核心适配", "## 失败处理与回滚"],
                500,
            ),
            "test-plan.md": (["## 自动测试", "## 手工验收", "## 数据与权限", "## 未覆盖项"], 400),
        }
        for name, (headings, minimum) in checks.items():
            result.errors.extend(
                self.markdown_check(directory / name, required_headings=headings, minimum_chars=minimum)
            )
        requirement_text = ""
        requirement_md = directory / "requirement.md"
        if requirement_md.is_file() and not path_is_link_like(requirement_md):
            try:
                requirement_text = requirement_md.read_text(encoding="utf-8")
            except OSError:
                pass
        for requirement_id in task.get("requirement_ids", []):
            if isinstance(requirement_id, str) and requirement_id not in requirement_text:
                result.errors.append(f"requirement.md 未包含任务需求编号：{requirement_id}")
        for label, value in (
            ("PRIORITY", task.get("priority")),
            ("PHASE", task.get("phase")),
        ):
            if not re.search(
                rf"(?im)^\s*[-*]?\s*{label}:\s*{re.escape(str(value))}\s*$",
                requirement_text,
            ):
                result.errors.append(
                    f"requirement.md 未记录与 task.json 一致的 {label}: {value}"
                )
        result.data["summary"] = "需求摘录、影响分析、实施计划和测试计划已检查。"
        return result

    def core_change_registration_errors(
        self,
        task_id: str,
        task: dict[str, Any],
    ) -> list[str]:
        """Validate the approved eight-column core-change registry row."""

        normalized = self.validate_task_id(task_id)
        core_change = task.get("shopxo_core_change", {})
        if not isinstance(core_change, dict) or core_change.get("required") is not True:
            return []
        register = self.root / ".harness" / "core-changes" / "REGISTER.md"
        register_error = repo_path_safety_error(self.root, register)
        if register_error:
            return [f"核心修改登记路径不安全：{register_error}"]
        try:
            lines = register.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return [f"无法读取核心修改登记：{exc}"]

        errors: list[str] = []
        rows: list[tuple[int, list[str]]] = []
        for line_number, line in enumerate(lines, start=1):
            if not line.lstrip().startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells and cells[0].casefold() == "task id":
                if len(cells) != 8:
                    errors.append("核心修改登记表头必须固定为 8 列")
                continue
            if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                if len(cells) != 8:
                    errors.append("核心修改登记分隔行必须固定为 8 列")
                continue
            if not cells or not cells[0].strip("`"):
                continue
            if len(cells) != 8:
                errors.append(f"核心修改登记第 {line_number} 行必须完整填写 8 列")
                continue
            rows.append((line_number, cells))

        matches = [
            (line_number, cells)
            for line_number, cells in rows
            if cells[0].strip().strip("`").upper() == normalized
        ]
        if len(matches) != 1:
            errors.append(
                f"核心修改登记必须且只能有一行 Task ID={normalized}，当前 {len(matches)} 行"
            )
            return errors

        line_number, cells = matches[0]
        baseline = cells[1].strip().strip("`")
        expected_baseline = self.pinned_source_commit()
        if baseline != expected_baseline:
            errors.append(
                f"核心修改登记第 {line_number} 行 upstream baseline 必须为 {expected_baseline}"
            )

        registered_paths: set[str] = set()
        for raw_path in re.split(r"(?:<br\s*/?>|[,，;；])", cells[2], flags=re.I):
            candidate = raw_path.strip().strip("`")
            if not candidate:
                continue
            try:
                registered_paths.add(normalize_repo_path(candidate, allow_glob=True))
            except ValueError as exc:
                errors.append(
                    f"核心修改登记第 {line_number} 行 Paths 路径无效 {candidate!r}：{exc}"
                )
        declared_paths: set[str] = set()
        for raw_path in core_change.get("paths", []):
            try:
                declared_paths.add(normalize_repo_path(str(raw_path), allow_glob=True))
            except ValueError as exc:
                errors.append(f"核心修改声明路径无效 {raw_path!r}：{exc}")
        missing_paths = sorted(declared_paths - registered_paths)
        if missing_paths:
            errors.append(
                "核心修改登记 Paths 未覆盖任务声明路径：" + ", ".join(missing_paths)
            )

        for index, label in (
            (3, "Why plugin/hook is insufficient"),
            (4, "Upgrade risk"),
            (5, "Rollback"),
        ):
            if not cells[index].strip().strip("`"):
                errors.append(
                    f"核心修改登记第 {line_number} 行 {label} 不得为空"
                )

        reviewer = cells[6].strip().strip("`")
        expected_reviewer = str(task.get("reviewer", "")).strip()
        if not expected_reviewer or reviewer.casefold() != expected_reviewer.casefold():
            errors.append("核心修改登记 Reviewer 必须与 task.json reviewer 一致")
        status = cells[7].strip().strip("`").casefold()
        if status != "approved":
            errors.append("核心修改登记 Status 必须为 approved")
        return errors

    # ---------- Active task and preflight ----------

    def read_active_state(self) -> dict[str, Any] | None:
        if not self.state_file.is_file():
            return None
        ensure_repo_path_safe(self.root, self.state_file, label="active-task.json")
        value = read_json(self.state_file)
        if not isinstance(value, dict):
            raise HarnessError("active-task.json 顶层必须是 object")
        return value

    def validate_active_state(
        self,
        task_id: str,
        task: dict[str, Any],
        *,
        required: bool,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("active-task")
        try:
            state = self.read_active_state()
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result
        if state is None:
            if required:
                result.errors.append("尚未运行 preflight，缺少 .harness/state/active-task.json")
            else:
                result.warnings.append("未找到活动任务状态；仅允许 CI 使用显式 base ref 继续")
            return result
        state_task_id = str(state.get("task_id", ""))
        if not TASK_ID_RE.fullmatch(state_task_id):
            result.errors.append("active-task.json task_id 格式无效")
            return result
        if state_task_id != normalized:
            result.errors.append(f"活动任务是 {state_task_id}，不是 {normalized}")
        state_branch = state.get("git_branch")
        current_branch = self.branch()
        if not isinstance(state_branch, str) or not state_branch:
            result.errors.append("active-task.json 缺少 git_branch")
        elif current_branch != state_branch:
            result.errors.append(
                f"当前分支 {current_branch or '<detached>'} 与 preflight 分支 {state_branch} 不一致"
            )
        expected = state.get("contract_sha256")
        actual = immutable_contract_hash(task)
        if not isinstance(expected, str) or expected != actual:
            result.errors.append("immutable contract sha256 与 preflight 状态不一致，请重新审批并 preflight")
        policy_expected = state.get("policy_sha256")
        policy_actual = policy_contract_hash(task)
        if not isinstance(policy_expected, str) or policy_expected != policy_actual:
            result.errors.append("任务执行策略在 preflight 后发生变化，请重新审批并 preflight")
        plan_expected = state.get("plan_artifacts_sha256")
        try:
            plan_actual = self.plan_artifacts_sha256(normalized)
        except HarnessError as exc:
            result.errors.append(str(exc))
            plan_actual = None
        if (
            not isinstance(plan_expected, str)
            or plan_actual is None
            or plan_expected != plan_actual
        ):
            result.errors.append("计划制品在 preflight 后发生变化，请重新审批并 preflight")
        decision_expected = state.get("decision_context_sha256")
        try:
            decision_actual = self.decision_context_sha256(task)
        except HarnessError as exc:
            result.errors.append(str(exc))
            decision_actual = None
        if (
            not isinstance(decision_expected, str)
            or decision_actual is None
            or decision_expected != decision_actual
        ):
            result.errors.append("关联需求决策在 preflight 后发生变化，请重新审批并 preflight")
        base = state.get("scope_base_commit")
        if not isinstance(base, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", base):
            result.errors.append("active-task.json 缺少有效 scope_base_commit")
        elif not self.git_object_exists(base):
            result.errors.append(f"scope_base_commit 在当前仓库不存在：{base}")
        elif not self.is_ancestor(base):
            result.errors.append("scope_base_commit 不是当前 HEAD 的祖先，拒绝不可靠范围检查")
        result.data.update(
            {
                "task_id": state_task_id,
                "contract_sha256": actual,
                "policy_sha256": policy_actual,
                "plan_artifacts_sha256": plan_actual,
                "decision_context_sha256": decision_actual,
                "scope_base_commit": base,
                "git_branch": state_branch,
            }
        )
        return result

    def state_recover(
        self,
        task_id: str,
        *,
        actor: str,
        reason: str,
        allow_invalid_state: bool,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        try:
            # Preserve the project-wide lock order used by transitions and
            # approvals: per-task workflow lock, then global active-state lock.
            with self.workflow_lock(normalized):
                with self.active_state_lock():
                    return self._state_recover_locked(
                        normalized,
                        actor=actor,
                        reason=reason,
                        allow_invalid_state=allow_invalid_state,
                    )
        except WorkflowLockError as exc:
            result = GateResult("state-recover")
            result.errors.append(f"无法取得状态恢复锁：{exc}")
            return result

    def _state_recover_locked(
        self,
        task_id: str,
        *,
        actor: str,
        reason: str,
        allow_invalid_state: bool,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("state-recover")
        actor = actor.strip()
        reason = reason.strip()
        if not actor:
            result.errors.append("--by 必须记录实际执行状态恢复的人")
        if len(reason) < 10 or any(
            marker.casefold() in reason.casefold() for marker in PLACEHOLDER_MARKERS
        ):
            result.errors.append("--reason 必须给出至少 10 字符的具体恢复原因")
        try:
            task = self.load_task(normalized)
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result
        authorized_actors = {
            str(task.get(field) or "").strip().casefold()
            for field in ("owner", "reviewer", "release_approver")
            if str(task.get(field) or "").strip()
        }
        if actor and actor.casefold() not in authorized_actors:
            result.errors.append(
                "state-recover 执行人必须匹配 task.json 的 owner、reviewer 或 release_approver"
            )
        task_status = str(task.get("status", ""))
        recoverable_statuses = {
            "ready_for_analysis",
            "awaiting_plan_approval",
            "blocked",
            "closed",
            "cancelled",
        }
        if task_status not in recoverable_statuses:
            result.errors.append(
                f"任务状态 {task_status or '<empty>'} 不允许清除活动状态；"
                "请先按状态机退回 blocked/ready_for_analysis 或结束任务"
            )
        if result.errors:
            return result

        state_parent = self.state_file.parent
        try:
            ensure_repo_path_safe(self.root, state_parent, label="active state 父目录")
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result
        state_is_symlink = path_is_link_like(self.state_file)
        if not state_is_symlink and not self.state_file.exists():
            result.errors.append("不存在 active-task.json，无需恢复")
            return result
        if not state_is_symlink and not self.state_file.is_file():
            result.errors.append("active-task.json 不是普通文件，拒绝自动清理")
            return result

        state_value: Any = None
        state_bytes: bytes | None = None
        invalid_reason: str | None = None
        symlink_target: str | None = None
        if state_is_symlink:
            invalid_reason = "active-task.json is a symlink"
            try:
                symlink_target = redact_text(os.readlink(self.state_file))
            except OSError as exc:
                result.errors.append(f"无法检查 active-task.json 符号链接：{exc}")
                return result
        else:
            try:
                ensure_repo_path_safe(self.root, self.state_file, label="active-task.json")
                state_bytes = self.state_file.read_bytes()
                state_value = json_loads_strict(
                    state_bytes.decode("utf-8"), source=display_path(self.state_file)
                )
            except (HarnessError, OSError, UnicodeDecodeError) as exc:
                invalid_reason = str(exc)
            else:
                if not isinstance(state_value, dict):
                    invalid_reason = "active-task.json 顶层不是 object"
                else:
                    state_owner = state_value.get("task_id")
                    if (
                        isinstance(state_owner, str)
                        and TASK_ID_RE.fullmatch(state_owner)
                        and state_owner != normalized
                    ):
                        result.errors.append(
                            f"active-task.json 属于 {state_owner}，拒绝由 {normalized} 清理"
                        )
                        return result
                    if state_value.get("schema_version") != 1:
                        invalid_reason = "active-task.json schema_version 无效"
                    elif not isinstance(state_owner, str) or not TASK_ID_RE.fullmatch(
                        state_owner
                    ):
                        invalid_reason = "active-task.json task_id 无效"

        if invalid_reason and not allow_invalid_state:
            result.errors.append(
                "active-task.json 无效；复核后使用 --allow-invalid-state 才能清理："
                + invalid_reason
            )
            return result

        recovery_root = self.harness_dir / "state" / "recoveries"
        recovery_dir = recovery_root / f"{run_id('state-recover')}-{normalized}"
        snapshot_path = recovery_dir / "active-task.snapshot"
        metadata_path = recovery_dir / "recovery.json"
        try:
            ensure_repo_path_safe(self.root, recovery_root, label="状态恢复记录目录")
            ensure_repo_path_safe(self.root, recovery_dir, label="本次状态恢复目录")
            recovery_dir.mkdir(parents=True, exist_ok=False)
            metadata = {
                "schema_version": 1,
                "status": "prepared",
                "task_id": normalized,
                "task_status": task_status,
                "actor": redact_text(actor),
                "reason": redact_text(reason),
                "allow_invalid_state": allow_invalid_state,
                "invalid_reason": redact_text(invalid_reason) if invalid_reason else None,
                "state_sha256": (
                    hashlib.sha256(state_bytes).hexdigest()
                    if state_bytes is not None
                    else None
                ),
                "prepared_at": utc_now(),
            }
            if symlink_target is not None:
                metadata["symlink_target"] = symlink_target
            write_json(metadata_path, metadata)
            if state_is_symlink:
                self.state_file.unlink()
                snapshot_file: str | None = None
            else:
                assert state_bytes is not None
                current_bytes = self.state_file.read_bytes()
                if hashlib.sha256(current_bytes).digest() != hashlib.sha256(
                    state_bytes
                ).digest():
                    raise HarnessError(
                        "active-task.json 在恢复检查期间发生变化，拒绝清理"
                    )
                os.replace(self.state_file, snapshot_path)
                snapshot_file = snapshot_path.name
            metadata.update(
                {
                    "status": "cleared",
                    "cleared_at": utc_now(),
                    "snapshot_file": snapshot_file,
                }
            )
            write_json(metadata_path, metadata)
        except (HarnessError, OSError) as exc:
            result.errors.append(f"状态恢复失败：{exc}")
            return result

        result.data.update(
            {
                "task_id": normalized,
                "task_status": task_status,
                "invalid_state": invalid_reason is not None,
                "recovery_record": display_path(metadata_path),
                "snapshot": display_path(snapshot_path) if snapshot_path.is_file() else None,
                "summary": "active-task.json 已通过受控恢复流程清除并保留本地审计记录。",
            }
        )
        return result

    def production_environment_hits(self) -> list[str]:
        hits: list[str] = []
        markers = self.config.get("execution", {}).get("production_environment_markers", {})
        if isinstance(markers, dict):
            for key, values in markers.items():
                current = os.environ.get(str(key), "").strip().casefold()
                expected = {str(item).casefold() for item in values} if isinstance(values, list) else set()
                if current and current in expected:
                    hits.append(str(key))
        return hits

    def test_environment(self) -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not SENSITIVE_ENV_NAME_RE.search(key)
        }
        markers = self.config.get("execution", {}).get("production_environment_markers", {})
        if isinstance(markers, dict):
            for key in markers:
                environment.pop(str(key), None)
        environment.update(
            {
                "APP_ENV": "test",
                "ENVIRONMENT": "test",
                "SHOPXO_ENV": "test",
                "HTTP_PROXY": "http://127.0.0.1:9",
                "HTTPS_PROXY": "http://127.0.0.1:9",
                "ALL_PROXY": "http://127.0.0.1:9",
                "NO_PROXY": "127.0.0.1,localhost,::1",
                "COMPOSER_DISABLE_NETWORK": "1",
                "PIP_NO_INDEX": "1",
                "npm_config_offline": "true",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        return environment

    def approval_is_valid(self, approval: Any, reviewer: str) -> bool:
        if not isinstance(approval, dict) or approval.get("status") != "approved":
            return False
        approved_by = str(approval.get("approved_by", "")).strip()
        approved_at = str(approval.get("approved_at", "")).strip()
        return bool(approved_by and approved_at and reviewer and approved_by.casefold() == reviewer.casefold())

    def preflight(self, task_id: str) -> GateResult:
        normalized = self.validate_task_id(task_id)
        try:
            with self.workflow_lock(normalized):
                with self.active_state_lock():
                    return self._preflight_locked(normalized)
        except WorkflowLockError as exc:
            result = GateResult("preflight")
            result.errors.append(f"无法取得任务工作流锁：{exc}")
            return result

    def _preflight_locked(self, task_id: str) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("preflight")
        task_gate = self.task_check(normalized, block_open_decisions=True)
        if not task_gate.ok:
            result.merge(task_gate)
            return result
        plan_gate = self.plan_check(normalized)
        if not plan_gate.ok:
            result.merge(plan_gate)
            return result
        task = self.load_task(normalized)
        source_gate = self.source_baseline_check()
        if not source_gate.ok:
            result.merge(source_gate)
        source = source_gate.data.get("source", self.source_status())

        try:
            existing_state = self.read_active_state()
        except HarnessError as exc:
            result.errors.append(str(exc))
            existing_state = None
        if existing_state is not None:
            existing_task = str(existing_state.get("task_id", ""))
            if existing_task == normalized:
                result.errors.append(
                    "该任务已有 preflight active state，拒绝重写 scope_base_commit；"
                    "如需重新定基，先通过状态迁移返回 ready_for_analysis 并重新审批"
                )
            else:
                result.errors.append(
                    f"已有活动任务 {existing_task or '<invalid>'}，完成或取消后才能 preflight {normalized}"
                )

        configured_preflight = self.config.get("workflow", {}).get("preflight_statuses", [])
        allowed_statuses = {"approved_for_implementation"}
        if configured_preflight != ["approved_for_implementation"]:
            result.errors.append("workflow.preflight_statuses 必须固定为 approved_for_implementation")
        if task.get("status") not in allowed_statuses:
            result.errors.append(
                f"任务状态 {task.get('status')} 不允许 preflight；允许：{', '.join(sorted(allowed_statuses))}"
            )

        if not self.is_git_repository():
            result.errors.append("当前目录不是 Git 工作树")
        branch = self.branch()
        if not branch:
            result.errors.append("当前处于 detached HEAD 或无法识别分支")
        else:
            protected = self.config.get("git", {}).get("protected_branches", [])
            if path_matches(branch, protected):
                result.errors.append(f"禁止在保护分支实施任务：{branch}")
            patterns = [
                str(pattern).format(task_id=normalized)
                for pattern in self.config.get("git", {}).get("task_branch_patterns", [])
            ]
            if patterns and not path_matches(branch, patterns):
                result.errors.append(f"分支名必须包含任务编号并匹配项目规则：{branch}")

        head = self.head()
        if not head:
            result.errors.append("无法读取当前 Git commit")

        if self.config.get("git", {}).get("clean_worktree_preflight", True):
            dirty = self.repository_dirty_paths()
            if dirty:
                preview = ", ".join(dirty[:8])
                suffix = " ..." if len(dirty) > 8 else ""
                result.errors.append(
                    f"preflight 要求干净工作区，发现 {len(dirty)} 个路径：{preview}{suffix}"
                )

        current_tools = self.current_toolchain()
        for required_tool in ("python", "git"):
            if current_tools.get(required_tool, {}).get("status") != "confirmed":
                result.errors.append(f"preflight 必需工具不可用：{required_tool}")

        production_hits = self.production_environment_hits()
        if production_hits:
            result.errors.append(f"生产环境标记存在，Harness 拒绝执行：{', '.join(production_hits)}")
        execution_policy = self.config.get("execution", {})
        expected_execution = {
            "production_access": "task_scoped_explicit",
            "secret_access": "external_reference_only",
            "network_access": "task_scoped_explicit",
        }
        if not isinstance(execution_policy, dict):
            result.errors.append("Harness execution 策略无效")
        else:
            for key, expected in expected_execution.items():
                if execution_policy.get(key) != expected:
                    result.errors.append(f"Harness execution.{key} 未固定为 {expected}")

        risk = str(task.get("risk_level", ""))
        db_change = task.get("database_change", {})
        core_change = task.get("shopxo_core_change", {})
        reviewer = str(task.get("reviewer", "")).strip()
        approvals = task.get("manual_approvals", {})
        independent_risks = {
            str(item)
            for item in self.config.get("workflow", {}).get("independent_review_risks", [])
        }
        declared_plan = approvals.get("plan") if isinstance(approvals, dict) else None
        requires_plan_approval = (
            isinstance(declared_plan, dict) and declared_plan.get("required") is True
        ) or risk in independent_risks or (
            isinstance(db_change, dict) and bool(db_change.get("required"))
        ) or (isinstance(core_change, dict) and bool(core_change.get("required")))
        if requires_plan_approval:
            if not self.approval_is_valid(declared_plan, reviewer):
                result.errors.append("任务缺少由独立 reviewer 完成的必需计划审批")
        if isinstance(core_change, dict) and core_change.get("required"):
            result.errors.extend(self.core_change_registration_errors(normalized, task))

        if result.errors:
            result.data["summary"] = "preflight 未通过，active-task.json 未更新。"
            return result

        assert head is not None
        try:
            plan_hash = self.plan_artifacts_sha256(normalized)
            decision_hash = self.decision_context_sha256(task)
        except HarnessError as exc:
            result.errors.append(str(exc))
            result.data["summary"] = "preflight 未通过，active-task.json 未更新。"
            return result
        state = {
            "schema_version": 1,
            "task_id": normalized,
            "task_file": f".harness/tasks/{normalized}/task.json",
            "contract_sha256": immutable_contract_hash(task),
            "policy_sha256": policy_contract_hash(task),
            "plan_artifacts_sha256": plan_hash,
            "decision_context_sha256": decision_hash,
            "scope_base_commit": head,
            "git_branch": branch,
            "git_commit": head,
            "preflight_at": utc_now(),
            "source_paths": source,
        }
        try:
            ensure_repo_path_safe(self.root, self.state_file, label="active-task.json")
            write_json(self.state_file, state)
        except (OSError, HarnessError) as exc:
            result.errors.append(f"无法写入 active-task.json：{exc}")
            return result
        result.data.update(
            {
                "state_file": display_path(self.state_file),
                "contract_sha256": state["contract_sha256"],
                "scope_base_commit": head,
                "summary": "任务合同与计划已锁定，活动任务状态已原子写入。",
            }
        )
        return result

    # ---------- Git scope and fingerprints ----------

    def parse_name_status(self, payload: str, *, source: str) -> list[GitChange]:
        fields = payload.split("\x00")
        changes: list[GitChange] = []
        index = 0
        while index < len(fields):
            status = fields[index]
            index += 1
            if not status:
                continue
            code = status[0]
            needed = 2 if code in ("R", "C") else 1
            paths: list[str] = []
            for _ in range(needed):
                if index >= len(fields) or not fields[index]:
                    raise HarnessError(f"无法解析 git --name-status -z 输出，状态 {status}")
                raw_path = fields[index].replace("\\", "/")
                index += 1
                try:
                    paths.append(normalize_repo_path(raw_path, allow_glob=False))
                except ValueError as exc:
                    raise HarnessError(f"Git 返回仓库外或无效路径 {raw_path!r}：{exc}") from exc
            changes.append(GitChange(status=status, paths=tuple(paths), source=source))
        return changes

    def resolve_scope_base(
        self,
        task_id: str | None,
        task: dict[str, Any] | None,
        explicit_base: str | None,
        *,
        require_state: bool,
    ) -> tuple[str, GateResult]:
        result = GateResult("scope-base")
        if explicit_base:
            base = explicit_base.strip()
            if not self.git_object_exists(base):
                result.errors.append(f"显式 base ref 不是有效 commit：{base}")
                return base, result
            resolved = self.git_value("rev-parse", f"{base}^{{commit}}")
            base = resolved or base
            if not self.is_ancestor(base):
                result.errors.append(f"显式 base ref 不是当前 HEAD 的祖先：{base}")
            if task_id and task:
                state_gate = self.validate_active_state(task_id, task, required=False)
                if self.state_file.is_file() and not state_gate.ok:
                    result.merge(state_gate)
                elif not self.state_file.is_file() and os.environ.get("GITHUB_ACTIONS") != "true":
                    result.warnings.append("本地显式 base ref 未绑定 preflight state；结果仅用于诊断")
            result.data["base_source"] = "explicit"
            return base, result

        if task_id and task:
            state_gate = self.validate_active_state(task_id, task, required=require_state)
            if not state_gate.ok:
                result.merge(state_gate)
                return "HEAD", result
            state = self.read_active_state()
            if state and isinstance(state.get("scope_base_commit"), str):
                result.data["base_source"] = "preflight-state"
                return state["scope_base_commit"], result

        github_base = os.environ.get("GITHUB_BASE_SHA", "").strip()
        if github_base and self.git_object_exists(github_base):
            if not self.is_ancestor(github_base):
                result.errors.append("GITHUB_BASE_SHA 不是当前 HEAD 的祖先")
            result.data["base_source"] = "GITHUB_BASE_SHA"
            return github_base, result

        result.data["base_source"] = "HEAD-working-tree"
        return "HEAD", result

    def collect_changes(self, base: str) -> list[GitChange]:
        if not self.is_git_repository():
            raise HarnessError("当前目录不是 Git 工作树")
        diff = self.git(
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            "--find-copies",
            base,
            "--",
            check=True,
        )
        changes = self.parse_name_status(diff.stdout, source=f"git-diff:{base}")
        untracked = self.git("ls-files", "--others", "--exclude-standard", "-z", check=True)
        for raw_path in untracked.stdout.split("\x00"):
            if not raw_path:
                continue
            normalized = normalize_repo_path(raw_path.replace("\\", "/"), allow_glob=False)
            changes.append(GitChange(status="?", paths=(normalized,), source="untracked"))
        unique: dict[tuple[str, tuple[str, ...]], GitChange] = {}
        for change in changes:
            unique[(change.status, change.paths)] = change
        return sorted(unique.values(), key=lambda item: (item.paths[-1], item.status))

    def task_runtime_patterns(self, task_id: str) -> list[str]:
        normalized = self.validate_task_id(task_id)
        return [item.format(task_id=normalized) for item in TASK_RUNTIME_PATTERN_TEMPLATES]

    def workspace_fingerprint(
        self,
        task_id: str,
        base: str,
        changes: Sequence[GitChange] | None = None,
    ) -> str:
        normalized = self.validate_task_id(task_id)
        if changes is None:
            changes = self.collect_changes(base)
        mutable_patterns = (
            f".harness/tasks/{normalized}/task.json",
            f".harness/tasks/{normalized}/workflow-history.json",
            f".harness/tasks/{normalized}/evidence.md",
            f".harness/tasks/{normalized}/review.md",
            f".harness/tasks/{normalized}/release-note.md",
            *(
                f".harness/tasks/{normalized}/{name}"
                for name in APPROVAL_ARTIFACT_NAMES.values()
            ),
            f".harness/runs/{normalized}/**",
            f".harness/reports/{normalized}/**",
            ".harness/state/active-task.json",
        )
        records = sorted(
            {
                (
                    str(change.status),
                    tuple(
                        path
                        for path in change.paths
                        if not path_matches(path, mutable_patterns)
                    ),
                )
                for change in changes
            }
        )
        digest = hashlib.sha256()
        digest.update(f"base:{base}\n".encode())
        for status, relevant in records:
            if not relevant:
                continue
            digest.update(f"status:{status}\n".encode("utf-8"))
            for rel in relevant:
                digest.update(f"path:{rel}\n".encode("utf-8"))
                path = self.root / Path(*rel.split("/"))
                path_error = repo_path_safety_error(self.root, path)
                if path_error:
                    digest.update(
                        f"unsafe-path:{canonical_json_hash(path_error)}\n".encode()
                    )
                elif path.is_file():
                    file_digest = hashlib.sha256()
                    try:
                        with path.open("rb") as handle:
                            while True:
                                chunk = handle.read(1024 * 1024)
                                if not chunk:
                                    break
                                file_digest.update(chunk)
                    except OSError as exc:
                        digest.update(
                            (
                                "read-error:"
                                f"{type(exc).__name__}:{getattr(exc, 'errno', None)}\n"
                            ).encode("utf-8")
                        )
                    else:
                        digest.update(f"sha256:{file_digest.hexdigest()}\n".encode())
                else:
                    digest.update(b"missing\n")
        return digest.hexdigest()

    def scope_check(
        self,
        task_id: str | None,
        *,
        base_ref: str | None,
        bootstrap: bool,
        require_state: bool = True,
    ) -> GateResult:
        result = GateResult("scope-check")
        if bootstrap:
            if task_id:
                result.errors.append("--bootstrap 与 TASK_ID 不能同时使用")
                return result
            task = None
            normalized = None
        else:
            if not task_id:
                result.errors.append("业务 scope-check 必须提供 TASK_ID")
                return result
            normalized = self.validate_task_id(task_id)
            contract_gate = self.task_check(normalized, block_open_decisions=True)
            if not contract_gate.ok:
                result.merge(contract_gate)
                return result
            task = self.load_task(normalized)
            status_gate = self.workflow_status_gate(task, "scope_statuses", "scope-check")
            if not status_gate.ok:
                result.merge(status_gate)
                return result

        base, base_gate = self.resolve_scope_base(
            normalized, task, base_ref, require_state=require_state and not bootstrap
        )
        if not base_gate.ok:
            result.merge(base_gate)
            return result
        result.warnings.extend(base_gate.warnings)
        try:
            changes = self.collect_changes(base)
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result

        config_protected = [
            normalize_repo_path(str(item), allow_glob=True)
            for item in self.config.get("paths", {}).get("protected", [])
        ]
        if bootstrap:
            allowed = [
                normalize_repo_path(str(item), allow_glob=True)
                for item in self.config.get("paths", {}).get("bootstrap_allowed", [])
            ]
            forbidden = config_protected
        else:
            assert task is not None and normalized is not None
            allowed = [normalize_repo_path(str(item), allow_glob=True) for item in task.get("allowed_paths", [])]
            runtime_allowed = self.task_runtime_patterns(normalized)
            allowed.extend(runtime_allowed)
            forbidden = config_protected + [
                normalize_repo_path(str(item), allow_glob=True)
                for item in task.get("forbidden_paths", [])
            ]
            # task.json remains scope-visible for controlled status and
            # post-review approval updates. validate_active_state locks all
            # implementation fields and plan approval hashes.

        violations: list[dict[str, str]] = []
        all_paths: list[str] = []
        status_counts = {"tracked": 0, "untracked": 0, "deleted": 0, "renamed_or_copied": 0}
        for change in changes:
            all_paths.extend(change.paths)
            if change.status == "?":
                status_counts["untracked"] += 1
            else:
                status_counts["tracked"] += 1
            if change.status.startswith("D"):
                status_counts["deleted"] += 1
            if change.status.startswith(("R", "C")):
                status_counts["renamed_or_copied"] += 1
            for path in change.paths:
                candidate = self.root / Path(*path.split("/"))
                candidate_error = repo_path_safety_error(self.root, candidate)
                if candidate_error:
                    violations.append(
                        {
                            "path": path,
                            "status": change.status,
                            "reason": f"unsafe path/symlink: {candidate_error}",
                        }
                    )
                    continue
                harness_policy_violation = bool(
                    not bootstrap
                    and task is not None
                    and normalized is not None
                    and str(task.get("type", "")).casefold() != "harness"
                    and path_matches(path, HARNESS_POLICY_PATTERNS)
                    and not path_matches(path, runtime_allowed)
                )
                if harness_policy_violation:
                    violations.append(
                        {
                            "path": path,
                            "status": change.status,
                            "reason": "business task cannot modify Harness policy path",
                        }
                    )
                elif path_matches(path, forbidden):
                    violations.append(
                        {"path": path, "status": change.status, "reason": "protected/forbidden path"}
                    )
                elif not path_matches(path, allowed):
                    violations.append(
                        {"path": path, "status": change.status, "reason": "outside allowed_paths"}
                    )

        try:
            tracked_inventory = [
                normalize_repo_path(path, allow_glob=False)
                for path in self.git("ls-files", "-z", "--", check=True).stdout.split("\x00")
                if path
            ]
        except (HarnessError, ValueError) as exc:
            result.errors.append(f"无法检查全仓库路径大小写冲突：{exc}")
            tracked_inventory = []
        case_map: dict[str, set[str]] = {}
        for path in [*tracked_inventory, *all_paths]:
            case_map.setdefault(path.casefold(), set()).add(path)
        for variants in case_map.values():
            if len(variants) > 1:
                result.errors.append(
                    "发现仅大小写不同的路径，跨平台范围判断不可靠：" + ", ".join(sorted(variants))
                )
        for violation in violations:
            result.errors.append(
                f"{violation['status']} {violation['path']}：{violation['reason']}"
            )
        result.data.update(
            {
                "task_id": normalized,
                "bootstrap": bootstrap,
                "base_commit": base,
                "base_source": base_gate.data.get("base_source"),
                "changes": [change.as_dict() for change in changes],
                "status_counts": status_counts,
                "violations": violations,
                "summary": (
                    f"基准 {base[:12]}，变更 {len(changes)} 项；"
                    f"tracked={status_counts['tracked']} untracked={status_counts['untracked']} "
                    f"delete={status_counts['deleted']} rename/copy={status_counts['renamed_or_copied']}。"
                ),
            }
        )
        if normalized:
            result.data["workspace_fingerprint"] = self.workspace_fingerprint(normalized, base, changes)
        return result

    # ---------- Test execution and evidence ----------

    def create_run_directory(self, task_id: str, command: str) -> Path:
        task_runs = self.runs_dir / self.validate_task_id(task_id)
        ensure_repo_path_safe(self.root, task_runs, label="任务运行目录")
        directory = task_runs / run_id(command)
        ensure_repo_path_safe(self.root, directory, label="运行证据目录")
        directory.mkdir(parents=True, exist_ok=False)
        for child in ("test-results", "screenshots"):
            (directory / child).mkdir(parents=True, exist_ok=True)
        return directory

    def verification_contract_sha256(
        self,
        task_id: str,
        task: dict[str, Any],
    ) -> str:
        normalized = self.validate_task_id(task_id)
        return canonical_json_hash(
            {
                "task_id": normalized,
                "contract_sha256": immutable_contract_hash(task),
                "policy_sha256": policy_contract_hash(task),
                "plan_artifacts_sha256": self.plan_artifacts_sha256(normalized),
                "decision_context_sha256": self.decision_context_sha256(task),
            }
        )

    def control_plane_sha256(self) -> str:
        files: set[str] = set()
        excluded_prefixes = (
            ".harness/runs/",
            ".harness/reports/",
            ".harness/state/workflow-locks/",
            ".harness/state/workflow-transactions/",
        )

        def excluded(rel: str) -> bool:
            return any(rel.startswith(prefix) for prefix in excluded_prefixes)

        for pattern in HARNESS_POLICY_PATTERNS:
            if pattern.endswith("/**"):
                base_rel = pattern[:-3].rstrip("/")
                base = self.root / Path(*base_rel.split("/"))
                base_error = repo_path_safety_error(self.root, base)
                if base_error or path_is_link_like(base):
                    files.add(base_rel)
                    continue
                if not base.is_dir():
                    continue
                for current, dirnames, filenames in os.walk(
                    base, topdown=True, followlinks=False
                ):
                    current_path = Path(current)
                    safe_directories: list[str] = []
                    for name in dirnames:
                        path = current_path / name
                        rel = path.absolute().relative_to(
                            self.root.absolute()
                        ).as_posix()
                        prefix = rel + "/"
                        if excluded(prefix):
                            continue
                        if path_is_link_like(path):
                            files.add(rel)
                        else:
                            safe_directories.append(name)
                    dirnames[:] = safe_directories
                    for name in filenames:
                        path = current_path / name
                        rel = path.absolute().relative_to(
                            self.root.absolute()
                        ).as_posix()
                        if not excluded(rel):
                            files.add(rel)
                continue

            path = self.root / Path(*pattern.split("/"))
            if path.is_file() or path_is_link_like(path):
                files.add(pattern)
        facts: dict[str, dict[str, Any]] = {}
        for rel in sorted(files):
            path = self.root / Path(*rel.split("/"))
            path_error = repo_path_safety_error(self.root, path)
            if path_error:
                facts[rel] = {"kind": "unsafe", "error": path_error}
                continue
            try:
                payload = path.read_bytes()
            except OSError as exc:
                facts[rel] = {"kind": "read-error", "error": str(exc)}
            else:
                facts[rel] = {
                    "kind": "file",
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
        return canonical_json_hash(facts)

    def evidence_artifacts_sha256(self) -> str:
        """Fingerprint gate-relevant prior manifests without hashing raw logs."""

        facts: dict[str, dict[str, Any]] = {}
        for root, directory_suffix, filename in (
            (self.runs_dir, "-verify", "manifest.json"),
            (self.reports_dir, "-review-pack", "review-pack.json"),
        ):
            ensure_repo_path_safe(self.root, root, label="Harness 证据根目录")
            if not root.is_dir():
                continue
            for current, dirnames, filenames in os.walk(
                root, topdown=True, followlinks=False
            ):
                current_path = Path(current)
                safe_directories: list[str] = []
                for name in dirnames:
                    path = current_path / name
                    rel = path.absolute().relative_to(
                        self.root.absolute()
                    ).as_posix()
                    error = repo_path_safety_error(self.root, path)
                    if error:
                        facts[rel] = {"kind": "unsafe", "error": error}
                    else:
                        safe_directories.append(name)
                dirnames[:] = safe_directories
                if (
                    not current_path.name.endswith(directory_suffix)
                    or filename not in filenames
                ):
                    continue
                path = current_path / filename
                rel = path.absolute().relative_to(self.root.absolute()).as_posix()
                error = repo_path_safety_error(self.root, path)
                if error:
                    facts[rel] = {"kind": "unsafe", "error": error}
                    continue
                try:
                    payload = path.read_bytes()
                except OSError as exc:
                    facts[rel] = {"kind": "read-error", "error": str(exc)}
                else:
                    facts[rel] = {
                        "kind": "file",
                        "size": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
        return canonical_json_hash(facts)

    def executable_for_test(self, command: str, cwd: Path) -> str | None:
        if "/" not in command and "\\" not in command:
            return shutil.which(command)
        try:
            normalized = normalize_repo_path(command, allow_glob=False)
        except ValueError:
            return None
        lexical_candidate = cwd / Path(*normalized.split("/"))
        if repo_path_safety_error(self.root, lexical_candidate):
            return None
        candidate = lexical_candidate.resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError:
            return None
        return str(candidate) if candidate.is_file() else None

    def verify(
        self,
        task_id: str,
        *,
        base_ref: str | None,
        require_state: bool = True,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("verify")
        task_gate = self.task_check(normalized, block_open_decisions=True)
        if not task_gate.ok:
            result.merge(task_gate)
            return result
        task = self.load_task(normalized)
        status_gate = self.workflow_status_gate(task, "verify_statuses", "verify")
        if not status_gate.ok:
            result.merge(status_gate)
            return result
        if base_ref is None:
            state_gate = self.validate_active_state(normalized, task, required=require_state)
            if not state_gate.ok:
                result.merge(state_gate)
                return result
        elif self.state_file.is_file():
            state_gate = self.validate_active_state(normalized, task, required=False)
            if not state_gate.ok:
                result.merge(state_gate)
                return result
        elif os.environ.get("GITHUB_ACTIONS") != "true":
            result.errors.append("本地 verify 必须先 preflight；显式 --base-ref 仅供 GitHub Actions")
            return result

        base, base_gate = self.resolve_scope_base(
            normalized,
            task,
            base_ref,
            require_state=require_state,
        )
        if not base_gate.ok:
            result.merge(base_gate)
            return result
        try:
            changes = self.collect_changes(base)
            fingerprint = self.workspace_fingerprint(normalized, base, changes)
            verification_contract = self.verification_contract_sha256(
                normalized, task
            )
            control_plane_before = self.control_plane_sha256()
            run_dir = self.create_run_directory(normalized, "verify")
        except (HarnessError, OSError) as exc:
            result.errors.append(str(exc))
            return result

        started_at = utc_now()
        started_monotonic = time.monotonic()
        try:
            configured_output = int(
                self.config.get("execution", {}).get(
                    "max_captured_output_bytes", HARD_MAX_CAPTURED_OUTPUT_BYTES
                )
            )
        except (TypeError, ValueError):
            configured_output = HARD_MAX_CAPTURED_OUTPUT_BYTES
        try:
            configured_timeout = int(
                self.config.get("execution", {}).get(
                    "max_test_timeout_seconds", HARD_MAX_TEST_TIMEOUT_SECONDS
                )
            )
        except (TypeError, ValueError):
            configured_timeout = HARD_MAX_TEST_TIMEOUT_SECONDS
        max_output = max(1, min(configured_output, HARD_MAX_CAPTURED_OUTPUT_BYTES))
        max_timeout = max(1, min(configured_timeout, HARD_MAX_TEST_TIMEOUT_SECONDS))
        test_results: list[dict[str, Any]] = []
        combined_stdout: list[str] = []
        combined_stderr: list[str] = []
        command_log: list[str] = []
        integrity_errors: list[str] = []

        for test in task.get("required_tests", []):
            test_id = str(test["id"])
            declared_command = [str(item) for item in test["command"]]
            cwd_value = str(test.get("cwd", "."))
            timeout_seconds = min(int(test.get("timeout_seconds", 300)), max_timeout)
            test_started = utc_now()
            test_clock = time.monotonic()
            status = "blocked"
            exit_code: int | None = None
            stdout = ""
            stderr = ""
            blocker: str | None = None
            timed_out = False
            stdout_limit_exceeded = False
            stderr_limit_exceeded = False

            try:
                cwd = resolve_repo_path(self.root, cwd_value, must_exist=True)
                if not cwd.is_dir():
                    raise ValueError("cwd is not a directory")
            except ValueError as exc:
                cwd = self.root
                blocker = f"测试工作目录无效：{exc}"

            executable = None if blocker else self.executable_for_test(declared_command[0], cwd)
            if not blocker and not executable:
                blocker = f"缺失测试工具或可执行文件：{declared_command[0]}"
            if not blocker:
                actual_command = [executable or declared_command[0], *declared_command[1:]]
                command_log.append(f"{test_id}: {command_text(declared_command)}")
                try:
                    evidence_artifacts_before = self.evidence_artifacts_sha256()
                    (
                        exit_code,
                        raw_stdout,
                        raw_stderr,
                        timed_out,
                        stdout_limit_exceeded,
                        stderr_limit_exceeded,
                    ) = bounded_subprocess(
                        actual_command,
                        cwd=cwd,
                        timeout=timeout_seconds,
                        max_output_bytes=max_output,
                        environment=self.test_environment(),
                    )
                    evidence_artifacts_after = self.evidence_artifacts_sha256()
                    if evidence_artifacts_after != evidence_artifacts_before:
                        integrity_errors.append(
                            f"测试 {test_id} 修改了 Harness verify/review gate 证据目录"
                        )
                    stdout = raw_stdout.decode("utf-8", errors="replace")
                    stderr = raw_stderr.decode("utf-8", errors="replace")
                    if timed_out:
                        status = "failed"
                        blocker = f"测试超过 {timeout_seconds} 秒超时"
                    elif stdout_limit_exceeded or stderr_limit_exceeded:
                        status = "failed"
                        blocker = f"测试输出超过每流 {max_output} 字节限制"
                    else:
                        status = "passed" if exit_code == 0 else "failed"
                except FileNotFoundError:
                    blocker = f"缺失测试工具或可执行文件：{declared_command[0]}"
                    status = "blocked"
                except (HarnessError, OSError) as exc:
                    blocker = f"测试进程无法启动：{exc}"
                    status = "blocked"

            if blocker:
                stderr = f"{stderr}\n[HARNESS] {blocker}".strip()
            stdout = redact_text(stdout)
            stderr = redact_text(stderr)
            stdout, stdout_truncated_by_encoding = truncate_utf8(stdout, max_output)
            stderr, stderr_truncated_by_encoding = truncate_utf8(stderr, max_output)
            stdout_truncated = stdout_limit_exceeded or stdout_truncated_by_encoding
            stderr_truncated = stderr_limit_exceeded or stderr_truncated_by_encoding
            ended = utc_now()
            item = {
                "id": test_id,
                "description": str(test.get("description", "")),
                "command": declared_command,
                "shell": False,
                "cwd": cwd_value,
                "timeout_seconds": timeout_seconds,
                "started_at": test_started,
                "ended_at": ended,
                "duration_seconds": round(time.monotonic() - test_clock, 3),
                "status": status,
                "exit_code": exit_code,
                "blocked_reason": blocker if status == "blocked" else None,
                "timed_out": timed_out,
                "output_limit_exceeded": (
                    stdout_limit_exceeded or stderr_limit_exceeded
                ),
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "stdout_file": f"test-results/{test_id}.stdout.log",
                "stderr_file": f"test-results/{test_id}.stderr.log",
            }
            test_results.append(item)
            atomic_write_text(run_dir / item["stdout_file"], stdout)
            atomic_write_text(run_dir / item["stderr_file"], stderr)
            write_json(run_dir / "test-results" / f"{test_id}.json", item)
            combined_stdout.append(f"===== {test_id} ({status}) =====\n{stdout}")
            combined_stderr.append(f"===== {test_id} ({status}) =====\n{stderr}")

        try:
            post_test_changes = self.collect_changes(base)
            post_test_fingerprint = self.workspace_fingerprint(
                normalized, base, post_test_changes
            )
            control_plane_after = self.control_plane_sha256()
        except HarnessError as exc:
            post_test_fingerprint = None
            control_plane_after = None
            integrity_errors.append(f"测试后完整性检查失败：{exc}")
        else:
            if post_test_fingerprint != fingerprint:
                integrity_errors.append("required_tests 修改了业务工作区，verify 结果无效")
            if control_plane_after != control_plane_before:
                integrity_errors.append("required_tests 修改了 Harness/control-plane，verify 结果无效")

        all_passed = (
            bool(test_results)
            and all(item["status"] == "passed" for item in test_results)
            and not integrity_errors
        )
        ended_at = utc_now()
        manifest = {
            "schema_version": 1,
            "task_id": normalized,
            "command": "verify",
            "run_id": run_dir.name,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": round(time.monotonic() - started_monotonic, 3),
            "git_branch": self.branch(),
            "git_commit": self.head(),
            "scope_base_commit": base,
            "contract_sha256": immutable_contract_hash(task),
            "policy_sha256": policy_contract_hash(task),
            "verification_contract_sha256": verification_contract,
            "workspace_fingerprint": fingerprint,
            "post_test_workspace_fingerprint": post_test_fingerprint,
            "control_plane_sha256_before": control_plane_before,
            "control_plane_sha256_after": control_plane_after,
            "control_plane_intact": not integrity_errors,
            "success": all_passed,
            "exit_code": 0 if all_passed else 1,
            "tests": test_results,
            "evidence_path": display_path(run_dir),
        }
        try:
            write_json(run_dir / "manifest.json", manifest)
            atomic_write_text(run_dir / "command.log", "\n".join(command_log) + "\n")
            atomic_write_text(run_dir / "stdout.log", "\n\n".join(combined_stdout) + "\n")
            atomic_write_text(run_dir / "stderr.log", "\n\n".join(combined_stderr) + "\n")
            atomic_write_text(
                run_dir / "changed-files.txt",
                "\n".join(path for change in changes for path in change.paths) + "\n",
            )
            atomic_write_text(
                run_dir / "diff-summary.md",
                "# Verify workspace\n\n"
                f"- Base: `{base}`\n"
                f"- HEAD: `{self.head() or 'unknown'}`\n"
                f"- Fingerprint: `{fingerprint}`\n"
                f"- Changed records: {len(changes)}\n",
            )
            atomic_write_text(
                run_dir / "database-report.md",
                "# Database report\n\nVerify 未直接连接数据库；数据库验证只来自 task.required_tests 的真实命令。\n",
            )
            atomic_write_text(
                run_dir / "security-report.md",
                "# Security report\n\nVerify 输出已执行密钥脱敏；安全结论须由任务测试与 review-pack 提供。\n",
            )
            atomic_write_text(
                run_dir / "final-report.md",
                "# Verify result\n\n"
                f"- Task: `{normalized}`\n"
                f"- Success: `{str(all_passed).lower()}`\n"
                f"- Passed: {sum(1 for item in test_results if item['status'] == 'passed')}\n"
                f"- Failed: {sum(1 for item in test_results if item['status'] == 'failed')}\n"
                f"- Blocked: {sum(1 for item in test_results if item['status'] == 'blocked')}\n",
            )
        except OSError as exc:
            result.errors.append(f"写入 verify 证据失败：{exc}")
            return result

        for item in test_results:
            if item["status"] != "passed":
                reason = item.get("blocked_reason") or f"exit_code={item.get('exit_code')}"
                result.errors.append(f"测试 {item['id']} {item['status']}：{reason}")
        result.errors.extend(integrity_errors)
        result.data.update(
            {
                "run_dir": display_path(run_dir),
                "manifest": display_path(run_dir / "manifest.json"),
                "contract_sha256": manifest["contract_sha256"],
                "verification_contract_sha256": manifest[
                    "verification_contract_sha256"
                ],
                "workspace_fingerprint": fingerprint,
                "tests": test_results,
                "summary": (
                    f"执行 {len(test_results)} 个声明测试："
                    f"passed={sum(1 for item in test_results if item['status'] == 'passed')} "
                    f"failed={sum(1 for item in test_results if item['status'] == 'failed')} "
                    f"blocked={sum(1 for item in test_results if item['status'] == 'blocked')}。"
                ),
            }
        )
        return result

    def verify_manifests(self, task_id: str) -> list[Path]:
        directory = self.runs_dir / self.validate_task_id(task_id)
        ensure_repo_path_safe(self.root, directory, label="任务运行目录")
        if not directory.is_dir():
            return []
        manifests: list[Path] = []
        for run_directory in directory.iterdir():
            if not run_directory.name.endswith("-verify"):
                continue
            run_error = repo_path_safety_error(self.root, run_directory)
            if run_error:
                raise HarnessError(
                    f"发现不安全 verify 运行目录 {display_path(run_directory)}：{run_error}"
                )
            manifest = run_directory / "manifest.json"
            manifest_error = repo_path_safety_error(self.root, manifest)
            if manifest_error:
                raise HarnessError(
                    f"发现不安全 verify manifest {display_path(manifest)}：{manifest_error}"
                )
            if manifest.is_file():
                manifests.append(manifest)
        return sorted(manifests, key=lambda path: path.parent.name, reverse=True)

    def evidence_check(
        self,
        task_id: str,
        *,
        base_ref: str | None,
        require_state: bool = True,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("evidence-check")
        task_gate = self.task_check(normalized, block_open_decisions=True)
        if not task_gate.ok:
            result.merge(task_gate)
            return result
        task = self.load_task(normalized)
        status_gate = self.workflow_status_gate(task, "review_statuses", "evidence-check")
        if not status_gate.ok:
            result.merge(status_gate)
            return result
        if base_ref is None:
            state_gate = self.validate_active_state(normalized, task, required=require_state)
            if not state_gate.ok:
                result.merge(state_gate)
                return result
        elif self.state_file.is_file():
            state_gate = self.validate_active_state(normalized, task, required=False)
            if not state_gate.ok:
                result.merge(state_gate)
                return result

        try:
            manifests = self.verify_manifests(normalized)
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result
        if not manifests:
            result.errors.append("没有找到 verify manifest；未执行测试不能表述为通过")
            return result
        manifest_path = manifests[0]
        try:
            manifest = read_json(manifest_path)
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result
        if not isinstance(manifest, dict):
            result.errors.append("verify manifest 顶层不是 object")
            return result
        expected_contract = immutable_contract_hash(task)
        expected_policy = policy_contract_hash(task)
        try:
            expected_verification_contract = self.verification_contract_sha256(
                normalized, task
            )
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result
        if manifest.get("task_id") != normalized:
            result.errors.append("verify manifest task_id 不匹配")
        if manifest.get("contract_sha256") != expected_contract:
            result.errors.append("verify 证据属于旧的 immutable contract")
        if manifest.get("policy_sha256") != expected_policy:
            result.errors.append("verify 证据属于旧的执行策略")
        if (
            manifest.get("verification_contract_sha256")
            != expected_verification_contract
        ):
            result.errors.append("verify 证据属于旧的稳定验证合同")

        base = str(manifest.get("scope_base_commit", ""))
        if base_ref:
            resolved = self.git_value("rev-parse", f"{base_ref}^{{commit}}")
            if resolved and base != resolved:
                result.errors.append("verify manifest base 与本次显式 base ref 不同")
        if not base or not self.git_object_exists(base):
            result.errors.append("verify manifest scope_base_commit 无效")
        else:
            try:
                current_fingerprint = self.workspace_fingerprint(normalized, base)
            except HarnessError as exc:
                result.errors.append(str(exc))
                current_fingerprint = None
            if current_fingerprint and manifest.get("workspace_fingerprint") != current_fingerprint:
                result.errors.append("verify 后业务工作区发生变化，测试证据已过期")

        declared = {
            str(item["id"]): item
            for item in task.get("required_tests", [])
            if isinstance(item, dict) and "id" in item
        }
        recorded = {
            str(item.get("id")): item
            for item in manifest.get("tests", [])
            if isinstance(item, dict) and item.get("id")
        }
        missing = sorted(set(declared) - set(recorded))
        extra = sorted(set(recorded) - set(declared))
        if missing:
            result.errors.append(f"verify 缺少测试记录：{', '.join(missing)}")
        if extra:
            result.errors.append(f"verify 包含合同外测试记录：{', '.join(extra)}")
        for test_id, declared_test in declared.items():
            item = recorded.get(test_id)
            if not item:
                continue
            if item.get("command") != declared_test.get("command"):
                result.errors.append(f"测试 {test_id} 实际命令与合同 command 数组不一致")
            if item.get("shell") is not False:
                result.errors.append(f"测试 {test_id} 未证明 shell=False")
            if item.get("status") != "passed" or item.get("exit_code") != 0:
                result.errors.append(
                    f"测试 {test_id} 未通过：status={item.get('status')} exit_code={item.get('exit_code')}"
                )
            for key in ("stdout_file", "stderr_file"):
                rel = item.get(key)
                evidence_file = manifest_path.parent / str(rel or "")
                if (
                    not isinstance(rel, str)
                    or repo_path_safety_error(self.root, evidence_file) is not None
                    or not evidence_file.is_file()
                ):
                    result.errors.append(f"测试 {test_id} 缺少证据文件 {key}")
        if manifest.get("success") is not True or manifest.get("exit_code") != 0:
            result.errors.append("verify manifest 未声明真实成功")

        evidence_path = self.task_dir(normalized) / "evidence.md"
        result.errors.extend(
            self.markdown_check(
                evidence_path,
                required_headings=(
                    "## 验收标准映射",
                    "## 自动测试证据",
                    "## 手工与页面证据",
                    "## 已知限制",
                    "## 回滚证据",
                ),
                minimum_chars=450,
            )
        )
        evidence_text = ""
        if evidence_path.is_file() and not path_is_link_like(evidence_path):
            try:
                evidence_text = evidence_path.read_text(encoding="utf-8")
            except OSError:
                pass
        run_reference = display_path(manifest_path.parent)
        if not re.search(
            rf"(?im)^\s*VERIFY_CONTRACT_SHA256:\s*{re.escape(expected_verification_contract)}\s*$",
            evidence_text,
        ):
            result.errors.append(
                "evidence.md 未记录与当前任务一致的稳定标记 "
                f"VERIFY_CONTRACT_SHA256: {expected_verification_contract}"
            )
        for test_id, declared_test in declared.items():
            command = declared_test.get("command")
            command_json = (
                command_text([str(item) for item in command])
                if isinstance(command, list)
                else ""
            )
            if not re.search(
                rf"(?m)^\s*TEST_COMMAND:\s*{re.escape(test_id)}\s+{re.escape(command_json)}\s*$",
                evidence_text,
            ):
                result.errors.append(
                    f"evidence.md 未逐项记录 TEST_COMMAND: {test_id} <完整 argv JSON>"
                )
            if not re.search(
                rf"(?im)^\s*TEST_RESULT:\s*{re.escape(test_id)}\s+exit_code\s*[:=]\s*0\s*$",
                evidence_text,
            ):
                result.errors.append(
                    f"evidence.md 未逐项记录 TEST_RESULT: {test_id} exit_code=0"
                )
        for criterion in task.get("acceptance_criteria", []):
            if isinstance(criterion, dict):
                criterion_id = str(criterion.get("id", ""))
                if criterion_id and criterion_id not in evidence_text:
                    result.errors.append(f"evidence.md 未映射验收标准 {criterion_id}")
        result.data.update(
            {
                "manifest": display_path(manifest_path),
                "run_dir": run_reference,
                "verification_contract_sha256": expected_verification_contract,
                "summary": f"检查最新 verify 运行 {manifest_path.parent.name} 与人工 evidence.md。",
            }
        )
        return result

    # ---------- Review and release gates ----------

    def scan_changed_files(self, changes: Sequence[GitChange]) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        scanned: set[str] = set()
        binary_suffixes = {
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svgz",
            ".mp4", ".webm", ".mov", ".avi", ".mp3", ".wav", ".ogg",
            ".woff", ".woff2", ".ttf", ".otf", ".pdf", ".zip", ".gz",
        }
        for change in changes:
            for rel in change.paths:
                if rel in scanned:
                    continue
                scanned.add(rel)
                path = self.root / Path(*rel.split("/"))
                path_error = repo_path_safety_error(self.root, path)
                if path_error:
                    findings.append(
                        {
                            "severity": "error",
                            "kind": "unsafe-path-or-symlink",
                            "path": rel,
                            "line": 1,
                        }
                    )
                    continue
                if not path.is_file():
                    continue
                try:
                    if path.stat().st_size > 2 * 1024 * 1024:
                        severity = (
                            "warning" if path.suffix.casefold() in binary_suffixes else "error"
                        )
                        findings.append(
                            {
                                "severity": severity,
                                "kind": "large-file-not-secret-scanned",
                                "path": rel,
                                "line": 1,
                            }
                        )
                        skipped.append({"path": rel, "reason": "larger than 2 MiB"})
                        continue
                    raw = path.read_bytes()
                except OSError as exc:
                    skipped.append({"path": rel, "reason": f"read error: {exc}"})
                    findings.append(
                        {
                            "severity": "error",
                            "kind": "file-read-error",
                            "path": rel,
                            "line": 1,
                        }
                    )
                    continue
                if b"\x00" in raw[:8192]:
                    severity = (
                        "warning" if path.suffix.casefold() in binary_suffixes else "error"
                    )
                    findings.append(
                        {
                            "severity": severity,
                            "kind": "binary-file-not-secret-scanned",
                            "path": rel,
                            "line": 1,
                        }
                    )
                    skipped.append({"path": rel, "reason": "binary/NUL content"})
                    continue
                text = raw.decode("utf-8", errors="replace")
                lines = text.splitlines()
                for kind, pattern in SECRET_SCAN_PATTERNS:
                    for match in pattern.finditer(text):
                        line = text.count("\n", 0, match.start()) + 1
                        matched_text = match.group(0).casefold()
                        if any(
                            token in matched_text
                            for token in ("[redacted]", "placeholder", "changeme", "replace_me")
                        ):
                            continue
                        findings.append(
                            {"severity": "error", "kind": kind, "path": rel, "line": line}
                        )
                for kind, pattern in DEBUG_SCAN_PATTERNS:
                    for match in pattern.finditer(text):
                        line = text.count("\n", 0, match.start()) + 1
                        findings.append(
                            {"severity": "warning", "kind": kind, "path": rel, "line": line}
                        )
        return {
            "scanned_files": len(scanned),
            "findings": findings,
            "skipped": skipped,
        }

    def diff_stat(self, base: str) -> str:
        try:
            value = self.git("diff", "--stat", base, "--", check=True).stdout.strip()
        except HarnessError as exc:
            return f"无法生成 diff stat：{exc}"
        return value or "无 tracked diff；可能仅有未跟踪文件。"

    def review_pack(
        self,
        task_id: str,
        *,
        base_ref: str | None,
        require_state: bool = True,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("review-pack")
        task_gate = self.task_check(normalized, block_open_decisions=True)
        plan_gate = self.plan_check(normalized)
        scope_gate = self.scope_check(
            normalized,
            base_ref=base_ref,
            bootstrap=False,
            require_state=require_state,
        )
        evidence_gate = self.evidence_check(
            normalized,
            base_ref=base_ref,
            require_state=require_state,
        )
        for gate in (task_gate, plan_gate, scope_gate, evidence_gate):
            if not gate.ok:
                result.merge(gate)
            else:
                result.data[gate.name] = gate.as_dict()

        try:
            task = self.load_task(normalized)
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result
        status_gate = self.workflow_status_gate(task, "review_pack_statuses", "review-pack")
        if not status_gate.ok:
            result.merge(status_gate)
            return result
        changes = [
            GitChange(
                status=str(item.get("status", "")),
                paths=tuple(str(path) for path in item.get("paths", [])),
                source=str(item.get("source", "")),
            )
            for item in scope_gate.data.get("changes", [])
            if isinstance(item, dict)
        ]
        security = self.scan_changed_files(changes)
        for finding in security["findings"]:
            message = (
                f"安全扫描 {finding['kind']}：{finding['path']}:{finding['line']}"
            )
            if finding["severity"] == "error":
                result.errors.append(message)
            else:
                result.warnings.append(message)

        changed_paths = sorted(set(path for change in changes for path in change.paths))
        detected_dependency_files = sorted(
            path for path in changed_paths if is_dependency_manifest_path(path)
        )
        if detected_dependency_files and task.get("new_dependency_allowed") is not True:
            result.errors.append(
                "检测到依赖清单/锁文件变更但任务未授权 new_dependency_allowed："
                + ", ".join(detected_dependency_files)
            )

        db_change = task.get("database_change", {})
        detected_database_paths = sorted(
            path for path in changed_paths if path.casefold().endswith(".sql")
        )
        database_report = {
            "declared": bool(isinstance(db_change, dict) and db_change.get("required")),
            "detected_paths": detected_database_paths,
            "affected_tables": db_change.get("affected_tables", []) if isinstance(db_change, dict) else [],
            "migration_paths": db_change.get("migration_paths", []) if isinstance(db_change, dict) else [],
            "fresh_install_baseline_exception": db_change.get("fresh_install_baseline_exception", {}) if isinstance(db_change, dict) else {},
            "rollback_plan": db_change.get("rollback_plan", "") if isinstance(db_change, dict) else "",
            "verification": db_change.get("verification", "") if isinstance(db_change, dict) else "",
        }
        if detected_database_paths and not database_report["declared"]:
            result.errors.append(
                "检测到 SQL/迁移文件变更但任务未声明 database_change.required："
                + ", ".join(detected_database_paths)
            )
        if database_report["declared"]:
            for pattern in database_report["migration_paths"]:
                if not any(path_matches(path, [str(pattern)]) for path in changed_paths):
                    result.errors.append(f"声明的迁移路径未出现在变更中：{pattern}")
            uncovered_database_paths = [
                path
                for path in detected_database_paths
                if not any(
                    path_matches(path, [str(pattern)])
                    for pattern in database_report["migration_paths"]
                )
            ]
            if uncovered_database_paths:
                result.errors.append(
                    "SQL/迁移变更未被 database_change.migration_paths 覆盖："
                    + ", ".join(uncovered_database_paths)
                )
            baseline_changed = any(
                path.casefold() == "config/shopxo.sql"
                for path in detected_database_paths
            )
            forward_migrations = [
                path
                for path in detected_database_paths
                if path.casefold() != "config/shopxo.sql"
            ]
            baseline_exception = database_report[
                "fresh_install_baseline_exception"
            ]
            exception_requested = bool(
                isinstance(baseline_exception, dict)
                and baseline_exception.get("requested") is True
            )
            if baseline_changed and not forward_migrations and not exception_requested:
                result.errors.append(
                    "config/shopxo.sql 变更缺少版本化 forward migration；"
                    "全量安装 SQL 不能作为已有站点的唯一升级路径"
                )
            if exception_requested and (not baseline_changed or forward_migrations):
                result.errors.append(
                    "fresh_install_baseline_exception 与实际差异不一致；"
                    "该例外只允许 config/shopxo.sql 是唯一 SQL 变更"
                )

        core_change = task.get("shopxo_core_change", {})
        core_report = {
            "declared": bool(isinstance(core_change, dict) and core_change.get("required")),
            "paths": core_change.get("paths", []) if isinstance(core_change, dict) else [],
            "registration": core_change.get("registration", "") if isinstance(core_change, dict) else "",
        }
        known_core_patterns = (
            "app/service/**",
            "app/admin/controller/**",
            "app/index/controller/**",
            "config/shopxo.sql",
            "app/common.php",
            "app/middleware.php",
            "app/middleware/**",
            "app/BaseController.php",
            "app/ExceptionHandle.php",
            "app/Request.php",
            "app/event.php",
        )
        detected_core = sorted(path for path in changed_paths if path_matches(path, known_core_patterns))
        if detected_core and not core_report["declared"]:
            result.errors.append(
                "检测到 ShopXO 核心路径但任务未声明 core change：" + ", ".join(detected_core)
            )
        if core_report["declared"]:
            for pattern in core_report["paths"]:
                if not any(path_matches(path, [str(pattern)]) for path in detected_core):
                    result.warnings.append(f"核心声明路径未出现在本次差异：{pattern}")
            uncovered_core_paths = [
                path
                for path in detected_core
                if not any(
                    path_matches(path, [str(pattern)])
                    for pattern in core_report["paths"]
                )
            ]
            if uncovered_core_paths:
                result.errors.append(
                    "ShopXO 核心变更未被 shopxo_core_change.paths 覆盖："
                    + ", ".join(uncovered_core_paths)
                )

        base = str(scope_gate.data.get("base_commit") or base_ref or "HEAD")
        fingerprint = str(scope_gate.data.get("workspace_fingerprint") or "")
        report_dir = self.reports_dir / normalized / run_id("review-pack")
        try:
            ensure_repo_path_safe(self.root, report_dir, label="review pack 目录")
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result
        try:
            report_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            result.errors.append(f"无法创建 review pack 目录：{exc}")
            return result

        gate_payload = {
            gate.name: gate.as_dict()
            for gate in (task_gate, plan_gate, scope_gate, evidence_gate)
        }
        payload = {
            "schema_version": 1,
            "generated_at": utc_now(),
            "task_id": normalized,
            "contract_sha256": immutable_contract_hash(task),
            "policy_sha256": policy_contract_hash(task),
            "scope_base_commit": base,
            "git_commit": self.head(),
            "workspace_fingerprint": fingerprint,
            "ready_for_review": not result.errors,
            "gates": gate_payload,
            "changed_files": changed_paths,
            "database": database_report,
            "core_change": {**core_report, "detected_paths": detected_core},
            "security": security,
            "acceptance_criteria": task.get("acceptance_criteria", []),
            "acceptance_evidence_source": f".harness/tasks/{normalized}/evidence.md",
            "rollback": task.get("rollback", {}),
            "known_limitations_source": f".harness/tasks/{normalized}/evidence.md",
        }
        markdown_lines = [
            f"# {normalized} Review Pack",
            "",
            f"- Generated: `{payload['generated_at']}`",
            f"- Contract: `{payload['contract_sha256']}`",
            f"- Base: `{base}`",
            f"- HEAD: `{self.head() or 'unknown'}`",
            f"- Workspace fingerprint: `{fingerprint or 'unavailable'}`",
            f"- Ready: `{str(payload['ready_for_review']).lower()}`",
            "",
            "## Gates",
            "",
        ]
        for gate_name, gate_value in gate_payload.items():
            markdown_lines.append(f"- {gate_name}: `{'PASS' if gate_value['ok'] else 'FAIL'}`")
        markdown_lines.extend(["", "## Changed files", ""])
        markdown_lines.extend(f"- `{path}`" for path in changed_paths)
        if not changed_paths:
            markdown_lines.append("- 无")
        markdown_lines.extend(["", "## Diff stat", "", "```text", self.diff_stat(base), "```", ""])
        markdown_lines.extend(["## Database", "", f"```json\n{json.dumps(database_report, ensure_ascii=False, indent=2)}\n```", ""])
        markdown_lines.extend(["## Core change", "", f"```json\n{json.dumps(payload['core_change'], ensure_ascii=False, indent=2)}\n```", ""])
        markdown_lines.extend(["## Security", "", f"```json\n{json.dumps(security, ensure_ascii=False, indent=2)}\n```", ""])
        markdown_lines.extend(
            [
                "## Acceptance mapping",
                "",
                f"Evidence source: `{payload['acceptance_evidence_source']}`",
                "",
            ]
        )
        for criterion in task.get("acceptance_criteria", []):
            if isinstance(criterion, dict):
                markdown_lines.append(
                    f"- `{criterion.get('id')}`: {criterion.get('description')}"
                )
        markdown_lines.extend(["", "## Rollback", "", f"```json\n{json.dumps(task.get('rollback', {}), ensure_ascii=False, indent=2)}\n```", ""])
        if result.errors:
            markdown_lines.extend(["## Blocking findings", ""])
            markdown_lines.extend(f"- {item}" for item in result.errors)
            markdown_lines.append("")

        try:
            write_json(report_dir / "review-pack.json", payload)
            atomic_write_text(report_dir / "review-pack.md", "\n".join(markdown_lines))
            atomic_write_text(report_dir / "changed-files.txt", "\n".join(changed_paths) + "\n")
            atomic_write_text(report_dir / "diff-summary.md", f"# Diff stat\n\n```text\n{self.diff_stat(base)}\n```\n")
            atomic_write_text(
                report_dir / "database-report.md",
                "# Database report\n\n```json\n"
                + json.dumps(database_report, ensure_ascii=False, indent=2)
                + "\n```\n",
            )
            atomic_write_text(
                report_dir / "security-report.md",
                "# Security report\n\n```json\n"
                + json.dumps(security, ensure_ascii=False, indent=2)
                + "\n```\n",
            )
        except OSError as exc:
            result.errors.append(f"写入 review pack 失败：{exc}")
            return result
        result.data.update(
            {
                "report_dir": display_path(report_dir),
                "report_json": display_path(report_dir / "review-pack.json"),
                "report_markdown": display_path(report_dir / "review-pack.md"),
                "summary": (
                    f"审查包已生成；ready_for_review={str(payload['ready_for_review']).lower()}，"
                    f"changed_files={len(changed_paths)}。"
                ),
            }
        )
        return result

    def latest_review_pack(self, task_id: str) -> Path | None:
        directory = self.reports_dir / self.validate_task_id(task_id)
        ensure_repo_path_safe(self.root, directory, label="任务审查报告目录")
        if not directory.is_dir():
            return None
        values: list[Path] = []
        for report_directory in directory.iterdir():
            if not report_directory.name.endswith("-review-pack"):
                continue
            report_error = repo_path_safety_error(self.root, report_directory)
            if report_error:
                raise HarnessError(
                    f"发现不安全 review pack 目录 {display_path(report_directory)}：{report_error}"
                )
            report = report_directory / "review-pack.json"
            report_error = repo_path_safety_error(self.root, report)
            if report_error:
                raise HarnessError(
                    f"发现不安全 review-pack.json {display_path(report)}：{report_error}"
                )
            if report.is_file():
                values.append(report)
        values.sort(key=lambda path: path.parent.name, reverse=True)
        return values[0] if values else None

    def release_check(
        self,
        task_id: str,
        *,
        base_ref: str | None,
        require_state: bool = True,
        allow_pretransition: bool = False,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("release-check")
        task_gate = self.task_check(normalized, block_open_decisions=True)
        plan_gate = self.plan_check(normalized)
        scope_gate = self.scope_check(
            normalized,
            base_ref=base_ref,
            bootstrap=False,
            require_state=require_state,
        )
        evidence_gate = self.evidence_check(
            normalized,
            base_ref=base_ref,
            require_state=require_state,
        )
        for gate in (task_gate, plan_gate, scope_gate, evidence_gate):
            if not gate.ok:
                result.merge(gate)
        try:
            task = self.load_task(normalized)
        except HarnessError as exc:
            result.errors.append(str(exc))
            return result

        statuses = {"approved_for_merge", "closed"}
        if allow_pretransition:
            statuses.add("awaiting_review")
        if task.get("status") not in statuses:
            result.errors.append(
                f"任务状态 {task.get('status')} 未获合并/关闭授权；允许：{', '.join(sorted(statuses))}"
            )
        reviewer = str(task.get("reviewer", "")).strip()
        approvals = task.get("manual_approvals", {})
        merge_approval = approvals.get("merge") if isinstance(approvals, dict) else None
        if not self.approval_is_valid(merge_approval, reviewer):
            result.errors.append("缺少独立 reviewer 的合并审批")
        release_approval = approvals.get("release") if isinstance(approvals, dict) else None
        if isinstance(release_approval, dict) and release_approval.get("required"):
            release_approver = self.expected_approval_actor(task, "release")
            if not self.approval_is_valid(release_approval, release_approver):
                result.errors.append("L4/声明任务缺少独立 release_approver 的发布审批")

        review_path = self.task_dir(normalized) / "review.md"
        result.errors.extend(
            self.markdown_check(
                review_path,
                required_headings=("## 审查范围", "## 发现", "## 审查结论"),
                minimum_chars=300,
            )
        )
        review_text = ""
        if review_path.is_file() and not path_is_link_like(review_path):
            try:
                review_text = review_path.read_text(encoding="utf-8")
            except OSError:
                pass
        if not re.search(r"(?m)^\s*REVIEW_RESULT:\s*APPROVED\s*$", review_text):
            result.errors.append("review.md 未包含独立审查标记 REVIEW_RESULT: APPROVED")
        if reviewer and not re.search(
            rf"(?im)^\s*REVIEWER:\s*{re.escape(reviewer)}\s*$",
            review_text,
        ):
            result.errors.append("review.md 未使用 REVIEWER: <task reviewer> 记录独立审查身份")
        if not re.search(r"(?im)^\s*REVIEWED_AT:\s*\S.+$", review_text):
            result.errors.append("review.md 未记录 REVIEWED_AT")

        try:
            pack_path = self.latest_review_pack(normalized)
        except HarnessError as exc:
            result.errors.append(str(exc))
            pack_path = None
        if not pack_path:
            result.errors.append("缺少 review-pack；先运行 review-pack")
        else:
            try:
                pack = read_json(pack_path)
            except HarnessError as exc:
                result.errors.append(str(exc))
                pack = {}
            if not isinstance(pack, dict):
                result.errors.append("review-pack.json 顶层无效")
            else:
                if pack.get("ready_for_review") is not True:
                    result.errors.append("最新 review-pack 未通过全部自动门禁")
                if pack.get("contract_sha256") != immutable_contract_hash(task):
                    result.errors.append("最新 review-pack 属于旧合同")
                if pack.get("policy_sha256") != policy_contract_hash(task):
                    result.errors.append("最新 review-pack 属于旧执行策略")
                current_fingerprint = scope_gate.data.get("workspace_fingerprint")
                if current_fingerprint and pack.get("workspace_fingerprint") != current_fingerprint:
                    result.errors.append("review-pack 后业务差异发生变化")

        release_note = self.task_dir(normalized) / "release-note.md"
        result.errors.extend(
            self.markdown_check(
                release_note,
                required_headings=(
                    "## 变更摘要",
                    "## 发布前提",
                    "## 发布步骤",
                    "## 回滚触发与步骤",
                    "## 发布后验证",
                ),
                minimum_chars=450,
            )
        )
        result.data.update(
            {
                "task_id": normalized,
                "review_pack": display_path(pack_path) if pack_path else None,
                "summary": "release-check 只判断合并/发布准备度；远程动作由 L4 合同测试或受控发布步骤执行。",
            }
        )
        return result

    # ---------- Contracted remote execution ----------

    def release_seal(self, task_id: str) -> GateResult:
        normalized = self.validate_task_id(task_id)
        try:
            with self.workflow_lock(normalized):
                with self.active_state_lock():
                    return self._release_seal_locked(normalized)
        except WorkflowLockError as exc:
            result = GateResult("release-seal")
            result.errors.append(f"无法取得发布封印锁：{exc}")
            return result

    def _release_seal_locked(self, task_id: str) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("release-seal")
        release_gate = self.release_check(
            normalized,
            base_ref=None,
            require_state=True,
        )
        if not release_gate.ok:
            result.merge(release_gate)
            return result
        task = self.load_task(normalized)
        if task.get("risk_level") != "L4" or task.get("network_access_required") is not True:
            result.errors.append("release-seal 只允许已批准的 L4 网络 operations 任务")
            return result
        dirty = self.repository_dirty_paths()
        if dirty:
            result.errors.append(
                "release-seal 要求审批与状态事件已提交且工作区干净；发现："
                + ", ".join(dirty[:8])
            )
            return result
        head = self.head()
        if not head:
            result.errors.append("无法读取 release Git commit")
            return result
        try:
            state = self.read_active_state()
            if not isinstance(state, dict):
                raise HarnessError("缺少活动任务状态")
            upload_artifacts = RemoteExecutionBroker.release_upload_artifact_facts(
                normalized,
            )
            state["release_commit"] = head
            state["release_contract_sha256"] = immutable_contract_hash(task)
            state["release_policy_sha256"] = policy_contract_hash(task)
            state["release_sealed_at"] = utc_now()
            state["release_upload_artifacts"] = upload_artifacts
            write_json(self.state_file, state)
        except (HarnessError, OSError, RemoteBrokerError) as exc:
            result.errors.append(f"无法写入 release seal：{exc}")
            return result
        result.data.update(
            {
                "task_id": normalized,
                "release_commit": head,
                "release_upload_artifacts": upload_artifacts,
                "summary": (
                    f"发布封印已锁定 Git commit {head[:12]} 及 "
                    f"{len(upload_artifacts)} 个上传制品。"
                ),
            }
        )
        return result

    def remote_actions(self, task_id: str) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("remote-actions")
        task_gate = self.task_check(normalized, block_open_decisions=True)
        if not task_gate.ok:
            result.merge(task_gate)
            return result
        task = self.load_task(normalized)
        state_gate = self.validate_active_state(normalized, task, required=True)
        if not state_gate.ok:
            result.merge(state_gate)
            return result
        try:
            broker = RemoteExecutionBroker.from_repository(
                normalized,
            )
        except (HarnessError, RemoteBrokerError) as exc:
            result.errors.append(f"远程 broker 拒绝合同：{exc}")
            return result
        result.data.update(
            {
                "task_id": normalized,
                "read_only_actions": list(broker.action_ids(mode="read_only")),
                "mutating_actions": list(broker.action_ids(mode="mutating")),
                "summary": "只列出 active state 锁定动作，未建立网络连接。",
            }
        )
        return result

    def remote_execute(
        self,
        task_id: str,
        *,
        action_id: str,
        allow_mutating: bool,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        try:
            with self.workflow_lock(normalized):
                with self.active_state_lock():
                    return self._remote_execute_locked(
                        normalized,
                        action_id=action_id,
                        allow_mutating=allow_mutating,
                    )
        except WorkflowLockError as exc:
            result = GateResult("remote-exec")
            result.errors.append(f"无法取得远程执行锁：{exc}")
            return result

    def _remote_execute_locked(
        self,
        task_id: str,
        *,
        action_id: str,
        allow_mutating: bool,
    ) -> GateResult:
        normalized = self.validate_task_id(task_id)
        result = GateResult("remote-exec")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", action_id):
            result.errors.append("远程 action id 格式无效")
            return result
        task_gate = self.task_check(normalized, block_open_decisions=True)
        if not task_gate.ok:
            result.merge(task_gate)
            return result
        task = self.load_task(normalized)
        state_gate = self.validate_active_state(normalized, task, required=True)
        if not state_gate.ok:
            result.merge(state_gate)
            return result
        if allow_mutating:
            release_gate = self.release_check(
                normalized,
                base_ref=None,
                require_state=True,
            )
            if not release_gate.ok:
                result.merge(release_gate)
            dirty = self.repository_dirty_paths()
            if dirty:
                result.errors.append(
                    "远程变更要求审批后工作区完全干净；发现：" + ", ".join(dirty[:8])
                )
            try:
                sealed_state = self.read_active_state()
            except HarnessError as exc:
                result.errors.append(str(exc))
                sealed_state = None
            head = self.head()
            if (
                not isinstance(sealed_state, dict)
                or not head
                or sealed_state.get("release_commit") != head
                or sealed_state.get("release_contract_sha256")
                != immutable_contract_hash(task)
                or sealed_state.get("release_policy_sha256") != policy_contract_hash(task)
            ):
                result.errors.append(
                    "远程变更缺少与当前干净 Git HEAD/合同一致的 release-seal"
                )
            if result.errors:
                return result
        try:
            broker = RemoteExecutionBroker.from_repository(
                normalized,
            )
            run_directory = self.create_run_directory(normalized, f"remote-{action_id}")
            evidence = broker.execute(action_id, allow_mutating=allow_mutating)
            evidence_path = run_directory / "remote-evidence.json"
            manifest_path = run_directory / "manifest.json"
            ensure_repo_path_safe(self.root, evidence_path, label="远程证据")
            ensure_repo_path_safe(self.root, manifest_path, label="远程证据清单")
            write_json(evidence_path, evidence)
            manifest = {
                "schema_version": 1,
                "kind": "harness_remote_run",
                "task_id": normalized,
                "action_id": action_id,
                "action_sha256": evidence.get("action_sha256"),
                "contract_sha256": immutable_contract_hash(task),
                "policy_sha256": policy_contract_hash(task),
                "git_commit": self.head(),
                "git_branch": self.branch(),
                "success": evidence.get("success") is True,
                "failure_kind": evidence.get("failure_kind"),
                "evidence_file": "remote-evidence.json",
                "recorded_at": utc_now(),
            }
            write_json(manifest_path, manifest)
        except (HarnessError, OSError, RemoteBrokerError) as exc:
            result.errors.append(f"远程 broker 拒绝或无法记录执行：{exc}")
            return result

        result.data.update(
            {
                "task_id": normalized,
                "action_id": action_id,
                "run_directory": display_path(run_directory),
                "success": evidence.get("success") is True,
                "failure_kind": evidence.get("failure_kind"),
                "summary": (
                    f"远程动作 {action_id} 已执行并写入脱敏证据；"
                    f"exit_code={evidence.get('exit_code')}。"
                ),
            }
        )
        if evidence.get("success") is not True:
            result.errors.append(
                f"远程动作失败：{evidence.get('failure_kind') or 'unknown'}；已保留脱敏证据"
            )
        return result


def add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="以 JSON 输出检查结果")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="ShopXO 苗木项目级 Harness（Python 3.11+ 标准库，JSON 合同）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    project = subparsers.add_parser("project-check", help="检查项目级 Harness 文件与配置")
    add_json_flag(project)

    doctor = subparsers.add_parser("doctor", help="检查工具链、源码、工作区和环境")
    doctor.add_argument("--strict", action="store_true", help="将所有警告升级为失败")
    add_json_flag(doctor)

    baseline = subparsers.add_parser("baseline", help="生成四份只读事实基线")
    add_json_flag(baseline)

    source_check = subparsers.add_parser(
        "source-check",
        help="检查 ShopXO 必需源码、固定上游与可移植基线新鲜度",
    )
    add_json_flag(source_check)

    recover = subparsers.add_parser(
        "state-recover",
        help="在安全状态下受控清理损坏或遗留的 active-task.json",
    )
    recover.add_argument("task_id")
    recover.add_argument("--by", required=True, help="必须匹配任务 owner/reviewer/release_approver")
    recover.add_argument("--reason", required=True, help="记录至少 10 字符的具体恢复原因")
    recover.add_argument(
        "--allow-invalid-state",
        action="store_true",
        help="确认 active-task.json 已损坏、格式无效或为符号链接",
    )
    add_json_flag(recover)

    create = subparsers.add_parser("task-create", help="从项目模板创建 JSON 任务合同")
    create.add_argument("task_id")
    create.add_argument("--title", required=True)
    create.add_argument("--risk", choices=sorted(RISK_ORDER), default="L2")
    create.add_argument("--priority", choices=("P0", "P1", "P2"), default="P0")
    create.add_argument("--phase", type=int, choices=range(0, 7), default=0)
    create.add_argument("--requirement", action="append", default=[], help="可重复提供需求 ID")
    create.add_argument(
        "--type",
        choices=(
            "feature",
            "bug",
            "ui",
            "data",
            "security",
            "operations",
            "documentation",
            "refactor",
            "harness",
        ),
    )
    add_json_flag(create)

    transition = subparsers.add_parser("task-transition", help="按项目状态机更新任务状态并记录历史")
    transition.add_argument("task_id")
    transition.add_argument(
        "status",
        choices=tuple(status for status in TASK_STATUSES if status != "draft"),
    )
    transition.add_argument("--by", required=True, help="记录实际执行状态变更的人")
    transition.add_argument("--reason", default="", help="状态变更原因；blocked/cancelled/closed 必填")
    add_json_flag(transition)

    approval = subparsers.add_parser("task-approval", help="记录 plan/merge/release 独立审批结果")
    approval.add_argument("task_id")
    approval.add_argument("stage", choices=("plan", "merge", "release"))
    approval.add_argument("--status", choices=("approved", "rejected"), required=True)
    approval.add_argument(
        "--by",
        required=True,
        help="plan/merge 必须匹配 reviewer；release 必须匹配 release_approver",
    )
    approval.add_argument(
        "--agent-task",
        default="",
        help="Codex 审批必填，记录独立子代理 canonical task，例如 /root/plan_review",
    )
    approval.add_argument("--reason", default="", help="审批说明；rejected 必填")
    add_json_flag(approval)

    contract_hash = subparsers.add_parser("contract-hash", help="输出与项目 Hook 兼容的合同 SHA-256")
    contract_hash.add_argument("task_id")
    add_json_flag(contract_hash)

    remote_actions = subparsers.add_parser(
        "remote-actions",
        help="列出 active L4 合同锁定的远程动作，不建立网络连接",
    )
    remote_actions.add_argument("task_id")
    add_json_flag(remote_actions)

    release_seal = subparsers.add_parser(
        "release-seal",
        help="在 L4 审批提交后锁定干净 Git HEAD，供 mutating 远程动作校验",
    )
    release_seal.add_argument("task_id")
    add_json_flag(release_seal)

    remote_exec = subparsers.add_parser(
        "remote-exec",
        help="通过项目 broker 执行一个 active L4 合同锁定动作",
    )
    remote_exec.add_argument("task_id")
    remote_exec.add_argument("action_id")
    remote_exec.add_argument(
        "--allow-mutating",
        action="store_true",
        help="仅对已完成 release 审批且状态为 approved_for_merge 的 mutating 动作显式启用",
    )
    add_json_flag(remote_exec)

    for name, help_text in (
        ("task-check", "验证 JSON 合同、需求编号、决策、范围和审批声明"),
        ("plan-check", "验证需求摘录、影响分析、实施计划与测试计划"),
        ("preflight", "锁定合同并生成 active-task.json"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("task_id")
        add_json_flag(command)

    scope = subparsers.add_parser("scope-check", help="检查 tracked/untracked/delete/rename 是否越界")
    scope.add_argument("task_id", nargs="?")
    scope.add_argument("--base-ref", help="CI 显式基准 commit；本地默认使用 preflight base")
    scope.add_argument("--bootstrap", action="store_true", help="仅按 Harness bootstrap 路径检查")
    add_json_flag(scope)

    for name, help_text in (
        ("verify", "只运行 task.required_tests 中的 command argv 数组"),
        ("evidence-check", "检查真实测试证据、退出码、合同与工作区指纹"),
        ("review-pack", "生成差异、测试、数据库、核心、安全、验收与回滚审查包"),
        ("release-check", "检查独立合并/发布准备度；不直接执行远程动作"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("task_id")
        command.add_argument("--base-ref", help="CI 显式基准 commit；本地默认使用 preflight base")
        add_json_flag(command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        harness = Harness(ROOT)
        if args.command == "project-check":
            result = harness.project_check()
        elif args.command == "doctor":
            result = harness.doctor(strict=args.strict)
        elif args.command == "baseline":
            result = harness.baseline()
        elif args.command == "source-check":
            result = harness.source_baseline_check()
        elif args.command == "state-recover":
            result = harness.state_recover(
                args.task_id,
                actor=args.by,
                reason=args.reason,
                allow_invalid_state=args.allow_invalid_state,
            )
        elif args.command == "task-create":
            result = harness.task_create(
                args.task_id,
                title=args.title,
                risk=args.risk,
                priority=args.priority,
                phase=args.phase,
                requirements=args.requirement,
                task_type=args.type,
            )
        elif args.command == "task-transition":
            result = harness.task_transition(
                args.task_id,
                target_status=args.status,
                actor=args.by,
                reason=args.reason,
            )
        elif args.command == "task-approval":
            result = harness.task_approval(
                args.task_id,
                stage=args.stage,
                status=args.status,
                actor=args.by,
                reason=args.reason,
                agent_task=args.agent_task,
            )
        elif args.command == "contract-hash":
            gate = harness.task_check(args.task_id)
            if gate.ok:
                task = harness.load_task(args.task_id)
                gate.data.update(
                    {
                        "contract_sha256": immutable_contract_hash(task),
                        "policy_sha256": policy_contract_hash(task),
                        "summary": immutable_contract_hash(task),
                    }
                )
            result = gate
            result.name = "contract-hash"
        elif args.command == "remote-actions":
            result = harness.remote_actions(args.task_id)
        elif args.command == "release-seal":
            result = harness.release_seal(args.task_id)
        elif args.command == "remote-exec":
            result = harness.remote_execute(
                args.task_id,
                action_id=args.action_id,
                allow_mutating=args.allow_mutating,
            )
        elif args.command == "task-check":
            result = harness.task_check(args.task_id)
        elif args.command == "plan-check":
            result = harness.plan_check(args.task_id)
        elif args.command == "preflight":
            result = harness.preflight(args.task_id)
        elif args.command == "scope-check":
            result = harness.scope_check(
                args.task_id,
                base_ref=args.base_ref,
                bootstrap=args.bootstrap,
                require_state=args.base_ref is None,
            )
        elif args.command == "verify":
            result = harness.verify(
                args.task_id,
                base_ref=args.base_ref,
                require_state=args.base_ref is None,
            )
        elif args.command == "evidence-check":
            result = harness.evidence_check(
                args.task_id,
                base_ref=args.base_ref,
                require_state=args.base_ref is None,
            )
        elif args.command == "review-pack":
            result = harness.review_pack(
                args.task_id,
                base_ref=args.base_ref,
                require_state=args.base_ref is None,
            )
        elif args.command == "release-check":
            result = harness.release_check(
                args.task_id,
                base_ref=args.base_ref,
                require_state=args.base_ref is None,
            )
        else:  # pragma: no cover - argparse enforces this.
            parser.error(f"unknown command: {args.command}")
            return 2
        return print_gate(result, json_output=bool(getattr(args, "json", False)))
    except HarnessError as exc:
        if bool(getattr(args, "json", False)):
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"[FAIL] {args.command}\n  [ERROR] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("[FAIL] 用户中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

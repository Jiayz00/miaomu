#!/usr/bin/env python3
"""Fail-closed remote execution broker for the project Harness.

This module intentionally has no command-line interface.  Production callers
must use ``from_repository`` so the broker itself safely loads the fixed task
contract and active state, validates release/Git/artifact seals, resolves only
project-external ``user-ssh-file`` references, and turns exact action records
into bounded ``ssh``/``scp`` calls.

The private identity file is never opened by this module.  Only filesystem
metadata is inspected before its path is passed to the system OpenSSH client.
The public ``known_hosts`` file is read to pin the contracted host fingerprint.
"""

from __future__ import annotations

import base64
import binascii
import copy
import datetime as dt
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, BinaryIO, Mapping, Sequence
from urllib.parse import urlsplit
import uuid


HARD_MAX_TIMEOUT_SECONDS = 1800
HARD_MAX_OUTPUT_BYTES = 256 * 1024
HARD_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_ACTIONS = 64
MAX_ARGV_ITEMS = 96
MAX_ARGUMENT_LENGTH = 4096
MAX_KNOWN_HOSTS_BYTES = 1024 * 1024
MAX_CONTROL_JSON_BYTES = 4 * 1024 * 1024
LOCAL_GIT_OUTPUT_BYTES = 64 * 1024
MAX_TRACKED_HARNESS_BYTES = 4 * 1024 * 1024

_RELEASE_CHECK_LAUNCHER = (
    "import sys,types;"
    "stream=sys.stdin.buffer;"
    "remote_path=sys.argv[2];"
    "remote_size=int.from_bytes(stream.read(8),'big');"
    "remote_source=stream.read(remote_size);"
    "script_path=sys.argv[1];"
    "script_size=int.from_bytes(stream.read(8),'big');"
    "script_source=stream.read(script_size);"
    "arguments=sys.argv[3:];"
    "remote_module=types.ModuleType('harness_remote');"
    "remote_module.__file__=remote_path;"
    "remote_module.__package__=None;"
    "sys.modules['harness_remote']=remote_module;"
    "exec(compile(remote_source,remote_path,'exec'),remote_module.__dict__);"
    "launcher_token=object();"
    "remote_module._shopxo_verified_launcher_token=launcher_token;"
    "sys.argv=[script_path,*arguments];"
    "script_globals={'__name__':'__main__','__file__':script_path,"
    "'__package__':None,'__cached__':None,"
    "'_HARNESS_VERIFIED_REMOTE_CONTEXT':(launcher_token,remote_module)};"
    "exec(compile(script_source,script_path,'exec'),script_globals)"
)

TASK_ID_RE = re.compile(
    r"^NUR-(?:FEAT|BUG|UI|DATA|SEC|OPS|DOC|REFACTOR|HARNESS)-\d{3}$"
)
ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HOST_KEY_FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,31}$")
REFERENCE_RE = re.compile(r"^user-ssh-file:([A-Za-z0-9][A-Za-z0-9_.-]{0,127})$")
CODEX_AGENT_TASK_RE = re.compile(r"^/root(?:/[a-z0-9_]+)*$")

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
POLICY_EXTENSION_KEYS = (
    "new_dependency_allowed",
    "network_access_required",
    "remote_execution",
    "rollback",
)

# The contract must explicitly retain every one of these permanent denials.
REQUIRED_FORBIDDEN_ACTIONS = frozenset(
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

REMOTE_CONTRACT_KEYS = frozenset(
    {
        "authorization",
        "environment",
        "host",
        "port",
        "user",
        "host_key_fingerprint",
        "identity_reference",
        "known_hosts_reference",
        "deployment_root",
        "managed_roots",
        "allowed_actions",
        "forbidden_actions",
    }
)
AUTHORIZATION_KEYS = frozenset(
    {"mode", "thread_id", "authorized_at", "scope"}
)
SSH_ACTION_KEYS = frozenset(
    {"id", "transport", "mode", "timeout_seconds", "cwd", "argv"}
)
SCP_ACTION_KEYS = frozenset(
    {
        "id",
        "transport",
        "mode",
        "timeout_seconds",
        "direction",
        "source",
        "destination",
    }
)

ALLOWED_READ_ONLY_STATUSES = frozenset(
    {
        "approved_for_implementation",
        "implementing",
        "verifying",
        "awaiting_review",
        "approved_for_merge",
    }
)

PROTECTED_MANAGED_ROOTS = frozenset(
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

SHELL_TOKENS = frozenset(
    {
        "bash",
        "bash.exe",
        "cmd",
        "cmd.exe",
        "dash",
        "fish",
        "ksh",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "sh",
        "sh.exe",
        "zsh",
    }
)
NESTED_TRANSPORT_TOKENS = frozenset(
    {"nc", "ncat", "netcat", "scp", "sftp", "socat", "ssh", "sshpass"}
)
INLINE_INTERPRETERS = frozenset(
    {"node", "node.exe", "perl", "php", "python", "python.exe", "python3", "ruby"}
)

SENSITIVE_ARGUMENT_RE = re.compile(
    r"(?i)(?:"
    r"-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE\s+KEY-----|"
    r"\bBearer\s+[A-Za-z0-9._~+/=-]+|"
    r"(?:password|passwd|pwd|token|secret|api[_-]?key|private[_-]?key|"
    r"authorization|cookie|credential|database[_-]?url)\s*[:=]\s*\S+|"
    r"--(?:password|passwd|token|secret|api-key|authorization)(?:=|$)|"
    r"[a-z][a-z0-9+.-]*://[^\s/?#@]+@"
    r")"
)
SENSITIVE_REMOTE_PATH_RE = re.compile(
    r"(?i)(?:"
    r"(?:^|/)(?:\.ssh|\.gnupg)(?:/|$)|"
    r"(?:^|/)(?:id_rsa|id_ed25519|id_ecdsa|authorized_keys)(?:$|[./])|"
    r"(?:^|/)(?:shadow|gshadow)(?:$|[./])|"
    r"(?:^|/)\.env(?:$|[./])|"
    r"/proc/(?:self|\d+)/environ(?:$|/)"
    r")"
)

PRIVATE_KEY_OUTPUT_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
    r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.I,
)
BEARER_OUTPUT_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
ASSIGNMENT_OUTPUT_RE = re.compile(
    r"(?im)(\b(?:password|passwd|pwd|token|secret|api[_-]?key|"
    r"access[_-]?key|private[_-]?key|authorization|cookie|credential|"
    r"database[_-]?url)\b\s*[:=]\s*)([^\s,;]+)"
)
HEADER_OUTPUT_RE = re.compile(
    r"(?im)(\b(?:authorization|proxy-authorization|cookie|set-cookie)\b"
    r"\s*:\s*)([^\r\n]+)"
)
URL_USERINFO_OUTPUT_RE = re.compile(
    r"(?i)(\b[a-z][a-z0-9+.-]*://)[^\s/?#@]+@"
)
PHONE_OUTPUT_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

READ_ONLY_SIMPLE_COMMANDS = frozenset(
    {
        "cat",
        "df",
        "du",
        "free",
        "grep",
        "head",
        "id",
        "ls",
        "lscpu",
        "nproc",
        "ps",
        "pwd",
        "readlink",
        "realpath",
        "sha256sum",
        "stat",
        "tail",
        "true",
        "uname",
        "wc",
        "whoami",
    }
)

DOCKER_CONTAINER_INSPECT_FORMATS = frozenset(
    {
        "{{.Id}}",
        "{{.Image}}",
        "{{.Name}}",
        "{{.State.Status}}",
        "{{.HostConfig.NetworkMode}}",
        "{{json .Mounts}}",
        "{{json .NetworkSettings.Ports}}",
    }
)
DOCKER_IMAGE_INSPECT_FORMATS = frozenset(
    {
        "{{.Id}}",
        "{{json .RepoDigests}}",
        "{{.Architecture}}",
        "{{.Os}}",
    }
)
DOCKER_CONTAINER_LIST_FORMATS = frozenset(
    {
        "{{.ID}}",
        "{{.Names}}",
        "{{.Image}}",
        "{{.Status}}",
        "{{.Ports}}",
        "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}",
    }
)
DOCKER_IMAGE_LIST_FORMATS = frozenset(
    {
        "{{.ID}}",
        "{{.Repository}}",
        "{{.Tag}}",
        "{{.Digest}}",
        "{{.Size}}",
        "{{.ID}}|{{.Repository}}|{{.Tag}}|{{.Digest}}|{{.Size}}",
    }
)
DOCKER_CONTAINER_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
DOCKER_IMAGE_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,255}$")


class RemoteBrokerError(RuntimeError):
    """A stable, sanitized denial or local broker failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProcessOutcome:
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    stdout_bytes: int
    stderr_bytes: int
    timed_out: bool
    output_limited: bool
    duration_ms: int
    launch_error: str | None = None


@dataclass(frozen=True)
class ActionSpec:
    action_id: str
    transport: str
    mode: str
    timeout_seconds: int
    cwd: str | None = None
    argv: tuple[str, ...] = ()
    direction: str | None = None
    source: str | None = None
    destination: str | None = None



@dataclass
class _UploadStage:
    path: Path
    handle: BinaryIO
    repo_path: str
    size: int
    sha256: str

    def close_and_remove(self) -> None:
        path_matches_handle = False
        try:
            handle_stat = os.fstat(self.handle.fileno())
            path_stat = self.path.stat(follow_symlinks=False)
            path_matches_handle = os.path.samestat(handle_stat, path_stat)
        except (OSError, ValueError):
            path_matches_handle = False
        finally:
            self.handle.close()
        if not path_matches_handle:
            raise RemoteBrokerError(
                "artifact_cleanup_failed",
                "broker upload staging path changed before cleanup",
            )
        try:
            self.path.unlink()
        except FileNotFoundError as exc:
            raise RemoteBrokerError(
                "artifact_cleanup_failed",
                "broker upload staging file disappeared before cleanup",
            ) from exc
        except OSError as exc:
            raise RemoteBrokerError(
                "artifact_cleanup_failed",
                "broker upload staging file could not be removed",
            ) from exc


@dataclass
class _DownloadStage:
    directory: Path
    directory_stat: os.stat_result
    path: Path
    handle: BinaryIO
    destination: Path
    destination_linked: bool = False
    keep_destination: bool = False

    def close_and_remove(self) -> None:
        try:
            handle_stat = os.fstat(self.handle.fileno())
            stage_stat = self.path.stat(follow_symlinks=False)
            directory_stat = self.directory.stat(follow_symlinks=False)
        except (OSError, ValueError) as exc:
            self.handle.close()
            raise RemoteBrokerError(
                "artifact_cleanup_failed",
                "broker download staging identity changed before cleanup",
            ) from exc
        if (
            not os.path.samestat(handle_stat, stage_stat)
            or not os.path.samestat(self.directory_stat, directory_stat)
            or stat.S_ISLNK(stage_stat.st_mode)
            or _is_reparse_point(stage_stat)
            or not stat.S_ISREG(stage_stat.st_mode)
        ):
            self.handle.close()
            raise RemoteBrokerError(
                "artifact_cleanup_failed",
                "broker download staging path changed before cleanup",
            )

        if self.destination_linked:
            try:
                destination_stat = self.destination.stat(follow_symlinks=False)
            except OSError as exc:
                self.handle.close()
                raise RemoteBrokerError(
                    "artifact_cleanup_failed",
                    "download destination changed before staging cleanup",
                ) from exc
            if not os.path.samestat(handle_stat, destination_stat):
                self.handle.close()
                raise RemoteBrokerError(
                    "artifact_cleanup_failed",
                    "download destination identity changed before staging cleanup",
                )
            if not self.keep_destination:
                try:
                    self.destination.unlink()
                except OSError as exc:
                    self.handle.close()
                    raise RemoteBrokerError(
                        "artifact_cleanup_failed",
                        "failed download publication could not be removed",
                    ) from exc

        self.handle.close()
        try:
            self.path.unlink()
            self.directory.rmdir()
        except OSError as exc:
            raise RemoteBrokerError(
                "artifact_cleanup_failed",
                "broker download staging files could not be removed",
            ) from exc

        if self.keep_destination:
            try:
                final_stat = self.destination.stat(follow_symlinks=False)
            except OSError as exc:
                raise RemoteBrokerError(
                    "artifact_cleanup_failed",
                    "published download destination is unavailable",
                ) from exc
            if (
                stat.S_ISLNK(final_stat.st_mode)
                or _is_reparse_point(final_stat)
                or not stat.S_ISREG(final_stat.st_mode)
                or final_stat.st_nlink != 1
            ):
                raise RemoteBrokerError(
                    "artifact_cleanup_failed",
                    "published download destination did not retain a unique identity",
                )


def _canonical_json_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _immutable_contract(task: Mapping[str, Any]) -> dict[str, Any]:
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
            "merge": {"required": merge.get("required")}
            if isinstance(merge, dict)
            else merge,
            "release": {"required": release.get("required")}
            if isinstance(release, dict)
            else release,
        }
    else:
        value["manual_approvals"] = approvals
    return value


def _immutable_contract_hash(task: Mapping[str, Any]) -> str:
    return _canonical_json_hash(_immutable_contract(task))


def _policy_contract_hash(task: Mapping[str, Any]) -> str:
    value = _immutable_contract(task)
    value.update({key: task.get(key) for key in POLICY_EXTENSION_KEYS})
    return _canonical_json_hash(value)


def _json_clone(value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    try:
        cloned = json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise RemoteBrokerError("invalid_input", f"{label} must be JSON data") from exc
    if not isinstance(cloned, dict):
        raise RemoteBrokerError("invalid_input", f"{label} must be an object")
    return cloned


def _parse_rfc3339(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\r" in value or "\n" in value:
        raise RemoteBrokerError("invalid_contract", f"{label} must be RFC3339 text")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RemoteBrokerError("invalid_contract", f"{label} must be RFC3339 text") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RemoteBrokerError("invalid_contract", f"{label} must include a timezone")
    return value


def _clean_text(value: Any, *, label: str, min_length: int = 1, max_length: int = 4096) -> str:
    if not isinstance(value, str):
        raise RemoteBrokerError("invalid_contract", f"{label} must be text")
    if not (min_length <= len(value) <= max_length):
        raise RemoteBrokerError("invalid_contract", f"{label} length is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise RemoteBrokerError("invalid_contract", f"{label} contains control characters")
    return value


def _validate_host(value: Any) -> str:
    host = _clean_text(value, label="remote_execution.host", max_length=253)
    if host.startswith("-") or any(character in host for character in "/@[]"):
        raise RemoteBrokerError("invalid_contract", "remote host is not a literal target")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    labels = host.rstrip(".").split(".")
    label_re = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
    if not labels or any(not label_re.fullmatch(label) for label in labels):
        raise RemoteBrokerError("invalid_contract", "remote host is invalid")
    return host


def _normalize_remote_path(value: Any, *, label: str) -> str:
    path_text = _clean_text(value, label=label, max_length=1024)
    if not path_text.startswith("/"):
        raise RemoteBrokerError("invalid_contract", f"{label} must be absolute")
    path = PurePosixPath(path_text)
    if ".." in path.parts or "." in path.parts:
        raise RemoteBrokerError("invalid_contract", f"{label} contains parent/current traversal")
    normalized = str(path)
    if normalized != path_text.rstrip("/") and path_text != "/":
        raise RemoteBrokerError("invalid_contract", f"{label} must be normalized")
    return normalized


def _within_remote_roots(path_text: str, roots: Sequence[str]) -> bool:
    path = PurePosixPath(path_text)
    return any(path == PurePosixPath(root) or path.is_relative_to(PurePosixPath(root)) for root in roots)


def _basename_token(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].casefold()


def _validate_no_sensitive_arguments(argv: Sequence[str], *, label: str) -> None:
    for index, argument in enumerate(argv):
        if SENSITIVE_ARGUMENT_RE.search(argument):
            raise RemoteBrokerError(
                "sensitive_argument",
                f"{label}[{index}] contains a forbidden sensitive CLI pattern",
            )
        if SENSITIVE_REMOTE_PATH_RE.search(argument):
            raise RemoteBrokerError(
                "sensitive_path",
                f"{label}[{index}] references a forbidden sensitive path",
            )


def _validate_command_tokens(argv: Sequence[str], *, label: str) -> tuple[str, ...]:
    if not isinstance(argv, (list, tuple)) or not argv:
        raise RemoteBrokerError("invalid_contract", f"{label} must be a non-empty argv array")
    if len(argv) > MAX_ARGV_ITEMS:
        raise RemoteBrokerError("invalid_contract", f"{label} has too many arguments")
    normalized: list[str] = []
    for index, value in enumerate(argv):
        normalized.append(
            _clean_text(
                value,
                label=f"{label}[{index}]",
                min_length=1,
                max_length=MAX_ARGUMENT_LENGTH,
            )
        )
    tokens = tuple(normalized)
    basenames = [_basename_token(item) for item in tokens]
    if any(token in SHELL_TOKENS for token in basenames):
        raise RemoteBrokerError("shell_denied", f"{label} may not invoke a shell")
    if any(token in NESTED_TRANSPORT_TOKENS for token in basenames):
        raise RemoteBrokerError("transport_denied", f"{label} may not open a nested transport")
    executable = basenames[0]
    if executable in INLINE_INTERPRETERS and any(
        item in {"-c", "-e", "-r", "--eval"} for item in tokens[1:]
    ):
        raise RemoteBrokerError("inline_code_denied", f"{label} may not execute inline code")
    _validate_no_sensitive_arguments(tokens, label=label)
    _validate_no_destructive_system_action(tokens, label=label)
    return tokens


def _validate_no_destructive_system_action(argv: Sequence[str], *, label: str) -> None:
    executable = _basename_token(argv[0])
    lowered = tuple(item.casefold() for item in argv[1:])
    destructive_executables = {
        "fdisk",
        "halt",
        "init",
        "mkfs",
        "mkfs.ext2",
        "mkfs.ext3",
        "mkfs.ext4",
        "mkfs.xfs",
        "parted",
        "poweroff",
        "reboot",
        "sfdisk",
        "shutdown",
        "telinit",
        "wipefs",
    }
    if executable in destructive_executables:
        raise RemoteBrokerError(
            "destructive_action_denied", f"{label} invokes a system-destructive executable"
        )
    if executable == "dd" and any(
        item.startswith("of=/dev/") or item.startswith("if=/dev/") for item in lowered
    ):
        raise RemoteBrokerError(
            "destructive_action_denied", f"{label} may not copy raw device data"
        )

    catastrophic_targets = {
        "/",
        "/*",
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
        "$home",
        "${home}",
        "~",
    }
    if executable in {"rm", "rmdir", "chmod", "chown", "chgrp"}:
        operands = [item.rstrip("/").casefold() or "/" for item in argv[1:] if not item.startswith("-")]
        if any(item in catastrophic_targets for item in operands):
            raise RemoteBrokerError(
                "destructive_action_denied", f"{label} targets a protected system root"
            )
        if any(".." in PurePosixPath(item).parts for item in operands):
            raise RemoteBrokerError(
                "destructive_action_denied", f"{label} contains destructive path traversal"
            )

    if executable == "docker" and len(lowered) >= 2:
        if lowered[0] in {"builder", "container", "image", "network", "system", "volume"} and lowered[1] == "prune":
            raise RemoteBrokerError(
                "destructive_action_denied", f"{label} may not prune shared Docker state"
            )
    if executable == "systemctl" and lowered:
        if lowered[0] in {"emergency", "halt", "kexec", "poweroff", "reboot", "rescue"}:
            raise RemoteBrokerError(
                "destructive_action_denied", f"{label} may not change the host run state"
            )
        shared_units = {"containerd", "containerd.service", "docker", "docker.service", "networking", "networking.service", "ssh", "ssh.service", "sshd", "sshd.service"}
        if lowered[0] in {"disable", "mask", "restart", "stop"} and any(
            item in shared_units for item in lowered[1:]
        ):
            raise RemoteBrokerError(
                "destructive_action_denied", f"{label} may not disrupt shared host services"
            )


def _docker_format_value(
    arguments: Sequence[str], index: int, *, allow_short: bool, label: str
) -> tuple[str | None, int]:
    item = arguments[index]
    format_options = {"--format"}
    if allow_short:
        format_options.add("-f")
    if item in format_options:
        if index + 1 >= len(arguments):
            raise RemoteBrokerError(
                "mode_mismatch", f"{label} Docker format value is missing"
            )
        return arguments[index + 1], index + 2
    if item.startswith("--format="):
        return item.split("=", 1)[1], index + 1
    return None, index


def _validate_docker_inspect(
    arguments: Sequence[str],
    *,
    allowed_formats: frozenset[str],
    target_pattern: re.Pattern[str],
    label: str,
) -> None:
    selected_format: str | None = None
    targets: list[str] = []
    index = 0
    while index < len(arguments):
        format_value, next_index = _docker_format_value(
            arguments, index, allow_short=True, label=label
        )
        if next_index != index:
            if selected_format is not None or not format_value:
                raise RemoteBrokerError(
                    "mode_mismatch",
                    f"{label} Docker inspect requires one format",
                )
            selected_format = format_value
            index = next_index
            continue
        item = arguments[index]
        if item.startswith("-") or not target_pattern.fullmatch(item):
            raise RemoteBrokerError(
                "mode_mismatch", f"{label} Docker inspect target is invalid"
            )
        targets.append(item)
        index += 1
    if selected_format not in allowed_formats:
        raise RemoteBrokerError(
            "sensitive_output_denied",
            f"{label} Docker inspect format is outside the fixed safe fields",
        )
    if not targets or len(targets) > 16 or len(targets) != len(set(targets)):
        raise RemoteBrokerError(
            "mode_mismatch",
            f"{label} Docker inspect requires unique bounded targets",
        )


def _validate_docker_list(
    arguments: Sequence[str],
    *,
    allowed_formats: frozenset[str],
    allowed_flags: frozenset[str],
    label: str,
) -> None:
    selected_format: str | None = None
    seen_flags: set[str] = set()
    index = 0
    while index < len(arguments):
        format_value, next_index = _docker_format_value(
            arguments, index, allow_short=False, label=label
        )
        if next_index != index:
            if selected_format is not None or not format_value:
                raise RemoteBrokerError(
                    "mode_mismatch", f"{label} Docker list requires one format"
                )
            selected_format = format_value
            index = next_index
            continue
        item = arguments[index]
        if item not in allowed_flags:
            raise RemoteBrokerError(
                "mode_mismatch", f"{label} Docker list option is outside the allowlist"
            )
        canonical = "all" if item in {"-a", "--all"} else item
        if canonical in seen_flags:
            raise RemoteBrokerError(
                "mode_mismatch", f"{label} Docker list option is duplicated"
            )
        seen_flags.add(canonical)
        index += 1
    if selected_format not in allowed_formats:
        raise RemoteBrokerError(
            "sensitive_output_denied",
            f"{label} Docker list requires a fixed safe format",
        )


def _validate_read_only_docker_compose(
    arguments: Sequence[str], *, label: str
) -> None:
    index = 1
    project_seen = False
    while index < len(arguments):
        item = arguments[index]
        if item in {"-f", "--file"}:
            if index + 1 >= len(arguments) or arguments[index + 1].startswith("-"):
                raise RemoteBrokerError(
                    "mode_mismatch", f"{label} Compose file value is invalid"
                )
            index += 2
            continue
        if item.startswith("--file=") and item.split("=", 1)[1]:
            index += 1
            continue
        if item in {"-p", "--project-name"}:
            if project_seen or index + 1 >= len(arguments) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", arguments[index + 1]
            ):
                raise RemoteBrokerError(
                    "mode_mismatch", f"{label} Compose project name is invalid"
                )
            project_seen = True
            index += 2
            continue
        if item.startswith("--project-name="):
            project_name = item.split("=", 1)[1]
            if project_seen or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", project_name
            ):
                raise RemoteBrokerError(
                    "mode_mismatch", f"{label} Compose project name is invalid"
                )
            project_seen = True
            index += 1
            continue
        break
    if index >= len(arguments):
        raise RemoteBrokerError(
            "mode_mismatch", f"{label} Docker Compose action is incomplete"
        )
    subcommand = arguments[index]
    remainder = tuple(arguments[index + 1 :])
    if subcommand == "version" and not remainder:
        return
    if subcommand == "ps":
        if not remainder or len(remainder) != len(set(remainder)):
            raise RemoteBrokerError(
                "sensitive_output_denied",
                f"{label} Compose ps requires quiet ID output",
            )
        quiet_count = sum(item in {"-q", "--quiet"} for item in remainder)
        all_count = sum(item in {"-a", "--all"} for item in remainder)
        if (
            quiet_count == 1
            and all_count <= 1
            and all(item in {"-q", "--quiet", "-a", "--all"} for item in remainder)
        ):
            return
        raise RemoteBrokerError(
            "sensitive_output_denied",
            f"{label} Compose ps output is outside the fixed quiet grammar",
        )
    compose_config_flags = {
        "--hash",
        "--images",
        "--profiles",
        "--quiet",
        "--services",
        "--volumes",
    }
    if (
        subcommand == "config"
        and remainder
        and len(remainder) == len(set(remainder))
        and all(item in compose_config_flags for item in remainder)
    ):
        return
    raise RemoteBrokerError(
        "mode_mismatch", f"{label} Docker Compose action is not read-only"
    )


def _is_loopback_url_host(hostname: str) -> bool:
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _parse_loopback_resolve(
    value: str, *, expected_host: str, expected_port: int, label: str
) -> None:
    if "," in value:
        raise RemoteBrokerError(
            "mode_mismatch", f"{label} --resolve may contain only one address"
        )
    parts = value.split(":", 2)
    if len(parts) != 3:
        raise RemoteBrokerError(
            "mode_mismatch", f"{label} --resolve must be host:port:address"
        )
    resolve_host, resolve_port, resolve_address = parts
    if (
        not resolve_host
        or "*" in resolve_host
        or resolve_host.startswith(("+", "-"))
        or resolve_host.casefold() != expected_host.casefold()
    ):
        raise RemoteBrokerError(
            "mode_mismatch", f"{label} --resolve host must exactly match the URL"
        )
    if resolve_port != str(expected_port):
        raise RemoteBrokerError(
            "mode_mismatch", f"{label} --resolve port must exactly match the URL"
        )
    if resolve_address.startswith("[") and resolve_address.endswith("]"):
        resolve_address = resolve_address[1:-1]
    if resolve_address not in {"127.0.0.1", "::1"}:
        raise RemoteBrokerError(
            "mode_mismatch", f"{label} --resolve address must be exact loopback"
        )


def _validate_read_only_curl(arguments: Sequence[str], *, label: str) -> None:
    if not arguments or arguments[0] not in {"-q", "--disable"}:
        raise RemoteBrokerError(
            "mode_mismatch",
            f"{label} curl must begin with -q/--disable to ignore user curl config",
        )
    # This is deliberately a positive grammar.  Unknown curl switches are
    # rejected because curl regularly adds new options with write, proxy,
    # expansion, authentication, or multi-transfer behavior.
    flag_options = {
        "--fail",
        "--fail-with-body",
        "--head",
        "--http1.1",
        "--http2",
        "--include",
        "--show-error",
        "--silent",
    }
    short_flag_options = frozenset("fIsSi")
    noproxy_count = 0
    resolves: list[str] = []
    urls: list[str] = []
    requested_methods: list[str] = []
    index = 1
    while index < len(arguments):
        item = arguments[index]
        if item == "--noproxy":
            if index + 1 >= len(arguments) or arguments[index + 1] != "*":
                raise RemoteBrokerError(
                    "mode_mismatch", f"{label} curl requires --noproxy '*'"
                )
            noproxy_count += 1
            index += 2
            continue
        if item in flag_options:
            if item == "--head":
                requested_methods.append("HEAD")
            index += 1
            continue
        if item in {"-X", "--request"}:
            if index + 1 >= len(arguments):
                raise RemoteBrokerError(
                    "mode_mismatch", f"{label} curl request method is missing"
                )
            requested_methods.append(arguments[index + 1].upper())
            index += 2
            continue
        if item.startswith("-X") and item != "-X":
            requested_methods.append(item[2:].upper())
            index += 1
            continue
        if item.startswith("--request="):
            requested_methods.append(item.split("=", 1)[1].upper())
            index += 1
            continue
        if item == "--resolve":
            if index + 1 >= len(arguments):
                raise RemoteBrokerError(
                    "mode_mismatch", f"{label} --resolve is missing its value"
                )
            resolves.append(arguments[index + 1])
            index += 2
            continue
        if item.startswith("--resolve="):
            resolves.append(item.split("=", 1)[1])
            index += 1
            continue
        if item in {"--connect-timeout", "--max-time"}:
            if index + 1 >= len(arguments):
                raise RemoteBrokerError(
                    "mode_mismatch", f"{label} {item} is missing its value"
                )
            value = arguments[index + 1]
            try:
                seconds = float(value)
            except ValueError as exc:
                raise RemoteBrokerError(
                    "mode_mismatch", f"{label} {item} must be numeric"
                ) from exc
            maximum = 30.0 if item == "--connect-timeout" else 300.0
            if not 0 < seconds <= maximum or not re.fullmatch(r"\d+(?:\.\d+)?", value):
                raise RemoteBrokerError(
                    "mode_mismatch", f"{label} {item} exceeds its fixed bound"
                )
            index += 2
            continue
        if item.startswith("-") and not item.startswith("--"):
            flags = item[1:]
            if not flags or any(flag not in short_flag_options for flag in flags):
                raise RemoteBrokerError(
                    "mode_mismatch", f"{label} curl option is outside the allowlist"
                )
            if "I" in flags:
                requested_methods.append("HEAD")
            index += 1
            continue
        if item.startswith("--") or item.startswith("-"):
            raise RemoteBrokerError(
                "mode_mismatch", f"{label} curl option is outside the allowlist"
            )
        if re.match(r"(?i)^https?://", item):
            urls.append(item)
            index += 1
            continue
        raise RemoteBrokerError(
            "mode_mismatch", f"{label} curl contains an unexpected transfer operand"
        )

    if noproxy_count != 1:
        raise RemoteBrokerError(
            "mode_mismatch", f"{label} curl requires exactly one --noproxy '*'"
        )
    if any(method not in {"GET", "HEAD"} for method in requested_methods):
        raise RemoteBrokerError("mode_mismatch", f"{label} curl method is not read-only")
    if len(set(requested_methods)) > 1:
        raise RemoteBrokerError("mode_mismatch", f"{label} curl method options conflict")
    if len(urls) != 1:
        raise RemoteBrokerError(
            "mode_mismatch", f"{label} read-only curl requires exactly one URL"
        )
    raw_url = urls[0]
    if "\\" in raw_url or any(character.isspace() for character in raw_url):
        raise RemoteBrokerError("mode_mismatch", f"{label} URL syntax is invalid")
    try:
        parsed = urlsplit(raw_url)
        hostname = parsed.hostname
        explicit_port = parsed.port
    except ValueError as exc:
        raise RemoteBrokerError("mode_mismatch", f"{label} URL syntax is invalid") from exc
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or "{" in raw_url
        or "}" in raw_url
        or "[" in (parsed.path + parsed.query)
        or "]" in (parsed.path + parsed.query)
    ):
        raise RemoteBrokerError(
            "mode_mismatch", f"{label} URL must not contain userinfo or invalid authority"
        )

    if _is_loopback_url_host(hostname):
        if resolves:
            raise RemoteBrokerError(
                "mode_mismatch", f"{label} loopback URL must not add --resolve ambiguity"
            )
        return

    if parsed.scheme.casefold() != "https":
        raise RemoteBrokerError(
            "mode_mismatch", f"{label} non-loopback HTTP URL is forbidden"
        )
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise RemoteBrokerError(
            "mode_mismatch", f"{label} external HTTPS target must be a DNS hostname"
        )
    effective_port = explicit_port if explicit_port is not None else 443
    if effective_port != 443:
        raise RemoteBrokerError(
            "mode_mismatch", f"{label} external HTTPS target must use port 443"
        )
    if len(resolves) != 1:
        raise RemoteBrokerError(
            "mode_mismatch", f"{label} external HTTPS target requires one exact --resolve"
        )
    _parse_loopback_resolve(
        resolves[0],
        expected_host=hostname,
        expected_port=effective_port,
        label=label,
    )


def _validate_read_only_command(argv: Sequence[str], *, label: str) -> None:
    executable = _basename_token(argv[0])
    arguments = tuple(argv[1:])

    if executable in READ_ONLY_SIMPLE_COMMANDS:
        return

    if executable == "date":
        utc_seen = False
        format_seen = False
        for argument in arguments:
            if argument in {"-u", "--utc"} and not utc_seen:
                utc_seen = True
                continue
            if argument.startswith("+") and len(argument) > 1 and not format_seen:
                format_seen = True
                continue
            raise RemoteBrokerError(
                "mode_mismatch",
                f"{label} date action is outside the read-only grammar",
            )
        return

    if executable == "hostname":
        allowed = {
            "-a",
            "--alias",
            "-A",
            "--all-fqdns",
            "-d",
            "--domain",
            "-f",
            "--fqdn",
            "-i",
            "--ip-address",
            "-I",
            "--all-ip-addresses",
            "-s",
            "--short",
            "-y",
            "--yp",
        }
        if all(item in allowed for item in arguments):
            return
        raise RemoteBrokerError("mode_mismatch", f"{label} hostname action is not read-only")

    if executable == "systemctl":
        if arguments and arguments[0] in {
            "is-active",
            "is-enabled",
            "list-unit-files",
            "list-units",
            "show",
            "status",
        }:
            return
        raise RemoteBrokerError("mode_mismatch", f"{label} systemctl action is not read-only")

    if executable == "caddy":
        if arguments == ("version",):
            return
        if not arguments or arguments[0] not in {"adapt", "validate"}:
            raise RemoteBrokerError(
                "mode_mismatch", f"{label} caddy action is not read-only"
            )
        command = arguments[0]
        index = 1
        seen: set[str] = set()
        while index < len(arguments):
            option = arguments[index]
            if option in {"--config", "--adapter"}:
                if option in seen or index + 1 >= len(arguments):
                    raise RemoteBrokerError(
                        "mode_mismatch", f"{label} caddy option is invalid"
                    )
                value = arguments[index + 1]
                if value.startswith("-") or not value:
                    raise RemoteBrokerError(
                        "mode_mismatch", f"{label} caddy option value is invalid"
                    )
                seen.add(option)
                index += 2
                continue
            if command == "adapt" and option in {"--pretty", "--validate"}:
                if option in seen:
                    raise RemoteBrokerError(
                        "mode_mismatch", f"{label} caddy option is duplicated"
                    )
                seen.add(option)
                index += 1
                continue
            raise RemoteBrokerError(
                "mode_mismatch", f"{label} caddy option is outside the allowlist"
            )
        if "--config" not in seen:
            raise RemoteBrokerError(
                "mode_mismatch", f"{label} caddy action requires --config"
            )
        return

    if executable == "curl":
        _validate_read_only_curl(arguments, label=label)
        return

    if executable == "docker":
        if not arguments:
            raise RemoteBrokerError("mode_mismatch", f"{label} docker action is incomplete")
        command = arguments[0]
        if arguments == ("version",):
            return
        if command == "ps":
            _validate_docker_list(
                arguments[1:],
                allowed_formats=DOCKER_CONTAINER_LIST_FORMATS,
                allowed_flags=frozenset({"-a", "--all", "--no-trunc"}),
                label=label,
            )
            return
        if command == "images":
            _validate_docker_list(
                arguments[1:],
                allowed_formats=DOCKER_IMAGE_LIST_FORMATS,
                allowed_flags=frozenset(
                    {"-a", "--all", "--digests", "--no-trunc"}
                ),
                label=label,
            )
            return
        if command == "container" and len(arguments) >= 2:
            if arguments[1] == "inspect":
                _validate_docker_inspect(
                    arguments[2:],
                    allowed_formats=DOCKER_CONTAINER_INSPECT_FORMATS,
                    target_pattern=DOCKER_CONTAINER_TARGET_RE,
                    label=label,
                )
                return
            if arguments[1] == "ls":
                _validate_docker_list(
                    arguments[2:],
                    allowed_formats=DOCKER_CONTAINER_LIST_FORMATS,
                    allowed_flags=frozenset(
                        {"-a", "--all", "--no-trunc"}
                    ),
                    label=label,
                )
                return
        if command == "image" and len(arguments) >= 2:
            if arguments[1] == "inspect":
                _validate_docker_inspect(
                    arguments[2:],
                    allowed_formats=DOCKER_IMAGE_INSPECT_FORMATS,
                    target_pattern=DOCKER_IMAGE_TARGET_RE,
                    label=label,
                )
                return
            if arguments[1] == "ls":
                _validate_docker_list(
                    arguments[2:],
                    allowed_formats=DOCKER_IMAGE_LIST_FORMATS,
                    allowed_flags=frozenset(
                        {"-a", "--all", "--digests", "--no-trunc"}
                    ),
                    label=label,
                )
                return
        if command == "compose":
            _validate_read_only_docker_compose(arguments, label=label)
            return
        raise RemoteBrokerError("mode_mismatch", f"{label} docker action is not read-only")

    raise RemoteBrokerError(
        "mode_mismatch",
        f"{label} executable is not in the conservative read-only catalog",
    )


def _is_reparse_point(path_stat: os.stat_result) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & flag)


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


def _open_ssh_path(path: Path) -> str:
    return path.as_posix() if os.name == "nt" else str(path)


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_repository_root(value: Path) -> Path:
    lexical = Path(value)
    if not lexical.is_absolute():
        raise RemoteBrokerError(
            "unsafe_local_path", "repository root must be an absolute path"
        )
    try:
        root_stat = lexical.lstat()
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise RemoteBrokerError(
            "unsafe_local_path", "repository root is unavailable"
        ) from exc
    if stat.S_ISLNK(root_stat.st_mode) or _is_reparse_point(root_stat):
        raise RemoteBrokerError(
            "unsafe_local_path", "repository root may not be a symlink/reparse point"
        )
    if not stat.S_ISDIR(root_stat.st_mode) or not _same_path(lexical, resolved):
        raise RemoteBrokerError(
            "unsafe_local_path", "repository root must be a direct directory"
        )
    return resolved


def _project_repository_root() -> Path:
    module_path = Path(os.path.abspath(__file__))
    if len(module_path.parents) < 2:
        raise RemoteBrokerError(
            "unsafe_local_path", "broker module has no fixed project root"
        )
    root = _safe_repository_root(module_path.parents[1])
    expected_module = _safe_repository_entry(
        root,
        "scripts/harness_remote.py",
        label="remote broker module",
        expect_file=True,
    )
    if not _same_path(module_path, expected_module):
        raise RemoteBrokerError(
            "unsafe_local_path", "broker module is outside its fixed project root"
        )
    return root


def _safe_repository_entry(
    root: Path,
    relative_path: str,
    *,
    label: str,
    expect_file: bool,
) -> Path:
    pure = PurePosixPath(relative_path)
    if (
        not relative_path
        or relative_path.startswith("/")
        or not pure.parts
        or pure.as_posix() != relative_path
        or ".." in pure.parts
        or "." in pure.parts
    ):
        raise RemoteBrokerError(
            "unsafe_local_path", f"{label} must be a normalized repository path"
        )
    current = root
    for index, part in enumerate(pure.parts):
        current = current / part
        try:
            entry_stat = current.lstat()
        except OSError as exc:
            raise RemoteBrokerError(
                "unsafe_local_path", f"{label} is unavailable"
            ) from exc
        if stat.S_ISLNK(entry_stat.st_mode) or _is_reparse_point(entry_stat):
            raise RemoteBrokerError(
                "unsafe_local_path", f"{label} may not traverse a symlink/reparse point"
            )
        is_last = index == len(pure.parts) - 1
        if is_last and expect_file:
            if not stat.S_ISREG(entry_stat.st_mode):
                raise RemoteBrokerError(
                    "unsafe_local_path", f"{label} must be a regular file"
                )
        elif not stat.S_ISDIR(entry_stat.st_mode):
            raise RemoteBrokerError(
                "unsafe_local_path", f"{label} parent must be a directory"
            )
        try:
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise RemoteBrokerError(
                "unsafe_local_path", f"{label} cannot be resolved"
            ) from exc
        if not _same_path(resolved, current.absolute()) or not _path_within(
            resolved, root
        ):
            raise RemoteBrokerError(
                "unsafe_local_path", f"{label} redirects outside its fixed path"
            )
    return current


def _read_repository_json(root: Path, relative_path: str, *, label: str) -> dict[str, Any]:
    path = _safe_repository_entry(
        root, relative_path, label=label, expect_file=True
    )
    before = path.lstat()
    if before.st_size <= 0 or before.st_size > MAX_CONTROL_JSON_BYTES:
        raise RemoteBrokerError("invalid_input", f"{label} size is invalid")
    open_flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, open_flags)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            opened = os.fstat(handle.fileno())
            if not os.path.samestat(before, opened):
                raise RemoteBrokerError(
                    "invalid_input", f"{label} was replaced before it was read"
                )
            payload = handle.read(MAX_CONTROL_JSON_BYTES + 1)
            handle_after = os.fstat(handle.fileno())
        after = path.lstat()
    except RemoteBrokerError:
        raise
    except OSError as exc:
        raise RemoteBrokerError("invalid_input", f"{label} cannot be read") from exc
    before_facts = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    after_facts = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    handle_facts = (
        handle_after.st_dev,
        handle_after.st_ino,
        handle_after.st_size,
        handle_after.st_mtime_ns,
    )
    if (
        before_facts != after_facts
        or before_facts != handle_facts
        or not os.path.samestat(handle_after, after)
        or len(payload) != before.st_size
    ):
        raise RemoteBrokerError("invalid_input", f"{label} changed while being read")
    try:
        value = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RemoteBrokerError("invalid_input", f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise RemoteBrokerError("invalid_input", f"{label} must contain an object")
    return value


def _run_artifact_repo_path(
    root: Path,
    task_id: str,
    value: Any,
    *,
    label: str,
    require_file: bool,
) -> tuple[str, Path]:
    if not isinstance(value, str):
        raise RemoteBrokerError("unsafe_local_path", f"{label} must be text")
    pure = PurePosixPath(value)
    prefix = f".harness/runs/{task_id}/"
    if (
        not value.startswith(prefix)
        or value == prefix
        or pure.as_posix() != value
        or ".." in pure.parts
        or "." in pure.parts
    ):
        raise RemoteBrokerError(
            "unsafe_local_path", f"{label} must stay in {prefix}**"
        )
    if require_file:
        path = _safe_repository_entry(root, value, label=label, expect_file=True)
    else:
        parent_text = PurePosixPath(value).parent.as_posix()
        _safe_repository_entry(root, parent_text, label=f"{label} parent", expect_file=False)
        path = root.joinpath(*pure.parts)
        if path.exists():
            _safe_repository_entry(root, value, label=label, expect_file=True)
    return value, path


def _sha256_regular_file(path: Path, *, label: str) -> tuple[int, str]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise RemoteBrokerError("unsafe_local_path", f"{label} is unavailable") from exc
    if stat.S_ISLNK(before.st_mode) or _is_reparse_point(before):
        raise RemoteBrokerError(
            "unsafe_local_path", f"{label} may not be a symlink/reparse point"
        )
    if not stat.S_ISREG(before.st_mode):
        raise RemoteBrokerError("unsafe_local_path", f"{label} must be a regular file")
    open_flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    digest = hashlib.sha256()
    bytes_read = 0
    try:
        descriptor = os.open(path, open_flags)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            opened = os.fstat(handle.fileno())
            if not os.path.samestat(before, opened):
                raise RemoteBrokerError(
                    "artifact_drift", f"{label} was replaced before hashing"
                )
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                bytes_read += len(chunk)
            handle_after = os.fstat(handle.fileno())
        after = path.lstat()
    except RemoteBrokerError:
        raise
    except OSError as exc:
        raise RemoteBrokerError("unsafe_local_path", f"{label} cannot be hashed") from exc
    before_facts = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    after_facts = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    handle_facts = (
        handle_after.st_dev,
        handle_after.st_ino,
        handle_after.st_size,
        handle_after.st_mtime_ns,
    )
    if (
        before_facts != after_facts
        or before_facts != handle_facts
        or not os.path.samestat(handle_after, after)
        or bytes_read != before.st_size
    ):
        raise RemoteBrokerError(
            "artifact_drift", f"{label} changed while its release hash was computed"
        )
    return before.st_size, digest.hexdigest()


def _read_stable_regular_bytes(
    path: Path, *, label: str, maximum_bytes: int, allow_empty: bool = False
) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise RemoteBrokerError(
            "release_check_invalid", f"{label} is unavailable"
        ) from exc
    if stat.S_ISLNK(before.st_mode) or _is_reparse_point(before):
        raise RemoteBrokerError(
            "release_check_invalid", f"{label} may not redirect"
        )
    minimum_size = 0 if allow_empty else 1
    if (
        not stat.S_ISREG(before.st_mode)
        or not minimum_size <= before.st_size <= maximum_bytes
    ):
        raise RemoteBrokerError(
            "release_check_invalid", f"{label} size or file type is invalid"
        )
    open_flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, open_flags)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            opened = os.fstat(handle.fileno())
            if not os.path.samestat(before, opened):
                raise RemoteBrokerError(
                    "release_check_invalid", f"{label} was replaced before reading"
                )
            payload = handle.read(maximum_bytes + 1)
            handle_after = os.fstat(handle.fileno())
        after = path.lstat()
    except RemoteBrokerError:
        raise
    except OSError as exc:
        raise RemoteBrokerError(
            "release_check_invalid", f"{label} cannot be read safely"
        ) from exc
    before_facts = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    handle_facts = (
        handle_after.st_dev,
        handle_after.st_ino,
        handle_after.st_size,
        handle_after.st_mtime_ns,
    )
    after_facts = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if (
        len(payload) != before.st_size
        or before_facts != handle_facts
        or before_facts != after_facts
        or not os.path.samestat(handle_after, after)
    ):
        raise RemoteBrokerError(
            "release_check_invalid", f"{label} changed while being read"
        )
    return payload


def _windows_directory() -> Path:
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetWindowsDirectoryW(buffer, len(buffer))
    except (AttributeError, OSError) as exc:
        raise RemoteBrokerError(
            "tool_unavailable", "Windows system directory is unavailable"
        ) from exc
    if not length or length >= len(buffer):
        raise RemoteBrokerError(
            "tool_unavailable", "Windows system directory is unavailable"
        )
    return Path(buffer.value).resolve(strict=True)


def _trusted_executable_candidates(executable_name: str) -> tuple[Path, ...]:
    if os.name == "nt":
        windows = _windows_directory()
        if executable_name in {"ssh", "scp"}:
            return (
                windows
                / "System32"
                / "OpenSSH"
                / f"{executable_name}.exe",
            )
        if executable_name == "git":
            drive = windows.drive or "C:"
            return (
                Path(drive + "/Program Files/Git/cmd/git.exe"),
                Path(drive + "/Program Files/Git/bin/git.exe"),
                Path(drive + "/Program Files (x86)/Git/cmd/git.exe"),
            )
    else:
        return tuple(
            Path(directory) / executable_name
            for directory in ("/usr/bin", "/bin")
        )
    return ()


def _trusted_system_executable(executable_name: str, repository_root: Path) -> Path:
    trusted_directories: set[Path] = set()
    for candidate in _trusted_executable_candidates(executable_name):
        try:
            lexical_parent = candidate.parent.resolve(strict=True)
            resolved = candidate.resolve(strict=True)
            executable_stat = resolved.stat()
        except OSError:
            continue
        trusted_directories.add(lexical_parent)
        if not stat.S_ISREG(executable_stat.st_mode):
            continue
        if not any(
            resolved == directory / resolved.name or _path_within(resolved, directory)
            for directory in trusted_directories
        ):
            continue
        if _path_within(resolved, repository_root):
            continue
        return resolved
    raise RemoteBrokerError(
        "tool_unavailable",
        f"trusted system {executable_name} executable is unavailable",
    )


def _trusted_running_python(repository_root: Path) -> Path:
    candidate = Path(sys.executable)
    if not candidate.is_absolute():
        raise RemoteBrokerError(
            "tool_unavailable", "the running Python executable is not absolute"
        )
    try:
        resolved = candidate.resolve(strict=True)
        executable_stat = resolved.stat()
    except OSError as exc:
        raise RemoteBrokerError(
            "tool_unavailable", "the running Python executable is unavailable"
        ) from exc
    if not stat.S_ISREG(executable_stat.st_mode) or _path_within(
        resolved, repository_root
    ):
        raise RemoteBrokerError(
            "tool_unavailable", "the running Python executable is not trusted"
        )
    return resolved


def _default_user_ssh_directory() -> Path:
    """Resolve the OS account profile without trusting HOME/USERPROFILE."""

    if os.name == "nt":
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(32768)
            # CSIDL_PROFILE is the current interactive account's profile.
            result = ctypes.windll.shell32.SHGetFolderPathW(
                None, 0x0028, None, 0, buffer
            )
        except (AttributeError, OSError) as exc:
            raise RemoteBrokerError(
                "unsafe_reference", "Windows user profile is unavailable"
            ) from exc
        if result != 0 or not buffer.value:
            raise RemoteBrokerError(
                "unsafe_reference", "Windows user profile is unavailable"
            )
        home = Path(buffer.value)
    else:
        try:
            import pwd

            home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        except (ImportError, KeyError, OSError) as exc:
            raise RemoteBrokerError(
                "unsafe_reference", "POSIX user profile is unavailable"
            ) from exc
    if not home.is_absolute():
        raise RemoteBrokerError("unsafe_reference", "user profile is not absolute")
    return home / ".ssh"


def _minimal_environment(*, path_directories: Sequence[Path] = ()) -> dict[str, str]:
    """Build a fixed environment; no caller-controlled variables are inherited."""

    environment = {"LANG": "C", "LC_ALL": "C"}
    if os.name == "nt":
        windows = _windows_directory()
        environment["SYSTEMROOT"] = str(windows)
        environment["WINDIR"] = str(windows)
    if path_directories:
        environment["PATH"] = os.pathsep.join(
            str(path.resolve(strict=True)) for path in path_directories
        )
    return environment


def _minimal_git_environment(
    git_executable: Path, repository_root: Path
) -> dict[str, str]:
    git_directory = _safe_repository_entry(
        repository_root,
        ".git",
        label="Git metadata directory",
        expect_file=False,
    )
    environment = _minimal_environment(path_directories=(git_executable.parent,))
    # These are fixed broker values, never inherited GIT_* values.  They keep
    # release-check read-only and disable config-driven fsmonitor/pager hooks.
    safe_config = (
        ("core.attributesFile", os.devnull),
        ("core.excludesFile", os.devnull),
        ("core.fsmonitor", "false"),
        ("core.hooksPath", os.devnull),
        ("core.untrackedCache", "false"),
        ("core.pager", "cat"),
        ("diff.external", ""),
        ("pager.status", "false"),
    )
    environment.update(
        {
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": str(len(safe_config)),
            "GIT_DIR": str(git_directory),
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_WORK_TREE": str(repository_root),
            "PAGER": "cat",
        }
    )
    for index, (key, value) in enumerate(safe_config):
        environment[f"GIT_CONFIG_KEY_{index}"] = key
        environment[f"GIT_CONFIG_VALUE_{index}"] = value
    return environment


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _run_bounded_process(
    argv: tuple[str, ...],
    timeout_seconds: int,
    output_limit_bytes: int,
    *,
    cwd: Path | None = None,
    environment: Mapping[str, str] | None = None,
    stdin_handle: BinaryIO | None = None,
    stdout_handle: BinaryIO | None = None,
    stdout_file_limit_bytes: int | None = None,
) -> ProcessOutcome:
    """Run without a shell while bounding both captured output streams."""

    started = time.monotonic()
    creationflags = 0
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = int(subprocess.CREATE_NO_WINDOW)
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            stdin=stdin_handle if stdin_handle is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=dict(environment) if environment is not None else _minimal_environment(),
            creationflags=creationflags,
        )
    except OSError as exc:
        return ProcessOutcome(
            exit_code=None,
            stdout=b"",
            stderr=b"",
            stdout_bytes=0,
            stderr_bytes=0,
            timed_out=False,
            output_limited=False,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            launch_error=exc.__class__.__name__,
        )

    assert process.stdout is not None
    assert process.stderr is not None
    overflow = threading.Event()
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    counts = {"stdout": 0, "stderr": 0}
    stream_errors: list[str] = []

    def read_stream(name: str, stream: Any) -> None:
        while True:
            chunk = stream.read(16384)
            if not chunk:
                break
            previous_count = counts[name]
            counts[name] += len(chunk)
            if name == "stdout" and stdout_handle is not None:
                if stdout_file_limit_bytes is None:
                    stream_errors.append("stdout_limit_missing")
                    overflow.set()
                    break
                writable = max(0, stdout_file_limit_bytes - previous_count)
                if writable:
                    try:
                        stdout_handle.write(chunk[:writable])
                    except (OSError, ValueError):
                        stream_errors.append("stdout_write_failed")
                        overflow.set()
                        break
                if counts[name] > stdout_file_limit_bytes:
                    overflow.set()
                continue
            remaining = max(0, output_limit_bytes - len(buffers[name]))
            if remaining:
                buffers[name].extend(chunk[:remaining])
            if counts[name] > output_limit_bytes:
                overflow.set()

    readers = [
        threading.Thread(target=read_stream, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=read_stream, args=("stderr", process.stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()

    deadline = started + timeout_seconds
    timed_out = False
    while process.poll() is None:
        if overflow.is_set():
            _terminate_process(process)
            break
        if time.monotonic() >= deadline:
            timed_out = True
            _terminate_process(process)
            break
        time.sleep(0.02)

    if process.poll() is None:
        _terminate_process(process)
    for reader in readers:
        reader.join(timeout=2)
    process.stdout.close()
    process.stderr.close()
    stdout_limit = (
        stdout_file_limit_bytes
        if stdout_handle is not None and stdout_file_limit_bytes is not None
        else output_limit_bytes
    )
    output_limited = (
        overflow.is_set()
        or counts["stdout"] > stdout_limit
        or counts["stderr"] > output_limit_bytes
    )
    return ProcessOutcome(
        exit_code=process.returncode,
        stdout=bytes(buffers["stdout"]),
        stderr=bytes(buffers["stderr"]),
        stdout_bytes=counts["stdout"],
        stderr_bytes=counts["stderr"],
        timed_out=timed_out,
        output_limited=output_limited,
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        launch_error=stream_errors[0] if stream_errors else None,
    )


def _run_transport_process(
    argv: tuple[str, ...],
    timeout_seconds: int,
    output_limit_bytes: int,
    *,
    stdin_handle: BinaryIO | None = None,
    stdout_handle: BinaryIO | None = None,
    stdout_file_limit_bytes: int | None = None,
) -> ProcessOutcome:
    executable_directory = Path(argv[0]).resolve(strict=True).parent
    return _run_bounded_process(
        argv,
        timeout_seconds,
        output_limit_bytes,
        environment=_minimal_environment(path_directories=(executable_directory,)),
        stdin_handle=stdin_handle,
        stdout_handle=stdout_handle,
        stdout_file_limit_bytes=stdout_file_limit_bytes,
    )


def _redact_output(text: str, external_paths: Sequence[Path]) -> str:
    redacted = PRIVATE_KEY_OUTPUT_RE.sub("[REDACTED_PRIVATE_KEY]", text)
    redacted = BEARER_OUTPUT_RE.sub("Bearer [REDACTED]", redacted)
    redacted = ASSIGNMENT_OUTPUT_RE.sub(r"\1[REDACTED]", redacted)
    redacted = HEADER_OUTPUT_RE.sub(r"\1[REDACTED]", redacted)
    redacted = URL_USERINFO_OUTPUT_RE.sub(r"\1[REDACTED]@", redacted)
    redacted = PHONE_OUTPUT_RE.sub("[REDACTED_PHONE]", redacted)
    for path in sorted({str(item) for item in external_paths}, key=len, reverse=True):
        if path:
            redacted = redacted.replace(path, "[REDACTED_EXTERNAL_PATH]")
            redacted = redacted.replace(path.replace("\\", "/"), "[REDACTED_EXTERNAL_PATH]")
    return redacted


class RemoteExecutionBroker:
    """Execute exact, pre-approved actions from a locked L4 task contract."""

    def __init__(self) -> None:
        raise RemoteBrokerError(
            "factory_required",
            "construct the production broker only with from_repository",
        )

    def _initialize_from_repository(self, task_id: str) -> None:
        if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
            raise RemoteBrokerError("invalid_task", "task id is invalid")
        self._repository_root = _project_repository_root()
        self._task = _read_repository_json(
            self._repository_root,
            f".harness/tasks/{task_id}/task.json",
            label="task contract",
        )
        self._active_state = _read_repository_json(
            self._repository_root,
            ".harness/state/active-task.json",
            label="active task state",
        )
        self._user_ssh_directory = _default_user_ssh_directory()
        if not self._user_ssh_directory.is_absolute():
            raise RemoteBrokerError(
                "unsafe_reference", "user SSH directory must be absolute"
            )
        self._sealed_upload_artifacts: dict[str, dict[str, Any]] = {}

        self._validate_locked_inputs()
        remote = self._task.get("remote_execution")
        assert isinstance(remote, dict)
        self._remote = remote
        self._host = _validate_host(remote.get("host"))
        self._port = self._validate_port(remote.get("port"))
        self._user = self._validate_user(remote.get("user"))
        self._fingerprint = self._validate_fingerprint(
            remote.get("host_key_fingerprint")
        )
        self._validate_authorization(remote.get("authorization"))
        self._managed_roots, self._deployment_root = self._validate_roots(remote)
        self._identity_path = self._resolve_external_reference(
            remote.get("identity_reference"), label="identity_reference"
        )
        self._known_hosts_path = self._resolve_external_reference(
            remote.get("known_hosts_reference"), label="known_hosts_reference"
        )
        if _same_path(self._identity_path, self._known_hosts_path):
            raise RemoteBrokerError(
                "unsafe_reference",
                "identity_reference and known_hosts_reference must be different files",
            )
        self._actions = self._validate_actions(remote.get("allowed_actions"))
        self._validate_forbidden_actions(remote.get("forbidden_actions"))
        self._ssh_executable = _trusted_system_executable(
            "ssh", self._repository_root
        )
        self._git_executable = _trusted_system_executable(
            "git", self._repository_root
        )
        self._python_executable = _trusted_running_python(self._repository_root)
        self._validate_external_files()

    @classmethod
    def from_repository(
        cls,
        task_id: str,
    ) -> "RemoteExecutionBroker":
        if cls is not RemoteExecutionBroker:
            raise RemoteBrokerError(
                "factory_required", "broker subclasses are not production entry points"
            )
        broker = object.__new__(cls)
        broker._initialize_from_repository(task_id)
        return broker

    @classmethod
    def release_upload_artifact_facts(
        cls,
        task_id: str,
    ) -> list[dict[str, Any]]:
        """Return deterministic facts that release-seal must store for uploads."""

        if cls is not RemoteExecutionBroker:
            raise RemoteBrokerError(
                "factory_required", "broker subclasses are not release-seal entry points"
            )
        if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
            raise RemoteBrokerError("invalid_task", "task id is invalid")
        root = _project_repository_root()
        task = _read_repository_json(
            root,
            f".harness/tasks/{task_id}/task.json",
            label="task contract",
        )
        if task.get("id") != task_id:
            raise RemoteBrokerError("invalid_task", "task id does not match its repository path")
        remote = task.get("remote_execution")
        actions = remote.get("allowed_actions") if isinstance(remote, dict) else None
        if not isinstance(actions, list):
            raise RemoteBrokerError(
                "invalid_contract", "remote upload actions are unavailable"
            )
        facts: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                raise RemoteBrokerError(
                    "invalid_contract", f"allowed_actions[{index}] must be an object"
                )
            if action.get("transport") != "scp" or action.get("direction") != "upload":
                continue
            action_id = action.get("id")
            if (
                not isinstance(action_id, str)
                or not ACTION_ID_RE.fullmatch(action_id)
                or action_id in seen_ids
            ):
                raise RemoteBrokerError(
                    "invalid_contract", "upload action id is invalid or duplicated"
                )
            seen_ids.add(action_id)
            repo_path, local_path = _run_artifact_repo_path(
                root,
                task_id,
                action.get("source"),
                label=f"upload action {action_id}",
                require_file=True,
            )
            size, sha256 = _sha256_regular_file(
                local_path, label=f"upload action {action_id}"
            )
            facts.append(
                {
                    "action_id": action_id,
                    "repo_path": repo_path,
                    "size": size,
                    "sha256": sha256,
                }
            )
        return sorted(facts, key=lambda item: item["action_id"])

    def action_ids(self, *, mode: str | None = None) -> tuple[str, ...]:
        if mode is not None and mode not in {"read_only", "mutating"}:
            raise RemoteBrokerError("invalid_request", "mode filter is invalid")
        return tuple(
            sorted(
                action_id
                for action_id, action in self._actions.items()
                if mode is None or action.mode == mode
            )
        )

    def execute(self, action_id: str, *, allow_mutating: bool = False) -> dict[str, Any]:
        """Execute one exact action and return a JSON-serializable evidence summary."""

        if not isinstance(action_id, str) or action_id not in self._actions:
            raise RemoteBrokerError("action_denied", "action id is not in the locked allowlist")
        action = self._actions[action_id]
        if action.mode == "mutating":
            if allow_mutating is not True:
                raise RemoteBrokerError(
                    "mutation_denied",
                    "mutating execution requires an explicit per-call opt-in",
                )
            self._validate_mutating_approval()
        elif allow_mutating:
            raise RemoteBrokerError(
                "invalid_request",
                "allow_mutating may only be used for a mutating action",
            )

        # Recheck external references and the pinned public host key immediately
        # before every process launch.  The identity path is stat'ed, never read.
        self._validate_external_files()
        upload_stage: _UploadStage | None = None
        download_stage: _DownloadStage | None = None
        try:
            if action.transport == "scp" and action.direction == "upload":
                upload_stage = self._prepare_upload_stage(action)
            elif action.transport == "scp" and action.direction == "download":
                download_stage = self._prepare_download_stage(action)
            system_argv = self._build_system_argv(
                action,
                upload_stage=upload_stage,
                download_stage=download_stage,
            )
            started_at = dt.datetime.now(dt.timezone.utc)
            outcome = _run_transport_process(
                system_argv,
                action.timeout_seconds,
                HARD_MAX_OUTPUT_BYTES,
                stdin_handle=upload_stage.handle if upload_stage is not None else None,
                stdout_handle=(
                    download_stage.handle if download_stage is not None else None
                ),
                stdout_file_limit_bytes=(
                    HARD_MAX_DOWNLOAD_BYTES if download_stage is not None else None
                ),
            )
            if not isinstance(outcome, ProcessOutcome):
                raise RemoteBrokerError(
                    "runner_error", "transport process returned an invalid result"
                )
            if upload_stage is not None:
                actual_size, actual_sha256 = self._hash_open_handle(
                    upload_stage.handle,
                    label="broker upload staging file after transfer",
                )
                if actual_size != upload_stage.size or not hmac.compare_digest(
                    actual_sha256, upload_stage.sha256
                ):
                    raise RemoteBrokerError(
                        "artifact_drift", "upload staging file changed during transfer"
                    )
                if (
                    not outcome.launch_error
                    and not outcome.timed_out
                    and not outcome.output_limited
                    and outcome.exit_code == 0
                ):
                    receipt = (
                        f"HARNESS_UPLOAD_VERIFIED {upload_stage.sha256} "
                        f"{upload_stage.size}"
                    )
                    stdout_lines = outcome.stdout.decode(
                        "utf-8", errors="replace"
                    ).splitlines()
                    if stdout_lines != [receipt]:
                        raise RemoteBrokerError(
                            "remote_upload_verification_failed",
                            "remote upload did not return the exact verified receipt",
                        )
            download_verification: dict[str, Any] | None = None
            if download_stage is not None and (
                not outcome.launch_error
                and not outcome.timed_out
                and not outcome.output_limited
                and outcome.exit_code == 0
            ):
                download_verification = self._publish_download_stage(
                    action, download_stage
                )
            finished_at = dt.datetime.now(dt.timezone.utc)
            evidence = self._build_evidence(
                action, outcome, started_at, finished_at
            )
            if upload_stage is not None:
                evidence["upload_verification"] = {
                    "repo_path": upload_stage.repo_path,
                    "size": upload_stage.size,
                    "sha256": upload_stage.sha256,
                    "local_content_addressed_stage": True,
                    "stable_handle_verified_before_and_after": True,
                    "remote_staging_verification_confirmed": evidence["success"],
                    "atomic_destination_apply_confirmed": evidence["success"],
                    "confirmation": (
                        "confirmed" if evidence["success"] else "not_confirmed"
                    ),
                    "wire_transport": "ssh_stdin",
                }
            if download_stage is not None:
                evidence["download_verification"] = download_verification or {
                    "stable_handle_verified": False,
                    "unique_stage_link_verified": False,
                    "atomic_no_overwrite_publish_confirmed": False,
                    "wire_transport": "ssh_stdout_to_stable_handle",
                }
            return evidence
        finally:
            if upload_stage is not None:
                upload_stage.close_and_remove()
            if download_stage is not None:
                download_stage.close_and_remove()

    def execute_json(self, action_id: str, *, allow_mutating: bool = False) -> str:
        return json.dumps(
            self.execute(action_id, allow_mutating=allow_mutating),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _validate_locked_inputs(self) -> None:
        task = self._task
        state = self._active_state
        task_id = task.get("id")
        if task.get("schema_version") != 2:
            raise RemoteBrokerError(
                "invalid_task", "remote execution requires task schema version 2"
            )
        if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
            raise RemoteBrokerError("invalid_task", "task id is invalid")
        if task.get("type") != "operations" or task.get("risk_level") != "L4":
            raise RemoteBrokerError(
                "invalid_task", "remote execution requires an L4 operations task"
            )
        if task.get("network_access_required") is not True:
            raise RemoteBrokerError(
                "invalid_task", "task does not explicitly require network access"
            )
        if task.get("status") not in ALLOWED_READ_ONLY_STATUSES:
            raise RemoteBrokerError("invalid_task", "task status does not permit remote execution")
        if state.get("schema_version") != 1 or state.get("task_id") != task_id:
            raise RemoteBrokerError("invalid_state", "active task does not match the task contract")
        for key in (
            "contract_sha256",
            "policy_sha256",
            "plan_artifacts_sha256",
            "decision_context_sha256",
        ):
            value = state.get(key)
            if not isinstance(value, str) or not HEX_SHA256_RE.fullmatch(value):
                raise RemoteBrokerError("invalid_state", f"active state {key} is invalid")
        base = state.get("scope_base_commit")
        if not isinstance(base, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", base):
            raise RemoteBrokerError("invalid_state", "active state scope base is invalid")
        if not isinstance(state.get("git_branch"), str) or not state.get("git_branch"):
            raise RemoteBrokerError("invalid_state", "active state branch is invalid")
        if state["contract_sha256"] != _immutable_contract_hash(task):
            raise RemoteBrokerError("contract_drift", "immutable task contract changed after preflight")
        if state["policy_sha256"] != _policy_contract_hash(task):
            raise RemoteBrokerError("contract_drift", "remote execution policy changed after preflight")

        remote = task.get("remote_execution")
        if not isinstance(remote, dict) or set(remote) != REMOTE_CONTRACT_KEYS:
            raise RemoteBrokerError(
                "invalid_contract", "remote_execution keys do not match the fixed schema"
            )
        if remote.get("environment") != "authorized_personal_site":
            raise RemoteBrokerError(
                "invalid_contract", "remote environment is not the authorized personal site"
            )

        approvals = task.get("manual_approvals")
        reviewer = task.get("reviewer")
        if not isinstance(approvals, dict) or not isinstance(reviewer, str) or not reviewer:
            raise RemoteBrokerError("invalid_task", "independent plan approval is missing")
        plan = approvals.get("plan")
        if (
            not isinstance(plan, dict)
            or plan.get("required") is not True
            or plan.get("status") != "approved"
            or plan.get("approved_by") != reviewer
        ):
            raise RemoteBrokerError("invalid_task", "independent plan approval is not valid")
        _parse_rfc3339(plan.get("approved_at"), label="manual_approvals.plan.approved_at")
        self._validate_codex_role_bindings(task, approvals)

    @staticmethod
    def _validate_codex_role_bindings(
        task: Mapping[str, Any], approvals: Mapping[str, Any]
    ) -> None:
        bindings = task.get("codex_role_bindings")
        if not isinstance(bindings, dict) or set(bindings) != {
            "implementation",
            "plan",
            "merge",
            "release",
        }:
            raise RemoteBrokerError(
                "invalid_task", "remote task lacks fixed Codex role bindings"
            )
        implementation = bindings.get("implementation")
        if not isinstance(implementation, dict) or set(implementation) != {
            "agent_task",
            "thread_id",
        }:
            raise RemoteBrokerError(
                "invalid_task", "remote implementation binding is invalid"
            )
        implementation_task = implementation.get("agent_task")
        implementation_thread = implementation.get("thread_id")
        if not isinstance(implementation_task, str) or not CODEX_AGENT_TASK_RE.fullmatch(
            implementation_task
        ):
            raise RemoteBrokerError(
                "invalid_task", "remote implementation agent task is invalid"
            )
        try:
            parsed_thread = uuid.UUID(str(implementation_thread))
        except (ValueError, AttributeError) as exc:
            raise RemoteBrokerError(
                "invalid_task", "remote implementation thread id is invalid"
            ) from exc
        if str(parsed_thread) != implementation_thread:
            raise RemoteBrokerError(
                "invalid_task", "remote implementation thread id is not canonical"
            )

        stage_tasks: dict[str, str] = {}
        for stage in ("plan", "merge", "release"):
            approval = approvals.get(stage)
            if not isinstance(approval, dict) or approval.get("required") is not True:
                raise RemoteBrokerError(
                    "invalid_task", f"remote task requires independent {stage} approval"
                )
            binding = bindings.get(stage)
            if not isinstance(binding, dict) or set(binding) != {"agent_task"}:
                raise RemoteBrokerError(
                    "invalid_task", f"remote {stage} role binding is invalid"
                )
            agent_task = binding.get("agent_task")
            if not isinstance(agent_task, str) or not CODEX_AGENT_TASK_RE.fullmatch(
                agent_task
            ):
                raise RemoteBrokerError(
                    "invalid_task", f"remote {stage} agent task is invalid"
                )
            if agent_task == implementation_task:
                raise RemoteBrokerError(
                    "invalid_task", f"remote {stage} role is not independent"
                )
            stage_tasks[stage] = agent_task
        if stage_tasks["release"] in {
            stage_tasks["plan"],
            stage_tasks["merge"],
        }:
            raise RemoteBrokerError(
                "invalid_task", "remote release role is not independent"
            )

    @staticmethod
    def _validate_port(value: Any) -> int:
        if type(value) is not int or not 1 <= value <= 65535:
            raise RemoteBrokerError("invalid_contract", "remote port is invalid")
        return value

    @staticmethod
    def _validate_user(value: Any) -> str:
        if not isinstance(value, str) or not USER_RE.fullmatch(value):
            raise RemoteBrokerError("invalid_contract", "remote user is invalid")
        return value

    @staticmethod
    def _validate_fingerprint(value: Any) -> str:
        if not isinstance(value, str) or not HOST_KEY_FINGERPRINT_RE.fullmatch(value):
            raise RemoteBrokerError("invalid_contract", "host key fingerprint is invalid")
        return value

    @staticmethod
    def _validate_authorization(value: Any) -> None:
        if not isinstance(value, dict) or set(value) != AUTHORIZATION_KEYS:
            raise RemoteBrokerError("invalid_contract", "authorization keys are invalid")
        if value.get("mode") != "user_explicit":
            raise RemoteBrokerError("invalid_contract", "authorization mode is invalid")
        thread_id = value.get("thread_id")
        try:
            parsed_thread_id = uuid.UUID(str(thread_id))
        except (ValueError, AttributeError) as exc:
            raise RemoteBrokerError("invalid_contract", "authorization thread id is invalid") from exc
        if str(parsed_thread_id) != thread_id:
            raise RemoteBrokerError("invalid_contract", "authorization thread id must be canonical")
        _parse_rfc3339(value.get("authorized_at"), label="authorization.authorized_at")
        _clean_text(value.get("scope"), label="authorization.scope", min_length=20, max_length=500)

    @staticmethod
    def _validate_roots(remote: Mapping[str, Any]) -> tuple[tuple[str, ...], str]:
        deployment_root = _normalize_remote_path(
            remote.get("deployment_root"), label="remote_execution.deployment_root"
        )
        if deployment_root in PROTECTED_MANAGED_ROOTS:
            raise RemoteBrokerError("unsafe_remote_root", "deployment root is too broad")
        values = remote.get("managed_roots")
        if not isinstance(values, list) or not values or len(values) > 8:
            raise RemoteBrokerError("invalid_contract", "managed_roots must be a bounded array")
        roots: list[str] = []
        for index, value in enumerate(values):
            root = _normalize_remote_path(value, label=f"managed_roots[{index}]")
            if root in PROTECTED_MANAGED_ROOTS:
                raise RemoteBrokerError("unsafe_remote_root", "managed root is too broad")
            roots.append(root)
        if len(set(roots)) != len(roots):
            raise RemoteBrokerError("invalid_contract", "managed_roots contains duplicates")
        for index, root in enumerate(roots):
            root_path = PurePosixPath(root)
            for other in roots[index + 1 :]:
                other_path = PurePosixPath(other)
                if root_path in other_path.parents or other_path in root_path.parents:
                    raise RemoteBrokerError(
                        "invalid_contract",
                        "managed_roots may not contain one another",
                    )
        if deployment_root not in roots:
            raise RemoteBrokerError(
                "invalid_contract", "deployment_root must be an exact managed root"
            )
        return tuple(roots), deployment_root

    def _resolve_external_reference(self, value: Any, *, label: str) -> Path:
        if not isinstance(value, str):
            raise RemoteBrokerError("unsafe_reference", f"{label} must be an external reference")
        matched = REFERENCE_RE.fullmatch(value)
        if not matched:
            raise RemoteBrokerError(
                "unsafe_reference",
                f"{label} must use user-ssh-file:<basename>",
            )
        basename = matched.group(1)
        if basename in {".", ".."} or "/" in basename or "\\" in basename:
            raise RemoteBrokerError("unsafe_reference", f"{label} basename is invalid")
        return self._user_ssh_directory / basename

    def _validate_actions(self, value: Any) -> dict[str, ActionSpec]:
        if not isinstance(value, list) or not value or len(value) > MAX_ACTIONS:
            raise RemoteBrokerError("invalid_contract", "allowed_actions must be a bounded array")
        actions: dict[str, ActionSpec] = {}
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise RemoteBrokerError("invalid_contract", f"allowed_actions[{index}] must be an object")
            transport = item.get("transport")
            expected_keys = SSH_ACTION_KEYS if transport == "ssh" else SCP_ACTION_KEYS if transport == "scp" else None
            if expected_keys is None or set(item) != expected_keys:
                raise RemoteBrokerError("invalid_contract", f"allowed_actions[{index}] keys are invalid")
            action_id = item.get("id")
            if not isinstance(action_id, str) or not ACTION_ID_RE.fullmatch(action_id):
                raise RemoteBrokerError("invalid_contract", f"allowed_actions[{index}].id is invalid")
            if action_id in actions:
                raise RemoteBrokerError("invalid_contract", "allowed_actions contains duplicate ids")
            mode = item.get("mode")
            if mode not in {"read_only", "mutating"}:
                raise RemoteBrokerError("invalid_contract", f"allowed_actions[{index}].mode is invalid")
            timeout = item.get("timeout_seconds")
            if type(timeout) is not int or not 1 <= timeout <= HARD_MAX_TIMEOUT_SECONDS:
                raise RemoteBrokerError("invalid_contract", f"allowed_actions[{index}] timeout is invalid")

            if transport == "ssh":
                cwd = _normalize_remote_path(item.get("cwd"), label=f"allowed_actions[{index}].cwd")
                if not _within_remote_roots(cwd, self._managed_roots):
                    raise RemoteBrokerError("unmanaged_remote_path", f"allowed_actions[{index}].cwd is outside managed_roots")
                argv = _validate_command_tokens(item.get("argv"), label=f"allowed_actions[{index}].argv")
                if mode == "read_only":
                    _validate_read_only_command(argv, label=f"allowed_actions[{index}].argv")
                self._validate_remote_argv_paths(
                    argv,
                    cwd=cwd,
                    mode=mode,
                    label=f"allowed_actions[{index}].argv",
                )
                action = ActionSpec(
                    action_id=action_id,
                    transport="ssh",
                    mode=mode,
                    timeout_seconds=timeout,
                    cwd=cwd,
                    argv=argv,
                )
            else:
                direction = item.get("direction")
                if direction not in {"upload", "download"}:
                    raise RemoteBrokerError("invalid_contract", f"allowed_actions[{index}].direction is invalid")
                if direction == "upload" and mode != "mutating":
                    raise RemoteBrokerError("mode_mismatch", "scp upload must be mutating")
                if direction == "download" and mode != "read_only":
                    raise RemoteBrokerError("mode_mismatch", "scp download must be read_only")
                source = _clean_text(item.get("source"), label=f"allowed_actions[{index}].source", max_length=1024)
                destination = _clean_text(item.get("destination"), label=f"allowed_actions[{index}].destination", max_length=1024)
                remote_path = destination if direction == "upload" else source
                normalized_remote = _normalize_remote_path(remote_path, label=f"allowed_actions[{index}].remote_path")
                if not _within_remote_roots(normalized_remote, self._managed_roots):
                    raise RemoteBrokerError("unmanaged_remote_path", f"allowed_actions[{index}] remote path is outside managed_roots")
                local_path = source if direction == "upload" else destination
                self._validate_local_contract_path(local_path, label=f"allowed_actions[{index}].local_path")
                _validate_no_sensitive_arguments((source, destination), label=f"allowed_actions[{index}].paths")
                action = ActionSpec(
                    action_id=action_id,
                    transport="scp",
                    mode=mode,
                    timeout_seconds=timeout,
                    direction=direction,
                    source=source,
                    destination=destination,
                )
            actions[action_id] = action
        bootstrap_actions = [
            action
            for action in actions.values()
            if self._is_deployment_root_bootstrap(action)
        ]
        if len(bootstrap_actions) > 1:
            raise RemoteBrokerError(
                "invalid_contract",
                "only one deployment-root bootstrap action is allowed",
            )
        return actions

    def _normalized_action_path(self, value: str, *, cwd: str, label: str) -> str:
        if ".." in value.split("/"):
            raise RemoteBrokerError(
                "unmanaged_remote_path", f"{label} may not contain parent traversal"
            )
        if value.startswith(("~", "$HOME", "${HOME}")):
            raise RemoteBrokerError(
                "unmanaged_remote_path", f"{label} may not use home expansion"
            )
        if value.startswith("/"):
            candidate = posixpath.normpath(value)
        else:
            candidate = posixpath.normpath(posixpath.join(cwd, value))
        normalized = _normalize_remote_path(candidate, label=label)
        if not _within_remote_roots(normalized, self._managed_roots):
            raise RemoteBrokerError(
                "unmanaged_remote_path", f"{label} resolves outside managed_roots"
            )
        return normalized

    def _validate_path_option_value(
        self, value: str, *, cwd: str, label: str
    ) -> None:
        if not value or value == "-":
            raise RemoteBrokerError(
                "unmanaged_remote_path", f"{label} must name a managed file path"
            )
        self._normalized_action_path(value, cwd=cwd, label=label)

    def _validate_docker_host_paths(
        self, argv: Sequence[str], *, cwd: str, label: str
    ) -> None:
        path_flags = {
            "-f",
            "--config",
            "--env-file",
            "--file",
            "--iidfile",
            "--metadata-file",
            "--project-directory",
        }
        index = 1
        while index < len(argv):
            item = argv[index]
            if item in path_flags:
                if index + 1 >= len(argv):
                    raise RemoteBrokerError(
                        "invalid_contract", f"{label} path option is missing its value"
                    )
                self._validate_path_option_value(
                    argv[index + 1], cwd=cwd, label=f"{label}[{index + 1}]"
                )
                index += 2
                continue
            matched_flag = next(
                (flag for flag in path_flags if item.startswith(flag + "=")), None
            )
            if matched_flag is not None:
                self._validate_path_option_value(
                    item.split("=", 1)[1], cwd=cwd, label=f"{label}[{index}]"
                )
            if item in {"-v", "--volume"}:
                if index + 1 >= len(argv):
                    raise RemoteBrokerError(
                        "invalid_contract", f"{label} volume option is missing its value"
                    )
                host_source = argv[index + 1].split(":", 1)[0]
                if host_source.startswith(('/', '.', '~', '$')) or "/" in host_source:
                    self._validate_path_option_value(
                        host_source, cwd=cwd, label=f"{label}[{index + 1}] host volume"
                    )
                index += 2
                continue
            if item.startswith("--volume="):
                host_source = item.split("=", 1)[1].split(":", 1)[0]
                if host_source.startswith(('/', '.', '~', '$')) or "/" in host_source:
                    self._validate_path_option_value(
                        host_source, cwd=cwd, label=f"{label}[{index}] host volume"
                    )
            if item == "--mount":
                if index + 1 >= len(argv):
                    raise RemoteBrokerError(
                        "invalid_contract", f"{label} mount option is missing its value"
                    )
                mount_value = argv[index + 1]
                self._validate_docker_mount_source(
                    mount_value, cwd=cwd, label=f"{label}[{index + 1}]"
                )
                index += 2
                continue
            if item.startswith("--mount="):
                self._validate_docker_mount_source(
                    item.split("=", 1)[1], cwd=cwd, label=f"{label}[{index}]"
                )
            index += 1

        command = argv[1] if len(argv) > 1 else ""
        if command == "cp":
            for operand_index, operand in enumerate(argv[2:], start=2):
                if operand.startswith("-") or ":" in operand:
                    continue
                self._validate_path_option_value(
                    operand, cwd=cwd, label=f"{label}[{operand_index}] docker cp host path"
                )
        if command == "build" and len(argv) > 2:
            context = argv[-1]
            if context not in {"-"} and not re.match(r"(?i)^(?:https?|git|ssh)://", context):
                self._validate_path_option_value(
                    context, cwd=cwd, label=f"{label}[{len(argv) - 1}] build context"
                )

    def _validate_docker_mount_source(
        self, value: str, *, cwd: str, label: str
    ) -> None:
        fields: dict[str, str] = {}
        for item in value.split(","):
            if "=" in item:
                key, field_value = item.split("=", 1)
                fields[key.casefold()] = field_value
        mount_type = fields.get("type", "").casefold()
        source = fields.get("src") or fields.get("source")
        if mount_type == "bind" or (source and source.startswith(('/', '.', '~', '$'))):
            if not source:
                raise RemoteBrokerError(
                    "unmanaged_remote_path", f"{label} bind mount lacks a source"
                )
            self._validate_path_option_value(
                source, cwd=cwd, label=f"{label} bind source"
            )

    def _validate_mutating_file_paths(
        self, argv: Sequence[str], *, cwd: str, label: str
    ) -> None:
        executable = _basename_token(argv[0])
        file_mutators = {
            "chgrp",
            "chmod",
            "chown",
            "cp",
            "install",
            "ln",
            "mkdir",
            "mv",
            "rm",
            "rmdir",
            "sed",
            "tee",
            "touch",
            "truncate",
        }
        if executable not in file_mutators:
            return
        operands = [item for item in argv[1:] if item != "--" and not item.startswith("-")]
        if executable in {"chmod", "chown", "chgrp"} and operands:
            operands = operands[1:]
        if executable == "sed" and operands:
            operands = operands[1:]
        for operand_index, operand in enumerate(operands):
            self._normalized_action_path(
                operand, cwd=cwd, label=f"{label} file operand {operand_index}"
            )

    def _validate_remote_argv_paths(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        mode: str,
        label: str,
    ) -> None:
        executable = _basename_token(argv[0])
        if executable == "docker":
            self._validate_docker_host_paths(argv, cwd=cwd, label=label)
        else:
            for index, argument in enumerate(argv[1:], start=1):
                path_value: str | None = None
                if argument.startswith(("/", "~", "$HOME", "${HOME}")):
                    path_value = argument
                elif "=" in argument:
                    possible = argument.split("=", 1)[1]
                    if (
                        possible.startswith(("/", "./", "../", "~", "$HOME", "${HOME}"))
                        or (
                            "/" in possible
                            and not re.match(r"(?i)^[a-z][a-z0-9+.-]*://", possible)
                        )
                    ):
                        path_value = possible
                elif (
                    argument.startswith(("./", "../"))
                    or (
                        "/" in argument
                        and not re.match(r"(?i)^[a-z][a-z0-9+.-]*://", argument)
                    )
                ):
                    path_value = argument
                if path_value is not None:
                    self._validate_path_option_value(
                        path_value, cwd=cwd, label=f"{label}[{index}]"
                    )
        if mode == "mutating":
            self._validate_mutating_file_paths(argv, cwd=cwd, label=label)

    def _is_deployment_root_bootstrap(self, action: ActionSpec) -> bool:
        return (
            action.transport == "ssh"
            and action.mode == "mutating"
            and action.cwd == self._deployment_root
            and action.argv
            == ("mkdir", "-p", "--", self._deployment_root)
        )

    @staticmethod
    def _validate_forbidden_actions(value: Any) -> None:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise RemoteBrokerError("invalid_contract", "forbidden_actions must be an array")
        if len(value) != len(set(value)) or set(value) != REQUIRED_FORBIDDEN_ACTIONS:
            raise RemoteBrokerError(
                "invalid_contract",
                "forbidden_actions must contain the complete fixed denial set",
            )

    def _validate_local_contract_path(self, value: str, *, label: str) -> Path:
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
            raise RemoteBrokerError("unsafe_local_path", f"{label} must be a normalized repository-relative path")
        if not candidate.parts:
            raise RemoteBrokerError("unsafe_local_path", f"{label} is empty")
        lexical = (self._repository_root / candidate).absolute()
        resolved = lexical.resolve(strict=False)
        if not _path_within(resolved, self._repository_root):
            raise RemoteBrokerError("unsafe_local_path", f"{label} escapes the repository")
        if not _same_path(resolved, lexical):
            raise RemoteBrokerError("unsafe_local_path", f"{label} may not traverse a redirect")
        repo_path = candidate.as_posix()
        run_prefix = f".harness/runs/{self._task['id']}/"
        if not repo_path.startswith(run_prefix) or repo_path == run_prefix:
            raise RemoteBrokerError(
                "unsafe_local_path",
                f"{label} must stay in .harness/runs/{self._task['id']}/**",
            )
        return resolved

    def _validate_plain_external_file(self, path: Path, *, label: str, public_file: bool) -> Path:
        if not path.is_absolute():
            raise RemoteBrokerError("unsafe_reference", f"{label} path must be absolute")
        try:
            path_stat = path.lstat()
        except OSError as exc:
            raise RemoteBrokerError("unsafe_reference", f"{label} file is unavailable") from exc
        if stat.S_ISLNK(path_stat.st_mode) or _is_reparse_point(path_stat):
            raise RemoteBrokerError("unsafe_reference", f"{label} may not be a symlink/reparse point")
        if not stat.S_ISREG(path_stat.st_mode):
            raise RemoteBrokerError("unsafe_reference", f"{label} must be a regular file")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise RemoteBrokerError("unsafe_reference", f"{label} file cannot be resolved") from exc
        if not _same_path(resolved, path.absolute()):
            raise RemoteBrokerError("unsafe_reference", f"{label} parent path may not redirect")
        if _path_within(resolved, self._repository_root):
            raise RemoteBrokerError("unsafe_reference", f"{label} must remain outside the repository")
        if path_stat.st_size <= 0:
            raise RemoteBrokerError("unsafe_reference", f"{label} file is empty")
        if public_file and path_stat.st_size > MAX_KNOWN_HOSTS_BYTES:
            raise RemoteBrokerError("unsafe_reference", f"{label} file is too large")
        return resolved

    def _validate_external_files(self) -> None:
        self._identity_path = self._validate_plain_external_file(
            self._identity_path,
            label="identity_reference",
            public_file=False,
        )
        self._known_hosts_path = self._validate_plain_external_file(
            self._known_hosts_path,
            label="known_hosts_reference",
            public_file=True,
        )
        self._verify_known_hosts_fingerprint()

    def _host_tokens(self) -> tuple[str, ...]:
        if self._port == 22:
            return (self._host, f"[{self._host}]:22")
        return (f"[{self._host}]:{self._port}",)

    @staticmethod
    def _hashed_host_matches(pattern: str, candidate: str) -> bool:
        parts = pattern.split("|")
        if len(parts) != 4 or parts[1] != "1":
            return False
        try:
            salt_text = parts[2] + "=" * ((4 - len(parts[2]) % 4) % 4)
            digest_text = parts[3] + "=" * ((4 - len(parts[3]) % 4) % 4)
            salt = base64.b64decode(salt_text, validate=True)
            expected = base64.b64decode(digest_text, validate=True)
        except (ValueError, binascii.Error):
            return False
        actual = hmac.new(salt, candidate.encode("utf-8"), hashlib.sha1).digest()
        return hmac.compare_digest(actual, expected)

    def _known_host_pattern_matches(self, pattern: str) -> bool:
        candidates = self._host_tokens()
        if pattern.startswith("|1|"):
            return any(self._hashed_host_matches(pattern, candidate) for candidate in candidates)
        if any(character in pattern for character in "*!?"):
            return False
        return pattern in candidates

    def _verify_known_hosts_fingerprint(self) -> None:
        try:
            before = self._known_hosts_path.lstat()
            open_flags = (
                os.O_RDONLY
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(self._known_hosts_path, open_flags)
            with os.fdopen(descriptor, "rb", closefd=True) as handle:
                opened = os.fstat(handle.fileno())
                if not os.path.samestat(before, opened):
                    raise RemoteBrokerError(
                        "known_hosts_invalid", "known_hosts was replaced before reading"
                    )
                payload = handle.read(MAX_KNOWN_HOSTS_BYTES + 1)
                handle_after = os.fstat(handle.fileno())
            after = self._known_hosts_path.lstat()
            if (
                not os.path.samestat(before, handle_after)
                or not os.path.samestat(handle_after, after)
                or before.st_size != handle_after.st_size
                or before.st_mtime_ns != handle_after.st_mtime_ns
                or len(payload) != before.st_size
                or len(payload) > MAX_KNOWN_HOSTS_BYTES
            ):
                raise RemoteBrokerError(
                    "known_hosts_invalid", "known_hosts changed while being read"
                )
            content = payload.decode("utf-8")
        except RemoteBrokerError:
            raise
        except UnicodeError as exc:
            raise RemoteBrokerError("known_hosts_invalid", "known_hosts is not UTF-8 text") from exc
        except OSError as exc:
            raise RemoteBrokerError("known_hosts_invalid", "known_hosts is not readable UTF-8 text") from exc
        fingerprints: set[str] = set()
        revoked_match = False
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            marker = None
            if fields and fields[0].startswith("@"):
                marker = fields.pop(0)
            if len(fields) < 3:
                continue
            host_field, _key_type, key_data = fields[:3]
            patterns = host_field.split(",")
            positive = any(
                not pattern.startswith("!") and self._known_host_pattern_matches(pattern)
                for pattern in patterns
            )
            negative = any(
                pattern.startswith("!") and self._known_host_pattern_matches(pattern[1:])
                for pattern in patterns
            )
            if not positive or negative:
                continue
            if marker == "@revoked":
                revoked_match = True
                continue
            if marker is not None:
                # Certificate-authority pinning is deliberately not inferred as
                # a direct host-key fingerprint.
                continue
            try:
                padded = key_data + "=" * ((4 - len(key_data) % 4) % 4)
                key_blob = base64.b64decode(padded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise RemoteBrokerError("known_hosts_invalid", "matching host key is invalid") from exc
            digest = base64.b64encode(hashlib.sha256(key_blob).digest()).decode("ascii").rstrip("=")
            fingerprints.add("SHA256:" + digest)
        if revoked_match:
            raise RemoteBrokerError("host_key_revoked", "target host key is marked revoked")
        if fingerprints != {self._fingerprint}:
            raise RemoteBrokerError(
                "host_key_mismatch",
                "known_hosts does not contain exactly the contracted target fingerprint",
            )

    def _validate_mutating_approval(self) -> None:
        fresh_task = _read_repository_json(
            self._repository_root,
            f".harness/tasks/{self._task['id']}/task.json",
            label="task contract",
        )
        fresh_state = _read_repository_json(
            self._repository_root,
            ".harness/state/active-task.json",
            label="active task state",
        )
        if fresh_task != self._task or fresh_state != self._active_state:
            raise RemoteBrokerError(
                "contract_drift",
                "task or active state changed after broker construction",
            )
        task = self._task
        if task.get("status") != "approved_for_merge":
            raise RemoteBrokerError(
                "mutation_denied",
                "mutating action requires task status approved_for_merge",
            )
        owner = task.get("owner")
        reviewer = task.get("reviewer")
        release_approver = task.get("release_approver")
        if not all(isinstance(item, str) and item for item in (owner, reviewer, release_approver)):
            raise RemoteBrokerError("mutation_denied", "independent release role is missing")
        if len({owner.casefold(), reviewer.casefold(), release_approver.casefold()}) != 3:
            raise RemoteBrokerError("mutation_denied", "owner/reviewer/release roles are not independent")
        approvals = task.get("manual_approvals")
        merge = approvals.get("merge") if isinstance(approvals, dict) else None
        if (
            not isinstance(merge, dict)
            or merge.get("required") is not True
            or merge.get("status") != "approved"
            or merge.get("approved_by") != reviewer
        ):
            raise RemoteBrokerError(
                "mutation_denied", "independent merge approval is not valid"
            )
        _parse_rfc3339(
            merge.get("approved_at"), label="manual_approvals.merge.approved_at"
        )
        release = approvals.get("release") if isinstance(approvals, dict) else None
        if (
            not isinstance(release, dict)
            or release.get("required") is not True
            or release.get("status") != "approved"
            or release.get("approved_by") != release_approver
        ):
            raise RemoteBrokerError("mutation_denied", "independent release approval is not valid")
        _parse_rfc3339(release.get("approved_at"), label="manual_approvals.release.approved_at")
        self._validate_mutating_repository_seal()

    def _local_git_bytes(
        self, *arguments: str, output_limit: int = LOCAL_GIT_OUTPUT_BYTES
    ) -> bytes:
        if self._git_executable is None:
            raise RemoteBrokerError(
                "release_seal_invalid", "trusted Git is unavailable to the production broker"
            )
        outcome = _run_bounded_process(
            (
                str(self._git_executable),
                "-C",
                str(self._repository_root),
                *arguments,
            ),
            15,
            output_limit,
            cwd=self._repository_root,
            environment=_minimal_git_environment(
                self._git_executable, self._repository_root
            ),
        )
        if (
            outcome.launch_error
            or outcome.timed_out
            or outcome.output_limited
            or outcome.exit_code != 0
            or outcome.stderr
        ):
            raise RemoteBrokerError(
                "release_seal_invalid", "local Git verification failed closed"
            )
        return outcome.stdout

    def _local_git(self, *arguments: str) -> str:
        try:
            return self._local_git_bytes(*arguments).decode(
                "utf-8", errors="strict"
            )
        except UnicodeError as exc:
            raise RemoteBrokerError(
                "release_seal_invalid", "local Git output is not valid UTF-8"
            ) from exc

    @staticmethod
    def _attribute_payload_uses_execution_features(
        payload: bytes, *, label: str
    ) -> None:
        try:
            text = payload.decode("utf-8-sig", errors="strict")
        except UnicodeError as exc:
            raise RemoteBrokerError(
                "release_check_invalid", f"{label} is not valid UTF-8"
            ) from exc
        forbidden_attribute = re.compile(
            r"(?i)(?:^|\s)[-!]?(?:filter|diff|ident|working-tree-encoding)(?:=|\s|$)"
        )
        for line in text.splitlines():
            active = line.split("#", 1)[0].strip()
            if active and forbidden_attribute.search(active):
                raise RemoteBrokerError(
                    "release_check_invalid",
                    f"{label} enables a forbidden Git content transformation",
                )

    def _validate_git_execution_policy(self) -> None:
        config_path = _safe_repository_entry(
            self._repository_root,
            ".git/config",
            label="repository-local Git config",
            expect_file=True,
        )
        config_payload = _read_stable_regular_bytes(
            config_path,
            label="repository-local Git config",
            maximum_bytes=MAX_CONTROL_JSON_BYTES,
        )
        try:
            config_text = config_payload.decode("utf-8-sig", errors="strict")
        except UnicodeError as exc:
            raise RemoteBrokerError(
                "release_check_invalid",
                "repository-local Git config is not valid UTF-8",
            ) from exc
        current_section = ""
        for line in config_text.splitlines():
            active = line.strip()
            if not active or active.startswith(("#", ";")):
                continue
            section_match = re.fullmatch(r"\[\s*([^\]]+)\s*\]", active)
            if section_match:
                current_section = section_match.group(1).strip().casefold()
                section_name = re.split(r"[\s\"]", current_section, maxsplit=1)[0]
                if section_name in {"alias", "filter", "include", "includeif"}:
                    raise RemoteBrokerError(
                        "release_check_invalid",
                        "repository-local Git config enables an execution-capable section",
                    )
                continue
            key = active.split("=", 1)[0].strip().casefold()
            if (
                current_section == "core"
                and key in {"hookspath", "attributesfile"}
            ) or (
                current_section.startswith("diff")
                and key in {"command", "external", "textconv"}
            ):
                raise RemoteBrokerError(
                    "release_check_invalid",
                    "repository-local Git config enables an execution-capable helper",
                )

        info_attributes = self._repository_root / ".git" / "info" / "attributes"
        try:
            info_attributes.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise RemoteBrokerError(
                "release_check_invalid", "Git info attributes cannot be inspected"
            ) from exc
        else:
            info_path = _safe_repository_entry(
                self._repository_root,
                ".git/info/attributes",
                label="Git info attributes",
                expect_file=True,
            )
            self._attribute_payload_uses_execution_features(
                _read_stable_regular_bytes(
                    info_path,
                    label="Git info attributes",
                    maximum_bytes=MAX_CONTROL_JSON_BYTES,
                    allow_empty=True,
                ),
                label="Git info attributes",
            )

        for current_root, directory_names, file_names in os.walk(
            self._repository_root, topdown=True, followlinks=False
        ):
            current = Path(current_root)
            retained_directories: list[str] = []
            for directory_name in directory_names:
                if current == self._repository_root and directory_name == ".git":
                    continue
                directory = current / directory_name
                try:
                    directory_stat = directory.stat(follow_symlinks=False)
                except OSError as exc:
                    raise RemoteBrokerError(
                        "release_check_invalid",
                        "worktree attributes search cannot inspect a directory",
                    ) from exc
                if stat.S_ISLNK(directory_stat.st_mode) or _is_reparse_point(
                    directory_stat
                ):
                    continue
                if stat.S_ISDIR(directory_stat.st_mode):
                    retained_directories.append(directory_name)
            directory_names[:] = retained_directories
            if ".gitattributes" not in file_names:
                continue
            attributes_path = current / ".gitattributes"
            relative = attributes_path.relative_to(self._repository_root).as_posix()
            safe_attributes_path = _safe_repository_entry(
                self._repository_root,
                relative,
                label="worktree Git attributes",
                expect_file=True,
            )
            self._attribute_payload_uses_execution_features(
                _read_stable_regular_bytes(
                    safe_attributes_path,
                    label="worktree Git attributes",
                    maximum_bytes=MAX_CONTROL_JSON_BYTES,
                    allow_empty=True,
                ),
                label="worktree Git attributes",
            )

    def _validate_tracked_harness(self) -> tuple[Path, bytes, Path, bytes]:
        def tracked_path(relative: str, *, label: str) -> tuple[Path, bytes]:
            path = _safe_repository_entry(
                self._repository_root,
                relative,
                label=label,
                expect_file=True,
            )
            tracked = self._local_git(
                "ls-files", "--error-unmatch", "--", relative
            ).strip()
            if tracked != relative:
                raise RemoteBrokerError(
                    "release_check_invalid", f"{label} is not tracked"
                )
            worktree_bytes = _read_stable_regular_bytes(
                path,
                label=label,
                maximum_bytes=MAX_TRACKED_HARNESS_BYTES,
            )
            head_bytes = self._local_git_bytes(
                "cat-file",
                "blob",
                f"HEAD:{relative}",
                output_limit=MAX_TRACKED_HARNESS_BYTES,
            )
            worktree_sha256 = hashlib.sha256(worktree_bytes).digest()
            head_sha256 = hashlib.sha256(head_bytes).digest()
            if (
                len(head_bytes) > MAX_TRACKED_HARNESS_BYTES
                or not hmac.compare_digest(worktree_sha256, head_sha256)
                or not hmac.compare_digest(worktree_bytes, head_bytes)
            ):
                raise RemoteBrokerError(
                    "release_check_invalid",
                    f"{label} differs from the clean release commit",
                )
            return path, worktree_bytes

        harness_path, harness_bytes = tracked_path(
            "scripts/harness.py", label="release-check executable"
        )
        remote_path, remote_bytes = tracked_path(
            "scripts/harness_remote.py", label="remote broker module"
        )
        scripts_directory = _safe_repository_entry(
            self._repository_root,
            "scripts",
            label="Harness scripts directory",
            expect_file=False,
        )
        stdlib_names = {name.casefold() for name in sys.stdlib_module_names}
        try:
            entries = tuple(scripts_directory.iterdir())
        except OSError as exc:
            raise RemoteBrokerError(
                "release_check_invalid", "Harness scripts directory cannot be inspected"
            ) from exc
        for entry in entries:
            name = entry.name.casefold()
            stem = entry.stem.casefold()
            try:
                entry_stat = entry.lstat()
            except OSError as exc:
                raise RemoteBrokerError(
                    "release_check_invalid",
                    "Harness scripts directory entry cannot be inspected",
                ) from exc
            if stat.S_ISLNK(entry_stat.st_mode) or _is_reparse_point(entry_stat):
                raise RemoteBrokerError(
                    "release_check_invalid",
                    "Harness scripts directory contains a redirecting entry",
                )
            if (
                name in {"sitecustomize.py", "usercustomize.py"}
                or (
                    stem in stdlib_names
                    and (
                        stat.S_ISDIR(entry_stat.st_mode)
                        or entry.suffix.casefold() in {".py", ".pyc", ".pyd", ".so"}
                    )
                )
            ):
                raise RemoteBrokerError(
                    "release_check_invalid",
                    "Harness scripts directory contains a Python stdlib shadow",
                )
        return harness_path, harness_bytes, remote_path, remote_bytes

    def _run_release_check(self) -> None:
        self._validate_git_execution_policy()
        (
            harness_path,
            harness_bytes,
            remote_path,
            remote_bytes,
        ) = self._validate_tracked_harness()
        with tempfile.TemporaryFile(mode="w+b") as verified_sources:
            verified_sources.write(len(remote_bytes).to_bytes(8, "big"))
            verified_sources.write(remote_bytes)
            verified_sources.write(len(harness_bytes).to_bytes(8, "big"))
            verified_sources.write(harness_bytes)
            verified_sources.flush()
            os.fsync(verified_sources.fileno())
            verified_sources.seek(0)
            outcome = _run_bounded_process(
                (
                    str(self._python_executable),
                    "-X",
                    "utf8",
                    "-I",
                    "-S",
                    "-B",
                    "-c",
                    _RELEASE_CHECK_LAUNCHER,
                    str(harness_path),
                    str(remote_path),
                    "release-check",
                    self._task["id"],
                    "--json",
                ),
                180,
                HARD_MAX_OUTPUT_BYTES,
                cwd=self._repository_root,
                environment=_minimal_git_environment(
                    self._git_executable, self._repository_root
                ),
                stdin_handle=verified_sources,
            )
        if (
            outcome.launch_error
            or outcome.timed_out
            or outcome.output_limited
            or outcome.exit_code != 0
            or outcome.stderr
        ):
            raise RemoteBrokerError(
                "release_check_failed",
                "tracked Harness release-check did not pass",
            )
        try:
            payload = json.loads(outcome.stdout.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RemoteBrokerError(
                "release_check_failed", "release-check output is not valid JSON"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("name") != "release-check"
            or payload.get("ok") is not True
            or payload.get("errors") != []
            or not isinstance(payload.get("data"), dict)
            or payload["data"].get("task_id") != self._task["id"]
        ):
            raise RemoteBrokerError(
                "release_check_failed",
                "release-check did not prove the current task ready",
            )

    def _validate_release_git_identity(self, release_commit: str) -> None:
        self._validate_git_execution_policy()
        head = self._local_git("rev-parse", "--verify", "HEAD").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", head) or not hmac.compare_digest(
            head.casefold(), release_commit.casefold()
        ):
            raise RemoteBrokerError(
                "release_seal_invalid", "current Git HEAD differs from the release seal"
            )
        dirty = self._local_git(
            "status", "--porcelain=v1", "--untracked-files=all"
        )
        if dirty.strip():
            raise RemoteBrokerError(
                "release_seal_invalid", "mutating execution requires a clean worktree"
            )
        self._validate_tracked_harness()

    def _validate_mutating_repository_seal(self) -> None:
        state = self._active_state
        release_commit = state.get("release_commit")
        if not isinstance(release_commit, str) or not re.fullmatch(
            r"[0-9a-fA-F]{40,64}", release_commit
        ):
            raise RemoteBrokerError(
                "release_seal_invalid", "active state lacks a valid release commit"
            )
        if state.get("release_contract_sha256") != _immutable_contract_hash(self._task):
            raise RemoteBrokerError(
                "release_seal_invalid", "release contract hash does not match the task"
            )
        if state.get("release_policy_sha256") != _policy_contract_hash(self._task):
            raise RemoteBrokerError(
                "release_seal_invalid", "release policy hash does not match the task"
            )
        _parse_rfc3339(
            state.get("release_sealed_at"), label="active_state.release_sealed_at"
        )
        self._validate_release_git_identity(release_commit)
        sealed_artifacts = state.get("release_upload_artifacts")
        if not isinstance(sealed_artifacts, list):
            raise RemoteBrokerError(
                "release_seal_invalid", "release seal lacks upload artifact facts"
            )
        actual_artifacts = self.release_upload_artifact_facts(
            self._task["id"]
        )
        if sealed_artifacts != actual_artifacts:
            raise RemoteBrokerError(
                "artifact_drift",
                "release upload artifacts differ from their sealed size or SHA-256",
            )
        self._sealed_upload_artifacts = {
            item["action_id"]: copy.deepcopy(item) for item in actual_artifacts
        }
        self._run_release_check()
        # The gate is an isolated subprocess.  Recheck HEAD, cleanliness and
        # the tracked gate after it exits so environment/config hooks cannot
        # silently alter the release snapshot.
        self._validate_release_git_identity(release_commit)
        if self.release_upload_artifact_facts(
            self._task["id"]
        ) != actual_artifacts:
            raise RemoteBrokerError(
                "artifact_drift", "release upload artifacts changed during release-check"
            )
        fresh_task = _read_repository_json(
            self._repository_root,
            f".harness/tasks/{self._task['id']}/task.json",
            label="task contract",
        )
        fresh_state = _read_repository_json(
            self._repository_root,
            ".harness/state/active-task.json",
            label="active task state",
        )
        if fresh_task != self._task or fresh_state != self._active_state:
            raise RemoteBrokerError(
                "contract_drift",
                "task or active state changed during release validation",
            )

    def _validate_local_runtime_path(self, action: ActionSpec) -> Path:
        assert action.direction in {"upload", "download"}
        assert action.source is not None and action.destination is not None
        local_text = action.source if action.direction == "upload" else action.destination
        local_path = self._validate_local_contract_path(local_text, label=f"action {action.action_id} local path")
        if action.direction == "upload":
            try:
                local_stat = local_path.lstat()
            except OSError as exc:
                raise RemoteBrokerError("unsafe_local_path", "upload source is unavailable") from exc
            if stat.S_ISLNK(local_stat.st_mode) or _is_reparse_point(local_stat):
                raise RemoteBrokerError("unsafe_local_path", "upload source may not redirect")
            if not stat.S_ISREG(local_stat.st_mode):
                raise RemoteBrokerError("unsafe_local_path", "upload source must be a regular file")
            if not _same_path(local_path.resolve(strict=True), local_path.absolute()):
                raise RemoteBrokerError("unsafe_local_path", "upload source parent path may not redirect")
        else:
            parent = local_path.parent
            try:
                parent_relative = parent.relative_to(self._repository_root).as_posix()
            except ValueError as exc:
                raise RemoteBrokerError(
                    "unsafe_local_path", "download destination parent escaped the repository"
                ) from exc
            _safe_repository_entry(
                self._repository_root,
                parent_relative,
                label="download destination parent",
                expect_file=False,
            )
            try:
                local_path.lstat()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise RemoteBrokerError(
                    "unsafe_local_path", "download destination cannot be inspected"
                ) from exc
            else:
                raise RemoteBrokerError(
                    "unsafe_local_path",
                    "download destination must be a new evidence file",
                )
        return local_path

    @staticmethod
    def _hash_open_handle(handle: BinaryIO, *, label: str) -> tuple[int, str]:
        try:
            before = os.fstat(handle.fileno())
            handle.seek(0)
            digest = hashlib.sha256()
            bytes_read = 0
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                bytes_read += len(chunk)
            after = os.fstat(handle.fileno())
            handle.seek(0)
        except (OSError, ValueError) as exc:
            raise RemoteBrokerError(
                "artifact_drift", f"{label} stable handle cannot be verified"
            ) from exc
        before_facts = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        after_facts = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if before_facts != after_facts or bytes_read != before.st_size:
            raise RemoteBrokerError(
                "artifact_drift", f"{label} changed while its handle was read"
            )
        return bytes_read, digest.hexdigest()

    def _prepare_download_stage(self, action: ActionSpec) -> _DownloadStage:
        assert action.direction == "download" and action.destination is not None
        destination = self._validate_local_runtime_path(action)
        parent = destination.parent
        stage_directory: Path | None = None
        for _attempt in range(8):
            candidate = parent / f".broker-download-{uuid.uuid4().hex}"
            try:
                candidate.mkdir(mode=0o700)
            except FileExistsError:
                continue
            except OSError as exc:
                raise RemoteBrokerError(
                    "unsafe_local_path",
                    "broker download staging directory cannot be created",
                ) from exc
            stage_directory = candidate
            break
        if stage_directory is None:
            raise RemoteBrokerError(
                "artifact_stage_conflict",
                "exclusive broker download staging directory is unavailable",
            )

        stage_path = stage_directory / "payload.download"
        write_flags = (
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            directory_stat = stage_directory.stat(follow_symlinks=False)
            if (
                stat.S_ISLNK(directory_stat.st_mode)
                or _is_reparse_point(directory_stat)
                or not stat.S_ISDIR(directory_stat.st_mode)
                or not _same_path(
                    stage_directory.resolve(strict=True), stage_directory.absolute()
                )
            ):
                raise RemoteBrokerError(
                    "unsafe_local_path", "download staging directory may redirect"
                )
            descriptor = os.open(stage_path, write_flags, 0o600)
            handle = os.fdopen(descriptor, "w+b", closefd=True)
            handle_stat = os.fstat(handle.fileno())
            path_stat = stage_path.stat(follow_symlinks=False)
            if (
                not stat.S_ISREG(handle_stat.st_mode)
                or handle_stat.st_nlink != 1
                or not os.path.samestat(handle_stat, path_stat)
            ):
                raise RemoteBrokerError(
                    "unsafe_local_path",
                    "download staging file lacks a unique stable identity",
                )
        except RemoteBrokerError:
            if "handle" in locals():
                handle.close()
            try:
                stage_path.unlink(missing_ok=True)
                stage_directory.rmdir()
            except OSError:
                pass
            raise
        except OSError as exc:
            if "handle" in locals():
                handle.close()
            try:
                stage_path.unlink(missing_ok=True)
                stage_directory.rmdir()
            except OSError:
                pass
            raise RemoteBrokerError(
                "unsafe_local_path",
                "broker download staging file cannot be created safely",
            ) from exc
        return _DownloadStage(
            directory=stage_directory,
            directory_stat=directory_stat,
            path=stage_path,
            handle=handle,
            destination=destination,
        )

    def _publish_download_stage(
        self, action: ActionSpec, stage: _DownloadStage
    ) -> dict[str, Any]:
        try:
            stage.handle.flush()
            os.fsync(stage.handle.fileno())
            handle_stat = os.fstat(stage.handle.fileno())
            path_stat = stage.path.stat(follow_symlinks=False)
            directory_stat = stage.directory.stat(follow_symlinks=False)
        except (OSError, ValueError) as exc:
            raise RemoteBrokerError(
                "download_verification_failed",
                "download staging file cannot be verified",
            ) from exc
        if (
            not stat.S_ISREG(handle_stat.st_mode)
            or stat.S_ISLNK(path_stat.st_mode)
            or _is_reparse_point(path_stat)
            or handle_stat.st_nlink != 1
            or not os.path.samestat(handle_stat, path_stat)
            or not os.path.samestat(stage.directory_stat, directory_stat)
            or handle_stat.st_size > HARD_MAX_DOWNLOAD_BYTES
        ):
            raise RemoteBrokerError(
                "download_verification_failed",
                "download staging identity, link count, or size is invalid",
            )
        size, sha256 = self._hash_open_handle(
            stage.handle, label="broker download staging file"
        )
        if size > HARD_MAX_DOWNLOAD_BYTES:
            raise RemoteBrokerError(
                "download_verification_failed", "download exceeds the fixed size limit"
            )

        # Revalidate the contracted parent and absence immediately before the
        # create-if-absent publication operation.
        runtime_destination = self._validate_local_runtime_path(action)
        if runtime_destination != stage.destination:
            raise RemoteBrokerError(
                "download_verification_failed", "download destination contract drifted"
            )
        try:
            os.link(stage.path, stage.destination, follow_symlinks=False)
            stage.destination_linked = True
        except FileExistsError as exc:
            raise RemoteBrokerError(
                "download_destination_conflict",
                "download destination appeared before atomic publication",
            ) from exc
        except OSError as exc:
            raise RemoteBrokerError(
                "download_publish_failed",
                "download cannot be published atomically without overwrite",
            ) from exc
        try:
            linked_stat = stage.destination.stat(follow_symlinks=False)
            linked_handle_stat = os.fstat(stage.handle.fileno())
        except (OSError, ValueError) as exc:
            raise RemoteBrokerError(
                "download_verification_failed",
                "published download identity cannot be verified",
            ) from exc
        if (
            stat.S_ISLNK(linked_stat.st_mode)
            or _is_reparse_point(linked_stat)
            or not stat.S_ISREG(linked_stat.st_mode)
            or linked_handle_stat.st_nlink != 2
            or not os.path.samestat(linked_handle_stat, linked_stat)
        ):
            raise RemoteBrokerError(
                "download_verification_failed",
                "published download does not match its stable staging handle",
            )
        stage.keep_destination = True
        return {
            "size": size,
            "sha256": sha256,
            "stable_handle_verified": True,
            "unique_stage_link_verified": True,
            "atomic_no_overwrite_publish_confirmed": True,
            "wire_transport": "ssh_stdout_to_stable_handle",
        }

    def _prepare_upload_stage(self, action: ActionSpec) -> _UploadStage:
        assert action.direction == "upload" and action.source is not None
        sealed = self._sealed_upload_artifacts.get(action.action_id)
        if (
            not isinstance(sealed, dict)
            or set(sealed) != {"action_id", "repo_path", "size", "sha256"}
            or sealed.get("action_id") != action.action_id
            or sealed.get("repo_path") != action.source
            or type(sealed.get("size")) is not int
            or sealed["size"] < 0
            or not isinstance(sealed.get("sha256"), str)
            or not HEX_SHA256_RE.fullmatch(sealed["sha256"])
        ):
            raise RemoteBrokerError(
                "release_seal_invalid", "upload action lacks exact sealed artifact facts"
            )
        source_path = self._validate_local_runtime_path(action)
        open_read_flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            source_descriptor = os.open(source_path, open_read_flags)
            source_handle = os.fdopen(source_descriptor, "rb", closefd=True)
        except OSError as exc:
            raise RemoteBrokerError(
                "unsafe_local_path", "sealed upload source cannot be opened safely"
            ) from exc

        task_id = self._task["id"]
        run_relative = f".harness/runs/{task_id}"
        run_root = _safe_repository_entry(
            self._repository_root,
            run_relative,
            label="upload run root",
            expect_file=False,
        )
        stage_directory = run_root / ".broker-upload-staging"
        try:
            stage_directory.mkdir(mode=0o700, exist_ok=True)
        except OSError as exc:
            source_handle.close()
            raise RemoteBrokerError(
                "unsafe_local_path", "broker upload staging directory is unavailable"
            ) from exc
        try:
            _safe_repository_entry(
                self._repository_root,
                f"{run_relative}/.broker-upload-staging",
                label="upload staging directory",
                expect_file=False,
            )
        except RemoteBrokerError:
            source_handle.close()
            raise
        stage_path = stage_directory / f"{sealed['sha256']}.{sealed['size']}.upload"
        write_flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        stage_created = False
        try:
            source_before = os.fstat(source_handle.fileno())
            source_path_before = source_path.stat(follow_symlinks=False)
            if not os.path.samestat(source_before, source_path_before):
                raise RemoteBrokerError(
                    "artifact_drift", "sealed upload source was replaced before staging"
                )
            stage_descriptor = os.open(stage_path, write_flags, 0o600)
            stage_created = True
            digest = hashlib.sha256()
            bytes_written = 0
            with os.fdopen(stage_descriptor, "wb", closefd=True) as writer:
                while True:
                    chunk = source_handle.read(1024 * 1024)
                    if not chunk:
                        break
                    writer.write(chunk)
                    digest.update(chunk)
                    bytes_written += len(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            source_after = os.fstat(source_handle.fileno())
            source_path_after = source_path.stat(follow_symlinks=False)
            if (
                not os.path.samestat(source_before, source_after)
                or not os.path.samestat(source_after, source_path_after)
                or source_before.st_size != source_after.st_size
                or source_before.st_mtime_ns != source_after.st_mtime_ns
            ):
                raise RemoteBrokerError(
                    "artifact_drift", "sealed upload source changed during staging"
                )
            if (
                bytes_written != sealed["size"]
                or not hmac.compare_digest(digest.hexdigest(), sealed["sha256"])
            ):
                raise RemoteBrokerError(
                    "artifact_drift", "staged upload differs from its release seal"
                )
        except FileExistsError as exc:
            raise RemoteBrokerError(
                "artifact_stage_conflict",
                "exclusive content-addressed upload staging file already exists",
            ) from exc
        except RemoteBrokerError:
            if stage_created:
                try:
                    stage_path.unlink()
                except OSError:
                    pass
            raise
        except OSError as exc:
            if stage_created:
                try:
                    stage_path.unlink()
                except OSError:
                    pass
            raise RemoteBrokerError(
                "artifact_drift", "sealed upload could not be staged"
            ) from exc
        finally:
            source_handle.close()

        try:
            stage_descriptor = os.open(stage_path, open_read_flags)
            stage_handle = os.fdopen(stage_descriptor, "rb", closefd=True)
            stage_stat = os.fstat(stage_handle.fileno())
            stage_path_stat = stage_path.stat(follow_symlinks=False)
            if (
                not stat.S_ISREG(stage_stat.st_mode)
                or not os.path.samestat(stage_stat, stage_path_stat)
            ):
                raise RemoteBrokerError(
                    "artifact_drift", "broker upload staging path was replaced"
                )
            actual_size, actual_sha256 = self._hash_open_handle(
                stage_handle, label="broker upload staging file"
            )
            if actual_size != sealed["size"] or not hmac.compare_digest(
                actual_sha256, sealed["sha256"]
            ):
                raise RemoteBrokerError(
                    "artifact_drift", "broker upload staging verification failed"
                )
        except Exception:
            if "stage_handle" in locals():
                stage_handle.close()
            if stage_created:
                try:
                    stage_path.unlink()
                except OSError:
                    pass
            raise
        return _UploadStage(
            path=stage_path,
            handle=stage_handle,
            repo_path=sealed["repo_path"],
            size=sealed["size"],
            sha256=sealed["sha256"],
        )

    def _upload_remote_command(self, action: ActionSpec, stage: _UploadStage) -> str:
        assert action.destination is not None
        destination = action.destination
        parent = str(PurePosixPath(destination).parent)
        template = f"{parent}/.harness-upload-{stage.sha256[:16]}.XXXXXX"
        receipt = f"HARNESS_UPLOAD_VERIFIED {stage.sha256} {stage.size}"
        return " ".join(
            (
                "set -eu;",
                "umask 077;",
                f"staging=$(mktemp -- {shlex.quote(template)});",
                "trap 'rm -f -- \"$staging\"' 0 1 2 15;",
                "cat > \"$staging\";",
                "actual_size=$(stat -c %s -- \"$staging\");",
                "actual_sha=$(sha256sum -- \"$staging\");",
                "actual_sha=${actual_sha%% *};",
                f"[ \"$actual_size\" = {shlex.quote(str(stage.size))} ];",
                f"[ \"$actual_sha\" = {shlex.quote(stage.sha256)} ];",
                f"mv -fT -- \"$staging\" {shlex.quote(destination)};",
                "trap - 0 1 2 15;",
                f"printf '%s\\n' {shlex.quote(receipt)}",
            )
        )

    def _common_open_ssh_options(self) -> list[str]:
        return [
            "-F",
            "none",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={_open_ssh_path(self._known_hosts_path)}",
            "-o",
            "GlobalKnownHostsFile=none",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "IdentityAgent=none",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "CanonicalizeHostname=no",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ForwardX11=no",
            "-o",
            "UpdateHostKeys=no",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "PubkeyAuthentication=yes",
            "-o",
            "ConnectionAttempts=1",
            "-i",
            _open_ssh_path(self._identity_path),
        ]

    def _ssh_destination(self) -> str:
        return f"{self._user}@{self._host}"

    def _build_system_argv(
        self,
        action: ActionSpec,
        *,
        upload_stage: _UploadStage | None = None,
        download_stage: _DownloadStage | None = None,
    ) -> tuple[str, ...]:
        options = self._common_open_ssh_options()
        connect_timeout = max(1, min(15, action.timeout_seconds))
        options.extend(["-o", f"ConnectTimeout={connect_timeout}"])
        if action.transport == "ssh":
            assert action.cwd is not None and action.argv
            if self._is_deployment_root_bootstrap(action):
                # The deployment root is the sole cwd that may not exist yet.
                # The exact mkdir action is therefore executed without a prior
                # cd; every other SSH action retains the cd-before-exec rule.
                remote_command = f"exec {shlex.join(action.argv)}"
            else:
                remote_command = (
                    f"cd -- {shlex.quote(action.cwd)} && exec {shlex.join(action.argv)}"
                )
            return tuple(
                [
                    str(self._ssh_executable),
                    *options,
                    "-p",
                    str(self._port),
                    "-T",
                    "--",
                    self._ssh_destination(),
                    remote_command,
                ]
            )

        assert action.direction in {"upload", "download"}
        assert action.source is not None and action.destination is not None
        if action.direction == "upload":
            if upload_stage is None:
                raise RemoteBrokerError(
                    "artifact_drift", "upload requires a verified stable staging handle"
                )
            remote_command = self._upload_remote_command(action, upload_stage)
            return tuple(
                [
                    str(self._ssh_executable),
                    *options,
                    "-p",
                    str(self._port),
                    "-T",
                    "--",
                    self._ssh_destination(),
                    remote_command,
                ]
            )

        if upload_stage is not None:
            raise RemoteBrokerError(
                "invalid_request", "upload staging handle supplied to a download"
            )
        if download_stage is None:
            raise RemoteBrokerError(
                "download_verification_failed",
                "download requires an exclusive stable staging handle",
            )
        if action.source is None:
            raise RemoteBrokerError(
                "invalid_contract", "download source is unavailable"
            )
        remote_command = f"exec cat -- {shlex.quote(action.source)}"
        return tuple(
            [
                str(self._ssh_executable),
                *options,
                "-p",
                str(self._port),
                "-T",
                "--",
                self._ssh_destination(),
                remote_command,
            ]
        )

    def _build_evidence(
        self,
        action: ActionSpec,
        outcome: ProcessOutcome,
        started_at: dt.datetime,
        finished_at: dt.datetime,
    ) -> dict[str, Any]:
        stdout = outcome.stdout.decode("utf-8", errors="replace")
        stderr = outcome.stderr.decode("utf-8", errors="replace")
        stdout = _redact_output(stdout, (self._identity_path, self._known_hosts_path))
        stderr = _redact_output(stderr, (self._identity_path, self._known_hosts_path))
        if outcome.output_limited:
            marker = "\n[OUTPUT TRUNCATED BY HARNESS REMOTE BROKER]"
            stdout += marker
            stderr += marker

        if outcome.launch_error:
            failure_kind = "launch_error"
        elif outcome.timed_out:
            failure_kind = "timeout"
        elif outcome.output_limited:
            failure_kind = "output_limit"
        elif outcome.exit_code != 0:
            failure_kind = "nonzero_exit"
        else:
            failure_kind = None
        success = failure_kind is None

        logical_action: dict[str, Any] = {
            "id": action.action_id,
            "transport": action.transport,
            "mode": action.mode,
            "timeout_seconds": action.timeout_seconds,
        }
        if action.transport == "ssh":
            logical_action["cwd"] = action.cwd
            logical_action["argv"] = list(action.argv)
        else:
            logical_action["direction"] = action.direction
            logical_action["source"] = action.source
            logical_action["destination"] = action.destination

        authorization = self._remote["authorization"]
        return {
            "schema_version": 1,
            "kind": "harness_remote_execution",
            "task_id": self._task["id"],
            "authorization": {
                "mode": authorization["mode"],
                "thread_id": authorization["thread_id"],
                "authorized_at": authorization["authorized_at"],
            },
            "target": {
                "environment": self._remote["environment"],
                "host": self._host,
                "port": self._port,
                "user": self._user,
                "host_key_fingerprint": self._fingerprint,
            },
            "action": logical_action,
            "action_sha256": _canonical_json_hash(logical_action),
            "started_at": started_at.isoformat().replace("+00:00", "Z"),
            "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
            "duration_ms": outcome.duration_ms,
            "exit_code": outcome.exit_code,
            "success": success,
            "failure_kind": failure_kind,
            "timed_out": outcome.timed_out,
            "output_limited": outcome.output_limited,
            "stdout_bytes": outcome.stdout_bytes,
            "stderr_bytes": outcome.stderr_bytes,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
            "transport_policy": {
                "ssh_config": "none",
                "strict_host_key_checking": True,
                "user_known_hosts_file": "external_reference",
                "global_known_hosts_file": "none",
                "identities_only": True,
                "identity_agent": "none",
                "proxy_command": "none",
                "proxy_jump": "none",
                "batch_mode": True,
            },
        }


def main() -> int:
    print(
        "harness_remote.py has no standalone CLI; invoke it through scripts/harness.py",
        file=os.sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

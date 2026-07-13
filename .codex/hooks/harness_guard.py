#!/usr/bin/env python3
"""Project-local Codex hook for session guidance and fast safety checks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any


# Codex hook stdio is a JSON protocol and must not inherit the Windows GBK
# console encoding.  Reconfigure explicitly so Chinese context and paths remain
# valid UTF-8 in both directions.
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")


ROOT = Path(os.path.abspath(__file__)).parents[2]
STATE_FILE = ROOT / ".harness" / "state" / "active-task.json"
TASKS_DIR = ROOT / ".harness" / "tasks"
DECISIONS_FILE = ROOT / ".harness" / "requirements-decisions.json"
TASK_ID_RE = re.compile(r"^NUR-(?:FEAT|BUG|UI|DATA|SEC|OPS|DOC|REFACTOR|HARNESS)-\d{3}$")

BOOTSTRAP_PATTERNS = (
    ".agents/**",
    ".codex/**",
    ".harness/**",
    ".github/**",
    "docs/product/BUSINESS_RULES.md",
    "docs/product/REQUIREMENTS_TRACEABILITY.md",
    "docs/architecture/SHOPXO_BOUNDARY.md",
    "AGENTS.md",
    "HARNESS.md",
    "shopxo_nursery_harness_spec.md",
    "ShopXO苗木平台需求规格说明书_V1.0.md",
    ".gitignore",
    "scripts/harness.py",
    "scripts/harness_remote.py",
    "scripts/harness_remote_selftest.py",
    "scripts/harness_selftest.py",
    "scripts/harness.ps1",
    "scripts/harness.sh",
)

PLAN_ARTIFACT_NAMES = (
    "requirement.md",
    "impact-analysis.md",
    "implementation-plan.md",
    "test-plan.md",
)

TASK_CONTRACT_EDITABLE_STATUSES = frozenset({"draft", "ready_for_analysis"})
TASK_CONTRACT_LOCKED_STATUSES = frozenset(
    {
        "awaiting_plan_approval",
        "approved_for_implementation",
        "implementing",
        "verifying",
        "awaiting_review",
        "approved_for_merge",
        "closed",
        "blocked",
        "cancelled",
    }
)

SHELL_NETWORK_CLIENT_BASENAMES = frozenset(
    {
        "ssh",
        "scp",
        "sftp",
        "curl",
        "wget",
        "ftp",
        "nc",
        "ncat",
        "telnet",
        "plink",
        "pscp",
        "invoke-webrequest",
        "invoke-restmethod",
        "iwr",
        "irm",
        "start-bitstransfer",
        "test-netconnection",
        "resolve-dnsname",
    }
)
SHELL_DYNAMIC_EXECUTION_BASENAMES = frozenset({"invoke-expression", "iex"})
SHELL_POWERSHELL_BASENAMES = frozenset({"powershell", "powershell_ise", "pwsh"})
SHELL_EXECUTABLE_SUFFIXES = (".exe", ".com", ".cmd", ".bat", ".ps1")
SHELL_TOKEN_SPLIT_RE = re.compile(r"[\s\"'`=,:;|&(){}\[\]<>]+")
SHELL_WORD_RE = re.compile(
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[^\s]+'
)
SHELL_STRING_LITERAL_RE = re.compile(
    r'"(?P<double>(?:\\.|[^"\\])*)"|'
    r"'(?P<single>(?:\\.|[^'\\])*)'|"
    r"`(?P<backtick>(?:\\.|[^`\\])*)`"
)
JS_COMMAND_LITERAL_RE = re.compile(
    r"(?i)\bcommand\s*:\s*(?:"
    r'"(?P<double>(?:\\.|[^"\\])*)"|'
    r"'(?P<single>(?:\\.|[^'\\])*)'|"
    r"`(?P<backtick>(?:\\.|[^`\\])*)`"
    r")"
)
DOTNET_NETWORK_TYPE_RE = re.compile(
    r"(?i)\b(?:System\.)?Net\."
    r"(?:WebClient|WebRequest|HttpWebRequest|Dns|Http\.HttpClient|Sockets\b)"
)
DOTNET_SHORT_NETWORK_TYPE_RE = re.compile(
    r"(?i)(?:\[\s*|\bNew-Object\s+(?:-TypeName\s+)?)"
    r"(?:WebClient|HttpClient|WebRequest|HttpWebRequest|TcpClient|UdpClient|Dns)\b"
)
POWERSHELL_ENCODED_COMMAND_RE = re.compile(
    r"(?i)(?:^|[\s\"'`])[-/](?:EncodedCommand|Enc)\b"
)
POWERSHELL_DYNAMIC_CALL_RE = re.compile(
    r"(?is)(?<!&)&\s*(?:\(|\{|\[|\$(?:\{|[A-Za-z_]))"
)
POWERSHELL_STRING_CONCAT_RE = re.compile(
    r"(?is)(?P<expression>"
    r"(?:(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')\s*\+\s*)+"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
    r")"
)
POWERSHELL_CONCAT_CALL_RE = re.compile(
    r"(?is)(?:(?:\[(?:System\.)?String\])::|(?:System\.)?String\.)"
    r"Concat\s*\((?P<arguments>[^)]{0,2048})\)"
)
POWERSHELL_DYNAMIC_START_RE = re.compile(
    r"(?is)\bStart-Process\b[^\r\n;|]{0,512}"
    r"(?:\(|\$(?:\{|[A-Za-z_])|\[\s*(?:System\.)?String\s*\]::\s*Concat\b|"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')\s*\+)"
)
GIT_UNCONDITIONAL_WRITE_SUBCOMMANDS = frozenset(
    {
        "hash-object",
        "update-index",
        "write-tree",
        "commit-tree",
        "update-ref",
        "read-tree",
        "checkout-index",
        "fast-import",
        "mktree",
        "replace",
    }
)
GIT_EXISTING_BLOCKED_SUBCOMMANDS = frozenset(
    {
        "apply",
        "am",
        "checkout",
        "restore",
        "reset",
        "clean",
        "stash",
        "merge",
        "rebase",
        "cherry-pick",
        "revert",
    }
)
GIT_NOTES_WRITE_ACTIONS = frozenset(
    {"add", "append", "copy", "edit", "merge", "prune", "remove"}
)
GIT_WORKTREE_WRITE_ACTIONS = frozenset(
    {"add", "lock", "move", "prune", "remove", "repair", "unlock"}
)
GIT_CONFIG_WRITE_FLAGS = frozenset(
    {
        "--add",
        "--replace-all",
        "--unset",
        "--unset-all",
        "--rename-section",
        "--remove-section",
        "--edit",
        "-e",
    }
)
GIT_CONFIG_WRITE_ACTIONS = frozenset(
    {"set", "unset", "rename-section", "remove-section", "edit"}
)
GIT_CONFIG_READ_ACTIONS = frozenset({"get", "list"})
GIT_CONFIG_READ_FLAGS = frozenset(
    {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l"}
)
GIT_ENV_CONFIG_INJECTION_RE = re.compile(
    r"(?i)\bGIT_CONFIG_(?:COUNT|KEY_\d+|VALUE_\d+|PARAMETERS|SYSTEM|GLOBAL)\b"
)
EXACT_HARNESS_REMOTE_CLI_RE = re.compile(
    r"^\s*python\s+-I\s+-S\s+-B\s+scripts[\\/]+harness\.py\s+(?:"
    r"(?:remote-actions|release-seal|release-check)\s+"
    r"NUR-(?:FEAT|BUG|UI|DATA|SEC|OPS|DOC|REFACTOR|HARNESS)-\d{3}"
    r"(?:\s+--base-ref\s+[^\s]+)?(?:\s+--json)?|"
    r"remote-exec\s+"
    r"NUR-(?:FEAT|BUG|UI|DATA|SEC|OPS|DOC|REFACTOR|HARNESS)-\d{3}\s+"
    r"[a-z][a-z0-9_-]{2,63}"
    r"(?:\s+(?:--allow-mutating|--json)){0,2}"
    r")\s*$",
    re.I,
)
SENSITIVE_HARNESS_CLI_FRAGMENT_RE = re.compile(
    r"(?i)\bscripts[\\/]+harness\.py\s+"
    r"(?:remote-actions|remote-exec|release-seal|release-check)\b"
)


def path_is_link_like(path: Path) -> bool:
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


def repository_root_safety_error() -> str | None:
    root = Path(os.path.abspath(os.fspath(ROOT)))
    components: list[Path] = []
    current = root
    while current.parent != current:
        components.append(current)
        current = current.parent
    for component in reversed(components):
        if path_is_link_like(component):
            return f"仓库根路径经过符号链接、目录联接或 reparse point：{component}"
    try:
        root.resolve(strict=True)
    except OSError as exc:
        return f"仓库根路径无法安全解析：{exc}"
    return None

SHELL_BLOCK_PATTERNS = (
    (
        re.compile(r"\bgit\s+reset\s+--hard\b", re.I),
        "禁止破坏性重置工作区。",
    ),
    (
        re.compile(r"\bgit\s+clean\s+-[^\r\n;]*f", re.I),
        "禁止强制清理未跟踪文件。",
    ),
    (
        re.compile(r"\bgit\s+push\b[^\r\n;]*(?:--force|-f\b)", re.I),
        "禁止强制推送。",
    ),
    (
        re.compile(r"\bgit\s+(?:checkout\s+--|restore\s+(?:--source\S*\s+)?(?:--worktree\s+)?(?:\.|:\/))", re.I),
        "禁止批量丢弃工作区修改。",
    ),
    (
        re.compile(r"\b(?:drop\s+database|drop\s+table|truncate\s+table)\b", re.I),
        "禁止执行破坏性数据库语句。",
    ),
    (
        re.compile(r"\b(?:terraform\s+destroy|kubectl\s+(?:apply|delete)|vercel\b[^\r\n;]*--prod|netlify\s+deploy\b[^\r\n;]*--prod)\b", re.I),
        "Harness 不允许自动修改或发布生产环境。",
    ),
    (
        re.compile(r"\bcodex\s+(?:mcp\s+(?:add|remove|login|logout)|plugin\s+marketplace)\b", re.I),
        "本项目不得通过命令修改用户级 Codex MCP 或插件配置。",
    ),
    (
        re.compile(
            r"(?:~[/\\]\.codex|\$HOME[/\\]\.codex|%USERPROFILE%[/\\]\.codex|[A-Za-z]:[/\\]Users[/\\][^/\\]+[/\\]\.codex)",
            re.I,
        ),
        "本项目不得修改用户级 .codex 目录。",
    ),
    (
        re.compile(r"\brm\s+-rf\s+(?:/|~|\$HOME)(?:\s|$)", re.I),
        "禁止递归删除系统根目录或用户目录。",
    ),
    (
        re.compile(r"\bRemove-Item\b[^\r\n;]*-Recurse[^\r\n;]*(?:[A-Za-z]:\\\s|\$env:USERPROFILE|~)", re.I),
        "禁止递归删除磁盘根目录或用户目录。",
    ),
)

# Direct shell file mutation is intentionally denied. Repository edits must go
# through apply_patch (where paths can be checked) or the fixed Harness CLI.
SHELL_DIRECT_WRITE_PATTERNS = (
    re.compile(
        r"(?i)(?:^|[\s;|&])(?:Set-Content|Add-Content|Out-File|New-Item|"
        r"Remove-Item|Move-Item|Copy-Item|Rename-Item|Clear-Content)\b"
    ),
    re.compile(
        r"(?i)\[(?:System\.)?IO\.(?:File|Directory)\]::"
        r"(?:Write|Append|Create|Delete|Move|Copy|Replace)\w*\b"
    ),
    re.compile(r"(?m)(?<![<>=])>{1,2}\s*(?![=&])['\"]?[^\s'\"]+"),
    re.compile(r"(?i)(?:^|[\s;|&])(?:tee|touch|mkdir|mktemp|cp|mv|rm|install)\b"),
    re.compile(r"(?i)\b(?:sed\s+-[^\r\n;]*i|perl\s+-[^\r\n;]*pi)\b"),
    re.compile(r"(?i)\bgit\s+(?:apply|am)\b"),
    re.compile(r"(?i)\bgit\s+(?:checkout|restore|reset|clean|stash|merge|rebase|cherry-pick|revert)\b"),
    re.compile(
        r"(?i)\b(?:npm|pnpm|yarn|bun|composer|pip(?:3)?|uv)\s+"
        r"(?:ci|install|update|upgrade|add|remove|uninstall|require|sync|lock|dump-autoload)\b"
    ),
    re.compile(r"(?i)\b(?:tar\s+[^\r\n;]*-[^\r\n;]*x|unzip\b|7z\s+x\b|Expand-Archive\b)"),
    re.compile(
        r"(?i)\b(?:python(?:3)?|py)\s+-c\b|\bphp\s+-r\b|"
        r"\bnode\s+(?:-e|--eval)\b|\bruby\s+-e\b|\bperl\s+-e\b"
    ),
    re.compile(r"(?i)(?:^|[\s;&|])(?:del|erase|copy|move|ren|md|rd|rmdir)\b"),
)


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def block(reason: str) -> None:
    emit(
        {
            "decision": "block",
            "reason": reason,
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            },
        }
    )


def collect_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for child in value.values():
            result.extend(collect_strings(child))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(collect_strings(child))
        return result
    return []


def normalize_repo_path(value: str) -> str:
    value = value.strip().strip('"\'').replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    if not value or "\x00" in value:
        raise ValueError("empty path or NUL")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value) or value.startswith("~"):
        raise ValueError("path must be repository-relative")
    segments = value.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise ValueError("path contains an empty, dot, or parent segment")
    return value


def path_matches(path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    normalized = normalize_repo_path(path).casefold()
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


def extract_patch_paths(text: str) -> list[str]:
    # functions.exec receives JavaScript source before nested tool execution, so
    # a patch string commonly contains literal ``\\n`` escape sequences. Decode
    # only line separators for header inspection; do not evaluate JavaScript.
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    paths: list[str] = []
    for line in text.splitlines():
        match = re.match(
            r"^\*\*\* (?:(?:Add|Update|Delete) File:|Move to:)\s+(.+?)\s*$",
            line,
        )
        if match:
            paths.append(match.group(1).strip().strip('"\''))
    return paths


def task_control_file(path: str) -> tuple[str, str] | None:
    parts = path.split("/")
    if (
        len(parts) == 4
        and parts[0].casefold() == ".harness"
        and parts[1].casefold() == "tasks"
    ):
        return parts[2], parts[3].casefold()
    return None


def existing_task_contract_patch_error(path: str) -> str | None:
    control_file = task_control_file(path)
    if control_file is None or control_file[1] != "task.json":
        return None
    task_id = control_file[0]
    task_path = TASKS_DIR / task_id / "task.json"
    if not task_path.exists():
        return None
    try:
        if path_is_link_like(task_path) or not task_path.is_file():
            raise ValueError("task.json is not a regular repository file")
        task_path.resolve(strict=True).relative_to(ROOT.resolve())
        task = json.loads(task_path.read_text(encoding="utf-8"))
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise ValueError("task id does not match its directory")
        status = task.get("status")
        if not isinstance(status, str):
            raise ValueError("task status is missing or invalid")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return f"已有任务合同无法安全读取，只能由 Harness CLI 修复：{task_id}（{exc}）"
    if status in TASK_CONTRACT_EDITABLE_STATUSES:
        return None
    if status not in TASK_CONTRACT_LOCKED_STATUSES:
        return f"任务 {task_id} 的未知状态 {status} 禁止直接修改 task.json。"
    return (
        f"任务 {task_id} 当前状态 {status} 已锁定 task.json；"
        "请使用 Harness CLI 状态流转，需调整计划时先退回 ready_for_analysis。"
    )


def is_exact_harness_remote_cli(text: str) -> bool:
    return EXACT_HARNESS_REMOTE_CLI_RE.fullmatch(text) is not None


def strip_exact_harness_remote_cli_literals(text: str) -> str:
    if is_exact_harness_remote_cli(text):
        return ""

    def replace(match: re.Match[str]) -> str:
        body = string_literal_body(match)
        return " " if is_exact_harness_remote_cli(body) else match.group(0)

    return SHELL_STRING_LITERAL_RE.sub(replace, text)


def string_literal_body(match: re.Match[str]) -> str:
    for name in ("double", "single", "backtick"):
        body = match.groupdict().get(name)
        if body is not None:
            return body
    return ""


def shell_token_basename(raw_token: str) -> str:
    token = raw_token.strip().strip('"\'`').rstrip(",")
    basename = re.split(r"[\\/]+", token)[-1].casefold()
    for suffix in SHELL_EXECUTABLE_SUFFIXES:
        if basename.endswith(suffix):
            return basename[: -len(suffix)]
    return basename


def shell_network_client(text: str) -> str | None:
    for raw_token in SHELL_TOKEN_SPLIT_RE.split(text):
        if not raw_token:
            continue
        basename = shell_token_basename(raw_token)
        if basename in SHELL_NETWORK_CLIENT_BASENAMES:
            return basename
    return None


def dynamic_client_name(value: str) -> str | None:
    compact = re.sub(r"\s+", "", value)
    if DOTNET_NETWORK_TYPE_RE.search(compact) or DOTNET_SHORT_NETWORK_TYPE_RE.search(
        compact
    ):
        return "dotnet-network"
    basename = shell_token_basename(compact)
    if basename in SHELL_NETWORK_CLIENT_BASENAMES | SHELL_DYNAMIC_EXECUTION_BASENAMES:
        return basename
    return None


def powershell_encoded_command(text: str) -> bool:
    if not any(
        shell_token_basename(raw_token) in SHELL_POWERSHELL_BASENAMES
        for raw_token in SHELL_TOKEN_SPLIT_RE.split(text)
    ):
        return False
    if POWERSHELL_ENCODED_COMMAND_RE.search(text):
        return True
    for raw_token in SHELL_TOKEN_SPLIT_RE.split(text):
        token = raw_token.casefold()
        if not token.startswith(("-", "/")):
            continue
        candidate = token[1:]
        if candidate and "encodedcommand".startswith(candidate):
            return True
    return False


def powershell_dynamic_network_error(text: str) -> str | None:
    if DOTNET_NETWORK_TYPE_RE.search(text) or DOTNET_SHORT_NETWORK_TYPE_RE.search(text):
        return "禁止通过 PowerShell/.NET 网络类型绕过项目远程执行 broker。"
    if powershell_encoded_command(text):
        return "禁止 PowerShell EncodedCommand；编码载荷无法由 Hook 可靠审计。"
    for raw_token in SHELL_TOKEN_SPLIT_RE.split(text):
        if shell_token_basename(raw_token) in SHELL_DYNAMIC_EXECUTION_BASENAMES:
            return "禁止 Invoke-Expression/iex 动态执行；远程动作必须使用固定 Harness CLI。"
    if POWERSHELL_DYNAMIC_CALL_RE.search(text):
        return "禁止 PowerShell 计算型 call operator；不得动态构造可执行客户端。"
    if POWERSHELL_DYNAMIC_START_RE.search(text):
        return "禁止 Start-Process 动态构造可执行客户端。"
    for match in POWERSHELL_STRING_CONCAT_RE.finditer(text):
        joined = "".join(
            string_literal_body(item)
            for item in SHELL_STRING_LITERAL_RE.finditer(match.group("expression"))
        )
        client = dynamic_client_name(joined)
        if client is not None:
            return f"禁止通过字符串拼接动态构造网络/执行客户端 {client}。"
    for match in POWERSHELL_CONCAT_CALL_RE.finditer(text):
        joined = "".join(
            string_literal_body(item)
            for item in SHELL_STRING_LITERAL_RE.finditer(match.group("arguments"))
        )
        client = dynamic_client_name(joined)
        if client is not None:
            return f"禁止通过 String.Concat 动态构造网络/执行客户端 {client}。"
    return None


def shell_words(text: str) -> list[str]:
    words: list[str] = []
    for match in SHELL_WORD_RE.finditer(text):
        value = match.group(0).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        value = value.strip("(),{}[]").rstrip(",")
        if value:
            words.append(value)
    return words


def split_shell_segments(text: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    for character in text:
        if escaped:
            current.append(character)
            escaped = False
            continue
        if quote is not None and character == "\\":
            current.append(character)
            escaped = True
            continue
        if character in {'"', "'", "`"}:
            current.append(character)
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            continue
        if quote is None and character in {"\r", "\n", ";", "|", "&"}:
            segment = "".join(current).strip()
            if segment:
                segments.append(segment)
            current = []
            continue
        current.append(character)
    segment = "".join(current).strip()
    if segment:
        segments.append(segment)
    return segments


def git_command_fragments(text: str) -> list[str]:
    matches = list(JS_COMMAND_LITERAL_RE.finditer(text))
    if matches:
        return [string_literal_body(match) for match in matches]
    return [text]


def git_subcommand(
    words: list[str], git_index: int
) -> tuple[str | None, list[str], str | None]:
    index = git_index + 1
    options_with_values = {"-C", "--git-dir", "--work-tree", "--namespace", "--super-prefix"}
    while index < len(words):
        raw = words[index]
        lowered = raw.casefold()
        if raw == "-C":
            index += 2
            continue
        if raw == "-c" or raw.startswith("-c"):
            return None, [], "禁止 git -c 配置注入；不得动态注入 alias/filter/attributes。"
        if lowered == "--config-env" or lowered.startswith("--config-env="):
            return None, [], "禁止 git --config-env 配置注入。"
        if lowered == "--exec-path" or lowered.startswith("--exec-path="):
            return None, [], "禁止覆盖 Git exec-path 动态执行外部子命令。"
        option_name = lowered.split("=", 1)[0]
        if raw in options_with_values or option_name in {
            "--git-dir",
            "--work-tree",
            "--namespace",
            "--super-prefix",
        }:
            index += 1 if "=" in raw else 2
            continue
        if raw.startswith("-"):
            index += 1
            continue
        return shell_token_basename(raw), words[index + 1 :], None
    return None, [], None


def first_git_action(arguments: list[str], *, value_options: set[str]) -> str | None:
    index = 0
    while index < len(arguments):
        raw = arguments[index]
        lowered = raw.casefold()
        option_name = lowered.split("=", 1)[0]
        if option_name in value_options:
            index += 1 if "=" in raw else 2
            continue
        if raw.startswith("-"):
            index += 1
            continue
        return lowered
    return None


def git_symbolic_ref_writes(arguments: list[str]) -> bool:
    if any(item.casefold() == "--delete" for item in arguments):
        return True
    positionals: list[str] = []
    index = 0
    while index < len(arguments):
        raw = arguments[index]
        lowered = raw.casefold()
        if lowered == "-m":
            index += 2
            continue
        if raw.startswith("-"):
            index += 1
            continue
        positionals.append(raw)
        index += 1
    return len(positionals) >= 2


def git_config_writes(arguments: list[str]) -> bool:
    lowered_arguments = [item.casefold() for item in arguments]
    if any(item.split("=", 1)[0] in GIT_CONFIG_WRITE_FLAGS for item in lowered_arguments):
        return True

    explicit_read = any(
        item.split("=", 1)[0] in GIT_CONFIG_READ_FLAGS for item in lowered_arguments
    )
    options_with_values = {"--file", "--blob", "--type", "-t", "--default"}
    positionals: list[str] = []
    index = 0
    options_terminated = False
    while index < len(arguments):
        raw = arguments[index]
        lowered = raw.casefold()
        if not options_terminated and raw == "--":
            options_terminated = True
            index += 1
            continue
        option_name = lowered.split("=", 1)[0]
        if not options_terminated and option_name in options_with_values:
            index += 1 if "=" in raw else 2
            continue
        if not options_terminated and raw.startswith("-"):
            index += 1
            continue
        positionals.append(lowered)
        index += 1

    if positionals and positionals[0] in GIT_CONFIG_WRITE_ACTIONS:
        return True
    if explicit_read or (positionals and positionals[0] in GIT_CONFIG_READ_ACTIONS):
        return False
    return len(positionals) >= 2


def git_write_error(text: str) -> str | None:
    if GIT_ENV_CONFIG_INJECTION_RE.search(text):
        return "禁止通过 GIT_CONFIG_* 环境变量注入 Git alias/filter/attributes。"
    for fragment in git_command_fragments(text):
        for segment in split_shell_segments(fragment):
            words = shell_words(segment)
            for index, word in enumerate(words):
                if shell_token_basename(word) != "git":
                    continue
                subcommand, arguments, parse_error = git_subcommand(words, index)
                if parse_error:
                    return parse_error
                if subcommand in GIT_UNCONDITIONAL_WRITE_SUBCOMMANDS:
                    return f"禁止直接运行写型 Git plumbing：git {subcommand}。"
                if subcommand in GIT_EXISTING_BLOCKED_SUBCOMMANDS:
                    return f"禁止通过 git {subcommand} 直接改写或丢弃工作区。"
                if subcommand == "push" and any(
                    item.casefold() in {"--force", "-f"}
                    or item.casefold().startswith("--force=")
                    for item in arguments
                ):
                    return "禁止强制推送。"
                if subcommand == "symbolic-ref" and git_symbolic_ref_writes(arguments):
                    return "禁止使用 git symbolic-ref 写入或删除引用。"
                if subcommand == "notes":
                    action = first_git_action(arguments, value_options={"--ref"})
                    if action in GIT_NOTES_WRITE_ACTIONS:
                        return f"禁止使用 git notes {action} 修改 notes 引用。"
                if subcommand == "worktree":
                    action = first_git_action(arguments, value_options=set())
                    if action in GIT_WORKTREE_WRITE_ACTIONS:
                        return f"禁止使用 git worktree {action} 修改工作区。"
                if subcommand == "config" and git_config_writes(arguments):
                    return "禁止通过 git config 写入 repo/global 配置或注入 filter/attributes/alias/hooksPath。"
    return None


def canonical_json_hash(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def plan_artifacts_sha256(task_id: str) -> str:
    digest = hashlib.sha256()
    directory = TASKS_DIR / task_id
    for name in PLAN_ARTIFACT_NAMES:
        path = directory / name
        if path_is_link_like(path):
            raise OSError(f"plan artifact is a symlink/junction: {name}")
        try:
            path.resolve(strict=True).relative_to(ROOT.resolve())
        except ValueError as exc:
            raise OSError(f"plan artifact resolves outside repository: {name}") from exc
        payload = path.read_bytes()
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise OSError(f"plan artifact is not UTF-8: {name}") from exc
        payload = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        digest.update(name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(len(payload)).encode("ascii"))
        digest.update(b"\x00")
        digest.update(payload)
        digest.update(b"\x00")
    return digest.hexdigest()


def decision_context_sha256(task: dict[str, Any]) -> str:
    if path_is_link_like(DECISIONS_FILE):
        raise OSError("requirements-decisions.json is a symlink/junction")
    try:
        DECISIONS_FILE.resolve(strict=True).relative_to(ROOT.resolve())
    except ValueError as exc:
        raise OSError("requirements-decisions.json resolves outside repository") from exc
    value = json.loads(DECISIONS_FILE.read_text(encoding="utf-8"))
    items = value.get("decisions") if isinstance(value, dict) else None
    if not isinstance(items, list):
        raise OSError("requirements-decisions.json is invalid")
    decisions: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise OSError("requirements-decisions.json contains invalid item")
        decision_id = str(item.get("id", "")).strip().upper()
        if not decision_id or decision_id in decisions:
            raise OSError("requirements-decisions.json contains missing/duplicate id")
        decisions[decision_id] = item
    selected: dict[str, dict[str, Any]] = {}
    for raw_id in task.get("decision_ids", []):
        decision_id = str(raw_id).strip().upper()
        if decision_id not in decisions:
            raise OSError(f"unknown decision id: {decision_id}")
        selected[decision_id] = decisions[decision_id]
    return canonical_json_hash(selected)


def immutable_contract(task: dict[str, Any]) -> dict[str, Any]:
    keys = (
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
    value = {key: task.get(key) for key in keys}
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
    value.update(
        {
            key: task.get(key)
            for key in (
                "new_dependency_allowed",
                "network_access_required",
                "remote_execution",
                "rollback",
            )
        }
    )
    return value


def active_task() -> tuple[dict[str, Any] | None, str | None]:
    if not STATE_FILE.is_file():
        return None, "尚未运行任务 preflight。"
    try:
        if path_is_link_like(STATE_FILE):
            raise ValueError("active state is a symlink/junction")
        STATE_FILE.resolve(strict=True).relative_to(ROOT.resolve())
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if state.get("schema_version") != 1:
            raise ValueError("invalid state schema")
        task_id = state["task_id"]
        if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
            raise ValueError("invalid task_id")
        task_path = TASKS_DIR / task_id / "task.json"
        if path_is_link_like(task_path):
            raise ValueError("task contract is a symlink/junction")
        task_path.resolve(strict=True).relative_to(ROOT.resolve())
        task = json.loads(task_path.read_text(encoding="utf-8"))
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise ValueError("task id does not match active state")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return None, f"活动任务状态无效：{exc}"
    expected = state.get("contract_sha256")
    actual = canonical_json_hash(immutable_contract(task))
    if not expected or expected != actual:
        return None, "任务授权字段在 preflight 后发生变化，请重新审批并运行 preflight。"
    policy_expected = state.get("policy_sha256")
    policy_actual = canonical_json_hash(policy_contract(task))
    if not policy_expected or policy_expected != policy_actual:
        return None, "任务执行策略在 preflight 后发生变化，请重新审批并运行 preflight。"
    plan_expected = state.get("plan_artifacts_sha256")
    try:
        plan_actual = plan_artifacts_sha256(task_id)
    except OSError as exc:
        return None, f"无法读取 preflight 锁定的计划制品：{exc}"
    if not plan_expected or plan_expected != plan_actual:
        return None, "计划制品在 preflight 后发生变化，请重新审批并运行 preflight。"
    decision_expected = state.get("decision_context_sha256")
    try:
        decision_actual = decision_context_sha256(task)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"无法读取 preflight 锁定的需求决策：{exc}"
    if not decision_expected or decision_expected != decision_actual:
        return None, "关联需求决策在 preflight 后发生变化，请重新审批并运行 preflight。"
    return task, None


def check_apply_patch(tool_input: Any) -> str | None:
    patch_text = "\n".join(text for text in collect_strings(tool_input) if "*** Begin Patch" in text)
    if not patch_text:
        return None
    raw_paths = extract_patch_paths(patch_text)
    if not raw_paths:
        return "无法可靠解析补丁路径，拒绝执行。"

    paths: list[str] = []
    for path in raw_paths:
        try:
            normalized = normalize_repo_path(path)
        except ValueError:
            return f"补丁路径必须是仓库内的规范相对路径：{path}"
        candidate = ROOT
        try:
            for segment in normalized.split("/"):
                candidate = candidate / segment
                if path_is_link_like(candidate):
                    return f"补丁路径不得经过符号链接或目录联接：{normalized}"
            candidate.resolve(strict=False).relative_to(ROOT.resolve())
        except (OSError, ValueError):
            return f"补丁路径解析到仓库外：{normalized}"
        paths.append(normalized)

    # State is CLI-owned even though it lives under the bootstrap namespace.
    if any(path.startswith(".harness/state/") for path in paths):
        return "活动任务状态只能由 Harness CLI 更新。"

    for path in paths:
        control_file = task_control_file(path)
        if control_file is not None and control_file[1] == "workflow-history.json":
            return "workflow-history.json 只能由 Harness CLI 更新。"
        task_error = existing_task_contract_patch_error(path)
        if task_error:
            return task_error

    task = None
    error = None
    if STATE_FILE.is_file():
        task, error = active_task()
        if task is None:
            return error

    if task is not None:
        task_id = str(task.get("id", ""))
        if any(path == f".harness/tasks/{task_id}/task.json" for path in paths):
            return "活动任务的授权合同在 preflight 后锁定；修改后必须重新独立审批。"
        protected_harness_paths = (
            ".codex/**",
            ".agents/**",
            ".harness/**",
            ".github/**",
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
            "AGENTS.md",
            "HARNESS.md",
            "shopxo_nursery_harness_spec.md",
            "ShopXO苗木平台需求规格说明书_V1.0.md",
        )
        task_runtime_patch_paths = (
            f".harness/tasks/{task_id}/evidence.md",
            f".harness/tasks/{task_id}/review.md",
            f".harness/tasks/{task_id}/release-note.md",
            f".harness/tasks/{task_id}/approval-plan.json",
            f".harness/tasks/{task_id}/approval-merge.json",
            f".harness/tasks/{task_id}/approval-release.json",
        )
        if str(task.get("type", "")).lower() != "harness":
            for path in paths:
                if path_matches(path, protected_harness_paths) and not path_matches(
                    path, task_runtime_patch_paths
                ):
                    return f"业务任务不得修改 Harness 策略或执行面：{path}"

    non_bootstrap = [path for path in paths if not path_matches(path, BOOTSTRAP_PATTERNS)]
    if task is not None and str(task.get("type", "")).lower() == "harness" and non_bootstrap:
        return (
            "NUR-HARNESS 任务只能修改项目 bootstrap/Harness 路径；"
            f"首个业务路径：{non_bootstrap[0]}"
        )
    if not non_bootstrap:
        return None

    if task is None:
        task, error = active_task()
    if task is None:
        return f"业务源码修改被阻止：{error} 首个越界路径：{non_bootstrap[0]}"

    if str(task.get("status", "")) != "implementing":
        return (
            f"任务 {task.get('id', '<unknown>')} 当前状态 {task.get('status', '<empty>')} "
            "不允许修改业务源码；请通过 task-transition 进入 implementing。"
        )

    task_id = str(task.get("id", ""))
    for path in paths:
        if path == f".harness/tasks/{task_id}/task.json":
            return "活动任务的授权合同在 preflight 后锁定；修改后必须重新人工审批。"

    allowed = [str(item) for item in task.get("allowed_paths", [])]
    forbidden = [str(item) for item in task.get("forbidden_paths", [])]
    for path in non_bootstrap:
        if path_matches(path, forbidden) or not path_matches(path, allowed):
            return f"补丁路径不在任务 {task_id} 的 allowed_paths 中：{path}"
    return None


def check_shell(tool_input: Any, *, strip_patch_blocks: bool = False) -> str | None:
    policy_values = [
        strip_exact_harness_remote_cli_literals(value)
        for value in collect_strings(tool_input)
    ]
    text = "\n".join(policy_values)
    if strip_patch_blocks:
        text = re.sub(
            r"\*\*\* Begin Patch[\s\S]*?\*\*\* End Patch",
            "",
            text,
        )
    if SENSITIVE_HARNESS_CLI_FRAGMENT_RE.search(text):
        return (
            "敏感 Harness 命令必须使用精确隔离启动形式："
            "python -I -S -B scripts/harness.py <command> ..."
        )
    for pattern in SHELL_DIRECT_WRITE_PATTERNS:
        if pattern.search(text):
            return (
                "禁止通过 shell 直接写入、移动或删除项目文件；"
                "请使用 apply_patch 让 Hook 校验路径，或使用固定 Harness CLI。"
            )
    powershell_error = powershell_dynamic_network_error(text)
    if powershell_error:
        return powershell_error
    network_client = shell_network_client(text)
    if network_client is not None:
        return (
            f"禁止直接调用网络客户端 {network_client}；"
            "远程动作只能使用精确的 python -I -S -B scripts/harness.py remote-exec 合同命令。"
        )
    for value in policy_values:
        git_error = git_write_error(value)
        if git_error:
            return git_error
    for pattern, reason in SHELL_BLOCK_PATTERNS:
        if pattern.search(text):
            return reason
    return None


def main() -> None:
    payload = read_payload()
    event_name = payload.get("hook_event_name")
    root_error = repository_root_safety_error()
    if root_error:
        if event_name == "PreToolUse":
            block(root_error)
        elif event_name == "SessionStart":
            emit(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": (
                            f"ShopXO 苗木 Harness 已拒绝当前工作目录：{root_error}。"
                            "请从非符号链接、非目录联接的真实仓库路径重新打开项目。"
                        ),
                    }
                }
            )
        else:
            emit({})
        return
    if event_name == "SessionStart":
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": (
                        "ShopXO 苗木项目 Harness 已启用。修改业务代码前读取 AGENTS.md、"
                        ".harness/CONSTITUTION.md 和当前 task.json，并运行 "
                        "python scripts/harness.py preflight <TASK_ID>。不得修改用户级 Codex 配置或访问生产环境。"
                    ),
                }
            }
        )
        return

    if event_name != "PreToolUse":
        emit({})
        return

    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input")
    reason = None
    lowered_tool_name = tool_name.lower()
    if "apply_patch" in lowered_tool_name:
        reason = check_apply_patch(tool_input)
    elif lowered_tool_name == "functions.exec":
        has_patch = any("*** Begin Patch" in text for text in collect_strings(tool_input))
        if has_patch:
            reason = check_apply_patch(tool_input)
        if reason is None:
            reason = check_shell(tool_input, strip_patch_blocks=has_patch)
    elif any(alias in lowered_tool_name for alias in ("bash", "shell_command", "exec_command")):
        reason = check_shell(tool_input)
    if reason:
        block(reason)
    else:
        emit({"continue": True})


if __name__ == "__main__":
    main()

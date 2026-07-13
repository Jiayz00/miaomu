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
    re.compile(r"(?i)(?:^|[\s;&|])(?:curl|wget|ftp|ssh|scp|sftp|nc|ncat|telnet)\b"),
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
            for key in ("new_dependency_allowed", "network_access_required", "rollback")
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

    task = None
    error = None
    if STATE_FILE.is_file():
        task, error = active_task()
        if task is None:
            return error

    if task is not None:
        task_id = str(task.get("id", ""))
        if any(path == f".harness/tasks/{task_id}/task.json" for path in paths):
            return "活动任务的授权合同在 preflight 后锁定；修改后必须重新人工审批。"
        protected_harness_paths = (
            ".codex/**",
            ".agents/**",
            ".harness/**",
            ".github/**",
            "docs/product/BUSINESS_RULES.md",
            "docs/product/REQUIREMENTS_TRACEABILITY.md",
            "docs/architecture/SHOPXO_BOUNDARY.md",
            "scripts/harness.py",
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
    text = "\n".join(collect_strings(tool_input))
    if strip_patch_blocks:
        text = re.sub(
            r"\*\*\* Begin Patch[\s\S]*?\*\*\* End Patch",
            "",
            text,
        )
    for pattern in SHELL_DIRECT_WRITE_PATTERNS:
        if pattern.search(text):
            return (
                "禁止通过 shell 直接写入、移动或删除项目文件；"
                "请使用 apply_patch 让 Hook 校验路径，或使用固定 Harness CLI。"
            )
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

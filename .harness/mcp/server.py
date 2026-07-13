#!/usr/bin/env python3
"""Read-only MCP server exposing the local nursery requirements and task state."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


# MCP stdio uses UTF-8 JSON.  Windows Python otherwise inherits the local GBK
# code page, which corrupts Chinese search arguments and response content.
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")


ROOT = Path(os.path.abspath(__file__)).parents[2]
HARNESS_DIR = ROOT / ".harness"
TASKS_DIR = HARNESS_DIR / "tasks"
DECISIONS_FILE = HARNESS_DIR / "requirements-decisions.json"
REQUIREMENTS_FILE = ROOT / "ShopXO苗木平台需求规格说明书_V1.0.md"
REQUIREMENT_ID_RE = re.compile(
    r"\b(?:BR|FR|NFR|DATA|METRIC|AC)(?:-[A-Z]+)*-\d{3}\b", re.I
)
TASK_ID_RE = re.compile(r"^NUR-(?:FEAT|BUG|UI|DATA|SEC|OPS|DOC|REFACTOR|HARNESS)-\d{3}$")


TOOLS = [
    {
        "name": "harness_status",
        "description": "Return read-only project, source, decision, baseline, and task status.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "requirements_search",
        "description": "Search the local Chinese ShopXO nursery requirements document with line and heading context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "requirement_get",
        "description": "Get the complete heading block for one BR/FR/NFR/DATA/METRIC/AC requirement ID.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "task_get",
        "description": "Read one local Harness task contract and its companion document status.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        },
    },
]


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


def lexical_path_components(path: Path) -> tuple[Path, tuple[Path, ...]]:
    absolute = Path(os.path.abspath(os.fspath(path)))
    components: list[Path] = []
    current = absolute
    while current.parent != current:
        components.append(current)
        current = current.parent
    components.reverse()
    return absolute, tuple(components)


def ensure_repo_path_safe(path: Path, *, label: str) -> None:
    root_absolute, root_components = lexical_path_components(ROOT)
    path_absolute, _path_components = lexical_path_components(path)
    for component in root_components:
        if path_is_link_like(component):
            raise ValueError(
                f"repository root contains symlink/junction component: {component.name}"
            )
    try:
        relative = path_absolute.relative_to(root_absolute)
    except ValueError as exc:
        raise ValueError(f"{label} is outside repository") from exc
    try:
        resolved_root = root_absolute.resolve(strict=True)
    except OSError as exc:
        raise ValueError("repository root cannot be resolved safely") from exc
    current = root_absolute
    for segment in relative.parts:
        current = current / segment
        if path_is_link_like(current):
            raise ValueError(f"{label} contains symlink/junction component: {segment}")
        try:
            current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError(f"{label} cannot be inspected safely") from exc
        try:
            current.resolve(strict=True).relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise ValueError(f"{label} resolves outside repository") from exc


def read_json(path: Path, default: Any) -> Any:
    ensure_repo_path_safe(path, label=str(path))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def git_value(*args: str) -> str | None:
    ensure_repo_path_safe(ROOT, label="repository root")
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def sanitize_remote_url(value: str | None) -> str | None:
    if not value:
        return value
    return re.sub(r"(?i)((?:https?|ssh)://)[^\s/@]+@", r"\1[REDACTED]@", value)


def requirement_lines() -> list[str]:
    ensure_repo_path_safe(REQUIREMENTS_FILE, label="requirements document")
    if not REQUIREMENTS_FILE.is_file():
        raise FileNotFoundError(f"Requirements document not found: {REQUIREMENTS_FILE}")
    return REQUIREMENTS_FILE.read_text(encoding="utf-8").splitlines()


def headings(lines: list[str]) -> list[tuple[int, int, str]]:
    result: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            result.append((index, len(match.group(1)), match.group(2)))
    return result


def enclosing_heading(lines: list[str], line_index: int) -> str | None:
    current = None
    for index, _level, title in headings(lines):
        if index > line_index:
            break
        current = title
    return current


def requirement_get(requirement_id: str) -> dict[str, Any]:
    requirement_id = requirement_id.strip().upper()
    if not REQUIREMENT_ID_RE.fullmatch(requirement_id):
        raise ValueError(f"Invalid requirement id: {requirement_id}")
    lines = requirement_lines()
    all_headings = headings(lines)
    for position, (start, level, title) in enumerate(all_headings):
        if re.search(rf"\b{re.escape(requirement_id)}\b", title, re.I):
            end = len(lines)
            for next_start, next_level, _next_title in all_headings[position + 1 :]:
                if next_level <= level:
                    end = next_start
                    break
            return {
                "id": requirement_id,
                "heading": title,
                "start_line": start + 1,
                "end_line": end,
                "text": "\n".join(lines[start:end]).strip(),
                "source": REQUIREMENTS_FILE.name,
            }
    raise KeyError(f"Requirement not found: {requirement_id}")


def requirements_search(query: str, limit: int) -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    lines = requirement_lines()
    needle = query.casefold()
    results = []
    for index, line in enumerate(lines):
        if needle not in line.casefold():
            continue
        start = max(0, index - 2)
        end = min(len(lines), index + 3)
        results.append(
            {
                "line": index + 1,
                "heading": enclosing_heading(lines, index),
                "requirement_ids": sorted(set(REQUIREMENT_ID_RE.findall("\n".join(lines[start:end]).upper()))),
                "context": "\n".join(
                    f"{line_no + 1}: {lines[line_no]}" for line_no in range(start, end)
                ),
            }
        )
        if len(results) >= limit:
            break
    return {"query": query, "count": len(results), "results": results, "source": REQUIREMENTS_FILE.name}


def harness_status() -> dict[str, Any]:
    decisions = read_json(DECISIONS_FILE, {}).get("decisions", [])
    ensure_repo_path_safe(TASKS_DIR, label="tasks directory")
    task_ids: list[str] = []
    if TASKS_DIR.is_dir():
        for task_directory in TASKS_DIR.iterdir():
            ensure_repo_path_safe(task_directory, label="task directory")
            if not task_directory.is_dir() or not TASK_ID_RE.fullmatch(task_directory.name):
                continue
            task_path = task_directory / "task.json"
            ensure_repo_path_safe(task_path, label="task contract")
            if task_path.is_file():
                task_ids.append(task_directory.name)
    task_ids.sort()
    baselines = HARNESS_DIR / "baselines"
    ensure_repo_path_safe(baselines, label="baseline directory")
    baseline_files: list[str] = []
    if baselines.is_dir():
        for path in baselines.iterdir():
            ensure_repo_path_safe(path, label="baseline file")
            if path.is_file() and path.suffix.casefold() == ".json":
                baseline_files.append(path.name)
    baseline_files.sort()
    blockers = []
    common_path = ROOT / "app" / "common.php"
    try:
        ensure_repo_path_safe(common_path, label="app/common.php")
    except ValueError as exc:
        blockers.append(str(exc))
    else:
        if not common_path.is_file():
            blockers.append("app/common.php missing from worktree")
    source_tree_present = True
    for path in (ROOT / "composer.json", ROOT / "app", ROOT / "config" / "shopxo.sql"):
        try:
            ensure_repo_path_safe(path, label=str(path.relative_to(ROOT)))
        except ValueError as exc:
            blockers.append(str(exc))
            source_tree_present = False
            continue
        if not path.exists():
            source_tree_present = False
    return {
        "root": str(ROOT),
        "git_branch": git_value("branch", "--show-current"),
        "git_commit": git_value("rev-parse", "HEAD"),
        "upstream": sanitize_remote_url(git_value("remote", "get-url", "upstream")),
        "shopxo_source_present": source_tree_present,
        "shopxo_source_ready": source_tree_present and not blockers,
        "known_source_blockers": blockers,
        "open_decisions": [item.get("id") for item in decisions if item.get("status") == "open"],
        "tasks": task_ids,
        "baselines": baseline_files,
    }


def task_get(task_id: str) -> dict[str, Any]:
    task_id = task_id.strip().upper()
    if not TASK_ID_RE.fullmatch(task_id):
        raise ValueError(f"Invalid task id: {task_id}")
    task_dir = TASKS_DIR / task_id
    task_path = task_dir / "task.json"
    ensure_repo_path_safe(task_dir, label="task directory")
    ensure_repo_path_safe(task_path, label="task contract")
    if not task_path.is_file():
        raise FileNotFoundError(f"Task not found: {task_id}")
    task = read_json(task_path, None)
    if task is None:
        raise ValueError(f"Task JSON is invalid: {task_id}")
    companions = {}
    for name in (
        "workflow-history.json",
        "impact-analysis.md",
        "implementation-plan.md",
        "test-plan.md",
        "evidence.md",
        "review.md",
        "release-note.md",
    ):
        path = task_dir / name
        ensure_repo_path_safe(path, label=f"task companion {name}")
        companions[name] = {"exists": path.is_file(), "bytes": path.stat().st_size if path.is_file() else 0}
    return {"task": task, "documents": companions}


def text_result(value: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}],
        "isError": is_error,
    }


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "harness_status":
        return text_result(harness_status())
    if name == "requirements_search":
        limit = int(arguments.get("limit", 8))
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        return text_result(requirements_search(str(arguments.get("query", "")), limit))
    if name == "requirement_get":
        return text_result(requirement_get(str(arguments.get("id", ""))))
    if name == "task_get":
        return text_result(task_get(str(arguments.get("task_id", ""))))
    raise KeyError(f"Unknown tool: {name}")


def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    try:
        ensure_repo_path_safe(ROOT, label="repository root")
    except ValueError as exc:
        if request_id is None:
            return None
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": f"Unsafe repository root: {exc}"},
        }
    if method == "initialize":
        params = request.get("params") or {}
        protocol = params.get("protocolVersion") or "2025-06-18"
        result = {
            "protocolVersion": protocol,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
            },
            "serverInfo": {"name": "nursery-harness", "version": "1.0.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "resources/list":
        result = {"resources": []}
    elif method == "resources/templates/list":
        result = {"resourceTemplates": []}
    elif method == "tools/call":
        params = request.get("params") or {}
        try:
            result = call_tool(str(params.get("name", "")), params.get("arguments") or {})
        except Exception as exc:  # MCP tool errors are returned as tool results.
            result = text_result({"error": type(exc).__name__, "message": str(exc)}, is_error=True)
    elif isinstance(method, str) and method.startswith("notifications/"):
        return None
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> None:
    for raw_line in sys.stdin:
        if not raw_line.strip():
            continue
        try:
            request = json.loads(raw_line)
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            response = handle(request)
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

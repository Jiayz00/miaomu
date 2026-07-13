#!/usr/bin/env python3
"""Offline standard-library tests for the Harness remote execution broker."""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from typing import BinaryIO, Callable
import unittest
from unittest import mock

import harness as harness_core
import harness_remote as remote


class RecordingTransport:
    def __init__(
        self,
        outcome: remote.ProcessOutcome | None = None,
        during_transfer: Callable[[BinaryIO], None] | None = None,
        *,
        download_payload: bytes = b"downloaded deployment evidence\n",
        during_download: Callable[[BinaryIO], None] | None = None,
    ) -> None:
        self.calls: list[tuple[tuple[str, ...], int, int]] = []
        self.stdin_payloads: list[bytes] = []
        self.outcome = outcome
        self.during_transfer = during_transfer
        self.download_payload = download_payload
        self.during_download = during_download

    def __call__(
        self,
        argv: tuple[str, ...],
        timeout_seconds: int,
        output_limit_bytes: int,
        *,
        stdin_handle: BinaryIO | None = None,
        stdout_handle: BinaryIO | None = None,
        stdout_file_limit_bytes: int | None = None,
    ) -> remote.ProcessOutcome:
        self.calls.append((argv, timeout_seconds, output_limit_bytes))
        payload: bytes | None = None
        if stdin_handle is not None:
            if self.during_transfer is not None:
                self.during_transfer(stdin_handle)
            stdin_handle.seek(0)
            payload = stdin_handle.read()
            self.stdin_payloads.append(payload)
        if stdout_handle is not None:
            if stdout_file_limit_bytes is None:
                raise AssertionError("download stdout handle lacks a size limit")
            stdout_handle.write(self.download_payload)
            stdout_handle.flush()
            if self.during_download is not None:
                self.during_download(stdout_handle)
        if self.outcome is not None:
            return self.outcome
        if stdout_handle is not None:
            stdout = b""
            stdout_bytes = len(self.download_payload)
        elif payload is None:
            stdout = b"ok password=hunter2 Bearer abc.def.ghi 13800138000\n"
            stdout_bytes = len(stdout)
        else:
            digest = hashlib.sha256(payload).hexdigest()
            stdout = f"HARNESS_UPLOAD_VERIFIED {digest} {len(payload)}\n".encode(
                "ascii"
            )
            stdout_bytes = len(stdout)
        return remote.ProcessOutcome(
            exit_code=0,
            stdout=stdout,
            stderr=b"",
            stdout_bytes=stdout_bytes,
            stderr_bytes=0,
            timed_out=False,
            output_limited=False,
            duration_ms=12,
        )


class RemoteBrokerTests(unittest.TestCase):
    _shared_sealed_temp: tempfile.TemporaryDirectory[str] | None = None
    _shared_sealed_root: Path | None = None

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._shared_sealed_temp is not None:
            cls._shared_sealed_temp.cleanup()
            cls._shared_sealed_temp = None
            cls._shared_sealed_root = None

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.base = base
        self.root = base / "repo"
        self.root.mkdir()
        self.ssh_dir = base / "user-ssh"
        self.ssh_dir.mkdir()
        self.identity = self.ssh_dir / "Jia-8u8g"
        self.identity.write_text("test fixture, broker must not read this\n", encoding="utf-8")
        self.known_hosts = self.ssh_dir / "known_hosts_miaomu"
        self.tool_dir = base / "system-tools"
        self.tool_dir.mkdir()
        self.ssh_executable = self.tool_dir / "ssh.exe"
        self.scp_executable = self.tool_dir / "scp.exe"
        self.ssh_executable.write_bytes(b"offline ssh fixture")
        self.scp_executable.write_bytes(b"offline scp fixture")
        key_blob = b"offline-test-host-key-blob"
        key_data = base64.b64encode(key_blob).decode("ascii")
        fingerprint_data = base64.b64encode(hashlib.sha256(key_blob).digest()).decode("ascii").rstrip("=")
        self.fingerprint = "SHA256:" + fingerprint_data
        self.known_hosts.write_text(
            f"38.12.21.18 ssh-ed25519 {key_data}\n", encoding="utf-8"
        )
        self.run_dir = self.root / ".harness" / "runs" / "NUR-OPS-001"
        self.run_dir.mkdir(parents=True)
        (self.root / ".harness" / "tasks" / "NUR-OPS-001").mkdir(parents=True)
        (self.root / ".harness" / "state").mkdir(parents=True)
        (self.run_dir / "release.tar").write_bytes(b"release")
        self.original_trusted_system_executable = remote._trusted_system_executable
        self.real_git = remote._trusted_system_executable("git", self.root)
        self.runner = RecordingTransport()
        self.active_runner = self.runner
        self.active_repository_root = self.root
        self.repository_patch = mock.patch.object(
            remote,
            "_project_repository_root",
            side_effect=lambda: self.active_repository_root,
        )
        self.profile_patch = mock.patch.object(
            remote, "_default_user_ssh_directory", return_value=self.ssh_dir
        )

        def trusted_tool(name: str, _repository_root: Path) -> Path:
            if name == "ssh":
                return self.ssh_executable
            if name == "scp":
                return self.scp_executable
            if name == "git":
                return self.real_git
            raise AssertionError(f"unexpected trusted tool: {name}")

        self.tool_patch = mock.patch.object(
            remote, "_trusted_system_executable", side_effect=trusted_tool
        )

        def transport_dispatch(*args, **kwargs):
            return self.active_runner(*args, **kwargs)

        self.transport_patch = mock.patch.object(
            remote, "_run_transport_process", side_effect=transport_dispatch
        )
        self.repository_patch.start()
        self.profile_patch.start()
        self.tool_patch.start()
        self.transport_patch.start()
        self.addCleanup(self.transport_patch.stop)
        self.addCleanup(self.tool_patch.stop)
        self.addCleanup(self.profile_patch.stop)
        self.addCleanup(self.repository_patch.stop)
        self.task = self._task()
        self.state = self._state(self.task)
        self._write_contract(self.root, self.task, self.state)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _task(self) -> dict:
        return {
            "schema_version": 2,
            "id": "NUR-OPS-001",
            "title": "remote deployment",
            "type": "operations",
            "priority": "P0",
            "phase": 1,
            "risk_level": "L4",
            "status": "approved_for_implementation",
            "requirement_ids": ["NFR-SEC-006"],
            "decision_ids": [],
            "business_goal": "deploy the authorized personal site",
            "in_scope": ["fixed remote target"],
            "out_of_scope": ["production secrets"],
            "business_invariants": ["no credential contents"],
            "dependencies": [],
            "allowed_paths": ["deploy/**", "evidence/**"],
            "forbidden_paths": [".env"],
            "shopxo_core_change": {"required": False, "paths": []},
            "database_change": {"required": False},
            "required_tests": [],
            "codex_role_bindings": {
                "implementation": {
                    "agent_task": "/root",
                    "thread_id": "11111111-1111-4111-8111-111111111111",
                },
                "plan": {"agent_task": "/root/plan_review"},
                "merge": {"agent_task": "/root/merge_review"},
                "release": {"agent_task": "/root/release_review"},
            },
            "owner": "Codex-Implementer",
            "reviewer": "Codex-Review",
            "release_approver": "Codex-Release",
            "acceptance_criteria": [
                {
                    "id": "AC-TASK-001",
                    "requirement_ids": ["NFR-SEC-006"],
                    "description": "strict remote execution",
                }
            ],
            "manual_approvals": {
                "plan": {
                    "required": True,
                    "status": "approved",
                    "approved_by": "Codex-Review",
                    "approved_at": "2026-07-13T08:00:00Z",
                },
                "merge": {
                    "required": True,
                    "status": "pending",
                    "approved_by": None,
                    "approved_at": None,
                },
                "release": {
                    "required": True,
                    "status": "pending",
                    "approved_by": None,
                    "approved_at": None,
                },
            },
            "new_dependency_allowed": False,
            "network_access_required": True,
            "remote_execution": {
                "authorization": {
                    "mode": "user_explicit",
                    "thread_id": "019f566b-dffa-7913-a608-bc2dffbd2bea",
                    "authorized_at": "2026-07-13T08:00:00+08:00",
                    "scope": "Deploy the nursery site to the named personal server.",
                },
                "environment": "authorized_personal_site",
                "host": "38.12.21.18",
                "port": 22,
                "user": "root",
                "host_key_fingerprint": self.fingerprint,
                "identity_reference": "user-ssh-file:Jia-8u8g",
                "known_hosts_reference": "user-ssh-file:known_hosts_miaomu",
                "deployment_root": "/root/jia/miaomu",
                "managed_roots": ["/root/jia/miaomu", "/root/jia/caddy"],
                "allowed_actions": [
                    {
                        "id": "inventory_pwd",
                        "transport": "ssh",
                        "mode": "read_only",
                        "timeout_seconds": 30,
                        "cwd": "/root/jia/miaomu",
                        "argv": ["pwd"],
                    },
                    {
                        "id": "upload_release",
                        "transport": "scp",
                        "mode": "mutating",
                        "timeout_seconds": 60,
                        "direction": "upload",
                        "source": ".harness/runs/NUR-OPS-001/release.tar",
                        "destination": "/root/jia/miaomu/release.tar",
                    },
                    {
                        "id": "download_log",
                        "transport": "scp",
                        "mode": "read_only",
                        "timeout_seconds": 60,
                        "direction": "download",
                        "source": "/root/jia/miaomu/deploy.log",
                        "destination": ".harness/runs/NUR-OPS-001/deploy.log",
                    },
                    {
                        "id": "bootstrap_deployment_root",
                        "transport": "ssh",
                        "mode": "mutating",
                        "timeout_seconds": 30,
                        "cwd": "/root/jia/miaomu",
                        "argv": [
                            "mkdir",
                            "-p",
                            "--",
                            "/root/jia/miaomu",
                        ],
                    },
                ],
                "forbidden_actions": sorted(remote.REQUIRED_FORBIDDEN_ACTIONS),
            },
            "rollback": {"required": True, "plan": "restore", "verification": "smoke"},
        }

    @staticmethod
    def _state(task: dict) -> dict:
        return {
            "schema_version": 1,
            "task_id": task["id"],
            "contract_sha256": remote._immutable_contract_hash(task),
            "policy_sha256": remote._policy_contract_hash(task),
            "plan_artifacts_sha256": "1" * 64,
            "decision_context_sha256": "2" * 64,
            "scope_base_commit": "3" * 40,
            "git_branch": "ops/NUR-OPS-001-deploy",
        }

    @staticmethod
    def _write_contract(root: Path, task: dict, state: dict) -> None:
        task_dir = root / ".harness" / "tasks" / task["id"]
        state_dir = root / ".harness" / "state"
        task_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "task.json").write_text(
            json.dumps(task, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (state_dir / "active-task.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _broker(
        self,
        *,
        task: dict | None = None,
        state: dict | None = None,
        runner: RecordingTransport | None = None,
    ) -> remote.RemoteExecutionBroker:
        selected_task = task if task is not None else self.task
        selected_state = state if state is not None else self._state(selected_task)
        self.active_runner = runner if runner is not None else self.runner
        self.active_repository_root = self.root
        self._write_contract(self.root, selected_task, selected_state)
        return remote.RemoteExecutionBroker.from_repository(selected_task["id"])

    def _git(self, root: Path, *arguments: str) -> str:
        result = subprocess.run(
            [str(self.real_git), "-C", str(root), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        return result.stdout.strip()

    @staticmethod
    def _write_plan_artifacts(root: Path, task_id: str) -> None:
        task_dir = root / ".harness" / "tasks" / task_id
        repeated = (
            "This fixture records verified facts, explicit boundaries, exact paths, "
            "failure handling, rollback steps, and accountable roles. "
        ) * 20
        documents = {
            "requirement.md": [
                f"# {task_id} requirement",
                "## 关联需求",
                "- NFR-SEC-006",
                "## 任务路由",
                "- PRIORITY: P0",
                "- PHASE: 1",
                "## 业务目标",
                repeated,
                "## 明确不做",
                repeated,
                "## 开放决策",
                "- No open decisions.",
            ],
            "impact-analysis.md": [
                f"# {task_id} impact",
                "## 需求与当前事实",
                repeated,
                "## 当前调用链与数据",
                repeated,
                "## 影响范围",
                repeated,
                "## 方案比较",
                repeated,
                "## 风险与边界",
                repeated,
                "## 预计文件",
                repeated,
            ],
            "implementation-plan.md": [
                f"# {task_id} implementation",
                "## 实施步骤",
                repeated,
                "## 验证顺序",
                repeated,
                "## 数据库与核心适配",
                repeated,
                "## 失败处理与回滚",
                repeated,
            ],
            "test-plan.md": [
                f"# {task_id} tests",
                "## 自动测试",
                "- broker_fixture: python payload/check.py",
                repeated,
                "## 手工验收",
                repeated,
                "## 数据与权限",
                repeated,
                "## 未覆盖项",
                repeated,
            ],
        }
        for name, lines in documents.items():
            (task_dir / name).write_text(
                "\n\n".join(lines) + "\n", encoding="utf-8"
            )

    @staticmethod
    def _write_approval_artifact(
        harness: harness_core.Harness,
        task_id: str,
        task: dict,
        *,
        stage: str,
        actor: str,
        agent_task: str,
        thread_id: str,
    ) -> None:
        context = harness.approval_context(task_id, task, stage)
        path = (
            harness.root
            / ".harness"
            / "tasks"
            / task_id
            / f"approval-{stage}.json"
        )
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "task_id": task_id,
                    "stage": stage,
                    "decision": "approved",
                    "actor": actor,
                    "agent_task": agent_task,
                    "codex_thread_id": thread_id,
                    "result_marker": "APPROVED",
                    "approval_context_sha256": harness_core.canonical_json_hash(
                        context
                    ),
                    "reviewed_at": "2026-07-13T09:00:00Z",
                    "findings": [],
                    "summary": (
                        "An independent Codex role reviewed the exact locked "
                        "contract, evidence, rollback, and release boundary."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _approve_bound_stage(
        self,
        harness: harness_core.Harness,
        task_id: str,
        *,
        stage: str,
        actor: str,
        thread_id: str,
    ) -> None:
        task = harness.load_task(task_id)
        binding = task["codex_role_bindings"][stage]
        assert isinstance(binding, dict)
        agent_task = str(binding["agent_task"])
        self._write_approval_artifact(
            harness,
            task_id,
            task,
            stage=stage,
            actor=actor,
            agent_task=agent_task,
            thread_id=thread_id,
        )
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": thread_id}):
            gate = harness.task_approval(
                task_id,
                stage=stage,
                status="approved",
                actor=actor,
                reason="independent fixture review",
                agent_task=agent_task,
            )
        if not gate.ok:
            raise AssertionError(f"{stage} approval failed: {gate.errors}")

    def _build_real_sealed_repository(self, root: Path) -> None:
        workspace = Path(__file__).resolve().parents[1]
        shutil.copytree(workspace / ".harness", root / ".harness")
        for relative in (
            ".harness/tasks",
            ".harness/runs",
            ".harness/reports",
            ".harness/state",
        ):
            directory = root / relative
            for child in tuple(directory.iterdir()):
                if child.name == ".gitignore":
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        shutil.copy2(workspace / ".gitignore", root / ".gitignore")
        shutil.copy2(
            workspace / "ShopXO苗木平台需求规格说明书_V1.0.md",
            root / "ShopXO苗木平台需求规格说明书_V1.0.md",
        )
        scripts_dir = root / "scripts"
        scripts_dir.mkdir()
        shutil.copy2(workspace / "scripts/harness.py", scripts_dir / "harness.py")
        shutil.copy2(
            workspace / "scripts/harness_remote.py",
            scripts_dir / "harness_remote.py",
        )
        payload_dir = root / "payload"
        payload_dir.mkdir()
        (payload_dir / "check.py").write_text(
            "print('broker fixture verified')\n", encoding="utf-8"
        )

        task = copy.deepcopy(self.task)
        task.update(
            {
                "schema_version": 2,
                "status": "draft",
                "allowed_paths": ["payload/**"],
                "shopxo_core_change": {
                    "required": False,
                    "paths": [],
                    "reason": "",
                    "registration": "",
                },
                "database_change": {
                    "required": False,
                    "affected_tables": [],
                    "migration_paths": [],
                    "fresh_install_baseline_exception": {
                        "requested": False,
                        "reason": "",
                    },
                    "rollback_plan": "No database change is made by this fixture.",
                    "verification": "The release diff contains no database path.",
                },
                "required_tests": [
                    {
                        "id": "broker_fixture",
                        "description": "Run the offline broker release fixture check.",
                        "command": ["python", "payload/check.py"],
                        "cwd": ".",
                        "timeout_seconds": 60,
                    }
                ],
                "rollback": {
                    "required": True,
                    "plan": "Delete the temporary fixture repository.",
                    "verification": "Confirm the temporary path no longer exists.",
                },
                "manual_approvals": {
                    "plan": {
                        "required": True,
                        "status": "pending",
                        "approved_by": None,
                        "approved_at": None,
                    },
                    "merge": {
                        "required": True,
                        "status": "pending",
                        "approved_by": None,
                        "approved_at": None,
                    },
                    "release": {
                        "required": True,
                        "status": "pending",
                        "approved_by": None,
                        "approved_at": None,
                    },
                },
                "created_at": "2026-07-13T08:00:00Z",
                "updated_at": "2026-07-13T08:00:00Z",
            }
        )
        task_dir = root / ".harness" / "tasks" / task["id"]
        task_dir.mkdir()
        (task_dir / "task.json").write_text(
            json.dumps(task, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._write_plan_artifacts(root, task["id"])
        run_dir = root / ".harness" / "runs" / task["id"]
        run_dir.mkdir()
        (run_dir / "release.tar").write_bytes(b"sealed release artifact")

        self._git(root, "init", "-b", "ops/NUR-OPS-001-deploy")
        self._git(root, "config", "core.autocrlf", "true")
        self._git(root, "config", "user.name", "Broker Selftest")
        self._git(root, "config", "user.email", "broker@example.invalid")
        original_harness_root = harness_core.ROOT
        harness_core.ROOT = root
        self.addCleanup(setattr, harness_core, "ROOT", original_harness_root)
        harness = harness_core.Harness(root)

        def require(gate: harness_core.GateResult, label: str) -> None:
            if not gate.ok:
                raise AssertionError(f"{label} failed: {gate.errors}")

        require(
            harness.task_transition(
                task["id"],
                target_status="ready_for_analysis",
                actor="Codex-Implementer",
                reason="fixture analysis ready",
            ),
            "ready_for_analysis",
        )
        require(
            harness.task_transition(
                task["id"],
                target_status="awaiting_plan_approval",
                actor="Codex-Implementer",
                reason="fixture plan ready",
            ),
            "awaiting_plan_approval",
        )
        self._approve_bound_stage(
            harness,
            task["id"],
            stage="plan",
            actor="Codex-Review",
            thread_id="33333333-3333-4333-8333-333333333333",
        )
        require(
            harness.task_transition(
                task["id"],
                target_status="approved_for_implementation",
                actor="Codex-Review",
                reason="fixture plan approved",
            ),
            "approved_for_implementation",
        )
        self._git(root, "add", "-A")
        self._git(root, "commit", "-m", "broker fixture preflight base")
        base_commit = self._git(root, "rev-parse", "HEAD")
        approved_task = harness.load_task(task["id"])
        state = {
            "schema_version": 1,
            "task_id": task["id"],
            "task_file": f".harness/tasks/{task['id']}/task.json",
            "contract_sha256": harness_core.immutable_contract_hash(approved_task),
            "policy_sha256": harness_core.policy_contract_hash(approved_task),
            "plan_artifacts_sha256": harness.plan_artifacts_sha256(task["id"]),
            "decision_context_sha256": harness.decision_context_sha256(
                approved_task
            ),
            "scope_base_commit": base_commit,
            "git_branch": "ops/NUR-OPS-001-deploy",
            "git_commit": base_commit,
            "preflight_at": "2026-07-13T09:05:00Z",
            "source_paths": [],
        }
        harness.state_file.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        require(
            harness.task_transition(
                task["id"],
                target_status="implementing",
                actor="Codex-Implementer",
                reason="fixture implementation",
            ),
            "implementing",
        )
        require(
            harness.task_transition(
                task["id"],
                target_status="verifying",
                actor="Codex-Implementer",
                reason="fixture verification",
            ),
            "verifying",
        )
        verify = harness.verify(task["id"], base_ref=None, require_state=True)
        require(verify, "verify")
        verification_contract = str(verify.data["verification_contract_sha256"])
        repeated = (
            "This evidence records exact inputs, assertions, limitations, rollback, "
            "and reproducible results without claiming unexecuted checks. "
        ) * 14
        command_json = harness_core.command_text(["python", "payload/check.py"])
        evidence = (
            f"# {task['id']} evidence\n\n"
            "## 验收标准映射\n\n"
            f"AC-TASK-001: passed. {repeated}\n\n"
            "## 自动测试证据\n\n"
            f"VERIFY_CONTRACT_SHA256: {verification_contract}\n\n"
            f"TEST_COMMAND: broker_fixture {command_json}\n\n"
            "TEST_RESULT: broker_fixture exit_code=0\n\n"
            "## 手工与页面证据\n\nNo page fixture is required.\n\n"
            "## 已知限制\n\nThe fixture performs no network operation.\n\n"
            "## 回滚证据\n\nThe temporary repository is deleted by unittest.\n"
        )
        (task_dir / "evidence.md").write_text(evidence, encoding="utf-8")
        require(
            harness.evidence_check(task["id"], base_ref=None, require_state=True),
            "evidence-check",
        )
        require(
            harness.task_transition(
                task["id"],
                target_status="awaiting_review",
                actor="Codex-Implementer",
                reason="fixture evidence complete",
            ),
            "awaiting_review",
        )
        require(
            harness.review_pack(task["id"], base_ref=None, require_state=True),
            "review-pack",
        )
        review_text = (
            f"# {task['id']} review\n\n## 审查范围\n\n{repeated}\n\n"
            f"## 发现\n\nNo blocking finding. {repeated}\n\n"
            "## 审查结论\n\nREVIEW_RESULT: APPROVED\n"
            "REVIEWER: Codex-Review\nREVIEWED_AT: 2026-07-13T09:10:00Z\n"
        )
        release_text = (
            f"# {task['id']} release\n\n## 变更摘要\n\n{repeated}\n\n"
            f"## 发布前提\n\n{repeated}\n\n## 发布步骤\n\n{repeated}\n\n"
            f"## 回滚触发与步骤\n\n{repeated}\n\n## 发布后验证\n\n{repeated}\n"
        )
        (task_dir / "review.md").write_text(review_text, encoding="utf-8")
        (task_dir / "release-note.md").write_text(
            release_text, encoding="utf-8"
        )
        self._approve_bound_stage(
            harness,
            task["id"],
            stage="merge",
            actor="Codex-Review",
            thread_id="44444444-4444-4444-8444-444444444444",
        )
        self._approve_bound_stage(
            harness,
            task["id"],
            stage="release",
            actor="Codex-Release",
            thread_id="55555555-5555-4555-8555-555555555555",
        )
        require(
            harness.task_transition(
                task["id"],
                target_status="approved_for_merge",
                actor="Codex-Review",
                reason="fixture independently approved",
            ),
            "approved_for_merge",
        )
        self._git(root, "add", "-A")
        self._git(root, "commit", "-m", "approved broker release fixture")
        require(
            harness.release_check(task["id"], base_ref=None, require_state=True),
            "release-check",
        )
        final_task = harness.load_task(task["id"])
        final_state = json.loads(harness.state_file.read_text(encoding="utf-8"))
        head = self._git(root, "rev-parse", "HEAD")
        self.active_repository_root = root
        final_state.update(
            {
                "release_commit": head,
                "release_contract_sha256": harness_core.immutable_contract_hash(
                    final_task
                ),
                "release_policy_sha256": harness_core.policy_contract_hash(
                    final_task
                ),
                "release_sealed_at": "2026-07-13T09:15:00Z",
                "release_upload_artifacts": remote.RemoteExecutionBroker.release_upload_artifact_facts(
                    task["id"]
                ),
            }
        )
        if remote._immutable_contract_hash(final_task) != final_state[
            "release_contract_sha256"
        ] or remote._policy_contract_hash(final_task) != final_state[
            "release_policy_sha256"
        ]:
            raise AssertionError("remote/core contract hashes diverged")
        harness.state_file.write_text(
            json.dumps(final_state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _shared_sealed_repository(self) -> Path:
        cls = type(self)
        if cls._shared_sealed_root is None:
            cls._shared_sealed_temp = tempfile.TemporaryDirectory(
                prefix="broker-real-release-template-"
            )
            root = Path(cls._shared_sealed_temp.name) / "repo"
            root.mkdir()
            self._build_real_sealed_repository(root)
            cls._shared_sealed_root = root
        return cls._shared_sealed_root

    def _sealed_repository(
        self,
        *,
        release_gate_failures: list[str] | None = None,
        merge_approved: bool = True,
    ) -> tuple[Path, dict, dict]:
        root = Path(tempfile.mkdtemp(prefix="sealed-repo-", dir=self.base))
        shutil.copytree(self._shared_sealed_repository(), root, dirs_exist_ok=True)
        task_path = root / ".harness" / "tasks" / "NUR-OPS-001" / "task.json"
        state_path = root / ".harness" / "state" / "active-task.json"
        task = json.loads(task_path.read_text(encoding="utf-8"))
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not merge_approved:
            task["manual_approvals"]["merge"] = {
                "required": True,
                "status": "pending",
                "approved_by": None,
                "approved_at": None,
            }
            task_path.write_text(
                json.dumps(task, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        tracked_mutation = False
        for failure in release_gate_failures or []:
            if failure == "review missing":
                (task_path.parent / "review.md").write_text(
                    "# Review\n\ninvalid\n", encoding="utf-8"
                )
                tracked_mutation = True
            elif failure == "evidence stale":
                with (task_path.parent / "evidence.md").open(
                    "a", encoding="utf-8"
                ) as handle:
                    handle.write("\nEvidence changed after independent approval.\n")
                tracked_mutation = True
            elif failure == "plan artifacts stale":
                with (task_path.parent / "implementation-plan.md").open(
                    "a", encoding="utf-8"
                ) as handle:
                    handle.write("\nPlan changed after approval.\n")
                tracked_mutation = True
            elif failure == "review-pack missing":
                packs = sorted(
                    (root / ".harness" / "reports" / task["id"]).glob(
                        "*-review-pack/review-pack.json"
                    )
                )
                if not packs:
                    raise AssertionError("real release fixture lacks review-pack")
                packs[-1].unlink()
            elif failure == "decision context stale":
                state["decision_context_sha256"] = "f" * 64
            else:
                raise AssertionError(f"unknown release gate failure: {failure}")
        if tracked_mutation:
            self._git(root, "add", "-A")
            self._git(root, "commit", "-m", "make release gate stale")
            state["release_commit"] = self._git(root, "rev-parse", "HEAD")
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if merge_approved and not release_gate_failures:
            dirty = self._git(
                root, "status", "--porcelain=v1", "--untracked-files=all"
            )
            if dirty:
                raise AssertionError(f"copied release fixture is dirty: {dirty!r}")
        return root, task, state

    def _repository_broker(
        self, root: Path, *, runner: RecordingTransport | None = None
    ) -> remote.RemoteExecutionBroker:
        self.active_runner = runner if runner is not None else self.runner
        self.active_repository_root = root
        return remote.RemoteExecutionBroker.from_repository("NUR-OPS-001")

    def test_read_only_action_uses_pinned_open_ssh_options_and_redacts(self) -> None:
        broker = self._broker()
        evidence = broker.execute("inventory_pwd")
        self.assertTrue(evidence["success"])
        self.assertNotIn("hunter2", json.dumps(evidence))
        self.assertNotIn("abc.def.ghi", json.dumps(evidence))
        self.assertNotIn("13800138000", json.dumps(evidence))
        self.assertIn("[REDACTED]", evidence["stdout"])
        argv, timeout, limit = self.runner.calls[0]
        self.assertEqual(argv[0], str(self.ssh_executable))
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertIn(
            f"UserKnownHostsFile={remote._open_ssh_path(self.known_hosts)}", argv
        )
        self.assertIn("GlobalKnownHostsFile=none", argv)
        self.assertIn("IdentitiesOnly=yes", argv)
        self.assertIn("IdentityAgent=none", argv)
        self.assertIn("ProxyCommand=none", argv)
        self.assertIn("ProxyJump=none", argv)
        self.assertEqual(argv[1:3], ("-F", "none"))
        self.assertIn("root@38.12.21.18", argv)
        self.assertEqual(argv[-1], "cd -- /root/jia/miaomu && exec pwd")
        self.assertEqual(timeout, 30)
        self.assertEqual(limit, remote.HARD_MAX_OUTPUT_BYTES)
        self.assertNotIn(str(self.identity), json.dumps(evidence))

    def test_read_only_curl_allows_loopback_and_pinned_https_hostname(self) -> None:
        positive_argv = (
            ["curl", "-q", "--noproxy", "*", "http://127.0.0.1:88/health"],
            ["curl", "--disable", "--noproxy", "*", "https://[::1]/health"],
            [
                "curl",
                "-q",
                "-fsS",
                "--request",
                "GET",
                "--connect-timeout",
                "5",
                "--max-time",
                "20",
                "--noproxy",
                "*",
                "http://127.0.0.1:88/health",
            ],
            [
                "curl",
                "-q",
                "-IsS",
                "--noproxy",
                "*",
                "http://127.0.0.1:88/health",
            ],
            [
                "curl",
                "-q",
                "--noproxy",
                "*",
                "--resolve",
                "supervise.jiayyy.cn:443:127.0.0.1",
                "https://supervise.jiayyy.cn/health",
            ],
            [
                "curl",
                "-q",
                "--noproxy",
                "*",
                "--resolve=supervise.jiayyy.cn:443:[::1]",
                "https://supervise.jiayyy.cn:443/health",
            ],
        )
        for action_argv in positive_argv:
            with self.subTest(argv=action_argv):
                task = copy.deepcopy(self.task)
                task["remote_execution"]["allowed_actions"][0]["argv"] = action_argv
                runner = RecordingTransport()
                evidence = self._broker(task=task, runner=runner).execute(
                    "inventory_pwd"
                )
                self.assertTrue(evidence["success"])
                self.assertEqual(evidence["action"]["argv"], action_argv)

    def test_read_only_curl_rejects_ambiguous_or_external_resolution(self) -> None:
        rejected_argv = (
            ["curl", "https://supervise.jiayyy.cn/"],
            [
                "curl",
                "--resolve",
                "supervise.jiayyy.cn:443:127.0.0.2",
                "https://supervise.jiayyy.cn/",
            ],
            [
                "curl",
                "--resolve",
                "supervise.jiayyy.cn:443:127.0.0.1,::1",
                "https://supervise.jiayyy.cn/",
            ],
            [
                "curl",
                "--resolve",
                "*:443:127.0.0.1",
                "https://supervise.jiayyy.cn/",
            ],
            [
                "curl",
                "--resolve",
                "other.jiayyy.cn:443:127.0.0.1",
                "https://supervise.jiayyy.cn/",
            ],
            [
                "curl",
                "--resolve",
                "supervise.jiayyy.cn:80:127.0.0.1",
                "https://supervise.jiayyy.cn/",
            ],
            [
                "curl",
                "--resolve",
                "supervise.jiayyy.cn:443:127.0.0.1",
                "https://supervise.jiayyy.cn:8443/",
            ],
            [
                "curl",
                "--resolve",
                "supervise.jiayyy.cn:443:127.0.0.1",
                "http://supervise.jiayyy.cn/",
            ],
            [
                "curl",
                "--resolve",
                "supervise.jiayyy.cn:443:127.0.0.1",
                "https://user@supervise.jiayyy.cn/",
            ],
            [
                "curl",
                "-k",
                "--resolve",
                "supervise.jiayyy.cn:443:127.0.0.1",
                "https://supervise.jiayyy.cn/",
            ],
            [
                "curl",
                "--insecure",
                "--resolve",
                "supervise.jiayyy.cn:443:127.0.0.1",
                "https://supervise.jiayyy.cn/",
            ],
            [
                "curl",
                "-L",
                "--resolve",
                "supervise.jiayyy.cn:443:127.0.0.1",
                "https://supervise.jiayyy.cn/",
            ],
            [
                "curl",
                "-fsSL",
                "--resolve",
                "supervise.jiayyy.cn:443:127.0.0.1",
                "https://supervise.jiayyy.cn/",
            ],
            [
                "curl",
                "--resolve",
                "supervise.jiayyy.cn:443:127.0.0.1",
                "--resolve",
                "supervise.jiayyy.cn:443:[::1]",
                "https://supervise.jiayyy.cn/",
            ],
            [
                "curl",
                "--resolve",
                "supervise.jiayyy.cn:443:127.0.0.1",
                "https://supervise.jiayyy.cn/",
                "https://supervise.jiayyy.cn/second",
            ],
            [
                "curl",
                "--resolve",
                "localhost:443:127.0.0.1",
                "https://localhost/",
            ],
        )
        for action_argv in rejected_argv:
            with self.subTest(argv=action_argv):
                task = copy.deepcopy(self.task)
                task["remote_execution"]["allowed_actions"][0]["argv"] = action_argv
                with self.assertRaises(remote.RemoteBrokerError):
                    self._broker(task=task)

    def test_read_only_curl_requires_config_proxy_and_read_method_guards(self) -> None:
        safe_tail = [
            "--noproxy",
            "*",
            "--resolve",
            "supervise.jiayyy.cn:443:127.0.0.1",
            "https://supervise.jiayyy.cn/",
        ]
        rejected_argv = (
            ["curl", *safe_tail],
            [
                "curl",
                "-q",
                "--resolve",
                "supervise.jiayyy.cn:443:127.0.0.1",
                "https://supervise.jiayyy.cn/",
            ],
            ["curl", "-q", "--noproxy=*", *safe_tail[2:]],
            ["curl", "-q", "-XPOST", *safe_tail],
            ["curl", "-q", "--request=POST", *safe_tail],
            ["curl", "-q", "--data-urlencode", "a=b", *safe_tail],
            ["curl", "-q", "-da=b", *safe_tail],
            ["curl", "-q", "--form-string", "a=b", *safe_tail],
            ["curl", "-q", "-L", *safe_tail],
            ["curl", "-q", "--insecure", *safe_tail],
            ["curl", "-q", "--next", *safe_tail],
            ["curl", "-q", "-:", *safe_tail],
            ["curl", "-q", "--proxy", "http://127.0.0.1:9", *safe_tail],
            ["curl", "-q", "--socks5", "127.0.0.1:9", *safe_tail],
            ["curl", "-q", "--preproxy", "socks5://127.0.0.1:9", *safe_tail],
            ["curl", "-q", "--variable", "name=value", *safe_tail],
            ["curl", "-q", "--expand-url", "{{name}}", *safe_tail],
            ["curl", "-q", "--output", "result.txt", *safe_tail],
            ["curl", "-q", "--remote-name", *safe_tail],
            ["curl", "-q", "--user", "user:password", *safe_tail],
            ["curl", "-q", "--oauth2-bearer", "token", *safe_tail],
            ["curl", "-q", "--header", "Authorization: secret", *safe_tail],
            ["curl", "-q", "--location", *safe_tail],
            ["curl", "-q", "--location-trusted", *safe_tail],
            ["curl", "-q", "--cert", "client.pem", *safe_tail],
            ["curl", "-q", "--connect-to", "::127.0.0.1:", *safe_tail],
            ["curl", "-q", "--unix-socket", "/tmp/socket", *safe_tail],
            ["curl", "-q", "--parallel", *safe_tail],
            ["curl", "-q", "--url", "https://example.invalid", *safe_tail],
        )
        for action_argv in rejected_argv:
            with self.subTest(argv=action_argv):
                task = copy.deepcopy(self.task)
                task["remote_execution"]["allowed_actions"][0]["argv"] = action_argv
                with self.assertRaises(remote.RemoteBrokerError):
                    self._broker(task=task)

    def test_identity_file_is_never_opened(self) -> None:
        original_open = Path.open
        identity = self.identity.resolve()

        def guarded_open(path: Path, *args, **kwargs):
            if path.resolve() == identity:
                raise AssertionError("identity contents were opened")
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", guarded_open):
            broker = self._broker()
            broker.execute("inventory_pwd")

    def test_unknown_action_and_mutating_action_default_deny(self) -> None:
        broker = self._broker()
        with self.assertRaisesRegex(remote.RemoteBrokerError, "action_denied"):
            broker.execute("not_allowed")
        with self.assertRaisesRegex(remote.RemoteBrokerError, "mutation_denied"):
            broker.execute("upload_release")
        with self.assertRaisesRegex(remote.RemoteBrokerError, "mutation_denied"):
            broker.execute("upload_release", allow_mutating=True)
        self.assertEqual(self.runner.calls, [])

    def test_mutating_upload_uses_stable_ssh_stream_and_exact_target(self) -> None:
        root, _task, _state = self._sealed_repository()
        runner = RecordingTransport()
        broker = self._repository_broker(root, runner=runner)
        evidence = broker.execute("upload_release", allow_mutating=True)
        self.assertTrue(evidence["success"])
        argv = runner.calls[0][0]
        self.assertEqual(argv[0], str(self.ssh_executable))
        self.assertIn("root@38.12.21.18", argv)
        self.assertIn("mktemp --", argv[-1])
        self.assertIn("sha256sum --", argv[-1])
        self.assertIn("mv -fT --", argv[-1])
        self.assertIn("/root/jia/miaomu/release.tar", argv[-1])
        self.assertEqual(runner.stdin_payloads, [b"sealed release artifact"])
        verification = evidence["upload_verification"]
        self.assertTrue(verification["stable_handle_verified_before_and_after"])
        self.assertTrue(verification["remote_staging_verification_confirmed"])
        self.assertEqual(verification["wire_transport"], "ssh_stdin")
        stage_dir = (
            root
            / ".harness"
            / "runs"
            / "NUR-OPS-001"
            / ".broker-upload-staging"
        )
        self.assertEqual(list(stage_dir.iterdir()), [])

    def test_only_exact_deployment_root_bootstrap_skips_prior_cd(self) -> None:
        root, _task, _state = self._sealed_repository()
        runner = RecordingTransport()
        broker = self._repository_broker(root, runner=runner)
        evidence = broker.execute(
            "bootstrap_deployment_root", allow_mutating=True
        )
        self.assertTrue(evidence["success"])
        argv = runner.calls[0][0]
        self.assertEqual(
            argv[-1], "exec mkdir -p -- /root/jia/miaomu"
        )

        task = copy.deepcopy(self.task)
        task["remote_execution"]["allowed_actions"].append(
            {
                "id": "second_bootstrap",
                "transport": "ssh",
                "mode": "mutating",
                "timeout_seconds": 30,
                "cwd": "/root/jia/miaomu",
                "argv": ["mkdir", "-p", "--", "/root/jia/miaomu"],
            }
        )
        with self.assertRaisesRegex(remote.RemoteBrokerError, "only one"):
            self._broker(task=task)

    def test_download_is_read_only_and_stays_in_repository(self) -> None:
        broker = self._broker()
        evidence = broker.execute("download_log")
        self.assertTrue(evidence["success"])
        argv = self.runner.calls[0][0]
        self.assertEqual(argv[0], str(self.ssh_executable))
        self.assertEqual(argv[-2], "root@38.12.21.18")
        self.assertEqual(
            argv[-1], "exec cat -- /root/jia/miaomu/deploy.log"
        )
        self.assertNotIn(str(self.run_dir / "deploy.log"), argv)
        destination = self.run_dir / "deploy.log"
        self.assertEqual(
            destination.read_bytes(), b"downloaded deployment evidence\n"
        )
        verification = evidence["download_verification"]
        self.assertEqual(
            verification["sha256"], hashlib.sha256(destination.read_bytes()).hexdigest()
        )
        self.assertTrue(verification["stable_handle_verified"])
        self.assertTrue(verification["atomic_no_overwrite_publish_confirmed"])
        self.assertEqual(
            verification["wire_transport"], "ssh_stdout_to_stable_handle"
        )
        self.assertEqual(list(self.run_dir.glob(".broker-download-*")), [])

    def test_download_failure_or_stage_hardlink_never_publishes(self) -> None:
        failed = remote.ProcessOutcome(
            exit_code=1,
            stdout=b"",
            stderr=b"remote read failed\n",
            stdout_bytes=7,
            stderr_bytes=19,
            timed_out=False,
            output_limited=False,
            duration_ms=4,
        )
        runner = RecordingTransport(failed, download_payload=b"partial")
        evidence = self._broker(runner=runner).execute("download_log")
        self.assertFalse(evidence["success"])
        self.assertFalse((self.run_dir / "deploy.log").exists())
        self.assertEqual(list(self.run_dir.glob(".broker-download-*")), [])

        extra_link = self.run_dir / "attacker-stage-link"

        def hardlink_stage(_handle: BinaryIO) -> None:
            stage = next(self.run_dir.glob(".broker-download-*/payload.download"))
            os.link(stage, extra_link)

        runner = RecordingTransport(during_download=hardlink_stage)
        with self.assertRaisesRegex(remote.RemoteBrokerError, "link count|identity"):
            self._broker(runner=runner).execute("download_log")
        self.assertFalse((self.run_dir / "deploy.log").exists())
        self.assertEqual(list(self.run_dir.glob(".broker-download-*")), [])
        extra_link.unlink()

    def test_download_concurrent_hardlink_or_symlink_target_is_not_overwritten(self) -> None:
        destination = self.run_dir / "deploy.log"
        attacker_source = self.run_dir / "attacker-owned"
        attacker_source.write_bytes(b"attacker-owned-content")

        def occupy_with_hardlink(_handle: BinaryIO) -> None:
            os.link(attacker_source, destination)

        runner = RecordingTransport(during_download=occupy_with_hardlink)
        with self.assertRaisesRegex(remote.RemoteBrokerError, "new evidence file|appeared"):
            self._broker(runner=runner).execute("download_log")
        self.assertEqual(destination.read_bytes(), b"attacker-owned-content")
        self.assertEqual(attacker_source.read_bytes(), b"attacker-owned-content")
        destination.unlink()

        original_lstat = Path.lstat
        fake_symlink_stat = SimpleNamespace(st_mode=0o120777)

        def concurrent_symlink_lstat(path: Path):
            if path == destination:
                return fake_symlink_stat
            return original_lstat(path)

        runner = RecordingTransport()
        with mock.patch.object(Path, "lstat", new=concurrent_symlink_lstat), mock.patch.object(
            remote.os, "link", wraps=os.link
        ) as atomic_link:
            with self.assertRaisesRegex(remote.RemoteBrokerError, "new evidence file"):
                self._broker(runner=runner).execute("download_log")
            atomic_link.assert_not_called()
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.run_dir.glob(".broker-download-*")), [])

    def test_download_size_limit_fails_closed_and_cleans_stage(self) -> None:
        runner = RecordingTransport(download_payload=b"too-large")
        with mock.patch.object(remote, "HARD_MAX_DOWNLOAD_BYTES", 4):
            with self.assertRaisesRegex(remote.RemoteBrokerError, "size|exceeds"):
                self._broker(runner=runner).execute("download_log")
        self.assertFalse((self.run_dir / "deploy.log").exists())
        self.assertEqual(list(self.run_dir.glob(".broker-download-*")), [])

    def test_download_cannot_overwrite_or_target_harness_control_files(self) -> None:
        destination = self.run_dir / "deploy.log"
        destination.write_text("existing evidence\n", encoding="utf-8")
        broker = self._broker()
        with self.assertRaisesRegex(remote.RemoteBrokerError, "new evidence file"):
            broker.execute("download_log")

        task = copy.deepcopy(self.task)
        task["remote_execution"]["allowed_actions"][2]["destination"] = (
            "scripts/harness_remote.py"
        )
        with self.assertRaisesRegex(
            remote.RemoteBrokerError, r"\.harness/runs/NUR-OPS-001"
        ):
            self._broker(task=task)

    def test_contract_hash_drift_is_denied(self) -> None:
        state = self._state(self.task)
        task = copy.deepcopy(self.task)
        task["remote_execution"]["host"] = "127.0.0.1"
        with self.assertRaisesRegex(remote.RemoteBrokerError, "contract_drift"):
            self._broker(task=task, state=state)

        stale = copy.deepcopy(self.task)
        stale["schema_version"] = 1
        with self.assertRaisesRegex(remote.RemoteBrokerError, "schema version 2"):
            self._broker(task=stale, state=self._state(stale))

    def test_repository_factory_validates_seal_git_cleanliness_and_artifacts(self) -> None:
        root, _task, _state = self._sealed_repository()
        runner = RecordingTransport()
        evidence = self._repository_broker(root, runner=runner).execute(
            "upload_release", allow_mutating=True
        )
        self.assertTrue(evidence["success"])

        root, _task, state = self._sealed_repository()
        for key in (
            "release_commit",
            "release_contract_sha256",
            "release_policy_sha256",
            "release_sealed_at",
            "release_upload_artifacts",
        ):
            state.pop(key)
        (root / ".harness" / "state" / "active-task.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(remote.RemoteBrokerError, "release_seal_invalid"):
            self._repository_broker(root).execute(
                "upload_release", allow_mutating=True
            )

        root, _task, _state = self._sealed_repository()
        (root / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(remote.RemoteBrokerError, "clean worktree"):
            self._repository_broker(root).execute(
                "upload_release", allow_mutating=True
            )

        root, _task, _state = self._sealed_repository()
        (root / "head-drift.txt").write_text("new commit\n", encoding="utf-8")
        self._git(root, "add", "head-drift.txt")
        self._git(root, "commit", "-m", "head drift")
        with self.assertRaisesRegex(remote.RemoteBrokerError, "Git HEAD differs"):
            self._repository_broker(root).execute(
                "upload_release", allow_mutating=True
            )

        root, _task, _state = self._sealed_repository()
        artifact = root / ".harness" / "runs" / "NUR-OPS-001" / "release.tar"
        artifact.write_bytes(b"X" * artifact.stat().st_size)
        with self.assertRaisesRegex(remote.RemoteBrokerError, "artifact"):
            self._repository_broker(root).execute(
                "upload_release", allow_mutating=True
            )

    def test_mutating_broker_requires_merge_and_full_release_check(self) -> None:
        root, _task, _state = self._sealed_repository(merge_approved=False)
        with self.assertRaisesRegex(remote.RemoteBrokerError, "merge approval"):
            self._repository_broker(root).execute(
                "bootstrap_deployment_root", allow_mutating=True
            )

        release_failures = (
            "review missing",
            "evidence stale",
            "review-pack missing",
            "plan artifacts stale",
            "decision context stale",
        )
        for failure in release_failures:
            with self.subTest(failure=failure):
                root, _task, _state = self._sealed_repository(
                    release_gate_failures=[failure]
                )
                with self.assertRaisesRegex(
                    remote.RemoteBrokerError, "release_check_failed"
                ):
                    self._repository_broker(root).execute(
                        "bootstrap_deployment_root", allow_mutating=True
                    )

    def test_git_and_release_check_ignore_inherited_environment_injection(self) -> None:
        root, _task, _state = self._sealed_repository()
        hijack = self.base / "environment-hijack"
        hijack.mkdir()
        self._git(root, "config", "core.fsmonitor", "definitely-missing-fsmonitor")
        self._git(root, "config", "core.untrackedCache", "true")
        injected = {
            "PATH": str(hijack),
            "GIT_DIR": str(hijack / "fake.git"),
            "GIT_WORK_TREE": str(hijack),
            "GIT_INDEX_FILE": str(hijack / "index"),
            "GIT_CONFIG_GLOBAL": str(hijack / "gitconfig"),
            "GIT_EXTERNAL_DIFF": "evil-diff",
            "GIT_SSH": "evil-ssh",
            "GIT_SSH_COMMAND": "evil-ssh-command",
            "GIT_PAGER": "evil-pager",
            "PAGER": "evil-pager",
            "PYTHONHOME": str(hijack),
            "PYTHONPATH": str(hijack),
            "PYTHONSTARTUP": str(hijack / "startup.py"),
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "socks5://127.0.0.1:9",
        }
        runner = RecordingTransport()
        with mock.patch.dict(os.environ, injected, clear=False):
            evidence = self._repository_broker(root, runner=runner).execute(
                "upload_release", allow_mutating=True
            )
        self.assertTrue(evidence["success"])

    def test_full_mutating_gate_rejects_repo_filter_without_executing_it(self) -> None:
        root, _task, _state = self._sealed_repository()
        marker = root.parent / "clean-filter-executed"
        clean_script = root.parent / "clean-filter.py"
        original_harness = root.parent / "original-harness.py"
        harness_path = root / "scripts" / "harness.py"
        original_harness.write_bytes(harness_path.read_bytes())
        clean_script.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "Path(sys.argv[1]).write_text('executed', encoding='utf-8')\n"
            "sys.stdout.buffer.write(Path(sys.argv[2]).read_bytes())\n",
            encoding="utf-8",
        )
        command = " ".join(
            shlex.quote(Path(value).as_posix())
            for value in (
                sys.executable,
                clean_script,
                marker,
                original_harness,
            )
        )
        self._git(root, "config", "filter.harness.clean", command)
        info_attributes = root / ".git" / "info" / "attributes"
        info_attributes.write_text(
            "scripts/harness.py filter=harness\n", encoding="utf-8"
        )
        harness_path.write_bytes(b"raise RuntimeError('tampered harness')\n")

        with self.assertRaisesRegex(
            remote.RemoteBrokerError, "Git config|execution-capable|transformation"
        ):
            self._repository_broker(root).execute(
                "bootstrap_deployment_root", allow_mutating=True
            )
        self.assertFalse(marker.exists())
        self.assertEqual(self.runner.calls, [])

    def test_worktree_attributes_transform_is_rejected_before_release_check(self) -> None:
        root, _task, _state = self._sealed_repository()
        (root / ".gitattributes").write_text(
            "scripts/harness.py working-tree-encoding=UTF-16\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(remote.RemoteBrokerError, "transformation"):
            self._repository_broker(root).execute(
                "bootstrap_deployment_root", allow_mutating=True
            )
        self.assertEqual(self.runner.calls, [])

    def test_release_check_rejects_ignored_python_stdlib_shadow(self) -> None:
        root, _task, _state = self._sealed_repository()
        info_exclude = root / ".git" / "info" / "exclude"
        with info_exclude.open("a", encoding="utf-8") as handle:
            handle.write("scripts/json.py\n")
        (root / "scripts" / "json.py").write_text(
            "raise RuntimeError('must never be imported')\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(remote.RemoteBrokerError, "stdlib shadow"):
            self._repository_broker(root).execute(
                "bootstrap_deployment_root", allow_mutating=True
            )

    def test_upload_replacement_before_transfer_is_rejected(self) -> None:
        root, _task, _state = self._sealed_repository()
        broker = self._repository_broker(root)
        artifact = root / ".harness" / "runs" / "NUR-OPS-001" / "release.tar"
        artifact.write_bytes(b"X" * artifact.stat().st_size)
        with self.assertRaisesRegex(remote.RemoteBrokerError, "artifact"):
            broker.execute("upload_release", allow_mutating=True)

    def test_upload_source_replacement_during_transfer_cannot_change_wire_bytes(self) -> None:
        root, _task, _state = self._sealed_repository()
        artifact = root / ".harness" / "runs" / "NUR-OPS-001" / "release.tar"

        def replace_source(_handle: BinaryIO) -> None:
            artifact.write_bytes(b"attacker replacement")

        runner = RecordingTransport(during_transfer=replace_source)
        evidence = self._repository_broker(root, runner=runner).execute(
            "upload_release", allow_mutating=True
        )
        self.assertTrue(evidence["success"])
        self.assertEqual(runner.stdin_payloads, [b"sealed release artifact"])

    def test_upload_stage_mutation_during_transfer_is_rejected(self) -> None:
        root, _task, _state = self._sealed_repository()

        def mutate_stage(_handle: BinaryIO) -> None:
            stage_dir = (
                root
                / ".harness"
                / "runs"
                / "NUR-OPS-001"
                / ".broker-upload-staging"
            )
            stage_path = next(stage_dir.iterdir())
            stage_path.write_bytes(b"X" * stage_path.stat().st_size)

        runner = RecordingTransport(during_transfer=mutate_stage)
        with self.assertRaisesRegex(remote.RemoteBrokerError, "artifact_drift"):
            self._repository_broker(root, runner=runner).execute(
                "upload_release", allow_mutating=True
            )

    def test_upload_stage_is_exclusive_and_remote_receipt_is_required(self) -> None:
        root, _task, state = self._sealed_repository()
        sealed = state["release_upload_artifacts"][0]
        stage_dir = (
            root
            / ".harness"
            / "runs"
            / "NUR-OPS-001"
            / ".broker-upload-staging"
        )
        stage_dir.mkdir()
        conflict = stage_dir / f"{sealed['sha256']}.{sealed['size']}.upload"
        conflict.write_bytes(b"untrusted preexisting stage")
        with self.assertRaisesRegex(remote.RemoteBrokerError, "stage_conflict"):
            self._repository_broker(root).execute(
                "upload_release", allow_mutating=True
            )
        conflict.unlink()

        missing_receipt = RecordingTransport(
            remote.ProcessOutcome(
                exit_code=0,
                stdout=b"unexpected success\n",
                stderr=b"",
                stdout_bytes=19,
                stderr_bytes=0,
                timed_out=False,
                output_limited=False,
                duration_ms=3,
            )
        )
        with self.assertRaisesRegex(remote.RemoteBrokerError, "verified receipt"):
            self._repository_broker(root, runner=missing_receipt).execute(
                "upload_release", allow_mutating=True
            )

    def test_production_api_has_no_test_factory_or_runtime_overrides(self) -> None:
        self.assertFalse(hasattr(remote.RemoteExecutionBroker, "from_validated_harness"))
        self.assertFalse(hasattr(remote, "_FACTORY_TOKEN"))
        with self.assertRaisesRegex(remote.RemoteBrokerError, "factory_required"):
            remote.RemoteExecutionBroker()
        with self.assertRaises(TypeError):
            remote.RemoteExecutionBroker.from_repository(
                "NUR-OPS-001", self.root, runner=self.runner
            )
        with self.assertRaises(TypeError):
            remote.RemoteExecutionBroker.release_upload_artifact_facts(
                task=self.task, repository_root=self.root
            )

    def test_repository_factory_rejects_reparse_control_files(self) -> None:
        root, _task, _state = self._sealed_repository()
        state_path = (root / ".harness" / "state" / "active-task.json").resolve()
        original_lstat = Path.lstat

        def marked_lstat(path: Path):
            value = original_lstat(path)
            if path.absolute() == state_path:
                return SimpleNamespace(
                    st_mode=value.st_mode,
                    st_file_attributes=0x400,
                )
            return value

        with mock.patch.object(Path, "lstat", marked_lstat):
            with self.assertRaisesRegex(remote.RemoteBrokerError, "reparse point"):
                self._repository_broker(root)

    def test_host_key_mismatch_is_denied(self) -> None:
        task = copy.deepcopy(self.task)
        task["remote_execution"]["host_key_fingerprint"] = "SHA256:" + "A" * 43
        with self.assertRaisesRegex(remote.RemoteBrokerError, "host_key_mismatch"):
            self._broker(task=task)

    def test_deployment_root_and_managed_path_fail_closed(self) -> None:
        task = copy.deepcopy(self.task)
        task["remote_execution"]["deployment_root"] = "/"
        task["remote_execution"]["managed_roots"][0] = "/"
        with self.assertRaisesRegex(remote.RemoteBrokerError, "unsafe_remote_root"):
            self._broker(task=task)

        task = copy.deepcopy(self.task)
        task["remote_execution"]["allowed_actions"][0]["cwd"] = "/etc"
        with self.assertRaisesRegex(
            remote.RemoteBrokerError,
            "unmanaged_remote_path|destructive_action_denied",
        ):
            self._broker(task=task)

        task = copy.deepcopy(self.task)
        task["remote_execution"]["managed_roots"].append(
            "/root/jia/miaomu/releases"
        )
        with self.assertRaisesRegex(remote.RemoteBrokerError, "contain one another"):
            self._broker(task=task)

    def test_absolute_and_mutating_host_paths_cannot_escape_managed_roots(self) -> None:
        task = copy.deepcopy(self.task)
        task["remote_execution"]["allowed_actions"][0]["argv"] = [
            "cat",
            "/etc/os-release",
        ]
        with self.assertRaisesRegex(
            remote.RemoteBrokerError,
            "unmanaged_remote_path|destructive_action_denied",
        ):
            self._broker(task=task)

        task = copy.deepcopy(self.task)
        task["remote_execution"]["allowed_actions"].append(
            {
                "id": "escape_file_mutation",
                "transport": "ssh",
                "mode": "mutating",
                "timeout_seconds": 30,
                "cwd": "/root/jia/miaomu",
                "argv": ["rm", "-f", "../../outside"],
            }
        )
        with self.assertRaisesRegex(
            remote.RemoteBrokerError,
            "unmanaged_remote_path|destructive_action_denied",
        ):
            self._broker(task=task)

        task = copy.deepcopy(self.task)
        task["remote_execution"]["allowed_actions"].append(
            {
                "id": "escape_compose_file",
                "transport": "ssh",
                "mode": "mutating",
                "timeout_seconds": 30,
                "cwd": "/root/jia/miaomu",
                "argv": ["docker", "compose", "-f", "/etc/compose.yaml", "up"],
            }
        )
        with self.assertRaisesRegex(remote.RemoteBrokerError, "unmanaged_remote_path"):
            self._broker(task=task)

    def test_relative_path_operands_and_find_output_actions_fail_closed(self) -> None:
        task = copy.deepcopy(self.task)
        task["remote_execution"]["allowed_actions"][0]["argv"] = [
            "cat",
            "config/caddy/Caddyfile",
        ]
        self._broker(task=task)

        for relative_path in ("../outside/file", "config/../outside"):
            with self.subTest(relative_path=relative_path):
                task = copy.deepcopy(self.task)
                task["remote_execution"]["allowed_actions"][0]["argv"] = [
                    "cat",
                    relative_path,
                ]
                with self.assertRaisesRegex(
                    remote.RemoteBrokerError, "parent traversal"
                ):
                    self._broker(task=task)

        for find_action in ("-fprint", "-fprint0", "-fprintf", "-fls"):
            with self.subTest(find_action=find_action):
                task = copy.deepcopy(self.task)
                task["remote_execution"]["allowed_actions"][0]["argv"] = [
                    "find",
                    ".",
                    find_action,
                    "/root/jia/miaomu/find-output",
                ]
                with self.assertRaisesRegex(
                    remote.RemoteBrokerError, "not read-only|read-only catalog"
                ):
                    self._broker(task=task)

        task = copy.deepcopy(self.task)
        task["remote_execution"]["allowed_actions"].append(
            {
                "id": "escape_bind_mount",
                "transport": "ssh",
                "mode": "mutating",
                "timeout_seconds": 30,
                "cwd": "/root/jia/miaomu",
                "argv": [
                    "docker",
                    "run",
                    "--mount",
                    "type=bind,source=/etc,target=/host-etc",
                    "busybox:1.36",
                ],
            }
        )
        with self.assertRaisesRegex(remote.RemoteBrokerError, "unmanaged_remote_path"):
            self._broker(task=task)

    def test_duplicate_action_shell_newline_and_sensitive_arg_are_denied(self) -> None:
        task = copy.deepcopy(self.task)
        duplicate = copy.deepcopy(task["remote_execution"]["allowed_actions"][0])
        task["remote_execution"]["allowed_actions"].append(duplicate)
        with self.assertRaisesRegex(remote.RemoteBrokerError, "duplicate"):
            self._broker(task=task)

        task = copy.deepcopy(self.task)
        task["remote_execution"]["allowed_actions"][0]["argv"] = ["bash", "-c", "pwd"]
        with self.assertRaisesRegex(remote.RemoteBrokerError, "shell_denied"):
            self._broker(task=task)

        task = copy.deepcopy(self.task)
        task["remote_execution"]["allowed_actions"][0]["argv"] = ["pwd\nwhoami"]
        with self.assertRaisesRegex(remote.RemoteBrokerError, "control characters"):
            self._broker(task=task)

        task = copy.deepcopy(self.task)
        task["remote_execution"]["allowed_actions"][0]["argv"] = [
            "curl",
            "Authorization=secret-value",
        ]
        with self.assertRaisesRegex(remote.RemoteBrokerError, "sensitive_argument"):
            self._broker(task=task)

    def test_destructive_action_and_false_read_only_label_are_denied(self) -> None:
        task = copy.deepcopy(self.task)
        task["remote_execution"]["allowed_actions"][0]["mode"] = "mutating"
        task["remote_execution"]["allowed_actions"][0]["argv"] = ["rm", "-rf", "/"]
        with self.assertRaisesRegex(remote.RemoteBrokerError, "destructive_action_denied"):
            self._broker(task=task)

        task = copy.deepcopy(self.task)
        task["remote_execution"]["allowed_actions"][0]["argv"] = [
            "docker",
            "compose",
            "up",
            "-d",
        ]
        with self.assertRaisesRegex(remote.RemoteBrokerError, "mode_mismatch"):
            self._broker(task=task)

    def test_read_only_positive_grammar_rejects_embedded_execution_and_writers(self) -> None:
        denied = (
            ["sed", "-n", "e touch pwned", "input.txt"],
            ["sed", "-i.bak", "s/a/b/", "input.txt"],
            ["sed", "-ni", "s/a/b/", "input.txt"],
            ["ss", "-K", "dst", "127.0.0.1"],
            ["ss", "-D", "socket.dump"],
            ["date", "-s@0"],
            ["date", "--set=2026-01-01"],
            ["ip", "netns", "exec", "ns", "touch", "pwned"],
            ["ip", "n", "e", "ns", "touch", "pwned"],
            ["journalctl", "--setup-keys"],
            ["journalctl", "--update-catalog"],
            ["journalctl", "--vacuum-time=1s"],
            ["git", "diff", "--ext-diff"],
            ["caddy", "adapt", "-o", "rendered.json"],
            ["caddy", "adapt", "--output=rendered.json"],
            [
                "docker",
                "compose",
                "config",
                "--services",
                "--output",
                "rendered.yml",
            ],
            ["find", ".", "-exec", "touch", "pwned", ";"],
            ["pgrep", "--signal", "KILL", "process"],
        )
        for argv in denied:
            with self.subTest(argv=argv):
                task = copy.deepcopy(self.task)
                task["remote_execution"]["allowed_actions"][0]["argv"] = argv
                with self.assertRaises(remote.RemoteBrokerError):
                    self._broker(task=task)

        allowed = (
            ["date"],
            ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
            ["caddy", "version"],
            [
                "caddy",
                "validate",
                "--config",
                "/root/jia/miaomu/Caddyfile",
                "--adapter",
                "caddyfile",
            ],
            ["docker", "compose", "config", "--services", "--images"],
        )
        for argv in allowed:
            with self.subTest(argv=argv):
                task = copy.deepcopy(self.task)
                task["remote_execution"]["allowed_actions"][0]["argv"] = argv
                self._broker(task=task)

    def test_docker_read_only_output_is_limited_to_fixed_safe_fields(self) -> None:
        denied = (
            ["docker", "inspect", "jia-caddy"],
            ["docker", "container", "inspect", "jia-caddy"],
            ["docker", "image", "inspect", "shopxo-app:release"],
            [
                "docker",
                "container",
                "inspect",
                "--format",
                "{{json .Config}}",
                "jia-caddy",
            ],
            [
                "docker",
                "container",
                "inspect",
                "--format={{json .Config.Env}}",
                "jia-caddy",
            ],
            [
                "docker",
                "container",
                "inspect",
                "-f",
                "{{json .Config.Labels}}",
                "jia-caddy",
            ],
            [
                "docker",
                "container",
                "inspect",
                "--format",
                "{{json .Args}}",
                "jia-caddy",
            ],
            [
                "docker",
                "container",
                "inspect",
                "--format",
                "{{.Path}}",
                "jia-caddy",
            ],
            [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{json .Config}}",
                "shopxo-app:release",
            ],
            [
                "docker",
                "container",
                "inspect",
                "-f",
                "{{.Id}}",
                "--format",
                "{{.Name}}",
                "jia-caddy",
            ],
            ["docker", "container", "inspect", "-f", "{{.Id}}"],
            ["docker", "logs", "jia-caddy"],
            ["docker", "top", "jia-caddy"],
            ["docker", "info"],
            ["docker", "stats", "--no-stream"],
            ["docker", "ps"],
            ["docker", "ps", "-f", "{{.ID}}"],
            ["docker", "ps", "--format", "{{.Command}}"],
            ["docker", "ps", "--format", "{{json .}}"],
            ["docker", "container", "ls"],
            ["docker", "images"],
            ["docker", "images", "-f", "{{.ID}}"],
            ["docker", "image", "ls", "--format", "{{json .}}"],
            ["docker", "network", "inspect", "backend"],
            ["docker", "volume", "inspect", "db-data"],
            ["docker", "compose", "logs", "app"],
            ["docker", "compose", "top", "app"],
            ["docker", "compose", "ps"],
            ["docker", "compose", "ps", "--format", "json"],
            ["docker", "compose", "ps", "--format", "{{.Command}}"],
            ["docker", "compose", "images"],
        )
        for argv in denied:
            with self.subTest(argv=argv):
                task = copy.deepcopy(self.task)
                task["remote_execution"]["allowed_actions"][0]["argv"] = argv
                with self.assertRaises(remote.RemoteBrokerError):
                    self._broker(task=task)

        allowed = (
            [
                "docker",
                "container",
                "inspect",
                "-f",
                "{{.Id}}",
                "jia-caddy",
            ],
            [
                "docker",
                "container",
                "inspect",
                "--format={{json .Mounts}}",
                "jia-caddy",
            ],
            [
                "docker",
                "container",
                "inspect",
                "--format",
                "{{json .NetworkSettings.Ports}}",
                "jia-caddy",
            ],
            [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{json .RepoDigests}}",
                "jiayz00/miaomu:release",
            ],
            [
                "docker",
                "ps",
                "--all",
                "--format",
                "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}",
            ],
            ["docker", "container", "ls", "--format={{.Names}}"],
            [
                "docker",
                "images",
                "--digests",
                "--format",
                "{{.ID}}|{{.Repository}}|{{.Tag}}|{{.Digest}}|{{.Size}}",
            ],
            ["docker", "image", "ls", "--format={{.ID}}"],
            [
                "docker",
                "compose",
                "-f",
                "/root/jia/miaomu/compose.yaml",
                "ps",
                "--quiet",
            ],
            ["docker", "compose", "ps", "--all", "--quiet"],
            ["docker", "compose", "version"],
        )
        for argv in allowed:
            with self.subTest(argv=argv):
                task = copy.deepcopy(self.task)
                task["remote_execution"]["allowed_actions"][0]["argv"] = argv
                self._broker(task=task)

    def test_known_hosts_with_an_extra_target_key_is_denied(self) -> None:
        extra_blob = b"second-offline-host-key"
        extra_key = base64.b64encode(extra_blob).decode("ascii")
        with self.known_hosts.open("a", encoding="utf-8") as handle:
            handle.write(f"38.12.21.18 ssh-rsa {extra_key}\n")
        with self.assertRaisesRegex(remote.RemoteBrokerError, "host_key_mismatch"):
            self._broker()

    def test_hashed_known_hosts_target_is_supported(self) -> None:
        key_blob = b"offline-test-host-key-blob"
        key_data = base64.b64encode(key_blob).decode("ascii")
        salt = b"fixed-offline-salt"
        digest = hmac.new(salt, b"38.12.21.18", hashlib.sha1).digest()
        host_pattern = "|1|{}|{}".format(
            base64.b64encode(salt).decode("ascii").rstrip("="),
            base64.b64encode(digest).decode("ascii").rstrip("="),
        )
        self.known_hosts.write_text(
            f"{host_pattern} ssh-ed25519 {key_data}\n", encoding="utf-8"
        )
        evidence = self._broker().execute("inventory_pwd")
        self.assertTrue(evidence["success"])

    def test_ssh_config_reference_and_incomplete_forbidden_set_are_denied(self) -> None:
        task = copy.deepcopy(self.task)
        task["remote_execution"]["identity_reference"] = "ssh-config:miaomu"
        with self.assertRaisesRegex(remote.RemoteBrokerError, "user-ssh-file"):
            self._broker(task=task)

        task = copy.deepcopy(self.task)
        task["remote_execution"]["forbidden_actions"].pop()
        with self.assertRaisesRegex(remote.RemoteBrokerError, "complete fixed denial set"):
            self._broker(task=task)

        task = copy.deepcopy(self.task)
        task["remote_execution"]["known_hosts_reference"] = task[
            "remote_execution"
        ]["identity_reference"]
        with self.assertRaisesRegex(remote.RemoteBrokerError, "must be different files"):
            self._broker(task=task)

    def test_timeout_and_managed_root_count_use_hard_limits(self) -> None:
        task = copy.deepcopy(self.task)
        task["remote_execution"]["allowed_actions"][0]["timeout_seconds"] = 1801
        with self.assertRaisesRegex(remote.RemoteBrokerError, "timeout is invalid"):
            self._broker(task=task)

        task = copy.deepcopy(self.task)
        task["remote_execution"]["managed_roots"] = [
            "/root/jia/miaomu",
            "/root/jia/caddy",
            "/root/jia/site-a",
            "/root/jia/site-b",
            "/root/jia/site-c",
            "/root/jia/site-d",
            "/root/jia/site-e",
            "/root/jia/site-f",
            "/root/jia/site-g",
        ]
        with self.assertRaisesRegex(remote.RemoteBrokerError, "bounded array"):
            self._broker(task=task)

    def test_transport_executable_cannot_come_from_repository(self) -> None:
        fake_ssh = self.root / "ssh.exe"
        fake_ssh.write_bytes(b"not a system tool")
        with mock.patch.object(
            remote, "_trusted_executable_candidates", return_value=(fake_ssh,)
        ):
            with self.assertRaisesRegex(remote.RemoteBrokerError, "unavailable"):
                self.original_trusted_system_executable("ssh", self.root)

    def test_repository_factory_ignores_path_and_rejects_binary_overrides(self) -> None:
        root, _task, _state = self._sealed_repository()
        hijack_dir = self.base / "path-hijack"
        hijack_dir.mkdir()
        hijack_ssh = hijack_dir / ("ssh.exe" if os.name == "nt" else "ssh")
        hijack_scp = hijack_dir / ("scp.exe" if os.name == "nt" else "scp")
        hijack_ssh.write_bytes(b"path hijack")
        hijack_scp.write_bytes(b"path hijack")
        with mock.patch.dict(os.environ, {"PATH": str(hijack_dir)}):
            broker = self._repository_broker(root)
        self.assertNotEqual(broker._ssh_executable, hijack_ssh)
        self.assertFalse(hasattr(broker, "_scp_executable"))

        with self.assertRaises(TypeError):
            remote.RemoteExecutionBroker.from_repository(
                "NUR-OPS-001",
                root,
                user_ssh_directory=self.ssh_dir,
                ssh_executable=hijack_ssh,
                scp_executable=hijack_scp,
                runner=self.runner,
            )

    def test_output_limit_is_a_failed_evidence_result(self) -> None:
        runner = RecordingTransport(
            remote.ProcessOutcome(
                exit_code=-9,
                stdout=b"x" * 32,
                stderr=b"",
                stdout_bytes=remote.HARD_MAX_OUTPUT_BYTES + 1,
                stderr_bytes=0,
                timed_out=False,
                output_limited=True,
                duration_ms=5,
            )
        )
        evidence = self._broker(runner=runner).execute("inventory_pwd")
        self.assertFalse(evidence["success"])
        self.assertEqual(evidence["failure_kind"], "output_limit")
        self.assertIn("OUTPUT TRUNCATED", evidence["stdout"])

    def test_real_local_runner_bounds_output_without_network(self) -> None:
        outcome = remote._run_bounded_process(
            (sys.executable, "-c", "import sys; sys.stdout.write('x' * 8192)"),
            10,
            1024,
        )
        self.assertTrue(outcome.output_limited)
        self.assertLessEqual(len(outcome.stdout), 1024)
        self.assertGreater(outcome.stdout_bytes, 1024)

    def test_real_harness_release_check_launches_with_isolated_environment(self) -> None:
        workspace = Path(__file__).resolve().parents[1]
        git_executable = self.real_git
        python_executable = remote._trusted_running_python(workspace)
        harness_path = workspace / "scripts" / "harness.py"
        remote_path = workspace / "scripts" / "harness_remote.py"
        harness_bytes = harness_path.read_bytes()
        remote_bytes = remote_path.read_bytes()
        with tempfile.TemporaryFile(mode="w+b") as verified_sources:
            verified_sources.write(len(remote_bytes).to_bytes(8, "big"))
            verified_sources.write(remote_bytes)
            verified_sources.write(len(harness_bytes).to_bytes(8, "big"))
            verified_sources.write(harness_bytes)
            verified_sources.seek(0)
            outcome = remote._run_bounded_process(
                (
                    str(python_executable),
                    "-X",
                    "utf8",
                    "-I",
                    "-S",
                    "-B",
                    "-c",
                    remote._RELEASE_CHECK_LAUNCHER,
                    str(harness_path),
                    str(remote_path),
                    "release-check",
                    "NUR-OPS-003",
                    "--json",
                ),
                180,
                remote.HARD_MAX_OUTPUT_BYTES,
                cwd=workspace,
                environment=remote._minimal_git_environment(
                    git_executable, workspace
                ),
                stdin_handle=verified_sources,
            )
        self.assertIsNone(outcome.launch_error)
        self.assertFalse(outcome.timed_out)
        self.assertFalse(outcome.output_limited)
        self.assertIn(outcome.exit_code, {0, 1})
        self.assertTrue(outcome.stdout, outcome.stderr.decode("utf-8", errors="replace"))
        payload = json.loads(outcome.stdout.decode("utf-8"))
        self.assertEqual(payload["name"], "release-check")
        self.assertEqual(payload["data"]["task_id"], "NUR-OPS-003")

    def test_verified_release_launcher_ignores_replaced_or_missing_sibling(self) -> None:
        workspace = Path(__file__).resolve().parents[1]
        harness_bytes = (workspace / "scripts/harness.py").read_bytes()
        remote_bytes = (workspace / "scripts/harness_remote.py").read_bytes()
        with tempfile.TemporaryDirectory(
            prefix="broker-verified-launcher-toctou-"
        ) as temporary_value:
            root = Path(temporary_value)
            scripts = root / "scripts"
            scripts.mkdir()
            harness_path = scripts / "harness.py"
            remote_path = scripts / "harness_remote.py"
            harness_path.write_bytes(harness_bytes)
            harness_dir = root / ".harness"
            harness_dir.mkdir()
            shutil.copy2(
                workspace / ".harness/harness.json",
                harness_dir / "harness.json",
            )
            for name in (
                "tasks",
                "runs",
                "reports",
                "state",
                "templates",
                "schemas",
                "baselines",
            ):
                (harness_dir / name).mkdir()
            marker = root / "malicious-sibling-executed.txt"
            fake_release = (
                '{"name":"release-check","ok":true,"errors":[],"data":'
                '{"task_id":"NUR-OPS-999"}}'
            )
            malicious_source = (
                f"open({str(marker)!r}, 'w', encoding='utf-8').write('executed')\n"
                f"print({fake_release!r})\n"
                "raise SystemExit(0)\n"
            )

            framed_sources = (
                len(remote_bytes).to_bytes(8, "big")
                + remote_bytes
                + len(harness_bytes).to_bytes(8, "big")
                + harness_bytes
            )

            def launch() -> subprocess.CompletedProcess[bytes]:
                return subprocess.run(
                    [
                        sys.executable,
                        "-X",
                        "utf8",
                        "-I",
                        "-S",
                        "-B",
                        "-c",
                        remote._RELEASE_CHECK_LAUNCHER,
                        str(harness_path),
                        str(remote_path),
                        "release-check",
                        "NUR-OPS-999",
                        "--json",
                    ],
                    cwd=root,
                    input=framed_sources,
                    capture_output=True,
                    check=False,
                )

            remote_path.write_text(malicious_source, encoding="utf-8")
            replaced = launch()
            self.assertEqual(replaced.returncode, 1, replaced.stderr)
            self.assertFalse(marker.exists())
            replaced_payload = json.loads(replaced.stdout.decode("utf-8"))
            self.assertEqual(replaced_payload["name"], "release-check")
            self.assertFalse(replaced_payload["ok"])
            self.assertIn("task.json", " ".join(replaced_payload["errors"]))

            remote_path.unlink()
            missing = launch()
            self.assertEqual(missing.returncode, 1, missing.stderr)
            self.assertFalse(marker.exists())
            missing_payload = json.loads(missing.stdout.decode("utf-8"))
            self.assertEqual(missing_payload["name"], "release-check")
            self.assertFalse(missing_payload["ok"])

    def test_module_has_no_operational_cli(self) -> None:
        self.assertEqual(remote.main(), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

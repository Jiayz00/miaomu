#!/usr/bin/env python3
"""Regression tests for the project-local ShopXO nursery Harness core."""

from __future__ import annotations

import copy
import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import harness as harness_module


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


class HarnessCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="nursery-harness-selftest-")
        self.root = Path(self.temporary.name)
        shutil.copytree(PROJECT_ROOT / ".harness", self.root / ".harness")
        shutil.copy2(
            PROJECT_ROOT / "ShopXO苗木平台需求规格说明书_V1.0.md",
            self.root / "ShopXO苗木平台需求规格说明书_V1.0.md",
        )
        for rel in (".harness/tasks", ".harness/runs", ".harness/reports", ".harness/state"):
            directory = self.root / rel
            for child in list(directory.iterdir()):
                if child.name == ".gitignore":
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        self.harness = harness_module.Harness(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def task_value(self, task_id: str, *, status: str = "draft") -> dict[str, object]:
        task = json.loads(
            (self.root / ".harness/templates/task.json").read_text(encoding="utf-8")
        )
        task.update(
            {
                "id": task_id,
                "title": "Harness self-test task",
                "risk_level": "L4",
                "status": status,
                "requirement_ids": ["AC-001"],
                "business_goal": "验证项目 Harness 的状态、审批、事务与并发不变量。",
                "in_scope": ["仅测试 Harness 临时副本。"],
                "out_of_scope": ["不修改业务源码或外部环境。"],
                "business_invariants": ["非法状态、半提交和并发竞态必须被阻止。"],
                "allowed_paths": ["sandbox.txt"],
                "owner": "Owner",
                "reviewer": "Reviewer",
                "release_approver": "Release Approver",
            }
        )
        task["acceptance_criteria"] = [
            {
                "id": "AC-TASK-001",
                "requirement_ids": ["AC-001"],
                "description": "Harness 不变量可确定性验证。",
            }
        ]
        task["required_tests"] = [
            {
                "id": "harness_selftest",
                "description": "运行项目 Harness 自测。",
                "command": ["python", "scripts/harness_selftest.py"],
                "cwd": ".",
                "timeout_seconds": 120,
            }
        ]
        task["rollback"] = {
            "required": True,
            "plan": "删除临时测试目录。",
            "verification": "确认临时测试目录已清理。",
        }
        task["manual_approvals"] = {
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
        }
        return task

    def write_task(self, task_id: str, task: dict[str, object]) -> Path:
        directory = self.root / ".harness/tasks" / task_id
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "task.json"
        path.write_text(json_text(task), encoding="utf-8")
        return path

    def write_history(self, task_id: str, events: list[dict[str, object]]) -> Path:
        path = self.root / ".harness/tasks" / task_id / "workflow-history.json"
        path.write_text(
            json_text({"schema_version": 1, "task_id": task_id, "events": events}),
            encoding="utf-8",
        )
        return path

    def write_valid_plan_artifacts(self, task_id: str) -> None:
        directory = self.root / ".harness/tasks" / task_id
        repeated = (
            "本段记录可验证事实、明确边界、实际文件路径、失败处理、回滚步骤与责任人，"
            "不把未知事项表述为已确认结论。"
        ) * 12
        documents = {
            "requirement.md": [
                f"# {task_id} 需求摘录",
                "## 关联需求",
                "- AC-001",
                "## 任务路由",
                "- PRIORITY: P0",
                "- PHASE: 0",
                "## 业务目标",
                repeated,
                "## 明确不做",
                repeated,
                "## 开放决策",
                "- 无开放决策。",
            ],
            "impact-analysis.md": [
                f"# {task_id} 影响分析",
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
                f"# {task_id} 实施计划",
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
                f"# {task_id} 测试计划",
                "## 自动测试",
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
            (directory / name).write_text("\n\n".join(lines) + "\n", encoding="utf-8")

    def enable_codex_bindings(
        self,
        task: dict[str, object],
        *,
        implementation_thread: str = "11111111-1111-4111-8111-111111111111",
    ) -> None:
        task["codex_role_bindings"] = {
            "implementation": {
                "agent_task": "/root",
                "thread_id": implementation_thread,
            },
            "plan": {"agent_task": "/root/plan_review"},
            "merge": {"agent_task": "/root/merge_review"},
            "release": {"agent_task": "/root/release_review"},
        }

    def write_approval_artifact(
        self,
        task_id: str,
        task: dict[str, object],
        *,
        stage: str,
        status: str,
        actor: str,
        agent_task: str,
        thread_id: str,
        findings: list[str] | None = None,
    ) -> Path:
        context = self.harness.approval_context(task_id, task, stage)
        path = self.root / ".harness/tasks" / task_id / f"approval-{stage}.json"
        path.write_text(
            json_text(
                {
                    "schema_version": 1,
                    "task_id": task_id,
                    "stage": stage,
                    "decision": status,
                    "actor": actor,
                    "agent_task": agent_task,
                    "codex_thread_id": thread_id,
                    "result_marker": (
                        "APPROVED" if status == "approved" else "REJECTED"
                    ),
                    "approval_context_sha256": harness_module.canonical_json_hash(
                        context
                    ),
                    "reviewed_at": "2026-07-12T00:00:02Z",
                    "findings": findings or [],
                    "summary": "独立代理已复核当前阶段的合同、证据与阻断项。",
                }
            ),
            encoding="utf-8",
        )
        return path

    def approve_bound_stage(
        self,
        task_id: str,
        *,
        stage: str,
        actor: str,
        status: str = "approved",
        reason: str = "independent review",
        thread_id: str | None = None,
    ) -> harness_module.GateResult:
        task = self.harness.load_task(task_id)
        bindings = task.get("codex_role_bindings")
        assert isinstance(bindings, dict)
        binding = bindings.get(stage)
        assert isinstance(binding, dict)
        agent_task = str(binding["agent_task"])
        if thread_id is None:
            thread_id = {
                "plan": "33333333-3333-4333-8333-333333333333",
                "merge": "44444444-4444-4444-8444-444444444444",
                "release": "55555555-5555-4555-8555-555555555555",
            }[stage]
        self.write_approval_artifact(
            task_id,
            task,
            stage=stage,
            status=status,
            actor=actor,
            agent_task=agent_task,
            thread_id=thread_id,
            findings=["审批拒绝的具体阻断项。"] if status == "rejected" else None,
        )
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": thread_id}):
            return self.harness.task_approval(
                task_id,
                stage=stage,
                status=status,
                actor=actor,
                reason=reason,
                agent_task=agent_task,
            )

    def write_plan_approved_task(self, task_id: str) -> dict[str, object]:
        task = self.task_value(task_id, status="approved_for_implementation")
        self.write_task(task_id, task)
        self.write_valid_plan_artifacts(task_id)
        approved_at = "2026-07-12T00:00:02Z"
        approvals = task["manual_approvals"]
        assert isinstance(approvals, dict)
        plan = approvals["plan"]
        assert isinstance(plan, dict)
        plan["status"] = "approved"
        plan["approved_by"] = "Reviewer"
        plan["approved_at"] = approved_at
        (self.root / ".harness/tasks" / task_id / "task.json").write_text(
            json_text(task), encoding="utf-8"
        )
        plan_hash = self.harness.plan_artifacts_sha256(task_id)
        decision_hash = self.harness.decision_context_sha256(task)
        contract_hash = harness_module.plan_review_contract_hash(task)
        policy_hash = harness_module.plan_review_policy_hash(task)
        self.write_history(
            task_id,
            [
                {
                    "type": "transition",
                    "from": "draft",
                    "to": "ready_for_analysis",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:00Z",
                },
                {
                    "type": "transition",
                    "from": "ready_for_analysis",
                    "to": "awaiting_plan_approval",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:01Z",
                },
                {
                    "type": "approval",
                    "stage": "plan",
                    "status": "approved",
                    "by": "Reviewer",
                    "reason": "",
                    "at": approved_at,
                    "plan_artifacts_sha256": plan_hash,
                    "decision_context_sha256": decision_hash,
                    "contract_sha256": contract_hash,
                    "policy_sha256": policy_hash,
                },
                {
                    "type": "transition",
                    "from": "awaiting_plan_approval",
                    "to": "approved_for_implementation",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:03Z",
                },
            ],
        )
        return task

    def test_safe_transition_graph_cannot_be_relaxed(self) -> None:
        self.harness.config["workflow"]["status_transitions"]["closed"] = ["draft"]
        with self.assertRaisesRegex(harness_module.HarnessError, "status_transitions.closed"):
            self.harness.status_transitions()

    def test_project_path_policy_lists_cannot_be_broadened(self) -> None:
        self.harness.config["paths"]["bootstrap_allowed"].append("app/**")
        self.harness.config["paths"]["task_runtime_allowed"].append(
            ".harness/harness.json"
        )
        self.harness.config["execution"]["max_test_timeout_seconds"] = 10**9
        self.harness.config["execution"]["max_captured_output_bytes"] = 10**12
        gate = self.harness.project_check()
        self.assertFalse(gate.ok)
        self.assertTrue(any("bootstrap_allowed" in item for item in gate.errors))
        self.assertTrue(any("task_runtime_allowed" in item for item in gate.errors))
        self.assertTrue(any("max_test_timeout_seconds" in item for item in gate.errors))
        self.assertTrue(any("max_captured_output_bytes" in item for item in gate.errors))

    def test_remote_execution_requires_explicit_l4_operations_contract(self) -> None:
        task = self.task_value("NUR-OPS-990")
        task["type"] = "operations"
        task["network_access_required"] = True
        missing = self.harness.remote_execution_contract_errors(task)
        self.assertTrue(any("remote_execution" in item for item in missing))

        task["remote_execution"] = {
            "authorization": {
                "mode": "user_explicit",
                "thread_id": "019f566b-dffa-7913-a608-bc2dffbd2bea",
                "authorized_at": "2026-07-13T00:00:00+08:00",
                "scope": "Authorize the contracted personal-site deployment only.",
            },
            "environment": "authorized_personal_site",
            "host": "38.12.21.18",
            "port": 22,
            "user": "root",
            "host_key_fingerprint": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "identity_reference": "user-ssh-file:Jia-8u8g",
            "known_hosts_reference": "user-ssh-file:known_hosts",
            "deployment_root": "/root/jia/miaomu",
            "managed_roots": ["/root/jia/miaomu", "/root/jia/caddy"],
            "allowed_actions": [
                {
                    "id": "read_inventory",
                    "transport": "ssh",
                    "mode": "read_only",
                    "cwd": "/root/jia/miaomu",
                    "argv": ["docker", "version"],
                    "timeout_seconds": 60,
                }
            ],
            "forbidden_actions": sorted(harness_module.REMOTE_FORBIDDEN_ACTIONS),
        }
        self.assertEqual(self.harness.remote_execution_contract_errors(task), [])

        hook = runpy.run_path(str(PROJECT_ROOT / ".codex/hooks/harness_guard.py"))
        self.assertEqual(
            set(harness_module.HARNESS_POLICY_PATTERNS),
            set(hook["BOOTSTRAP_PATTERNS"]),
        )
        self.assertEqual(
            harness_module.policy_contract_hash(task),
            hook["canonical_json_hash"](hook["policy_contract"](task)),
        )

        task["remote_execution"]["deployment_root"] = "/"
        self.assertTrue(self.harness.remote_execution_contract_errors(task))
        task["remote_execution"]["deployment_root"] = "/root/jia/miaomu"
        task["remote_execution"]["identity_reference"] = "external:actual-secret"
        self.assertTrue(self.harness.remote_execution_contract_errors(task))
        task["remote_execution"]["identity_reference"] = "user-ssh-file:Jia-8u8g"

        task["type"] = "feature"
        self.assertTrue(self.harness.remote_execution_contract_errors(task))
        task["type"] = "operations"
        task["network_access_required"] = False
        self.assertTrue(self.harness.remote_execution_contract_errors(task))

    def test_remote_cli_uses_repository_factory_and_seals_upload_artifacts(self) -> None:
        task_id = "NUR-OPS-989"
        task = self.task_value(task_id, status="approved_for_merge")
        task["type"] = "operations"
        task["network_access_required"] = True
        ok_gate = harness_module.GateResult("stub")
        upload_facts = [
            {
                "action_id": "upload_release",
                "repo_path": ".harness/runs/NUR-OPS-989/release.tar",
                "size": 17,
                "sha256": "a" * 64,
            }
        ]
        state = {"schema_version": 1, "task_id": task_id}
        release_head = "b" * 40

        with (
            mock.patch.object(self.harness, "release_check", return_value=ok_gate),
            mock.patch.object(self.harness, "load_task", return_value=task),
            mock.patch.object(self.harness, "repository_dirty_paths", return_value=[]),
            mock.patch.object(self.harness, "head", return_value=release_head),
            mock.patch.object(self.harness, "read_active_state", return_value=state),
            mock.patch.object(
                harness_module.RemoteExecutionBroker,
                "release_upload_artifact_facts",
                return_value=upload_facts,
            ) as artifact_facts,
        ):
            seal = self.harness._release_seal_locked(task_id)

        self.assertTrue(seal.ok, seal.errors)
        artifact_facts.assert_called_once_with(task_id)
        sealed_state = json.loads(self.harness.state_file.read_text(encoding="utf-8"))
        self.assertEqual(sealed_state["release_commit"], release_head)
        self.assertEqual(sealed_state["release_upload_artifacts"], upload_facts)

        broker = mock.Mock()
        broker.action_ids.side_effect = lambda *, mode: (
            ("read_inventory",) if mode == "read_only" else ("upload_release",)
        )
        broker.execute.return_value = {
            "success": True,
            "action_sha256": "c" * 64,
            "failure_kind": None,
        }
        with (
            mock.patch.object(self.harness, "task_check", return_value=ok_gate),
            mock.patch.object(self.harness, "load_task", return_value=task),
            mock.patch.object(self.harness, "validate_active_state", return_value=ok_gate),
            mock.patch.object(
                harness_module.RemoteExecutionBroker,
                "from_repository",
                return_value=broker,
            ) as repository_factory,
        ):
            actions = self.harness.remote_actions(task_id)
            execution = self.harness._remote_execute_locked(
                task_id,
                action_id="read_inventory",
                allow_mutating=False,
            )

        self.assertTrue(actions.ok, actions.errors)
        self.assertTrue(execution.ok, execution.errors)
        self.assertEqual(actions.data["read_only_actions"], ["read_inventory"])
        self.assertEqual(actions.data["mutating_actions"], ["upload_release"])
        self.assertEqual(
            repository_factory.call_args_list,
            [mock.call(task_id), mock.call(task_id)],
        )
        broker.execute.assert_called_once_with("read_inventory", allow_mutating=False)

    def test_sensitive_cli_requires_isolated_flags_before_shadowable_imports(self) -> None:
        repo = self.root / "isolated-cli"
        scripts = repo / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy2(PROJECT_ROOT / "scripts/harness.py", scripts / "harness.py")
        shutil.copy2(
            PROJECT_ROOT / "scripts/harness_remote.py",
            scripts / "harness_remote.py",
        )
        harness_dir = repo / ".harness"
        harness_dir.mkdir()
        shutil.copy2(
            PROJECT_ROOT / ".harness/harness.json",
            harness_dir / "harness.json",
        )
        for rel in (
            "tasks",
            "runs",
            "reports",
            "state",
            "templates",
            "schemas",
            "baselines",
        ):
            (harness_dir / rel).mkdir()
        marker = repo / "json-shadow-executed.txt"
        (scripts / "json.py").write_text(
            f"open({str(marker)!r}, 'w', encoding='utf-8').write('executed')\n"
            "raise SystemExit(91)\n",
            encoding="utf-8",
        )

        def launch(*flags: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    *flags,
                    os.fspath(scripts / "harness.py"),
                    "remote-actions",
                    "NUR-OPS-999",
                    "--json",
                ],
                cwd=repo,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

        for flags in ((), ("-I", "-S"), ("-I", "-B"), ("-S", "-B")):
            marker.unlink(missing_ok=True)
            rejected = launch(*flags)
            self.assertEqual(rejected.returncode, 2, (flags, rejected.stderr))
            self.assertIn("-I -S -B", rejected.stderr)
            self.assertFalse(marker.exists(), flags)

        isolated = launch("-I", "-S", "-B")
        self.assertEqual(isolated.returncode, 1, isolated.stderr)
        self.assertIn('"name": "remote-actions"', isolated.stdout)
        self.assertIn("task.json", isolated.stdout)
        self.assertFalse(marker.exists())

    def test_required_source_and_project_files_reject_link_like_paths(self) -> None:
        (self.root / "composer.json").write_text("{}\n", encoding="utf-8")
        (self.root / "app").mkdir()
        with mock.patch.object(
            harness_module,
            "path_is_link_like",
            side_effect=lambda path: path.name in {"composer.json", "app"},
        ):
            source = self.harness.source_status()
        blocked = {item["path"] for item in source if item["status"] == "blocked"}
        self.assertIn("composer.json", blocked)
        self.assertIn("app", blocked)

        required = self.root / "AGENTS.md"
        required.write_text("# selftest\n", encoding="utf-8")
        self.harness.config["project_check"]["required_files"] = ["AGENTS.md"]
        with mock.patch.object(
            harness_module,
            "path_is_link_like",
            side_effect=lambda path: path.name == "AGENTS.md",
        ):
            gate = self.harness.project_check()
        self.assertFalse(gate.ok)
        self.assertTrue(
            any("必需文件路径不安全 AGENTS.md" in item for item in gate.errors)
        )

        executable = self.root / "scripts/check.py"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("print('ok')\n", encoding="utf-8")
        with mock.patch.object(
            harness_module,
            "path_is_link_like",
            side_effect=lambda path: path == executable,
        ):
            self.assertIsNone(
                self.harness.executable_for_test("scripts/check.py", self.root)
            )

    def test_read_only_mcp_rejects_link_like_requirement_paths(self) -> None:
        mcp = runpy.run_path(str(PROJECT_ROOT / ".harness/mcp/server.py"))
        requirement_path = self.root / "requirements.md"
        requirement_path.write_text("# AC-001\n\nselftest\n", encoding="utf-8")
        globals_value = mcp["requirement_lines"].__globals__
        globals_value["ROOT"] = self.root
        globals_value["REQUIREMENTS_FILE"] = requirement_path
        globals_value["path_is_link_like"] = lambda path: path == requirement_path
        with self.assertRaisesRegex(ValueError, "symlink/junction"):
            mcp["requirement_lines"]()

    def test_github_workflow_yaml_parses_when_pyyaml_is_available(self) -> None:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError:
            self.skipTest("PyYAML is optional; GitHub parses workflow YAML in CI")
        workflow = yaml.safe_load(
            (PROJECT_ROOT / ".github/workflows/harness.yml").read_text(
                encoding="utf-8"
            )
        )
        self.assertIsInstance(workflow, dict)
        self.assertEqual(workflow.get("name"), "nursery-harness")
        self.assertIn("harness", workflow.get("jobs", {}))

    def test_non_json_gate_output_emits_stable_verification_contract(self) -> None:
        gate = harness_module.GateResult("verify")
        gate.data["verification_contract_sha256"] = "a" * 64
        gate.data["summary"] = "selftest"
        with mock.patch("builtins.print") as printer:
            exit_code = harness_module.print_gate(gate, json_output=False)
        rendered = "\n".join(
            " ".join(str(item) for item in call.args)
            for call in printer.call_args_list
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("VERIFY_CONTRACT_SHA256: " + "a" * 64, rendered)

    def test_history_requires_approval_events_before_approved_states(self) -> None:
        task_id = "NUR-FEAT-990"
        task = self.task_value(task_id, status="approved_for_implementation")
        self.write_task(task_id, task)
        self.write_history(
            task_id,
            [
                {
                    "type": "transition",
                    "from": "draft",
                    "to": "ready_for_analysis",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:00Z",
                },
                {
                    "type": "transition",
                    "from": "ready_for_analysis",
                    "to": "awaiting_plan_approval",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:01Z",
                },
                {
                    "type": "transition",
                    "from": "awaiting_plan_approval",
                    "to": "approved_for_implementation",
                    "by": "Reviewer",
                    "reason": "",
                    "at": "2026-07-12T00:00:02Z",
                },
            ],
        )
        gate = self.harness.workflow_history_check(task_id, task)
        self.assertFalse(gate.ok)
        self.assertTrue(any("approved_for_implementation" in item for item in gate.errors))

    def test_transaction_rolls_back_interrupt_and_recovers_partial_write(self) -> None:
        task_id = "NUR-FEAT-989"
        task = self.task_value(task_id)
        task_path = self.write_task(task_id, task)
        original_task = task_path.read_text(encoding="utf-8")
        new_task = copy.deepcopy(task)
        new_task["status"] = "ready_for_analysis"
        event = {
            "type": "transition",
            "from": "draft",
            "to": "ready_for_analysis",
            "by": "Owner",
            "reason": "",
            "at": "2026-07-12T00:00:00Z",
        }
        original_write_json = harness_module.write_json
        calls = 0

        def interrupting_write(path: Path, value: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise KeyboardInterrupt
            original_write_json(path, value)

        with mock.patch.object(harness_module, "write_json", side_effect=interrupting_write):
            with self.assertRaises(KeyboardInterrupt):
                self.harness.write_task_workflow_update(task_id, new_task, event)
        history_path = task_path.parent / "workflow-history.json"
        self.assertEqual(task_path.read_text(encoding="utf-8"), original_task)
        self.assertFalse(history_path.exists())

        new_history = {"schema_version": 1, "task_id": task_id, "events": [event]}
        journal_path = self.harness.workflow_transaction_path(task_id)
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path.write_text(
            json_text(
                {
                    "schema_version": 1,
                    "task_id": task_id,
                    "prepared_at": "2026-07-12T00:00:00Z",
                    "original_task": original_task,
                    "original_history": None,
                    "new_task": new_task,
                    "new_history": new_history,
                }
            ),
            encoding="utf-8",
        )
        history_path.write_text(json_text(new_history), encoding="utf-8")
        recovered = self.harness.load_task(task_id)
        self.assertEqual(recovered["status"], "draft")
        self.assertFalse(history_path.exists())
        self.assertFalse(journal_path.exists())

    def test_concurrent_transitions_are_serialized(self) -> None:
        task_id = "NUR-FEAT-988"
        task = self.task_value(task_id)
        self.write_task(task_id, task)
        barrier = threading.Barrier(2)

        def transition() -> harness_module.GateResult:
            barrier.wait()
            return self.harness.task_transition(
                task_id,
                target_status="ready_for_analysis",
                actor="Owner",
                reason="",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [future.result() for future in (executor.submit(transition), executor.submit(transition))]
        self.assertEqual(sum(result.ok for result in results), 1)
        final_task = self.harness.load_task(task_id)
        self.assertTrue(self.harness.workflow_history_check(task_id, final_task).ok)
        lock_dir = self.root / ".harness/state/workflow-locks"
        self.assertFalse(list(lock_dir.glob("*.lock")))

    def test_cross_task_preflights_share_one_global_active_state_lock(self) -> None:
        barrier = threading.Barrier(2)
        original_resolve = Path.resolve

        def transient_windows_resolve(path: Path, strict: bool = False) -> Path:
            # Model the Windows strict=False race that motivated this test:
            # two tasks resolve lock children while their shared parent is
            # first being created.  Safe-path checks must not depend on the
            # non-strict resolution of a missing lock child.
            if (
                not strict
                and path.suffix == ".lock"
                and "workflow-locks" in path.parts
                and not path.exists()
            ):
                return self.root.parent / "simulated-transient-outside.lock"
            return original_resolve(path, strict=strict)

        def fake_preflight(task_id: str) -> harness_module.GateResult:
            result = harness_module.GateResult("preflight")
            if self.harness.state_file.exists():
                result.errors.append("active state already exists")
                return result
            threading.Event().wait(0.1)
            harness_module.write_json(
                self.harness.state_file,
                {"schema_version": 1, "task_id": task_id},
            )
            return result

        def invoke(task_id: str) -> harness_module.GateResult:
            barrier.wait()
            return self.harness.preflight(task_id)

        with (
            mock.patch.object(Path, "resolve", transient_windows_resolve),
            mock.patch.object(
                self.harness, "_preflight_locked", side_effect=fake_preflight
            ),
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = [
                    future.result()
                    for future in (
                        executor.submit(invoke, "NUR-FEAT-971"),
                        executor.submit(invoke, "NUR-FEAT-970"),
                    )
                ]
        self.assertEqual(sum(result.ok for result in results), 1)
        self.assertTrue(self.harness.state_file.is_file())
        self.harness.state_file.unlink()
        self.assertFalse(self.harness.active_state_lock_path().exists())

    def test_workflow_lock_path_safety_failure_is_structured(self) -> None:
        with mock.patch.object(
            harness_module,
            "ensure_repo_path_safe",
            side_effect=harness_module.HarnessError("simulated unsafe lock path"),
        ):
            result = self.harness.preflight("NUR-FEAT-969")
        self.assertFalse(result.ok)
        self.assertTrue(
            any("无法取得任务工作流锁" in error for error in result.errors),
            result.errors,
        )

    def test_stale_invalid_global_active_state_lock_is_recovered(self) -> None:
        lock_path = self.harness.active_state_lock_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("not-json\n", encoding="utf-8")
        stale_time = time.time() - harness_module.WORKFLOW_LOCK_STALE_SECONDS - 10
        os.utime(lock_path, (stale_time, stale_time))
        with self.harness.active_state_lock():
            owner = harness_module.read_json(lock_path)
            self.assertEqual(owner.get("name"), "active-state")
            self.assertEqual(owner.get("pid"), os.getpid())
        self.assertFalse(lock_path.exists())

    def test_stale_lock_reclamation_remains_mutually_exclusive(self) -> None:
        def probe(lock_path: Path, acquire) -> None:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text("not-json\n", encoding="utf-8")
            stale = time.time() - harness_module.WORKFLOW_LOCK_STALE_SECONDS - 10
            os.utime(lock_path, (stale, stale))

            original_unlink = Path.unlink
            both_at_delete = threading.Barrier(2)
            first_entered = threading.Event()
            second_entered = threading.Event()
            state_lock = threading.Lock()
            state = {"unlink_calls": 0, "active": 0, "max_active": 0}

            def controlled_unlink(path: Path, *args: object, **kwargs: object) -> None:
                if path == lock_path:
                    with state_lock:
                        state["unlink_calls"] += 1
                        call = state["unlink_calls"]
                    if call <= 2:
                        try:
                            both_at_delete.wait(timeout=0.3)
                        except threading.BrokenBarrierError:
                            # The OS advisory guard intentionally prevents the
                            # second stale classifier from reaching this point.
                            pass
                        if call == 2:
                            first_entered.wait(timeout=2)
                original_unlink(path, *args, **kwargs)

            def contender() -> None:
                with acquire():
                    with state_lock:
                        state["active"] += 1
                        state["max_active"] = max(
                            state["max_active"], state["active"]
                        )
                        position = state["active"]
                    if position == 1:
                        first_entered.set()
                        second_entered.wait(timeout=0.5)
                    else:
                        second_entered.set()
                    with state_lock:
                        state["active"] -= 1

            with mock.patch.object(Path, "unlink", controlled_unlink):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [executor.submit(contender) for _ in range(2)]
                    for future in futures:
                        future.result(timeout=10)
            self.assertEqual(state["max_active"], 1, state)

        probe(self.harness.active_state_lock_path(), self.harness.active_state_lock)
        probe(
            self.harness.workflow_lock_path("NUR-HARNESS-999"),
            lambda: self.harness.workflow_lock("NUR-HARNESS-999"),
        )

    @unittest.skipIf(os.name == "nt", "POSIX guard replacement regression")
    def test_posix_guard_path_replacement_cannot_split_the_lock(self) -> None:
        guard_path = self.root / ".harness/state/.replacement.guard"
        guard_path.write_text("guard\n", encoding="utf-8")
        anchor = self.root / ".harness/state"
        first_entered = threading.Event()
        allow_first_exit = threading.Event()
        second_entered = threading.Event()

        def contender_one() -> None:
            with harness_module.advisory_lock_guard(
                self.root,
                guard_path,
                deadline=time.monotonic() + 5,
                label="replacement regression",
                anchor=anchor,
            ):
                first_entered.set()
                allow_first_exit.wait(timeout=5)

        def contender_two() -> None:
            with harness_module.advisory_lock_guard(
                self.root,
                guard_path,
                deadline=time.monotonic() + 5,
                label="replacement regression",
                anchor=anchor,
            ):
                second_entered.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(contender_one)
            self.assertTrue(first_entered.wait(timeout=5))
            guard_path.unlink()
            guard_path.write_text("replacement\n", encoding="utf-8")
            second = executor.submit(contender_two)
            self.assertFalse(second_entered.wait(timeout=0.3))
            allow_first_exit.set()
            first.result(timeout=5)
            second.result(timeout=5)
        self.assertTrue(second_entered.is_set())

    def test_lock_release_failure_is_reported(self) -> None:
        def probe(lock_path: Path, acquire) -> None:
            original_unlink = Path.unlink

            def fail_owned_lock_unlink(
                path: Path, *args: object, **kwargs: object
            ) -> None:
                if path == lock_path:
                    raise PermissionError("simulated release denial")
                original_unlink(path, *args, **kwargs)

            with mock.patch.object(Path, "unlink", fail_owned_lock_unlink):
                with self.assertRaisesRegex(
                    harness_module.WorkflowLockError,
                    "无法释放",
                ):
                    with acquire():
                        pass
            self.assertTrue(lock_path.is_file())
            lock_path.unlink()

        probe(self.harness.active_state_lock_path(), self.harness.active_state_lock)
        probe(
            self.harness.workflow_lock_path("NUR-HARNESS-998"),
            lambda: self.harness.workflow_lock("NUR-HARNESS-998"),
        )

    def test_lock_creation_cleanup_does_not_mask_primary_failure(self) -> None:
        def probe(lock_path: Path, acquire) -> None:
            guard_path = lock_path.with_name(f".{lock_path.name}.guard")
            guard_path.parent.mkdir(parents=True, exist_ok=True)
            guard_path.write_bytes(b"\x00")
            original_unlink = Path.unlink

            def deny_cleanup(
                path: Path, *args: object, **kwargs: object
            ) -> None:
                if path == lock_path:
                    raise PermissionError("simulated cleanup denial")
                original_unlink(path, *args, **kwargs)

            with (
                mock.patch.object(
                    harness_module.os,
                    "fsync",
                    side_effect=OSError("primary fsync failure"),
                ),
                mock.patch.object(Path, "unlink", deny_cleanup),
            ):
                with self.assertRaisesRegex(OSError, "primary fsync failure") as raised:
                    with acquire():
                        pass
            self.assertTrue(
                any("cleanup denial" in note for note in getattr(raised.exception, "__notes__", [])),
                getattr(raised.exception, "__notes__", []),
            )
            self.assertTrue(lock_path.is_file())
            lock_path.unlink()

        probe(self.harness.active_state_lock_path(), self.harness.active_state_lock)
        probe(
            self.harness.workflow_lock_path("NUR-HARNESS-997"),
            lambda: self.harness.workflow_lock("NUR-HARNESS-997"),
        )

    def test_reused_pid_owner_is_recovered_by_process_instance(self) -> None:
        def probe(lock_path: Path, acquire) -> None:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text(
                json_text(
                    {
                        "schema_version": 1,
                        "token": "stale-token",
                        "pid": os.getpid(),
                        "process_instance": "old-process-instance",
                        "acquired_at": "2026-01-01T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    harness_module,
                    "process_is_alive",
                    return_value=True,
                ),
                mock.patch.object(
                    harness_module,
                    "process_instance_id",
                    return_value="new-process-instance",
                ),
            ):
                with acquire():
                    current = harness_module.read_json(lock_path)
                    self.assertEqual(
                        current.get("process_instance"),
                        "new-process-instance",
                    )
            self.assertFalse(lock_path.exists())

        probe(self.harness.active_state_lock_path(), self.harness.active_state_lock)
        probe(
            self.harness.workflow_lock_path("NUR-HARNESS-996"),
            lambda: self.harness.workflow_lock("NUR-HARNESS-996"),
        )

    def test_python311_windows_reparse_fallback_is_fail_closed(self) -> None:
        mcp = runpy.run_path(str(PROJECT_ROOT / ".harness/mcp/server.py"))
        hook = runpy.run_path(
            str(PROJECT_ROOT / ".codex/hooks/harness_guard.py")
        )
        candidate = Path("legacy-junction")
        info = mock.Mock(
            st_mode=harness_module.stat.S_IFDIR,
            st_file_attributes=getattr(
                harness_module.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
            ),
        )
        with (
            mock.patch.object(harness_module.os, "name", "nt"),
            mock.patch.object(harness_module.os, "lstat", return_value=info),
            mock.patch.object(Path, "is_junction", None, create=True),
        ):
            for check in (
                harness_module.path_is_link_like,
                mcp["path_is_link_like"],
                hook["path_is_link_like"],
            ):
                self.assertTrue(check(candidate), check)

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_junction_backed_repository_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="nursery-harness-junction-alias-"
        ) as alias_parent:
            alias = Path(alias_parent) / "repo-alias"
            created = subprocess.run(
                [
                    "cmd.exe",
                    "/d",
                    "/c",
                    "mklink",
                    "/J",
                    str(alias),
                    str(PROJECT_ROOT),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if created.returncode != 0:
                self.skipTest(f"junction creation unavailable: {created.stderr.strip()}")
            try:
                with mock.patch.object(Path, "is_junction", None, create=True):
                    self.assertTrue(harness_module.path_is_link_like(alias))
                    with self.assertRaisesRegex(
                        harness_module.HarnessError,
                        "仓库根目录.*symlink/junction",
                    ):
                        harness_module.Harness(alias)

                    mcp = runpy.run_path(
                        str(PROJECT_ROOT / ".harness/mcp/server.py")
                    )
                    mcp_globals = mcp["ensure_repo_path_safe"].__globals__
                    mcp_globals["ROOT"] = alias
                    with self.assertRaisesRegex(ValueError, "symlink/junction"):
                        mcp["ensure_repo_path_safe"](
                            alias,
                            label="repository root",
                        )

                    hook = runpy.run_path(
                        str(PROJECT_ROOT / ".codex/hooks/harness_guard.py")
                    )
                    hook_globals = hook["repository_root_safety_error"].__globals__
                    hook_globals["ROOT"] = alias
                    self.assertIn(
                        "目录联接",
                        hook["repository_root_safety_error"](),
                    )

                    cli = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(alias / "scripts/harness.py"),
                            "project-check",
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                    )
                    self.assertNotEqual(cli.returncode, 0)
                    self.assertIn("symlink/junction", cli.stdout + cli.stderr)

                    hook_process = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(alias / ".codex/hooks/harness_guard.py"),
                        ],
                        input=json.dumps({"hook_event_name": "SessionStart"}) + "\n",
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                    )
                    self.assertEqual(hook_process.returncode, 0, hook_process.stderr)
                    self.assertIn("已拒绝当前工作目录", hook_process.stdout)

                    mcp_process = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(alias / ".harness/mcp/server.py"),
                        ],
                        input=(
                            json.dumps(
                                {
                                    "jsonrpc": "2.0",
                                    "id": 1,
                                    "method": "initialize",
                                    "params": {
                                        "protocolVersion": "2025-06-18",
                                        "capabilities": {},
                                        "clientInfo": {
                                            "name": "junction-selftest",
                                            "version": "1",
                                        },
                                    },
                                }
                            )
                            + "\n"
                        ),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                    )
                    self.assertEqual(mcp_process.returncode, 0, mcp_process.stderr)
                    response = json.loads(mcp_process.stdout)
                    self.assertEqual(response["error"]["code"], -32000)
            finally:
                os.rmdir(alias)

    def test_state_recover_requires_safe_status_actor_reason_and_invalid_opt_in(self) -> None:
        task_id = "NUR-FEAT-968"
        task = self.task_value(task_id, status="closed")
        self.write_task(task_id, task)
        self.harness.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.harness.state_file.write_text("not-json\n", encoding="utf-8")

        rejected = self.harness.state_recover(
            task_id,
            actor="Owner",
            reason="清理已结束任务的损坏活动状态记录。",
            allow_invalid_state=False,
        )
        self.assertFalse(rejected.ok)
        self.assertTrue(self.harness.state_file.exists())
        self.assertTrue(any("--allow-invalid-state" in item for item in rejected.errors))

        recovered = self.harness.state_recover(
            task_id,
            actor="Owner",
            reason="清理已结束任务的损坏活动状态记录。",
            allow_invalid_state=True,
        )
        self.assertTrue(recovered.ok, recovered.errors)
        self.assertFalse(self.harness.state_file.exists())
        record = Path(str(recovered.data["recovery_record"]))
        if not record.is_absolute():
            record = self.root / record
        self.assertTrue(record.is_file())

        active_id = "NUR-FEAT-967"
        active_task = self.task_value(active_id, status="implementing")
        self.write_task(active_id, active_task)
        self.harness.state_file.write_text(
            json_text({"schema_version": 1, "task_id": active_id}),
            encoding="utf-8",
        )
        unsafe = self.harness.state_recover(
            active_id,
            actor="Owner",
            reason="尝试清理仍在实施状态的活动任务。",
            allow_invalid_state=False,
        )
        self.assertFalse(unsafe.ok)
        self.assertTrue(self.harness.state_file.exists())
        self.harness.state_file.unlink()

    def test_required_source_state_changes_repository_facts_hash(self) -> None:
        (self.root / "app").mkdir()
        (self.root / "config").mkdir()
        (self.root / "composer.json").write_text("{}\n", encoding="utf-8")
        (self.root / "config/shopxo.sql").write_text("CREATE TABLE e2e(id int);\n", encoding="utf-8")
        common = self.root / "app/common.php"
        common.write_text("<?php // self-test\n", encoding="utf-8")
        before = harness_module.canonical_json_hash(self.harness.repository_baseline_facts())
        common.unlink()
        after = harness_module.canonical_json_hash(self.harness.repository_baseline_facts())
        self.assertNotEqual(before, after)

    def test_slash_aware_globs_do_not_cross_path_segments(self) -> None:
        self.assertTrue(harness_module.path_matches("app/Foo.php", ["app/*.php"]))
        self.assertFalse(harness_module.path_matches("app/a/Foo.php", ["app/*.php"]))
        self.assertTrue(harness_module.path_matches("app/a/Foo.php", ["app/**"]))
        self.assertFalse(harness_module.path_matches("docs/ab/b.md", ["docs/?/*.md"]))

    def test_dependency_manifests_are_detected_at_any_depth(self) -> None:
        for path in (
            "composer.json",
            "app/plugins/nursery/composer.json",
            "frontend/package.json",
            "tools/requirements-dev.txt",
            "analytics/pyproject.toml",
            "analytics/uv.lock",
            "worker/go.mod",
        ):
            self.assertTrue(harness_module.is_dependency_manifest_path(path), path)
        self.assertFalse(harness_module.is_dependency_manifest_path("docs/package-notes.md"))

    def test_workspace_fingerprint_is_stable_for_control_only_git_commit(self) -> None:
        repo = self.root / "fingerprint-git"
        task_id = "NUR-FEAT-965"
        task_dir = repo / ".harness/tasks" / task_id
        task_dir.mkdir(parents=True)
        shutil.copy2(
            PROJECT_ROOT / ".harness/harness.json",
            repo / ".harness/harness.json",
        )
        sandbox = repo / "sandbox"
        sandbox.mkdir()
        (task_dir / "task.json").write_text(
            json_text({"status": "draft"}), encoding="utf-8"
        )
        (sandbox / "tracked.txt").write_text("baseline\n", encoding="utf-8")

        def git(*args: str) -> str:
            completed = subprocess.run(
                ["git", *args],
                cwd=repo,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"git {' '.join(args)} failed: {completed.stderr}",
            )
            return completed.stdout.strip()

        git("init", "--quiet")
        git("config", "user.name", "Harness Selftest")
        git("config", "user.email", "harness-selftest@example.invalid")
        git("add", ".harness/harness.json", f".harness/tasks/{task_id}/task.json", "sandbox/tracked.txt")
        git("commit", "--quiet", "-m", "baseline")
        base = git("rev-parse", "HEAD")
        harness = harness_module.Harness(repo)

        (task_dir / "task.json").write_text(
            json_text({"status": "awaiting_review"}), encoding="utf-8"
        )
        (task_dir / "workflow-history.json").write_text(
            json_text({"schema_version": 1, "task_id": task_id, "events": []}),
            encoding="utf-8",
        )
        (task_dir / "approval-merge.json").write_text(
            json_text({"result_marker": "APPROVED"}), encoding="utf-8"
        )
        business = sandbox / "new-business.txt"
        business.write_text("verified business content\n", encoding="utf-8")

        verified_fingerprint = harness.workspace_fingerprint(task_id, base)
        self.assertEqual(
            verified_fingerprint,
            harness.approval_workspace_fingerprint(task_id, base),
        )
        git(
            "add",
            f".harness/tasks/{task_id}/task.json",
            f".harness/tasks/{task_id}/workflow-history.json",
            f".harness/tasks/{task_id}/approval-merge.json",
        )
        git("commit", "--quiet", "-m", "record approval controls")
        after_control_commit = harness.workspace_fingerprint(task_id, base)
        self.assertEqual(verified_fingerprint, after_control_commit)

        git("add", "sandbox/new-business.txt")
        git("commit", "--quiet", "-m", "commit reviewed business file")
        after_business_commit = harness.workspace_fingerprint(task_id, base)
        self.assertNotEqual(after_control_commit, after_business_commit)

        business.write_text("modified business content\n", encoding="utf-8")
        after_business_edit = harness.workspace_fingerprint(task_id, base)
        self.assertNotEqual(after_business_commit, after_business_edit)

        git("mv", "sandbox/tracked.txt", "sandbox/renamed.txt")
        after_rename = harness.workspace_fingerprint(task_id, base)
        self.assertNotEqual(after_business_edit, after_rename)

        (sandbox / "renamed.txt").unlink()
        after_delete = harness.workspace_fingerprint(task_id, base)
        self.assertNotEqual(after_rename, after_delete)

    def test_symlinks_never_redirect_harness_reads_or_run_writes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nursery-harness-external-") as external_value:
            external = Path(external_value)
            secret = external / "secret.json"
            secret.write_text('{"token":"must-not-be-read"}\n', encoding="utf-8")
            link = self.root / "sandbox-link.json"
            try:
                link.symlink_to(secret)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            with self.assertRaisesRegex(harness_module.HarnessError, "符号链接 JSON"):
                harness_module.read_json(link)
            change = harness_module.GitChange(
                status="A", paths=("sandbox-link.json",), source="selftest"
            )
            scan = self.harness.scan_changed_files([change])
            self.assertTrue(
                any(
                    item["kind"] == "unsafe-path-or-symlink"
                    for item in scan["findings"]
                )
            )
            with mock.patch.object(self.harness, "head", return_value="a" * 40):
                fingerprint = self.harness.workspace_fingerprint(
                    "NUR-FEAT-975", "b" * 40, [change]
                )
            self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")

            external_runs = external / "runs"
            external_runs.mkdir()
            task_runs = self.root / ".harness/runs/NUR-FEAT-975"
            task_runs.symlink_to(external_runs, target_is_directory=True)
            with self.assertRaisesRegex(harness_module.HarnessError, "任务运行目录"):
                self.harness.create_run_directory("NUR-FEAT-975", "verify")

    def test_task_id_type_mapping_and_harness_policy_allowed_paths(self) -> None:
        task_id = "NUR-OPS-987"
        task = self.task_value(task_id)
        task["allowed_paths"] = [".harness/**", ".gitignore"]
        self.write_task(task_id, task)
        gate = self.harness.task_check(task_id)
        self.assertFalse(gate.ok)
        self.assertTrue(any("type=operations" in item for item in gate.errors))
        self.assertTrue(any("Harness 策略/执行面" in item for item in gate.errors))

        harness_task_id = "NUR-HARNESS-980"
        harness_task = self.task_value(harness_task_id)
        harness_task["type"] = "harness"
        harness_task["allowed_paths"] = ["app/**"]
        self.write_task(harness_task_id, harness_task)
        harness_gate = self.harness.task_check(harness_task_id)
        self.assertFalse(harness_gate.ok)
        self.assertTrue(any("bootstrap_allowed" in item for item in harness_gate.errors))

    def test_acceptance_requirements_cannot_escape_task_contract(self) -> None:
        task_id = "NUR-FEAT-986"
        task = self.task_value(task_id)
        task["acceptance_criteria"] = [
            {
                "id": "AC-TASK-001",
                "requirement_ids": ["AC-001", "FR-INQ-006", "FR-NOPE-999"],
                "description": "验证任务合同之外的需求编号会被拒绝。",
            }
        ]
        self.write_task(task_id, task)
        gate = self.harness.task_check(task_id)
        self.assertFalse(gate.ok)
        self.assertTrue(any("需求文档外编号" in item for item in gate.errors))
        self.assertTrue(any("requirement_ids 之外" in item for item in gate.errors))

    def test_plan_approval_hash_invalidates_after_document_change(self) -> None:
        task_id = "NUR-FEAT-985"
        task = self.task_value(task_id, status="awaiting_plan_approval")
        self.enable_codex_bindings(task)
        self.write_task(task_id, task)
        self.write_valid_plan_artifacts(task_id)
        self.write_history(
            task_id,
            [
                {
                    "type": "transition",
                    "from": "draft",
                    "to": "ready_for_analysis",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:00Z",
                },
                {
                    "type": "transition",
                    "from": "ready_for_analysis",
                    "to": "awaiting_plan_approval",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:01Z",
                },
            ],
        )
        approval = self.approve_bound_stage(
            task_id,
            stage="plan",
            actor="Reviewer",
            reason="",
        )
        self.assertTrue(approval.ok, approval.errors)
        plan_path = self.root / ".harness/tasks" / task_id / "test-plan.md"
        plan_path.write_text(
            plan_path.read_text(encoding="utf-8") + "\n批准后非法修改。\n",
            encoding="utf-8",
        )
        gate = self.harness.task_check(task_id)
        self.assertFalse(gate.ok)
        self.assertTrue(any("旧审批已失效" in item for item in gate.errors))
        reopened = self.harness.task_transition(
            task_id,
            target_status="ready_for_analysis",
            actor="Owner",
            reason="revise approved plan",
        )
        self.assertTrue(reopened.ok, reopened.errors)
        reopened_task = self.harness.load_task(task_id)
        self.assertEqual(
            reopened_task["manual_approvals"]["plan"]["status"], "pending"
        )

    def test_plan_approval_hash_invalidates_after_contract_change(self) -> None:
        task_id = "NUR-OPS-972"
        task = self.task_value(task_id, status="awaiting_plan_approval")
        task["type"] = "operations"
        self.enable_codex_bindings(task)
        self.write_task(task_id, task)
        self.write_valid_plan_artifacts(task_id)
        self.write_history(
            task_id,
            [
                {
                    "type": "transition",
                    "from": "draft",
                    "to": "ready_for_analysis",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:00Z",
                },
                {
                    "type": "transition",
                    "from": "ready_for_analysis",
                    "to": "awaiting_plan_approval",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:01Z",
                },
            ],
        )
        approved = self.approve_bound_stage(
            task_id,
            stage="plan",
            actor="Reviewer",
            reason="contract reviewed",
        )
        self.assertTrue(approved.ok, approved.errors)

        changed = self.harness.load_task(task_id)
        changed["allowed_paths"] = ["other/**"]
        (self.root / ".harness/tasks" / task_id / "task.json").write_text(
            json_text(changed), encoding="utf-8"
        )
        stale = self.harness.task_check(task_id)
        self.assertFalse(stale.ok)
        self.assertTrue(any("任务授权合同" in item for item in stale.errors))

    def test_codex_approval_records_child_agent_and_thread_context(self) -> None:
        task_id = "NUR-OPS-971"
        task = self.task_value(task_id, status="awaiting_plan_approval")
        task["type"] = "operations"
        task["reviewer"] = "Automated Plan Reviewer"
        self.enable_codex_bindings(task)
        self.write_task(task_id, task)
        self.write_valid_plan_artifacts(task_id)
        self.write_history(
            task_id,
            [
                {
                    "type": "transition",
                    "from": "draft",
                    "to": "ready_for_analysis",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:00Z",
                },
                {
                    "type": "transition",
                    "from": "ready_for_analysis",
                    "to": "awaiting_plan_approval",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:01Z",
                },
            ],
        )
        missing = self.harness.task_approval(
            task_id,
            stage="plan",
            status="approved",
            actor="Automated Plan Reviewer",
            reason="independent plan review",
        )
        self.assertFalse(missing.ok)
        self.assertTrue(any("--agent-task" in item for item in missing.errors))

        thread_id = "019f566b-dffa-7913-a608-bc2dffbd2bea"
        self.write_approval_artifact(
            task_id,
            task,
            stage="plan",
            status="approved",
            actor="Automated Plan Reviewer",
            agent_task="/root/plan_review",
            thread_id=thread_id,
        )
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": thread_id}):
            approved = self.harness.task_approval(
                task_id,
                stage="plan",
                status="approved",
                actor="Automated Plan Reviewer",
                reason="independent plan review",
                agent_task="/root/plan_review",
            )
        self.assertTrue(approved.ok, approved.errors)
        history = self.harness.workflow_history_value(task_id)
        event = history["events"][-1]
        self.assertEqual(event["agent_task"], "/root/plan_review")
        self.assertEqual(event["codex_thread_id"], thread_id)
        self.assertEqual(event["expected_actor"], "Automated Plan Reviewer")
        self.assertEqual(event["expected_agent_task"], "/root/plan_review")
        self.assertEqual(event["observed_agent_task"], "/root/plan_review")
        self.assertEqual(event["observed_codex_thread_id"], thread_id)
        self.assertRegex(str(event["review_artifact_sha256"]), r"^[0-9a-f]{64}$")
        self.assertRegex(str(event["approval_context_sha256"]), r"^[0-9a-f]{64}$")

    def test_codex_role_bindings_enforce_stage_separation(self) -> None:
        task_id = "NUR-OPS-970"
        task = self.task_value(task_id)
        task["type"] = "operations"
        self.enable_codex_bindings(task)
        bindings = task["codex_role_bindings"]
        assert isinstance(bindings, dict)
        bindings["plan"] = {"agent_task": "/root"}
        bindings["release"] = {"agent_task": "/root/merge_review"}
        self.write_task(task_id, task)
        gate = self.harness.task_check(task_id)
        self.assertFalse(gate.ok)
        self.assertTrue(any("plan.agent_task 必须与 implementation" in item for item in gate.errors))
        self.assertTrue(any("release.agent_task 必须与 merge" in item for item in gate.errors))

    def test_new_task_approval_requires_stage_binding_not_actor_prefix(self) -> None:
        task_id = "NUR-OPS-966"
        task = self.task_value(task_id, status="awaiting_plan_approval")
        task["type"] = "operations"
        task["reviewer"] = "Codex-Review"
        self.write_task(task_id, task)
        self.write_valid_plan_artifacts(task_id)
        self.write_history(
            task_id,
            [
                {
                    "type": "transition",
                    "from": "draft",
                    "to": "ready_for_analysis",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:00Z",
                },
                {
                    "type": "transition",
                    "from": "ready_for_analysis",
                    "to": "awaiting_plan_approval",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:01Z",
                },
            ],
        )
        with mock.patch.dict(
            os.environ,
            {"CODEX_THREAD_ID": "66666666-6666-4666-8666-666666666666"},
        ):
            gate = self.harness.task_approval(
                task_id,
                stage="plan",
                status="approved",
                actor="Codex-Review",
                reason="independent review",
                agent_task="/root/plan_review",
            )
        self.assertFalse(gate.ok)
        self.assertTrue(any("要求预先声明 codex_role_bindings.plan" in item for item in gate.errors))

    def test_codex_approval_rejects_implementation_thread(self) -> None:
        task_id = "NUR-OPS-969"
        implementation_thread = "22222222-2222-4222-8222-222222222222"
        task = self.task_value(task_id, status="awaiting_plan_approval")
        task["type"] = "operations"
        task["reviewer"] = "Automated Reviewer"
        self.enable_codex_bindings(
            task, implementation_thread=implementation_thread
        )
        self.write_task(task_id, task)
        self.write_valid_plan_artifacts(task_id)
        self.write_history(
            task_id,
            [
                {
                    "type": "transition",
                    "from": "draft",
                    "to": "ready_for_analysis",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:00Z",
                },
                {
                    "type": "transition",
                    "from": "ready_for_analysis",
                    "to": "awaiting_plan_approval",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:01Z",
                },
            ],
        )
        self.write_approval_artifact(
            task_id,
            task,
            stage="plan",
            status="approved",
            actor="Automated Reviewer",
            agent_task="/root/plan_review",
            thread_id=implementation_thread,
        )
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": implementation_thread}):
            gate = self.harness.task_approval(
                task_id,
                stage="plan",
                status="approved",
                actor="Automated Reviewer",
                reason="independent review",
                agent_task="/root/plan_review",
            )
        self.assertFalse(gate.ok)
        self.assertTrue(any("implementation thread" in item for item in gate.errors))

    def test_codex_review_artifact_tampering_invalidates_history(self) -> None:
        task_id = "NUR-OPS-968"
        task = self.task_value(task_id, status="awaiting_plan_approval")
        task["type"] = "operations"
        task["reviewer"] = "Bound Reviewer"
        self.enable_codex_bindings(task)
        self.write_task(task_id, task)
        self.write_valid_plan_artifacts(task_id)
        self.write_history(
            task_id,
            [
                {
                    "type": "transition",
                    "from": "draft",
                    "to": "ready_for_analysis",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:00Z",
                },
                {
                    "type": "transition",
                    "from": "ready_for_analysis",
                    "to": "awaiting_plan_approval",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:01Z",
                },
            ],
        )
        thread_id = "33333333-3333-4333-8333-333333333333"
        artifact_path = self.write_approval_artifact(
            task_id,
            task,
            stage="plan",
            status="approved",
            actor="Bound Reviewer",
            agent_task="/root/plan_review",
            thread_id=thread_id,
        )
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": thread_id}):
            approved = self.harness.task_approval(
                task_id,
                stage="plan",
                status="approved",
                actor="Bound Reviewer",
                reason="independent review",
                agent_task="/root/plan_review",
            )
        self.assertTrue(approved.ok, approved.errors)
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["summary"] = "审查制品在审批事件后被修改，必须使历史门禁失效。"
        artifact_path.write_text(json_text(artifact), encoding="utf-8")
        gate = self.harness.task_check(task_id)
        self.assertFalse(gate.ok)
        self.assertTrue(
            any("canonical SHA 已失效" in item for item in gate.errors),
            gate.errors,
        )

    def test_merge_and_release_context_lock_review_evidence_and_readiness(self) -> None:
        task_id = "NUR-OPS-967"
        task = self.task_value(task_id, status="awaiting_review")
        task["type"] = "operations"
        approvals = task["manual_approvals"]
        assert isinstance(approvals, dict)
        merge = approvals["merge"]
        assert isinstance(merge, dict)
        merge.update(
            {
                "status": "approved",
                "approved_by": "Reviewer",
                "approved_at": "2026-07-12T00:00:03Z",
            }
        )
        self.write_task(task_id, task)
        self.write_valid_plan_artifacts(task_id)
        task_dir = self.root / ".harness/tasks" / task_id
        evidence_path = task_dir / "evidence.md"
        evidence_path.write_text("# Evidence\n\nverified evidence payload\n", encoding="utf-8")
        repeated = "已独立核验当前任务的合同、证据、范围、回滚和发布边界。" * 30
        (task_dir / "review.md").write_text(
            f"# Review\n\n## 审查范围\n\n{repeated}\n\n"
            f"## 发现\n\n{repeated}\n\n## 审查结论\n\n"
            "REVIEW_RESULT: APPROVED\nREVIEWER: Reviewer\n"
            "REVIEWED_AT: 2026-07-12T00:00:03Z\n",
            encoding="utf-8",
        )
        (task_dir / "release-note.md").write_text(
            f"# Release\n\n## 变更摘要\n\n{repeated}\n\n"
            f"## 发布前提\n\n{repeated}\n\n## 发布步骤\n\n{repeated}\n\n"
            f"## 回滚触发与步骤\n\n{repeated}\n\n## 发布后验证\n\n{repeated}\n",
            encoding="utf-8",
        )
        base = "a" * 40
        self.harness.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.harness.state_file.write_text(
            json_text(
                {
                    "schema_version": 1,
                    "task_id": task_id,
                    "scope_base_commit": base,
                }
            ),
            encoding="utf-8",
        )
        pack_dir = self.root / ".harness/reports" / task_id / "20260712T000000000000Z-review-pack"
        pack_dir.mkdir(parents=True)
        pack = {
            "schema_version": 1,
            "task_id": task_id,
            "ready_for_review": True,
            "contract_sha256": harness_module.immutable_contract_hash(task),
            "policy_sha256": harness_module.policy_contract_hash(task),
            "scope_base_commit": base,
        }
        (pack_dir / "review-pack.json").write_text(
            json_text(pack), encoding="utf-8"
        )
        with mock.patch.object(self.harness, "collect_changes", return_value=[]):
            merge_context = self.harness.approval_context(task_id, task, "merge")
            release_context = self.harness.approval_context(task_id, task, "release")
            evidence_path.write_text(
                "# Evidence\n\nchanged evidence payload\n", encoding="utf-8"
            )
            changed_merge_context = self.harness.approval_context(
                task_id, task, "merge"
            )
        for field in (
            "review_pack_sha256",
            "workspace_sha256",
            "evidence_sha256",
            "verification_contract_sha256",
        ):
            self.assertRegex(str(merge_context[field]), r"^[0-9a-f]{64}$")
        self.assertNotEqual(
            merge_context["evidence_sha256"],
            changed_merge_context["evidence_sha256"],
        )
        for field in (
            "merge_approval",
            "review_sha256",
            "release_note_sha256",
            "remote_execution_sha256",
        ):
            self.assertIn(field, release_context)

    def test_plan_hash_is_stable_across_lf_crlf_and_utf8_bom(self) -> None:
        task_id = "NUR-FEAT-974"
        task = self.task_value(task_id)
        self.write_task(task_id, task)
        self.write_valid_plan_artifacts(task_id)
        task_dir = self.root / ".harness/tasks" / task_id
        normalized_texts: dict[str, str] = {}
        for name in harness_module.PLAN_ARTIFACT_NAMES:
            normalized_texts[name] = (task_dir / name).read_text(encoding="utf-8")
            (task_dir / name).write_bytes(
                normalized_texts[name].replace("\n", "\r\n").encode("utf-8")
            )
        crlf_hash = self.harness.plan_artifacts_sha256(task_id)
        for index, name in enumerate(harness_module.PLAN_ARTIFACT_NAMES):
            prefix = b"\xef\xbb\xbf" if index == 0 else b""
            (task_dir / name).write_bytes(
                prefix + normalized_texts[name].encode("utf-8")
            )
        lf_hash = self.harness.plan_artifacts_sha256(task_id)
        self.assertEqual(crlf_hash, lf_hash)

    def test_decision_change_invalidates_plan_but_allows_reapproval(self) -> None:
        decisions_path = self.root / ".harness/requirements-decisions.json"
        decisions_value = json.loads(decisions_path.read_text(encoding="utf-8"))
        decision = decisions_value["decisions"][0]
        decision.update(
            {
                "status": "resolved",
                "resolution": "selftest initial resolution",
                "approved_by": "Decision Owner",
                "approved_at": "2026-07-12T00:00:00Z",
            }
        )
        decisions_path.write_text(json_text(decisions_value), encoding="utf-8")

        task_id = "NUR-FEAT-973"
        task = self.task_value(task_id, status="awaiting_plan_approval")
        task["decision_ids"] = [decision["id"]]
        self.enable_codex_bindings(task)
        self.write_task(task_id, task)
        self.write_valid_plan_artifacts(task_id)
        self.write_history(
            task_id,
            [
                {
                    "type": "transition",
                    "from": "draft",
                    "to": "ready_for_analysis",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:00Z",
                },
                {
                    "type": "transition",
                    "from": "ready_for_analysis",
                    "to": "awaiting_plan_approval",
                    "by": "Owner",
                    "reason": "",
                    "at": "2026-07-12T00:00:01Z",
                },
            ],
        )
        approved = self.approve_bound_stage(
            task_id,
            stage="plan",
            actor="Reviewer",
            reason="",
        )
        self.assertTrue(approved.ok, approved.errors)

        decisions_value["decisions"][0]["resolution"] = "selftest revised resolution"
        decisions_path.write_text(json_text(decisions_value), encoding="utf-8")
        stale = self.harness.task_check(task_id)
        self.assertFalse(stale.ok)
        self.assertTrue(any("关联需求决策" in item for item in stale.errors))
        reapproved = self.approve_bound_stage(
            task_id,
            stage="plan",
            actor="Reviewer",
            reason="decision revised",
        )
        self.assertTrue(reapproved.ok, reapproved.errors)
        self.assertTrue(self.harness.task_check(task_id).ok)

    def test_scope_hard_blocks_policy_paths_for_business_tasks(self) -> None:
        task_id = "NUR-FEAT-984"
        self.write_plan_approved_task(task_id)
        base_gate = harness_module.GateResult("scope-base")
        base_gate.data["base_source"] = "selftest"
        completed = subprocess.CompletedProcess(
            args=["git", "ls-files"], returncode=0, stdout="", stderr=""
        )
        with (
            mock.patch.object(
                self.harness, "resolve_scope_base", return_value=("a" * 40, base_gate)
            ),
            mock.patch.object(
                self.harness,
                "collect_changes",
                return_value=[
                    harness_module.GitChange(
                        status="M",
                        paths=(".harness/harness.json",),
                        source="selftest",
                    )
                ],
            ),
            mock.patch.object(self.harness, "git", return_value=completed),
            mock.patch.object(
                self.harness, "workspace_fingerprint", return_value="f" * 64
            ),
        ):
            gate = self.harness.scope_check(
                task_id, base_ref="a" * 40, bootstrap=False, require_state=False
            )
        self.assertFalse(gate.ok)
        self.assertTrue(any("Harness policy path" in item for item in gate.errors))

    def test_oauth_and_json_secrets_are_redacted_and_scanned(self) -> None:
        raw = (
            '{"access_token":"access-secret-value","refresh_token":"refresh-secret-value",'
            '"id_token":"identity-secret-value","token":"generic-secret-value"}'
        )
        redacted = harness_module.redact_text(raw)
        for secret in (
            "access-secret-value",
            "refresh-secret-value",
            "identity-secret-value",
            "generic-secret-value",
        ):
            self.assertNotIn(secret, redacted)
        bearer = harness_module.redact_text(
            "authorization: Bearer abc.def.ghi"
        )
        self.assertNotIn("abc.def.ghi", bearer)
        dsn = harness_module.redact_text(
            "postgresql://user:supersecret@db.example/app"
        )
        self.assertNotIn("supersecret", dsn)
        password_only_dsn = harness_module.redact_text(
            "redis://:cache-secret@cache.example/0"
        )
        self.assertNotIn("cache-secret", password_only_dsn)
        token_userinfo = harness_module.redact_text(
            "https://ghp_secret_token@git.example/repository"
        )
        self.assertNotIn("ghp_secret_token", token_userinfo)
        secret_path = self.root / "sandbox.json"
        secret_path.write_text(raw, encoding="utf-8")
        scan = self.harness.scan_changed_files(
            [harness_module.GitChange("?", ("sandbox.json",), "selftest")]
        )
        self.assertTrue(
            any(item["kind"] == "hardcoded-json-secret" for item in scan["findings"])
        )

        contextual = self.root / "contextual.json"
        contextual.write_text(
            '{"note":"example only","token":"real-hardcoded-secret"}\n',
            encoding="utf-8",
        )
        contextual_scan = self.harness.scan_changed_files(
            [harness_module.GitChange("?", ("contextual.json",), "selftest")]
        )
        self.assertTrue(
            any(
                item["kind"] == "hardcoded-json-secret"
                for item in contextual_scan["findings"]
            )
        )

        large = self.root / "large-config.json"
        large.write_text("x" * (2 * 1024 * 1024 + 1), encoding="utf-8")
        large_scan = self.harness.scan_changed_files(
            [harness_module.GitChange("?", ("large-config.json",), "selftest")]
        )
        self.assertTrue(
            any(
                item["kind"] == "large-file-not-secret-scanned"
                and item["severity"] == "error"
                for item in large_scan["findings"]
            )
        )
        self.assertTrue(large_scan["skipped"])

    def test_test_command_policy_and_sensitive_environment_cleanup(self) -> None:
        self.assertTrue(harness_module.test_command_policy_errors(["curl", "https://example.test"]))
        self.assertTrue(harness_module.test_command_policy_errors(["python", "-c", "print(1)"]))
        self.assertTrue(harness_module.test_command_policy_errors(["composer", "install"]))
        self.assertTrue(harness_module.test_command_policy_errors(["git", "fetch"]))
        self.assertTrue(
            harness_module.test_command_policy_errors(
                ["git", "checkout", "HEAD", "--", "app/common.php"]
            )
        )
        self.assertTrue(harness_module.test_command_policy_errors(["npm", "ci"]))
        self.assertTrue(
            harness_module.test_command_policy_errors(
                ["env", "curl", "https://example.test"]
            )
        )
        self.assertTrue(
            harness_module.test_command_policy_errors(
                ["nice", "python", "-c", "print(1)"]
            )
        )
        self.assertTrue(
            harness_module.test_command_policy_errors(
                ["tool", "--access-token", "oauthsecret"]
            )
        )
        self.assertTrue(
            harness_module.test_command_policy_errors(
                ["env", "MYSQL_PWD=database-secret", "tool"]
            )
        )
        self.assertTrue(
            harness_module.test_command_policy_errors(
                ["tool", "https://user:password@example.test/path"]
            )
        )
        self.assertTrue(
            harness_module.test_command_policy_errors(
                ["psql", "postgresql://user:supersecret@db.example/app"]
            )
        )
        self.assertTrue(
            harness_module.test_command_policy_errors(
                ["tool", "redis://:cache-secret@cache.example/0"]
            )
        )
        self.assertTrue(
            harness_module.test_command_policy_errors(
                ["tool", "https://ghp_secret_token@git.example/repository"]
            )
        )
        with mock.patch.dict(
            os.environ,
            {"ACCESS_TOKEN": "secret", "DATABASE_URL": "secret", "SAFE_VALUE": "kept"},
            clear=True,
        ):
            environment = self.harness.test_environment()
        self.assertNotIn("ACCESS_TOKEN", environment)
        self.assertNotIn("DATABASE_URL", environment)
        self.assertEqual(environment["SAFE_VALUE"], "kept")
        self.assertEqual(environment["PIP_NO_INDEX"], "1")

    def test_subprocess_output_is_bounded_before_memory_growth(self) -> None:
        script = self.root / "noisy.py"
        script.write_text(
            "import sys\nsys.stdout.write('x' * 200000)\nsys.stdout.flush()\n",
            encoding="utf-8",
        )
        (
            exit_code,
            stdout,
            stderr,
            timed_out,
            stdout_exceeded,
            stderr_exceeded,
        ) = harness_module.bounded_subprocess(
            [os.fspath(Path(os.sys.executable)), os.fspath(script)],
            cwd=self.root,
            timeout=10,
            max_output_bytes=4096,
            environment=dict(os.environ),
        )
        self.assertFalse(timed_out)
        self.assertTrue(stdout_exceeded)
        self.assertFalse(stderr_exceeded)
        self.assertLessEqual(len(stdout), 4096)
        self.assertEqual(stderr, b"")
        self.assertIsNotNone(exit_code)

    def test_verify_rejects_business_and_control_plane_mutations(self) -> None:
        sandbox = self.root / "sandbox"
        sandbox.mkdir()
        mutator = sandbox / "mutate.py"
        mutator.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "target = Path(sys.argv[1])\n"
            "target.parent.mkdir(parents=True, exist_ok=True)\n"
            "target.write_text('mutated by required test\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        (sandbox / "business.txt").write_text("before\n", encoding="utf-8")
        scripts_dir = self.root / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "harness.py").write_text("# before\n", encoding="utf-8")

        cases = (
            ("NUR-FEAT-966", "sandbox/business.txt", "业务工作区"),
            ("NUR-FEAT-965", "scripts/harness.py", "Harness/control-plane"),
            (
                "NUR-FEAT-964",
                ".harness/tasks/NUR-FEAT-964/task.json",
                "Harness/control-plane",
            ),
            (
                "NUR-FEAT-963",
                ".harness/state/active-task.json",
                "Harness/control-plane",
            ),
            (
                "NUR-FEAT-962",
                ".harness/runs/NUR-FEAT-962/99999999T999999999999Z-verify/manifest.json",
                "verify/review gate 证据目录",
            ),
            (
                "NUR-FEAT-961",
                ".harness/reports/NUR-FEAT-961/99999999T999999999999Z-review-pack/review-pack.json",
                "verify/review gate 证据目录",
            ),
        )
        base = "a" * 40
        base_gate = harness_module.GateResult("scope-base")
        base_gate.data["base_source"] = "selftest"
        for task_id, target, expected in cases:
            with self.subTest(target=target):
                task = self.task_value(task_id, status="verifying")
                task["allowed_paths"] = ["sandbox/**"]
                task["required_tests"] = [
                    {
                        "id": "mutation_probe",
                        "description": "验证 required test 不能修改工作区或控制面。",
                        "command": ["python", "sandbox/mutate.py", target],
                        "cwd": ".",
                        "timeout_seconds": 60,
                    }
                ]
                self.write_task(task_id, task)
                self.write_valid_plan_artifacts(task_id)
                changes = [
                    harness_module.GitChange(
                        status="A",
                        paths=("sandbox/mutate.py",),
                        source="selftest",
                    )
                ]
                if target == "sandbox/business.txt":
                    changes.append(
                        harness_module.GitChange(
                            status="M", paths=(target,), source="selftest"
                        )
                    )
                ok_gate = harness_module.GateResult("stub")
                with (
                    mock.patch.object(
                        self.harness, "task_check", return_value=ok_gate
                    ),
                    mock.patch.object(
                        self.harness, "workflow_status_gate", return_value=ok_gate
                    ),
                    mock.patch.object(
                        self.harness,
                        "resolve_scope_base",
                        return_value=(base, base_gate),
                    ),
                    mock.patch.object(
                        self.harness, "collect_changes", return_value=changes
                    ),
                    mock.patch.object(self.harness, "head", return_value=base),
                    mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}),
                ):
                    gate = self.harness.verify(
                        task_id, base_ref=base, require_state=False
                    )
                self.assertFalse(gate.ok)
                self.assertTrue(any(expected in item for item in gate.errors))
                if target == ".harness/state/active-task.json":
                    self.harness.state_file.unlink(missing_ok=True)

    def test_core_change_register_requires_structured_approved_row(self) -> None:
        task_id = "NUR-FEAT-983"
        task = self.task_value(task_id)
        task["shopxo_core_change"] = {
            "required": True,
            "paths": ["app/service/NurseryService.php", "app/common.php"],
            "reason": "现有插件钩子不能覆盖启动入口与公共服务。",
            "registration": ".harness/core-changes/REGISTER.md",
        }
        baseline = self.harness.pinned_source_commit()
        register = self.root / ".harness/core-changes/REGISTER.md"
        valid_register = (
            "# Register\n\n"
            "| Task ID | Upstream baseline | Paths | Why plugin/hook is insufficient | Upgrade risk | Rollback | Reviewer | Status |\n"
            "|---|---|---|---|---|---|---|---|\n"
            f"| {task_id} | {baseline} | `app/service/NurseryService.php`, `app/common.php` | hook gap | high | revert | Reviewer | approved |\n"
        )
        register.write_text(valid_register, encoding="utf-8")
        self.assertEqual(self.harness.core_change_registration_errors(task_id, task), [])
        register.write_text(
            valid_register.replace("| approved |", "| pending |"),
            encoding="utf-8",
        )
        errors = self.harness.core_change_registration_errors(task_id, task)
        self.assertTrue(any("Status 必须为 approved" in item for item in errors))
        register.write_text(
            valid_register.replace("| hook gap |", "|  |"), encoding="utf-8"
        )
        errors = self.harness.core_change_registration_errors(task_id, task)
        self.assertTrue(any("Why plugin/hook is insufficient 不得为空" in item for item in errors))

    def test_review_pack_rejects_unregistered_core_paths(self) -> None:
        task_id = "NUR-FEAT-976"
        task = self.task_value(task_id, status="awaiting_review")
        task["allowed_paths"] = ["app/service/**"]
        task["shopxo_core_change"] = {
            "required": True,
            "paths": ["app/service/Registered.php"],
            "reason": "现有扩展点无法覆盖该公共服务。",
            "registration": ".harness/core-changes/REGISTER.md",
        }
        self.write_task(task_id, task)
        ok_task = harness_module.GateResult("task-check")
        ok_plan = harness_module.GateResult("plan-check")
        ok_evidence = harness_module.GateResult("evidence-check")
        scope = harness_module.GateResult("scope-check")
        scope.data.update(
            {
                "base_commit": "a" * 40,
                "workspace_fingerprint": "f" * 64,
                "changes": [
                    {
                        "status": "M",
                        "paths": ["app/service/Registered.php"],
                        "source": "selftest",
                    },
                    {
                        "status": "M",
                        "paths": ["app/service/Extra.php"],
                        "source": "selftest",
                    },
                    {
                        "status": "A",
                        "paths": ["app/plugins/nursery/composer.json"],
                        "source": "selftest",
                    },
                ],
            }
        )
        with (
            mock.patch.object(self.harness, "task_check", return_value=ok_task),
            mock.patch.object(self.harness, "plan_check", return_value=ok_plan),
            mock.patch.object(self.harness, "scope_check", return_value=scope),
            mock.patch.object(self.harness, "evidence_check", return_value=ok_evidence),
            mock.patch.object(self.harness, "diff_stat", return_value="selftest"),
            mock.patch.object(self.harness, "head", return_value="b" * 40),
        ):
            gate = self.harness.review_pack(
                task_id, base_ref=None, require_state=False
            )
        self.assertFalse(gate.ok)
        self.assertTrue(any("核心变更未被" in item for item in gate.errors))
        self.assertTrue(any("new_dependency_allowed" in item for item in gate.errors))

    def test_database_change_requires_affected_tables(self) -> None:
        task_id = "NUR-DATA-977"
        task = self.task_value(task_id)
        task["type"] = "data"
        task["database_change"] = {
            "required": True,
            "affected_tables": [],
            "migration_paths": ["app/plugins/nursery/sql/update.sql"],
            "rollback_plan": "使用前向修复恢复兼容字段并保留历史数据。",
            "verification": "核对 schema、索引、行数和幂等重跑结果。",
        }
        self.write_task(task_id, task)
        gate = self.harness.task_check(task_id)
        self.assertFalse(gate.ok)
        self.assertTrue(any("affected_tables" in item for item in gate.errors))

    def test_full_install_sql_cannot_be_the_only_migration_without_exception(self) -> None:
        task_id = "NUR-DATA-969"
        task = self.task_value(task_id)
        task["type"] = "data"
        task["database_change"] = {
            "required": True,
            "affected_tables": ["sxo_goods"],
            "migration_paths": ["config/shopxo.sql"],
            "fresh_install_baseline_exception": {
                "requested": False,
                "reason": "",
            },
            "rollback_plan": "通过备份恢复，并保留升级前数据库快照。",
            "verification": "验证新装数据库 schema、既有站点升级和幂等重跑。",
        }
        self.write_task(task_id, task)
        rejected = self.harness.task_check(task_id)
        self.assertFalse(rejected.ok)
        self.assertTrue(any("唯一 forward migration" in item for item in rejected.errors))

        task_path = self.root / ".harness/tasks" / task_id / "task.json"
        task["database_change"]["fresh_install_baseline_exception"] = {
            "requested": True,
            "reason": "该任务只重建尚未发布的全新安装基线，不存在需要升级的既有实例。",
        }
        task_path.write_text(json_text(task), encoding="utf-8")
        accepted = self.harness.task_check(task_id)
        self.assertTrue(accepted.ok, accepted.errors)

    def test_authentication_foundation_requirements_force_l4(self) -> None:
        task_id = "NUR-FEAT-972"
        task = self.task_value(task_id)
        task["risk_level"] = "L2"
        task["requirement_ids"] = ["FR-USER-001"]
        task["acceptance_criteria"] = [
            {
                "id": "AC-TASK-001",
                "requirement_ids": ["FR-USER-001"],
                "description": "注册认证基础必须经过 L4 门禁。",
            }
        ]
        self.write_task(task_id, task)
        gate = self.harness.task_check(task_id)
        self.assertFalse(gate.ok)
        self.assertTrue(any("必须为 L4" in item for item in gate.errors))

    def test_hook_blocks_direct_shell_file_writes(self) -> None:
        hook = runpy.run_path(
            str(PROJECT_ROOT / ".codex/hooks/harness_guard.py")
        )
        self.assertIn("codex_role_bindings", hook["immutable_contract"]({}))
        self.assertEqual(
            set(harness_module.HARNESS_POLICY_PATTERNS),
            set(hook["BOOTSTRAP_PATTERNS"]),
        )
        check_shell = hook["check_shell"]
        self.assertIsNotNone(
            check_shell({"command": "Set-Content app/unauthorized.php '<?php'"})
        )
        self.assertIsNotNone(
            check_shell({"command": "echo secret > app/unauthorized.php"})
        )
        self.assertIsNone(
            check_shell(
                {"command": "python scripts/harness.py task-check NUR-FEAT-001"}
            )
        )
        for command in (
            "git checkout HEAD -- app/common.php",
            "git restore --source HEAD app/common.php",
            "npm ci",
            "composer update",
        ):
            self.assertIsNotNone(check_shell({"command": command}), command)
        self.assertIsNone(
            check_shell({"command": "git switch -c feat/NUR-FEAT-001-safe"})
        )

        task_id = "NUR-HARNESS-979"
        task = self.task_value(task_id, status="implementing")
        task["type"] = "harness"
        task["allowed_paths"] = ["app/**"]
        self.write_task(task_id, task)
        self.write_valid_plan_artifacts(task_id)
        hook_globals = check_shell.__globals__
        hook_globals["ROOT"] = self.root
        hook_globals["TASKS_DIR"] = self.root / ".harness/tasks"
        hook_globals["STATE_FILE"] = self.root / ".harness/state/active-task.json"
        hook_globals["DECISIONS_FILE"] = (
            self.root / ".harness/requirements-decisions.json"
        )
        state = {
            "schema_version": 1,
            "task_id": task_id,
            "contract_sha256": hook["canonical_json_hash"](
                hook["immutable_contract"](task)
            ),
            "policy_sha256": hook["canonical_json_hash"](
                hook["policy_contract"](task)
            ),
            "plan_artifacts_sha256": hook_globals["plan_artifacts_sha256"](task_id),
            "decision_context_sha256": hook_globals["decision_context_sha256"](task),
        }
        hook_globals["STATE_FILE"].write_text(json_text(state), encoding="utf-8")
        reason = hook["check_apply_patch"](
            "*** Begin Patch\n*** Update File: app/unauthorized.php\n*** End Patch"
        )
        self.assertIsNotNone(reason)
        self.assertIn("NUR-HARNESS", reason)

        business_id = "NUR-FEAT-978"
        business_task = self.task_value(business_id, status="implementing")
        business_task["allowed_paths"] = ["scripts/harness_remote.py"]
        self.write_task(business_id, business_task)
        self.write_valid_plan_artifacts(business_id)
        business_state = {
            "schema_version": 1,
            "task_id": business_id,
            "contract_sha256": hook["canonical_json_hash"](
                hook["immutable_contract"](business_task)
            ),
            "policy_sha256": hook["canonical_json_hash"](
                hook["policy_contract"](business_task)
            ),
            "plan_artifacts_sha256": hook_globals["plan_artifacts_sha256"](
                business_id
            ),
            "decision_context_sha256": hook_globals["decision_context_sha256"](
                business_task
            ),
        }
        hook_globals["STATE_FILE"].write_text(
            json_text(business_state), encoding="utf-8"
        )
        broker_reason = hook["check_apply_patch"](
            "*** Begin Patch\n*** Update File: scripts/harness_remote.py\n*** End Patch"
        )
        self.assertIsNotNone(broker_reason)
        self.assertIn("Harness 策略或执行面", broker_reason)
        approval_reason = hook["check_apply_patch"](
            "*** Begin Patch\n"
            f"*** Add File: .harness/tasks/{business_id}/approval-merge.json\n"
            "+{}\n"
            "*** End Patch"
        )
        self.assertIsNone(approval_reason)

        original_link_check = hook_globals["path_is_link_like"]
        hook_globals["path_is_link_like"] = lambda path: path.name == "linked.php"
        try:
            link_reason = hook["check_apply_patch"](
                "*** Begin Patch\n*** Update File: linked.php\n*** End Patch"
            )
        finally:
            hook_globals["path_is_link_like"] = original_link_check
        self.assertIsNotNone(link_reason)
        self.assertIn("符号链接或目录联接", link_reason)

    def test_hook_blocks_network_client_path_and_powershell_bypasses(self) -> None:
        hook = runpy.run_path(
            str(PROJECT_ROOT / ".codex/hooks/harness_guard.py")
        )
        check_shell = hook["check_shell"]
        expected_clients = {
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
        self.assertEqual(
            hook["SHELL_NETWORK_CLIENT_BASENAMES"], frozenset(expected_clients)
        )
        for client in sorted(expected_clients):
            command = rf'C:\Tools\Network Clients\{client}.EXE --version'
            self.assertIsNotNone(check_shell({"command": command}), command)

        for command in (
            "/usr/bin/curl https://example.test",
            r"C:\Windows\System32\OpenSSH\ssh.exe root@example.test",
            r'& "C:\Program Files\PuTTY\plink.cmd" root@example.test',
            "Microsoft.PowerShell.Utility\\Invoke-WebRequest https://example.test",
            "Microsoft.PowerShell.Utility\\Invoke-RestMethod https://example.test",
            "iwr https://example.test",
            "irm https://example.test",
            "Start-BitsTransfer https://example.test target.bin",
            "Test-NetConnection example.test -Port 443",
            "Resolve-DnsName example.test",
        ):
            self.assertIsNotNone(check_shell({"command": command}), command)

        exact_remote = (
            "python -I -S -B scripts/harness.py remote-exec "
            "NUR-OPS-003 curl --json"
        )
        self.assertIsNone(check_shell({"command": exact_remote}))
        self.assertIsNone(
            check_shell(
                'await tools.shell_command({command:"'
                + exact_remote
                + '"});'
            )
        )
        self.assertIsNotNone(
            check_shell(
                {
                    "command": exact_remote
                    + r"; C:\Windows\System32\OpenSSH\ssh.exe root@example.test"
                }
            )
        )
        for unsafe in (
            "python scripts/harness.py remote-exec NUR-OPS-003 curl --json",
            "python -I -S scripts/harness.py remote-actions NUR-OPS-003",
            "python -I -B scripts/harness.py release-seal NUR-OPS-003",
            "python -S -B scripts/harness.py release-check NUR-OPS-003",
        ):
            self.assertIsNotNone(check_shell({"command": unsafe}), unsafe)
        self.assertIsNone(
            check_shell(
                {
                    "command": "python -I -S -B scripts/harness.py "
                    "release-check NUR-OPS-003"
                }
            )
        )
        self.assertIn(
            "-I -S -B",
            (PROJECT_ROOT / "scripts/harness.ps1").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "-I -S -B",
            (PROJECT_ROOT / "scripts/harness.sh").read_text(encoding="utf-8"),
        )
        self.assertIsNone(
            check_shell({"command": "Write-Output ssh-keygen curl-config"})
        )

    def test_hook_blocks_powershell_dotnet_and_dynamic_network_execution(self) -> None:
        hook = runpy.run_path(
            str(PROJECT_ROOT / ".codex/hooks/harness_guard.py")
        )
        check_shell = hook["check_shell"]
        blocked_commands = (
            "(New-Object System.Net.WebClient).DownloadString('https://example.test')",
            "[System.Net.Http.HttpClient]::new().GetStringAsync('https://example.test')",
            "[System.Net.WebRequest]::Create('https://example.test')",
            "[System.Net.HttpWebRequest]::Create('https://example.test')",
            "[System.Net.Sockets.TcpClient]::new('example.test', 443)",
            "[System.Net.Sockets.UdpClient]::new(53)",
            "[System.Net.Dns]::GetHostAddresses('example.test')",
            "New-Object ([string]::Concat('System.Net.', 'WebClient'))",
            "[type]::GetType('System.Net.' + 'Sockets.TcpClient')",
            "& ('s'+'sh') root@example.test",
            "& ([string]::Concat('cu','rl')) https://example.test",
            "$client = 's' + 'sh'; & $client root@example.test",
            "Invoke-Expression ('cu' + 'rl' + ' https://example.test')",
            "iex $payload",
            "powershell.exe -EncodedCommand YwB1AHIAbAA=",
            "pwsh -enc YwB1AHIAbAA=",
            "powershell -e YwB1AHIAbAA=",
            "Start-Process $client -ArgumentList 'https://example.test'",
            "Write-Output ('s' + 'sh')",
            "[string]::Concat('cu', 'rl')",
        )
        for command in blocked_commands:
            self.assertIsNotNone(check_shell({"command": command}), command)

        for command in (
            "Write-Output ('seed' + 'ling')",
            "[string]::Concat('nur', 'sery')",
            "Test-Path scripts/harness.py",
            "python -I -S -B scripts/harness.py remote-exec NUR-OPS-003 ssh --json",
            "python -I -S -B scripts/harness.py remote-exec NUR-OPS-003 iex --json",
        ):
            self.assertIsNone(check_shell({"command": command}), command)
        self.assertIsNone(
            check_shell(
                'await tools.shell_command({command:"python -I -S -B scripts/harness.py '
                'remote-exec NUR-OPS-003 iex --json"});'
            )
        )

    def test_hook_blocks_git_write_plumbing_and_config_injection(self) -> None:
        hook = runpy.run_path(
            str(PROJECT_ROOT / ".codex/hooks/harness_guard.py")
        )
        check_shell = hook["check_shell"]
        blocked_commands = (
            "git hash-object -w --stdin",
            "git hash-object --stdin-paths",
            "git update-index --cacheinfo 100644 deadbeef .harness/tasks/NUR-OPS-003/workflow-history.json",
            "git commit-tree deadbeef -m forged",
            "git update-ref refs/heads/main deadbeef",
            "git read-tree -u deadbeef",
            "git checkout-index -a -f",
            "git fast-import",
            "git write-tree",
            "git mktree",
            "git replace deadbeef feedface",
            "git notes add -m forged deadbeef",
            "git notes remove deadbeef",
            "git symbolic-ref HEAD refs/heads/forged",
            "git symbolic-ref --delete refs/heads/forged",
            "git worktree add ../second-checkout main",
            "git config --local filter.x.clean powershell.exe",
            "git config core.attributesFile .gitattributes.injected",
            "git config alias.deploy !ssh",
            "git config core.hooksPath .hooks",
            "git -c core.attributesFile=.gitattributes.injected status",
            "git --config-env=core.attributesFile=ATTR_FILE status",
            "$env:GIT_CONFIG_COUNT=1; git status",
            r'"C:\Program Files\Git\cmd\git.exe" update-ref refs/heads/main deadbeef',
            'await tools.shell_command({command:"git update-ref refs/heads/main deadbeef"});',
        )
        for command in blocked_commands:
            self.assertIsNotNone(check_shell({"command": command}), command)

        read_only_commands = (
            "git status --short",
            "git log -1 --oneline",
            "git diff --stat",
            "git show --stat HEAD",
            "git rev-parse HEAD",
            "git ls-files",
            "git cat-file -e HEAD^{commit}",
            "git fast-export --all",
            "git symbolic-ref HEAD",
            "git notes list",
            "git notes show deadbeef",
            "git worktree list --porcelain",
            "git config --get user.name",
            "git config user.email",
            "git config --get core.attributesFile",
            "git check-attr -a app/common.php",
            r'"C:\Program Files\Git\cmd\git.exe" status --short',
            'await tools.shell_command({command:"git status --short"});',
        )
        for command in read_only_commands:
            self.assertIsNone(check_shell({"command": command}), command)

    def test_hook_locks_cli_owned_task_control_files(self) -> None:
        hook = runpy.run_path(
            str(PROJECT_ROOT / ".codex/hooks/harness_guard.py")
        )
        check_apply_patch = hook["check_apply_patch"]
        hook_globals = check_apply_patch.__globals__
        hook_globals["ROOT"] = self.root
        hook_globals["TASKS_DIR"] = self.root / ".harness/tasks"
        hook_globals["STATE_FILE"] = self.root / ".harness/state/active-task.json"
        hook_globals["DECISIONS_FILE"] = (
            self.root / ".harness/requirements-decisions.json"
        )

        history_reason = check_apply_patch(
            "*** Begin Patch\n"
            "*** Add File: .harness/tasks/NUR-FEAT-917/workflow-history.json\n"
            "*** End Patch"
        )
        self.assertIsNotNone(history_reason)
        self.assertIn("Harness CLI", history_reason)

        for task_id, status in (
            ("NUR-FEAT-918", "draft"),
            ("NUR-FEAT-919", "ready_for_analysis"),
        ):
            self.write_task(task_id, self.task_value(task_id, status=status))
            reason = check_apply_patch(
                "*** Begin Patch\n"
                f"*** Update File: .harness/tasks/{task_id}/task.json\n"
                "*** End Patch"
            )
            self.assertIsNone(reason, f"{status}: {reason}")

        locked_statuses = (
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
        self.assertEqual(
            hook["TASK_CONTRACT_LOCKED_STATUSES"], frozenset(locked_statuses)
        )
        for index, status in enumerate(locked_statuses, start=920):
            task_id = f"NUR-FEAT-{index:03d}"
            self.write_task(task_id, self.task_value(task_id, status=status))
            reason = check_apply_patch(
                "*** Begin Patch\n"
                f"*** Update File: .harness/tasks/{task_id}/task.json\n"
                "*** End Patch"
            )
            self.assertIsNotNone(reason, status)
            self.assertIn(status, reason)

        active_id = "NUR-FEAT-929"
        active_task = self.task_value(active_id, status="draft")
        self.write_task(active_id, active_task)
        self.write_valid_plan_artifacts(active_id)
        active_state = {
            "schema_version": 1,
            "task_id": active_id,
            "contract_sha256": hook["canonical_json_hash"](
                hook["immutable_contract"](active_task)
            ),
            "policy_sha256": hook["canonical_json_hash"](
                hook["policy_contract"](active_task)
            ),
            "plan_artifacts_sha256": hook_globals["plan_artifacts_sha256"](
                active_id
            ),
            "decision_context_sha256": hook_globals["decision_context_sha256"](
                active_task
            ),
        }
        hook_globals["STATE_FILE"].write_text(
            json_text(active_state), encoding="utf-8"
        )
        active_reason = check_apply_patch(
            "*** Begin Patch\n"
            f"*** Update File: .harness/tasks/{active_id}/task.json\n"
            "*** End Patch"
        )
        self.assertIsNotNone(active_reason)
        self.assertIn("preflight 后锁定", active_reason)

    def test_existing_active_state_prevents_preflight_rebase(self) -> None:
        task_id = "NUR-FEAT-982"
        self.write_plan_approved_task(task_id)
        self.harness.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.harness.state_file.write_text(
            json_text({"schema_version": 1, "task_id": task_id}), encoding="utf-8"
        )
        gate = self.harness.preflight(task_id)
        self.assertFalse(gate.ok)
        self.assertTrue(any("拒绝重写 scope_base_commit" in item for item in gate.errors))

    def test_portable_toolchain_facts_ignore_absolute_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nursery-harness-portable-") as other_value:
            other = Path(other_value)
            shutil.copytree(PROJECT_ROOT / ".harness", other / ".harness")
            other_harness = harness_module.Harness(other)
            first = harness_module.canonical_json_hash(self.harness.portable_toolchain_facts())
            second = harness_module.canonical_json_hash(other_harness.portable_toolchain_facts())
        self.assertEqual(first, second)

    def test_baseline_hashes_normalize_sql_lines_and_detect_content_drift(self) -> None:
        (self.root / "config").mkdir()
        sql_path = self.root / "config/shopxo.sql"
        sql_text = "CREATE TABLE sxo_example (id int);\nINSERT INTO sxo_example VALUES (1);\n"
        sql_path.write_text(sql_text, encoding="utf-8", newline="\n")
        lf_hash = harness_module.canonical_text_file_sha256(
            sql_path, label="config/shopxo.sql"
        )
        sql_path.write_bytes(sql_text.replace("\n", "\r\n").encode("utf-8"))
        crlf_hash = harness_module.canonical_text_file_sha256(
            sql_path, label="config/shopxo.sql"
        )
        self.assertEqual(lf_hash, crlf_hash)

        composer = self.root / "composer.json"
        composer.write_text('{"require":{"php":">=8.0.2"}}\n', encoding="utf-8")
        composer_before = harness_module.canonical_json_hash(
            self.harness.portable_toolchain_facts()
        )
        composer.write_text('{"require":{"php":">=8.1"}}\n', encoding="utf-8")
        composer_after = harness_module.canonical_json_hash(
            self.harness.portable_toolchain_facts()
        )
        self.assertNotEqual(composer_before, composer_after)

        migration_paths = (
            "app/install/controller/Index.php",
            "app/service/SystemUpgradeService.php",
            "app/service/PluginsAdminService.php",
            "app/service/SqlConsoleService.php",
        )
        for rel in migration_paths:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("<?php // migration selftest\n", encoding="utf-8")
        migration_before = harness_module.canonical_json_hash(
            self.harness.migration_mechanism_facts()
        )
        changed = self.root / migration_paths[1]
        changed.write_text("<?php // changed migration entry\n", encoding="utf-8")
        migration_after = harness_module.canonical_json_hash(
            self.harness.migration_mechanism_facts()
        )
        self.assertNotEqual(migration_before, migration_after)

    def test_release_check_requires_approved_for_merge_outside_transition(self) -> None:
        task_id = "NUR-FEAT-981"
        task = self.task_value(task_id, status="awaiting_review")
        self.write_task(task_id, task)
        ok_gate = harness_module.GateResult("stub")
        with (
            mock.patch.object(self.harness, "task_check", return_value=ok_gate),
            mock.patch.object(self.harness, "plan_check", return_value=ok_gate),
            mock.patch.object(self.harness, "scope_check", return_value=ok_gate),
            mock.patch.object(self.harness, "evidence_check", return_value=ok_gate),
        ):
            external = self.harness.release_check(
                task_id, base_ref=None, require_state=False
            )
            internal = self.harness.release_check(
                task_id,
                base_ref=None,
                require_state=False,
                allow_pretransition=True,
            )
        self.assertTrue(any("未获合并/关闭授权" in item for item in external.errors))
        self.assertFalse(any("未获合并/关闭授权" in item for item in internal.errors))

    def test_complete_l4_lifecycle_reaches_closed_with_eleven_events(self) -> None:
        task_id = "NUR-FEAT-978"
        branch = f"feat/{task_id}-lifecycle"
        pinned = self.harness.pinned_source_commit()
        assert pinned is not None
        (self.root / "config").mkdir(parents=True, exist_ok=True)
        (self.root / "config/shopxo.sql").write_text(
            "CREATE TABLE lifecycle_probe(id int);\n", encoding="utf-8"
        )
        (self.root / "composer.json").write_text("{}\n", encoding="utf-8")
        (self.root / "composer.lock").write_text("{}\n", encoding="utf-8")
        sandbox = self.root / "sandbox"
        sandbox.mkdir()
        (sandbox / "check.py").write_text(
            "print('lifecycle smoke passed')\n", encoding="utf-8"
        )

        task = self.task_value(task_id)
        task["allowed_paths"] = ["sandbox/**"]
        self.enable_codex_bindings(task)
        task["required_tests"] = [
            {
                "id": "lifecycle_smoke",
                "description": "运行完整生命周期的真实无 shell 冒烟测试。",
                "command": ["python", "sandbox/check.py"],
                "cwd": ".",
                "timeout_seconds": 60,
            },
            {
                "id": "lifecycle_smoke_second",
                "description": "验证多测试证据必须逐项完整记录。",
                "command": ["python", "sandbox/check.py"],
                "cwd": ".",
                "timeout_seconds": 60,
            },
        ]
        self.write_task(task_id, task)
        self.write_valid_plan_artifacts(task_id)

        source_status = [
            {"path": item["path"], "kind": item["kind"], "status": "confirmed"}
            for item in self.harness.config["source"]["required_paths"]
        ]

        def fake_git_value(*args: str) -> str | None:
            if args == ("rev-parse", "--show-toplevel"):
                return str(self.root)
            if args == ("remote",):
                return "upstream"
            if args == ("remote", "get-url", "upstream"):
                return self.harness.config["source"]["upstream_remote"]
            return None

        def fake_git(
            *args: str, timeout: int = 15, check: bool = False
        ) -> subprocess.CompletedProcess[str]:
            del timeout, check
            if args and args[0] == "ls-files":
                stdout = "sandbox/check.py\x00"
            elif args[:2] == ("diff", "--stat"):
                stdout = " sandbox/check.py | 1 +\n"
            else:
                stdout = ""
            return subprocess.CompletedProcess(
                args=["git", *args], returncode=0, stdout=stdout, stderr=""
            )

        changes = [
            harness_module.GitChange(
                status="A", paths=("sandbox/check.py",), source="selftest"
            )
        ]
        with (
            mock.patch.object(self.harness, "is_git_repository", return_value=True),
            mock.patch.object(self.harness, "branch", return_value=branch),
            mock.patch.object(self.harness, "head", return_value=pinned),
            mock.patch.object(self.harness, "git_value", side_effect=fake_git_value),
            mock.patch.object(self.harness, "git", side_effect=fake_git),
            mock.patch.object(self.harness, "git_object_exists", return_value=True),
            mock.patch.object(self.harness, "is_ancestor", return_value=True),
            mock.patch.object(self.harness, "repository_dirty_paths", return_value=[]),
            mock.patch.object(self.harness, "source_status", return_value=source_status),
            mock.patch.object(self.harness, "collect_changes", return_value=changes),
        ):
            baseline = self.harness.baseline()
            self.assertTrue(baseline.ok, baseline.errors)

            transitions = [
                ("ready_for_analysis", "Owner", ""),
                ("awaiting_plan_approval", "Owner", ""),
            ]
            for target, actor, reason in transitions:
                gate = self.harness.task_transition(
                    task_id, target_status=target, actor=actor, reason=reason
                )
                self.assertTrue(gate.ok, gate.errors)

            plan_approval = self.approve_bound_stage(
                task_id,
                stage="plan",
                actor="Reviewer",
                reason="",
            )
            self.assertTrue(plan_approval.ok, plan_approval.errors)
            approved = self.harness.task_transition(
                task_id,
                target_status="approved_for_implementation",
                actor="Reviewer",
                reason="",
            )
            self.assertTrue(approved.ok, approved.errors)
            preflight = self.harness.preflight(task_id)
            self.assertTrue(preflight.ok, preflight.errors)
            implementing = self.harness.task_transition(
                task_id,
                target_status="implementing",
                actor="Owner",
                reason="",
            )
            self.assertTrue(implementing.ok, implementing.errors)
            verifying = self.harness.task_transition(
                task_id,
                target_status="verifying",
                actor="Owner",
                reason="",
            )
            self.assertTrue(verifying.ok, verifying.errors)

            verify = self.harness.verify(task_id, base_ref=None, require_state=True)
            self.assertTrue(verify.ok, verify.errors)
            verification_contract = str(
                verify.data["verification_contract_sha256"]
            )
            command_json = harness_module.command_text(["python", "sandbox/check.py"])
            repeated = (
                "该证据来自本次真实运行，断言、限制、身份、输入与预期均已逐项记录，"
                "未执行内容不会表述为通过。"
            ) * 12
            evidence = (
                f"# {task_id} 实施证据\n\n"
                "## 验收标准映射\n\n"
                f"AC-TASK-001：通过。{repeated}\n\n"
                "## 自动测试证据\n\n"
                f"VERIFY_CONTRACT_SHA256: {verification_contract}\n\n"
                f"TEST_COMMAND: lifecycle_smoke {command_json}\n\n"
                "TEST_RESULT: lifecycle_smoke exit_code=0\n\n"
                "## 手工与页面证据\n\n本集成回归不涉及页面，自动断言覆盖状态与文件证据。\n\n"
                "## 已知限制\n\n仅模拟 Git 元数据，不访问生产环境。\n\n"
                "## 回滚证据\n\n临时目录由 unittest 清理，清理后无外部状态。\n"
            )
            (self.root / ".harness/tasks" / task_id / "evidence.md").write_text(
                evidence, encoding="utf-8"
            )
            incomplete_evidence = self.harness.evidence_check(
                task_id, base_ref=None, require_state=True
            )
            self.assertFalse(incomplete_evidence.ok)
            self.assertTrue(
                any(
                    "lifecycle_smoke_second" in item
                    for item in incomplete_evidence.errors
                )
            )
            evidence_path = self.root / ".harness/tasks" / task_id / "evidence.md"
            evidence_path.write_text(
                evidence_path.read_text(encoding="utf-8")
                + f"\nTEST_COMMAND: lifecycle_smoke_second {command_json}\n"
                + "TEST_RESULT: lifecycle_smoke_second exit_code=0\n",
                encoding="utf-8",
            )
            evidence_gate = self.harness.evidence_check(
                task_id, base_ref=None, require_state=True
            )
            self.assertTrue(evidence_gate.ok, evidence_gate.errors)
            awaiting_review = self.harness.task_transition(
                task_id,
                target_status="awaiting_review",
                actor="Owner",
                reason="",
            )
            self.assertTrue(awaiting_review.ok, awaiting_review.errors)
            review_pack = self.harness.review_pack(
                task_id, base_ref=None, require_state=True
            )
            self.assertTrue(review_pack.ok, review_pack.errors)

            review_text = (
                f"# {task_id} 审查\n\n## 审查范围\n\n{repeated}\n\n"
                f"## 发现\n\n未发现阻断项。{repeated}\n\n"
                "## 审查结论\n\nREVIEW_RESULT: APPROVED\n"
                "REVIEWER: Reviewer\nREVIEWED_AT: 2026-07-12T00:00:00Z\n"
            )
            release_text = (
                f"# {task_id} 发布说明\n\n## 变更摘要\n\n{repeated}\n\n"
                f"## 发布前提\n\n{repeated}\n\n## 发布步骤\n\n{repeated}\n\n"
                f"## 回滚触发与步骤\n\n{repeated}\n\n## 发布后验证\n\n{repeated}\n"
            )
            task_dir = self.root / ".harness/tasks" / task_id
            (task_dir / "review.md").write_text(review_text, encoding="utf-8")
            (task_dir / "release-note.md").write_text(
                release_text, encoding="utf-8"
            )
            merge = self.approve_bound_stage(
                task_id,
                stage="merge",
                actor="Reviewer",
                reason="",
            )
            self.assertTrue(merge.ok, merge.errors)
            release = self.approve_bound_stage(
                task_id,
                stage="release",
                actor="Release Approver",
                reason="",
            )
            self.assertTrue(release.ok, release.errors)
            merge_ready = self.harness.task_transition(
                task_id,
                target_status="approved_for_merge",
                actor="Reviewer",
                reason="",
            )
            self.assertTrue(merge_ready.ok, merge_ready.errors)
            release_gate = self.harness.release_check(
                task_id, base_ref=None, require_state=True
            )
            self.assertTrue(release_gate.ok, release_gate.errors)
            closed = self.harness.task_transition(
                task_id,
                target_status="closed",
                actor="Owner",
                reason="selftest merge complete",
            )
            self.assertTrue(closed.ok, closed.errors)
            closed_gate = self.harness.task_check(task_id)
            self.assertTrue(closed_gate.ok, closed_gate.errors)

        final_task = self.harness.load_task(task_id)
        self.assertEqual(final_task["status"], "closed")
        history = self.harness.workflow_history_value(task_id)
        self.assertEqual(len(history["events"]), 11)
        self.assertFalse(self.harness.state_file.exists())
        self.assertFalse(list((self.root / ".harness/state").rglob("*.lock")))
        self.assertFalse(list((self.root / ".harness/state").rglob("*.json")))


if __name__ == "__main__":
    unittest.main(verbosity=2)

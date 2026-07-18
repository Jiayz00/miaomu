# NUR-OPS-001 实施证据

## 验收标准映射

| 验收标准 | 当前结论 | 证据要求 |
| --- | --- | --- |
| `AC-TASK-001` 密钥与配置边界 | 本地合同与 broker 自检通过；服务器未执行 | Git 敏感扫描、外部文件元数据、脱敏 release manifest 和远程退出码 |
| `AC-TASK-002` 固定 release、两服务、intl/Caddy/88、v1 迁移与性能入口 | 本地合同验证通过；服务器未执行 | Docker/Compose/PHP/Caddy/HTTP、schema-only 基线、`initialize_nursery` 三组迁移的 schema/台账/幂等证据和性能真实结果；后台凭据、深备份及缺失场景标记 blocked/not_run |

## 自动测试证据

VERIFY_CONTRACT_SHA256: 6a55a14ab345dfd044a33961e8aa3c49aff2e5d0f35a7ac0e81dc59f43b9fd68

Harness verify 运行目录：`.harness/runs/NUR-OPS-001/20260718T194150030953Z-verify`。scope base：`42c7e4b1213a208b6bf8b6fc9b8d6db28f2f3283`；已实际运行：

TEST_COMMAND: task_check ["python", "scripts/harness.py", "task-check", "NUR-OPS-001"]
TEST_RESULT: task_check exit_code=0
TEST_COMMAND: plan_check ["python", "scripts/harness.py", "plan-check", "NUR-OPS-001"]
TEST_RESULT: plan_check exit_code=0
TEST_COMMAND: harness_selftest ["python", "scripts/harness_selftest.py"]
TEST_RESULT: harness_selftest exit_code=0
TEST_COMMAND: harness_remote_selftest ["python", "scripts/harness_remote_selftest.py"]
TEST_RESULT: harness_remote_selftest exit_code=0
TEST_COMMAND: deploy_contract ["python", "tests/ops/test_deployment_contract.py"]
TEST_RESULT: deploy_contract exit_code=0
TEST_COMMAND: release_inputs_contract ["python", "deploy/validate_release_inputs.py", "--contract-only"]
TEST_RESULT: release_inputs_contract exit_code=0

本次 verify 实际结果：`harness_selftest` 61 项通过、2 项 Windows 权限 skip；`harness_remote_selftest` 59 项通过（含 Caddy 容器内 `/etc/caddy/Caddyfile` 固定动作回归）；部署合同 43 项通过；release-input 合同通过。所有测试均为退出码 0，未触发超时或输出上限；verify 前后控制面哈希和业务工作区指纹一致，变更清单未包含 Harness 策略文件。

本次还完成项目级 Harness bootstrap 修复：仅允许合同声明的 Caddy `docker compose run ... caddy jia-caddy validate --config /etc/caddy/Caddyfile` 容器内路径，任意路径或服务变体仍 fail-closed；未扩大宿主机 `managed_roots`。

未执行的 PHP、Docker、Caddy、MySQL、HTTP、浏览器、并发和回滚不写为通过。

## 手工与页面证据

当前没有服务器、浏览器、数据库或 Caddy 真实证据。预留证据必须包含：主机指纹匹配（不含密钥内容）、Caddy/Beszel/80/443 快照、Docker/Compose/镜像摘要、secret owner/group/mode/size、空库/schema-only bootstrap 结果、固定 baseline 后三组 v1 迁移的实际表/索引、`sxo_config` 台账和幂等重跑结果、FPM socket 权限、回环 88 响应、拒绝旁路和性能原始结果路径。数据库/上传深备份与后台登录凭据若未执行必须显式标记 blocked/not_run。输出需脱敏。

## 已知限制

- 已按 broker 尝试两次只读 `inventory_pwd`，均为 `exit_code=255` 且无输出；本地 TCP 22 可达，但 SSH 认证/会话未建立。未执行任何远程写动作，完整远端部署目前 blocked，恢复 SSH 后必须从 inventory 重新开始。
- HMAC secret 的值不可读取或记录；只能证明外部文件元数据和幂等保留行为。
- 收藏、询价、行为上报、30 日趋势和导出性能依赖后续功能/夹具，未具备时必须分别记 blocked/not_run。
- 本证据不能作为 release approval 或部署成功证明；审批、release seal 和真实服务器测试仍是后续门禁。

## 回滚证据

尚未执行远程写操作，因此没有回滚结果。实际发布必须先保存 Caddyfile/Compose 快照；本次空测试库的数据库/上传/插件深备份若未具备动作支持必须记录 blocked，再在失败时执行合同 rollback actions，并记录每个动作的退出码、恢复哈希和共享服务健康结果。

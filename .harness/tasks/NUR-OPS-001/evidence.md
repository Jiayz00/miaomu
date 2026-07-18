# NUR-OPS-001 实施证据

## 验收标准映射

| 验收标准 | 当前结论 | 证据要求 |
| --- | --- | --- |
| `AC-TASK-001` 密钥与配置边界 | 本地合同已声明；服务器未执行 | Git 敏感扫描、外部文件元数据、脱敏 release manifest 和远程退出码 |
| `AC-TASK-002` 固定 release、两服务、intl/Caddy/88、v1 迁移与性能入口 | 本地制品已声明；远程未执行 | Docker/Compose/PHP/Caddy/HTTP、`initialize_nursery` 三组迁移的 schema/台账/幂等证据和性能真实结果；缺失场景标记 blocked/not_run |

## 自动测试证据

本轮仅完成合同制品审阅，未进入远程执行阶段。已实际运行：

- `TEST_COMMAND: task_check ["python","scripts/harness.py","task-check","NUR-OPS-001"]`
- `TEST_RESULT: task_check exit_code=0`
- `TEST_COMMAND: plan_check ["python","scripts/harness.py","plan-check","NUR-OPS-001"]`
- `TEST_RESULT: plan_check exit_code=0`

进入 `verifying` 后必须由 Harness 生成并填入 `VERIFY_CONTRACT_SHA256: <sha256>`，再追加 `harness_selftest`、`harness_remote_selftest`、`deploy_contract` 和 `release_inputs_contract` 的真实命令与退出码。未执行的 PHP、Docker、Caddy、MySQL、HTTP、浏览器、并发和回滚不写为通过。

## 手工与页面证据

当前没有服务器、浏览器、数据库或 Caddy 真实证据。预留证据必须包含：主机指纹匹配（不含密钥内容）、Caddy/Beszel/80/443 快照、Docker/Compose/镜像摘要、secret owner/group/mode/size、数据库与上传备份校验、固定 baseline 后三组 v1 迁移的实际表/索引、`sxo_config` 台账和幂等重跑结果、FPM socket 权限、回环 88 响应、拒绝旁路和性能原始结果路径。输出需脱敏。

## 已知限制

- remote execution 尚未运行；目标环境事实需要每次发布前重新核验。
- HMAC secret 的值不可读取或记录；只能证明外部文件元数据和幂等保留行为。
- 收藏、询价、行为上报、30 日趋势和导出性能依赖后续功能/夹具，未具备时必须分别记 blocked/not_run。
- 本证据不能作为 release approval 或部署成功证明；审批、release seal 和真实服务器测试仍是后续门禁。

## 回滚证据

尚未执行远程写操作，因此没有回滚结果。实际发布必须先保存 Caddyfile/Compose、数据库、上传、配置和插件备份，再在失败时执行合同 rollback actions，并记录每个动作的退出码、恢复哈希和共享服务健康结果。

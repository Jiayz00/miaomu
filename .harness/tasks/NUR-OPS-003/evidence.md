# NUR-OPS-003 实施证据

## 验收标准映射

- `AC-TASK-001`：待实现并由新版 `deployment_contract` 验证 app/db 两服务、FPM 回环、MySQL 内部网络和容器安全合同。
- `AC-TASK-002`：待实现并验证 `deploy/Caddyfile.miaomu`、只读挂载合同、PHP 入口白名单与共享 Caddy 回滚边界。
- `AC-TASK-003`：待更新性能基线文档；所有真实性能场景保持 `not_run`。

## 自动测试证据

当前任务已退回 `ready_for_analysis`，旧 Nginx 三服务计划及其 verify contract 全部失效。新版计划尚未 preflight、实施或 verify，因此本节没有可声明为通过的 `VERIFY_CONTRACT_SHA256`、`TEST_COMMAND` 或 `TEST_RESULT`。

## 手工与页面证据

当前只有需求、服务器只读盘点和新架构规划事实；没有页面、容器、Caddy、数据库、HTTP、浏览器或性能通过证据。服务器盘点不属于本 L3 离线任务的验收结果。

## 已知限制

- 本机缺少 Docker、PHP、Composer、MySQL 和 Caddy。
- `127.0.0.1:19000`、Caddy 文件/挂载路径和实际 Compose 语义必须由后续 L4 任务锁定并验证。
- HTTP `:88` 只能用于临时验收；登录和用户会话最终需要独立 HTTPS 域名。

## 回滚证据

尚未实施，无回滚演练。NUR-OPS-003 只允许回滚仓库内 `deploy/**`、`docs/operations/**` 和 `tests/ops/**`；任何服务器或共享 Caddy 回滚都属于 NUR-OPS-001。

# NUR-OPS-002 测试计划

## 自动测试

- `harness_selftest`：运行 `python scripts/harness_selftest.py`，预期 45 项 Harness 回归通过；平台不支持的符号链接测试可明确 skip，不转成 pass 证据。
- `deployment_contract`：运行 `python tests/ops/test_deployment_contract.py`，预期验证授权文件、结构化策略、端口 88、内部数据库、健康检查、资源限制、固定版本、非 root、Watchtower 禁用、Docker socket 禁止、持久化、文档章节和敏感信息扫描，退出码 0。
- 自动测试不得联网、安装依赖、调用 Docker daemon、修改工作区或访问服务器。

## 手工验收

1. 将 `deploy/compose.yaml` 通过 stdin 交给目标服务器 Docker Compose 5.1.3 的 `config --quiet`，预期退出码 0；命令不得包含 `up`、`build`、`pull` 或写文件操作。
2. 展开 Compose 规范结果，确认唯一宿主机端口为 88，数据库无宿主机端口，所有服务均带健康检查、资源限制和 Watchtower 禁用标签。
3. 检查服务、网络、卷、容器名不与 `caddy`、`beszel-monitoring` 冲突；前后 `docker ps` 与 `ss -ltnp` 必须无变化。
4. 检查 Nginx document root 为 `public/`，仅明确前端/后台/API入口进入 FPM，`install.php` 和上传目录 PHP 执行被拒绝；检查应用健康脚本验证必需扩展、写目录和只读数据库 `SELECT 1`。
5. 检查文档明确区分本任务的静态制品与 L4 部署步骤，没有把未运行命令或未来业务性能写成通过。
6. 审查 Git diff 和敏感信息扫描，只允许授权路径且无密钥、口令、私钥、生产配置或完整连接串。

## 数据与权限

本任务不连接数据库、不处理用户、收藏、询价或统计数据。测试只验证 MySQL 不发布宿主机端口、持久化和备份合同存在。PV/UV、用户隔离和历史数据由后续业务任务验证，不在环境静态测试中冒充覆盖。

## 未覆盖项

- Windows 本机没有 Docker、PHP、Composer 和 MySQL，不能执行构建、容器健康检查或应用启动；由 `NUR-OPS-001` 在测试服务器补测。
- 本任务不拉取镜像，镜像实际摘要必须在实施时从公开 registry/服务器只读元数据核验后记录；未核验不得通过合同测试。
- 不执行数据库初始化、备份恢复、端口 88 HTTP、浏览器、性能或回滚演练；这些属于 L4 部署及后续功能任务。
- ShopXO 真实运行数据夹具尚未建立，`NFR-PERF-005` 的业务场景结果不能在本任务完成，只固定测量协议和补测责任。

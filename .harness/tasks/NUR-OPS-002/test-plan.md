# NUR-OPS-002 测试计划

## 自动测试

- `harness_selftest`：运行 `python scripts/harness_selftest.py`，预期 45 项 Harness 回归通过；平台不支持的符号链接测试可明确 skip，不转成 pass 证据。
- `deployment_contract`：运行 `python tests/ops/test_deployment_contract.py`，预期验证授权文件、结构化策略、端口 88、内部数据库、健康检查、资源限制、固定版本、非 root、Watchtower 禁用、Docker socket 禁止、持久化、文档章节和敏感信息扫描，退出码 0。
- 自动测试不得联网、安装依赖、调用 Docker daemon、修改工作区或访问服务器。

## 手工验收

1. 离线检查 Compose 文本和结构化策略，确认设计中的唯一宿主机端口为 88，数据库/FPM 无宿主机端口，所有服务均声明健康检查、资源限制和 Watchtower 禁用标签。
2. 检查服务、网络、卷和容器名使用 `miaomu` 命名空间，并确认文档禁止把 `caddy`、`beszel-monitoring` 加入苗木网络。
3. 检查 Nginx document root 为 `public/`，仅明确前端/后台/API 入口进入 FPM，`install.php` 和上传目录 PHP 执行被拒绝；检查应用健康脚本声明验证必需扩展、写目录和只读数据库 `SELECT 1`。
4. 检查文档明确区分本任务的静态制品与 L4 部署步骤，没有把未运行命令、候选摘要或未来业务性能写成通过。
5. 审查 Git diff 和敏感信息扫描，只允许授权路径且无密钥、口令、私钥、生产配置或完整连接串。

## L4 交付验证（本任务不执行）

`NUR-OPS-001` 在取得独立 L4 审批后执行目标服务器 `docker compose config --quiet`、registry/目标架构摘要核验、构建、健康检查、`docker ps`/`ss` 前后对比和端口 88 冒烟，并在自己的 `evidence.md` 记录命令与退出码。`NUR-OPS-002` 只验证文档包含这些命令和判定标准，不把它们写成当前通过证据。

## 数据与权限

本任务不连接数据库、不处理用户、收藏、询价或统计数据。测试只验证 MySQL 不发布宿主机端口、持久化和备份合同存在。PV/UV、用户隔离和历史数据由后续业务任务验证，不在环境静态测试中冒充覆盖。

## 未覆盖项

- Windows 本机没有 Docker、PHP、Composer 和 MySQL，不能执行构建、容器健康检查或应用启动；由 `NUR-OPS-001` 在测试服务器补测。
- 本任务不访问 registry 或服务器；固定值只是候选 manifest-list digest。实际可解析性、`linux/amd64` 摘要和镜像 ID 必须由 `NUR-OPS-001` 核验，未核验不得作为运行通过证据。
- 不执行数据库初始化、备份恢复、端口 88 HTTP、浏览器、性能或回滚演练；这些属于 L4 部署及后续功能任务。
- ShopXO 真实运行数据夹具尚未建立，`NFR-PERF-005` 的业务场景结果不能在本任务完成，只固定测量协议和补测责任。

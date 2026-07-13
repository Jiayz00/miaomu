# NUR-OPS-001 测试计划

## 自动测试

- `harness_selftest`：运行 `python scripts/harness_selftest.py`，预期全部项目级门禁测试退出码 0。
- `deploy_contract`：运行 `python tests/ops/test_deployment_contract.py`，检查目标目录 `/root/jia/miaomu`、端口 88、非生产防护、仓库外敏感配置、备份/回滚步骤和禁止占位值，预期退出码 0。
- `compose_config`：运行 `docker compose -p miaomu -f deploy/compose.yaml config --quiet`，预期 Compose 配置可解析、无端口/卷/网络引用错误且退出码 0。
- `composer_validate`：通过 `docker compose ... exec -T app composer validate --no-check-publish --strict` 在应用容器执行，预期元数据和锁文件有效且退出码 0。
- `server_environment`：通过 `docker compose ... exec -T app php tests/ops/environment_check.php` 执行，检查容器 PHP 版本与扩展、`app/common.php` blob、可写目录边界、非生产标记和配置权限，预期退出码 0 且不输出凭据。

运行前另执行 `source-check` 和 `doctor --strict`。`source-check` 当前已通过；缺少 PHP/Composer 或远端运行环境未就绪仍记录 blocked，不计为测试通过。

## 手工验收

1. 由项目负责人确认服务器用途和无生产数据，记录云实例标识的脱敏证据；严格 SSH 主机校验已通过，后续连接不得自动接受指纹变化。
2. 以部署账号核对 `/root/jia/miaomu` 的提交与获批提交一致；应用运行账号不应拥有 SSH 私钥、全局系统目录或其他项目的写权限。
3. 发布前创建数据库、上传、配置和插件代码备份，记录文件存在性、大小、权限和校验值；在隔离测试位置完成一次恢复演练。
4. 启动实例后先从服务器本机访问 88 端口，再从外部浏览器访问 `http://38.12.21.18:88/`；预期返回 ShopXO 页面、无 PHP 堆栈或安装向导泄漏，静态资源无系统性 404。
5. 启动前后分别记录 `caddy`、`beszel`、`beszel-agent` 和 `beszel-watchtower` 的容器 ID、状态和端口；预期无重建、重启、端口或网络变化，苗木容器均带 Watchtower 禁用标签。
6. 检查 Web/PHP/MySQL 日志，无凭据、私钥、完整连接串或用户数据；检查 Git tracked files 和本任务证据，同样不得出现敏感值。
7. 对当前已存在的首页、商品列表和详情入口记录固定并发、样本数、预热规则、P50/P95/错误率和环境规格。尚未实现的收藏、询价、行为上报、30 日趋势和导出仅登记补测任务，不填造数据。
8. 执行一次应用版本回滚并重复本地/外部 88 端口冒烟，确认提交、配置、数据库和上传资源与回滚目标一致。

## 数据与权限

本任务不处理用户收藏、询价、PV/UV 或业务历史。测试库必须为空库或明确可丢弃的合成数据，禁止连接生产数据库。数据库端口不向公网开放，配置文件由运行账号最小权限读取，备份目录不在 Web root 且不可被匿名下载。任务无 migration；若只初始化测试库，应核对 schema 来自固定上游并在清理/回滚后验证数据库状态。

## 未覆盖项

- 当前 Windows 主机没有 PHP、Composer 和 MySQL；本地严格 doctor 为 blocked，Composer/PHP 业务检查改在目标应用容器执行。
- `38.12.21.18:22`、主机指纹、Ubuntu/Docker/Compose 与目录/端口事实已只读核验；`88` 尚未监听，必须等获批 Compose 栈启动后补测。
- 服务器是否非生产尚待 `Jiayz00` 明确确认；未确认前禁止远端写操作。
- 收藏、询价、行为上报、后台 30 日趋势和导出尚未实现，不能在本任务给出性能通过结论；对应功能任务必须在实现后补齐 `NFR-PERF-005` 证据。
- L4 release_approver 尚未指定，任务不能进入有效计划审批或 preflight。

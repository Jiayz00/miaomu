# NUR-OPS-001 测试计划

## 自动测试

- `harness_selftest`：`python scripts/harness_selftest.py`，验证项目 Harness、审批、范围、证据和状态恢复门禁。
- `harness_remote_selftest`：`python scripts/harness_remote_selftest.py`，用替身 transport 验证主机指纹、外部 SSH 文件引用、受管路径、动作白名单、输出脱敏、超时和 release seal；不得联网。
- `deploy_contract`：`python tests/ops/test_deployment_contract.py`，检查两服务 Compose、PHP `intl`/Normalizer、HMAC secret、FPM socket、Caddy 只读挂载、端口 88、备份和回滚合同。
- `release_inputs_contract`：`python deploy/validate_release_inputs.py --contract-only`，检查 release manifest、镜像固定策略、外部配置路径和恢复边界；不读取 secret 内容。

验证前先运行 `source-check`、`task-check` 和 `plan-check`。命令必须由 Harness 无 shell 执行并保存退出码；本地缺少 Docker/PHP/Composer 时只能记录 blocked，不得改写为通过。

## 手工验收

1. **主机与共享服务**：通过 `inventory_*`、`inspect_*`、`hash_*` 和 `smoke_supervise_before` 记录 Ubuntu/Docker/Compose、Caddy v2.11.2、容器 ID/镜像/网络/挂载、Beszel、80/443/8090、88 和 Caddy 配置快照；确认目标为非生产。
2. **发布与镜像**：确认 release SHA 与 release seal 一致；运行 Compose config、Dockerfile 构建、Composer validate/platform check、PHP lint 和 `environment_check.php --all`。确认 `intl` 与 `Normalizer` 可用，应用不以 root 常驻，不挂 Docker socket。
3. **secret 与权限**：只检查 database.php、HMAC 文件、generated event 的存在性、owner/group/mode/size 和不可被 Web 访问；禁止输出内容。验证 HMAC 已有文件不被覆盖，变更值会明确阻断历史解密风险。
4. **数据库、迁移与权限边界**：确认数据库无宿主机端口，仅 internal backend；备份后在空/可丢弃库导入固定基线，运行 `initialize_nursery` 的 catalog/favorite/inquiry v1 前向迁移，核验五类表/索引和 `sxo_config` 台账、重复执行幂等及失败关闭；清除样例交易/个人数据、禁用 id=1 超管 token，创建非 1 的最小权限管理员，并证明安装器、SQL 控制台、在线升级、插件/主题上传、订单/支付路由不可达。
5. **Caddy 与 FPM**：先运行候选 validate，再按合同只 recreate `jia-caddy`；确认 Caddy 仅只读挂载 public、uploads、FPM socket，supplemental group 10001，downloads/runtime/config/secrets 不挂载。验证 FPM socket group/mode、无 TCP listener、唯一入口 index/admin/api、`/download/**` 和 PHP 旁路拒绝。
6. **HTTP/浏览器**：运行首页、`admin.php`、`api.php`、查询参数、静态资源和上传媒体的回环冒烟；确认 `http://38.12.21.18:88` 不可达，supervise、80/443 和 Beszel 仍健康。浏览器验证只使用合成数据和临时账号，不记录 cookie、手机号或正文。
7. **备份/回滚**：保存数据库、uploads、配置、插件代码、Caddyfile/Compose 和镜像身份备份；在隔离位置检查恢复可读性。故障时执行合同 rollback actions，再重复共享服务和 88 冒烟。
8. **性能基线**：固定 Git/Caddy/PHP/MySQL/配置哈希、数据集规模、预热、并发、样本数和超时，记录 P50/P95/错误率和原始结果路径。商品列表、详情已有入口可真实测量；收藏、询价、行为上报、后台 30 日趋势、导出若缺少夹具或页面，分别记 `blocked`/`not_run` 并登记后续任务。

## 数据与权限

本任务只操作非生产测试数据，不读取生产数据库，不处理真实用户收藏/询价历史。数据库备份目录不在 Web root；secret 通过 `/etc/miaomu` 和 `/etc/miaomu-restore` 外部文件注入，应用只能读取所需 secret。所有管理员路由检查必须使用最小权限测试账号，并清理测试账号、token、cookie 和日志中的个人数据。

## 未覆盖项

- 本地 Windows 工具链和 Docker daemon 的可用性不等同于服务器通过；服务器命令尚未执行前统一记 `not_run`。
- 远程 HTTP/浏览器、真实并发、MySQL 备份恢复、Caddy reload/recreate 和公网 :88 探测必须由 L4 broker 后续补证。
- 收藏/询价/行为/趋势/导出性能基线依赖对应功能和合成数据夹具；不能用静态合同测试替代。
- 若主机、Caddy 路径、socket GID/mode、卷布局、镜像摘要或任一 v1 migration 的实际 schema 与合同不一致，任务必须阻塞并重新计划。

# NUR-OPS-003 测试计划

## 自动测试

- harness_selftest：运行 python scripts/harness_selftest.py，验证 Harness 范围、审批、证据、远程合同和状态恢复门禁；平台不支持的符号链接测试只记 skip，不转成 pass。
- harness_remote_selftest：运行 python scripts/harness_remote_selftest.py，以替身 runner 离线验证主机指纹、外部 SSH 引用、精确动作、只读/变更状态、敏感输出脱敏、超时和输出上限，禁止真实网络。
- deployment_contract：运行 python tests/ops/test_deployment_contract.py，离线检查 app/db Compose、应用 Dockerfile、Caddy 片段、配置样例、发布输入校验器和四份运维文档，退出码应为 0。
- 自动测试不得联网、安装依赖、调用 Docker daemon、访问服务器、读取密钥或修改业务/Harness 控制面。

## 离线合同断言

1. 服务拓扑：
   - Compose 长期服务集合恰为 app、db；允许独立 verify profile 的一次性检查目标，但不得出现 web 长期服务。
   - 仓库不存在 deploy/docker/web、Nginx 配置、Nginx 镜像、MIAOMU_NGINX_IMAGE 或 edge 网络。
   - app 与 db 只加入 internal backend；db 无 ports，app 只允许 127.0.0.1:19000:9000。
2. Caddy 接入：
   - deploy/Caddyfile.miaomu 与 deploy/caddy-mounts.json 明确使用现有 Caddy v2.11.2、独立 :88、root /var/www/html/public 和 FastCGI 127.0.0.1:19000。
   - 片段包含 file_server，唯一 PHP 入口为 index.php、admin.php、api.php；拒绝 install.php、core.php、router.php、Ace demo PHP、大小写、php[0-9]*、phtml、phar、path-info、隐藏/敏感路径和 upload/download/storage 脚本。
   - 片段不包含 80、443、TLS、现有域名、真实凭据或 Caddy 镜像拉取/升级。
   - 挂载合同只允许 Caddy 只读访问部署 public、uploads 与 downloads，不允许 runtime、数据库、config 或 secret。
3. 容器安全：
   - app 非 root、read_only、cap_drop、no-new-privileges、资源/日志限制、Watchtower 禁用且无 Docker socket。
   - db 无宿主机端口，backend internal；MySQL root bootstrap 例外和稳态降权责任明确。
   - PHP、Composer、MySQL 使用固定候选 tag+digest，禁止 latest；Caddy 只记录外部现有版本。
4. 配置与身份：
   - MySQL 使用 _FILE，database.php.example 只从 /run/secrets/mysql_app_password 读取口令。
   - 实际 config/secret 路径位于 /etc/miaomu，缺失和空文件失败关闭，database.php 模板哈希进入 L4 release manifest。
   - 主项目固定 miaomu；恢复项目需要显式独立 project、回环端口、config 和 secret，命令不得硬编码 -p miaomu 覆盖恢复名称。
5. L4 入口：
   - Composer 严格检查运行在含 Composer 的 build/verify target，而非精简运行镜像。
   - 应用镜像包含真实环境检查入口，路径与 NUR-OPS-001 required_tests 一致。
   - 文档明确 Caddy validate、reload/recreate、Docker、数据库、88 冒烟、备份和性能均为 NUR-OPS-001 not_run。

## 手工验收

NUR-OPS-001 必须在独立 Codex 角色审批和锁定 remote_execution 后执行：

1. 目标服务器 Caddy v2.11.2、host network、配置/Compose 路径、镜像 ID、挂载与 80/443 基线复核。
2. PHP、Composer、MySQL registry/平台摘要与镜像内版本核验，Compose config 和发布输入校验。
3. app 构建、Composer strict/platform 检查、运行镜像无 Composer、容器环境检查和数据库 readiness。
4. 127.0.0.1:19000 FastCGI 可达、非回环不可达、MySQL 无宿主机端口。
5. 保存原 Caddyfile、共享 Compose、docker inspect、挂载、端口和 supervise 健康快照；验证完整候选配置。新增挂载时只 recreate jia-caddy，只有三个挂载已存在且仅配置变化时才允许 reload。
6. 首页、后台、API、静态资源和媒体的 :88 无真实账号/个人数据冒烟；验证查询参数保留、FastCGI SCRIPT_FILENAME，并逐项拒绝 install.php、core.php、router.php、Ace demo PHP、大小写、php[0-9]*、phtml、phar、path-info 和媒体脚本。
7. https://supervise.jiayyy.cn 在变更前、变更后及回滚后均通过；80/443 既有路由、Beszel、共享网络/卷/容器无非预期变化。
8. 数据库、uploads、downloads、配置、镜像身份和 Caddy 配置的备份及隔离恢复。
9. 性能协议的真实执行或对尚未实现的七类场景记录 blocked/not_run。

每一项必须记录真实命令、退出码、环境指纹和脱敏结果。静态测试、Caddy 片段存在或 Docker 容器启动不能替代这些证据。

## 数据与权限

本任务不连接数据库、不处理用户、收藏、询价或统计数据，也不改变权限。测试只验证 MySQL 不发布宿主机端口、配置从仓库外 secret 注入、Caddy 媒体挂载只读、持久化和备份合同存在。用户隔离、历史语义和 PV/UV 由后续业务任务真实验证。

恢复合同必须保证不同 project、卷、FastCGI 回环端口、database.php 和 secrets；恢复环境默认不接入共享 Caddy。若需页面抽样，必须由 NUR-OPS-001 另行锁定仅回环的临时验证入口，不能复用主 :88 或主媒体卷。

## 性能协议覆盖

文档必须定义包含 Caddy 版本/配置哈希的环境指纹、数据集版本、预热、并发、样本数、P50、P95、错误率和原始结果保存方式，并分别列出商品列表、商品详情、收藏、询价、行为上报、后台 30 日趋势、数据导出的补测负责人和前置条件。未实现或未执行场景只能标记 blocked/not_run。

## 未覆盖项

- 本机缺少 Docker、PHP、Composer、MySQL 和 Caddy，不能执行 Compose/Caddy 解析、构建或应用启动。
- 本任务不访问 registry/服务器；候选 digest、Caddy 容器身份、目标架构摘要、镜像 ID、挂载、19000 与 88 端口状态未由本任务验证。
- 不执行数据库、Caddy reload/recreate、备份恢复、浏览器、HTTP、性能或服务器回滚演练；这些属于 NUR-OPS-001。
- 当前 owner/reviewer 已切换为 Codex-Implementer 与 Codex-Review；旧 Jiayz00 审批已由回退到 ready_for_analysis 的历史事件失效，后续必须重新完成独立 Codex 审查。
- 明文 :88 仅用于受控临时验收；真实用户登录、收藏、询价和个人数据流程在 TLS 域名完成前保持未验收。

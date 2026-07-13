# NUR-OPS-003 测试计划

## 自动测试

- harness_selftest：运行 python scripts/harness_selftest.py，验证 Harness 范围、审批、证据、远程合同和状态恢复门禁；平台不支持的符号链接测试只记 skip，不转成 pass。
- harness_remote_selftest：运行 python scripts/harness_remote_selftest.py，以替身 runner 离线验证主机指纹、外部 SSH 引用、精确动作、只读/变更状态、敏感输出脱敏、超时和输出上限，禁止真实网络。
- deployment_contract：运行 python tests/ops/test_deployment_contract.py，离线检查 app/db Compose、应用 Dockerfile、Caddy 片段、配置样例、发布输入校验器和四份运维文档，退出码应为 0。
- 自动测试不得联网、安装依赖、调用 Docker daemon、访问服务器、读取密钥或修改业务/Harness 控制面。

## 离线合同断言

1. 服务拓扑：
   - Compose 使用 JSON-compatible YAML，由 Python `json` 标准库拒绝重复键并结构化解析；长期服务集合恰为 app、db，不得出现 web 长期服务。
   - 仓库不存在 deploy/docker/web、Nginx 配置、Nginx 镜像、MIAOMU_NGINX_IMAGE 或 edge 网络。
   - app 与 db 只加入 internal backend；db 无 ports，app 只允许 127.0.0.1:19000:9000。
2. Caddy 接入：
   - deploy/Caddyfile.miaomu 与 deploy/caddy-mounts.json 明确使用现有 Caddy v2.11.2、独立 127.0.0.1:88、root /var/www/html/public 和 FastCGI 127.0.0.1:19000；公网 :88 不得监听。
   - 片段包含 file_server，唯一 PHP 入口为 index.php、admin.php、api.php；在 file_server 前拒绝整个 `/download/**`，并拒绝 install.php、core.php、router.php、Ace demo PHP、大小写、php[0-9]*、phtml、phar、path-info、隐藏/敏感路径和 upload/storage 脚本。
   - 片段不包含 80、443、TLS、现有域名、真实凭据或 Caddy 镜像拉取/升级。
   - 挂载合同只允许 Caddy 只读访问部署 public 与 uploads；downloads、runtime、数据库、config 和 secret 均不得挂载。
3. 容器安全：
   - app 非 root、read_only、cap_drop、no-new-privileges、资源/日志限制、Watchtower 禁用且无 Docker socket。
   - db 无宿主机端口，backend internal；MySQL root bootstrap 例外和稳态降权责任明确。
   - PHP、Composer、MySQL 使用固定候选 tag+digest，禁止 latest；Caddy 只记录外部现有版本。
4. 配置与身份：
   - MySQL 使用 _FILE，database.php.example 只从 /run/secrets/mysql_app_password 读取口令。
   - 实际 config/secret 路径位于 /etc/miaomu，缺失和空文件失败关闭，database.php 模板哈希进入 L4 release manifest；L4 只检查 secret 的 owner/mode/size 元数据，不读取或输出内容。
   - 主项目固定 miaomu；恢复项目需要显式独立 project、回环端口、config 和 secret，命令不得硬编码 -p miaomu 覆盖恢复名称。
5. L4 入口：
   - Composer 严格检查运行在含 Composer 的 build/verify target，而非精简运行镜像。
   - 应用镜像包含真实环境检查入口，路径与 NUR-OPS-001 required_tests 一致。
   - PHP-FPM 包含只对 fpm-fcgi 生效的 prepend guard；规范化后的 SCRIPT_FILENAME 仅允许三个入口并拒绝 PATH_INFO，CLI 检查不被误拦截。
   - 文档明确 Caddy validate、reload/recreate、Docker、数据库、88 冒烟、备份和性能均为 NUR-OPS-001 not_run。
   - 文档明确 downloads 是 app 私有生成区，Caddy 不挂载并拒绝整个路径；internal backend 默认无外部网络。
6. 负变异：
   - 额外服务、db ports、0.0.0.0 FPM、root app、read_only=false、Docker socket、主/恢复卷或 19000 冲突必须失败。
   - 移除 FPM guard、扩大 Caddy PHP matcher、删除大小写/扩展/path-info/媒体拒绝或把 file_server 放到 deny 前必须失败。
   - 使用浏览器安装器、MySQL 自动导入完整 SQL、未清除样例数据、id=1/role_id=1 仍启用、危险后台 action 可达、在初始化完成前启动 88 或把 downloads 挂入 Caddy必须失败。

## 手工验收

NUR-OPS-001 必须在独立 Codex 角色审批和锁定 remote_execution 后执行：

1. 目标服务器 Caddy v2.11.2、host network、配置/Compose 路径、镜像 ID、挂载与 80/443 基线复核。
2. PHP、Composer、MySQL registry/平台摘要与镜像内版本核验，Compose config 和发布输入校验。
3. app 构建、Composer strict/platform 检查、运行镜像无 Composer、容器环境检查和数据库 readiness；直接 FastCGI 负例证明 FPM guard 不能被同机请求绕过。
4. 127.0.0.1:19000 FastCGI 可达、非回环不可达、MySQL 无宿主机端口。
5. 证明空库，离线导入完整基线，清除样例用户/订单/支付/消息/日志/Session 数据，通过非 argv/日志输入重置 `common_data_encryption_secret`，清空并禁用 id=1，创建 id/role 均不为 1 的最小权限管理员。用该账号逐项证明 SQL 控制台、插件/主题安装上传、在线升级、路由/配置写入、订单和支付 action 不可达；不得使用浏览器安装器。
6. 保存原 Caddyfile、共享 Compose、docker inspect、挂载、端口和 supervise 健康快照；验证完整候选配置。新增 public/uploads 挂载时只 recreate jia-caddy，只有两个挂载已存在且仅配置变化时才允许 reload。
7. 首页、后台、API、静态资源和上传媒体的 127.0.0.1:88 无真实账号/个人数据冒烟；证明 38.12.21.18:88 未监听/不可达，验证查询参数保留、FastCGI SCRIPT_FILENAME，并逐项拒绝 `/download/**`、install.php、core.php、router.php、Ace demo PHP、大小写、php[0-9]*、phtml、phar、path-info 和上传目录脚本。
8. https://supervise.jiayyy.cn 在变更前、变更后及回滚后均通过；80/443 既有路由、Beszel、共享网络/卷/容器无非预期变化。
9. 数据库、uploads、downloads、配置、镜像身份和 Caddy 配置的备份及隔离恢复；不恢复 runtime 缓存或旧 Session。
10. 性能协议的真实执行或对尚未实现的七类场景记录 blocked/not_run。

每一项必须记录真实命令、退出码、环境指纹和脱敏结果。静态测试、Caddy 片段存在或 Docker 容器启动不能替代这些证据。

## 数据与权限

本任务不连接数据库、不处理用户、收藏、询价或统计数据，也不改变权限。测试只验证 MySQL 不发布宿主机端口、配置从仓库外 secret 注入、Caddy 仅挂 public/uploads、downloads 隔离、持久化和备份合同存在，并要求 L4 真实验证最小管理员。用户隔离、历史语义和 PV/UV 由后续业务任务真实验证。

恢复合同必须保证不同 project、卷、FastCGI 回环端口、database.php 和 secrets；恢复环境默认不接入共享 Caddy。若需页面抽样，必须由 NUR-OPS-001 另行锁定仅回环的临时验证入口，不能复用主 :88 或主媒体卷。

## 性能协议覆盖

文档必须定义包含 Caddy 版本/配置哈希的环境指纹、数据集版本、预热、并发、样本数、P50、P95、错误率和原始结果保存方式，并分别列出商品列表、商品详情、收藏、询价、行为上报、后台 30 日趋势、数据导出的补测负责人和前置条件。未实现或未执行场景只能标记 blocked/not_run。

## 未覆盖项

- 本机缺少 Docker、PHP、Composer、MySQL 和 Caddy，不能执行 Compose/Caddy 解析、构建或应用启动。
- 本任务不访问 registry/服务器；候选 digest、Caddy 容器身份、目标架构摘要、镜像 ID、挂载、19000 与 88 端口状态未由本任务验证。
- 不执行数据库、Caddy reload/recreate、备份恢复、浏览器、HTTP、性能或服务器回滚演练；这些属于 NUR-OPS-001。
- 当前 owner/reviewer 已切换为 Codex-Implementer 与 Codex-Review；旧 Jiayz00 审批已由回退到 ready_for_analysis 的历史事件失效，后续必须重新完成独立 Codex 审查。
- 回环 127.0.0.1:88 仅用于服务器内临时验收；公网 :88 必须不可达，真实用户登录、收藏、询价和个人数据流程在 TLS 域名完成前保持未验收。

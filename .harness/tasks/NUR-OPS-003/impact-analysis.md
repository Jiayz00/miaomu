# NUR-OPS-003 影响分析

## 需求与当前事实

任务关联 NFR-SEC-006、NFR-PERF-005。ShopXO 固定为 6.9.0、上游提交 d1825c5404054b535255d8fcad675a5dae0ab633，完整源码基线为 846eb6a1cf7f94415ae9ae4c3eefb87d4fa9da3e，source-check 已通过。源码核验确认最低 PHP 8.0.2，安全 document root 为 public/，HTTP 入口为 public/index.php、public/admin.php、public/api.php。

当前本机没有 PHP、Composer、Docker 或 MySQL，自动门禁只能使用 Python 3.11 标准库。项目负责人已确认目标服务器现有 Caddy v2.11.2 使用 host network，必须复用；端口 88 当前空闲并只用于回环验收，最终部署根为 /root/jia/miaomu。服务器事实和 Caddy 文件/挂载身份仍由 NUR-OPS-001 在任何写操作前重新核验。

源码和锁文件要求 curl、GD、mbstring、PDO/PDO MySQL、Zip、Fileinfo、iconv、ctype、json、filter、hash、libxml、DOM、SimpleXML、XML、XMLReader、XMLWriter、zlib，并需保证 fsockopen 可用。稳态写路径候选为 runtime、public/static/upload、public/download；public/storage 当前不启用，无法确认的目录不得通过全源码可写规避。

源码进一步核验确认 `public/download` 会生成订单取货码、二维码、小程序包和 `sensitive_data` 图片，不能作为匿名静态面。首版不把 downloads 卷挂入 Caddy并拒绝整个 `/download/**`；需要鉴权的 producer 以后迁出 public 或改为受权控制器下载。ShopXO 的域名、默认首页、favicon、路由、插件、主题和在线升级等后台动作会写 `config/`、`app/` 或 `public/`；只读运行合同要求后续业务收敛任务关闭对应菜单、路由和权限，而不是临时把整棵源码改为可写。

`config/shopxo.sql` 是包含固定 id=1/role_id=1 超管和历史记录的完整 dump，不是纯 schema；ShopXO 会给 id=1 或 role_id=1 无条件加载全部权限。NUR-OPS-001 只能在证明空库后离线导入，在非公开阶段清除样例交易/用户/日志数据，重置 `common_data_encryption_secret`，清空并禁用 id=1，创建 id/role 均不为 1 的最小权限管理员并验证危险 action 不可达后再启动回环 `:88`；不得使用浏览器安装器或 `/docker-entrypoint-initdb.d` 自动导入。

旧方案中的 Nginx stable-alpine、web 容器、edge 网络和 Compose 88:8080 发布与最新架构冲突，全部失效。候选镜像只保留 PHP 8.2 FPM、Composer 2.8 和 MySQL 8.0；现有 Caddy 不由本项目构建、拉取或升级，其版本、镜像 ID 和配置哈希由 NUR-OPS-001 记录。

## 当前调用链与数据

目标运行链路为：

    server-local smoke
        -> existing host-network Caddy 127.0.0.1:88
        -> /run/miaomu-fpm/php-fpm.sock
        -> app PHP-FPM :9000
        -> internal backend
        -> db MySQL :3306

Compose 只管理 app 与 db：

- app 与 db 加入 internal backend。
- app 不声明 `ports` 或宿主机 TCP listener；FPM 只在 `miaomu_fpm_socket` 命名卷内创建 `/run/miaomu-fpm/php-fpm.sock`，group 10001、mode 0660。
- db 不发布任何宿主机端口。
- Caddy 保持 host network，不加入 backend，也不由 miaomu Compose 管理；共享 Caddy Compose 只读挂载 `miaomu_fpm_socket` 并增加 supplemental group 10001。
- app、db 不挂载 Docker socket，均声明资源、日志和 Watchtower 禁用策略。
- backend 使用 `internal: true`，展示栈默认没有外部网络；短信、邮件、远程图片抓取等能力不能现场放宽网络，必须进入后续获批出网合同。

Caddy 与 FPM 必须对脚本路径使用一致的 /var/www/html/public。NUR-OPS-001 需要让现有 Caddy 只读看到：

- /root/jia/miaomu/public 映射到 /var/www/html/public；
- miaomu 主项目的 uploads 卷映射到 /var/www/html/public/static/upload；
- miaomu 主项目的 `miaomu_fpm_socket` 卷映射到 /run/miaomu-fpm，并通过 group 10001 连接 socket；
- downloads 卷保持 app 私有，不进入 Caddy；Caddy 对 `/download/**` 直接拒绝。

app 对上传、下载卷可写，Caddy 只读看到 uploads；downloads、runtime 与数据库卷不进入 Caddy。恢复项目使用不同 project 和卷，默认不接入共享 Caddy，避免恢复操作覆盖正式测试栈。

回环 TCP 与 `auto_prepend_file` 不能构成安全边界：直接 FastCGI 客户端可尝试用 `PHP_VALUE`/`PHP_ADMIN_VALUE` 覆盖 guard。修订方案取消全部 FPM TCP 暴露，把 socket 命名卷和 supplemental group 10001 作为 listener-level 边界；只有 app 与 `jia-caddy` 能看到并连接 socket，恢复项目使用不同卷且默认不挂 Caddy。PHP-FPM 仍通过仅对 `fpm-fcgi` 生效的 prepend guard 对规范化后的 `SCRIPT_FILENAME` 做三入口白名单校验并拒绝 `PATH_INFO`，但只作为可信 Caddy 配置出错时的纵深防御。Caddy 不得把任何 HTTP 输入映射到 `PHP_VALUE` 或 `PHP_ADMIN_VALUE`，CLI 构建、维护和 L4 检查不受 guard 误拦截。

ShopXO 原生从 config/database.php 读取连接信息。仓库只提交 deploy/config/database.php.example；L4 在仓库外生成完整 /etc/miaomu/config/database.php 并只读挂载，该文件从 /run/secrets/mysql_app_password 读取口令。MySQL 使用 _FILE 变量。口令不进入 Compose 环境、Git、命令行或日志，也不修改仓库中的 config/database.php。

## Caddy 安全边界

版本化 Caddy 片段只描述独立 `127.0.0.1:88` 站点，不拥有现有 80/443 站点或 TLS。片段必须：

- root 指向 /var/www/html/public；
- FastCGI 指向 `unix//run/miaomu-fpm/php-fpm.sock`；
- 唯一允许进入 FPM 的入口是 index.php、admin.php、api.php；不得使用“等”扩大白名单；
- 拒绝 install.php、core.php、router.php、Ace demo 目录 PHP、隐藏文件和敏感配置路径；
- 拒绝大小写变体、php[0-9]*、phtml、phar、path-info、public/static/upload 与未来 storage 中的脚本执行；
- 在 file_server 之前拒绝整个 `/download/**`，只提供源码静态文件和 uploads 媒体。

实际合并 Caddyfile、增加现有 Caddy 容器挂载、validate、reload 或受控 recreate 均属于共享网关远程变更，只有 NUR-OPS-001 的 L4 remote_execution 可以执行。变更前必须保存原 Caddyfile、共享 Compose、docker inspect、挂载、端口及 https://supervise.jiayyy.cn 健康快照；变更后和回滚后必须再次验证 supervise。新增任何所需挂载时必须验证完整候选配置后只 recreate jia-caddy，只有挂载已齐全时才允许 reload。

## 影响范围

- 用户端、管理端和 API：本任务不启动服务，无运行行为变化。
- 数据库：无 schema 或数据操作；只设计内部 db、持久卷和备份合同。
- 共享网关：版本化新增 :88 片段、public/uploads/socket 三项只读挂载和 supplemental group 10001 要求，但本任务不修改 Caddy。
- 安全：移除新增 Web 容器和 FPM TCP listener；主要风险收敛为 socket 卷或 group 被额外容器获得、共享 Caddy 配置误改、媒体卷权限和脚本执行。
- 初始化：完整 SQL 数据清理、加密串重置、id=1 禁用和最小权限管理员创建是后续 L4 的受控一次性动作；本任务不执行，但必须把“未验证不得启动回环 88”固化为部署门禁。
- 性能：环境指纹改为 Caddy v2.11.2 + PHP-FPM + MySQL，不再记录 Nginx；仍不声明任何业务性能结果。
- 升级：PHP、Composer、MySQL 输入集中固定；Caddy 版本由共享服务管理，本项目不得在线升级。

## 方案比较

1. 配置：使用 127.0.0.1:88 独立 Caddy 站点、权限化 FastCGI Unix socket、内部数据库和最小只读挂载。
2. 现有服务：按用户要求复用现有 host-network Caddy v2.11.2，是回环验收和后续 TLS Web 层的唯一方案。
3. 新 Web 容器：Nginx、Apache 或第二个 Caddy 会重复网关、扩大镜像与端口面，且违反明确指令，禁止采用。
4. 插件钩子和 nursery 插件：环境任务不需要业务扩展点。
5. 独立模块：部署合同集中于 deploy/**、tests/ops/**、docs/operations/**。
6. 核心适配：无，不修改 ShopXO、vendor 或数据库。

宿主机直接安装 PHP/MySQL 会污染共享服务器；让 Caddy 加入 Compose 网络与其 host-network 事实冲突；发布 FPM TCP 或 MySQL 端口会扩大攻击面；新建第二 checkout 违反单目录约束，均不采用。

## 风险与边界

- Caddy 配置路径、Compose 路径、容器名、镜像 ID、挂载或 host-network 事实与计划不一致时，NUR-OPS-001 必须停止并重新批准计划。
- `miaomu_fpm_socket`、GID 10001 或 userns 映射冲突时不得临时改为 TCP、mode 0666 或共享现有 socket 卷；先重新锁定合同。
- :88 只绑定回环并用于无真实账号和个人数据的服务器内验收；公网 38.12.21.18:88 必须不可达，正式登录、收藏和询价必须等待独立 L4 TLS 域名方案。
- Caddy 无法以最小只读挂载访问 public 或 uploads 时，不得复制媒体到镜像或授予整棵源码写权限；downloads 始终不得挂载。
- Caddy validate 失败、80/443 路由发生变化、Beszel 被影响或回滚文件缺失时，不得 reload/recreate。
- 静态合同不能证明 Caddy 语法、镜像可构建、FPM 可达或应用可运行；全部由 L4 补证。
- 任何真实密钥、Docker socket、FPM TCP 端口、socket mode 0666、未授权容器挂载 socket 卷、宿主机 MySQL 端口、root 应用、全源码写权限或未拒绝脚本路径出现即失败。
- 当前 NUR-OPS-001 仍声明旧独立 Web 拓扑、`network_access_required=false` 且无 `remote_execution`；在其整体重写和独立审批前，本任务制品不得被用于服务器变更。

## 预计文件

- 重写 deploy/compose.yaml 与 deploy/stack-policy.json，仅保留 app/db 和 backend。
- 保留并修订 deploy/docker/app/**；删除 deploy/docker/web/**。
- 在现有 deploy/ 根新增 Caddyfile.miaomu 与 caddy-mounts.json，不创建新的部署子目录；挂载清单只含 public 与 uploads。
- 修订 deploy/validate_release_inputs.py 与 deploy/config/database.php.example 的离线合同。
- 重写 tests/ops/test_deployment_contract.py，并提供 NUR-OPS-001 所需的真实 Composer build-stage 与容器环境检查入口。
- Compose 使用 JSON-compatible YAML，使 Python 标准库能够结构化解析服务、网络、卷和 secret；真实 Compose 语义仍由 NUR-OPS-001 的 `docker compose config` 补证。
- 应用镜像增加仅限 FPM SAPI 的入口 guard、Dockerfile 专用 ignore 文件和不输出 secret 的环境/readiness 检查。
- 重写 docs/operations/LOCAL_STACK.md、DEPLOYMENT.md、BACKUP_RESTORE.md、PERFORMANCE_BASELINE.md。
- 不修改 ShopXO 业务代码、config/shopxo.sql、仓库中的 config/database.php、Harness 策略或核心登记。

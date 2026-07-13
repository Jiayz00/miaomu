# NUR-OPS-003 影响分析

## 需求与当前事实

任务关联 NFR-SEC-006、NFR-PERF-005。ShopXO 固定为 6.9.0、上游提交 d1825c5404054b535255d8fcad675a5dae0ab633，完整源码基线为 846eb6a1cf7f94415ae9ae4c3eefb87d4fa9da3e，source-check 已通过。源码核验确认最低 PHP 8.0.2，安全 document root 为 public/，HTTP 入口为 public/index.php、public/admin.php、public/api.php。

当前本机没有 PHP、Composer、Docker 或 MySQL，自动门禁只能使用 Python 3.11 标准库。项目负责人已确认目标服务器现有 Caddy v2.11.2 使用 host network，必须复用；公开端口 88 当前空闲，最终部署根为 /root/jia/miaomu。服务器事实和 Caddy 文件/挂载身份仍由 NUR-OPS-001 在任何写操作前重新核验。

源码和锁文件要求 curl、GD、mbstring、PDO/PDO MySQL、Zip、Fileinfo、iconv、ctype、json、filter、hash、libxml、DOM、SimpleXML、XML、XMLReader、XMLWriter、zlib，并需保证 fsockopen 可用。稳态写路径候选为 runtime、public/static/upload、public/download；public/storage 当前不启用，无法确认的目录不得通过全源码可写规避。

旧方案中的 Nginx stable-alpine、web 容器、edge 网络和 Compose 88:8080 发布与最新架构冲突，全部失效。候选镜像只保留 PHP 8.2 FPM、Composer 2.8 和 MySQL 8.0；现有 Caddy 不由本项目构建、拉取或升级，其版本、镜像 ID 和配置哈希由 NUR-OPS-001 记录。

## 当前调用链与数据

目标运行链路为：

    external client
        -> existing host-network Caddy :88
        -> 127.0.0.1:19000
        -> app PHP-FPM :9000
        -> internal backend
        -> db MySQL :3306

Compose 只管理 app 与 db：

- app 与 db 加入 internal backend。
- app 将 FPM 9000 仅发布到宿主机 127.0.0.1:19000；该端口是 FastCGI 接口，不是公共 HTTP。
- db 不发布任何宿主机端口。
- Caddy 保持 host network，不加入 backend，也不由 miaomu Compose 管理。
- app、db 不挂载 Docker socket，均声明资源、日志和 Watchtower 禁用策略。

Caddy 与 FPM 必须对脚本路径使用一致的 /var/www/html/public。NUR-OPS-001 需要让现有 Caddy 只读看到：

- /root/jia/miaomu/public 映射到 /var/www/html/public；
- miaomu 主项目的 uploads 卷映射到 /var/www/html/public/static/upload；
- miaomu 主项目的 downloads 卷映射到 /var/www/html/public/download。

app 对上传、下载卷可写，Caddy 对相同卷只读。runtime 与数据库卷不进入 Caddy。恢复项目使用不同 project 和卷，默认不接入共享 Caddy，避免恢复操作覆盖正式测试栈。

ShopXO 原生从 config/database.php 读取连接信息。仓库只提交 deploy/config/database.php.example；L4 在仓库外生成完整 /etc/miaomu/config/database.php 并只读挂载，该文件从 /run/secrets/mysql_app_password 读取口令。MySQL 使用 _FILE 变量。口令不进入 Compose 环境、Git、命令行或日志，也不修改仓库中的 config/database.php。

## Caddy 安全边界

版本化 Caddy 片段只描述独立 :88 站点，不拥有现有 80/443 站点或 TLS。片段必须：

- root 指向 /var/www/html/public；
- FastCGI 指向 127.0.0.1:19000；
- 唯一允许进入 FPM 的入口是 index.php、admin.php、api.php；不得使用“等”扩大白名单；
- 拒绝 install.php、core.php、router.php、Ace demo 目录 PHP、隐藏文件和敏感配置路径；
- 拒绝大小写变体、php[0-9]*、phtml、phar、path-info 以及 public/static/upload、public/download、未来 storage 中的脚本执行；
- 使用 Caddy file_server 提供静态文件和只读媒体。

实际合并 Caddyfile、增加现有 Caddy 容器挂载、validate、reload 或受控 recreate 均属于共享网关远程变更，只有 NUR-OPS-001 的 L4 remote_execution 可以执行。变更前必须保存原 Caddyfile、共享 Compose、docker inspect、挂载、端口及 https://supervise.jiayyy.cn 健康快照；变更后和回滚后必须再次验证 supervise。新增任何所需挂载时必须验证完整候选配置后只 recreate jia-caddy，只有挂载已齐全时才允许 reload。

## 影响范围

- 用户端、管理端和 API：本任务不启动服务，无运行行为变化。
- 数据库：无 schema 或数据操作；只设计内部 db、持久卷和备份合同。
- 共享网关：版本化新增 :88 片段与只读挂载要求，但本任务不修改 Caddy。
- 安全：移除新增 Web 容器，减少一个镜像和网络面；新增的主要风险是 FastCGI 回环暴露、共享 Caddy 配置误改、媒体卷权限和脚本执行。
- 性能：环境指纹改为 Caddy v2.11.2 + PHP-FPM + MySQL，不再记录 Nginx；仍不声明任何业务性能结果。
- 升级：PHP、Composer、MySQL 输入集中固定；Caddy 版本由共享服务管理，本项目不得在线升级。

## 方案比较

1. 配置：使用 :88 独立 Caddy 站点、回环 FastCGI、内部数据库和最小只读挂载。
2. 现有服务：按用户要求复用现有 host-network Caddy v2.11.2，是公开 Web 层的唯一方案。
3. 新 Web 容器：Nginx、Apache 或第二个 Caddy 会重复网关、扩大镜像与端口面，且违反明确指令，禁止采用。
4. 插件钩子和 nursery 插件：环境任务不需要业务扩展点。
5. 独立模块：部署合同集中于 deploy/**、tests/ops/**、docs/operations/**。
6. 核心适配：无，不修改 ShopXO、vendor 或数据库。

宿主机直接安装 PHP/MySQL 会污染共享服务器；让 Caddy加入 Compose 网络与其 host-network 事实冲突；公开 FPM 或 MySQL 会扩大攻击面；新建第二 checkout 违反单目录约束，均不采用。

## 风险与边界

- Caddy 配置路径、Compose 路径、容器名、镜像 ID、挂载或 host-network 事实与计划不一致时，NUR-OPS-001 必须停止并重新批准计划。
- 127.0.0.1:19000 被占用时不得临时改为公共地址或任意端口；先重新锁定合同。
- 明文 :88 只允许无真实账号和个人数据的受控验收；正式登录、收藏和询价必须等待独立 L4 TLS 域名方案。
- Caddy 无法以最小只读挂载访问 public、uploads 或 downloads 时，不得复制媒体到镜像或授予整棵源码写权限。
- Caddy validate 失败、80/443 路由发生变化、Beszel 被影响或回滚文件缺失时，不得 reload/recreate。
- 静态合同不能证明 Caddy 语法、镜像可构建、FPM 可达或应用可运行；全部由 L4 补证。
- 任何真实密钥、Docker socket、非回环 FPM、宿主机 MySQL 端口、root 应用、全源码写权限或未拒绝脚本路径出现即失败。

## 预计文件

- 重写 deploy/compose.yaml 与 deploy/stack-policy.json，仅保留 app/db 和 backend。
- 保留并修订 deploy/docker/app/**；删除 deploy/docker/web/**。
- 在现有 deploy/ 根新增 Caddyfile.miaomu 与 caddy-mounts.json，不创建新的部署子目录。
- 修订 deploy/validate_release_inputs.py 与 deploy/config/database.php.example 的离线合同。
- 重写 tests/ops/test_deployment_contract.py，并提供 NUR-OPS-001 所需的真实 Composer build-stage 与容器环境检查入口。
- 重写 docs/operations/LOCAL_STACK.md、DEPLOYMENT.md、BACKUP_RESTORE.md、PERFORMANCE_BASELINE.md。
- 不修改 ShopXO 业务代码、config/shopxo.sql、仓库中的 config/database.php、Harness 策略或核心登记。

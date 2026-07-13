# NUR-OPS-003 实施计划

## 实施步骤

1. 删除失效 Web 层。删除 deploy/docker/web/**，从 Compose、stack policy、发布输入校验器、测试和文档中移除 web 服务、Nginx 镜像、MIAOMU_NGINX_IMAGE、edge 网络、web 输出镜像和 88:8080 发布。不得保留兼容开关或 dormant Nginx 配置。
2. 固定 app 运行合同。使用 PHP 8.2-FPM，document root 为 public/；应用 Dockerfile 在 build stage 执行 Composer validate、install、platform check、PHP 扩展和 fsockopen 检查，运行阶段不保留 Composer/编译工具并使用非 root UID/GID 10001。源码只读，写路径限于 runtime、uploads 与 downloads。Dockerfile 专用 ignore 文件排除 Git、密钥、database.php、runtime、本地证据和控制状态；FPM 只监听 `/run/miaomu-fpm/php-fpm.sock`，socket group 10001、mode 0660。prepend guard 仅对 `fpm-fcgi` 生效，按真实路径二次限定三个入口并拒绝 PATH_INFO，但明确只作为纵深防御。
3. 定义 app/db 两服务 JSON-compatible Compose。app 与 db 只加入 internal backend；两者均无 `ports`，db 不发布端口，app 只挂载固定名称 `miaomu_fpm_socket` 到 `/run/miaomu-fpm`。两服务声明健康检查、资源限制、日志限制、read_only、capabilities、no-new-privileges 与 Watchtower 禁用，不挂 Docker socket。JSON 子集由标准库结构化测试，`docker compose config` 仍由 L4 真实执行。
4. 稳定共享卷名称。Compose 主项目固定为 miaomu；uploads 和 `miaomu_fpm_socket` 具有可由 Caddy 只读引用的确定名称，downloads 仅供 app 私有使用且不得挂入 Caddy。恢复项目必须使用不同 project、不同 uploads/downloads/runtime/db/socket 卷及独立 config/secrets；恢复 socket 卷默认不挂入 Caddy，不能仅依赖命令行 `-p` 覆盖。
5. 在现有 deploy/ 根编写 Caddyfile.miaomu 与 caddy-mounts.json，不创建新的部署子目录。它们只描述 `127.0.0.1:88` 回环站点以及 public、uploads、`miaomu_fpm_socket` 三个只读挂载；Caddy 增加 supplemental group 10001，root 为 `/var/www/html/public`，FastCGI 为 `unix//run/miaomu-fpm/php-fpm.sock`。唯一 PHP `SCRIPT_FILENAME` 为 index.php、admin.php、api.php，Caddy 不得把请求头、查询或环境映射为 `PHP_VALUE`/`PHP_ADMIN_VALUE`。必须在 file_server 前拒绝整个 `/download/**`，并拒绝 install.php、core.php、router.php、Ace demo PHP、大小写变体、php[0-9]*、phtml、phar、path-info 及 upload/storage 脚本。片段不得包含公网 :88、现有 80/443 站点、TLS 配置或服务器真实路径之外的共享配置。
6. 编写非敏感配置。Compose secrets 只引用 /etc/miaomu/secrets/**；MySQL 使用 _FILE。deploy/config/database.php.example 从 /run/secrets/mysql_app_password 读取口令并固定 db、miaomu、miaomu_app。L4 实际 database.php 必须与审计模板逐字节一致并只读挂载。Compose file secret 视为 bind mount：L4 只检查元数据与非零长度，要求宿主机 root:10001、0440，不读取或输出内容。
7. 集中候选镜像与发布输入。stack-policy 只记录 PHP、Composer、MySQL 候选 tag+digest 和 external Caddy v2.11.2 合同；validate_release_inputs.py 校验全限定镜像、Git SHA、主/恢复 project、主/恢复 socket 卷名、socket 路径/GID/mode、仓库外文件、release manifest 和 database.php 模板哈希，不宣称 registry 或 Caddy 已验证。
8. 提供 L4 可执行测试入口。Composer 严格校验必须在实际含 Composer 的 build stage 或一次性 verify target 运行；server environment 检查必须被复制到应用镜像固定路径，验证 PHP/扩展、Git revision、只读源码、可写目录、secret 元数据、socket 类型/owner/group/mode 和 sxo_config readiness。运行镜像不因测试保留 Composer，错误输出不得包含连接口令或数据库异常正文。
9. 固定离线初始化与权限门禁。不得把完整 `config/shopxo.sql` 放入 MySQL 自动初始化目录，也不得运行浏览器安装器。NUR-OPS-001 必须证明空库并受控导入，在启动 Caddy 前清除样例用户、订单、支付、消息、日志和 Session 数据，通过非 argv/日志输入重置 `common_data_encryption_secret`，清空 token 并禁用 id=1/role_id=1 超管，创建 id/role 均不为 1 的最小权限管理员。用该账号直接验证 `Sqlconsole/Implement`、插件与主题安装/上传、在线升级、路由/配置写入、订单和支付 action 均被拒绝后，才允许启动回环 :88。
10. 重写运维文档。LOCAL_STACK 记录两服务、internal 无出网和 Caddy 边界；DEPLOYMENT 记录 Caddy 备份、validate、最小挂载、reload/recreate、初始化门禁和回滚；BACKUP_RESTORE 纳入 Caddy 配置/Compose 哈希并保证恢复不接入主 Caddy、不恢复缓存/旧 Session；PERFORMANCE_BASELINE 用 Caddy 指纹替换 Nginx。明确 downloads 是 app 私有生成区，Caddy 不挂载并全路径拒绝。
11. 重写标准库离线测试。使用 json 结构化解析 Compose；检查无 Nginx/web/edge、app/db 均无 ports、FPM Unix socket 及二次 guard、MySQL 内部、Caddy 127.0.0.1:88 片段与拒绝顺序、public/uploads/socket 挂载、supplemental group 10001、downloads 隔离、project/socket 卷隔离、固定候选镜像、安全配置、真实 L4 测试入口和文档 not_run 边界。通过 mutation corpus 证明额外服务、任何 FPM/MySQL 端口、socket mode 0666、移除 group/卷隔离、映射 PHP_VALUE/PHP_ADMIN_VALUE、root、可写源码、放宽 PHP matcher、挂载 downloads 或保留超管等变异会失败。

## 验证顺序

1. python scripts/harness.py source-check。
2. python scripts/harness_selftest.py。
3. python scripts/harness_remote_selftest.py。
4. python tests/ops/test_deployment_contract.py。
5. 本地逐文件敏感信息检查、Nginx/Web 残留扫描和预期文件清单复核。
6. 进入 verifying 后运行 verify、scope-check、evidence-check 和 review-pack，记录真实退出码与限制。

Caddy validate、现有 Caddy Compose 解析、registry/目标架构核验、应用构建、容器健康、数据库初始化、Caddy 挂载/reload/recreate、端口 88 冒烟、备份恢复和性能测试全部由 NUR-OPS-001 执行。本任务不得把 Caddy 片段的文本检查写成真实 Caddy 通过。

## NUR-OPS-001 交付合同

NUR-OPS-001 必须消费本任务最终获批 Git SHA，不得在远端临时修改 Compose、Dockerfile、Caddy 片段或安全策略。它应在锁定 remote_execution 中依次：

1. 只读复核 Caddy v2.11.2、host network、配置/Compose 路径、容器与挂载、supplemental groups、80/443、Beszel、named volume/GID 10001 和 userns 映射事实。
2. 备份原 Caddyfile 与共享 Compose，记录 docker inspect、容器/镜像身份、挂载、端口和 https://supervise.jiayyy.cn 健康结果，并验证回滚副本。
3. 在执行前整体重写 NUR-OPS-001 为 L4、`network_access_required=true` 的 Caddy/FPM remote contract，重新完成 plan/release 审批并锁定本任务最终 Git SHA；旧独立 Web 计划不得复用。
4. 在 /root/jia/miaomu 部署精确提交，准备仓库外 config/secrets，构建 app 并启动 app/db。
5. 证明数据库为空后离线导入完整基线，清除全部样例用户/交易/日志/Session 数据，通过不进入 argv/日志的输入重置 `common_data_encryption_secret`；清空并禁用 id=1，创建 id/role 均不为 1 的最小权限管理员，验证 sxo_config 和危险 action 拒绝。不得使用浏览器安装器。
6. 完成 app readiness，确认宿主机与 app 均无 FPM TCP listener，socket 为 group 10001/mode 0660；无 socket 卷容器和普通宿主机用户连接失败，`jia-caddy` 连接成功。通过 HTTP 请求头/查询负例证明 `PHP_VALUE`/`PHP_ADMIN_VALUE` 不会进入 FastCGI 参数，并验证三个入口与 PATH_INFO guard。
7. 增加 public、uploads、`miaomu_fpm_socket` 三个只读挂载和 supplemental group 10001，合并独立 `127.0.0.1:88` 片段，使用现有镜像验证完整候选 Caddyfile 与共享 Compose；downloads 不得挂载。因为新增挂载/group，必须只 recreate jia-caddy，不对共享栈执行 down。只有 L4 证明三项挂载和 group 已存在且仅配置变化时才允许 reload。
8. 立即验证 https://supervise.jiayyy.cn、80/443 既有路由、Beszel、共享容器和日志无非预期变化，再执行 127.0.0.1:88 无真实账号/个人数据的入口、查询参数、SCRIPT_FILENAME 和拒绝旁路冒烟，并证明 38.12.21.18:88 未监听/不可达、`/download/**` 始终拒绝。
9. 任一门禁失败立即恢复原 Caddyfile、共享 Compose、挂载和既有服务身份（service、镜像、network、mount/config 哈希；不要求 recreate 后 container ID 不变），只 recreate jia-caddy，再次验证 supervise，然后停止 miaomu 服务；不得扩大修改范围。

若 L4 发现必须改变 socket 卷名/路径/GID/mode、Caddy 路径、挂载、Compose 拓扑、源码写路径或数据库结构，应阻塞 NUR-OPS-001 并建立新的离线合同修订，不能借远程任务直接修改本任务拥有的制品。

## 数据库与核心适配

无数据库结构或数据变更，无 ShopXO 核心适配。本任务不得运行 config/shopxo.sql，不得修改仓库中的 config/database.php。差异只允许位于 deploy/**、tests/ops/**、docs/operations/** 和任务生命周期制品。

## 失败处理与回滚

发现 Nginx/Web 残留、Caddy 公网 :88 或 80/443 配置进入版本化片段、真实密钥、网络访问、未固定镜像、任何 FPM TCP listener、socket mode 0666/额外挂载者/缺少 group 隔离、PHP_VALUE/PHP_ADMIN_VALUE 请求映射、数据库宿主机端口、Docker socket、root 应用、全源码写权限、安装器开放、downloads 挂入 Caddy、id=1/role_id=1 仍可登录或 L4 测试入口不存在时立即停止，不将缺口表述为通过。

本任务回滚只还原授权路径，不连接服务器或恢复 Caddy。回滚后运行 source-check、Harness 自检和 Nginx/Web 残留扫描。服务器和共享 Caddy 回滚只属于 NUR-OPS-001。

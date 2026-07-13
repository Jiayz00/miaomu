# NUR-OPS-003 实施计划

## 实施步骤

1. 删除失效 Web 层。删除 deploy/docker/web/**，从 Compose、stack policy、发布输入校验器、测试和文档中移除 web 服务、Nginx 镜像、MIAOMU_NGINX_IMAGE、edge 网络、web 输出镜像和 88:8080 发布。不得保留兼容开关或 dormant Nginx 配置。
2. 固定 app 运行合同。使用 PHP 8.2-FPM，document root 为 public/；应用 Dockerfile 在 build stage 执行 Composer validate、install、platform check、PHP 扩展和 fsockopen 检查，运行阶段不保留 Composer/编译工具并使用非 root UID。源码只读，写路径限于 runtime、uploads 与 downloads。
3. 定义 app/db 两服务 Compose。app 与 db 只加入 internal backend；app 的 9000 固定只绑定 127.0.0.1:19000，db 不发布端口。若 L4 发现 19000 占用则阻塞并重新审批，不现场换值。两服务声明健康检查、资源限制、日志限制、read_only、capabilities、no-new-privileges 与 Watchtower 禁用，不挂 Docker socket。
4. 稳定共享媒体卷名称。Compose project 继续参数化，主项目固定为 miaomu；上传和下载卷在主项目中具有可由 Caddy 只读引用的确定名称。恢复项目必须使用不同 project、不同卷、独立 config/secrets 和非 19000 回环端口，不能仅依赖命令行 -p 覆盖。
5. 在现有 deploy/ 根编写 Caddyfile.miaomu 与 caddy-mounts.json，不创建新的部署子目录。它们只描述受控临时 :88 站点和挂载清单：root /var/www/html/public，FastCGI 127.0.0.1:19000，静态 file_server；唯一 PHP 入口为 index.php、admin.php、api.php。明确拒绝 install.php、core.php、router.php、Ace demo PHP、大小写变体、php[0-9]*、phtml、phar、path-info 及 upload/download/storage 脚本。片段不得包含现有 80/443 站点、TLS 配置或服务器真实路径之外的共享配置。
6. 编写非敏感配置。Compose secrets 只引用 /etc/miaomu/secrets/**；MySQL 使用 _FILE。deploy/config/database.php.example 从 /run/secrets/mysql_app_password 读取口令并固定 db、miaomu、miaomu_app。L4 实际 database.php 必须与审计模板逐字节一致并只读挂载。
7. 集中候选镜像与发布输入。stack-policy 只记录 PHP、Composer、MySQL 候选 tag+digest 和 external Caddy v2.11.2 合同；validate_release_inputs.py 校验全限定镜像、Git SHA、主/恢复 project、回环 FastCGI 端口、仓库外文件、release manifest 和 database.php 模板哈希，不宣称 registry 或 Caddy 已验证。
8. 提供 L4 可执行测试入口。Composer 严格校验必须在实际含 Composer 的 build stage 或一次性 verify target 运行；server environment 检查必须被复制到应用镜像固定路径，验证 PHP/扩展、Git revision、只读源码、可写目录、secret 可读和 sxo_config readiness。运行镜像不因测试保留 Composer。
9. 重写运维文档。LOCAL_STACK 记录两服务和 Caddy 边界；DEPLOYMENT 记录 Caddy 备份、validate、最小挂载、reload/recreate 和回滚；BACKUP_RESTORE 纳入 Caddy 配置/Compose 哈希并保证恢复不接入主 Caddy；PERFORMANCE_BASELINE 用 Caddy 指纹替换 Nginx。
10. 重写标准库离线测试。检查无 Nginx/web/edge、FPM 仅回环、MySQL 内部、Caddy :88 片段与拒绝规则、媒体挂载合同、project 隔离、固定候选镜像、安全配置、真实 L4 测试入口和文档 not_run 边界。

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

1. 只读复核 Caddy v2.11.2、host network、配置/Compose 路径、容器与挂载、80/443、Beszel 和固定回环端口 19000。
2. 备份原 Caddyfile 与共享 Compose，记录 docker inspect、容器/镜像身份、挂载、端口和 https://supervise.jiayyy.cn 健康结果，并验证回滚副本。
3. 在 /root/jia/miaomu 部署精确提交，准备仓库外 config/secrets，构建 app 并启动 app/db。
4. 完成空测试库初始化和 app readiness，确认 127.0.0.1:19000 可达且非回环不可达。
5. 增加 public 与媒体只读挂载、合并独立 :88 片段，使用现有镜像验证完整候选 Caddyfile 与共享 Compose；因为新增挂载，必须只 recreate jia-caddy，不对共享栈执行 down。只有 L4 证明三个挂载已存在且仅配置变化时才允许 reload。
6. 立即验证 https://supervise.jiayyy.cn、80/443 既有路由、Beszel、共享容器和日志无非预期变化，再执行 :88 无真实账号/个人数据的入口、查询参数、SCRIPT_FILENAME 和拒绝旁路冒烟。
7. 任一门禁失败立即恢复原 Caddyfile、共享 Compose、挂载和容器身份，只 recreate jia-caddy，再次验证 supervise，然后停止 miaomu 服务；不得扩大修改范围。

若 L4 发现必须改变 FastCGI 端口、Caddy 路径、挂载、Compose 拓扑、源码写路径或数据库结构，应阻塞 NUR-OPS-001 并建立新的离线合同修订，不能借远程任务直接修改本任务拥有的制品。

## 数据库与核心适配

无数据库结构或数据变更，无 ShopXO 核心适配。本任务不得运行 config/shopxo.sql，不得修改仓库中的 config/database.php。差异只允许位于 deploy/**、tests/ops/**、docs/operations/** 和任务生命周期制品。

## 失败处理与回滚

发现 Nginx/Web 残留、Caddy 80/443 配置进入版本化片段、真实密钥、网络访问、未固定镜像、非回环 FPM、数据库宿主机端口、Docker socket、root 应用、全源码写权限、安装器开放、媒体卷对 Caddy 可写或 L4 测试入口不存在时立即停止，不将缺口表述为通过。

本任务回滚只还原授权路径，不连接服务器或恢复 Caddy。回滚后运行 source-check、Harness 自检和 Nginx/Web 残留扫描。服务器和共享 Caddy 回滚只属于 NUR-OPS-001。

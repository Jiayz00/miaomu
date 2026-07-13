# ShopXO 苗木站部署合同

## 执行权限

本文是 `NUR-OPS-001` 的 L4 发布输入，不授权 `NUR-OPS-003` 连接服务器或执行部署。所有服务器、Docker、Caddy、MySQL、HTTP、浏览器和性能动作当前均为 `not_run`。

远程动作只能通过项目 Harness 的锁定 `remote_execution` 和仓库内版本化脚本执行。禁止原始 SSH、SCP、现场编辑 Compose/Caddy、内联解释器或临时脚本。目标提交必须干净、已批准并由 release seal 锁定，部署根固定为 `/root/jia/miaomu`。

## 发布输入门禁

写操作前，`NUR-OPS-001` 必须只读确认并记录脱敏证据：

1. Git release SHA 与 [deploy/release-manifest.example.json](../../deploy/release-manifest.example.json) 派生的正式 manifest 完全一致。
2. 目标为 `linux/amd64`，PHP、Composer、MySQL 平台摘要、镜像 ID 和镜像内版本真实匹配 [deploy/stack-policy.json](../../deploy/stack-policy.json)。
3. 服务器现有 `jia-caddy` 为 Caddy v2.11.2、host network；其完整 Caddyfile、共享 Compose、容器/镜像身份、挂载、supplemental groups、80/443 路由和端口状态已盘点。
4. `miaomu_fpm_socket`、GID `10001` 和 user namespace 映射不存在冲突，端口 `88` 可仅绑定 `127.0.0.1`。
5. `/etc/miaomu/config/database.php` 与主模板哈希一致，恢复配置与独立恢复模板哈希一致；主/恢复应用 secret 为 root:10001/0440，root DB secret 只能为 root:root/0400，均非空。主/恢复 generated event 文件路径独立，bootstrap 前为 root:10001/0660，稳态为 root:10001/0440 且哈希进入 release manifest。不得读取或输出 secret 内容。
6. 完整候选 Caddyfile、共享 Compose 和回滚副本均已生成并可验证。
7. 主栈每个 Docker volume 的 Driver 为没有 Options 的普通 `local`，Mountpoint 位于 Docker 管理的 volume 根，Compose project/volume labels 与合同一致；任何 `driver_opts` bind、外部卷、同名非 Compose 卷或宿主目录 backing 都必须停止发布。恢复卷必须由当前恢复演练创建并单独核验，不能因为固定名称已存在就复用。

发布输入校验器必须先以合同模式运行。完成镜像构建与镜像身份记录后、任何 DB/app/Caddy 状态变更前，L4 使用 `--check-external --external-scope main --external-phase bootstrap`、`generated_events.main.state=pending` 的预初始化 manifest、真实 Caddy 配置路径和共享 Compose 路径复核；此阶段主 event 可以尚不存在，或只能是 root:10001/0660 的空普通文件，其哈希必须为 null。构建前无法取得的 app image ID 不得伪造；校验失败即停止，不得现场放宽合同。

release manifest 使用 `generated_events.main` 与 `generated_events.restore` 分别记录 `state` 和 `sha256`。主站官方 CLI 生成主 event 后，只把 main 状态改为 `generated`，并以 `--external-scope main --external-phase steady` 校验主 event、主配置、主 secrets 和 Caddy 输入；restore 可以继续保持 pending。恢复演练生成独立 event 后再以 `--external-scope restore` 校验，只有同时核验两栈时才使用 `both`。各阶段 manifest 保留不覆盖；路径、哈希、命令和退出码均进入 L4 证据。对应栈稳态校验未通过不得启动其 FPM。

## 受控部署顺序

### 1. 保存共享服务基线

变更前必须保存并计算哈希：

- 原完整 Caddyfile；
- 共享 Caddy Compose；
- `docker inspect`、容器与镜像身份；
- networks、volumes、mounts、supplemental groups；
- 80/443 和 `127.0.0.1:88`/公网 `:88` 监听状态；
- Beszel 与 `https://supervise.jiayyy.cn` 健康结果。

备份必须可用于精确回滚。不得只保存苗木站片段。

### 2. 构建镜像并启动 DB bootstrap

主 Compose 只能包含 `app` 和 `db`。在现有 Caddy 变更前完成：

1. 验证 Compose 解析结果没有额外服务、任何 `ports`、外部 backend 或 Docker socket。
2. 在含 Composer 的 build/verify stage 执行 strict `composer validate`、锁文件安装和 platform check；仅用 `--no-check-all` 抑制上游 `composer.json` 已审计的通配版本告警，其他 warning/error 仍失败。运行镜像不得保留 Composer或编译工具。
3. 构建并记录 `miaomu-app:<release-sha>` 镜像 ID。
4. 准备外部只读配置与 secrets，组合主 Compose 与 `compose.bootstrap.yaml`，且只启动空数据卷的 `db` bootstrap，不启动 app。验证 override 将 health 模式改为 bootstrap，而基础 Compose 仍固定要求 steady marker；项目 wrapper 只把 secret 文件复制到私有 tmpfs、不会把内容写入 stdout 或 argv，并通过 `gosu mysql` 运行官方初始化入口。官方 MySQL entrypoint 对 `_FILE` 的内部处理必须由 L4 在 bootstrap 与 steady 两阶段分别检查进程环境；证据只记录敏感变量名是否存在的布尔结果，不读取或输出值。

bootstrap healthy 后继续执行第 3 节；此时仍不得创建 steady marker、启动 app 或修改 Caddy。

### 3. 空库初始化与最小权限

不得使用浏览器安装器，也不得把完整 `config/shopxo.sql` 放入 MySQL 自动初始化目录。

仅在证明目标库为空且已有数据库备份后，才可通过锁定动作离线导入基线。对外启动前必须：

1. 清除样例用户、订单、支付、消息、日志和 Session 数据，并核对逐表结果。
2. 通过不进入 argv 或日志的输入重置 `common_data_encryption_secret`。
3. 清空 token 并禁用 `id=1` 管理员；不得让 `id=1` 或 `role_id=1` 用于日常管理。
4. 创建 `id`、`role_id` 均不为 `1` 的最小权限管理员。
5. 使用该账号逐项证明 SQL 控制台执行、插件/主题安装或上传、在线升级、路由/配置写入、订单和支付 action 均不可达。
6. 确认没有真实账号或个人数据后，方可继续回环 HTTP 冒烟。

任一清理或权限断言失败时，不得启动 `127.0.0.1:88`。

### 4. 转入无凭据稳态并初始化 nursery

1. 只有第 3 节全部通过，才允许以 mysql 身份创建 mode `0444` 的空标记 `/var/lib/mysql/.miaomu-steady`；标记创建动作和元数据必须进入 L4 精确动作合同。随后停止并移除由 bootstrap overlay 创建的 db 容器，移除 overlay，只用基础 Compose 执行 `up --force-recreate db`。禁止用 `docker compose restart` 代替，因为 restart 不会应用基础 Compose 的 healthcheck 与 restart policy。新容器必须证明 Healthcheck argv 末项为 `steady`、RestartPolicy 与基础 Compose 一致，且 marker 存在并能连接 mysqld。不得用 system schema 目录本身替代标记。若 bootstrap 异常，只能按空库回滚合同重建，不能为残缺目录创建标记。
2. 验证第二次启动通过 `gosu mysql` 读取 steady marker，未复制 secrets、未进入官方初始化入口，且在 exec 前 unset 密码与 `_FILE` 变量。证明 MySQL 稳态 PID 为 `999:999`、Groups 不含 `10001`、CapEff 为零；该身份不能读取 `/run/secrets/mysql_root_password`，进程环境没有密码或密码文件变量，私有 tmpfs 没有密码副本。
3. 创建空的 `/etc/miaomu/generated/event.php`，元数据固定 root:10001/0660。组合主 Compose 与 `compose.init.yaml` 运行一次性 app CLI：`php /usr/local/lib/miaomu/nursery-bootstrap.php initialize --actor NUR-OPS-001 --run-id=<locked-run-id>`。受管入口必须先运行固定 runtime sanitizer，清理 `cache`、`session`、`temp`、三端 `*/temp` 和 `data/config_data`，再把外部文件覆盖为固定安全空数组 stub 并启动 ThinkPHP；随后通过 ShopXO 官方 `PluginsAdminService` 安装并启用 nursery、生成 event.php、拒绝其他启用插件，并执行 existing 模式目录迁移。不得 include 外部残留、手写最终 event 内容或把整个 app 目录改为可写。
4. CLI 成功后停止一次性容器，将 event.php 改为 root:10001/0440，记录 SHA-256 并写入新的 main 稳态 manifest，不覆盖 pending manifest。通过 `--external-scope main --external-phase steady` 后才只使用主 Compose 启动稳态 `app`；其 entrypoint 必须再次清理固定 runtime 易失目录，并先通过 `environment_check.php --startup` 才能执行 FPM。证明旧 Session 与配置缓存不存在、`/var/www/html/app/event.php` 为只读 bind、内容与 nursery `config.json` hook 完全一致、`sxo_plugins` 仅 nursery 启用且 catalog manifest 存在。
5. 运行镜像内 `/usr/local/lib/miaomu/environment_check.php`，验证 PHP/扩展、release SHA、只读源码、有限写目录、应用 secret、generated event、数据库 readiness 和 socket 元数据。
6. 证明宿主机与容器均无 FPM TCP listener、MySQL 无宿主机端口；socket 是 `/run/miaomu-fpm/php-fpm.sock`、GID `10001`、mode `0660`，无卷容器和普通宿主机用户连接失败。

以上全部仍为 `NUR-OPS-001: not_run`，直到留下真实命令、退出码和脱敏输出。

### 5. 合并现有 Caddy

[deploy/Caddyfile.miaomu](../../deploy/Caddyfile.miaomu) 只是待合并片段。完整候选配置必须保持现有 80/443 站点，并新增：

- 仅 `127.0.0.1:88` 的苗木站点；
- `/root/jia/miaomu/public` → `/var/www/html/public:ro`；
- `miaomu_uploads` → `/var/www/html/public/static/upload:ro`；
- `miaomu_fpm_socket` → `/run/miaomu-fpm:ro`；
- supplemental group `10001`。

`miaomu_downloads`、runtime、数据库卷、`/etc/miaomu` 和 Docker socket不得挂入 Caddy。

Caddy 只通过 `unix//run/miaomu-fpm/php-fpm.sock` 访问 FPM，只允许 `index.php`、`admin.php`、`api.php`，拒绝 `/download/**`、安装入口、隐藏/敏感路径、脚本扩展变体、PATH_INFO 和上传目录脚本。任何 HTTP 请求头、查询参数或环境都不得映射为 `PHP_VALUE` 或 `PHP_ADMIN_VALUE`。

变更策略固定为：

- 只要新增 public/uploads/socket 任一挂载或 GID `10001`，先验证完整候选 Caddyfile 与共享 Compose，然后只 recreate `jia-caddy`；不得对共享栈执行 down。
- 仅当三项挂载和 group 已全部存在、只有配置内容变化时，验证完整候选后才允许 reload。

### 6. 冒烟与共享服务回归

Caddy 变更后必须立即验证：

- `https://supervise.jiayyy.cn`、80/443 既有路由和 Beszel 无回归；
- `127.0.0.1:88` 首页、后台、API、静态资源和上传媒体；
- 查询参数保留和三个固定 `SCRIPT_FILENAME`；
- `/download/**`、敏感入口、扩展/大小写/PATH_INFO 旁路及上传脚本逐项拒绝；
- 命名为 `PHP_VALUE`/`PHP_ADMIN_VALUE` 的 HTTP 头和查询参数不会变成 FastCGI 配置参数；
- `38.12.21.18:88` 未监听且不可达。

回环冒烟不得使用真实账号、个人数据或生产询价。正式用户登录、收藏和询价必须等待独立 TLS 域名的 L4 合同。

## 失败与回滚

任一构建、数据库、socket、Caddy validate、共享站点或 HTTP 门禁失败时：

1. 停止继续发布，不扩大端口、权限、挂载或写路径。
2. 恢复原完整 Caddyfile 与共享 Compose。
3. 恢复原 mounts、groups、service、image、network 和配置哈希，只 recreate `jia-caddy`；不要求 container ID 相同。
4. 再次验证 `https://supervise.jiayyy.cn`、80/443、Beszel 和共享容器。
5. 停止苗木 `app/db`，保留脱敏诊断和备份，不自动删除数据库或卷。

本文件未执行上述步骤。所有结果在 `NUR-OPS-001` 提供真实证据前均为 `not_run`。

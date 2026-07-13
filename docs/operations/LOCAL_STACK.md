# ShopXO 苗木站本地栈合同

## 状态与边界

本文描述 `NUR-OPS-003` 交付的离线运行合同，不代表任何容器、数据库或网关已经启动。当前所有 Docker、Caddy、MySQL、HTTP 和性能实测均由后续 L4 `NUR-OPS-001` 执行，状态统一为 `not_run`。

仓库只维护一个源码目录。主栈使用 [deploy/compose.yaml](../../deploy/compose.yaml)，恢复演练使用 [deploy/compose.restore.yaml](../../deploy/compose.restore.yaml)，不得为部署复制第二份源码或在服务器现场修改版本化制品。

## 两服务拓扑

长期服务集合必须恰为：

| 服务 | 职责 | 长期端口 | 身份 |
| --- | --- | --- | --- |
| `app` | ShopXO PHP-FPM 应用 | 无 | `10001:10001`，非 root |
| `db` | MySQL 8.0 数据库 | 无 | 短暂 root secret handoff 后，稳态 `999:999` |

主项目名固定为 `miaomu`，内部网络固定为 `miaomu_backend` 且 `internal: true`。`app` 和 `db` 只加入该网络，不发布宿主机端口，默认不能访问外部网络。短信、邮件、远程图片抓取或其他出网需求必须另立获批合同，不能现场放宽网络。

现有 `jia-caddy` 不属于本 Compose，不加入 `miaomu_backend`，也不由本项目拉取、升级或重建为新网关。它继续使用 host network，并只通过权限化 Unix socket 连接 PHP-FPM。

主/恢复 Compose 的每个顶层 volume 定义只能包含固定 `name`，不得设置 `external`、`driver` 或 `driver_opts`。L4 必须证明实际 Driver 为无 Options 的普通 `local`、Mountpoint 位于 Docker 管理根且 Compose labels 正确；同名但由宿主目录 bind 支撑的 local volume 不属于本合同。

## PHP-FPM Unix socket

主栈固定使用：

- 命名卷：`miaomu_fpm_socket`；
- 容器目录：`/run/miaomu-fpm`；
- socket：`/run/miaomu-fpm/php-fpm.sock`；
- group：`10001`；
- mode：`0660`。

`app` 是 socket 的创建者。除 `app` 和外部 `jia-caddy` 外，任何容器不得挂载 `miaomu_fpm_socket`，任何无关进程不得获得 supplemental group `10001`。不得改为 TCP listener、`0666` 或共享恢复栈 socket。

FPM 的 prepend guard 只在 `fpm-fcgi` SAPI 生效，规范化 `SCRIPT_FILENAME` 后仅允许：

- `/var/www/html/public/index.php`；
- `/var/www/html/public/admin.php`；
- `/var/www/html/public/api.php`。

guard 同时拒绝 `PATH_INFO`，但它只是纵深防御；首要信任边界仍是 socket 卷、GID 和挂载者集合。CLI 检查不得被该 guard 拦截。

## 文件系统

应用镜像中的源码保持只读。允许写入的运行路径只有：

- `/var/www/html/runtime` → `miaomu_runtime`；
- `/var/www/html/public/static/upload` → `miaomu_uploads`；
- `/var/www/html/public/download` → `miaomu_downloads`；
- `/run/miaomu-fpm` → `miaomu_fpm_socket`；
- 受限的 `/tmp` tmpfs。

`downloads` 是应用私有生成区，不挂入 Caddy；`/download/**` 在网关层全部拒绝。不得通过把整棵源码改为可写来解决后台配置、主题、插件或在线升级功能，这些能力应由业务权限和路由任务收敛。

容器必须保持 `read_only`、`cap_drop: [ALL]`、`no-new-privileges`、资源限制、日志轮转和 Watchtower 禁用，不得挂载 Docker socket。

首版 app 内存上限为 1 GiB，PHP 单请求 `memory_limit` 为 256 MiB，因此 FPM 初始 `pm.max_children` 固定为 3，给 master、OPcache 和系统库保留约 25% 容量。该值不是性能结论；NUR-OPS-001 记录真实 worker RSS 与 OOM 余量后才能在新获批合同中调整。

## 配置与 secrets

生产文件只存在于仓库外：

- `/etc/miaomu/config/database.php`；
- `/etc/miaomu/secrets/mysql_app_password`；
- `/etc/miaomu/secrets/mysql_root_password`；
- `/etc/miaomu/generated/event.php`。

恢复栈使用完全独立的 `/etc/miaomu-restore/config/database.php`、`/etc/miaomu-restore/secrets/**` 和 `/etc/miaomu-restore/generated/event.php`。主配置必须逐字节匹配 `deploy/config/database.php.example`，恢复配置必须逐字节匹配 `deploy/config/database.restore.php.example`；两份模板分别固定主库与恢复库身份，不能互换或现场手写。

`database.php`、应用数据库口令和稳态 generated event 的元数据合同为 owner UID `0`、GID `10001`、mode `0440` 且非空；event bootstrap 例外为同 owner/group 的空 `0660` 文件。MySQL root 口令只允许 root:root/0400，不能授予 GID `10001`。检查只能记录路径、owner、mode、size 和模板哈希，不得读取、打印或上传 secret 内容。

数据库不得加入 supplemental group `10001`。空数据卷首次启动属于 bootstrap：受控 entrypoint 以 owner root 读取两个 file secret，将内容不经 stdout 或 argv 复制到容器私有 tmpfs；复制阶段目录保持 root-only，文件先设 mode `0400` 再改为 `999:999`，目录最后改为 `999:999`、mode `0700`，随后通过 `gosu mysql` 执行官方 entrypoint。项目 wrapper 只保证自身不输出内容并只交付 `_FILE` 路径；官方 entrypoint 是否临时物化密码环境变量必须由 L4 检查 bootstrap/steady 进程环境后判定，证据只保留变量名存在性，不保留值。

基础 Compose 的 DB healthcheck 固定为 `steady`，在 marker 缺失时必须失败；首次初始化只能组合 `compose.bootstrap.yaml`（恢复栈使用独立 bootstrap override）并且只启动 db。bootstrap healthy 不是稳态门禁。L4 必须完成空库导入、样例清理、加密串重置、id=1 禁用和最小管理员门禁后，才可用 mysql 身份在数据卷创建只读空标记 `/var/lib/mysql/.miaomu-steady`。随后必须删除 bootstrap overlay 创建的容器，移除 overlay，并以基础 Compose `up --force-recreate db`；禁止使用不会应用新 healthcheck/restart policy 的 `restart`。新容器的 Healthcheck argv 必须为 steady、RestartPolicy 必须匹配基础 Compose。entrypoint 只能通过 `gosu mysql test -f` 识别该标记；稳态分支必须 unset 所有密码及 `_FILE` 变量、跳过 secret 复制和官方初始化入口，直接以 `gosu mysql` 启动 mysqld。稳态 PID 必须为 `999:999`、无 supplemental group、无有效 capability，且不能读取 `/run/secrets/mysql_root_password` 或看到私有密码副本/密码变量。未完成该标记和强制 recreate 不得运行 nursery 初始化、启动 app 或回环 `:88`。

实际 `database.php` 必须与 `deploy/config/database.php.example` 逐字节一致，固定数据库主机 `db`、库名 `miaomu`、应用账号 `miaomu_app`，并从 `/run/secrets/mysql_app_password` 读取口令。数据库容器使用 `_FILE` 变量，密码不得进入 Git、命令行、日志或证据。

`app/event.php` 不是手工源码。L4 先创建 owner `0`、group `10001`、mode `0660` 的空外部文件，再组合 `compose.yaml` 与 `compose.init.yaml` 运行一次 `/usr/local/lib/miaomu/nursery-bootstrap.php`。CLI 在启动 ThinkPHP 前必须把该元数据已验证的普通文件覆盖为固定的安全空数组 stub，绝不 include 外部残留内容；随后使用 ShopXO `PluginsAdminService` 安装/启用 nursery、生成事件映射并执行现有模式目录迁移。其他插件启用时失败关闭。CLI 成功后，宿主文件改为 `0440`、记录哈希，并只用主 Compose 以 read-only bind 启动 app。readiness 必须证明事件映射与 nursery `config.json` 完全一致、数据库仅 nursery 启用且目录 manifest 存在。稳态禁止后台在线安装、启停或升级插件。

外部校验按栈、按阶段执行：`generated_events.main` 与 `generated_events.restore` 分别记录状态和哈希。`bootstrap` 接受对应 event 不存在或 root:10001/0660 的空文件，pending 哈希必须为 null；`steady` 要求所选栈 event 为非空 root:10001/0440 并与 generated 哈希一致。主发布用 `--external-scope main`，恢复演练用 `restore`，联合审计才用 `both`；pending manifest 不得被稳态结果覆盖。

主 app 的受管初始化与 FPM 启动都先运行镜像内固定 runtime sanitizer，只清理 `cache`、`session`、`temp`、`admin/temp`、`index/temp`、`api/temp` 与 `data/config_data`，保留日志和业务生成文件。restore app 每次受管启动先清空整个独立 runtime 卷再重建这些目录，确保旧 Session、配置缓存和临时文件不污染恢复结果。sanitizer 拒绝 symlink、非目录和非规范 runtime 根，清理路径不得由环境或命令行动态提供。

基础 app 还会在启动 FPM 前执行 `environment_check.php --startup`；该模式核验只读 event、唯一启用插件、目录 manifest、数据库 readiness 和全部运行权限，只把 socket 检查延迟到 FPM 创建之后。任何 readiness 失败都不得创建 FastCGI socket。

## 镜像与离线检查

[deploy/stack-policy.json](../../deploy/stack-policy.json) 中的 PHP、Composer、MySQL tag 与 digest 只是候选输入，不是运行证据。禁止 `latest`。`NUR-OPS-001` 必须真实解析 `linux/amd64` 平台摘要、镜像 ID 和镜像内版本。

本任务允许执行的离线检查为：

```text
python deploy/validate_release_inputs.py --contract-only
python tests/ops/test_deployment_contract.py
```

应用构建、Composer platform check、`docker compose config`、容器 healthcheck、数据库 readiness 和 socket 权限检查均为 `NUR-OPS-001: not_run`，不能由文件存在或 Python 静态测试替代。

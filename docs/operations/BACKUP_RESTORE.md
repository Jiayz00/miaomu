# ShopXO 苗木站备份与恢复合同

## 状态

本文只定义 L4 `NUR-OPS-001` 必须执行的备份、隔离恢复和回滚门禁。当前没有运行备份、恢复容器、数据库导入、Caddy 变更或页面抽样；全部状态为 `not_run`。

## 备份集合

每个可发布 release SHA 必须形成同一批次的备份清单，至少包括：

- MySQL 一致性逻辑备份及其工具/版本、开始结束时间、退出码和校验和；
- `miaomu_uploads` 媒体卷；
- `miaomu_downloads` 应用私有生成区；
- `/etc/miaomu/config/database.php` 的模板哈希和文件元数据；
- `/etc/miaomu/generated/event.php` 的内容哈希和 root:10001/0440 元数据；
- 外部 secret 文件的 owner、group、mode、size 元数据，不读取或备份到 Git；
- Git release SHA、应用镜像 ID、PHP/Composer/MySQL 平台摘要；
- 正式 release manifest、`deploy/compose.yaml` 和 stack policy 哈希；
- pending 与 generated 两阶段 manifest 及各自校验输出；
- 变更前完整 Caddyfile、共享 Caddy Compose、`docker inspect`、镜像/容器身份、mounts、groups、networks 和 80/443/88 端口快照；
- `https://supervise.jiayyy.cn` 与 Beszel 的变更前健康结果。

`runtime` 缓存、临时文件和旧 Session 不进入恢复集。不得把原始数据库、secret、完整个人数据日志或未脱敏输出提交到 Git。

本合同只支持应用 schema 的一致性逻辑备份：导出 `miaomu` 中的表结构与数据，但不得包含 `CREATE DATABASE`、`USE miaomu`、`mysql`/`sys`/`performance_schema`/`information_schema`、账号、GRANT 或 MySQL system tables。恢复时客户端必须显式连接已由 restore bootstrap 创建的 `miaomu_restore`，再导入这份不带数据库选择语句的 dump。物理 datadir/`miaomu_db_data` 复制、带 `--databases` 语义的 dump 或系统 grant 恢复不属于本合同；若确有灾难恢复需求，必须另立 L4 身份、密码和 schema remap 方案。

备份保存位置、加密、保留期和删除动作必须写入 NUR-OPS-001 的远程合同；本任务不自行选择服务器路径。

## 隔离恢复拓扑

恢复使用 [deploy/compose.restore.yaml](../../deploy/compose.restore.yaml)，固定隔离身份：

| 项目资源 | 主栈 | 恢复栈 |
| --- | --- | --- |
| project | `miaomu` | `miaomu_restore` |
| backend | `miaomu_backend` | `miaomu_restore_backend` |
| database | `miaomu` | `miaomu_restore` |
| app user | `miaomu_app` | `miaomu_restore_app` |
| runtime | `miaomu_runtime` | `miaomu_restore_runtime` |
| uploads | `miaomu_uploads` | `miaomu_restore_uploads` |
| downloads | `miaomu_downloads` | `miaomu_restore_downloads` |
| db data | `miaomu_db_data` | `miaomu_restore_db_data` |
| FPM socket | `miaomu_fpm_socket` | `miaomu_restore_fpm_socket` |
| config/secrets root | `/etc/miaomu` | `/etc/miaomu-restore` |

主、恢复 `database.php` 分别使用 `deploy/config/database.php.example` 与 `deploy/config/database.restore.php.example`，两份文件及哈希必须不同。恢复配置固定 `miaomu_restore`/`miaomu_restore_app`，不得复用主模板后现场替换字符串。generated event 也必须使用不同外部路径；恢复栈通过 `compose.restore.init.yaml` 和相同的官方初始化 CLI 生成自己的 event，不得挂载或复制主栈文件。

恢复栈不得挂载任何主栈卷、config、secret 或 socket。`miaomu_restore_fpm_socket` 默认不挂入 `jia-caddy`，恢复栈也不发布端口。不能仅靠临时 `-p` 参数覆盖项目名；版本化 Compose 必须自身声明隔离名称。

## 恢复演练顺序

NUR-OPS-001 必须以锁定动作完成：

1. 核验备份批次的 release SHA、manifest、镜像身份、Compose/Caddy 哈希和所有校验和。
2. 由本次演练创建隔离的 restore volumes 和仓库外 `/etc/miaomu-restore` 配置；逐卷证明 Driver 为无 Options 的普通 `local`、Mountpoint 位于 Docker 管理根、Compose labels 正确且不是既有同名卷或 host bind backing。只检查 secrets 元数据，不输出内容。
3. 组合 restore Compose 与 `compose.restore.bootstrap.yaml` 并只启动空的恢复 `db`。先静态拒绝含 `CREATE DATABASE`、`USE` 或系统 schema/grant 的 dump，再把应用 schema 逻辑备份导入显式目标 `miaomu_restore`；完成行数、关键对象和用户隔离断言后，才以 mysql 身份创建独立 steady marker。删除 bootstrap 容器、移除 overlay，并只用基础 restore Compose `up --force-recreate db`；禁止用 restart 代替。证明新容器 Healthcheck argv 为 steady、RestartPolicy 正确、UID/GID、Groups、CapEff、进程环境和 secret 不可读门禁。不得挂入或复制主/备份物理 datadir。
4. 恢复 uploads 与 downloads 到各自恢复卷；不得把 downloads 暴露为匿名静态资源。
5. 确认 `miaomu_restore_runtime` 是本次演练新建或将其完整清空；以 root:10001/0660 创建恢复 generated event，组合 restore Compose 与 restore init overlay 运行官方初始化 CLI。restore 受管入口必须在框架启动前清空整个独立 runtime 卷并重建固定目录。成功后改 event 为 0440、记录独立哈希，以 `--external-scope restore --external-phase steady` 校验，再启动恢复 `app`。执行固定 environment check，验证旧 Session/缓存不存在、nursery 事件映射、唯一启用插件、release SHA、PHP 扩展、只读源码、有限写目录、数据库 readiness 和 `miaomu_restore_fpm_socket` 的 GID `10001`/mode `0660`。
6. 验证 id=1/role_id=1、最小管理员、样例数据清理和危险后台 action 状态符合备份时的安全基线。
7. 验证不恢复旧 Session，且主栈容器、卷、socket、Caddy mounts、80/443 和 `127.0.0.1:88` 均未变化。

如确需页面抽样，必须另行锁定临时的仅回环入口和 restore socket 挂载；不得使用主 `:88`、主 socket、主 uploads/downloads 或正式账号。抽样结束立即移除临时入口并验证共享站点。

## 恢复验收

一次恢复只有在以下证据齐全时才可记为成功：

- 每个备份文件/卷的校验和匹配；
- 数据库导入命令、退出码和关键数据断言通过；
- 恢复实例只存在目标应用 schema `miaomu_restore`，应用账号为 `miaomu_restore_app`，没有从备份导入账号、GRANT、系统 schema 或旧 Session；
- uploads/downloads 数量与抽样哈希匹配；
- app/db healthy，恢复 socket 权限正确且无 TCP/宿主机端口；
- restore 与 main 的 project、network、volumes、config、secrets、socket 全部不同；
- 主 Caddy、supervise、Beszel 和 80/443 没有变化；
- 原始输出已脱敏，未读取或泄露 secrets。

当前以上各项均为 `NUR-OPS-001: not_run`。

## 发布回滚与数据恢复的区别

代码或网关发布失败时，优先执行发布回滚：恢复原完整 Caddyfile/共享 Compose、原 mounts/groups/service/image/network 身份，只 recreate `jia-caddy`，重新验证 supervise，然后停止苗木 app/db。不得因为代码发布失败自动覆盖数据库或删除卷。

只有数据损坏且恢复点、影响范围和备份校验均经独立 L4 审批时，才允许从隔离恢复结果提升为数据恢复。提升前必须再次备份当前状态，明确停机窗口和前向补偿方案。不得把 restore volumes 直接改名为主卷或让 restore socket直接接入现有 Caddy。

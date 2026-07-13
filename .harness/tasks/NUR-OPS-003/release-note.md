# NUR-OPS-003 发布与回滚说明

## 变更摘要

- 新增只含 PHP-FPM `app` 与 MySQL `db` 的主/恢复 Compose 合同，无 Web 容器、无宿主机服务端口、无 Docker socket，并固定资源、权限、健康检查和隔离命名卷。
- PHP-FPM 只在 `miaomu_fpm_socket` 创建 `/run/miaomu-fpm/php-fpm.sock`；服务器继续复用现有 host-network `jia-caddy`，苗木验收入口只绑定 `127.0.0.1:88`。
- 新增 Caddy PHP 白名单、敏感路径与 downloads 拒绝、只读 public/uploads/socket 挂载合同。
- 新增 MySQL bootstrap/steady 分阶段入口、分栈 generated event manifest、官方 nursery 初始化 CLI、启动 readiness 与 runtime sanitizer。
- 新增备份恢复、共享 Caddy 变更、回滚和性能测量协议。本 L3 任务没有连接或修改服务器。

## 发布前提

- 本任务完成独立合并审查并进入 `approved_for_merge`；服务器动作必须另建 L4 `NUR-OPS-001`，设 `network_access_required=true`，锁定远程动作并取得独立 release 审批。
- L4 合同锁定 release commit、目标主机指纹、仓库外 SSH 凭据引用、`/root/jia/miaomu` 受管根、现有 Caddy 完整配置/Compose 路径、备份与回滚动作；禁止原始 ssh/scp/curl。
- 写操作前只读核验目标架构、Docker/Compose/Caddy/PHP/MySQL 版本、88 端口、`jia-caddy` host network、现有 80/443 站点、Beszel、GID 10001、userns 与命名卷冲突。
- 逐卷核验 Driver 为无 Options 的普通 `local`、Mountpoint 位于 Docker 管理根且 Compose labels 正确；restore 卷必须由本次演练创建，拒绝同名外部卷或 host bind backing。
- 构建后、任何 DB/app/Caddy 状态变更前生成真实 manifest，记录平台 digest、image ID、Caddy 哈希和主栈 pending event 状态，并通过 `--external-scope main --external-phase bootstrap`。
- 生产配置、event 和 secrets 只存在于仓库外；主/恢复路径和内容相互隔离，证据只记录允许的元数据与哈希。

## 发布步骤

1. 备份现有 Caddyfile、共享 Caddy Compose、容器身份、mounts/groups/networks、80/443/88 监听和既有站点健康状态；生成数据库与媒体备份清单。
2. 在 `/root/jia/miaomu` 检出已批准 release commit，核验工作区、Compose/Caddy/策略哈希，构建并记录真实 `linux/amd64` 镜像摘要与 ID。
3. 只以主 Compose + bootstrap overlay 启动空数据卷 `db`；导入 ShopXO 应用 schema，清除样例个人/交易数据，禁用 id=1 token，创建非 1 的最小权限管理员并验证危险后台能力不可达。
4. 创建 mysql-owned steady marker，删除 bootstrap 容器并移除 overlay，仅用基础 Compose `up --force-recreate db`；核验 steady health argv、restart policy、UID/GID、capability、secret 可读性和敏感环境变量名存在性。
5. 创建 root:10001/0660 空 event，运行一次性 nursery 初始化。runtime sanitizer 先清理旧 cache/session/temp/config cache，再由官方 `PluginsAdminService` 安装启用 nursery、生成 event 并执行 existing 目录迁移。
6. event 改为 root:10001/0440，写入 main generated 哈希并通过 `--external-scope main --external-phase steady`；只用主 Compose 启动 app，核验 readiness、只读源码、允许写目录和 FPM socket。
7. 验证完整候选 Caddyfile 与共享 Compose；新增挂载/GID 时只 recreate `jia-caddy`，仅配置变化且既有挂载完整时才 reload。不得执行共享栈 `down`，不得新建 Nginx 或第二个 Caddy。
8. 执行回环首页/后台/API/静态/上传与拒绝矩阵、既有 supervise/Beszel/80/443 回归，并证明公网 `38.12.21.18:88` 不可达。TLS 域名就绪后再验证真实登录、收藏、询价和个人数据流程。

## 回滚触发与步骤

- 触发条件：镜像/配置哈希不符、DB 数据门禁失败、bootstrap 未正确转 steady、event/readiness 失败、socket 权限错误、Caddy validate 失败、既有站点回归、公网 88 可达或 HTTP 拒绝矩阵失败。
- Caddy 变更失败：恢复发布前完整 Caddyfile 与共享 Compose，先 validate，再只 recreate `jia-caddy`；复核 supervise、Beszel、80/443 和原 mounts/groups/service/image/network。
- app/db 失败：停止苗木 app/db，保留脱敏诊断与数据库/媒体备份，不自动删除或覆盖卷，不把 restore 卷改名为主卷。
- 数据损坏：只能在独立 L4 审批、当前状态再次备份且隔离恢复验收完成后执行数据恢复；代码发布失败不得自动触发数据库覆盖。
- 仓库制品问题：还原本任务提交并重跑 source-check、scope-check、部署合同与 Harness 自测。

## 发布后验证

- app/db healthy；MySQL 无宿主机端口，FPM 无 TCP listener，主 socket 路径/GID/mode 正确且仅 app 与 `jia-caddy` 可访问。
- 主 event 与 manifest 哈希一致，仅 nursery 插件启用，目录 manifest 存在，旧 Session 与配置缓存已清理。
- `127.0.0.1:88` 三个 PHP 入口、静态资源和上传媒体正常；安装器、敏感路径、脚本变体、PATH_INFO、上传脚本和 `/download/**` 被拒绝。
- `38.12.21.18:88` 不可达；共享 80/443、`https://supervise.jiayyy.cn` 和 Beszel 无回归。
- 性能结果只有在固定数据集和协议真实执行后才记录；商品列表/详情及后续收藏、询价、统计场景未实现或未执行时保持 `blocked/not_run`。

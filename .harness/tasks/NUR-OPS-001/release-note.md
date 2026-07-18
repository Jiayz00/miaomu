# NUR-OPS-001 发布与回滚说明

## 变更摘要

本版本把 NUR-OPS-001 从旧的离线 draft 改为 L4 服务器部署合同：目标固定为 `root@38.12.21.18:22`，部署根 `/root/jia/miaomu`，受管 Caddy 根 `/root/jia/caddy`，入口只使用现有 `jia-caddy` 的 `127.0.0.1:88`。苗木 Compose 只有 `app` 与 `db` 两个长期服务；PHP 镜像补充 `intl`，询价 HMAC 通过仓库外 secret 注入。`bootstrap_shopxo_schema` 只在空库按 `deploy/shopxo-schema-baseline-manifest.json` 建立 83 张表的 schema-only 基线，写入站点运行配置、三层地区参考链并创建禁用的非 1 号占位账号，`initialize_nursery` 再执行已批准的 catalog/favorite/inquiry v1 前向迁移，合同锁定受影响表、台账/幂等核验、主机指纹、外部 SSH 文件引用、动作白名单、Caddy 快照和回滚边界。

## 发布前提

- `source-check`、`task-check`、`plan-check`、Harness/远程自检、部署合同和 release-input 合同通过。
- 独立 Codex 角色完成 plan、merge、release 审查；任务处于 `approved_for_merge`，工作区干净且 release seal 锁定发布 SHA。
- 只读 inventory 确认目标为个人/测试服务器，Caddy/Beszel/80/443 健康，端口 88 可用，`/root/jia/miaomu` 根和 `miaomu_*` named volumes 均不存在，目标数据可丢弃。
- 仓库外 database.php、MySQL secret、`nursery_inquiry_hmac_key`、SSH identity 和 known_hosts 已由文件权限门禁确认；不读取或输出值。release.env 只包含与 sealed HEAD 匹配的 `MIAOMU_RELEASE_SHA`，release tar 已通过成员路径/链接审计。
- 已完成共享 Caddyfile/Compose 的备份并能在隔离位置读取校验；数据库、上传、配置和插件代码备份仅在远端存在既有数据时作为前置门禁。针对本次全新可丢弃测试卷，这些备份动作未纳入合同，必须记录为 `blocked/not_run`，不得宣称完整回滚覆盖。

## 发布步骤

1. 经 Harness broker 执行 `inventory_*`、`inspect_*`、`hash_*`、`download_caddy_*` 和 `smoke_supervise_before`。
2. 执行 `bootstrap_deployment_root`、`upload_release`、`upload_release_env`、`extract_release`、`prepare_external_files`，再运行 `compose_config`。
3. 执行 `build_app`、`bootstrap_db`、`bootstrap_db_status`、`bootstrap_shopxo_schema`（空库/schema-only 门禁、83 张基线表、站点运行配置、三层地区链和禁用的非 1 号占位账号）、`create_steady_marker`、`restart_db_steady`、`initialize_nursery`（依次核验 catalog/favorite/inquiry v1 表、索引、台账和幂等重跑）、`finalize_event`、`start_app`、`app_status`、`app_readiness`。后台登录凭据设置不在本次自动发布范围内，认证验收记录为 `blocked`，不得将占位账号当作可登录管理员。
4. 执行 `prepare_backup_root`、不覆盖式 Caddy 快照目录/文件备份和 `validate_caddy_candidate`；快照目录已存在即停止，避免覆盖旧回滚基线。仅在挂载/组变化时执行 `apply_caddy_candidate`，不对共享栈执行 `down`。
5. 执行 `inspect_caddy_after`、supervise/首页/后台/API/拒绝旁路冒烟和公网 :88 探测，记录脱敏退出码与环境指纹。

所有服务器动作只能通过合同 action ID 调用，不允许直接 SSH、SCP、curl 或现场编辑。

## 回滚触发与步骤

主机指纹异常、备份失败、release 漂移、secret/intl/Normalizer/FPM/数据库/v1 迁移/Caddy/HTTP 任一门禁失败，或 supervise/80/443/Beszel 状态异常时立即停止。迁移不执行 DROP/DELETE；空测试库可在备份后按固定基线重建，含未知数据时保留原库并阻塞或前向修复。先按需执行 `rollback_caddy` 恢复原 Caddyfile/Compose/挂载/组并验证共享服务，再执行 `rollback_miaomu` 停止苗木 app/db；不删除未知卷、数据库或上传资源。回滚动作必须使用已审批合同并记录退出码、时间、配置/容器哈希和恢复校验。

## 发布后验证

确认 `jia-caddy` 仍为原 host-network 服务且只增加声明的三项只读挂载，80/443 路由和 Beszel 无非预期变化；确认 `127.0.0.1:88` 首页真实包含苗木内容而非关闭页，后台入口、API、静态资源和拒绝规则结果；固定 Python 探针同时确认回环首页内容和公网 :88 `expected_denied`；确认日志和 Harness evidence 不含密钥、完整手机号、cookie 或个人正文。后台登录凭据设置、数据库/上传深备份和未执行性能场景保持 blocked/not_run。

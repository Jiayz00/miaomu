# NUR-OPS-001 发布与回滚说明

## 变更摘要

本版本把 NUR-OPS-001 从旧的离线 draft 改为 L4 服务器部署合同：目标固定为 `root@38.12.21.18:22`，部署根 `/root/jia/miaomu`，受管 Caddy 根 `/root/jia/caddy`，入口只使用现有 `jia-caddy` 的 `127.0.0.1:88`。苗木 Compose 只有 `app` 与 `db` 两个长期服务；PHP 镜像补充 `intl`，询价 HMAC 通过仓库外 secret 注入。`initialize_nursery` 还会执行已批准的 catalog/favorite/inquiry v1 前向迁移，合同锁定受影响表、台账/幂等核验、主机指纹、外部 SSH 文件引用、动作白名单、备份和回滚边界。

## 发布前提

- `source-check`、`task-check`、`plan-check`、Harness/远程自检、部署合同和 release-input 合同通过。
- 独立 Codex 角色完成 plan、merge、release 审查；任务处于 `approved_for_merge`，工作区干净且 release seal 锁定发布 SHA。
- 只读 inventory 确认目标为个人/测试服务器，Caddy/Beszel/80/443 健康，端口 88 可用，目标数据可丢弃。
- 仓库外 database.php、MySQL secret、`nursery_inquiry_hmac_key`、SSH identity 和 known_hosts 已由文件权限门禁确认；不读取或输出值。
- 已完成数据库、上传、配置、插件代码和共享 Caddyfile/Compose 的备份，并能在隔离位置读取校验。

## 发布步骤

1. 经 Harness broker 执行 `inventory_*`、`inspect_*`、`hash_*`、`download_caddy_*` 和 `smoke_supervise_before`。
2. 执行 `bootstrap_deployment_root`、`upload_release`、`upload_release_env`、`extract_release`、`prepare_external_files`，再运行 `compose_config`。
3. 执行 `build_app`、`bootstrap_db`、数据库清理/最小管理员门禁、`create_steady_marker`、`restart_db_steady`、`initialize_nursery`（依次核验 catalog/favorite/inquiry v1 表、索引、台账和幂等重跑）、`finalize_event`、`start_app`、`app_status`、`app_readiness`。
4. 执行 Caddy 备份和 `validate_caddy_candidate`；仅在挂载/组变化时执行 `apply_caddy_candidate`，不对共享栈执行 `down`。
5. 执行 `inspect_caddy_after`、supervise/首页/后台/API/拒绝旁路冒烟和公网 :88 探测，记录脱敏退出码与环境指纹。

所有服务器动作只能通过合同 action ID 调用，不允许直接 SSH、SCP、curl 或现场编辑。

## 回滚触发与步骤

主机指纹异常、备份失败、release 漂移、secret/intl/Normalizer/FPM/数据库/v1 迁移/Caddy/HTTP 任一门禁失败，或 supervise/80/443/Beszel 状态异常时立即停止。迁移不执行 DROP/DELETE；空测试库可在备份后按固定基线重建，含未知数据时保留原库并阻塞或前向修复。先按需执行 `rollback_caddy` 恢复原 Caddyfile/Compose/挂载/组并验证共享服务，再执行 `rollback_miaomu` 停止苗木 app/db；不删除未知卷、数据库或上传资源。回滚动作必须使用已审批合同并记录退出码、时间、配置/容器哈希和恢复校验。

## 发布后验证

确认 `jia-caddy` 仍为原 host-network 服务且只增加声明的三项只读挂载，80/443 路由和 Beszel 无非预期变化；确认 `127.0.0.1:88` 首页、后台、API、静态资源和拒绝规则结果；确认公网 :88 不可达；确认日志和 Harness evidence 不含密钥、完整手机号、cookie 或个人正文。性能结果按 `test-plan.md` 指纹和统计格式保存，未执行场景保持 blocked/not_run。

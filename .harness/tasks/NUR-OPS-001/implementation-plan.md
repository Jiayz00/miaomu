# NUR-OPS-001 实施计划

## 实施步骤

1. **本地合同与发布输入**：确认 `source-check`、`task-check`、`plan-check`、部署合同测试、HMAC/intl 变更审阅和 Git diff 安全扫描通过。生成只包含获批提交和非敏感 manifest 的 release 工件；不把 `.env`、secret 或私钥放入工件。
2. **只读主机盘点**：使用 `inventory_*`（含 `inventory_miaomu_root`/`inventory_miaomu_volumes`）、`inspect_*`、`hash_*`、`download_caddy_*`、`smoke_supervise_before` 动作核验主机指纹、Docker/Compose、`jia-caddy`、Beszel、80/443/8090、88、苗木发布根和已有卷、Caddyfile/Compose 快照和可用空间。必须证明 `/root/jia/miaomu` 尚未出现且 `miaomu_*` named volumes 均不存在；发现生产标记、指纹变化、共享服务异常或目标根/目标卷已有未知业务数据时停止。
3. **建立发布根并上传**：在独立 release/merge/release 审批和 release seal 后执行 `bootstrap_deployment_root`、`upload_release`、`upload_release_env`、`extract_release`。该动作使用无 `-p` 的精确 `mkdir`，目标已存在即失败，禁止覆盖未知文件。解包内容只来自锁定提交；`release.env` 只含与 sealed HEAD 一致的 `MIAOMU_RELEASE_SHA`，release tar 不得包含 `.git`、`.harness`、release 输入自身或链接成员。
4. **准备外部运行时文件**：执行 `prepare_external_files`，从仓库外受限位置检查/创建 database.php、event.php 和 `nursery_inquiry_hmac_key`；脚本必须幂等，既有 HMAC 只保留并检查元数据。Compose 解析前运行 `compose_config`。
5. **构建与数据库初始化**：执行 `build_app`，确认镜像含 ICU/intl/Normalizer、schema-only 产物且运行阶段无 Composer 工具。通过 `bootstrap_db`（`--wait`）启动隔离 db，`bootstrap_db_status` 确认容器 ID，再执行 `bootstrap_shopxo_schema`；该入口只允许空库、按 `deploy/shopxo-schema-baseline-manifest.json` 建立 83 张表结构，写入非 1 号禁用管理员占位、站点启用/默认主题/用户名登录注册配置和北京三层地区参考链，不导入上游 INSERT。占位账号保持禁用，后台登录凭据由部署后人工运维动作设置，本任务不把认证标记为通过。随后用 `create_steady_marker`、`restart_db_steady` 完成 root bootstrap 到稳态降权；若发现既有表、生产标记或 schema/config/region 不完整立即停止。数据库/上传深备份在个人空测试库阶段记为条件性未覆盖，Caddy 快照仍是强制回滚边界。
6. **应用 readiness 与前向迁移**：执行 `initialize_nursery`，由固定 bootstrap 入口按顺序运行已批准的 `CatalogMigration::Run('existing')`、`FavoriteMigration::Run()` 和 `InquiryMigration::Run()`；核对返回状态、`sxo_config` 台账、information_schema 表/列/索引、重复执行无额外 DDL，并把每个 run-id 和退出码写入脱敏证据。随后执行 `finalize_event`、`start_app`、`app_status`、`app_readiness`。检查 FPM Unix socket 为 group 10001/mode 0660、应用无 TCP FPM 监听、源码只读、secret 元数据正确、危险后台能力不可达。任何 PHP/数据库/权限失败都进入回滚，不启动 Caddy 入口。
7. **候选 Caddy 与共享服务**：执行 `prepare_caddy_candidate` 生成完整候选配置，先执行 `prepare_backup_root`，再由不覆盖式 `backup_caddy_dir` 创建本次快照目录并执行 `backup_caddyfile`、`backup_caddy_compose`；目录已存在时 fail-closed，避免重复发布覆盖回滚基线。随后用 `validate_caddy_candidate` 验证。只有新增 public/uploads/socket 挂载或 group 时才执行 `apply_caddy_candidate`（只 recreate `jia-caddy`）；不得修改或重建其他共享服务。
8. **回环冒烟与性能记录**：执行 `inspect_caddy_after`、`smoke_supervise_after`、`smoke_miaomu_home`、`smoke_miaomu_admin`、`smoke_miaomu_api`、`smoke_download_denied` 和固定 Python `probe_public_88`。`app_readiness` 必须确认真实站点配置和地区链，固定探针还必须确认回环首页包含苗木内容且不是关闭页，同时确认公网 :88 `expected_denied`；仅 HTTP 2xx 不得作为首页通过证据。记录 HTTP 状态、错误率、脚本入口、查询参数、拒绝旁路和公网 :88 结果；后台认证因占位账号禁用保持 blocked。已实现业务场景按固定协议测量，未有夹具的收藏/询价/行为/趋势/导出保持 blocked/not_run。
9. **失败回滚与关闭**：任一门禁失败立即执行 `rollback_caddy`、`rollback_miaomu`（仅在相应变更已发生时），再次验证 supervise、Beszel、80/443 和 88。保存退出码、时间、配置/卷哈希和 Caddy 快照校验；数据库/上传深备份未覆盖时记录 blocked，不删除未知卷或数据；所有证据完成后才允许独立 reviewer/release approver 推进生命周期。

所有远程动作必须经 `python -I -S -B scripts/harness.py remote-exec` 调度；mutating action 还要求任务处于 `approved_for_merge`、工作区干净且 release seal 有效。审批由不同 Codex 角色自动完成，不把用户反复确认作为执行前置。

## 验证顺序

1. `python scripts/harness.py source-check`。
2. `python scripts/harness.py task-check NUR-OPS-001` 与 `python scripts/harness.py plan-check NUR-OPS-001`。
3. `python scripts/harness_selftest.py`、`python scripts/harness_remote_selftest.py`、`python tests/ops/test_deployment_contract.py`、`python deploy/validate_release_inputs.py --contract-only`。
4. 进入 `verifying` 后运行合同声明的 `verify`、`scope-check`、`evidence-check`、`review-pack`；保存合同哈希、每条测试的 argv 和退出码。
5. 完成独立计划/合并/发布审查和 release seal 后，按上面的 remote action 顺序执行；服务器 PHP lint、Composer、Docker Compose、Caddy validate、MySQL、HTTP、浏览器、并发和回滚均必须有真实证据。

## 数据库与核心适配

本任务不新增或改写 ShopXO/ nursery 迁移实现，也不修改 ShopXO 核心；但部署会执行已批准的 NUR-FEAT-002/003/004 v1 前向迁移。`config/shopxo.sql` 只作为确认空测试库后的固定安装基线，不能替代迁移。Catalog 受管目录/模板和 `sxo_config` 台账、Favorite 唯一索引和台账、Inquiry 五张表/索引和台账均须在 `initialize_nursery` 后真实核验；迁移只前向、幂等，失败不 DROP/DELETE。数据库初始化、默认数据清理、禁用的非 1 号管理员占位和密钥重置均限制在远程合同声明的非生产实例，并在备份后执行；管理员凭据设置与真实后台认证属于部署后人工运维动作，未执行时保持 `blocked`。若发现需要新增未批准表、改变 socket/挂载边界或修改核心路径，立即阻塞并另立任务，不在本合同内临时扩权。

## 失败处理与回滚

以下任一情况停止：主机指纹不匹配、目标被判定为生产、备份失败、release SHA 漂移、secret 缺失/权限异常、intl/Normalizer 缺失、任一 v1 迁移返回失败、台账/实际 schema 不匹配、同名异构表或重复执行产生非预期写入、FPM TCP 暴露、MySQL 宿主机端口暴露、Caddy validate 失败、共享 Caddy/Beszel/80/443 异常、HTTP 冒烟失败或证据含敏感值。恢复顺序为：停止新 app/db，恢复 Caddyfile/Compose 与挂载组快照，只 recreate `jia-caddy`，验证共享服务，再按需停止苗木栈；不运行共享栈 `down`，不物理删除未知数据或迁移历史。回滚验证必须记录真实动作和退出码，失败则保持 blocked。

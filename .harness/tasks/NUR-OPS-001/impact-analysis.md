# NUR-OPS-001 影响分析

## 需求与当前事实

任务关联 `NFR-SEC-006` 与 `NFR-PERF-005`，属于 P0/Phase 1/L4 operations。仓库已包含完整 ShopXO 源码、`composer.json`、`app/`、`config/shopxo.sql` 和 `app/common.php`，固定上游版本为 ShopXO 6.9.0（上游提交由 Harness baseline 锁定）。当前工作分支的功能提交为 `aafdfdf7c`；最终发布必须使用通过独立审查的干净 release commit，而不是直接发布未提交工作区。

本次工作区还包含部署合同所需的 PHP `intl`/ICU 扩展、询价 HMAC external secret、FPM 环境传递、Compose secret、运行时环境检查和合同测试改动。它们只位于 `deploy/**`、`tests/ops/**` 和 `docs/operations/**`，不新增业务迁移实现；但 `deploy/docker/app/nursery-bootstrap.php` 会在发布时编排已批准的 NUR-FEAT-002/003/004 v1 前向迁移，因此本任务必须如实声明数据库变更执行和验证边界。

目标主机、SSH 端口、用户、主机指纹、部署根和 Caddy 根以 `task.json.remote_execution` 为唯一事实。主机当前状态、Caddy 版本/容器身份、80/443/8090、88、卷、GID 和 userns 在每次发布前重新只读核验；旧文档或聊天记录不能替代新证据。

## 当前调用链与数据

本地唯一工作区产生已审查提交，broker 通过仓库外 SSH 文件完成主机指纹校验，然后在 `/root/jia/miaomu` 解包同一 release。`miaomu` Compose 只运行 `app` 和 `db`，两者使用 internal backend 网络；FPM 通过命名 Unix socket 与现有 Caddy 连接，MySQL 不发布宿主机端口。Caddy 的候选配置只增加 `127.0.0.1:88`、public/uploads/socket 只读挂载和必要组权限，不创建 Web 服务。

运行时配置、数据库口令和 `PHP_NURSERY_INQUIRY_HMAC_KEY` 来自 `/etc/miaomu` 下仓库外受限文件；恢复合同使用 `/etc/miaomu-restore`。HMAC 文件只允许首次创建，之后只检查 owner/group/mode/size 元数据，绝不读取或输出值。数据库初始化是可丢弃的非生产测试库，商品/询价历史等真实业务数据不在本任务范围。镜像构建阶段从固定上游 dump 提取 schema-only 文件；运行时 bootstrap 先检查 information_schema 表数必须为 0，只执行 SET/DROP/CREATE 结构语句，然后写入最小系统配置和非 1 号禁用管理员占位，不导入任何上游 INSERT 记录。

## 影响范围

- **服务器与网关**：可能只 recreate 现有 `jia-caddy` 以增加三项只读挂载和 group 10001；不得 `down` 共享栈或改变 80/443 路由。失败时按快照恢复 Caddyfile、Compose、挂载和组权限。
- **应用运行时**：Dockerfile 增加 ICU/`intl`，FPM 只监听 Unix socket，应用不以 root 常驻、不挂 Docker socket；运行时写入范围限于 runtime、uploads、downloads。
- **数据库与数据**：本任务不新增迁移代码，但会在确认空/可丢弃测试库后导入固定上游基线，并通过 `nursery-bootstrap.php` 执行 catalog/favorite/inquiry v1 前向迁移。Catalog 写入受管分类/规格/参数和 `sxo_config` 台账，Favorite 创建 `sxo_goods_favor` 唯一索引并写台账，Inquiry 创建五张询价表/索引并写台账；插件安装/启用还会更新 `sxo_plugins`。每次执行前备份，失败只停止并重建可丢弃库或前向修复，禁止删除未知数据。
- **安全与隐私**：所有远程命令结构化、主机/路径受管、敏感参数拒绝；日志、证据和 Git 扫描不得出现私钥、口令、完整手机号、HMAC 值或生产配置。
- **性能**：环境指纹必须包含 Git release SHA、Caddy/PHP/MySQL 版本、配置哈希、数据集规模、并发、预热和样本数。没有实现或夹具的场景只记 blocked/not_run。
- **升级与回滚**：禁止 ShopXO 在线升级覆盖二开文件；回滚以提交、Compose/Caddy 快照、数据库/上传备份为边界，失败时停止新 app/db 并验证旧健康版本。迁移只前向修复，不执行 DROP/DELETE 回退。
- **迁移依赖**：实际 schema 定义仍由已批准任务的 `app/plugins/nursery/{catalog-v1.json,favorite-schema-v1.json,inquiry-schema-v1.json}` 与对应 `*Migration.php` 拥有；OPS 只锁定 `deploy/docker/app/nursery-bootstrap.php` 编排入口，不允许在发布现场绕过版本台账或调用 `config/shopxo.sql` 作为唯一迁移。

## 方案比较

1. **配置与现有服务**：复用现有 Caddy、Docker 和 Compose，使用回环 88；不在宿主机安装第二套 PHP/MySQL，也不增加 Nginx。
2. **插件/独立模块**：业务已集中在 `nursery` 插件；部署只维护 `deploy/**`、`tests/ops/**` 和运维文档，不把远程逻辑散落到业务控制器。
3. **核心适配**：不修改 ShopXO 核心。`intl` 是应用镜像运行依赖，不是业务核心改动；数据库迁移实现留在已批准的业务任务，本任务只执行其固定版本并验证结果。

选用两服务 Compose 加共享 Caddy 的原因是目标机已有 host-network Caddy，且用户明确要求复用；单独 Web 容器会引入第二网关和端口冲突。所有变更均由 L4 broker 的精确动作执行，避免现场自由命令扩大范围。

## 风险与边界

- **误触生产**：远程写入前必须由只读动作确认个人/测试环境；发现生产标记、真实业务数据或目标指纹变化立即停止。
- **共享网关回归**：候选 Caddyfile 必须先在现有镜像中 validate；只允许受管的 `jia-caddy` recreate，任何 80/443/Beszel 异常立即回滚。
- **密钥不可逆性**：HMAC 值改变会使历史手机号无法解密；脚本只创建一次并保留既有文件，仓库不保存值。
- **初始化数据损失**：只允许空/可丢弃测试库；schema bootstrap 在发现任意既有表时 fail-closed。共享 Caddy 配置仍需快照；数据库/上传深备份在当前个人测试主机上不作为自动门禁，若盘点发现非空或生产标记则停止并记录 blocked。
- **动作越界**：受管根固定为 `/root/jia/miaomu`、`/root/jia/caddy`、`/etc/miaomu`、`/etc/miaomu-restore`；禁止 shell、嵌套传输、未合同主机、敏感 CLI 参数和系统破坏动作。
- **工具缺口**：本地没有 PHP/Composer/Docker 时不把本地缺口转成通过；对应检查必须在目标应用容器/服务器真实执行并保留退出码。

## 预计文件

- `deploy/compose*.yaml`、`deploy/docker/app/**`、`deploy/stack-policy.json`：两服务、FPM socket、intl、secret 和恢复边界。
- `deploy/prepare_runtime_secrets.py`、`deploy/prepare_caddy_candidate.py`、`deploy/validate_release_inputs.py`：仅元数据/配置准备和合同校验，不输出密钥。
- `tests/ops/test_deployment_contract.py`、`tests/ops/environment_check.php`：离线合同与容器环境检查。
- `docs/operations/DEPLOYMENT.md`、`LOCAL_STACK.md` 及相关运维文档：Caddy-only 发布、备份、回滚和性能协议。
- `.harness/tasks/NUR-OPS-001/**`：唯一任务合同、计划、证据、审批和审查制品；不修改 Harness 策略或用户级配置。

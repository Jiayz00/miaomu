# NUR-OPS-003 实施证据

## 验收标准映射

- `AC-TASK-001`：通过离线合同验证。主/恢复 Compose 长期服务恰为 `app` 与 `db`，只使用 internal backend；app 非 root、无端口、FPM 仅创建 GID 10001/mode 0660 的命名卷 Unix socket；MySQL 无宿主机端口。配置/event/脚本 bind mount 固定为只读且 `create_host_path=false`，runtime/uploads/downloads/socket/db_data 固定为隔离命名卷，相关相对 bind 负变异均失败关闭。
- `AC-TASK-002`：通过离线合同验证。Caddy 合同只允许 `127.0.0.1:88`，只读挂载 public、uploads 和主 FPM socket，不挂 downloads/runtime/db；只放行 `index.php`、`admin.php`、`api.php`，拒绝安装器、隐藏路径、上传脚本、扩展/大小写/PATH_INFO 旁路及 `/download/**`。
- `AC-TASK-003`：通过文档合同验证。性能协议固定环境指纹、数据集、预热、并发、样本数、P50/P95、错误率和原始结果保存方式，并为商品列表、详情、收藏、询价、行为上报、30 日趋势和导出分别保留 L4 补测责任；未执行结果保持 `not_run`。
- 正式证据目录：`.harness/runs/NUR-OPS-003/20260713T214526669860Z-verify`。

## 自动测试证据

VERIFY_CONTRACT_SHA256: f53da5fb01e9eeaf042920bfbea71d3ebd500a08985b6531e701ac17464e4ba7

TEST_COMMAND: harness_selftest ["python", "scripts/harness_selftest.py"]
TEST_RESULT: harness_selftest exit_code=0

TEST_COMMAND: deployment_contract ["python", "tests/ops/test_deployment_contract.py"]
TEST_RESULT: deployment_contract exit_code=0

TEST_COMMAND: harness_remote_selftest ["python", "scripts/harness_remote_selftest.py"]
TEST_RESULT: harness_remote_selftest exit_code=0

- verify 汇总：`passed=3 failed=0 blocked=0`；执行前后 workspace fingerprint 均为 `33d3f97fff60f7d415303b93fa28c7abd3b174015734464d2984fd21a9968577`，控制面哈希均为 `386d1e5fb18d3150df3faf5a6c1c4ec794a0d1b7f92fbbd8ac288dcd5d708339`。
- `deployment_contract` 实际执行 35 项测试全部通过，覆盖分栈 generated event 状态、main/restore/both 外部校验、服务挂载及顶层卷 backing 负变异、bootstrap/steady、runtime sanitizer、Caddy 和 FPM 入口边界。
- `harness_selftest` 实际执行 60 项通过；Windows 无符号链接权限和 POSIX 专用用例共 2 项按平台条件跳过，命令整体退出码为 0，未把跳过能力表述为已验证。
- `harness_remote_selftest` 实际执行 54 项全部通过，验证远程 broker 的凭据引用、主机边界、动作白名单、release seal、输出限制和脱敏门禁。
- 额外离线检查：`python -B deploy/validate_release_inputs.py --contract-only` 退出码 0；Git for Windows `sh -n` 对四个项目 Shell 脚本退出码 0。它们是补充检查，不替代任务声明测试。

## 安全与运行流程证据

- release manifest schema v2 按 `generated_events.main`/`restore` 独立记录状态与哈希；主站稳态不再依赖尚未执行的恢复演练。
- MySQL bootstrap overlay 只用于空库阶段；文档明确必须删除该容器、移除 overlay，再用基础 Compose `up --force-recreate db`，并核验 steady health argv 与 restart policy，禁止使用不会更新容器配置的 `restart`。
- app 的受管初始化与 FPM 启动会先运行固定 runtime sanitizer。主栈只清理 cache/session/temp/config cache，恢复栈清空独立 runtime；脚本拒绝 symlink、非目录和动态清理根。
- 项目 wrapper 只声明不把 secret 内容写入 stdout/argv，并只传递 `_FILE` 路径；官方 MySQL entrypoint 是否临时物化环境变量明确留给 L4 以变量名存在性布尔证据验证，不作未验证断言。
- 顶层卷对象只允许固定 `name`，静态合同拒绝 `external`、`driver`、`driver_opts` 和额外键；实际 Driver/Options/Mountpoint/Compose labels 仍由 L4 在清理任何 restore runtime 前核验。

## 手工与页面证据

- 本任务没有可声明为通过的页面或服务器手工证据；所有运行态、HTTP 和浏览器结果保持 `not_run`。
- 独立静态审查已复核分栈 event、mount/volume、bootstrap recreate、runtime sanitizer 和 secret 表述，最终结论为可批准；正式合并结论仍由任务绑定的 merge reviewer 记录。

## 已知限制

- 本机没有 Docker、PHP、Composer、MySQL 和 Caddy，因此未执行 `docker compose config`、镜像 pull/build、Composer platform check、PHP lint、MySQL 初始化/恢复、FPM socket、Caddy validate/recreate、HTTP、浏览器或性能测试。
- 镜像候选 digest、目标 `linux/amd64` 平台摘要与 image ID 仍是待核验输入，不是运行证据。
- 未连接服务器、未修改现有 `jia-caddy`、未创建容器/卷、未监听 88，也未验证 `38.12.21.18:88` 公网不可达；全部由后续 L4 `NUR-OPS-001` 执行。
- 用户登录、收藏、询价和个人数据流程必须在 TLS 域名与真实运行栈完成后验证；回环 `127.0.0.1:88` 只能使用无个人数据的临时冒烟。

## 回滚证据

- 本任务只产生仓库内 `deploy/**`、`docs/operations/**` 和 `tests/ops/**` 制品，没有远端或数据状态需要回滚。
- 未部署回滚为还原本任务提交，并重跑 source-check、scope-check、三项声明测试和 contract-only。
- 真实服务器、数据库和共享 Caddy 回滚必须由后续 L4 合同使用发布前备份与精确动作执行；本任务没有声称完成远端回滚演练。

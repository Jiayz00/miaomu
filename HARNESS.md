# ShopXO 苗木项目 Harness 使用手册

本 Harness 只在当前仓库生效。它不安装全局 skill、不修改 `~/.codex/config.toml`，也不向用户目录注册 MCP 或 hook。

## 当前状态

- Harness：已可独立运行。
- ShopXO 源码：以 `python scripts/harness.py doctor` 的检测结果为准；源码未导入时，业务开发门禁保持关闭。
- 需求基线：`ShopXO苗木平台需求规格说明书_V1.0.md`。
- Harness 设计：`shopxo_nursery_harness_spec.md`。

当前完整 ShopXO 源码基线已恢复并由 `source-check` 固定；本机 PHP、Composer、MySQL 或 Docker 的缺口不得伪装为通过，应在受合同约束的目标环境执行真实检查。Harness 不关闭安全软件、不写全局排除项，也不保存 SSH 或应用密钥内容。

## 首次启用

1. 在 Codex 中将本仓库标记为 trusted project。
2. 审查并批准 `.codex/hooks.json` 中的项目 hook。Codex 会记录 hook 内容哈希；hook 修改后需重新审批。
3. 在仓库根目录运行：

```powershell
python scripts/harness.py project-check
python scripts/harness_selftest.py
python scripts/harness_remote_selftest.py
python scripts/harness.py doctor
python scripts/harness.py baseline
python scripts/harness.py source-check
```

类 Unix 环境也可使用 `./scripts/harness.sh`；Windows 可使用 `./scripts/harness.ps1`。

## ShopXO 源码接入

Harness 预期 ShopXO 源码与本文件位于同一仓库根目录，能够找到 `composer.json`、`app/`、`config/shopxo.sql`。导入或合并上游源码属于单独的事实核验步骤；不要让自动脚本覆盖本目录中的需求和 Harness 文件。

接入后先在完整、隔离的源码 checkout 中执行：

```powershell
python scripts/harness.py baseline
# 首次从“缺失源码”迁移时，单独以 baseline-only bootstrap 提交四份基线；不要混入业务代码或业务 Task ID
python scripts/harness.py source-check
python scripts/harness.py doctor --strict
```

将确认的上游 commit、Composer 内容、插件/迁移入口和数据库结构写入基线后，才可创建首个业务任务。host 上 PHP/MySQL 是否可用由 `doctor --strict` 与任务真实测试证明，不把机器绝对路径纳入可移植 freshness gate。

## 标准任务流程

```powershell
git switch -c feat/NUR-FEAT-001-public-price
python scripts/harness.py task-create NUR-FEAT-001 --title "商品公开参考价格" --risk L2 --requirement FR-DETAIL-001 --requirement BR-PRICE-002 --requirement AC-001
# 补全 task.json、需求摘录、影响分析、计划和测试计划，并指定 owner/reviewer；需要 release 审批时还要指定独立 release_approver
python scripts/harness.py task-transition NUR-FEAT-001 ready_for_analysis --by "负责人"
python scripts/harness.py task-check NUR-FEAT-001
python scripts/harness.py plan-check NUR-FEAT-001
python scripts/harness.py task-transition NUR-FEAT-001 awaiting_plan_approval --by "负责人"
# 自动审批任务先按下文最小 JSON schema 创建任务目录内 approval-plan.json；
# --agent-task 必须精确匹配 codex_role_bindings.plan，CODEX_THREAD_ID 由当前审查代理环境提供。
# 仅 manual_approvals.plan.required=true 时，由 task.json reviewer 执行：
python scripts/harness.py task-approval NUR-FEAT-001 plan --status approved --by "Codex-Review" --agent-task "/root/plan_review"
python scripts/harness.py task-transition NUR-FEAT-001 approved_for_implementation --by "负责人"
# 将任务合同、计划及计划审批提交到任务分支，确认工作区干净
python scripts/harness.py preflight NUR-FEAT-001
python scripts/harness.py task-transition NUR-FEAT-001 implementing --by "负责人"
# 实施 allowed_paths 内的变更
python scripts/harness.py scope-check NUR-FEAT-001
python scripts/harness.py task-transition NUR-FEAT-001 verifying --by "负责人"
python scripts/harness.py verify NUR-FEAT-001
# 根据 verify 输出补全 evidence.md；写入稳定 VERIFY_CONTRACT_SHA256，并为每项测试写 TEST_COMMAND 与 TEST_RESULT: <id> exit_code=0，再记录 acceptance ID 和限制。本地 run 目录可附加，但 CI 不依赖时间戳路径
python scripts/harness.py evidence-check NUR-FEAT-001
python scripts/harness.py task-transition NUR-FEAT-001 awaiting_review --by "负责人"
python scripts/harness.py review-pack NUR-FEAT-001
# 独立审查者完成 review.md，并准备 approval-merge.json，写入精确标记 REVIEW_RESULT: APPROVED
python scripts/harness.py task-approval NUR-FEAT-001 merge --status approved --by "Codex-Review" --agent-task "/root/merge_review"
# 补全 release-note.md；所有任务都必须记录发布前提、受控步骤、回滚和发布后验证
# 仅 manual_approvals.release.required=true 时执行；先准备 approval-release.json，release_approver 必须不同于 owner/reviewer
python scripts/harness.py task-approval NUR-FEAT-001 release --status approved --by "Codex-Release" --agent-task "/root/release_review"
# 该迁移会在 awaiting_review 内部执行完整的合并准备度预检查
python scripts/harness.py task-transition NUR-FEAT-001 approved_for_merge --by "独立审查者"
# 独立 CLI/CI release-check 只接受 approved_for_merge/closed，用于确认迁移没有被跳过
python -I -S -B scripts/harness.py release-check NUR-FEAT-001
# 合并完成且无需继续发布准备工作后：
python scripts/harness.py task-transition NUR-FEAT-001 closed --by "负责人" --reason "记录合并提交或 PR 编号"
```

任务文件位于 `.harness/tasks/<TASK_ID>/`。`task.json` 是 schema v2 机器合同；`codex_role_bindings` 始终存在，legacy/非自动任务可四项均为 `null` 以安全迁移旧历史，但 null binding 不能记录新的 `task-approval`。新审批必须锁定 implementation `{agent_task,thread_id}` 以及每个 required 审批阶段的 `{agent_task}`。implementation 与各审批 task 必须不同，release 与其余 task 均不同，plan/merge 可复用同一独立审查 task。Markdown 文件用于需求摘录、影响分析、计划、证据和独立审查；`workflow-history.json` 由 CLI 记录状态与审批事件。plan 批准绑定完整任务授权合同、执行策略、四份计划制品和已解决决策上下文；merge 绑定 review-pack、稳定工作区内容、evidence 与 verify contract；release 再绑定 merge 结果、review、release-note 和当前 remote contract，但不提前要求尚不存在的 release-seal。任一锁定内容变化都会使旧批准失效。preflight、状态与审批写入由 `.harness/state/workflow-locks/` 下的 per-task 锁串行化；所有任务还共享一个全局 active-state 锁，防止两个任务并发 preflight。锁的检查、过期回收和创建另由操作系统 advisory guard 串行化：Windows 使用持久 guard 文件，POSIX 锁定 `.harness/state` 目录描述符；进程异常退出时 guard 自动释放，owner 的 PID 与启动指纹用于识别崩溃和 PID 复用，避免 stale-lock 回收删除其他执行者的新锁。双文件更新会在 `.harness/state/workflow-transactions/` 中短暂写入恢复日志；这些运行目录均被 Git 忽略。不要直接补丁修改活动任务的 `task.json`，使用 `task-transition` 和 `task-approval`。

自动 `task-approval` 不按 actor 名称前缀猜测 Codex 身份，而是要求阶段 binding、精确 `--agent-task`、有效 `CODEX_THREAD_ID`、与 implementation 不同的 thread，以及任务目录内普通非链接 JSON：`approval-plan.json`、`approval-merge.json` 或 `approval-release.json`。最小字段固定为 `schema_version`、`task_id`、`stage`、`decision`、`actor`、`agent_task`、`codex_thread_id`、`result_marker`、`approval_context_sha256`、`reviewed_at`、`findings`、`summary`；缺失制品时 CLI 错误会给出当前 context SHA。CLI 自行计算制品 canonical SHA 和阶段 context SHA 写入历史，回放时重新验证，文件篡改或上下文漂移都会使门禁失败。这些字段仍只是 self-asserted audit context，不构成密码学身份；实现代理不得批准自己的输出。
进入 `closed` 或 `cancelled` 时，CLI 会清除属于该任务的本地 `active-task.json`；`blocked` 保留活动状态以便修复后按允许迁移恢复。
已有 active state 的任务不能再次 preflight 覆盖 `scope_base_commit`。需要重新定基时，先按状态机返回 `ready_for_analysis`，修订计划并重新审批。

如果状态迁移后遗留了活动状态，或 `active-task.json` 已损坏，不得手工删除。任务必须先处于 `ready_for_analysis`、`awaiting_plan_approval`、`blocked`、`closed` 或 `cancelled`，然后由合同中的 owner/reviewer/release_approver 执行：

```powershell
python scripts/harness.py state-recover NUR-FEAT-001 --by "负责人" --reason "说明本次恢复原因"
# 仅在已复核 JSON 损坏、格式无效、符号链接或目录联接时增加：
python scripts/harness.py state-recover NUR-FEAT-001 --by "负责人" --reason "说明损坏与恢复依据" --allow-invalid-state
```

恢复命令按 per-task → global 的锁顺序运行，并在 `.harness/state/recoveries/` 保留本地审计记录或原状态快照。

## 门禁分层

- 自动阻止：任务合同无效、未知或合同外需求编号、关联开放决策、保护分支、越权路径、缺少迁移/回滚声明、缺少真实测试证据。非 `NUR-HARNESS-*` 任务不能把 Harness 策略路径加入自身范围。
- 自动收集证据：工具版本、Git 差异、命令、退出码、测试输出、数据库和安全检查说明。
- 独立角色决定：需求冲突、远程发布、真实备份恢复、性能数值预算、ShopXO 核心修改、数据隐私口径及 L3/L4 合并。不同 Codex 代理可以承担这些角色，但不得由实现代理自批。

## 远程执行

仓库配置保持 `network_access=false`，不能自行打开通用网络。项目负责人明确授权的 L4 运行仍需由外层 Codex 会话/工具权限单独提供网络能力；即使外层已授权，Hook 也继续阻止直接运行 `ssh`、`scp`、`curl` 等客户端，服务器动作只能通过 `python -I -S -B scripts/harness.py remote-exec` 执行。

`remote_execution` 必须固定用户授权 task/thread、主机、端口、SHA256 主机指纹、用户 `.ssh` 下按文件名引用的 identity/known_hosts、非根部署目录、互不包含的受管根和精确结构化动作。broker 禁用 SSH config、agent、ProxyCommand/ProxyJump、端口转发、密码交互和任意 shell 字符串；私钥只做文件元数据检查，从不读取内容。先使用 `remote-actions` 只读列出合同动作。mutating 动作还要求独立 release approval、`approved_for_merge`、完整 release-check、干净工作区，以及审批提交后的 `release-seal` 与当前 Git HEAD 一致：

```powershell
python -I -S -B scripts/harness.py remote-actions NUR-OPS-001
python -I -S -B scripts/harness.py release-seal NUR-OPS-001
python -I -S -B scripts/harness.py remote-exec NUR-OPS-001 inventory_caddy
python -I -S -B scripts/harness.py remote-exec NUR-OPS-001 deploy_release --allow-mutating
```

每次执行都在 `.harness/runs/<TASK_ID>/` 写入有界、脱敏 JSON 证据。不得扩大到合同外目录、数据库或共享服务；变更失败后只能执行合同中已审查的回滚动作。

`remote-actions`、`remote-exec`、`release-seal` 和独立 `release-check` 必须由同时启用 `-I -S -B` 的 Python 启动。`-I` 隔离仓库与用户导入路径，`-S` 禁止自动加载 site，`-B` 禁止生成 bytecode；这可阻止 `scripts/json.py` 一类仓库文件遮蔽标准库，但不是 Python 可执行文件的平台签名或供应链证明。`scripts/harness.ps1` 与 `scripts/harness.sh` 会为这些命令自动添加三个标志。

broker 内部执行 release-check 时先稳定读取并核对 Git 中的 Harness 与 broker bytes，再通过仅存在于内存 `script_globals` 的对象身份上下文把已验证 broker module 交给 Harness。该内部入口不使用环境变量或 argv 作为信任信号；校验后磁盘 sibling 被替换或暂时不存在时，也不得重新读取它或接受其伪造输出。普通直接隔离 CLI 没有该私有上下文，仍按精确 sibling 路径加载。

## 项目级 Codex 能力

- `.codex/config.toml`：最小权限默认值和本地只读 MCP。
- `.codex/hooks.json`：会话提醒、危险命令和直接 shell 文件写入的前置阻止；仓库编辑使用 `apply_patch`，工作流写入使用 Harness CLI。
- `.agents/skills/`：任务实施与审查工作流。
- `AGENTS.md`：所有代理的持久入口规则。

本地 MCP 不访问网络、不写业务数据，工具包括 `harness_status`、`requirements_search`、`requirement_get` 和 `task_get`。

仓库根及其祖先、所有 Harness、任务、运行证据和报告路径都禁止通过符号链接、Windows 目录联接或未知 reparse point 重定向；Python 3.11+ 使用 `lstat`/Windows reparse 属性执行同一检查。`verify` 使用 `shell=False`；代码将单流捕获上限硬限制为 1 MiB、单测试超时硬限制为 3600 秒，项目配置只能保持或收紧这些边界。测试超时或输出超限均失败；required test 运行前后还会比较业务工作区与 Harness/control-plane 哈希。

数据库任务不能把 `config/shopxo.sql` 当作已有站点的唯一增量迁移。修改全量安装 SQL 时必须同时提供版本化 forward migration；仅针对从未发布、没有既有实例的新装基线，可在 `database_change.fresh_install_baseline_exception` 中写明理由并经 L4 plan 审批使用一次性例外。

## 开放需求决策

`.harness/requirements-decisions.json` 中 `status = open` 的决策允许继续分析和计划，但会阻止 `approved_for_implementation`、`preflight` 及后续实现门禁。定案时必须记录结论、独立批准角色和日期，再将状态改为 `resolved`。

## 运行产物

- `.harness/baselines/`：版本化事实基线。
- `scripts/harness_selftest.py`：项目级状态、审批、事务、并发与 baseline 回归测试。
- `scripts/harness_remote.py`：无独立操作 CLI 的远程 broker，只由 `harness.py` 调用。
- `scripts/harness_remote_selftest.py`：不联网的远程合同、SSH 固定与脱敏回归测试。
- `.harness/runs/`：本地执行日志，默认不提交大体积输出。
- `.harness/reports/`：审查包。
- `.harness/core-changes/REGISTER.md`：ShopXO 核心修改登记。

如 Harness 与实际 ShopXO 版本冲突，以已核验的源码和数据库事实为准，但必须通过变更任务更新 Harness，不能静默绕过。

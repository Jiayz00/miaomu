# ShopXO 苗木项目 Harness 使用手册

本 Harness 只在当前仓库生效。它不安装全局 skill、不修改 `~/.codex/config.toml`，也不向用户目录注册 MCP 或 hook。

## 当前状态

- Harness：已可独立运行。
- ShopXO 源码：以 `python scripts/harness.py doctor` 的检测结果为准；源码未导入时，业务开发门禁保持关闭。
- 需求基线：`ShopXO苗木平台需求规格说明书_V1.0.md`。
- Harness 设计：`shopxo_nursery_harness_spec.md`。

当前 Windows 工作区中，`app/common.php` 从固定上游 blob 恢复后会被外部实时扫描再次删除；本机也尚无 PHP、Composer 和 MySQL。不要由 Harness 关闭安全软件或写全局排除项。先在 WSL/Linux、隔离虚拟机或干净 CI checkout 中恢复完整源码，执行一次只修改 `.harness/baselines/**` 的 bootstrap 刷新（PR/分支名不要携带业务 Task ID，因为 bootstrap CI 会跳过旧 `source-check`），审查并提交新基线；随后再执行 `NUR-OPS-001` 固化 PHP 8.0.2+、Composer、MySQL 8.0 与可复现开发环境，并运行 `source-check`、`doctor --strict`。

## 首次启用

1. 在 Codex 中将本仓库标记为 trusted project。
2. 审查并批准 `.codex/hooks.json` 中的项目 hook。Codex 会记录 hook 内容哈希；hook 修改后需重新审批。
3. 在仓库根目录运行：

```powershell
python scripts/harness.py project-check
python scripts/harness_selftest.py
python scripts/harness.py doctor
python scripts/harness.py baseline
python scripts/harness.py source-check
```

类 Unix 环境也可使用 `./scripts/harness.sh`；Windows 可使用 `./scripts/harness.ps1`。

## ShopXO 源码接入

Harness 预期 ShopXO 源码与本文件位于同一仓库根目录，能够找到 `composer.json`、`app/`、`config/shopxo.sql`。导入或合并上游源码属于单独的人工确认步骤；不要让自动脚本覆盖本目录中的需求和 Harness 文件。

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
# 仅 manual_approvals.plan.required=true 时，由 task.json reviewer 执行：
python scripts/harness.py task-approval NUR-FEAT-001 plan --status approved --by "独立审查者"
python scripts/harness.py task-transition NUR-FEAT-001 approved_for_implementation --by "独立审查者"
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
# 独立审查者完成 review.md，写入精确标记 REVIEW_RESULT: APPROVED
python scripts/harness.py task-approval NUR-FEAT-001 merge --status approved --by "独立审查者"
# 补全 release-note.md；所有任务都必须记录发布前提、人工步骤、回滚和发布后验证
# 仅 manual_approvals.release.required=true 时执行；release_approver 必须不同于 owner/reviewer
python scripts/harness.py task-approval NUR-FEAT-001 release --status approved --by "独立发布审批者"
# 该迁移会在 awaiting_review 内部执行完整的合并准备度预检查
python scripts/harness.py task-transition NUR-FEAT-001 approved_for_merge --by "独立审查者"
# 独立 CLI/CI release-check 只接受 approved_for_merge/closed，用于确认迁移没有被跳过
python scripts/harness.py release-check NUR-FEAT-001
# 合并完成且无需继续发布准备工作后：
python scripts/harness.py task-transition NUR-FEAT-001 closed --by "负责人" --reason "记录合并提交或 PR 编号"
```

任务文件位于 `.harness/tasks/<TASK_ID>/`。`task.json` 是机器合同，Markdown 文件用于需求摘录、影响分析、计划、证据和人工审查；`workflow-history.json` 由 CLI 记录状态与审批事件。plan 批准事件会绑定 `requirement.md`、`impact-analysis.md`、`implementation-plan.md`、`test-plan.md` 以及任务关联的已解决需求决策上下文，preflight 再将这些哈希写入 active state。任一计划文件或关联决策变化都会使旧批准失效。preflight、状态与审批写入由 `.harness/state/workflow-locks/` 下的 per-task 锁串行化；所有任务还共享一个全局 active-state 锁，防止两个任务并发 preflight。锁的检查、过期回收和创建另由操作系统 advisory guard 串行化：Windows 使用持久 guard 文件，POSIX 锁定 `.harness/state` 目录描述符；进程异常退出时 guard 自动释放，owner 的 PID 与启动指纹用于识别崩溃和 PID 复用，避免 stale-lock 回收删除其他执行者的新锁。双文件更新会在 `.harness/state/workflow-transactions/` 中短暂写入恢复日志；这些运行目录均被 Git 忽略。不要直接补丁修改活动任务的 `task.json`，使用 `task-transition` 和 `task-approval`。

`task-approval` 只是将人工声明写入仓库，不能证明真实身份；最终审批仍以 Git 平台的受保护分支、审查记录和账号身份为准。
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
- 仅人工决定：需求冲突、生产发布、真实备份恢复、性能数值预算、ShopXO 核心修改、数据隐私口径及 L3/L4 合并。

## 项目级 Codex 能力

- `.codex/config.toml`：最小权限默认值和本地只读 MCP。
- `.codex/hooks.json`：会话提醒、危险命令和直接 shell 文件写入的前置阻止；仓库编辑使用 `apply_patch`，工作流写入使用 Harness CLI。
- `.agents/skills/`：任务实施与审查工作流。
- `AGENTS.md`：所有代理的持久入口规则。

本地 MCP 不访问网络、不写业务数据，工具包括 `harness_status`、`requirements_search`、`requirement_get` 和 `task_get`。

仓库根及其祖先、所有 Harness、任务、运行证据和报告路径都禁止通过符号链接、Windows 目录联接或未知 reparse point 重定向；Python 3.11+ 使用 `lstat`/Windows reparse 属性执行同一检查。`verify` 使用 `shell=False`；代码将单流捕获上限硬限制为 1 MiB、单测试超时硬限制为 3600 秒，项目配置只能保持或收紧这些边界。测试超时或输出超限均失败；required test 运行前后还会比较业务工作区与 Harness/control-plane 哈希。

数据库任务不能把 `config/shopxo.sql` 当作已有站点的唯一增量迁移。修改全量安装 SQL 时必须同时提供版本化 forward migration；仅针对从未发布、没有既有实例的新装基线，可在 `database_change.fresh_install_baseline_exception` 中写明理由并经 L4 plan 审批使用一次性例外。

## 开放需求决策

`.harness/requirements-decisions.json` 中 `status = open` 的决策允许继续分析和计划，但会阻止 `approved_for_implementation`、`preflight` 及后续实现门禁。人工定案时必须记录结论、批准人和日期，再将状态改为 `resolved`。

## 运行产物

- `.harness/baselines/`：版本化事实基线。
- `scripts/harness_selftest.py`：项目级状态、审批、事务、并发与 baseline 回归测试。
- `.harness/runs/`：本地执行日志，默认不提交大体积输出。
- `.harness/reports/`：审查包。
- `.harness/core-changes/REGISTER.md`：ShopXO 核心修改登记。

如 Harness 与实际 ShopXO 版本冲突，以已核验的源码和数据库事实为准，但必须通过变更任务更新 Harness，不能静默绕过。

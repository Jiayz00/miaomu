# ShopXO 苗木平台项目级 Harness 规范

版本：2.0
状态：已落地，可执行
适用目录：本仓库根目录及其子目录
需求基线：`ShopXO苗木平台需求规格说明书_V1.0.md`
ShopXO 上游：`https://github.com/gongfuxiang/shopxo.git`
固定基线：`master@d1825c5404054b535255d8fcad675a5dae0ab633`（仓库标识 v6.9.0，2026-06-28；上游没有 v6.9.0 tag）

---

## 1. 文档目标

本规范定义一套只在当前仓库生效的开发 Harness，用于将 ShopXO 二次开发为个人苗木网站，并约束 Codex 与人工开发的需求追踪、代码范围、ShopXO 扩展边界、数据变更、测试证据和发布审批。

本规范不再只描述“未来应创建什么”，而是与仓库中的真实文件一一对应：

- `AGENTS.md`：代理入口；
- `.codex/config.toml`：项目级 Codex 配置和 MCP；
- `.codex/hooks.json`：项目级生命周期 Hook；
- `.agents/skills/`：项目级 Skills；
- `.harness/`：规则、任务、决策、基线和运行状态；
- `scripts/harness.py`：可执行门禁；
- `.github/workflows/harness.yml`：最终 CI 门禁。

所有定义、脚本和 Skill 均保存在仓库内。仓库信任状态、Hook 内容哈希审批以及外部 MCP 的 OAuth/令牌可能由 Codex 或操作系统保存在用户级安全存储中；Harness 不自动修改这些用户级状态，也不承诺“机器上绝对没有任何全局状态”。

---

## 2. V1 的关键修正

V1 的业务边界基本正确，但无法直接执行。本版完成以下修正：

1. 增加阶段 -1：先把当前目录建成 ShopXO 下游仓库并固定上游提交。
2. 将 YAML 配置和任务合同改为 JSON，保证 Python 标准库即可解析和校验。
3. 将 V1 过长且职责重叠的任务制品清单和 16 状态流程收敛为必要文档和简化状态机。
4. 增加 `.codex/`、`.agents/skills/`、项目 MCP 与 Hook，明确各层强制力。
5. 增加机器可读的开放需求决策；有冲突的需求不得由代理自行解释。
6. 区分永久业务不变量、当前阶段目标、P1/P2 能力和待决策项。
7. 不再假设 `app/plugins/nursery/` 是已验证目录；插件布局以固定版本的真实示例为准。
8. 将 ShopXO 核心删除、收藏唯一性、搜索日志复用和数据库升级方式纳入事实基线。
9. 运行日志默认不进入 Git，只提交脱敏摘要。
10. 明确 Hook 是快速反馈，CI 才是最终门禁；命令字符串正则不是完整安全边界。

---

## 3. 当前仓库事实基线

### 3.1 已确认事实

- 默认分支：`master`。
- 固定提交：`d1825c5404054b535255d8fcad675a5dae0ab633`。
- `composer.json` 声明 PHP `>=8.0.0`；`public/core.php` 和 Composer 平台检查实际要求至少 PHP 8.0.2。
- 上游安装页面仍存在较旧的 PHP 版本提示，环境判断不能只读安装页面文案。
- 项目使用 ThinkPHP，`vendor/` 和大量静态产物已提交到上游仓库。
- 上游没有项目级 PHPUnit 测试套件、业务测试目录或 GitHub Actions CI；搜索到的测试主要来自 `vendor/`，不得当成 ShopXO 业务测试。
- 上游没有前端 Node 构建基线，现有静态资源直接提交。
- 数据库基线是 `config/shopxo.sql`；插件/扩展通常使用安装、更新、卸载 SQL，而不是统一 migration 框架。
- 可复现开发环境以 MySQL 8.0 为推荐基线；Redis 可选，默认可使用文件缓存。
- 核心仓库的 `app/plugins/` 仅包含占位文件，不能从核心仓库推断完整插件目录结构。
- `GoodsService::GoodsDelete` 会物理删除商品、规格、参数、相册等数据；`plugins_service_goods_delete` 在删除处理之后触发，无法单靠该 Hook 实现“删除前转逻辑删除”。
- 商品收藏当前没有数据库 `(user_id, goods_id)` 唯一约束，收藏服务也没有可直接依赖的专用 Hook。
- 上游已有 `sxo_search_history` 和搜索记录逻辑；新增 `sxo_search_log` 前必须做复用/迁移分析，不能重复建表。

### 3.2 当前环境阻塞

本机能够检出绝大多数上游文件，但 `app/common.php` 恢复后约 0.2 秒内会被外部实时扫描删除，当前工作树显示该上游文件被删除。固定 commit 的 Git blob 与 GitHub raw 内容一致；v6.9.0 新增的插件包恶意 PHP 检测代码集中包含大量 WebShell 关键字，可能触发启发式误报，但这不是正式安全背书。Harness 将其记录为环境阻塞：

- `doctor`：警告；
- `doctor --strict`：失败；
- 业务任务：在该文件恢复并验证前不得声称 ShopXO 可运行。

不得由 Harness 自动为安全软件添加目录排除，也不得提交该删除。

对象证据：Git blob `74422022b2f384c1c97e3eafabd946d2bb5ec219`，文件 SHA-256 `c9a5c68abbcf2544723a52b125a055ec69f9f21d14473e9437e64838ff708324`。实际运行和 PHP lint 优先放到 WSL/Linux、隔离 VM 或 CI。

### 3.3 基线状态枚举

所有发现项只能使用：

- `confirmed`：已从当前 commit、命令或数据库验证；
- `unknown`：尚未核实；
- `not_available`：当前版本不存在；
- `blocked`：因权限、环境或依赖无法验证。

基线必须包含 schema 版本、生成时间、source commit 和失效条件。`repository.json` 还必须锁定配置的 upstream、实际 upstream、ShopXO 版本、固定 commit 与必需源码路径状态的事实哈希；`toolchain.json` 锁定 Composer 文件内容，`database.json` 以 UTF-8/LF 规范化方式锁定 `config/shopxo.sql` 与升级入口文件。切换上游 commit、PHP、数据库、插件版本、Composer 内容、迁移入口或必需源码状态后必须重跑 `baseline`，并以 `source-check` 验证可移植基线新鲜度。

---

## 4. 产品边界

### 4.1 项目定位

系统只服务一个苗木经营主体，核心能力是：

- 苗木分类、搜索、筛选、列表和详情；
- 图片、视频、规格、参数与公开参考价格；
- 注册登录、用户中心和收藏；
- 结构化询价、管理员回复和历史状态；
- 流量、注册、商品、搜索、收藏、询价和趋势分析。

### 4.2 永久业务不变量

- 商品在询价前公开展示参考价格。
- 询价回复价格不覆盖商品公开参考价格。
- 收藏用于保存商品，收藏与询价互不作为前置条件。
- 用户只能访问自己的收藏、询价和个人数据。
- 商品下架或逻辑删除不得破坏历史收藏、询价快照、回复和统计。
- 询价必须保存必要商品、规格、价格和需求快照。
- 回复、状态变化和关键管理员操作必须保留历史与审计。
- PV 按事件次数，UV 按 `visitor_id` 去重；IP 不是唯一访客标识。
- 事件数据不得存储密码、验证码、完整手机号或不必要的询价正文。

### 4.3 排除范围 PX

不得新增、重新启用或作为苗木主流程依赖：

- 供应商、多商户、独立店铺、分销、代理商；
- 购物车、在线订单、支付、退款售后；
- 会员等级、积分、优惠券、拼团、秒杀、砍价；
- 直播、配送结算、复杂进销存和财务结算。

ShopXO 上游保留这些源码不构成失败。验收必须检查目标用户是否看不到入口、无法访问路由/API、没有权限，而不是物理删除底层代码。

### 4.4 P0、P1 与待决策

- P0/P1/P2 仍以需求文档编号为准。
- P1 功能不得被写成阻塞全部 P0 的永久门禁。
- 需求文档中的冲突进入 `.harness/requirements-decisions.json`。
- 相关决策为 `open` 时，任务不能进入 `approved_for_implementation`。

当前开放决策包括：导出边界、媒体分析优先级、搜索采集/分析/预警边界、价格历史优先级、无编号 P1、询价状态机、重复询价窗口和首次回复指标口径。

---

## 5. Harness 强制力分层

### 5.1 指导层

- `AGENTS.md`：持久项目指令和路由。
- `.agents/skills/shopxo-nursery-task`：需求到实现工作流。
- `.agents/skills/shopxo-nursery-review`：独立审查工作流。
- 产品、架构和需求文档：事实与设计依据。

指导层能约束代理行为，但不是不可绕过的技术安全边界。

### 5.2 运行期层

- 项目 `sandbox_mode = "workspace-write"`；
- 仓库沙箱保持 `network_access=false`；只有项目负责人明确授权、外层会话另行具备网络权限且带锁定 `remote_execution` 的 L4 operations 任务可由 broker 访问远端，Hook 继续阻止原始网络客户端；
- `PreToolUse` Hook 阻止明显危险命令、用户级 Codex 配置修改和未授权补丁；
- `SessionStart` Hook 注入项目工作流提醒；
- `preflight` 锁定任务授权字段哈希并生成本地活动任务状态。

Hook 需要仓库被信任，并需要用户审查/批准内容哈希。Hook 脚本修改后应重新审批。

### 5.3 权威门禁层

- Harness CLI 对任务、需求、开放决策、路径、测试和证据做确定性检查；
- CI 从受信任的工作流执行相同检查；
- Git 平台分支保护、独立代理审查和验证证据决定合并；
- 远程迁移和发布由不同于 owner/reviewer 的 release 代理在 L4 合同内放行。

Hook 不能替代沙箱、操作系统权限、CI 或独立审查。

---

## 6. 项目目录

```text
.
├─ AGENTS.md
├─ HARNESS.md
├─ shopxo_nursery_harness_spec.md
├─ ShopXO苗木平台需求规格说明书_V1.0.md
├─ .codex/
│  ├─ config.toml
│  ├─ hooks.json
│  └─ hooks/harness_guard.py
├─ .agents/skills/
│  ├─ shopxo-nursery-task/
│  └─ shopxo-nursery-review/
├─ .harness/
│  ├─ CONSTITUTION.md
│  ├─ harness.json
│  ├─ requirements-decisions.json
│  ├─ baselines/
│  ├─ templates/
│  ├─ schemas/task.schema.json
│  ├─ tasks/
│  ├─ runs/
│  ├─ reports/
│  ├─ state/
│  ├─ mcp/server.py
│  └─ core-changes/REGISTER.md
├─ docs/
│  ├─ product/
│  └─ architecture/
├─ scripts/
│  ├─ harness.py
│  ├─ harness_remote.py
│  ├─ harness_remote_selftest.py
│  ├─ harness_selftest.py
│  ├─ harness.ps1
│  └─ harness.sh
├─ .github/
│  ├─ pull_request_template.md
│  └─ workflows/harness.yml
└─ ShopXO 原生 app、config、public、vendor、composer.json 等
```

不再为了目录完整性创建大量空策略和报告模块。职责相同的文件只保留一份事实源。

---

## 7. 分阶段实施

### 阶段 -1：下游仓库和上游固定

完成项：

- 当前目录成为 Git 下游仓库根目录；
- `upstream` 指向 `gongfuxiang/shopxo`；
- 工作分支为 `nursery/main`；
- 上游 commit 固定为 `d1825c5...`；
- 需求和 Harness 与 ShopXO 源码位于同一根目录。

退出条件：上游来源、commit、工作树异常和本地覆盖文件均可追溯。

### 阶段 0：事实发现

执行 `doctor` 和 `baseline`，确认：

- Git、PHP、Composer、数据库和运行环境；
- ShopXO 版本、缺失文件和当前差异；
- 真实插件、Hook、删除、收藏、搜索和 SQL 机制；
- 现有测试和 CI；
- 需要人工解决的阻塞。

阶段 0 对业务源码只读，但允许写 `.harness/baselines/`。

### 阶段 1：Harness 内核

建立规则、项目配置、Skills、Hooks、本地 MCP、JSON 任务合同、CLI 和 CI。该阶段允许使用 bootstrap 例外，不触碰苗木业务代码。

### 阶段 2：ShopXO 可运行基线

在项目负责人授权并由独立 Codex 角色复核的开发环境中恢复完整源码，安装 PHP 8.0.2+ 与 Composer，准备测试数据库，验证安装/启动、管理员登录、首页、商品列表和详情。

退出条件：至少一组真实 ShopXO 冒烟检查可运行，缺失项不再伪装为通过。

### 阶段 3：苗木业务里程碑

按需求文档顺序实施：

1. 基础改造与公开价格；
2. 用户与收藏；
3. 询价；
4. 流量和每日汇总；
5. 数据看板；
6. P1 增强。

每个里程碑必须由独立任务组成，不能用 Harness bootstrap 例外修改业务代码。

### 阶段 4：生产准备

部署环境、HTTPS、容量、媒体限制、隐私、通知渠道、备份恢复、性能预算和管理员角色由独立角色确认。用户明确授权后，不同 Codex 代理可承担 owner/reviewer/release_approver；远程动作仍只能由 L4 `remote_execution` 合同执行。

---

## 8. 任务合同

### 8.1 格式

任务合同使用 `.harness/tasks/<TASK_ID>/task.json`。使用 JSON 的原因是 Python 标准库可以可靠解析，不需要为 Harness 自身引入 PyYAML/jsonschema 运行依赖。

同一任务目录还包含 `workflow-history.json`、`requirement.md`、`impact-analysis.md`、`implementation-plan.md`、`test-plan.md`、`evidence.md`、`review.md`、`release-note.md`，以及自动审批时使用的 `approval-plan.json`、`approval-merge.json`、`approval-release.json`。审批 JSON 必须是任务目录内普通非链接文件，不能经符号链接或目录联接重定向。

任务编号：

```text
NUR-FEAT-001
NUR-BUG-001
NUR-UI-001
NUR-DATA-001
NUR-SEC-001
NUR-OPS-001
NUR-DOC-001
NUR-REFACTOR-001
NUR-HARNESS-001
```

### 8.2 必要字段

- `requirement_ids` 和 `decision_ids`；
- `priority`、`phase`、`risk_level`；
- `in_scope`、`out_of_scope`；
- `allowed_paths`、`forbidden_paths`；
- `shopxo_core_change`；
- `database_change`；
- `acceptance_criteria`，每项包含需求映射和可判定描述；
- `required_tests`，命令必须是参数数组；
- `manual_approvals`；
- `codex_role_bindings`：schema v2 必填；legacy/非自动任务可全部为 `null` 以回放旧历史，但记录任何新审批前必须迁移为非 null binding；自动任务锁定 implementation task/thread 和各 required 审批阶段 agent task；
- `owner`、独立 `reviewer`，以及需要发布审批时与二者不同的 `release_approver`。

自动审批的 implementation task 必须与 plan/merge/release 不同，release 还必须与 plan、merge 都不同；plan 与 merge 可以由同一独立审查 task 承担。required release 不得使用 `null` binding。绑定是不可变合同的一部分。

`task-check` 校验 `priority`/`phase` 的取值，`plan-check` 要求 `requirement.md` 记录与 task.json 一致的 `PRIORITY`/`PHASE` 标记；具体路由依据仍是需要人工审查的需求解释，遵循项目 Skill 的 `requirement-routing.md`。Harness 不假装能从长篇需求文字自动证明路由正确；跨阶段或优先级冲突必须进入 `requirements-decisions.json` 后再批准实现。

验收证据的唯一事实源是任务目录中的 `evidence.md`。它必须逐项引用 acceptance ID、`verify` 生成的稳定 `VERIFY_CONTRACT_SHA256`，并为每个 required test 记录 `TEST_COMMAND: <id> <argv JSON>` 与 `TEST_RESULT: <id> exit_code=0`，另含手工证据与已知限制；可附本地运行目录，但独立 CI 不要求预知时间戳目录。`task.json` 不重复存储可变证据路径。

`database_change` 必须声明受影响表、迁移路径、回滚和验证。`config/shopxo.sql` 是全量安装基线，不能作为唯一 forward migration；只有从未发布且不存在既有实例的 fresh-install 基线任务，才能设置 `fresh_install_baseline_exception.requested=true`、写明具体理由，并按 L4 任务接受独立 plan/release 门禁。

### 8.3 简化状态机

```text
draft
→ ready_for_analysis
→ awaiting_plan_approval
→ approved_for_implementation
→ implementing
→ verifying
→ awaiting_review
→ approved_for_merge
→ closed
```

异常状态：`blocked`、`cancelled`。

状态只能通过 `task-transition` 按代码与 `.harness/harness.json` 共同固定的安全边更新；`closed`、`cancelled` 无出边，配置不能新增跳阶段边。历史从 `draft` 重放，进入 `approved_for_implementation` 必须已有所需 plan 批准事件，进入 `approved_for_merge` 必须已有 merge 及所需 release 批准事件。迁移到 `approved_for_merge` 时，`task-transition` 会在仍处于 `awaiting_review` 的事务内调用仅供迁移使用的发布准备度预检查；独立 CLI 和 CI 的 `release-check` 不启用该例外，只接受已经进入 `approved_for_merge` 或 `closed` 的任务。`verify`、`evidence-check`、`review-pack` 和 `release-check` 分别校验当前阶段，CI 使用显式 base ref 时也不能绕过状态门禁。

### 8.4 授权锁定

计划批准事件先锁定规范化的完整任务授权合同与执行策略，并对 `requirement.md`、`impact-analysis.md`、`implementation-plan.md` 和 `test-plan.md` 计算制品 SHA-256，同时计算任务关联的已解决需求决策上下文哈希。`preflight` 再把同一组哈希与计划审批上下文锁定到 `.harness/state/active-task.json`。首次进入 `implementing` 前，任一授权字段、远程目标/动作、计划制品或关联决策变化都会使旧 plan 审批失效，必须重新审查并运行 `preflight`。任务历史已进入 `implementing` 后，仅四份计划制品漂移降为 warning，允许在受控恢复活动状态后重新 `preflight`，但必须由后续独立 merge 代码/功能审查重新核验。任务合同、执行策略、需求决策上下文、远程目标或动作漂移仍失败关闭并要求重做 plan 审批；L4 的独立 release 审批、release seal、远程合同、备份与回滚门禁不变。已有 active state 不能被再次 preflight 覆盖并改写 `scope_base_commit`。生命周期状态、`evidence.md` 及合并/发布审批结果是受控后置内容，只能通过 Harness CLI 或指定证据文件更新。

任务文件和审批字段仍是仓库内容，哈希与 Codex agent task/thread 只能提供审计关联，不能单独证明密码学身份。实现、审查和发布代理必须在合同与实际协作记录中分离，最终信任由独立代理输出、验证证据、Git 平台记录和受保护分支共同提供。

任务与历史使用项目本地 write-ahead transaction journal 防止双文件半提交，并以 per-task 原子锁串行化 preflight、状态与审批写入；所有任务再共享一个全局 active-state 锁，确保跨任务并发 preflight 最多一个成功。锁文件的检查、失效判定、过期回收与新建必须在操作系统 advisory guard 内完成：Windows 使用持久 guard 文件，POSIX 锁定稳定的 `.harness/state` 目录描述符；guard 由进程退出自动释放，禁止以未串行化的“先读路径、后 unlink”方式回收旧锁。owner 同时记录 PID 与进程启动指纹，避免崩溃后的 PID 复用把残锁永久误认成存活。中断后，下一次访问该任务的 Harness 命令只在磁盘内容仍匹配事务原值或目标值时自动完成或回滚；发现外部冲突时拒绝覆盖并要求人工审查。损坏或遗留的 `active-task.json` 只能通过 `state-recover` 受控清理：校验安全任务状态、合同角色和具体原因，对无效状态要求显式 `--allow-invalid-state`，并保留本地恢复记录/快照。

---

## 9. 风险等级

| 等级 | 示例 | 最低要求 |
|---|---|---|
| L0 | 纯文档 | 文档/链接检查 |
| L1 | 文案、样式、可逆菜单配置 | 语法检查、页面证据、基础回归 |
| L2 | 普通服务、接口、展示功能 | 服务/API 测试、页面验证、独立审查 |
| L3 | 用户权限、询价状态、统计口径、价格历史、数据库变更、个人数据导出 | 授权/迁移/回滚/数据对账、独立审查 |
| L4 | 认证基础、框架核心、远程迁移、破坏性数据操作 | 专项设计、备份恢复演练；plan/merge 由 reviewer，release 必须由不同于 owner/reviewer 的第二代理审批；远程动作必须有锁定合同 |

固定“最多修改 20 个文件”不作为硬门禁，只能作为审查提示。对个人项目，L0/L1 不强制 Worktree；代码和数据任务必须使用任务分支。

---

## 10. ShopXO 修改边界

### 10.1 优先顺序

```text
配置/菜单/权限
→ 现有服务
→ 当前 commit 中实际存在且时序满足要求的 Hook
→ 依据真实插件样例建立 nursery 插件
→ 独立模块
→ 小范围核心适配
→ 大规模核心修改（默认禁止）
```

影响分析必须记录已检查的替代方案，不能只写“使用插件更好”。

### 10.2 已知高风险点

- 商品删除当前为物理删除，且删除 Hook 时序过晚；逻辑删除设计不能靠简单 Hook 假设解决。
- 收藏缺少数据库唯一约束；必须同时考虑并发、已有重复数据和唯一索引迁移。
- 收藏服务缺少专用 Hook；增强方案可能需要独立服务、控制器适配或经审批的核心切入点。
- 搜索已有历史表和记录逻辑；新增分析应优先复用或扩展，避免双写和重复口径。
- 核心仓库没有完整插件样例；插件目录和 install/update/uninstall SQL 必须基于实际可安装插件再次验证。
- `vendor/**` 是保护路径，即使上游提交了 vendor，也不得在苗木任务中直接手改第三方包。

### 10.3 核心登记

核心修改写入 `.harness/core-changes/REGISTER.md`，至少说明：

- Task ID 与上游基线；
- 修改路径；
- 配置、服务、Hook、插件为何不足；
- 升级冲突风险；
- 回滚方式；
- 独立审查者和状态。

登记必须是唯一 Task ID 的完整八列表格行：上游基线精确匹配固定 commit，Paths 逐项覆盖任务声明，替代方案不足、升级风险和回滚列不得为空，Reviewer 匹配任务合同且 Status 为 `approved`。

---

## 11. 数据库规范

- 先以实际 `config/shopxo.sql` 和测试数据库确认表名、字段和索引。
- `config/shopxo.sql` 仅代表 fresh install；已有站点升级必须另有版本化 forward migration/update 路径。除经 L4 plan 审批的、明确没有既有实例的 fresh-install 例外外，不得只修改该全量 SQL。
- 适配 ShopXO 的插件 install/update/uninstall SQL 机制；不得假设存在 Laravel/Doctrine 风格 migration。
- 迁移必须可重复执行或明确一次性前置条件。
- 生产回滚不强制执行破坏性 down；可以使用向前修复、备份恢复或兼容回退，但必须在任务中选择并验证。
- 商品、收藏、询价、事件和日汇总的唯一约束与索引必须有测试。
- 删除、状态和快照历史不能被普通更新覆盖。
- 数据库脚本执行结果必须核验实际 schema/数据；不能只相信服务返回“成功”。

---

## 12. 安全、隐私与统计门禁

### 12.1 任务必须声明并执行的检查

Harness 自动校验测试命令、退出码、证据完整性、SQL/核心声明、依赖清单授权和基础密钥/调试扫描；它不会仅靠正则自动证明 IDOR、限流、隐私或统计口径正确。下列项目必须按关联需求写入 `required_tests`、手工验收和独立审查证据：

- IDOR：用户 A 不能通过修改 ID 访问用户 B 的收藏和询价。
- 手机号默认脱敏，查看完整值需要权限和审计。
- 文件上传检查扩展名、MIME、大小、数量、随机文件名和可执行内容。
- 注册、登录、验证码、收藏、询价、搜索和事件上报具备合理限流。
- 密钥、密码和生产配置不进入 Git 或运行日志。
- 事件名属于统一目录，字段满足契约且不含敏感正文。
- PV、UV、率、净增长和回复时间使用固定测试数据校验。
- 每日汇总与原始事件在同一口径下对账。
- 趋势查询使用合理索引和汇总表，不每次扫描全部事件。

### 12.2 仅独立角色批准

- 询价状态机和重复提交窗口；
- 完整手机号访问角色与个人数据导出；
- 原始事件保留周期、IP 哈希方式和隐私规则；
- 性能数值预算；
- 生产迁移、备份恢复和发布；
- ShopXO 核心修改与物理删除；
- L3/L4 合并。

---

## 13. 项目级 MCP

`.codex/config.toml` 注册 `nursery_harness` 本地 stdio MCP：

- `harness_status`：Git、源码、开放决策、任务和基线状态；
- `requirements_search`：搜索中文需求文档并返回行号与标题；
- `requirement_get`：读取一个需求编号的完整段落；
- `task_get`：读取任务合同和配套文档状态。

该 MCP 只读、不访问网络、不连接数据库、不存储凭据。GitHub、数据库、浏览器或远程执行能力只有在出现真实用例、权限模型和任务合同后才增加，不能为了“使用 MCP”而默认扩大权限。

---

## 14. 项目级 Skills

### `shopxo-nursery-task`

用于规划、实现和验证任何苗木业务、数据、UI、安全、统计、插件或核心适配任务。它负责路由需求、开放决策、ShopXO 边界、preflight 和证据流程。

### `shopxo-nursery-review`

用于代码审查、数据库审查、权限/统计审查和发布前审计。它要求从原始 diff、合同和测试日志独立重建结论，不把自填 `reviewer` 字段当作真实审批。

Skills 位于 `.agents/skills/`，不会安装到用户 Skill 目录。

---

## 15. Hooks

### SessionStart

提醒代理读取项目规则、确定 Task ID 并执行 preflight。

### PreToolUse

快速阻止：

- `git reset --hard`、强制 clean、强推和批量丢弃工作区；
- 破坏性数据库命令和生产发布命令；
- 修改用户级 `.codex`、全局 MCP 或插件配置；
- 仓库外绝对补丁路径；
- 未 preflight 的业务补丁；
- 超出活动任务 `allowed_paths` 的补丁；
- 非 `NUR-HARNESS-*` 任务触及当前任务固定制品之外的 Harness 策略/执行路径；
- preflight 后修改任务授权字段或活动状态。
- `Set-Content`、重定向、`tee`、`sed -i`、内联解释器等直接 shell 文件写入；仓库编辑必须走可校验路径的 `apply_patch`，工作流写入走 Harness CLI。
- 仓库根及其祖先、补丁、任务、状态、运行证据或报告路径经过符号链接、Windows 目录联接或未知 reparse point；Harness 在 Python 3.11+ 上使用 `lstat`/reparse 属性失败关闭，不读取或写入其目标。

Hook 对任意脚本变形并不完备。所有修改仍需 `scope-check` 和 CI 检查 tracked、untracked、delete 和 rename。

---

## 16. Harness CLI

统一入口：

```powershell
python scripts/harness.py --help
```

主要命令：

- `project-check`：校验 Harness JSON/TOML/Hook/Skill/MCP 基础结构；
- `harness_selftest.py`：回归状态审批前置、事务恢复、并发锁、安全迁移边与 repository facts 失效；
- `harness_remote_selftest.py`：不联网验证主机指纹、外部 SSH 引用、结构化动作、状态/发布封印、输出上限和脱敏；
- `doctor [--strict]`：检查 Git、ShopXO 源码、PHP、Composer 和环境阻塞；
- `baseline`：生成带 source commit 的事实基线；
- `source-check`：验证必需源码、固定上游和四份可移植基线是否仍新鲜；
- `state-recover`：在安全任务状态、合同角色和原因校验后清理损坏/遗留活动状态，并保留本地审计记录；
- `task-create`：创建任务合同和必要 Markdown；
- `task-transition`：按允许的迁移更新状态并记录工作流历史；
- `task-approval`：记录 plan/merge/release 角色审批声明；plan/merge 匹配 reviewer，release 匹配独立 release_approver。自动审批不依赖 actor 名称前缀，必须精确匹配阶段 agent-task binding、提供有效且不同于 implementation 的 `CODEX_THREAD_ID`，并验证固定审批 JSON 的 task/stage/decision/actor/task/thread/result/context/timestamp/findings/summary；
- `contract-hash`：输出授权字段哈希供独立角色核对；
- `remote-actions`：离线列出 active L4 合同中的只读和变更动作；
- `release-seal`：在 release 审批、状态事件和提交完成后，把当前干净 Git HEAD 锁入 active state；
- `remote-exec`：仅通过固定 host key、外部 identity/known_hosts、受管根和精确 argv 执行一个合同动作并保存脱敏证据；
- `task-check`：校验任务、需求编号、开放决策和风险字段；
- `plan-check`：校验影响分析、实施计划和测试计划；
- `preflight`：检查分支、状态、合同和路径并激活任务；
- `scope-check`：检查已跟踪、未跟踪、删除和重命名路径；
- `verify`：以 `shell=False` 运行任务声明的命令数组，代码硬限制单流输出不超过 1 MiB、单测试不超过 3600 秒，清理敏感环境并禁止直接网络客户端/安装/Git 变更命令；L4 远程测试必须通过版本化脚本和锁定 `remote_execution` 合同；测试前后业务指纹或 Harness/control-plane 哈希变化会使结果失败；
- `evidence-check`：校验证据完整性；
- `review-pack`：生成脱敏审查摘要；
- `release-check`：在任务已进入 `approved_for_merge` 或 `closed` 后复核合并/发布准备度；进入 `approved_for_merge` 前的同一套检查仅由 `task-transition` 内部调用，远程动作只能由项目 broker 执行。

`remote-actions`、`remote-exec`、`release-seal` 和独立 `release-check` 的进程入口必须同时启用 Python `-I -S -B`。CLI 在任何可能被仓库路径遮蔽的标准库导入前检查这三个 flags，隔离模式再按 `scripts/harness_remote.py` 的精确同级路径加载 broker。该措施防止仓库内 `json.py` 等文件参与敏感命令启动，不等同于对 Python 可执行文件进行平台签名或来源认证。

broker 的内部 release-check launcher 例外不回读磁盘 sibling：它把已稳定读取并与 Git 校验的 broker bytes 执行为内存 module，再用私有 token/module 对象身份上下文注入同一进程的 Harness。Harness 仅在该上下文与 `sys.modules['harness_remote']` 对象身份一致时复用；环境变量、argv 或普通直接 CLI 不能触发此分支。由此关闭“校验后替换磁盘 broker，再诱导 Harness 重载”的 TOCTOU 窗口。

broker 对已跟踪的 `scripts/harness.py` 与 `scripts/harness_remote.py` 使用稳定句柄读取工作树，只承认两种 Git 等价：原始 bytes 与 HEAD blob 完全相同；或在原始 bytes 不同时，工作树所有 CRLF 窄化为 LF 后与 HEAD blob 完全相同。不得进行 `splitlines`、Unicode、空白、bare CR 或其他宽泛归一化；任何非换行内容漂移都失败关闭。等价验证成功后，内部 launcher 的 framing 必须传递已验证的 HEAD blob bytes，而不是工作树原始 bytes。

仓库级 Git config 不得自行复刻 section header 语法。broker 必须稳定读取 `.git/config` 一次，把同一 payload 通过匿名稳定句柄送入固定系统 Git 的 `config --file - --no-includes --null --name-only --list`，在清理后的固定环境中只取得 NUL 分隔 key names；不得重开原配置、跟随 include、继承可执行 helper/pager 或输出 value。规范化 key casefold 后，按 root 拒绝 `alias`、`filter`、`include`、`includeIf`，拒绝会增加 `config.worktree` 配置源的 `extensions.worktreeConfig`，并按 root 与末级 key 拒绝 diff 的 `command`/`external`/`textconv` 及 core 的 `hooksPath`/`attributesFile`。Git 非零退出、stderr、超时、输出超限、非法 UTF-8、空 key 或损坏 framing 都必须失败关闭；合法复杂 quoted subsection、`remote.origin` 和 `branch.main` 不得误拒。

缺少 PHP、Composer、数据库、浏览器或测试夹具时返回 warning/blocked/failure，不得标记为 passed。

---

## 17. CI 与审查

CI 使用与本地相同的 Harness，不实现另一套规则。Pull Request 至少提供：

- Task ID、需求和风险；
- 实际修改与明确未修改范围；
- 核心和数据库影响；
- 验收项到证据的映射；
- 真实测试、失败、blocked 和未执行项；
- 风险、限制和回滚；
- 独立审查与发布审批要求。

业务任务不得顺带修改 Harness 策略、Hook 或检查器。Harness 变更使用 `NUR-HARNESS-*` 或 bootstrap 范围，并独立审查。

运行明细、截图和 stdout/stderr 默认不进 Git；CI 只上传有短保留期的脱敏机器摘要，不上传原始 stdout/stderr 或截图。CI 证据使用稳定 `VERIFY_CONTRACT_SHA256` 和逐测试 `TEST_COMMAND`/`TEST_RESULT` 标记，不依赖本地时间戳目录。

---

## 18. Harness 验收标准

项目 Harness 完成必须满足：

1. 当前目录是固定上游 commit 的 ShopXO 下游仓库。
2. 所有 Codex 定义和脚本均在项目内，不自动修改全局配置。
3. 项目被信任后可以发现两个 repo Skills、项目 Hook 和 `nursery_harness` MCP。
4. 无活动任务时业务补丁被阻止，Harness bootstrap 文件仍可维护。
5. 任务合同能校验真实需求编号和开放决策。
6. preflight 后修改授权字段会使任务失效。
7. scope-check 能识别 tracked、untracked、delete 和 rename。
8. 数据库、权限、统计和核心修改要求更高风险与独立审批。
9. verify 保存真实命令、退出码和脱敏输出。
10. 缺失工具和环境阻塞不会被判定为通过。
11. MCP 为只读并通过初始化、工具列表和调用自测。
12. Hook 安全/危险输入冒烟测试通过。
13. Skills 通过结构校验并能在独立代理测试中正确路由工作流。
14. CI 和本地使用同一套规则。
15. 当前 `app/common.php` 阻塞被明确报告，未被静默提交或伪装修复。
16. `config/shopxo.sql` 不能成为已有站点的唯一升级脚本，fresh-install 例外需显式 L4 审批。
17. 仓库根及其祖先、必需源码、控制面、任务、状态、运行证据、报告、测试可执行文件或 Hook 补丁路径不能经过符号链接、Windows 目录联接或未知 reparse point；Python 3.11 环境也必须拒绝。
18. 损坏/遗留活动状态可用带锁、角色和原因校验的 `state-recover` 恢复，无需手工删除。
19. 远程 broker 的 CLI 旁路、主机/指纹漂移、SSH config/agent/proxy、合同外路径、未封印 mutating 动作、超时、输出溢出和敏感输出都必须失败关闭。

---

## 19. 下一步开发顺序

Harness 建成后，不应立即开发全部需求。推荐先建立以下真实任务：

1. baseline-only bootstrap（无业务 Task ID）：在 WSL/隔离 VM/干净 CI checkout 中确认 `app/common.php` 存在，重建并审查四份基线；该提交不得混入业务代码。
2. `NUR-OPS-001`：固化完整 ShopXO 开发环境、PHP/Composer 和测试数据库；此时 `source-check` 必须基于上一步的新基线通过。
3. `NUR-HARNESS-001`：根据可运行环境固定第一组 PHP/HTTP/数据库冒烟检查。
4. `NUR-FEAT-001`：配置化关闭 PX 用户入口并建立可达性验收。
5. `NUR-FEAT-002`：公开参考价格与 `AC-001`。
6. `NUR-DATA-001`：评估商品逻辑删除、收藏唯一约束和历史保留方案；未批准设计前不直接实现。

先完成可运行基线和最小 P0 闭环，再逐步进入收藏、询价和统计。项目采用不同 Codex 代理分离实现、审查和发布角色；任何自动发布都必须受 L4 合同、备份、回滚和最新证据约束。

# ShopXO 苗木项目指令

本仓库用于将 `gongfuxiang/shopxo` 二次开发为单一经营主体的苗木展示、收藏、询价和运营分析平台。所有 Codex、人工开发与审查都遵守同一套项目级 Harness。

## 开始工作前

1. 阅读 `.harness/CONSTITUTION.md`。
2. 阅读 `ShopXO苗木平台需求规格说明书_V1.0.md` 中与任务相关的需求编号。
3. 阅读 `docs/product/BUSINESS_RULES.md` 与 `docs/architecture/SHOPXO_BOUNDARY.md`。
4. 使用 `.harness/tasks/<TASK_ID>/task.json` 作为唯一任务合同。
5. 先运行 `python scripts/harness.py source-check`，再运行 `python scripts/harness.py preflight <TASK_ID>`；两者通过后才修改业务代码。

若仓库根目录尚无 `composer.json`、`app/` 和 `config/shopxo.sql`，说明 ShopXO 源码尚未导入。此时只允许维护 Harness、需求、决策和基线，不得凭需求文档虚构代码位置或测试结果。

## 必须遵守的开发顺序

1. 确认需求编号、优先级和开放决策。
2. 完成需求摘录、影响分析、实施计划、测试计划和回滚设计；首次进入实现前仍需完成合同要求的 plan 审批。任务已实际进入 `implementing` 后，修复过程中仅四份计划制品的更新可作为 warning 保留并重新 `preflight`，不强制退回重复 plan 审批，且必须由后续独立 merge 代码/功能审查重新核验；任务合同、执行策略、需求决策、远程目标或动作变化仍必须重做 plan 审批。
3. 优先选择：配置 → 现有服务 → 插件钩子 → `nursery` 插件 → 独立模块 → 小范围核心适配。
4. 只修改任务 `allowed_paths` 授权的路径。
5. 执行任务声明的真实测试并保留退出码和证据。
6. 运行 `scope-check`、`evidence-check` 和 `review-pack`。
7. L3/L4、数据库、权限、统计口径或 ShopXO 核心修改必须由独立角色审批。按项目负责人的明确授权，owner、reviewer、release_approver 可由不同 Codex 代理承担；实现代理不得批准自己的变更，审批必须引用独立审查与真实验证证据。
8. 数据库升级必须提供版本化 forward migration；`config/shopxo.sql` 不能作为既有站点的唯一升级脚本，fresh-install 例外必须为 L4 且写明不存在既有实例。

## 业务不变量

- 商品在询价前公开展示参考价格；询价回复不得覆盖商品公开价。
- 收藏仅用于保存商品，收藏与询价互不作为前置条件。
- 用户只能访问自己的收藏、询价和个人数据。
- 商品下架或逻辑删除不得破坏收藏、询价和统计历史。
- 询价必须保存必要的商品、规格和价格快照，并保留回复与状态历史。
- PV 按事件次数计算，UV 按 `visitor_id` 去重；次数和人数不得混用。
- 不建设或重新启用供应商、多商户、分销、购物车、在线订单、支付和售后流程。

## 禁止事项

- 修改用户级或全局 Codex 配置；项目能力只能放在本仓库的 `.codex/`、`.agents/` 和 `.harness/`。
- 读取密钥内容、访问未授权数据库，或执行未写入 L4 `remote_execution` 合同的远程/发布动作；SSH 只能引用仓库外凭据，原始 `ssh/scp/curl` 命令保持禁止，远程动作只能经 `python -I -S -B scripts/harness.py remote-exec`（或自动添加这些 flags 的项目 wrapper）。
- 直接在保护分支实现功能、强制推送、破坏性重置或清理工作区。
- 物理删除 ShopXO 原有商城核心能力来“精简”系统。
- 未登记就修改 ShopXO 核心路径或数据库结构。
- 让业务任务修改 Harness 策略路径，或用 shell 重定向、`Set-Content`、`tee`、内联解释器等方式绕过 `apply_patch` 路径检查。
- 通过符号链接或 Windows 目录联接重定向必需源码、控制面、任务、状态、证据、报告、测试可执行文件或补丁路径。
- 把缺失、跳过或未执行的测试表述为通过。

损坏或遗留的 `.harness/state/active-task.json` 不得手工删除；先将任务退回安全状态，再使用 `python scripts/harness.py state-recover ...` 记录合同角色、原因和本地恢复审计。

## 项目工具

- 任务实施使用 `$shopxo-nursery-task`。
- 变更审查使用 `$shopxo-nursery-review`。
- Harness CLI：`python scripts/harness.py --help`。
- 项目 MCP：`nursery_harness`，仅提供需求、任务和 Harness 状态的只读工具。

Harness 自身首次搭建或修复属于 bootstrap 例外，可在没有业务任务合同的情况下修改 `.harness/**`、`.codex/**`、`.agents/**`、`.github/**`、三份既有 `docs/product|architecture` Harness 文档、项目级 `scripts/harness*` 入口与自测、`.gitignore`、`AGENTS.md`、`HARNESS.md`、Harness 规格和需求规格书；例外不得用于苗木业务代码。权威清单以 `.harness/harness.json` 的 `paths.bootstrap_allowed` 为准。

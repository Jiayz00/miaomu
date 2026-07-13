# NUR-FEAT-001 独立审查

## 审查范围

第三轮独立合并审查核对了 `FR-HOME-001`、`FR-CENTER-001`、`DEC-PX-BASELINE-NAV`、最新任务合同、四份修订计划、固定 `approval-plan.json` 与审批历史、前两轮 `CHANGES_REQUESTED`、verify `20260713T165229053992Z`、实施证据、发布说明、最新 review-pack、HEAD `1ea19b70d82b4228c477671e189a25265088e41a` 到完整暂存差异，以及 ShopXO 6.9.0 的 `User::Index()`、`MyView()`、`ModuleInclude()`、`ViewIncludeModule` 和默认商品模板真实调用链。

本轮实际复跑并通过：`git diff --check`、`source-check`、`task-check NUR-FEAT-001`、`scope-check NUR-FEAT-001`、`evidence-check NUR-FEAT-001`、23 项 `nursery_scope_contract` 和 60 项 Harness 自测；Harness 自测另有 2 项因当前 Windows 无符号链接权限而明确跳过。范围检查为 tracked=7、untracked=0，无核心、数据库、迁移、生成的 `app/event.php`、依赖或 forbidden path 变更。

## 发现

未发现 P0-P2 缺陷。

- 前一轮商品入口 P1 未回归：插件 `list/base` 与 `slider/binding` 模板继续等于固定上游仅删除批准的购物车节点，公开价格、单位、商品链接和三个既有商品模块 Hook 均保留；direct module 路径仅在 default 主题替换，显式 `../default` 回退始终替换，非 default 主题自有 direct 模板保持不变。
- 用户中心递归 P1 已关闭：`User::Index()` 的外层空 view 和非 default 主题缺页时产生的 `../default/user/index` 是 `USER_CENTER_ENTRY_VIEWS` 的仅有两个精确值；Windows 反斜杠只做分隔符规范化，不做 trim、大小写转换、子串或正则匹配。Hook 同时要求 `index/user/index` 路由和该精确 guard，替换后立即 return。插件模板中的 `public/header`、`public/nav`、`public/header_top_nav`、`public/header_nav_simple`、`public/user_menu`、`public/footer`，以及其他 module/plugin/相似路径均不匹配，因而不会再次替换。
- 23 项合同测试不仅复制实现模型，还锁定固定常量、PHP 方法结构、调用次数、精确 guard、立即 return、六个 ModuleInclude 路径、商品模板与固定上游的受控差异，并用临时仓库外副本验证删除 guard、恢复 route-only 替换、误加 public partial、漏掉 fallback、扩大为 substring/regex、恢复购物车节点或删除价格/链接/Hook 都会失败；测试未修改业务文件或 Harness 控制面。

## 审查结论

当前源码、任务授权、计划再审批、最新验证证据和 review-pack 一致，前两轮 P1 均已通过项目级插件边界修复，未修改 ShopXO 核心或数据库。本轮批准 NUR-FEAT-001 合并。

该批准仅覆盖源码合并，不代表可直接发布。本机仍未运行 PHP 语法、Composer、MySQL、插件安装/启用、`app/event.php` 生成、HTTP 路由、数据库副作用或 PC/H5 浏览器测试。尤其 Python 源码模型不能证明真实 ThinkPHP 嵌套 `ModuleInclude()` 一定有限完成；后续受控 PHP 环境必须以超时和输出上限执行用户中心递归冒烟，确认外层模板与公共 partial 各仅渲染一次、无 500/内存错误，并将失败设为发布阻断。真实 slider 配置、冷暖缓存、仅启用 nursery 插件、安装器/静态文件/直连 FPM 边界及正负路由矩阵也仍是发布前门禁。

REVIEW_RESULT: APPROVED

REVIEWER: Codex-Review

REVIEWED_AT: 2026-07-13T16:57:43Z

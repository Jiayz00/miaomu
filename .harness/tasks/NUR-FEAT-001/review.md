# NUR-FEAT-001 独立审查

## 审查范围

本轮重新核对了 `FR-HOME-001`、`FR-CENTER-001`、`DEC-PX-BASELINE-NAV`、最新任务合同、四份修订计划、`approval-plan.json` 及审批历史、上一轮 `CHANGES_REQUESTED`、最新 verify 运行、实施证据、发布说明、review-pack、HEAD `822b6ae2db717b5682e50c068ec8f2ce673e2b10` 到完整暂存差异，以及 ShopXO 6.9.0 的 `MyView`、`ModuleInclude`、分类、搜索、商品模块与用户中心真实调用链。

上一轮分类/搜索图文列表及动态 slider 的可见购物车 P1 已按修订计划处理：两个插件模板与固定上游相比只删除购物车节点，公开价格、单位、商品链接和原有商品模块 Hook 均保留；商品模块 direct 路径仅在 default 主题替换，显式 `../default` 回退始终替换，非 default 主题自有 direct 模板保持不变。本轮实际复跑 `source-check`、`task-check`、`scope-check`、`evidence-check` 和 23 项 `nursery_scope_contract`，均通过；最新 verify 证据另记录 60 项 Harness 自测通过、2 项因 Windows 无符号链接权限明确跳过。

## 发现

### P1：用户中心视图替换会递归替换其所有 ModuleInclude

- 证据：`app/index/controller/User.php:126` 的用户中心外层调用是 `MyView()`，因此 default 主题下进入 fetch-begin Hook 的外层 `view` 是空字符串；非 default 主题缺少该页面时，上游 `app/common.php:1041-1064` 会把它变成 `../default/user/index`。这两个值才是需要替换的外层输入。
- 失败场景：当前 `app/plugins/nursery/Hook.php:112-115` 只判断请求仍为 `index/user/index`，不检查本次 `view`，于是该请求中的每一次 `MyView()` 都被改成整个 nursery 用户中心模板。插件模板 `app/plugins/nursery/view/index/user/index.html:1-18` 随即调用 `ModuleInclude('public/header')`、`public/nav`、`public/header_top_nav`、`public/header_nav_simple` 和 `public/user_menu`；上游 `app/common.php:2497-2514` 与 `app/module/ViewIncludeModule.php:35-37` 证明每个 ModuleInclude 都再次调用 `MyView($template, ...)`。请求控制器和 action 未变化，这些嵌套 partial 会再次被替换成用户中心模板，形成递归渲染并使用户中心不可用。
- 测试缺口：23 项静态测试只要求存在 user/controller/action 条件、赋值和 return 顺序，没有断言用户中心替换只接受外层 `view` 的精确集合，也没有验证 `public/*`、商品模块或插件自身 view 在 `index/user/index` 请求内保持原值，因此该缺陷未被负变异捕获。
- 违反：直接破坏 `FR-CENTER-001`、`AC-TASK-001` 和任务不变量中“个人资料、账号安全、收藏和浏览历史不得误伤”的要求；同时不能把未运行的 PHP 页面渲染当成已验证。
- 最小修正：把用户中心替换收窄为源码确认的外层输入白名单，至少精确覆盖 default/custom-own 情况下的空外层 view 与 `../default/user/index` 显式回退，并明确让 `public/*`、`module/*`、`../../../plugins/*` 和相似路径保持不变。计划和测试必须锁定这些真实输入，加入删除条件、扩大为请求级无条件替换、错误替换 partial、漏掉 fallback 等临时负变异；在具备 PHP 的环境中增加一次用户中心渲染冒烟，证明不会递归且公共 partial 正常输出。

## 审查结论

商品 list/slider 的上一轮缺口已经关闭，自动门禁和 23 项离线测试也通过；但当前用户中心 fetch-begin 边界会让正常页面递归渲染，属于阻塞合并的 P1。本轮拒绝 merge 审批，不创建 `approval-merge.json`，不执行 `task-approval ... merge --status approved`。

本机仍未运行 PHP 语法、Composer、MySQL、插件安装/启用、`app/event.php` 生成、HTTP 路由、数据库副作用或 PC/H5 浏览器测试；这些项目保持未验证，后续不得表述为通过。安装器、直连 FPM、静态文件保护、真实 slider 配置、冷暖缓存和仅启用 nursery 插件也仍属于发布前运行验收门禁。

REVIEW_RESULT: CHANGES_REQUESTED

REVIEWER: Codex-Review

REVIEWED_AT: 2026-07-13T16:35:48Z

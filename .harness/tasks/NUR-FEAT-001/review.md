# NUR-FEAT-001 独立审查

## 审查范围

独立核对了 `FR-HOME-001`、`FR-CENTER-001`、`DEC-PX-BASELINE-NAV`、任务合同、四份获批计划、实施证据、发布说明、最新 review-pack、完整暂存差异，以及固定 ShopXO 6.9.0 源码中的事件部署、系统起始、导航、商品按钮、后台权限和视图 Hook 调用点。

本轮实际执行并通过：`source-check`、`task-check NUR-FEAT-001`、`scope-check NUR-FEAT-001`、`evidence-check NUR-FEAT-001`、19 项 `nursery_scope_contract` 测试和 60 项 Harness 自测；Harness 自测另有 2 项因当前 Windows 无符号链接权限而明确跳过。未执行 PHP 语法、Composer、MySQL、插件安装/启用、HTTP、数据库副作用或浏览器测试，不能将这些项目记为通过。

## 发现

### P1：分类和搜索图文列表仍显示可点击购物车入口

- 证据：上游 `app/index/view/default/module/goods/list/base.html:120` 在公开价格区块中硬编码输出 `icon-shopping-cart` 与 `common-goods-cart-submit-event`。`app/index/view/default/search/index.html:120-123` 在 `layout=1` 时直接包含该模板，`app/index/view/default/category/datalist.html:1-5` 也固定包含该模板，因此任务明确要求保留可用的分类与搜索页面仍会显示购物车图标。
- 缺口：当前 `app/plugins/nursery/Hook.php:39-48` 和 `app/plugins/nursery/service/ScopePolicy.php:323` 只过滤 `GoodsService::GoodsBuyButtonList()` 产生的商品详情按钮，无法触达列表模板里的硬编码入口。购物车控制器最终返回 404 只能满足直达路由失败关闭，不能替代可见入口收敛。
- 违反：任务 `business_invariants[0]` 要求排除能力同时从可见入口、直达 Web/API 路由和后台菜单权限收敛；同时违背 `FR-HOME-001` 及项目 PX 规则“不建设或重新启用购物车”的产品边界。
- 最小修正：退回实施阶段并修订计划与测试。可以继续保持业务改动集中在 `app/plugins/nursery/**`，通过经源码验证的结构化 Hook，或在 `plugins_view_fetch_begin` 中对实际使用的商品列表模块做插件内替代视图；不得以 CSS 隐藏替代模板收敛。同步审计 `app/index/view/default/module/goods/slider/binding.html:93-95` 的同类硬编码入口，并新增搜索 `layout=1`、分类列表及首页/动态商品 slider 的正负测试和后续浏览器验收。

## 审查结论

自动门禁与离线合同测试通过，但它们没有覆盖上述真实默认主题模板调用链。该 P1 会让首版苗木站在正常可达页面继续展示购物车入口，因此本轮拒绝合并审批。

修正后仍需在 PHP/MySQL 环境验证插件安装和 `app/event.php` 生成、真实 404、冷/暖缓存权限、数据库无副作用以及 PC/H5 浏览器页面。`?default_theme=default` 本身不能绕过当前 system-begin 或用户中心 fetch-begin Hook，但默认主题公共 footer/header 和详情隐藏表单仍保留休眠的购物车标记，发布前应确认所有可见触发入口均已收敛且目标路由持续失败关闭；部署还必须验证只有 `nursery` 插件启用。

REVIEW_RESULT: CHANGES_REQUESTED

REVIEWER: Codex-Review

REVIEWED_AT: 2026-07-13T15:52:06Z

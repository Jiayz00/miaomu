# NUR-FEAT-001 需求摘录

## 关联需求

- `FR-HOME-001`
- `FR-CENTER-001`

## 任务路由

- PRIORITY: P0
- PHASE: 1

需求规格 4.1 将首页、商品展示、用户中心和移动端自适应列为 P0；15.1 要求第一阶段先精简无关功能。`FR-HOME-001` 明确首页不得出现购物车、订单、支付、分销入口，`FR-CENTER-001` 明确用户中心隐藏购物车、订单、钱包、分销、优惠券等无关入口。因此本任务路由为 P0、阶段 1。

任务涉及 Web/API/后台路由拒绝和后台权限数组收敛，按 requirement-routing.md 属于 L3，计划和合并均由不同于实现代理的 Codex 角色独立审批。

## 业务目标

- `FR-HOME-001`（需求规格第 7.1 节）：首页展示品牌、分类、搜索、推荐/热门/新上架商品和联系方式；无需登录可访问，PC 与移动端正常展示，且“不出现购物车、订单、支付、分销等无关核心入口”。
- `FR-CENTER-001`（需求规格第 7.10 节）：用户中心至少保留个人资料、我的收藏、我的询价、浏览历史和账号安全；购物车、订单、钱包、分销、优惠券等无关入口应隐藏。
- 明确排除范围（需求规格第 4.4、12.5 节）：供应商、多商户、商家店铺、分销、代理、购物车、在线订单、在线支付、退款售后、会员等级、积分、优惠券及营销交易能力不得实施；优先通过配置、菜单、模板和路由权限关闭，不物理删除底层代码。

本任务先建立后续苗木功能共用的 `nursery` 插件，用已验证 Hook 同时收敛可见入口和直达路由。询价功能尚未实现，因此仅保留收藏、浏览历史、资料和安全等现有正向能力；“我的询价”由后续询价任务交付，不以占位页面冒充完成。

独立合并审查进一步确认，默认主题的 `module/goods/list/base` 会被分类页和搜索 `layout=1` 正常调用，并硬编码可点击购物车图标；`module/goods/slider/binding` 也硬编码同类入口。详情按钮 Hook 无法触达这些模板节点，购物车路由返回 404 也不能替代可见入口收敛。因此修订后的本任务必须通过既有 `plugins_view_fetch_begin` 精确替换这两类商品模块视图，且保留公开价格、商品链接和原有扩展 Hook。直接 `module/...` 同时可能表示非 default 主题已经拥有的自有模板，因此只在 `DefaultTheme() === 'default'` 时替换；`../default/...` 明确表示主题缺失文件后回退默认模板，必须始终替换。

第二次独立合并审查确认，用户中心替换若只判断当前请求为 `index/user/index`，插件用户模板内部的 `ModuleInclude('public/*')` 会再次进入同一 fetch-begin Hook 并被替换成整页模板，造成递归渲染。固定源码中 `User::Index()` 的外层调用是 `MyView()` 空 view，非 default 主题缺文件时外层 view 为 `../default/user/index`；只有这两个规范输入可替换。所有 `public/*`、`module/*`、插件自身路径、相似或大小写变体必须保持原样。

源码复核确认两类不能遗漏的入口：`sxo_app_home_nav/sxo_app_center_nav` 使用 `/pages/plugins/<slug>/...`，其中 `membershiplevelvip`、`weixinliveplayer` 是会员等级和直播的 ShopXO 基线标识；`sxo_shortcut_menu` 还独立保存订单、售后、分销、优惠券和秒杀快捷入口。它们均受既有 PX 业务规则约束，不因路由或数据源不同而保留。

## 明确不做

- 不实现询价、统计、价格历史、通知、排行榜或导出。
- 不新增苗木分类数据、规格参数、公开价格守卫或价格免责声明。
- 不创建完整视觉主题，不修改默认主题，不用 CSS 隐藏来替代模板和路由收敛；只在 nursery 插件内提供两份与固定上游同构、仅删除购物车节点的商品模块替代视图。
- 不删除 `app/index|api|admin/controller` 中的商城控制器、服务或 `config/shopxo.sql` 表结构。
- 不安装/启用插件、不生成 `app/event.php`、不访问数据库或服务器。

## 开放决策

- `DEC-PX-BASELINE-NAV` 已解决：`membershiplevelvip`、`weixinliveplayer`、`shop`、`excellentbuyreturntocash` 是明确 PX 的 ShopXO 等价标识，直达路由与入口均拒绝；`activity`、`blog`、`signin`、`ask`、`brand`、`realstore`、`binding`、`invoice` 首版仅隐藏前后台入口，不永久扩大直达拒绝集合。首版部署只允许 nursery 插件启用。
- 后续询价状态、重复窗口、价格历史和分析优先级决策不阻塞本任务。

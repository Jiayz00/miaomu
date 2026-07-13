# NUR-FEAT-001 影响分析

## 需求与当前事实

`source-check` 已确认 ShopXO 6.9.0、固定上游 `d1825c5404054b535255d8fcad675a5dae0ab633`。当前 `app/plugins/` 和 `public/static/plugins/` 只有占位文件，`app/event.php` 不存在，前后台主题只有 `default`，业务源码与上游 tree 一致，苗木业务实现为 0。

`FR-HOME-001` 和 `FR-CENTER-001` 要求去除排除的商城入口。现状中 `NavigationService::HomeHavTopRight()` 硬编码订单与购物车，`BottomNavigationData()` 硬编码购物车，`UserCenterLeftList()` 硬编码订单、售后、评价和积分；`app/index/view/default/user/index.html` 还硬编码订单、购物车区块。商品详情通过 `GoodsService::GoodsBuyButtonList()` 产生 buy/cart。Web、API 和后台商城控制器均可直接访问。

仓库没有业务测试或 PHPUnit 配置；当前机器没有 PHP、Composer、MySQL、Docker。可执行的首层验证是 Python 标准库离线合同测试，运行时测试必须在后续受控 PHP/MySQL 环境补齐并如实记录。

## 当前调用链与数据

1. 请求边界：index/api/admin 公共控制器在业务动作前调用 `SystemService::SystemBegin()`；该服务触发 `plugins_service_system_begin`，ThinkPHP 在实例化控制器前已经设置 module/controller/action。Hook 返回值被忽略，异常会向框架传播，因此必须 `abort(404, ...)`，不能只返回失败数组。
2. 插件注册：`PluginsAdminService::PluginsStatusUpdate()` 启用插件时读取 `app/plugins/<name>/config.json` 的 `hook`，生成 `app/event.php`。生成文件不应提交或手工编辑。
3. 可见入口：
   - `plugins_service_header_navigation_top_right_handle`：过滤顶部 `myself` 与 `cart`。
   - `plugins_service_bottom_navigation_handle`：过滤移动底部 `cartindex`。
   - `plugins_service_users_center_left_menu_handle` 和 `plugins_service_user_center_mini_navigation_handle`：保留资料、收藏、浏览、安全，移除订单/售后/评价/积分。
   - `plugins_service_admin_menu_data`：递归过滤后台菜单，并同步移除 `admin_power` 中被拒绝控制器的 action key。
   - `plugins_service_goods_buy_nav_button_handle`：从详情按钮集合移除 `buy`、`cart`，保留展示型 `show` 及未来 `inquiry`。
4. 硬编码页面：`plugins_view_assign_data` 在首页清空 `user_order_status`；`plugins_view_fetch_begin` 仅对 `index/user/index` 替换为插件自有视图，从模板层移除订单和购物车区块。
5. 数据：本任务不查询、写入或迁移订单/支付/收藏/商品表；插件安装状态属于后续部署操作。历史商城表和数据不删除。

固定路由策略在计划批准前锁定如下（全部小写比较，命中控制器后拒绝其所有 action）：

- Web/index：`buy`、`cart`、`order`、`orderaftersale`、`pay`、`useraddress`、`usergoodscomments`、`userintegral`。
- API：`buy`、`cart`、`cashier`、`order`、`orderaftersale`、`ordernotify`、`paylog`、`useraddress`、`usergoodscomments`、`userintegral`。
- Admin：`express`、`goodscart`、`goodscomments`、`integrallog`、`order`、`orderaftersale`、`payment`、`paylog`、`payrequestlog`、`refundlog`、`warehouse`、`warehousegoods`。
- PX 插件标识：`agent`、`aftersale`、`bargain`、`cart`、`coupon`、`delivery`、`distribution`、`finance`、`groupbuy`、`integral`、`inventory`、`live`、`memberlevel`、`membership`、`merchant`、`multimerchant`、`order`、`payment`、`points`、`refund`、`seckill`、`supplier`、`wallet`。

固定正向回归集合至少包含：Web 的 `index/category/search/goods/user/personal/safety/usergoodsfavor/usergoodsbrowse/message/plugins`，API 的 `index/category/search/goods/user/personal/safety/usergoodsfavor/usergoodsbrowse/message/plugins`，后台的 `goods/goodscategory/goodsspectemplate/goodsparamstemplate/user/goodsfavor/goodsbrowse/site/navigation/role/power`，以及 `pluginsname=nursery`。`install` 模块不在策略处理模块集合内，部署层单独关闭安装器。

## 影响范围

- 用户端：顶部、移动底部、商品详情和用户中心的交易入口消失；分类、搜索、商品、收藏和浏览历史继续使用上游链路。
- 管理端：交易型菜单和权限 key 被插件运行时过滤；`admin_left_menu` 按 control 递归裁剪，`admin_power` 按 `<control>_` 前缀裁剪，`admin_plugins/admin_all_plugins` 按固定 PX 插件标识裁剪。源码与表仍存在，便于上游同步和可控回滚。
- API：固定控制器拒绝表阻断购物车、结算、订单、支付、售后和积分的所有 action，不依赖 action 名逐项枚举。
- 插件入口：当 `RequestController()` 为 `plugins` 时，以 `PluginsRequestName()` 读取并规范化 `pluginsname`，对锁定的 23 个 PX 标识失败关闭；`nursery` 自身不受阻断。
- 历史数据：不执行 delete/update，不改变历史订单、收藏、用户或商品数据；部署后的路由不可达不等于数据删除。
- 统计：本任务不新增或改变事件、PV/UV 或指标口径。
- 安全：拒绝逻辑是应用层纵深防御，依赖插件已启用；不保护安装入口、静态文件或直连 FPM。
- 性能：每个请求只做小型固定集合匹配；菜单递归只处理已加载数组，不增加数据库查询。
- 上游同步：自定义逻辑集中在 `app/plugins/nursery/**`，不制造核心差异；Hook 名变化是升级时主要回归点。

## 方案比较

1. 配置：`site_type=4` 能隐藏详情 buy/cart 并显示“立即咨询”，`common_goods_close_buy_button` 也能关闭按钮，但二者都不能阻断直接 Web/API/后台路由，也不能移除全部硬编码用户中心区块，单独使用不足。
2. 现有服务：NavigationService 和 AdminPowerService 提供完整数据，但直接修改它们属于核心差异，优先级低于已有 Hook。
3. 已验证 Hook：系统开始、前后台导航、用户中心、商品按钮、视图赋值/抓取均存在且参数使用引用，能够完成本任务。
4. `nursery` 插件：将固定策略、Hook 入口和替代视图集中管理，符合 ShopXO 插件结构并为后续公开价格、询价和分析提供边界。
5. 独立模块/核心适配：本任务无必要，不采用。

## 风险与边界

- Hook 未注册或插件被禁用时策略完全失效；部署验收必须检查 `sxo_plugins.is_enable=1` 和生成事件映射。
- `SystemBegin` 已执行 UUID/token 基础初始化后才阻断，请求仍可能写 Session/Cookie；不写业务数据，运行验收应确认拒绝请求没有订单/购物车副作用。
- 控制器拒绝表过宽会误伤收藏、登录或苗木插件，过窄会留下 action 绕过；测试同时维护正例和控制器级负例。
- 后台菜单缓存可能保留旧菜单；安装/启用/禁用后必须刷新 ShopXO 缓存，运行验收不能只检查新会话外观。
- 插件替换用户中心视图只针对 `index/user/index`；其他资料、安全、收藏、浏览页面继续回退当前主题/默认主题。
- 第三方商城插件标识无法穷举；首版固定拒绝已知 PX 标识，部署时同时证明未安装未批准插件。
- 本机缺少 PHP/MySQL，静态测试不能证明框架异常响应、菜单缓存或数据库无副作用；这些保持未验证直至部署任务执行。

## 预计文件

- 新增：`app/plugins/nursery/config.json`
- 新增：`app/plugins/nursery/Hook.php`
- 新增：`app/plugins/nursery/Event.php`
- 新增：`app/plugins/nursery/service/ScopePolicy.php`
- 新增：`app/plugins/nursery/view/index/user/index.html`
- 新增：`tests/nursery/test_scope_contract.py`
- 不新增静态资源、迁移、install/update/uninstall SQL、`app/event.php` 或核心登记。

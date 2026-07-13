# NUR-FEAT-001 实施计划

## 实施步骤

1. 在 `app/plugins/nursery/config.json` 写入 ShopXO 6.9.0 可识别的插件元数据和 Hook 映射。只注册源码已确认存在的 `plugins_service_system_begin`、`plugins_service_navigation_header_handle`、`plugins_service_navigation_footer_handle`、`plugins_service_header_navigation_top_right_handle`、`plugins_service_quick_navigation_pc`、`plugins_service_quick_navigation_h5`、`plugins_service_app_home_navigation_h5`、`plugins_service_app_user_center_navigation_h5`、`plugins_service_bottom_navigation_handle`、`plugins_service_users_center_left_menu_handle`、`plugins_service_user_center_mini_navigation_handle`、`plugins_service_admin_menu_data`、`plugins_service_goods_buy_nav_button_handle`、`plugins_view_assign_data` 与 `plugins_view_fetch_begin`；不生成 `app/event.php`。JSON 解析或 Hook 映射测试失败即停止。
2. 在 `service/ScopePolicy.php` 定义不可由请求修改的固定策略：
   - Web/index 控制器 8 个：`buy, cart, order, orderaftersale, pay, useraddress, usergoodscomments, userintegral`。
   - API 控制器 10 个：`buy, cart, cashier, order, orderaftersale, ordernotify, paylog, useraddress, usergoodscomments, userintegral`。
   - Admin 控制器 12 个：`express, goodscart, goodscomments, integrallog, order, orderaftersale, payment, paylog, payrequestlog, refundlog, warehouse, warehousegoods`。
   - PX 插件标识 23 个：`agent, aftersale, bargain, cart, coupon, delivery, distribution, finance, groupbuy, integral, inventory, live, memberlevel, membership, merchant, multimerchant, order, payment, points, refund, seckill, supplier, wallet`。
   所有比较先做字符串小写化，命中控制器即拒绝其全部 action；仅处理 `index/api/admin`，`install` 和其他模块默认不匹配。插件路由只在控制器为 `plugins` 时读取 `PluginsRequestName()`。测试发现允许控制器误入、任一锁定项缺失、集合被请求参数扩展或 action 可绕过即停止。
3. 在 `Hook.php` 以 `hook_name` 白名单分派：
   - system begin 调用 `RequestModule/Controller/Action`，命中时使用 ThinkPHP `abort(404, ...)` 中断；插件请求额外检查 `pluginsname`。
   - 数据库 header/footer 导航、顶部快捷导航、PC/H5 quick nav、H5 首页/用户中心导航、移动底部导航、用户中心 left/mini 导航根据结构化 `url/event_value/value/only_tag/type/control` 字段过滤并重建数组索引，不使用整段 HTML 字符串替换。
   - 后台 `admin_left_menu` 递归过滤并移除空组：普通项按 `control`；ShopXO 动态插件项按规范化 `id` 或 `key` 是否严格等于 `plugins-<PX>`，并用 URL 中规范化的 `pluginsname=<PX>` 或插件路由段作为纵深校验。不得只依赖可本地化的菜单名称。`admin_power` 按被拒控制器加下划线的 key 前缀过滤；`admin_plugins` 和 `admin_all_plugins` 按 PX 插件标识过滤。该 Hook 每次 `PowerMenuInit()` 返回前运行，因此缓存中的上游原值也会重新过滤。
   - 商品按钮仅删除 `type=buy/cart`，保留 `show`、未来 `inquiry` 和未知扩展按钮。
   - view assign 仅在 `index/index/index` 清空 `user_order_status`。
   - view fetch 仅在 `index/user/index` 把模板路径替换为插件自有视图。
   未识别 Hook 不修改参数并返回空值。
4. 在 `Event.php` 提供无数据库写入的标准生命周期回调，使 ShopXO 安装、启用、禁用与卸载流程可识别插件；不自动修改系统配置、管理员权限或历史数据。
5. 在 `view/index/user/index.html` 复用当前主题的公共头部、导航、用户菜单和页脚，保留用户资料、消息、收藏及浏览历史数据，仅删除订单状态、进行中订单、购物车、售后、评价和积分链接。页面不创建“我的询价”假入口，后续询价任务通过插件/主题扩展。
6. 在 `tests/nursery/test_scope_contract.py` 使用 Python 标准库解析 JSON 和源码，逐项断言 15 个 Hook、8/10/12 个控制器、23 个 PX 插件标识、固定正向控制器、`abort` 语义、`plugins` 控制器限定、无动态请求扩展策略、四类后台菜单/权限过滤、插件菜单 `id/key/url` 识别、结构化导航过滤、按钮保留语义、替代视图无 PX URL及授权路径未引用核心文件，并用临时变异副本验证关键缺口会使测试失败。对每个 PX 标识构造无 `control`、仅 `id/key=plugins-<name>` 和插件 URL 的后台菜单项；删除任一识别分支或任一标识都必须使负变异失败。

## 验证顺序

1. `python tests/nursery/test_scope_contract.py`
2. `python scripts/harness_selftest.py`
3. `python scripts/harness.py verify NUR-FEAT-001`
4. `python scripts/harness.py scope-check NUR-FEAT-001`
5. 填写稳定 `VERIFY_CONTRACT_SHA256`、逐测试命令和退出码后运行 `evidence-check` 与 `review-pack`。
6. 独立审查通过后，本任务只合并源码；真实 PHP/MySQL 安装、Web/API/admin 路由和页面冒烟由后续 L4 部署任务在发布前补齐。

## 数据库与核心适配

无数据库结构或业务数据变更，无 ShopXO 核心适配。任务不创建 `install.sql`、`update.sql` 或 `uninstall.sql`，不修改 `config/shopxo.sql`、`app/event.php`、`app/service/**`、默认主题或控制器。插件安装/启用只允许在后续远程合同中执行，并由 ShopXO 自身写入插件状态、生成事件映射。

## 失败处理与回滚

发现需要修改默认主题、公共控制器、核心服务、数据库结构、安装生成文件或合同外路径时立即停止并重新分析，不隐式扩大任务。若静态合同测试、scope-check 或独立审查失败，保留脱敏输出并退回 implementing 修正。

未部署回滚只还原任务授权路径。已部署回滚先禁用 nursery 插件、刷新事件映射和缓存，确认 `app/event.php` 不再引用插件，再还原源码；不删除上游商城模块或任何历史数据。回滚后验证分类、商品、登录、资料、收藏和浏览历史仍可用，并记录排除路由恢复为部署前行为。

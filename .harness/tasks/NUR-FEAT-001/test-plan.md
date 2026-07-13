# NUR-FEAT-001 测试计划

## 自动测试

- `nursery_scope_contract`：执行 argv `['python', 'tests/nursery/test_scope_contract.py']`。结构化解析插件 `config.json`，逐项检查 15 个 Hook、Web/API/Admin 的 8/10/12 个拒绝控制器、23 个 PX 插件标识、正向控制器集合、异常中断、插件路由读取边界、`admin_left_menu/admin_power/admin_plugins/admin_all_plugins`、无 control 的 `plugins-<name>` 菜单 id/key/URL、结构化导航和按钮过滤、用户中心替代视图及禁止核心/SQL引用。对 23 个插件菜单逐项做临时负变异，不修改仓库业务文件。
- `harness_selftest`：执行 argv `['python', 'scripts/harness_selftest.py']`，确认任务没有绕过范围、审批、证据、符号链接或工作区变更门禁；平台不支持的符号链接用例只能记 skip。
- Harness `verify` 以无 shell、清理敏感环境、超时和输出上限运行上述命令；任何退出码非 0、超时、输出溢出或工作区变更均失败。

## 手工验收

在后续获批的 PHP/MySQL 测试或部署任务中安装并启用 nursery 插件、确认生成的 `app/event.php` 注册本任务 Hook，然后执行：

1. 游客 PC/移动首页：顶部和底部无购物车/订单/支付/分销入口；分类、搜索、商品卡片仍可访问。
2. 展示型与普通商品详情：均无 buy/cart；展示型 show/电话咨询可保留；收藏入口仍可用；隐藏表单不能通过直达路由提交。
3. 登录用户中心：仅保留资料、账号安全、收藏、浏览历史和消息相关现有能力；无订单、售后、购物车、评价或积分区块。
4. Web/API 负例：逐个覆盖合同锁定的 Web 8 个和 API 10 个控制器，分别请求 `index` 和至少一个真实写 action，预期 HTTP 404/框架等价不可达，且购物车/订单/支付表无新增或修改；混合大小写控制器/action 也不可绕过。
5. 后台最小权限管理员：逐个覆盖 12 个后台控制器；交易菜单不存在，`AdminIsPower` 对对应 action 返回 false，直接请求任意 action 均不可达；逐个构造或安装 23 个 PX 插件菜单形态，确认无 control 的 `id/key=plugins-<name>` 项也消失；商品分类、商品管理、用户查看和 nursery 菜单保持可用。分别在暖缓存和清缓存后重复。
6. 插件负例：逐个覆盖 23 个固定 PX 插件标识，index/api/admin 的插件入口均不可达；`pluginsname=nursery` 和非 PX 测试插件不被策略拒绝。
7. 禁用插件并刷新缓存：确认事件映射移除、路由恢复部署前行为，用于证明回滚可控；随后按发布计划重新启用。

## 数据与权限

本任务不新增用户数据访问、统计事件或迁移。运行测试使用无真实个人数据的游客、普通测试用户和非 `id=1/role_id=1` 最小管理员；拒绝请求前后对购物车、订单、支付、售后、用户、收藏和商品表做计数/更新时间抽样，证明无业务副作用。禁止把隐藏菜单当作后台权限验证，必须同时验证直达路由。

## 未覆盖项

- 当前本机没有 PHP、Composer、MySQL 或 Docker，不能执行 PHP 语法、ShopXO 启动、插件安装、事件生成、HTTP、数据库副作用或浏览器测试；这些项目保持 `not_run`，不计为通过。
- 离线测试不能证明 ThinkPHP 的最终错误响应格式、菜单缓存刷新和第三方插件实际状态。
- `install.php`、`core.php`、`router.php`、静态文件和直连 FPM 不经过 `plugins_service_system_begin`，由 NUR-OPS 部署边界负责。
- API `user/center` 上游响应仍会计算订单、积分和购物车计数，但对应功能路由和 H5 导航已关闭；App/小程序本身是 P2 排除范围。若首版 API 契约要求移除这些字段，应建立独立兼容性任务，不能在本任务静默破坏上游响应结构。
- 真实运行补测责任属于后续 L4 部署任务；任一正向路由误伤或负向路由可达都阻塞发布。

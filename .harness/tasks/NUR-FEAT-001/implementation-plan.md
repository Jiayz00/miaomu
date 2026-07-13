# NUR-FEAT-001 实施计划

## 实施步骤

1. 在 `app/plugins/nursery/config.json` 写入 ShopXO 6.9.0 可识别的插件元数据和 Hook 映射。只注册源码已确认存在的 `plugins_service_system_begin`、顶部/底部/用户中心/后台菜单、商品按钮、`plugins_view_assign_data` 与 `plugins_view_fetch_begin`；不生成 `app/event.php`。JSON 解析或 Hook 映射测试失败即停止。
2. 在 `service/ScopePolicy.php` 定义不可由请求修改的模块-控制器拒绝表、PX 插件标识、菜单/按钮过滤方法和正向边界。所有比较先做字符串小写化，按控制器整体拒绝所有 action；`index`、`api`、`admin` 分表处理，其他模块默认不由本策略拒绝。测试发现允许控制器误入拒绝表或拒绝控制器缺失即停止。
3. 在 `Hook.php` 以 `hook_name` 白名单分派：
   - system begin 调用 `RequestModule/Controller/Action`，命中时使用 ThinkPHP `abort(404, ...)` 中断；插件请求额外检查 `pluginsname`。
   - 导航、后台菜单与权限、商品按钮通过引用原地过滤并重建数组索引。
   - view assign 仅在 `index/index/index` 清空 `user_order_status`。
   - view fetch 仅在 `index/user/index` 把模板路径替换为插件自有视图。
   未识别 Hook 不修改参数并返回空值。
4. 在 `Event.php` 提供无数据库写入的标准生命周期回调，使 ShopXO 安装、启用、禁用与卸载流程可识别插件；不自动修改系统配置、管理员权限或历史数据。
5. 在 `view/index/user/index.html` 复用当前主题的公共头部、导航、用户菜单和页脚，保留用户资料、消息、收藏及浏览历史数据，仅删除订单状态、进行中订单、购物车、售后、评价和积分链接。页面不创建“我的询价”假入口，后续询价任务通过插件/主题扩展。
6. 在 `tests/nursery/test_scope_contract.py` 使用 Python 标准库解析 JSON 和源码，断言 Hook 映射、固定拒绝/允许集合、`abort` 语义、无动态请求控制策略、菜单/按钮过滤、替代视图无 PX URL、允许路径未引用核心文件，并用临时变异副本验证关键缺口会使测试失败。

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

# NUR-FEAT-001 实施证据

## 验收标准映射

- `AC-TASK-001`：离线合同测试确认 `config.json` 精确登记 15 个已核验 Hook，前后台导航、后台快捷菜单、商品按钮、首页赋值和用户中心替换视图均有对应过滤分支；默认快捷菜单 `178/364` 与 distribution/coupon/seckill 被拒，商品、站点和 nursery 正例保留。替换视图保留资料、安全、消息、收藏和浏览历史，未包含排除能力链接。真实页面结果留待 L4 运行环境验收。
- `AC-TASK-002`：离线合同测试确认 Web 8 个、API 10 个、后台 12 个控制器、23 个 PX 规范标识和 4 个明确等价标识固定在大小写无关拒绝表中；8 个首版未授权标识仅从入口隐藏，直达策略不永久扩大。系统起始 Hook 使用 `abort(404, ...)`，`pluginsname` 与 H5 `/pages/plugins` 会扫描全部匹配，后台四类菜单/权限数组、快捷菜单及无 `control` 的插件菜单 `id/key/url` 均被覆盖。真实 HTTP 与权限副作用留待 L4 运行环境验收。
- `AC-TASK-003`：离线合同测试确认三组正向控制器与 8 个仅隐藏标识未误入直达拒绝集合、用户中心仍包含收藏和浏览历史入口；Git 索引确认包括被上游 ignore 命中的 `Event.php` 在内全部 5 个插件文件可进入干净克隆，并确认本任务未修改或删除 ShopXO 核心、SQL、迁移或生成的 `app/event.php`。

## 自动测试证据

VERIFY_CONTRACT_SHA256: 0d2cba99830f71a2dc5550c59e5401a8382ab46866f391978d379ca1c321128b

TEST_COMMAND: nursery_scope_contract ["python", "tests/nursery/test_scope_contract.py"]
TEST_RESULT: nursery_scope_contract exit_code=0

结果：19 项合同测试通过；覆盖逐 Hook、逐拒绝控制器、23+4 直达拒绝、8 个仅隐藏入口、重复插件 URL 全量扫描、后台快捷菜单、Git 跟踪、导航、按钮和视图关键分支的临时副本负变异。Harness 记录于 `.harness/runs/NUR-FEAT-001/20260713T153549168154Z-verify/`。

TEST_COMMAND: harness_selftest ["python", "scripts/harness_selftest.py"]
TEST_RESULT: harness_selftest exit_code=0

结果：60 项 Harness 自测通过；2 项需要 Windows 符号链接权限的用例明确 skip，不影响本任务业务断言。`source-check` 与 `scope-check NUR-FEAT-001` 另行执行并均为 exit code 0，范围检查为 tracked=10、untracked=0、无越界路径。

## 手工与页面证据

本任务未安装或启用插件，未生成 `app/event.php`，也未执行 PHP 语法、ShopXO 启动、HTTP、数据库副作用或浏览器页面测试。上述检查不是通过项，必须在获批的 L4 部署任务中使用 PHP/MySQL 测试环境补齐后才能发布。

## 已知限制

- 本机没有 PHP、Composer、MySQL 或 Docker；当前证据只证明源码合同和 Harness 边界。
- 离线测试不能证明 ThinkPHP 最终 404 响应、插件安装/启用、`app/event.php` 生成、菜单缓存刷新、数据库无副作用或真实主题渲染。
- API `user/center` 的上游订单、积分和购物车计数计算未在本任务移除；对应路由和可见导航已收敛，响应字段兼容性如需改变必须另立任务。
- `install.php`、`core.php`、`router.php`、静态文件和直连 FPM 不经过本插件系统起始 Hook，必须由部署边界阻断。

## 回滚证据

未执行部署，因此没有远程回滚演练。源码回滚边界已由 scope-check 证明仅包含 `app/plugins/nursery/**`、`tests/nursery/**` 和当前任务制品。部署后的回滚必须先禁用 nursery 插件并刷新事件映射与缓存，确认 `app/event.php` 不再引用 nursery，再回退源码；不得删除商城核心表或历史数据。

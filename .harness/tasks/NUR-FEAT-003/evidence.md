# NUR-FEAT-003 实施证据

## 验收标准映射

- `AC-TASK-001`：离线合同通过。`FavoriteService` 使用显式幂等 `Add/Cancel`，Web/API 控制器不调用 toggle；商品卡片、详情、移动端导航和基础收藏页只调用独立 add/cancel URL，页面没有询价占位入口。证据：`tests/nursery/test_favorite_contract.py` 与本次 `nursery_favorite_contract` 输出。
- `AC-TASK-002`：离线合同通过。favorite schema v1 固定 `(user_id, goods_id)` 唯一索引；迁移先扫描重复、发现冲突失败关闭且没有删除路径，运行时 Add 同时要求真实索引和匹配台账。真实 MySQL 并发尚未执行，列入 L4 集成验证。
- `AC-TASK-003`：离线合同通过。控制器只把网关认证用户传给服务；读写条件固定包含认证 `user_id`；列表使用左连接并输出 `active/off_shelf/deleted`，缺失商品没有详情链接或伪价格。真实 A/B 会话越权和数据库状态流转尚未执行。
- `AC-TASK-004`：离线合同通过。旧 Web 收藏列表统一重定向到 nursery 左连接列表，导航同步改写；旧 API 收藏列表、旧 Web/API 收藏写 action、`admin/goods/delete` 路由和 `goods_delete` 权限被拒绝。目录价格与 PX 范围回归继续通过；差异未修改 ShopXO 核心或 `config/shopxo.sql`。

## 自动测试证据

VERIFY_CONTRACT_SHA256: 0e0a5243234746ae456d0e195732b1201796432151e956ce04507e5d075b428a

TEST_COMMAND: nursery_favorite_contract ["python", "tests/nursery/test_favorite_contract.py"]
TEST_RESULT: nursery_favorite_contract exit_code=0

TEST_COMMAND: nursery_catalog_price_regression ["python", "tests/nursery/test_catalog_price_contract.py"]
TEST_RESULT: nursery_catalog_price_regression exit_code=0

TEST_COMMAND: nursery_scope_regression ["python", "tests/nursery/test_scope_contract.py"]
TEST_RESULT: nursery_scope_regression exit_code=0

TEST_COMMAND: harness_selftest ["python", "scripts/harness_selftest.py"]
TEST_RESULT: harness_selftest exit_code=0

本地运行：`.harness/runs/NUR-FEAT-003/20260713T225005175873Z-verify/`。最终报告记录 `passed=4 failed=0 blocked=0`；收藏合同 33 项、目录价格回归 30 项、范围回归 23 项、Harness 自检 60 项通过且 2 项平台相关测试按既有条件跳过。运行清单确认 `workspace_fingerprint` 与 `post_test_workspace_fingerprint` 相同，Harness 控制面校验前后一致。

## 手工与页面证据

未执行。当前 Windows 工作区没有 PHP、Composer、MySQL、Docker 或可运行 ShopXO 的本地服务，因此没有伪造 PHP lint、HTTP 响应、数据库并发或浏览器截图。后续 L4 集成任务必须在隔离服务器实例完成 PHP lint、MySQL 8 迁移矩阵、A/B 用户越权、匿名/CSRF、下架/删除/缺失商品、PC/H5 页面和旧路由烟雾测试。

## 已知限制

- 当前证据证明源码合同、路径边界和回归测试，不证明 ThinkPHP 运行时方法签名、MySQL DDL、真实会话或浏览器渲染。
- `sxo_goods_favor` 的真实历史重复、同名索引冲突和 DDL 权限只能在部署前只读预检后确认；存在重复时必须停止，不能自动去重。
- 收藏统计事件不在本任务范围；本任务实现没有事件或询价服务调用。
- 后台 `admin/goodsfavor/delete` 仍作为原 ShopXO 特权管理能力保留；普通用户入口不可达，后续权限/审计任务需决定是否进一步禁用。

## 回滚证据

未部署，未执行远程回滚演练。代码回滚可移除本任务插件控制器、服务、视图和静态资源，但已创建的唯一索引与迁移台账必须保留；不得回退到并发不安全的旧写入口，也不得删除收藏行。真实回滚演练由后续 L4 集成/发布任务在备份副本上完成。

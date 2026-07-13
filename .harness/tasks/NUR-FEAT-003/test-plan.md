# NUR-FEAT-003 测试计划

## 自动测试

### nursery_favorite_contract

命令：`["python", "tests/nursery/test_favorite_contract.py"]`

断言版本清单、重复检测先于 DDL、同连接迁移锁与释放、唯一索引列序、显式迁移 CLI、运行时 `AssertReady` 同时核验台账与实际索引且未迁移时 Add 失败关闭、Add/Cancel 非 toggle、认证用户强制条件、左连接下架保留、旧 API `usergoodsfavor/index` 拒绝和 Web 旧列表视图替换、无询价引用、旧写 action 和物理删除拒绝、详情两处与列表按钮不触发 ShopXO toggle handler、基础列表无假询价入口、无核心和 `config/shopxo.sql` 差异。

### nursery_catalog_price_regression

命令：`["python", "tests/nursery/test_catalog_price_contract.py"]`

确认目录台账、上架价格门禁和公开参考价模型未被收藏实现改变。

### nursery_scope_regression

命令：`["python", "tests/nursery/test_scope_contract.py"]`

确认 PX 路由、导航、用户中心、商品模板和主题边界保持通过，并验证旧收藏写入口及物理删除新增拒绝不放宽既有规则。

### harness_selftest

命令：`["python", "scripts/harness_selftest.py"]`

确认范围、审批、证据、状态和隔离执行门禁未被削弱。

## 手工验收

后续 L4 隔离环境必须执行：

1. PHP lint 全部新增/修改 PHP。
2. MySQL 8 分别验证空表、合法存量、历史重复、同名冲突索引、重复迁移和两个并发 add；重复场景不得改变行数。
3. 用户 A/B 与匿名身份覆盖列表/详情 add、重复 add、cancel、重复 cancel、status/list 及篡改 user_id/ID；B 不能观察 A 记录是否存在。
4. 用户 A 收藏后下架、设置逻辑删除状态并模拟商品缺失；收藏行保留，列表显示不可用，A 可取消。
5. 记录收藏操作前后询价表/事件表行数，确认 AC-002 无副作用。
6. 访问所有旧 Web/API 收藏写 URL、旧 API `usergoodsfavor/index` 和 admin 物理删除 URL，必须拒绝；Web `usergoodsfavor/index` 必须展示 nursery 列表且下架/缺失记录不丢失，商品上下架仍正常。
7. 浏览器检查 PC/H5 按钮状态、未登录弹层和基础收藏页，确认没有询价假入口、购物车或订单入口。

## 数据与权限

- fixture 使用两个普通用户、一个管理员和至少一个在架/下架商品，不使用真实个人数据。
- 用户断言始终以认证上下文为真源；错误响应不返回他人收藏 ID、用户 ID 或存在性差异。
- 迁移前后比较 `sxo_goods_favor` 行数和重复分组；迁移不得删除、合并或修改收藏时间。
- 商品状态变化不得级联删除收藏；取消只能删除当前用户目标行。
- 本任务不采集 PV/UV 或询价事件；相关表必须保持不变。

## 未覆盖项

- 当前本机没有可用 PHP/MySQL/Docker 运行栈，自动测试只能证明离线源码合同，不能证明真实事务、DDL、会话或浏览器行为。
- 上述 PHP/MySQL/HTTP/browser 项必须由后续 L4 集成任务在部署前真实执行并记录退出码；未执行时标记 `not_run`，不得写为通过。
- 生产服务器、Caddy 和真实用户数据不属于本任务，不能在本任务验证阶段访问。

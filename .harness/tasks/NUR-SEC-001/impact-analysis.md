# NUR-SEC-001 影响分析

## 需求与当前事实

当前固定上游为 ShopXO `d1825c5404054b535255d8fcad675a5dae0ab633`。`SearchService::GoodsList()` 和 `GoodsService::GoodsDataHandle()` 已提供规格、参数和产地处理，但当前 nursery Hook 没有打开 `is_spec/is_params`，收藏查询只取商品基础字段。商品保存事务有 `plugins_service_goods_save_handle`/`*_thing_begin`/`*_thing_end`，状态更新只有更新后的 `plugins_service_goods_field_status_update`。

## 当前调用链与数据

- 搜索/首页：`SearchService::GoodsList` 或 `GoodsService::GoodsList` → `GoodsDataHandle` → nursery `Hook`；通过参数开启规格/参数，模板读取派生字段。
- 收藏：`FavoriteController` → `FavoriteService::Add/Cancel/Listing` → `GoodsFavor`；新增独立 `PluginsNurseryFavoriteRateLimit` 表。
- 商品保存：`admin/Goods::Save` 注入认证 `admin` → `GoodsService::GoodsSave` 事务 → nursery Hook；插件在事务前读取旧摘要，在事务后追加 `PluginsNurseryGoodsAudit`。
- 上下架：`GoodsService::GoodsStatusUpdate` 事务更新前锁定旧 `is_shelves`，把 `previous_goods` 传给现有 Hook；插件只对真实变化写审计。
- 迁移：`FavoriteMigration::Run` 在既有收藏唯一索引迁移后编排 `SecurityMigration`，写入 `sxo_config` 非敏感台账。两张新表不建立外键。

## 影响范围

- 用户端：首页、搜索/分类列表、收藏列表和商品详情模板；下架详情隐藏不可用询价 CTA，历史查看链路不变。
- 管理端：商品保存/上下架事务增加短审计写入；不改变管理员权限或原字段语义。
- 数据：新增两个 nursery 表与一个台账，不改商品、收藏、询价历史数据；审计只保存价格/状态摘要。
- 安全：收藏限流按 `user_id + action` 独立计数；缺表、结构漂移、事务失败均拒绝写操作。审计表只追加，普通商品操作无删除路径。
- 性能：列表规格为批量 `GoodsSpecificationsData` 查询；收藏规格和产地按收藏商品 ID 批量查询，避免 N+1；限流为每次一次行锁事务。
- 升级：核心只增加 Hook 参数；上游同步需重新核对 `GoodsStatusUpdate` 行号。回滚保留新表和历史数据。

## 方案比较

1. 配置：不能让 ShopXO 配置生成主要规格/审计，排除。
2. 现有服务：复用 `GoodsDataHandle`、`RegionService`、`FavoriteMigration` 和认证上下文。
3. Hook：列表/保存使用已验证 nursery Hook；状态 Hook 缺旧值，因此登记一处最小核心适配。
4. nursery 插件：所有展示、限流、迁移和审计逻辑放在插件服务/视图中。
5. 核心适配：仅 `GoodsService::GoodsStatusUpdate` 在同一事务内读取并传递 `previous_goods`，不改写业务状态机。

## 风险与边界

- 结构冲突或迁移中断不得自动 ALTER/删除，必须前向修复。
- 价格摘要只允许规范化十进制/范围 JSON；不记录富文本或个人数据。
- 审计写入失败使商品事务回滚，避免“成功但无审计”；相同值不生成虚假行。
- 下架 CTA 只影响新询价入口，服务端历史读取和公开列表规则保持原样。
- 列表规格字段为空时显示稳定空态，不把库存或购物车字段误当规格。

## 预计文件

- 修改：`app/plugins/nursery/Hook.php`、`FavoriteService.php`、`FavoriteMigration.php`、商品/收藏视图、`app/service/GoodsService.php`、配置与静态 CSS。
- 新增：`security-schema-v1.json`、`SecurityMigration.php`、`FavoriteRateLimit.php`、`GoodsAuditService.php`、合同测试。
- 迁移入口：`scripts/nursery_favorite.php`（保持 status/preflight/migrate 语义）。
- 测试：`tests/nursery/**`，不修改 `config/shopxo.sql` 或 vendor。

# NUR-FEAT-003 影响分析

## 需求与当前事实

- 固定上游为 ShopXO 6.9.0 `d1825c5404054b535255d8fcad675a5dae0ab633`，当前仓库 `source-check` 通过。
- `sxo_goods_favor` 只有主键；没有 `(user_id, goods_id)` 唯一约束。
- `GoodsFavorService::GoodsFavorCancel()` 先查询再 toggle；并发可重复插入，重试可能反向取消。
- `UserGoodsFavorListWhere()` 排除逻辑删除商品，列表与总数使用内连接，不能呈现不可用收藏。
- 公共 Web/API 调用者虽然传入当前用户，但核心服务的用户条件是可选模式，不适合作为 nursery 的强制所有权边界。
- `GoodsService::GoodsDelete()` 物理删除，删除 Hook 在删除后触发；必须在 `plugins_service_system_begin` 阶段拒绝 `admin/goods/delete`。
- nursery 已有请求范围、视图替换和公开参考价服务，可在插件边界扩展，无需核心适配。

## 当前调用链与数据

```text
商品列表/详情按钮
  -> nursery 静态脚本选择 add 或 cancel
  -> index/plugins 或 api/plugins 网关
  -> nursery Favorite 控制器（读取认证 user）
  -> FavoriteService（忽略请求 user_id）
  -> sxo_goods_favor UNIQUE(user_id, goods_id)

我的收藏
  -> nursery Favorite::Index/List
  -> f.user_id = 认证用户
  -> LEFT JOIN goods
  -> 当前参考价 + active/off_shelf/deleted 状态

旧写入口/admin 物理删除
  -> plugins_service_system_begin
  -> ScopePolicy action 级拒绝
```

迁移入口为 `scripts/nursery_favorite.php migrate --actor ... --run-id ...`。它读取版本清单，先扫描重复，再核验/创建唯一索引并记录 `sxo_config` 台账；不依赖 `install.sql`。

## 影响范围

- 用户端：列表和详情可添加/取消；提供基础收藏列表和下架状态，不提供假询价入口。
- 管理端：物理删除路由和权限入口关闭；上下架继续使用现有能力。
- API：显式 add/cancel/status/list，user_id 只取认证上下文。
- 历史：迁移不删除收藏；下架、逻辑删除或商品缺失不删除收藏行。
- 安全：所有查询强制 user_id；旧 toggle 和可选 user 旁路不可达；IDOR 返回统一不存在结果。
- 性能：唯一索引支持状态和写入查询；列表分页并批量处理商品，禁止 N+1。
- 升级：差异集中于 nursery 插件和版本化 CLI；唯一索引为前向约束，代码回滚默认保留。
- 统计：本任务不产生询价或运营事件，不改变 PV/UV 口径。

## 方案比较

1. 配置不能增加唯一约束、显式命令语义或强制用户过滤，不足。
2. 现有收藏服务可复用商品处理思路，但 toggle、可选用户条件和内连接不满足业务不变量，不直接使用写路径。
3. 已验证的 system/view Hook 可关闭旧路由、过滤物理删除权限并接入插件视图，选用。
4. nursery 插件承载控制器、服务、迁移和页面，选用。
5. 单文件项目 CLI 承载显式 schema 迁移，避免被忽略的插件安装回调，选用。
6. 核心适配没有必要；`app/service/**`、核心控制器和默认主题保持不变。

## 风险与边界

- 并发：不能以先查再插入代替数据库唯一约束；重复键只在确认目标行属于同一用户/商品后视为幂等成功。
- 迁移：历史重复、同名冲突索引或异常 schema 必须失败关闭；不静默去重。MySQL DDL 隐式提交，台账失败通过重跑前向修复。
- IDOR：请求中的 `user`、`user_id`、收藏 ID 都不能放宽认证用户条件。
- 下架：取消收藏仍允许；查看商品仅在商品可公开访问时提供，收藏行本身保留。
- 旁路：Web/API 四个旧写 action 与 admin 物理删除必须同时拒绝；旧 API `usergoodsfavor/index` 仍使用内连接并过滤逻辑删除商品，不能作为合规读取入口，必须拒绝并由 nursery `list` 替代。Web `usergoodsfavor/index` 只可作为替换后的 nursery 页面壳，不得继续读取旧列表服务。只改前端按钮不算完成。
- 部署顺序：`Add` 在每次写入前必须核验 favorite schema v1 台账与实际唯一索引；台账缺失、结构漂移或迁移未完成时失败关闭，不能在无数据库唯一约束时退化为先查后写。
- 回滚：不自动删除唯一索引，否则旧 toggle 并发会重新产生重复。
- PX：新增脚本和视图不得恢复购物车、订单、支付或售后入口。

## 预计文件

预计修改：`app/plugins/nursery/config.json`、`Hook.php`、`service/ScopePolicy.php` 和 nursery 用户中心视图。

预计新增：`favorite-schema-v1.json`、`service/FavoriteMigration.php`、`service/FavoriteService.php`、`index/Favorite.php`、`api/Favorite.php`、收藏视图/按钮模板、`public/static/plugins/nursery/js/favorite.js`、`scripts/nursery_favorite.php`、`tests/nursery/test_favorite_contract.py`。

迁移修改 `sxo_goods_favor` 和 `sxo_config`。不修改核心，不新增核心登记。

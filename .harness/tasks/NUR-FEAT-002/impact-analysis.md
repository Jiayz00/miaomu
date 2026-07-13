# NUR-FEAT-002 影响分析

## 需求与当前事实

- 固定基线为 ShopXO 6.9.0、上游提交 `d1825c5404054b535255d8fcad675a5dae0ab633`，`source-check` 已通过。
- 当前 `nursery` 插件只承担 PX 路由/菜单/视图收敛，没有目录迁移或价格校验。
- `app/service/GoodsService.php::GoodsSave()` 在规格解析完成、事务开始前触发 `plugins_service_goods_save_handle`，其非零返回会阻止保存。
- `GoodsStatusUpdate()` 在事务内先更新字段再触发 `plugins_service_goods_field_status_update`，忽略 Hook 返回；监听器抛出的异常会被外层捕获并回滚。
- `GoodsSaveBaseUpdate()` 以 `sxo_goods_spec_base.price` 的 MIN/MAX 更新 `sxo_goods.min_price/max_price/price`。
- 核心单规格只拒绝 `< 0`，多规格没有完整正价和严格格式校验，零价可进入数据库。
- `sxo_goods_spec_base.price` 是 `DECIMAL(10,2)`；`sxo_config.only_tag` 有唯一索引；分类、规格模板和参数模板没有自然唯一约束。
- 默认搜索样式可使用 `module/goods/grid/base`，当前 nursery 只替换 list/base 和 slider/binding，grid 仍需纳入公开价格与 PX 回归范围。

## 当前调用链与数据

```text
后台商品表单/API
  -> GoodsService::GoodsSave
  -> GetFormGoodsSpecificationsParams
  -> plugins_service_goods_save_handle (事务前，可返回失败)
  -> Goods/CategoryJoin/SpecType/SpecValue/SpecBase/Params 写入
  -> GoodsSaveBaseUpdate (规格聚合主表价格)
  -> commit

后台独立上架
  -> GoodsService::GoodsStatusUpdate
  -> update sxo_goods.is_shelves (事务内)
  -> plugins_service_goods_field_status_update
  -> 监听器抛异常则 rollback

公开列表/详情/API
  -> GoodsService::GoodsDataHandle
  -> 生成价格开关、符号、单位和 price_container
  -> plugins_service_goods_handle_begin
  -> default 主题 grid/list/slider 或详情模板
```

目录迁移涉及：

- `sxo_goods_category`：一级和二级目录；
- `sxo_goods_spec_template`：每个一级目录最多两个 SKU 规格模板；
- `sxo_goods_params_template`、`sxo_goods_params_template_config`：苗木属性模板；
- `sxo_config`：唯一台账。

与目录导入解耦的价格完整性检查只读 `sxo_goods_spec_base`；只有后续显式 `apply` 才写 `sxo_goods` 做受控下架或派生汇总修正。插件安装和目录升级不会调用 apply。

## 影响范围

- 用户端：default 主题 grid/list/slider 和详情统一使用“参考价”；区间列表显示最低价起，详情继续使用 ShopXO 的区间及规格切换。
- 管理端：既有商品表单不改核心 UI；保存和独立上架增加服务端硬门禁。管理员仍可管理分类的排序、图片、描述、SEO 和启停，也可新建分类，但新分类必须经后续目录版本纳管后才可用于商品。
- API：商品经公共处理 Hook 获得 `reference_price`，包含 `mode/min/max/unit/text/short_text/disclaimer`；原始价格字段保留兼容。
- 历史：目录迁移不修改商品；独立价格修复 apply 不删除商品或任何收藏、询价、统计，非法存量价格商品只下架并记录原因。
- 安全：不新增用户输入面或权限；严格拒绝非 ASCII 数字、指数、符号、NaN/INF 等绕过格式。
- 性能：公开价完全从当前商品行派生，不增加列表 N+1 查询；目录迁移只在安装/升级显式执行。
- 升级：变更集中在插件；`config/shopxo.sql` 和核心不变。新增 grid 同构模板需通过固定上游差异测试防止未来同步漂移。
- 执行入口：`PluginsUpgrade()` 在替换新包前调用 `BeginUpgrade`，因此安装/升级事件只能做只读预检；`scripts/nursery_catalog.php` 在新代码就位后初始化 ShopXO，提供可锁定 argv、退出码和 JSON 输出的 migrate/integrity 入口。

## 方案比较

1. 配置：ShopXO 有单分类模式和价格展示开关，但不能严格验证多规格价格、阻断零价上架或管理种子所有权，单独使用不足。
2. 现有服务：分类、规格和参数服务可用于后台操作，但没有跨实体唯一台账和原子导入；直接调用还会产生嵌套事务边界，不能满足整批回滚。
3. 已验证 Hook：保存、状态更新、商品处理、详情价格底部和视图替换 Hook 能覆盖门禁与展示，选用。
4. nursery 插件：以结构化 JSON 清单和插件迁移服务直接使用 ThinkPHP Db 事务实现目录台账与模板；价格完整性检查使用独立服务并默认为 dry-run；选用。
5. 项目 CLI：新增单文件 `scripts/nursery_catalog.php` 作为部署后受控入口，避免内联 PHP、临时脚本和返回值被忽略的插件回调；选用。
6. 独立模块/核心适配：没有必要；不会修改 `app/service/**`、控制器、默认主题或数据库基础 SQL。

## 风险与边界

- `GoodsStatusUpdate()` 忽略返回值：状态 Hook 必须抛异常，使用 `DataReturn` 会错误放行。
- 原始价格会被 PHP 宽松数字转换：必须在 Hook 中针对原始 `specifications_price[]` 做完整字符串正则和范围比较。
- 导入并发：台账唯一索引与同一事务防止双重所有权；唯一冲突或结构冲突必须整体回滚。
- 升级时序：`BeginUpgrade` 不得写数据；CLI 只在新代码部署完成后运行，失败时保留旧台账并返回非零退出码。
- CLI 误用：migrate 要求显式 mode；integrity 默认 dry-run，apply 同时要求 `--apply`、非空 actor 和唯一 run-id，输出不得包含敏感数据。
- 管理员编辑与托管漂移：只校验 seed_key、数据库 ID、父级和规范化名称等结构身份；不回写运营字段。
- 分类绕过：叶子状态不足以证明是苗木目录；保存和上架必须从 `plugins_nursery_catalog_manifest` 解析受管二级叶子 ID，拒绝旧演示目录和未纳管新分类。
- 存量价格：目录安装不得隐式修改；独立 dry-run 先给出清单，显式 apply 时无效规格只下架，不能补假价格，规格有效的汇总漂移才允许按 MIN/MAX 修正。
- 模板复制：grid/list/slider 必须保留原 Hook 和页面结构，不得重新加入购物车或覆盖非 default 主题自有模板。
- 本机工具缺口：Python 静态测试不能证明 PHP 语法、事务或页面行为；这些结果必须在 L4 服务器集成任务中另行取得。

## 预计文件

修改：

- `app/plugins/nursery/config.json`
- `app/plugins/nursery/Hook.php`
- `app/plugins/nursery/Event.php`
- `app/plugins/nursery/service/ScopePolicy.php`
- `app/plugins/nursery/view/index/module/goods/list/base.html`
- `app/plugins/nursery/view/index/module/goods/slider/binding.html`

新增：

- `app/plugins/nursery/catalog-v1.json`
- `app/plugins/nursery/service/CatalogMigration.php`
- `app/plugins/nursery/service/CatalogIntegrity.php`
- `app/plugins/nursery/service/CatalogPolicy.php`
- `app/plugins/nursery/service/ReferencePriceService.php`
- `app/plugins/nursery/view/index/module/goods/grid/base.html`
- `scripts/nursery_catalog.php`
- `tests/nursery/test_catalog_price_contract.py`

不修改核心登记，因为没有 ShopXO 核心差异。

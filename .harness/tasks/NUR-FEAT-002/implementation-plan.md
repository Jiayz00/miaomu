# NUR-FEAT-002 实施计划

## 实施步骤

1. 建立结构化目录清单
   - 新增 `catalog-v1.json`，声明 schema/version、默认单位、8 个一级及二级叶子、每类最多两个规格模板和苗木参数模板。
   - 固定 seed_key；厘米规格名称显式带 `(cm)`，值只使用数值或 `min-max`，交叉属性进入参数。
   - 验证：Python 解析 JSON，检查层级、父键、唯一键、分类集合、规格维度和单位集合。

2. 实现事务化目录迁移
   - `CatalogMigration::Run($mode)` 只接受 `existing/fresh`；fresh 在本任务中不做清理。
   - 事务内锁定 `plugins_nursery_catalog_manifest`，校验版本、清单哈希和受管结构身份；同父同名未托管、父级冲突、ID 缺失或结构漂移抛异常。
   - 首次执行按父子顺序插入分类、规格模板、参数模板/配置，写入 version、mode、seed_key、ID、结构哈希和清单哈希。
   - 目录事务不得扫描或修改商品状态；运营字段不进入结构哈希且不被回写。
   - 提交后清理 ShopXO 分类缓存；失败回滚全部新增和修复。
   - `Event::BeginInstall/BeginUpgrade` 只调用 `CatalogMigration::Preflight()` 并返回真实只读结果；不得在插件包替换前写数据，Install/Upgrade 也不承担权威迁移。

3. 提供受控 CLI 入口
   - 新增 `scripts/nursery_catalog.php`，通过固定仓库根加载 ShopXO autoload/应用，拒绝未知动作和未知参数，以 JSON 输出并用非零退出码表示失败。
   - `migrate --mode existing|fresh --actor <actor> --run-id <id>` 在新代码就位后调用写迁移；mode、actor、run-id 均必填并写入台账。
   - `integrity` 默认 dry-run；只有 `integrity --apply --actor <actor> --run-id <id>` 才允许修改，并把 before/after、原因和操作者写入审计配置。
   - L4 `remote_execution` 只能锁定该脚本的结构化 argv，不允许内联 PHP、临时脚本或原始 SSH 命令。

4. 实现独立价格完整性检查
   - `CatalogIntegrity::Run($apply=false, $actor='', $run_id='')` 批量读取在架商品和规格，默认返回 dry-run 清单，不写数据库。
   - 显式 apply 在独立事务中对无规格/非法价商品下架，对合法规格但汇总漂移商品重算派生汇总，并记录 before/after、原因和运行标识；重复运行不重复修复。
   - `BeginInstall/BeginUpgrade` 不得调用该入口；实际 apply 只能由后续获批的集成/发布步骤显式调用。

5. 实现目录与保存门禁
   - `CatalogPolicy` 从 `plugins_nursery_catalog_manifest` 解析受管二级叶子 ID，规范化分类 ID 和单位，验证恰有一个主归属分类、该 ID 受管且分类启用并无启用子节点、规格维度最多两个、主单位及规格单位属于默认白名单；旧演示叶子和未纳管新分类失败。
   - `ReferencePriceService::ValidateSave()` 对原始 `specifications_price[]` 要求字符串完整匹配 `^[0-9]{1,8}(\.[0-9]{1,2})?$`，规范化两位小数；草稿允许 0.00，上架每行要求正价且不超过 99999999.99。
   - `Hook::handle()` 在 `plugins_service_goods_save_handle` 返回验证失败，保证发生在核心事务前。

6. 实现独立上架数据库复核
   - 在 `plugins_service_goods_field_status_update` 且 `field=is_shelves,status=1` 时读取商品规格和主分类。
   - 要求规格存在、每行正价有效、主表 min/max/price 与规格聚合一致、分类属于当前台账的单一受管启用二级叶子且单位有效；不一致抛 `RuntimeException` 触发核心事务回滚。
   - 下架及其他状态字段直接返回，不更改历史。

7. 统一公开参考价模型
   - 在 `plugins_service_goods_handle_begin` 从当前商品 `min_price/max_price/inventory_unit` 派生 `reference_price`。
   - 强制 `show_field_price_status=1`，标题改为“参考价”，输出 fixed/range、两位小数 min/max、单位、列表短文案、详情文案和固定免责声明；不查询额外表。
   - 保留 ShopXO 原价格字段和 `price_container`，确保规格选择脚本继续使用确切规格价。

8. 覆盖 default 主题公开商品模板
   - 扩展 `ScopePolicy` 的受主题映射，新增 `module/goods/grid/base`；直接路径只替换 default 主题，显式 `../default` 回退始终替换。
   - grid/list/slider 同构模板使用 `reference_price.short_text`，保留原 Hook、链接、图像、布局类与非 PX 功能，移除/不恢复购物车入口。
   - 详情通过 `plugins_view_goods_detail_panel_price_bottom` 返回 BR-PRICE-004 原文提示，不复制核心详情模板。

9. 增加合同和回归测试
   - 新增 `test_catalog_price_contract.py`，对清单、Hook、严格价格规则、异常语义、迁移原子性标记、台账、模板映射、免责声明、Git 跟踪和无核心差异做离线断言。
   - 扩展/复用 `test_scope_contract.py` 证明新增 grid 模板不含购物车，并与固定上游只存在批准差异。
   - 执行 Harness 自测、scope/evidence/review 流程。

## 验证顺序

1. `python scripts/harness.py source-check`
2. `python scripts/harness.py preflight NUR-FEAT-002`
3. `python tests/nursery/test_catalog_price_contract.py`
4. `python tests/nursery/test_scope_contract.py`
5. `python scripts/harness_selftest.py`
6. `python scripts/harness.py verify NUR-FEAT-002`
7. `python scripts/harness.py scope-check NUR-FEAT-002`
8. 补充稳定 verify contract 和各测试退出码后运行 `evidence-check`、`review-pack`
9. 独立合并审查通过后转 `approved_for_merge` 并运行 `release-check`

PHP lint、真实 MySQL 迁移、插件安装、匿名 Web/API 和浏览器规格切换不是本机测试；它们必须写入后续 L4 集成任务并在部署前真实执行。

## 数据库与核心适配

- 有现有表数据变更，无 schema 变更、新表或 `config/shopxo.sql` 修改。
- 正向迁移入口为受控 CLI 调用的 `CatalogMigration::Run()`，版本清单为 `catalog-v1.json`，台账位于 `sxo_config`；安装/升级事件只调用只读 Preflight。
- 迁移幂等：相同版本/清单校验结构后 no-op；任何冲突整批回滚；运营字段保持现值。
- 无核心适配；业务差异限于 `app/plugins/nursery/**` 与单文件受控入口 `scripts/nursery_catalog.php`。

## 失败处理与回滚

- 决策重新打开、preflight 失败、台账冲突、目录结构冲突、价格校验绕过、测试修改工作区或出现核心差异时立即停止。
- 迁移异常由事务回滚，不手工删除台账或部分种子。
- 未部署代码回退只还原任务路径。已部署先禁用插件、验证事件移除，再回退代码。
- 数据默认前向修复；不得自动重新上架无效商品。确需删除种子或恢复 before-image 时，进入 L4 任务并使用发布前数据库备份。

# NUR-FEAT-002 测试计划

## 自动测试

### nursery_catalog_price_contract

命令：`["python", "tests/nursery/test_catalog_price_contract.py"]`

断言：

- `catalog-v1.json` 可解析，版本和 seed_key 唯一，8 个一级分类及批准二级分类完整，层级不超过两级，每类规格模板不超过两个；
- 单位默认值为株、盆、丛、平方米；厘米规格值为单值或范围；参数模板包含需求列出的苗木属性；
- config.json 注册保存、状态、商品处理和详情免责声明 Hook；
- BeginInstall/BeginUpgrade 只调用只读 Preflight；受控 CLI 拒绝未知参数，migrate 强制 mode/actor/run-id，integrity 默认 dry-run 且 apply 强制 actor/run-id；
- 保存校验使用完整 ASCII 十进制、0.01/99999999.99 边界、草稿/上架分支、两维规格、受管二级叶子和单位白名单；旧演示叶子与未纳管新叶子负例必须失败；
- 状态 Hook 对上架抛异常而不是返回被忽略的错误；
- 目录迁移包含事务、唯一台账、existing/fresh 显式模式和结构冲突失败，且不修改商品；独立完整性入口默认 dry-run，只有显式 apply 才下架或修正汇总并记录；
- grid/list/slider 读取统一参考价且没有购物车入口，详情免责声明与 BR-PRICE-004 完全一致；
- `git diff` 不包含 ShopXO 核心、默认主题或 `config/shopxo.sql`。

### nursery_scope_regression

命令：`["python", "tests/nursery/test_scope_contract.py"]`

断言 NUR-FEAT-001 的 Web/API/Admin 路由拒绝、PX 插件集合、导航/用户中心收敛、default/回退/自定义主题边界和插件文件跟踪状态保持通过，并加入 grid 模板受控差异断言。

### harness_selftest

命令：`["python", "scripts/harness_selftest.py"]`

确认范围、审批、证据、状态、隔离执行和远程发布门禁未被业务代码削弱。Windows 无符号链接权限导致的既有 skip 必须单独记录，不得改写为 pass。

## 手工验收

以下为真实 PHP/MySQL 集成验收，由后续 L4 任务在部署前必须执行：

1. PHP lint：对全部 nursery PHP 文件执行 `php -l`，任一语法错误失败。
2. 数据库迁移：在与生产一致的 MySQL 8 严格模式副本执行 existing、重复 existing、干净 fresh、同父同名冲突、受管 ID 缺失和并发执行；比较逐表行数与事务残留。
   所有写迁移必须从新代码就位后的 `scripts/nursery_catalog.php migrate ...` 执行；模拟插件包替换失败并证明 BeginUpgrade 预检没有写数据库。
3. 保存矩阵：覆盖 `0`、`0.00`、`0.01`、`99999999.99`、`100000000.00`、负号、正号、空白、指数、千分位、全角数字、NaN、INF、数组和布尔输入。
4. 草稿/上架：草稿零价成功；保存为上架的零价失败且商品、分类、规格、图片和参数无部分写入。
5. 独立上架：零价、缺规格、无效单位、非叶子、停用受管分类、旧演示叶子、未纳管新叶子和汇总漂移分别失败并核对 `is_shelves/upd_time` 回滚；使用受管启用二级叶子的合法商品成功。
6. 存量审计：先运行 dry-run 并确认数据库无写入，再显式 apply；无规格/非法价商品只下架并记录，合法规格的汇总漂移被修正；收藏、询价和统计行不变；第二次执行不重复修复。
7. Web/API：匿名访问分类、搜索 grid/list、首页模块、详情和 API；固定价、区间价、最低价起、单位与免责声明一致；切换规格显示该规格精确价。
8. PX 回归：所有购物车/订单/支付入口及直达路由继续不可用。

## 数据与权限

- 本任务不读取用户私有数据，不新增角色或 API 权限。
- 数据断言必须确认商品下架不删除收藏、询价或统计历史。
- 迁移测试使用隔离数据库和脱敏 fixture；不得访问合同外数据库。
- fresh 清理不属于本任务，不能在上述迁移测试中隐式删除演示或真实数据。

## 未覆盖项

- 当前 Windows 本机没有 PHP、Composer、MySQL 或 Docker，因此本任务只能执行 Python 离线合同测试。
- 未执行的 PHP/MySQL/HTTP/browser 项不得在 `evidence.md` 标为通过，也不得用于关闭后续 L4 发布任务。
- 后续 L4 集成任务负责人为独立 Codex 发布代理；其合同必须锁定服务器、外部 SSH 凭据引用、备份、回滚和现有 Caddy 变更范围。

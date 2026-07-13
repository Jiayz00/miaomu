# NUR-FEAT-003 实施计划

## 实施步骤

1. 新增 `favorite-schema-v1.json`，固定版本、索引名、列序和台账 tag；测试解析和禁止 `config/shopxo.sql` 差异。
2. 实现 `FavoriteMigration`：只读 preflight 检查表、重复和索引；写迁移要求 actor/run-id，以同一数据库连接取得迁移锁并在 `finally` 核验释放，再次检查重复，幂等核验或创建唯一索引，验证实际 schema 后写台账。重复或冲突只返回脱敏计数并非零失败，不删除数据；提供运行时 `AssertReady`，同时核验台账和实际唯一索引，禁止只信任台账。
3. 新增 `scripts/nursery_favorite.php`，只接受 `status/preflight/migrate` 及固定参数；未知参数失败，JSON 输出不含用户私有数据。安装/升级事件最多做只读 preflight，不能把 `install.sql` 当权威迁移。
4. 实现 `FavoriteService`：认证用户校验、商品可收藏校验、显式幂等 Add/Cancel/Status、强制用户条件的分页 List；`Add` 写入前调用 schema `AssertReady`，未迁移或结构漂移时失败关闭，不允许无唯一索引退化运行；列表左连接商品并输出 active/off_shelf/deleted，不查询或写入询价。
5. 新增 index/api Favorite 控制器。构造时保存网关认证用户，所有 action 忽略请求 user/user_id；未登录 Web 引导登录，API 返回稳定认证错误。
6. 扩展 `ScopePolicy` 与 system hook，拒绝旧 Web/API 收藏写 action、语义不合规的旧 API `usergoodsfavor/index` 和 `admin/goods/delete`，过滤物理删除权限/入口；保留商品上下架。Web `usergoodsfavor/index` 只能由 view hook 替换为调用 nursery `list` 的页面壳，不能继续消费旧内连接列表。
7. 新增 nursery 收藏按钮模板和静态脚本。替换列表模板、详情 PC 相册收藏入口和移动端购买左导航收藏入口，使用 nursery 专属 class，避免 ShopXO `common.js` 的 toggle handler 与新 handler 同时执行；按钮根据当前状态调用 add 或 cancel，不调用 toggle；未登录复用登录弹层。新增基础收藏页，只展示当前价格、状态、查看和取消，不出现询价占位入口。
8. 新增 `test_favorite_contract.py`，覆盖 schema、迁移失败关闭、显式语义、认证绑定、IDOR、下架保留、无询价副作用、旧旁路、物理删除和无核心差异；运行目录价格、范围及 Harness 回归。

## 验证顺序

1. `python scripts/harness.py source-check`
2. 计划批准后：`python scripts/harness.py preflight NUR-FEAT-003`
3. `python tests/nursery/test_favorite_contract.py`
4. `python tests/nursery/test_catalog_price_contract.py`
5. `python tests/nursery/test_scope_contract.py`
6. `python scripts/harness_selftest.py`
7. `python scripts/harness.py verify NUR-FEAT-003`
8. `scope-check`、`evidence-check`、`review-pack`，独立合并审查后运行 `release-check`。

## 数据库与核心适配

- schema 变更：为 `sxo_goods_favor(user_id, goods_id)` 增加唯一索引；`sxo_config` 写版本台账。
- 正向迁移：`FavoriteMigration` + `favorite-schema-v1.json` + `scripts/nursery_favorite.php`。不得只依赖 `install.sql`。
- 幂等：实际唯一索引与台账一致时 no-op；索引同名不同结构、重复数据或表结构异常时失败。
- 回滚：普通回滚保留索引和台账；删除索引需要独立 L4 数据任务和备份。
- 核心适配：无。所有预计业务差异都在插件、插件静态资源、单文件 CLI 和测试路径。

## 失败处理与回滚

- 开放决策影响范围变化、preflight 失败、历史重复、索引冲突、IDOR、旧路由可达、核心差异或测试变更工作区时立即停止。
- DDL 后台账失败不尝试反向删除索引；重跑验证 schema 后完成台账。
- 业务写失败必须回滚；重复 add/cancel 返回目标状态，不执行相反操作。
- 未部署只回退授权路径。已部署先停止收藏写流量，再回退代码并保留唯一索引；核对收藏和询价行数。

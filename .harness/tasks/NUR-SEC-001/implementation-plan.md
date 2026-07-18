# NUR-SEC-001 实施计划

## 实施步骤

1. 通过 `source-check`、`task-check`、`plan-check` 和 `preflight` 锁定合同；核对实际模板、Hook 和上游核心行号。
2. 新增 security schema v1 与 `SecurityMigration`：用 GET_LOCK、information_schema、表/列/索引/引擎核验和 `sxo_config` 台账实现幂等前向创建；把它编排进 `FavoriteMigration`，保证现有部署 bootstrap 自动执行。
3. 实现 `FavoriteRateLimit`：按认证用户和 `add`/`cancel` 动作分别维护 60 秒/20 次固定窗口，独立短事务先提交，行锁处理首次并发与窗口重置；在 Add/Cancel 的商品校验后调用。
4. 扩展 `FavoriteService::Listing` 批量加载规格值、参数和产地名称，输出 `primary_spec_text`、`produce_region_name`；修正页码上限并更新收藏模板/CSS。
5. 在 nursery 列表 Hook 打开 `is_spec/is_params`，在 grid/list/slider 模板渲染规格、产地、单位；详情询价入口增加 `is_shelves && !is_delete_time` 条件。
6. 新增 `GoodsAuditService`，在商品保存事务 Hook 前读取旧价格/状态摘要、Hook 后比较并追加审计；修改 `GoodsService::GoodsStatusUpdate` 在 update 前锁定旧记录并把 `previous_goods` 传给 Hook。审计字段仅包含 ID、动作、摘要、原因、请求标识和时间。
7. 编写/更新离线合同测试，覆盖 schema、并发语义静态断言、主要规格/产地、下架 CTA、核心差异、收藏/询价独立性和 PX 回归。
8. 运行 required tests、scope/evidence/review-pack；独立代理审查后再把任务推进到 merge。未具备 PHP/MySQL/浏览器时明确记录 blocked/not_run。

## 验证顺序

1. `python scripts/harness.py source-check`
2. `python scripts/harness.py task-check NUR-SEC-001`
3. `python scripts/harness.py plan-check NUR-SEC-001`
4. `python scripts/harness.py verify NUR-SEC-001`
5. `python scripts/harness.py scope-check NUR-SEC-001`
6. `python scripts/harness.py evidence-check NUR-SEC-001`
7. `python scripts/harness.py review-pack NUR-SEC-001`

## 数据库与核心适配

新增 `sxo_plugins_nursery_favorite_rate_limit` 和 `sxo_plugins_nursery_goods_audit`，由 `security-schema-v1.json`/`SecurityMigration.php` 正向创建；`config/shopxo.sql` 不改。核心登记仅覆盖 `GoodsStatusUpdate` 的 previous-state Hook 参数，原因、风险和回滚已记录在 `.harness/core-changes/REGISTER.md`。

## 失败处理与回滚

发现结构冲突、缺少事务/认证上下文、审计写入失败、用户数据越权、公开价变化、PX 旁路或核心差异时停止。迁移不 DROP；应用回滚保留审计和限流表。回滚后重复运行收藏、目录、询价、范围和安全合同测试，并确认公开价/收藏/询价历史未减少。

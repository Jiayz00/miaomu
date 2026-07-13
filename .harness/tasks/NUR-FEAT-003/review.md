# NUR-FEAT-003 独立审查

## 审查范围

- 审查基线：`origin/main` 为 `f85752c074be83f7389a1bf74d3f0b36db7612ca`，审查快照 HEAD 为 `dbb8dd29a88858e4efc3b672452e05fbd6dc2d4e`，计划批准基线为 `cb681718eb2f8558a80ac110630c43cd49557621`。
- 已核对 `AGENTS.md`、项目宪章、需求原文、业务规则、ShopXO 边界、任务合同、获批计划、测试计划、实施证据、发布说明、最新 verify 原始清单与 `origin/main...HEAD` 全部差异。
- 已运行 `source-check`、`task-check`、`scope-check`、`evidence-check` 与 `review-pack`；这些门禁在审查快照上通过，但不能覆盖下列人工审查发现。
- 已对照固定 ShopXO 6.9.0 上游的 `Usergoodsfavor` Web/API 控制器与 `GoodsFavorService`，确认旧列表仍使用内连接并过滤逻辑删除商品。

## 发现

### P1：旧 Web/API 收藏列表绕过 nursery 左连接保留语义

- `app/plugins/nursery/service/ScopePolicy.php:50-53` 的 API action 拒绝表只包含 `cancel/delete`，没有拒绝获批计划明确列出的旧 API `usergoodsfavor/index`。
- `app/plugins/nursery/service/ScopePolicy.php:187-199` 和 `app/plugins/nursery/Hook.php:172-184` 没有把旧 Web `usergoodsfavor/index` 替换或路由到 `FavoriteService::Listing`；现有导航仍可能进入上游列表。
- 上游该入口调用 `GoodsFavorService::UserGoodsFavorListWhere/GoodsFavorList`，使用内连接并排除 `g.is_delete_time != 0`。用户从旧入口看不到下架后逻辑删除或缺失商品的收藏，违反 `BR-FAV-004`、任务不变量和获批实施计划第 6 步。
- `tests/nursery/test_favorite_contract.py:261-265` 反而把 `index` 断言为安全允许，掩盖了该旁路。
- 最小修复：拒绝旧 API `usergoodsfavor/index`；让旧 Web 收藏入口及用户中心/导航统一进入 nursery 左连接列表；增加负向合同测试，证明旧 API 被拒绝、旧 Web 不再消费上游内连接列表，并保留下架、逻辑删除和缺失商品收藏。

### P1：迁移预检在台账缺失时误报已就绪

- `app/plugins/nursery/service/FavoriteMigration.php:33-47` 调用 `ReadLedger()` 后丢弃结果，`ready` 和 `migration_required` 只由唯一索引决定。
- 在任务明确设计的“DDL 成功、台账写入失败、随后前向修复”场景中，`preflight` 会返回 `ready=true`、`migration_required=false`，但 `AssertReady()` 会因台账缺失拒绝全部 Add。该不一致会让发布判断错误并造成收藏写入不可用。
- `tests/nursery/test_favorite_contract.py:66-72` 固化了错误语义，没有覆盖“索引存在但台账缺失”。
- 最小修复：令预检就绪条件与 `Status/AssertReady` 一致，必须同时存在兼容唯一索引和匹配台账；增加对应负向测试。

修复后必须重新运行四项合同测试、`verify`、`scope-check`、`evidence-check` 和 `review-pack`。当前 verify 的内容指纹覆盖审查快照，但不覆盖待修复差异，不能用于后续批准。

## 审查结论

存在两个 P1 blocker，未创建 `approval-merge.json`，未执行 merge approval，也未推进 `approved_for_merge`。任务已退回 `implementing`，等待修复和全量重验后由同一独立 merge reviewer 复审。

REVIEW_RESULT: CHANGES_REQUIRED

REVIEWER: Codex-Review (/root/fav003_merge_review)

REVIEWED_AT: 2026-07-13T22:49:06Z

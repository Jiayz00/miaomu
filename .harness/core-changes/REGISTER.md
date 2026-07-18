# ShopXO 核心修改登记

只有任务合同明确允许且经独立审批后，才能增加记录。
每个 Task ID 只能有一行；八列必须完整。`Upstream baseline` 使用固定 commit，`Paths` 用逗号或 `<br>` 分隔并逐项覆盖 task.json 声明，`Reviewer` 必须匹配任务合同，批准后 `Status` 写 `approved`。

| Task ID | Upstream baseline | Paths | Why plugin/hook is insufficient | Upgrade risk | Rollback | Reviewer | Status |
|---|---|---|---|---|---|---|---|
| NUR-SEC-001 | d1825c5404054b535255d8fcad675a5dae0ab633 | app/service/GoodsService.php | `plugins_service_goods_field_status_update` runs after the update and cannot recover the old shelf state; a small previous_goods read/argument inside the existing transaction is required for truthful audit. | Low, isolated argument addition to an existing hook; upstream merge may need conflict review. | Remove the previous_goods read and hook field; nursery audit writes fail closed without changing ShopXO status behavior. | Codex-Review | approved |

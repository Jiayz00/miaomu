# ShopXO 核心修改登记

只有任务合同明确允许且经独立审批后，才能增加记录。
每个 Task ID 只能有一行；八列必须完整。`Upstream baseline` 使用固定 commit，`Paths` 用逗号或 `<br>` 分隔并逐项覆盖 task.json 声明，`Reviewer` 必须匹配任务合同，批准后 `Status` 写 `approved`。

| Task ID | Upstream baseline | Paths | Why plugin/hook is insufficient | Upgrade risk | Rollback | Reviewer | Status |
|---|---|---|---|---|---|---|---|

# NUR-SEC-001 独立审查

## 审查范围

独立复核了当前分支 `sec/NUR-SEC-001-hardening` 的任务合同、需求摘录、业务规则、ShopXO 6.9.0 实际调用链、基线 `502e8266b` 到 HEAD `de86f2f04` 的 25 个变更文件，以及最新 verify 运行 `20260718T214545098084Z-verify`。同时核对了 `source-check`、`task-check`、`scope-check`、`evidence-check` 和 `review-pack` 的结果，并按代码路径检查了收藏用户隔离与限流、下架询价入口、商品保存/上下架事务、前向迁移和核心差异登记。

## 发现

- 已关闭 P1（规格审计身份）：早期摘要只比较规格价格集合，规格价格互换可能漏记；当前 `GoodsAuditService.php:129-189` 以 `GoodsSpecType`/`GoodsSpecValue` 组成稳定的类型-值身份，对身份和行分别规范排序，并在类型和值数量不一致时失败关闭。规格列重排不会生成虚假 `price_update`，价格互换仍可被识别。
- 未发现剩余 P0-P2 缺陷。收藏 add/cancel 使用独立的用户-动作固定窗口、数据库时间和行锁；收藏与询价保持独立，列表与写入均绑定认证用户；下架/逻辑删除不暴露新的询价提交入口且服务端仍校验状态；商品价格/上下架审计写入位于 ShopXO 事务钩子内并保持只追加；迁移清单、台账、索引和结构漂移均失败关闭，核心只增加已登记的 `previous_goods` 参数。

## 审查结论

本轮独立审查确认当前实现、验证证据和最新审查包一致，未发现剩余 P0-P2 缺陷，批准进入合并准备状态。

## 残余限制

本机没有 PHP、Composer、MySQL、Docker 或浏览器，因此 PHP lint、真实 schema/迁移矩阵、HTTP 会话、模板渲染、并发压测和回滚演练尚未执行。`evidence.md` 已将这些项目标为未覆盖/后续运行时门禁；六项离线合同测试均以退出码 0 完成，不能替代 L4 部署验证。远端 SSH 认证和服务器发布不属于本任务 merge 审批范围。

REVIEW_RESULT: APPROVED

REVIEWER: Codex-Review

REVIEWED_AT: 2026-07-18T21:57:51Z

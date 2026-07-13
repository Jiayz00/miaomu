# NUR-FEAT-003 独立审查

## 审查范围

- 审查基线：`origin/main` 为 `f85752c074be83f7389a1bf74d3f0b36db7612ca`，最终审查 HEAD 为 `bc7502d0f1f92736229f37d11a736b88c59a01c5`，计划批准基线为 `cb681718eb2f8558a80ac110630c43cd49557621`。
- 已核对 `AGENTS.md`、项目宪章、九项需求原文、业务规则、ShopXO 边界、任务合同、获批计划、测试计划、实施证据、发布说明、固定 ShopXO 6.9.0 上游实现及 `origin/main...HEAD` 全部差异。
- 已运行 `source-check`、`task-check`、`scope-check`、`evidence-check` 和最新 `review-pack`，均通过；范围记录 26 个 tracked 变更，无未跟踪、删除、重命名、核心或 `config/shopxo.sql` 差异。
- verify `20260713T225005175873Z-verify` 为 4/4 通过，前后 workspace fingerprint 均为 `1e1a4af4ad8a931b53783ab587a64dfdc85f0f4e0d8e82e7118f16912d733f83`，控制面完整。该 fingerprint 与干净 HEAD `bc7502d0f` 的最新 review-pack 完全一致。
- 本 reviewer 另行重跑四项声明测试：收藏 33 项、目录价格 30 项、范围 23 项、Harness 60 项通过；Harness 2 项按既有 Windows 平台条件跳过。

## 发现

### 旧收藏列表旁路

- 已修复。API `usergoodsfavor/index` 进入 action 拒绝表；旧 Web `usergoodsfavor/index` 在请求开始阶段固定重定向到 nursery 收藏列表，导航 URL 同步改写。
- nursery 列表继续按认证 `user_id` 左连接商品，保留下架、逻辑删除和缺失商品收藏；旧 Web/API 写入口及 `admin/goods/delete` 仍被拒绝。
- 新增合同测试覆盖旧 API 拒绝、旧 Web 重定向与导航改写，初审 P1 已关闭。

### 迁移预检台账误报

- 已修复。`FavoriteMigration::Preflight()` 的 `ready` 现在同时要求兼容唯一索引和匹配台账；索引存在但台账缺失时返回 `migration_required=true`。
- `AssertReady()` 仍在 Add 前同时核验真实索引和台账；重复扫描、同名冲突、1062 幂等确认、迁移锁和前向修复设计保持不变。
- 合同测试已覆盖新的预检语义，初审 P1 已关闭。

### 最终复审

未发现剩余 P0-P2 缺陷。认证用户绑定、IDOR 防护、POST 加 session nonce、显式幂等 add/cancel、唯一索引迁移、下架/删除/缺失保留、旧入口拒绝、商品物理删除关闭、无询价副作用和无 ShopXO 核心修改均与任务合同一致。

## 残余风险

- 当前 Windows 环境没有 PHP、Composer、MySQL、Docker 或可运行 ShopXO 服务；PHP lint、真实 MySQL 8 DDL/1062/并发、A/B 会话、CSRF、HTTP、PC/H5 浏览器和回滚演练尚未执行，必须由后续 L4 集成/发布任务完成，不能视为本次已通过。
- 后台 `admin/goodsfavor/delete` 作为既有特权管理能力保留；普通用户不可达，后续权限与审计任务仍需决定是否关闭。

## 审查结论

两项初审 P1 已关闭，当前差异、证据和回滚说明满足 NUR-FEAT-003 合并条件。

REVIEW_RESULT: APPROVED

REVIEWER: Codex-Review

REVIEW_AGENT_TASK: /root/fav003_merge_review

REVIEWED_AT: 2026-07-13T22:59:07Z

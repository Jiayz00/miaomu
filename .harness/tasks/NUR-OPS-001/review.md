# NUR-OPS-001 独立合并审查

## 审查范围

本轮独立审查覆盖基线 `42c7e4b1213a208b6bf8b6fc9b8d6db28f2f3283` 至 HEAD `04b4806125da456a63bfcaefa427d492d0c3e0f7` 的部署差异、L4 任务合同、NFR-SEC-006/NFR-PERF-005、远程动作白名单、两服务 Compose、ShopXO schema-only 基线、nursery v1 前向迁移编排、外部 secret、现有 `jia-caddy` 接入、回滚边界、实施证据及最新 review-pack。补查了合同基线修复 `7abddf` 至 `42c7e4b1`，确认其未隐藏未审查的部署行为。

## 发现

未发现 P0-P2 缺陷。

- Docker build context 已明确包含 `config/shopxo.sql` 与 `deploy/shopxo-schema-baseline-manifest.json`，schema extractor 固定 manifest source 和 ShopXO 上游提交 `d1825c5404054b535255d8fcad675a5dae0ab633`。
- MySQL steady marker 由 mysql 用户以 `0444` 创建；schema bootstrap 对固定 83 表、运行配置、地区 seed 和三组 nursery v1 前向迁移执行后置核验，未知或不完整结构继续失败关闭。
- Caddy 候选文件使用临时文件、`fsync` 与排他 hard-link 发布，容器内 broker 例外只接受合同固定的 validation action；现有 `jia-caddy`、共享路由和回滚边界未被扩大。
- 有效验证为 `.harness/runs/NUR-OPS-001/20260718T194150030953Z-verify`，合同 SHA-256 为 `6a55a14ab345dfd044a33961e8aa3c49aff2e5d0f35a7ac0e81dc59f43b9fd68`，4/4 测试退出码均为 0，控制面完整；有效审查包为 `.harness/reports/NUR-OPS-001/20260718T194600015120Z-review-pack`，task/plan/scope/evidence 与安全扫描均通过。
- 旧 verify `20260718T193008350307Z-verify` 曾受并行临时 JSON 写入影响，不作为本次批准证据。

环境阻断项：两次锁定的只读 `inventory_pwd` 均以 SSH `exit_code=255` 且无输出结束。TCP 22 可达，但远端会话尚未建立；未执行远程写操作。该问题阻断 release approval、release seal 后部署和服务器实测，不阻断当前源码合并审查。

## 审查结论

当前 HEAD、任务授权范围、真实本地验证证据和 review-pack 一致；已修复的 Docker context、schema seed/后置检查、marker 权限和 Caddy 发布竞态均有回归覆盖。本轮批准 NUR-OPS-001 合并。批准只覆盖当前提交的合并准备度，不代表服务器部署成功；发布仍须由独立 `Codex-Release` 审查 SSH 连接、主机指纹、Caddy 快照、备份、回滚、干净 release commit/seal 和远端真实结果。

REVIEW_RESULT: APPROVED

REVIEWER: Codex-Review

REVIEWED_AT: 2026-07-19T03:51:52+08:00

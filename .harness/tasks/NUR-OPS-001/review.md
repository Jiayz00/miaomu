# NUR-OPS-001 独立审查

## 审查范围

审查者应核对：`task.json` 的 L4/`network_access_required`/主机指纹/外部凭据引用/受管根/动作白名单；NFR-SEC-006 与 NFR-PERF-005 追踪；`deploy/**` 的两服务 Compose、PHP intl、HMAC secret、FPM socket、Caddy-only 入口；备份与回滚边界；禁止 Nginx、共享栈 down、生产数据和密钥输出；以及 `requirement.md`、影响分析、实施计划、测试计划、证据和发布说明的一致性。

## 发现

本地合同检查已确认：

- 目标主机、端口、用户、指纹、`id_ed25519`/`known_hosts` 引用、部署根和四个受管根已固定；禁止动作集合完整。
- `app`/`db` 是唯一长期服务，现有 Caddy 是唯一 Web 网关，端口 88 仅回环；MySQL 不发布宿主机端口。
- PHP `intl`/Normalizer 与询价 HMAC external secret 已纳入 Compose、FPM、环境检查和离线测试；不读取或提交 secret 值。
- `nursery-bootstrap.php:150-171` 实际依次执行 Catalog/Favorite/Inquiry v1 前向迁移；原 `database_change.required=false` 与该运行合同不一致，已改为 `true`，列出受影响表并锁定编排入口，明确三组已批准业务迁移实现仍由 NUR-FEAT-002/003/004 拥有。
- 文档把本地合同测试与远程真实证据分开，未把未执行的服务器动作表述为通过。

服务器、数据库、Caddy、浏览器、并发和回滚证据尚未产生，不能据此批准发布。

## 审查结论

计划审查结论：数据库执行边界已与实际 bootstrap 调用链统一；三组迁移保持 forward-only、幂等和独立任务所有权，fresh baseline 例外未启用。服务器、数据库、Caddy、浏览器、并发和回滚证据尚未产生，不能据此批准发布；这些仍是后续 L4 release gates。实现代理不得填写批准结论。

REVIEW_RESULT: APPROVED

REVIEWER: Codex-Review

REVIEWED_AT: 2026-07-19T00:45:00+08:00

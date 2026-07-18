# NUR-FEAT-004 实施证据

## 验收标准映射

- `AC-TASK-001`、`AC-TASK-002`、`AC-TASK-003`、`AC-TASK-004`、`AC-TASK-005`、`AC-TASK-006`、`AC-TASK-007`：离线合同测试覆盖入口、快照、状态/回复历史、用户隔离、管理员权限、手机号审计、HMAC 防重、独立频控和迁移结构；证据目录为 `.harness/runs/NUR-FEAT-004/20260718T154714813714Z-verify/`。
- `scope-check` 与 `git diff --check` 证明变更限定在任务授权路径，未修改 ShopXO 核心、`config/shopxo.sql` 或 vendor。

## 自动测试证据

VERIFY_CONTRACT_SHA256: 8fce0522c267dbd63d27cc0453f269072fe665e8b802c99fdce097d74b76f6ce
TEST_COMMAND: nursery_inquiry_contract ["python", "tests/nursery/test_inquiry_contract.py"]
TEST_RESULT: nursery_inquiry_contract exit_code=0
TEST_COMMAND: nursery_favorite_regression ["python", "tests/nursery/test_favorite_contract.py"]
TEST_RESULT: nursery_favorite_regression exit_code=0
TEST_COMMAND: nursery_catalog_price_regression ["python", "tests/nursery/test_catalog_price_contract.py"]
TEST_RESULT: nursery_catalog_price_regression exit_code=0
TEST_COMMAND: nursery_scope_regression ["python", "tests/nursery/test_scope_contract.py"]
TEST_RESULT: nursery_scope_regression exit_code=0
TEST_COMMAND: harness_selftest ["python", "scripts/harness_selftest.py"]
TEST_RESULT: harness_selftest exit_code=0
运行清单：`.harness/runs/NUR-FEAT-004/20260718T154714813714Z-verify/manifest.json`；Harness 报告 passed=5、failed=0、blocked=0，控制面前后哈希一致。

## 手工与页面证据

本机没有 PHP、Composer、MySQL、Docker 或浏览器，未执行真实模板渲染、HTTP 会话、数据库迁移、并发请求或截图；这些验收进入后续 L4 服务器任务，不能以本地合同测试替代。

## 已知限制

- 服务器运行环境和 `nursery_inquiry_hmac_key` 尚未验证；部署时必须从仓库外注入并在同一实例生命周期内保持不变。
- PHP `intl`/`Normalizer`、OpenSSL、Think 模板语法、MySQL schema v1、真实权限缓存和 Caddy 路由仍需服务器验证。
- 未运行真实用户/管理员浏览器流程、手机号 reveal 审计查询和并发防重复压测。

## 回滚证据

未部署，未执行远程回滚演练。按合同回滚仅回退本任务授权路径；若已创建询价表，后续 L4 回滚保留表、快照、回复、历史和审计，不执行 DROP/TRUNCATE/DELETE。

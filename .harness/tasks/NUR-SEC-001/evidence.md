# NUR-SEC-001 实施证据

## 验收标准映射

- `AC-TASK-001`：通过离线目录/收藏合同测试，覆盖规格、产地、公开价和单位字段；真实模板页面尚未在本机运行。
- `AC-TASK-002`：通过收藏与询价合同测试，确认下架/逻辑删除商品不暴露可提交询价入口，且保留历史关系。
- `AC-TASK-003`：通过安全合同测试，确认 add/cancel 独立用户级固定窗口限流、幂等迁移和失败关闭策略。
- `AC-TASK-004`：通过安全合同测试和代码审查，确认价格/规格身份及上下架变更在事务内追加审计，规格列重排会先规范化，不产生虚假价格变更。
- `AC-TASK-005`：目录、收藏、询价、PX 范围和 Harness 自测均通过；PHP/MySQL/浏览器/真实并发仍列为未覆盖。

## 自动测试证据

VERIFY_CONTRACT_SHA256: feed23156e397bbbd9055c07d1d58d4c04912fe3be008a961c8acddf06d86f33
运行目录：`.harness/runs/NUR-SEC-001/20260718T214545098084Z-verify`。

TEST_COMMAND: nursery_security_hardening_contract ["python", "tests/nursery/test_security_hardening_contract.py"]
TEST_RESULT: nursery_security_hardening_contract exit_code=0
TEST_COMMAND: nursery_favorite_regression ["python", "tests/nursery/test_favorite_contract.py"]
TEST_RESULT: nursery_favorite_regression exit_code=0
TEST_COMMAND: nursery_catalog_price_regression ["python", "tests/nursery/test_catalog_price_contract.py"]
TEST_RESULT: nursery_catalog_price_regression exit_code=0
TEST_COMMAND: nursery_inquiry_regression ["python", "tests/nursery/test_inquiry_contract.py"]
TEST_RESULT: nursery_inquiry_regression exit_code=0
TEST_COMMAND: nursery_scope_regression ["python", "tests/nursery/test_scope_contract.py"]
TEST_RESULT: nursery_scope_regression exit_code=0
TEST_COMMAND: harness_selftest ["python", "scripts/harness_selftest.py"]
TEST_RESULT: harness_selftest exit_code=0

verify manifest 显示 6/6 passed、0 failed、0 blocked；收藏回归包含 34 项断言，安全回归包含 12 项断言；Harness 自测为 62 passed、2 skipped（Windows 无创建符号链接权限），证据文件和 control-plane 指纹前后一致。

## 手工与页面证据

本任务在本机未启动 PHP/ShopXO，因此未执行真实页面截图、HTTP 会话、隔离 MySQL 迁移矩阵或管理员并发操作。代码审查核对了 `GoodsService::GoodsStatusUpdate` 的 `previous_goods` 传递、nursery Hook 注册、用户上下文和审计/限流 fail-closed 路径。

## 已知限制

- 本机缺少 PHP、Composer 运行时、MySQL、Docker 和浏览器，不能把 lint、真实数据库事务、模板渲染或并发压测表述为通过。
- 远端 SSH 认证尚未建立（既有 inventory 返回 exit code 255 且无输出）；部署任务必须在 L4 合同内单独验证。
- 当前规格摘要依赖 ShopXO 规格类型和值的合法对应关系；数量不一致时主动失败关闭。

## 回滚证据

未执行部署回滚演练。本任务代码回滚边界为提交 `7b0f9be421affd5d8471b7e2f1ee7f7606206017` 之前的授权路径差异；已创建的限流和审计表/历史不执行 DROP、TRUNCATE 或 DELETE。实际远端回滚由 NUR-OPS-001 的 Caddy/Compose 快照和合同动作负责。

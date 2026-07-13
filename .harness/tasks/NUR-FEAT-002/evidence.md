# NUR-FEAT-002 实施证据

## 验收标准映射

- `AC-TASK-001`：通过离线合同验证。`catalog-v1.json` 的 8 个一级分类、批准的二级叶子、单位、规格/参数模板、稳定 seed、台账哈希、只读预检、串行迁移和同父范围事务锁均由 `nursery_catalog_price_contract` 覆盖；迁移重放还必须匹配原 actor 与 mode，证据见本次 verify 的对应 test-result 与 stdout。
- `AC-TASK-002`：通过离线合同验证。原始分类必须恰好一个正整数；规格请求固定字段顺序并拒绝未知字段；保存前和事务提交前分别校验价格、最多两维、全局/规格单位及受管叶子；独立上架对数据库态规格、单位、分类和聚合再次复核并以异常回滚。
- `AC-TASK-003`：通过离线合同验证。商品处理 Hook 生成公开 `reference_price`，default 主题 grid/list/slider 使用最低参考价与“起”，详情保留 ShopXO 区间/规格价并输出完整免责声明；PX 范围回归证明未恢复购物车、订单或支付入口。
- `AC-TASK-004`：通过离线合同验证。完整性 CLI 默认 dry-run；apply 强制 actor、run-id 和 dry-run `items_sha256`，锁定后哈希漂移失败，超过 500 项失败关闭；同一 run-id 重放必须匹配首次 actor 与 reviewed hash；修复只下架无效商品或重算派生汇总，并记录完整 before/after、`upd_time` 与永久 run-id 历史。
- 正式证据目录：`.harness/runs/NUR-FEAT-002/20260713T191702898265Z-verify`。

## 自动测试证据

VERIFY_CONTRACT_SHA256: ea70c7824ada6ea0b6563509053de09d6035e0eea3a0b27fb8fe7d80c65d5302

TEST_COMMAND: nursery_catalog_price_contract ["python", "tests/nursery/test_catalog_price_contract.py"]
TEST_RESULT: nursery_catalog_price_contract exit_code=0

TEST_COMMAND: nursery_scope_regression ["python", "tests/nursery/test_scope_contract.py"]
TEST_RESULT: nursery_scope_regression exit_code=0

TEST_COMMAND: harness_selftest ["python", "scripts/harness_selftest.py"]
TEST_RESULT: harness_selftest exit_code=0

- verify 汇总：`passed=3 failed=0 blocked=0`；执行前后 workspace fingerprint 均为 `65af6c565ef93f1e1037ca9c66d6e705264f6cca2cdef84ef0a635abeca3cfaf`，控制面哈希均为 `847a5321cdf784328466828c867abf03011522e5c72ac6fe0e24e736c126d1b1`。
- `nursery_catalog_price_contract` 实际执行 30 项断言全部通过，其中包含目录清单的 8 项测试。
- `nursery_scope_regression` 实际执行 23 项断言全部通过。
- `harness_selftest` 实际执行 60 项通过；Windows 无符号链接权限和 POSIX 专用用例共 2 项按平台条件跳过，命令整体退出码为 0，未将跳过表述为对应能力已验证。
- `python scripts/harness.py scope-check NUR-FEAT-002` 通过：基准 `c1f83e08c118`，20 个授权变更项，tracked=20、untracked=0、delete=0、rename/copy=1。

## 手工与页面证据

- 本机未执行 PHP lint、真实 MySQL 目录迁移/并发/回滚、插件安装、匿名 HTTP/API 或浏览器规格切换验收；本机没有 PHP、Composer、MySQL 和 Docker。
- 上述项目不是本任务的通过证据，也未标记为通过。它们必须由后续 L4 集成发布任务在服务器隔离数据库和真实 ShopXO 运行时完成，再允许生产迁移与发布。

## 已知限制

- MySQL `GET_LOCK/RELEASE_LOCK`、同连接事务、同父范围 `FOR UPDATE` 锁、死锁/断线重连和释放失败路径仅完成固定源码审查，尚未经过真实 MySQL 并发与故障注入。
- 完整性 apply 单次最多 500 个修复项；超过上限会失败关闭，当前没有内建 keyset 分批入口。
- 当前任务不包含完整 nursery 视觉主题、询价、收藏唯一性、行为统计、运营看板或生产发布。
- PHP/MySQL/HTTP/browser 缺口由后续 L4 合同承担，不降低本次离线测试结论的边界。

## 回滚证据

- 尚未部署、未执行目录 migrate 或完整性 apply，因此没有生产数据需要回滚，也未声称完成数据库恢复演练。
- 未部署代码回滚范围已由 scope-check 固定为 `app/plugins/nursery/**`、`scripts/nursery_catalog.php` 和 `tests/nursery/**`；回退后重跑 source-check、范围回归和 Harness 自测。
- 已部署后的回滚必须先禁用 nursery 插件并确认生成的 `app/event.php` 不再注册 Hook，再回退代码；目录种子/台账和已下架状态默认保留，数据恢复只允许后续 L4 使用发布前备份或受审 before-image。

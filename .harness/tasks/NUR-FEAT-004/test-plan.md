# NUR-FEAT-004 测试计划

## 自动测试

### nursery_inquiry_contract

命令：`["python", "tests/nursery/test_inquiry_contract.py"]`

离线断言 `inquiry-schema-v1.json` 的五表、复合唯一守卫、索引、无外键和 config 台账；迁移使用同连接 `GET_LOCK`、`information_schema`、DDL 后复核、结构完整后写台账、幂等重放和运行时 `AssertReady`；控制器只使用注入 user/admin，Web/API POST 与 nonce 边界正确；快照来自商品/逐项规格/公开价真源且创建后不可变，`GoodsSpecBase.id` 仅作引用；状态矩阵逐项匹配 `DEC-INQ-STATE`，回复/history/reopen/reveal 只追加；dup-v1 对有序 `[{type,value}]`、规格价/单位与公开价上下文执行 NFKC/canonical JSON/HMAC，禁止无分隔拼接；完整校验后独立频控事务先提交，600 秒防重+询价使用第二事务；项目内 logo 可解码且 config 引用本地路径，BaseService 显式声明六个动作；手机号 reveal 先审计后返回；无通知、导出、统计、事件、核心或 `config/shopxo.sql` 差异。

### nursery_favorite_regression

命令：`["python", "tests/nursery/test_favorite_contract.py"]`

继续验证显式 add/cancel、唯一索引、认证用户隔离、下架保留和旧写旁路拒绝。把 NUR-FEAT-003 的“页面不得含假询价”断言收敛为：只有 active 收藏项出现 `PluginsHomeUrl('nursery','inquiry','form',...)` 真实入口；收藏服务 add/cancel/status 不调用 InquiryService，询价提交也不写 `sxo_goods_favor`。

### nursery_catalog_price_regression

命令：`["python", "tests/nursery/test_catalog_price_contract.py"]`

确认目录、规格、上架价格门禁和公开参考价展示未被询价改变；InquiryService 只读商品/规格价格构造快照，管理员回复控制器/服务不调用商品保存、价格更新或用回复值覆盖主表/快照。

### nursery_scope_regression

命令：`["python", "tests/nursery/test_scope_contract.py"]`

确认 PX 路由、导航、商品按钮、用户中心和后台菜单保持收敛；只放行 nursery Inquiry 的获批页面/API/admin action，其他商城入口仍不可见不可达；业务差异不越过 allowed_paths。

### harness_selftest

命令：`["python", "scripts/harness_selftest.py"]`

确认 L3 schema、身份权限、自动审批角色隔离、计划锁、范围、真实证据、隔离执行和状态门禁未被削弱。

## 手工验收

1. **PHP 与运行扩展。** 对全部新增/修改 PHP 执行真实 `php -l`；确认 PHP 8、PDO MySQL 和 Unicode NFKC 所需 `Normalizer`/intl 可用。缺少扩展时提交必须失败关闭，安装或启用扩展只能由获批 L4 任务处理。
2. **迁移矩阵。** 在 MySQL 8 隔离副本分别验证空库、五表部分存在、DDL 中断、同名异构列/索引、结构完整但台账缺失、台账哈希错误、重复 actor/run-id、两个并发 migrate。结构冲突非零失败且不删数据；合法重跑最终五表完整、无外键、台账匹配且不重复写业务行。
3. **身份与基本提交。** 准备匿名、用户 A、用户 B、普通询价管理员、含 contactreveal 的管理员和含 reopen 的管理员；使用非真实手机号/地址 fixture。匿名提交拒绝；A 未收藏 active 商品可提交，表单展示公开参考价，提交前后收藏行数不变；B 篡改 A 的 user_id/inquiry_id/goods_id 不能区分不存在和他人记录。
4. **快照与历史保留。** A 提交后记录快照；管理员修改商品名称、图片、规格、公开价并下架，再设置逻辑删除/在副本模拟商品缺失。A 与授权管理员仍看到提交时快照、回复和历史；当前商品链接禁用，主表/历史行不删除。
5. **600 秒防重。** 固定数据库时钟或用可控 fixture：相同 user/goods、有序逐项 `[{type,value}]`、规格价/单位、数量/单位、需求和服务端公开价快照串行与并发提交，仅一条成功；`last_accepted_at` 在拒绝后不变；`delta < 600` 拒绝，`delta >= 600` 可新建。模拟商品保存后 `GoodsSpecBase.id` 改变但规格语义与价格上下文相同，仍判等价；分别改变任一 type/value、规格价、单位、说明、服务选项或公开价上下文时不判完全重复。数据库、响应和日志不出现 canonical 明文、完整电话或说明。
6. **60 秒 5 次限流。** 无效输入、无效规格或无效价格在完整校验阶段拒绝且不计数；A 的五次不同有效内容在 60 秒内均进入防重判定，第六次被拒绝且无询价。再用完全相同内容验证：第一次成功、后续重复拒绝仍逐次计数并在第六次由频控拒绝；防重/业务事务回滚后 rate_limit 计数不回退。并发六次也最多五次进入防重；`delta >= 60` 重置。B 独立计数。
7. **状态与回复。** 从 pending 覆盖全部允许/禁止矩阵；pending 只能普通关闭或由回复转 replied。用户首次查看 replied 转 user_viewed，重复/并发查看只有一条状态历史。回复在 pending/replied/user_viewed/communicating 追加，非 replied 转 replied；回复与状态/history 同事务，失败无孤立回复。completed/closed 普通动作不能离开终态，只有 reopen 角色加非空原因可转 communicating。
8. **价格隔离。** 回复填写本次参考单价、总额及各项费用；发布前后比较 `sxo_goods`、`sxo_goods_spec_base` 和 inquiry snapshot 价格字段完全不变。页面明确区分“提交时公开参考价”和“本次回复报价”。
9. **后台权限与隐私。** 验证 config 的项目内 logo 实际可加载，非超级管理员角色页出现 nursery 插件，并可分别配置 BaseService 显式声明的 index/detail/reply/statusupdate/contactreveal/reopen；遗漏任一声明测试失败。未授权直达 URL/API 均拒绝。列表与详情初始 HTML/JSON 只含脱敏手机号。contactreveal 必须 POST/AJAX/nonce，审计插入失败时不返回；成功时审计先存在且仅授权响应含完整 fixture 号码，日志/证据保持脱敏。
10. **筛选与超时。** 创建不同编号、商品、用户、手机、状态、时间和地区记录，逐一验证筛选；无首次回复满 24 小时为超时，已回复或未满 24 小时不超时。分页总数与过滤结果一致，不以当前商品存在为前提。
11. **PC/H5 浏览器。** 检查商品详情收藏与立即询价并列、收藏页 active 项直接询价、未登录引导、表单校验/重复/限流反馈、我的询价空态/分页/详情时间线、后台列表/详情/回复/状态/reveal 弹层。确认窄屏无重叠，完整手机号不预埋 DOM，页面无购物车、订单、支付、通知或导出占位。
12. **回归与日志。** 运行收藏、目录价格、PX 范围回归；检查 PHP-FPM/MySQL/Caddy 应用日志仅有脱敏错误，无持续 5xx、SQL 死锁风暴、密钥或个人数据输出。Caddy 仅复用既有网关，不新增 Nginx 或第二个 Caddy。

## 数据与权限

- fixture 至少包含两个普通用户、三个权限不同的管理员、一个在架多规格商品和一个下架商品；只使用明确标识的虚构手机号、地区、地址和说明，测试结束按 L4 合同清理 fixture，不接触未授权生产个人数据。
- 用户 SQL 从首个查询条件就绑定认证 user_id；错误状态、消息长度和响应字段不能暴露他人询价是否存在。管理员身份和动作权限只从网关注入上下文读取。
- 迁移前后记录实际表结构、索引和各业务表行数；不得在 committed 证据中保存 `SHOW CREATE TABLE` 之外的个人数据查询结果。防重只记录 digest/version/时间，证据不得回显密钥或 canonical payload。
- 回复、状态、reopen 和 contactreveal 的审计断言使用 ID、actor、事件类型、时间和状态，不包含完整手机号、地址、用户说明或回复正文。
- 本任务不采集 PV/UV、事件或统计；验证相关表行数不因询价动作变化，不把提交次数、人数或询价数当作运营指标发布。

## 未覆盖项

- 当前本机没有 PHP、Composer、MySQL、Docker 或可用浏览器运行栈；required_tests 只能提供离线源码合同证据，不能证明 PHP 语法、真实 DDL、事务锁、并发、ShopXO 会话、管理员角色、HTTP 或视觉行为。
- 上述 12 组 L4 项当前统一为 `not_run`，不是通过。后续 L4 集成发布任务必须锁定测试环境、数据库备份、外部 HMAC 密钥引用和真实命令，在部署前执行并保留退出码、脱敏响应、数据库断言和 PC/H5 截图。
- 生产通知、导出、统计、事件和性能容量测试不属于本任务；若后续需要，必须新建需求可追溯任务，不能据此扩大当前实现。

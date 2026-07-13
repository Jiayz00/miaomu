# NUR-FEAT-004 实施计划

## 实施步骤

1. **冻结决策、接口和 schema 清单。** 以已解决的 `DEC-INQ-STATE`、`DEC-DUP-WINDOW` 和 `DEC-PX-BASELINE-NAV` 为唯一产品语义，新增 `inquiry-schema-v1.json`，完整声明五张表、字段、索引、InnoDB/utf8mb4、复合唯一守卫和 `sxo_config` 台账标识。实现前运行 `source-check` 与 `preflight`；若决策上下文、固定上游或计划哈希变化，停止并重新审批。验证清单可被严格 JSON 解析且不包含 SQL、密钥或个人数据。

2. **实现可恢复的 schema v1 前向迁移。** 新增 `InquiryMigration` 和 `scripts/nursery_inquiry.php` 的 `status/preflight/migrate` 动作。迁移使用同一连接取得固定名 `GET_LOCK`，通过 `information_schema` 核对表、列、类型、空值、默认值、索引顺序、唯一性、引擎和字符集；同名异构结构立即失败。缺表按固定顺序创建，每次 DDL 后重新核验；MySQL DDL 中断时重跑只能继续缺失步骤，五表全部匹配后才以唯一 `only_tag=plugins_nursery_inquiry_schema_v1` 写入清单哈希、actor/run-id 和时间。`AssertReady` 同时检查真实结构和台账，缺一即拒绝业务写。`Event::PreflightAll` 增加只读询价预检，但安装/升级事件不隐式执行迁移。普通回滚不删表、不删台账。

3. **建立可分配的插件权限和状态机。** 新增 `public/static/plugins/nursery/images/logo.png` 可解码项目内位图，并把 `config.json base.logo` 设置为对应本地静态 URL；禁止外链或空值。新增 `BaseService::AdminPowerMenu()`，控制器固定为 `inquiry`，显式逐项声明 `index`、`detail`、`reply`、`statusupdate`、`contactreveal`、`reopen`，不能遗漏后依赖插件总权限放行。新增 `InquiryStateMachine`，把代码值、中文文案和合法矩阵集中：创建仅为 `pending`；回复可发生于 `pending/replied/user_viewed/communicating`，非 `replied` 时转 `replied`，已是 `replied` 只追加回复；所属用户首次查看执行条件式 `replied -> user_viewed`；普通状态管理仅允许 `pending -> closed`、`replied -> communicating|completed|closed`、`user_viewed -> communicating|completed|closed`、`communicating -> completed|closed`；新增回复可触发 `communicating|user_viewed -> replied`；`completed|closed` 只有独立 `reopen` 权限和非空原因才能转 `communicating`。所有真实变化必须有一条只追加 history，重复查看或同状态请求不伪造历史。

4. **实现身份、完整输入和快照边界。** 新增 `InquiryService`，所有用户方法先从插件构造器注入的 ShopXO `user` 校验有效 user_id，永不读取请求中的 `user_id/user`。提交仅接受 POST；Web 还要求站内 AJAX 和会话绑定 256-bit 随机 nonce，API 依赖 ShopXO 认证/token 上下文。严格校验正整数商品/规格 ID、十进制采购数量和单位、联系人/电话/地区/地址/日期、三个布尔值、说明长度与 UTF-8；不接受上传或 HTML。省/市/县必须逐级查询 `sxo_region`，验证 `is_enable=1`、level 和 pid 父子链；canonical 使用数字 ID 元组，名称与可能为空的 code 只保存为快照。查询在架且未逻辑删除商品，调用 `ReferencePriceService::AssertPublishedGoods()`，校验所选 `GoodsSpecBase` 当时属于商品；再按 `GoodsSpecType` 的确定顺序逐项验证对应 `GoodsSpecValue`，构造有序 `[{type,value}]`、规格价与单位。`GoodsSpecBase.id` 仅保存在快照作当时引用，因为商品保存会删后重建；禁止直接复用无类型、无分隔规格拼接。客户端价格、商品名、图片、规格文本和状态全部忽略。

5. **完整校验后以独立短事务实现 60 秒 5 次频率限制。** 只有步骤 4 的全部输入、商品、逐项规格和服务端公开价快照校验通过后才计数；无效输入不消耗额度。使用 `sxo_plugins_nursery_inquiry_rate_limit` 每用户一行和独立短事务行锁，并从该事务连接执行 `SELECT UNIX_TIMESTAMP()` 取得唯一窗口时间真源：无记录时插入 `window_started_at=database_now,count=1`；`now-window_started_at >= 60` 时重置为 1；时钟倒退或未过期且 count 已到 5 时拒绝且不改起点；否则原子加一。频控通过必须先提交该短事务，再开始步骤 7 的防重+询价事务；因此完全重复被拒绝或后续业务事务回滚仍保留尝试计数。并发首次插入唯一冲突要在短事务内重新读取加锁并计数，不能退化为无锁先查后写。限流表不存 IP、手机号或内容。

6. **实现 dup-v1 规范化与 HMAC。** 只接受仓库外实例配置提供的高熵密钥；空值、占位值或格式异常失败关闭，密钥不得写 `sxo_config`、日志、响应或测试证据。规范化严格按 `DEC-DUP-WINDOW`：字符串 Unicode NFKC（缺少可验证的 `Normalizer`/intl 能力时失败关闭）、CRLF/LF 统一、首尾清理；手机号、地区、日期、十进制数量、单位、枚举、布尔按已验证格式；空值与缺失同一表示；自由文本不删标点、不改大小写。字段名排序并保留类型生成 UTF-8 canonical JSON，覆盖 user_id、goods_id、步骤 4 的有序 `[{type,value}]`、规格公开价/单位、数量/单位、全部联系与服务需求以及服务端公开参考价格快照；不把易变 `GoodsSpecBase.id` 当语义键。计算 `HMAC-SHA-256` 原始摘要，数据库只保存 version 和 digest。

7. **原子创建询价、防重守卫和初始历史。** 频控通过且输入/快照校验完成后开启业务事务，从同一连接执行 `SELECT UNIX_TIMESTAMP()` 取得受理时间，并读取复合键 `(user_id,goods_id,fingerprint_version,fingerprint_digest)` 守卫后 `FOR UPDATE`。若时钟倒退或 `now-last_accepted_at < 600`，回滚并返回不包含原文的重复提示，绝不更新时间；若已过期，先创建询价和 `pending` 初始历史，再更新守卫的时间/inquiry_id；若不存在，创建询价与历史后插入守卫。并发首次插入发生唯一冲突时整笔事务回滚，不能留下第二条询价或孤立历史。主表保存不可变商品/规格/公开价/状态/联系人/需求快照和便于筛选的规范字段；不调用 FavoriteService，不写 `sxo_goods_favor`、商品、规格、事件或统计表。

8. **实现用户 Web/API 闭环。** 新增 `index/Inquiry.php` 的 `Form/Create/Index/Detail` 和 `api/Inquiry.php` 的 `Create/List/Detail`，具体方法名由离线合同固定。表单只接收商品和可选规格标识，服务端重新加载展示数据；列表和详情 SQL 从开始就带认证 user_id，统一处理不存在与非本人记录。用户查看本人 `replied` 详情时用 `WHERE id=? AND user_id=? AND status='replied'` 条件更新，在同事务追加 `user_viewed` history；并发/重复查看幂等。页面始终以快照展示历史；当前商品仍可用时才提供再次查看链接。

9. **实现管理员筛选、回复、状态、reveal 和重开。** 新增 `admin/Inquiry.php` 与后台列表/详情视图。构造器只接受插件网关注入的 `admin/admin_plugins`；每个服务入口除校验注入上下文外，还必须调用 `AdminIsPower('inquiry', <action>, 'nursery')` 二次验证对应 `control-action`。列表支持询价编号、商品、用户、规范手机号、状态、提交区间、地区和是否超时；P0 超时定义为尚无首次回复且数据库时间距提交满 24 小时。列表和默认详情只返回脱敏手机号。`Reply` 在一笔事务内锁定非终态询价、追加完整回复、按状态机条件更新并追加关联 reply_id 的 history；`StatusUpdate`、`Reopen` 同样锁定当前状态并只追加历史。`ContactReveal` 只接受 POST/AJAX/nonce，先成功写入不含手机号原文的审计历史，再返回完整手机号；审计失败时失败关闭。所有管理员写操作不得使用请求 admin_id，不记录完整手机号、地址或说明到日志。

10. **接入入口与界面。** 扩展 `Hook.php/config.json`：在 `plugins_service_goods_buy_nav_button_handle` 过滤商城按钮后追加 nursery “立即询价”，与收藏并列且不引入购买语义；在 `plugins_service_users_center_left_menu_handle` 注入“我的询价”；在 `plugins_service_admin_menu_data` 先保持 ScopePolicy 过滤再注入授权询价菜单。`FavoriteService::Listing()` 只为 active 收藏项生成真实表单 URL，收藏模板显示“直接询价”，下架/删除项不提供新询价。新增 PC/H5 询价 CSS/JS、空态、分页、表单错误、回复时间线和状态文案；页面不出现订单、支付、购物车、供应商或通知/导出占位入口。

11. **扩展离线合同并执行回归。** 新增 `test_inquiry_contract.py`，用源码/清单 fixture 断言迁移、表结构、身份、权限、状态矩阵、只追加语义、快照、防重、频控、reveal 审计、入口和无核心差异。更新 `test_favorite_contract.py` 与 `test_scope_contract.py`：原“禁止假询价”改为只允许已实现的 nursery Inquiry 控制器 URL，继续证明收藏不自动创建询价、取消收藏不影响询价。目录价格合同增加回复不写公开价路径检查。任何测试失败先修业务实现，再重新执行完整五项 required_tests。

## 验证顺序

1. `python scripts/harness.py source-check`
2. 计划批准后：`python scripts/harness.py preflight NUR-FEAT-004`
3. `python tests/nursery/test_inquiry_contract.py`
4. `python tests/nursery/test_favorite_contract.py`
5. `python tests/nursery/test_catalog_price_contract.py`
6. `python tests/nursery/test_scope_contract.py`
7. `python scripts/harness_selftest.py`
8. `python scripts/harness.py verify NUR-FEAT-004`
9. 填写稳定 `VERIFY_CONTRACT_SHA256` 和每项真实退出码后运行 `scope-check`、`evidence-check`、`review-pack`。
10. 独立 merge reviewer 核对源码、迁移、权限、证据和未执行项，批准后才进入 `approved_for_merge` 和 `release-check`。

PHP lint、真实 MySQL 迁移/并发、HTTP/API、会话 nonce、角色权限和 PC/H5 浏览器测试不在本机伪执行；这些在后续 L4 集成发布任务中按 `test-plan.md` 逐项记录真实命令、退出码和脱敏证据。

## 数据库与核心适配

- 新增五张表：`sxo_plugins_nursery_inquiry`、`sxo_plugins_nursery_inquiry_reply`、`sxo_plugins_nursery_inquiry_history`、`sxo_plugins_nursery_inquiry_duplicate_guard`、`sxo_plugins_nursery_inquiry_rate_limit`；新增 `sxo_config` schema v1 台账行。
- 正向迁移由 `InquiryMigration`、`inquiry-schema-v1.json` 和 `scripts/nursery_inquiry.php` 共同拥有。`config/shopxo.sql` 不修改，插件 install/upgrade 不暗中执行 DDL。
- 幂等以实际 schema 与清单为准，不只相信台账；台账缺失但结构完整时可在相同 actor/run-id 流程核验后前向补写，结构冲突不得自动改列、删索引或清数据。
- 新表不设外键，避免商品、用户或管理员变化破坏历史。索引和字段只服务 P0 列表、所有权、状态、审计、防重和限流，不为统计/导出预建未批准结构。
- 核心适配：无。实现只在 `app/plugins/nursery/**`、插件静态资源、单一 CLI 和 nursery 测试路径；发现必须改核心时停止任务。

## 失败处理与回滚

- 决策变更、preflight 失败、schema 同名异构、缺少 HMAC 密钥/intl NFKC 能力、身份或动作权限不明确、非法状态、IDOR、完整手机号泄露、公开价被写、收藏副作用、PX 回归或核心差异时立即停止。
- DDL 失败不反向删除已建表；保留数据库错误与脱敏结构摘要，重跑相同 schema v1 前向修复。台账只能在五表实际完整后写入。
- 业务事务失败必须回滚询价、守卫、回复和 history 的本次差异；频率限制尝试计数按已提交短事务保留。死锁或唯一冲突返回统一可重试/重复结果，不能产生半条业务记录。
- 未部署时只回退授权路径的本任务差异。已部署时先关闭新提交、保留本人/后台只读历史，再回退代码；五表和台账全部保留，不执行 DROP、TRUNCATE、DELETE 或恢复商品物理删除。
- 回滚后执行五项自动测试，并在隔离数据库对比询价、回复、history、reveal 审计、收藏和商品公开价行数/值；任何历史减少都视为回滚失败。

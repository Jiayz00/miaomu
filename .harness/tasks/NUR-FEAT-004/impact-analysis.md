# NUR-FEAT-004 影响分析

## 需求与当前事实

- 固定上游为 ShopXO 6.9.0 `d1825c5404054b535255d8fcad675a5dae0ab633`，当前仓库 `source-check` 通过。
- `app/index/controller/Plugins.php`、`app/api/controller/Plugins.php` 和 `app/admin/controller/Plugins.php` 均通过 `PluginsService::PluginsControlCall()` 调用 `app/plugins/<name>/<group>/<Control>.php`。index/api 上下文带认证 `user`，admin 上下文带 `admin` 和 `admin_plugins`，请求中的同名字段不能作为身份真源。
- `PluginsService::PluginsAdminPowerMenu()` 会调用插件 `service/BaseService.php::AdminPowerMenu()`；admin 插件网关使用 `control-action` 与角色缓存执行权限检查，适合声明询价列表、详情、回复、状态、手机号 reveal 和重开六类权限。
- `AdminRoleService` 只有在插件 `plugins`、`name`、`logo` 均非空时才把插件加入非超级管理员角色配置；当前 nursery `config.json` 的 `base.logo` 为空。必须新增项目内 `public/static/plugins/nursery/images/logo.svg` 并设置本地 URL，否则六项细粒度权限无法由非超管角色配置。
- nursery 已注册 `plugins_service_goods_buy_nav_button_handle`、`plugins_service_users_center_left_menu_handle` 和 `plugins_service_admin_menu_data`。现有 Hook 只过滤商城按钮和导航，尚未增加询价入口。
- NUR-FEAT-002 的 `ReferencePriceService` 以 `sxo_goods_spec_base.price` 为价格真源并校验商品汇总；询价应读取该真源构造快照，不新建或反向写价格模型。
- NUR-FEAT-003 的 `FavoriteService` 已按认证用户左连接读取收藏并保留下架/删除记录；当前收藏页故意没有假询价入口，`test_favorite_contract.py` 和 `test_scope_contract.py` 也会拒绝任何占位询价。本任务需把这些断言更新为只允许真实 nursery Inquiry URL，且继续验证无收藏副作用。
- `config/shopxo.sql` 和 `app/plugins/nursery/` 当前没有询价表或询价服务。ShopXO 普通插件安装路径不可靠执行增量 SQL，现有 nursery 迁移模式是显式 CLI、`GET_LOCK`、实际 schema 核验和 `sxo_config` 台账。
- `sxo_goods`、`sxo_goods_spec_base`、`sxo_goods_spec_type`、`sxo_user`、`sxo_region` 和 `sxo_admin` 提供当前实体，但历史询价不能依赖它们永久存在；新表不得建立级联外键。`sxo_region.code` 大量为空，地区 canonical 身份必须使用经启用状态和父子链验证的省/市/县数字 ID 元组，名称与非空 code 只进入快照。
- 当前本机没有 PHP、Composer、MySQL 或 Docker 可执行栈；可运行的自动证据是 Python 离线源码合同，不能把它表述为真实数据库、会话或浏览器通过。

## 当前调用链与数据

```text
商品详情/自己的可用收藏项
  -> nursery Inquiry 表单（公开价仍先展示，收藏不是前置）
  -> index/api 插件网关（认证 user 注入）
  -> nursery index/api Inquiry（忽略请求 user_id）
  -> InquiryService::Submit
       -> InquiryMigration::AssertReady
       -> 校验商品、所属规格和 ReferencePriceService 价格真源
       -> 读取仓库外实例 HMAC 密钥并规范化完整业务内容
       -> 事务锁定 rate_limit 与 duplicate_guard
       -> 写 inquiry 不可变快照 + pending 初始 history

用户中心 -> Inquiry::Index/Detail
  -> 所有查询强制 where user_id = authenticated user
  -> replied 首次详情查看在事务内转 user_viewed 并追加 history
  -> 商品不可用时继续展示快照，当前商品链接禁用

后台菜单 -> admin Inquiry
  -> 插件网关 + BaseService control-action 权限
  -> 列表/详情默认手机号脱敏
  -> Reply/StatusUpdate/Reopen 事务追加 reply/history 并更新 current_status
  -> ContactReveal 先追加无敏感值审计，再返回完整手机号
```

## 数据模型与写入不变量

| 表 | 用途 | 关键约束与索引 |
| --- | --- | --- |
| `sxo_plugins_nursery_inquiry` | 当前状态、不可变商品/规格/公开价/联系人/需求快照 | 唯一询价编号；`user_id,add_time`、`goods_id,add_time`、`status,add_time`、地区/超时筛选索引；创建后只允许更新当前状态与状态时间，不更新快照 |
| `sxo_plugins_nursery_inquiry_reply` | 管理员回复和费用拆分 | `inquiry_id,add_time`；每次回复独立行，包含 admin_id，不 UPDATE/DELETE；回复价不写商品表 |
| `sxo_plugins_nursery_inquiry_history` | 初始状态、状态流转、reply、contact_reveal、reopen 审计 | `inquiry_id,add_time` 与事件类型索引；记录 actor_type/actor_id、前后状态、非敏感原因摘要，只追加 |
| `sxo_plugins_nursery_inquiry_duplicate_guard` | 600 秒内容防重并发守卫 | `(user_id,goods_id,fingerprint_version,fingerprint_digest)` 复合唯一；保存最近成功时间与 inquiry_id，窗口内拒绝时不得更新时间 |
| `sxo_plugins_nursery_inquiry_rate_limit` | 每用户 60 秒最多 5 次提交尝试 | `user_id` 唯一；窗口起点与计数在行锁内创建、递增或过期重置 |
| `sxo_config` | schema v1 非敏感台账 | 唯一 `only_tag=plugins_nursery_inquiry_schema_v1`，保存清单哈希、结构版本和迁移运行元数据，不保存 HMAC 密钥或个人数据 |

五张新表统一使用 InnoDB/utf8mb4，并显式定义字段长度、数值精度和索引。用户、商品、规格和管理员 ID 只作历史引用，不建立外键或级联删除。手机、地址和用户说明属于个人数据，只在业务表中按需求保存；迁移台账、审计消息、HTTP 错误、测试 fixture 和 Harness 证据不得复制这些原文。

## 影响范围

### 用户端、管理端与接口

- 用户端：新增询价表单、我的询价列表和详情；详情与收藏增加真实“立即询价”；商品不可用后仍显示快照和回复，但“再次查看商品”禁用。
- Web/API：提交仅接受 POST。Web 写操作使用会话绑定随机 nonce；API 使用 ShopXO 已认证上下文并只接受 POST。列表和详情不能接受 `user_id` 覆盖，错误响应统一，不泄露他人记录是否存在。
- 管理端：新增询价菜单、列表、详情和六项细粒度权限。列表按需求字段筛选，`是否超时`定义为尚无首次回复且提交已满 24 小时；手机号列表与默认详情均脱敏。
- 管理写操作：reply、statusupdate、contactreveal、reopen 都只接受站内 POST/AJAX 与会话 nonce，服务层再次验证注入的管理员和对应动作权限。reveal 审计写失败时不得返回完整手机号。
- 状态：主表保留便于查询的当前状态，历史表是不可丢失的流转轨迹。用户只能触发 `replied -> user_viewed`；管理员按 `DEC-INQ-STATE` 操作，终态重开需要单独权限和非空原因。
- 价格：表单和快照读取公开参考价；管理员回复的本次参考单价、总额和费用是独立业务数据。任何询价写路径不得调用商品保存、价格保存或 `ReferencePriceService::ValidateSave()`。

## 并发、防刷与安全影响

- 内容指纹覆盖认证 user_id、goods_id、服务端逐项验证并按规格类型顺序编码的 `[{type,value}]`、对应规格公开价与单位、采购数量/单位、联系人、规范化手机号、经验证的省/市/县 ID 元组、地址、采购时间、三个服务布尔值、用户说明和提交时解析的公开参考价格快照。`GoodsSpecBase.id` 会在商品保存时重建，只作当时快照引用，不能作为等价语义键；禁止复用把 `GoodsSpecValue` 无分隔拼接成字符串的结果而不逐项复核类型和值。
- 指纹使用 `hash_hmac('sha256', canonical_payload, instance_secret, true)`；实例密钥必须由仓库外运行配置提供，无密钥或格式无效时失败关闭。数据库只保存指纹，不保存密钥或可逆原文副本。
- 先完整校验输入、商品、逐项规格语义和公开价快照；校验成功后用独立短事务锁定并提交 60 秒频控计数。频控通过后才开启防重+询价业务事务。完全重复在 600 秒内拒绝且不刷新守卫时间；守卫与询价/初始历史共同提交或共同回滚，但重复拒绝或业务回滚不得撤销已提交频控计数。
- 60 秒、600 秒、询价受理时间和状态时间统一从当前事务连接执行 `SELECT UNIX_TIMESTAMP()` 获取；不得用 PHP 进程时钟作为窗口真源。时钟倒退按仍在窗口内失败关闭。
- 限流按每个认证用户从首个完整有效尝试开始的固定 60 秒窗口计数，前五次可进入防重判定，第六次拒绝。输入/规格/价格校验失败不计数；内容重复计数。并发唯一冲突必须在短事务内重试加锁，不能用无锁 `SELECT` 后 `INSERT` 绕过。
- 管理员查看完整手机号是单独受限动作，不能在 HTML 初始数据、列表导出、日志或错误中预加载完整值；审计只记录管理员、询价、时间和动作。

## 方案比较

1. 配置：ShopXO 没有可配置的询价快照、回复、状态、防重或手机号 reveal 模型，仅靠配置无法完成。
2. 现有服务：商品、规格、用户、管理员权限和公开价服务可复用，但上游没有满足本需求的询价持久化与状态机；复用它们作为读源，不把业务塞进订单/表单收集服务。
3. 已验证 Hook：三个现有 Hook 足以增加详情、用户中心和后台入口，但 Hook 不适合承载事务、历史和权限本体。
4. `nursery` 插件：插件控制器网关、BaseService 权限、已有 ScopePolicy/ReferencePrice/Favorite 服务和自有资源提供完整隔离边界，是选定方案。
5. 独立模块：会重复插件路由、认证、权限和部署机制，收益不足。
6. 核心适配：没有证据表明必须修改核心；默认禁止并在范围测试中检查无 `app/service/**`、核心 controller、默认主题或 `config/shopxo.sql` 差异。

## 风险与边界

- IDOR：所有用户查询必须同时匹配认证 `user_id`，不能先按 inquiry_id 读取后在 PHP 判断，也不能通过不同 404 文案泄露存在性。
- 数据失真：快照与需求字段创建后不可更新；列表/详情不能以内连接当前商品替代快照。回复和状态历史禁止普通删除。
- DDL 中断：MySQL DDL 可能自动提交。迁移每一步前后检查 `information_schema`，同名异构结构失败关闭；中断后只允许同清单前向恢复，结构完整后才写台账。
- 并发：频控使用先提交的独立短事务；防重守卫、询价和初始历史使用第二事务。每个事务内部锁序固定，死锁/超时只回滚本事务；业务事务失败不得反向撤销已提交频控计数，也不能留下重复询价或孤立历史。
- 权限：BaseService 权限声明和网关校验不足以替代服务层身份检查；管理员 ID 和权限不得从请求参数读取。
- 隐私：手机号、地址、说明和回复内容不得进入 committed fixture、测试输出或 Harness 证据；错误和审计使用 ID 与动作摘要。
- PX：只新增 nursery 询价入口，不恢复购物车、订单、支付、供应商或第三方插件入口。
- 统计：本任务不写行为事件或聚合表，不定义 PV/UV、转化率或回复时长指标；统计任务以后只能消费已审查的数据合同。

## 预计文件

- 修改：`app/plugins/nursery/config.json`（含非空项目内 `base.logo`）、`Hook.php`、`Event.php`、`service/ScopePolicy.php`、`service/FavoriteService.php`、收藏/商品/用户中心相关 nursery 视图及现有 nursery CSS/JS。
- 新增：`service/BaseService.php`、`InquiryMigration.php`、`InquiryService.php`、`InquiryStateMachine.php`；`index/Inquiry.php`、`api/Inquiry.php`、`admin/Inquiry.php`；用户端和后台询价视图；询价 CSS/JS；`public/static/plugins/nursery/images/logo.svg` 项目内可加载矢量标识。
- 迁移：`app/plugins/nursery/inquiry-schema-v1.json`、`scripts/nursery_inquiry.php`。
- 测试：`tests/nursery/test_inquiry_contract.py`，并更新 favorite/catalog/scope 合同以识别真实询价能力且保留原不变量。
- 核心登记：无。若实现发现必须修改授权路径外文件，立即停止并新建核心适配任务，不能扩大本合同。

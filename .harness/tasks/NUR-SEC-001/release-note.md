# NUR-SEC-001 发布与回滚说明

## 变更摘要

苗木首页、搜索列表、网格/图文卡片和收藏列表补充主要规格、计价单位与产地。下架或逻辑删除商品不再显示可提交的询价入口，但既有收藏和询价历史继续保留。收藏 add/cancel 增加按认证用户和动作分离的 60 秒固定窗口限流。管理员真实修改公开价格、规格价格或上下架状态时，会在同一事务中追加非个人数据审计；相同值和规格列重排不会生成虚假价格变更。

## 发布前提

必须使用已通过 NUR-SEC-001 独立 merge 审查的提交，并由 NUR-OPS-001 L4 部署合同锁定 release SHA。部署前确认现有数据库备份策略、ShopXO 版本、nursery 插件启用状态和外部询价 HMAC 文件均符合部署合同。先在隔离数据库执行 FavoriteMigration 编排的 security schema v1，核对 `sxo_plugins_nursery_favorite_rate_limit`、`sxo_plugins_nursery_goods_audit` 和 `plugins_nursery_security_schema_v1` 台账，再允许收藏写入和商品编辑。

## 发布步骤

本 L3 任务不直接执行远程发布。代码合并后由 NUR-OPS-001 经项目 broker 上传固定 release、启动隔离数据库、执行 ShopXO 基线和 nursery 前向迁移、启动应用并复用现有 `jia-caddy`；不得使用原始 SSH/SCP/curl，不创建 Nginx。迁移必须使用固定 actor/run-id，重复执行应返回幂等结果，结构冲突时立即停止后续动作。

## 回滚触发与步骤

若安全表结构、台账、收藏限流、商品审计、下架询价入口或既有收藏/询价回归失败，停止发布并由 NUR-OPS-001 执行应用与 Caddy 回滚。应用代码可回退到前一固定 release，但已创建的限流表、审计表、计数和审计历史必须保留，不执行 DROP、TRUNCATE 或 DELETE。核心 `previous_goods` 参数回退后审计写入停止，既有商城状态更新语义保持不变。

## 发布后验证

检查首页、搜索、网格/列表、详情和收藏页的规格、产地、公开价与单位；验证在架商品收藏和询价并列、下架商品无新询价入口。用两个测试用户验证收藏隔离、add/cancel 独立限流和询价独立性；用测试管理员验证规格价格、重复保存、上下架和事务失败时的审计行数。最后核对安全 schema/台账、PHP/FPM 日志、HTTP 错误、现有 Caddy 路由和 Beszel 健康。未执行的浏览器、MySQL 并发或回滚演练必须继续标记为未覆盖。

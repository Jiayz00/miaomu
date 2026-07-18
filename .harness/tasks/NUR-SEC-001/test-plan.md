# NUR-SEC-001 测试计划

## 自动测试

- `nursery_security_hardening_contract`：schema/迁移、收藏限流、商品审计、规格/产地字段、下架入口和核心登记。
- `nursery_favorite_regression`：唯一性、用户隔离、下架保留、收藏无询价副作用。
- `nursery_catalog_price_regression`：公开价真源、规格和列表价格展示。
- `nursery_inquiry_regression`：询价快照、状态、独立性和 PX 回归。
- `nursery_scope_regression`：路由、导航、权限和核心边界。
- `harness_selftest`：项目 Harness 自检。

所有命令均通过 task.json 的 argv 由 Harness 无 shell 执行；每项必须记录退出码和稳定合同 SHA。

## 手工验收

1. 用含两维规格、产地和参考价的合成商品检查 1440x900、1024x768、390x844、360x800：首页/搜索/网格/列表/收藏无规格或产地缺失、长标题不重叠。
2. 下架商品详情不显示立即询价；在架商品收藏与询价并列；旁路 POST 仍由服务端拒绝。
3. 两个用户分别对 add/cancel 并发请求，确认动作分离、窗口 60 秒/20 次、无越权和无重复行。
4. 管理员修改规格价格、重复保存相同值、上下架/恢复，检查审计行的 old/new 摘要和 append-only；模拟事务失败无孤立行。
5. 隔离 MySQL 执行空库、部分表、重复迁移和结构冲突矩阵；PHP lint 和浏览器控制台真实结果若环境缺失记 blocked。

## 数据与权限

只使用虚构商品/用户/管理员。限流表不存 IP、手机号或正文；审计不存完整价格以外的个人内容，不把密钥或请求正文写入日志。普通用户无法读取或删除审计；下架不删除收藏/询价历史。

## 未覆盖项

当前本机没有 PHP、MySQL、Docker 和浏览器运行栈，真实数据库并发、模板渲染、HTTP 会话和视觉截图需在 L4 发布任务补测；这些不写成通过。远端 SSH 认证当前阻断，部署验证保持 blocked。

# NUR-OPS-003 需求摘录

## 关联需求

- NFR-SEC-006
- NFR-PERF-005

## 任务路由

- PRIORITY: P0
- PHASE: 1

需求规格第 15.1 节要求先部署并确认 ShopXO 版本；NFR-PERF-005 要求在部署环境确定后固定首版性能基准。可复现测试栈是后续 P0 功能真实验证的前提，因此路由为 P0、阶段 1。

NFR-SEC-006 明确要求数据库密码、短信密钥、邮件密码和生产配置不得进入 Git。本任务定义数据库口令的 secret 注入、敏感值拒绝、仓库外 database.php、回环 FastCGI 和共享 Caddy 最小接入边界，按 Harness 路由为 L3，计划与合并均需独立 reviewer 审批；实际服务器和 Caddy 变更继续由 L4 NUR-OPS-001 管理。

## 最新架构约束

项目负责人已明确：

- 服务器现有 Caddy v2.11.2 使用 host network，必须复用。
- 不创建或运行 Nginx、Apache 或其他新的公开 Web 服务。
- 公开端口 88 当前空闲，只作为受控临时验收入口；真实用户登录、会话和询价个人数据必须使用后续 L4 批准的 TLS 域名。最终部署根固定为 /root/jia/miaomu。
- 开发审批可由不同 Codex 代理独立完成，但实现代理不得批准自己的输出。

因此本任务的离线拓扑固定为：

    client -> existing Caddy :88 -> host loopback FastCGI -> app PHP-FPM -> internal db MySQL

Compose 只管理 app 与 db 两个长期服务。Caddy 不加入 Compose 网络；app 的 FPM 只绑定宿主机回环地址，MySQL 不发布宿主机端口。Caddy 必须在与 FPM 一致的 /var/www/html/public 路径看到只读静态根，并以只读方式看到上传和下载持久数据。

## 业务目标

本任务提交离线可审查的 app/db Compose、应用容器、安全配置样例、Caddy 端口 88 片段与挂载合同、运维文档和标准库测试。性能协议覆盖商品列表、商品详情、收藏、询价、行为上报、后台 30 日趋势和数据导出，但只固定环境指纹、预热、并发、样本、P50/P95 和错误率口径，不把未部署或未实现的场景写成通过。

NUR-OPS-001 将消费本任务最终获批提交，在锁定的 remote_execution 合同内备份和验证现有 Caddy、构建并启动 app/db、受控初始化空测试库、增加独立 :88 站点并执行冒烟和回滚。任何共享 Caddy 文件路径、镜像身份、FastCGI 回环端口或挂载事实与计划不一致时，L4 必须停止并重新计划。

## 明确不做

- 不访问 registry 或目标服务器，不运行 SSH/SCP、Docker daemon、数据库、Caddy 或端口命令。
- 不创建 /root/jia/miaomu，不监听端口 88，不修改、重载或重建现有 Caddy/Beszel。
- 不提交或保留任何 Nginx Dockerfile、Nginx 配置、web 服务或 edge 网络设计。
- 不修改 ShopXO 业务代码、核心、config/database.php、数据库 schema 或完整安装 SQL。
- 不提交真实密钥、口令、私钥、生产配置或 .env。
- 候选镜像 digest 和 Caddy 片段只作为固定输入；可解析性、目标架构摘要、镜像 ID、Caddy validate、Compose 语义和运行状态全部移交 NUR-OPS-001 核验。
- 不把共享 Caddy 复用扩大为修改现有 80/443 站点、TLS、其他路由、Caddy 镜像版本或 Beszel 服务。

## 开放决策与实施前事实

合同不关联现有开放产品决策。以下属于 L4 环境门禁而非产品决策：

1. NUR-OPS-001 必须重新核验 Caddy v2.11.2 的容器身份、host-network 模式、真实配置文件和 Compose 文件路径、当前挂载及 80/443 基线。
2. app FastCGI 的宿主机回环端口固定为 127.0.0.1:19000；若 NUR-OPS-001 发现占用，只能阻塞并重新批准本合同，不得现场改值。
3. 若 Caddy 尚不能看到 /root/jia/miaomu/public 与媒体卷，NUR-OPS-001 只能在备份和验证后增加最小只读挂载；需要修改其他共享路径时停止。
4. 共享 Caddy 变更前必须保存原 Caddyfile、共享 Compose、docker inspect、挂载、端口和 https://supervise.jiayyy.cn 健康快照。新增 public/uploads/downloads 挂载时，必须先验证完整候选 Caddyfile 与共享 Compose，再只 recreate jia-caddy；仅所需挂载已存在且只有配置变化时才允许 reload。失败后恢复原配置与挂载、只 recreate jia-caddy，并再次验证 supervise。
5. `http://38.12.21.18:88` 的验收不得提交真实账号、会话或询价个人数据；取得苗木域名 DNS 并完成独立 L4 TLS 计划前，不能把它描述为正式用户入口。

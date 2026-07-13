# NUR-OPS-003 测试计划

## 自动测试

- `harness_selftest`：运行 `python scripts/harness_selftest.py`，验证 Harness 范围、审批、证据和状态恢复门禁；平台不支持的符号链接测试只记 skip，不转成 pass。
- `deployment_contract`：运行 `python tests/ops/test_deployment_contract.py`，离线检查 Compose 文本、结构化策略、Dockerfile、Nginx/PHP 配置样例和四份运维文档，退出码应为 0。
- 自动测试不得联网、安装依赖、调用 Docker daemon、访问服务器、读取密钥或修改业务/Harness 控制面。

## 手工验收

1. 检查设计中唯一宿主机端口为 88，数据库/FPM 无宿主机端口，后端网络 internal，服务/网络/卷使用 `miaomu` 命名空间。
2. 检查所有服务声明健康检查、资源限制、日志限制和 Watchtower 禁用，应用/Web 非 root、只读且不挂 Docker socket。
3. 检查 Nginx root 为 `public/`，`install.php`、隐藏/敏感路径和上传目录 PHP 执行被拒绝。
4. 检查 MySQL 使用 `_FILE`，应用配置样例只读取 `/run/secrets/mysql_app_password`，Compose 只引用仓库外 secret/config 路径。
5. 检查文档区分离线制品与 L4 待执行步骤，不把候选 digest、Compose 文本、未启动容器或未来性能写成通过。
6. 扫描 Git diff，只允许授权路径且无口令、私钥、API Key、生产配置、连接串或 `.env`。

## L4 交付验证（本任务不执行）

`NUR-OPS-001` 在独立审批后执行目标服务器 `docker compose config --quiet`、registry 与 `linux/amd64` 摘要核验、镜像构建、Composer/platform 检查、容器健康、数据库初始化、备份恢复、端口 88 冒烟和性能测量，并在自己的 `evidence.md` 记录命令、退出码和脱敏结果。`NUR-OPS-003` 只检查运维文档包含这些命令和判定标准。

## 数据与权限

本任务不连接数据库、不处理用户、收藏、询价或统计数据，也不改变权限。测试只验证数据库不发布宿主机端口、配置从仓库外 secret 注入、持久化和备份合同存在；用户隔离、历史语义和 PV/UV 由后续业务任务真实验证。

## 性能协议覆盖

文档必须定义环境指纹、数据集版本、预热、并发、样本数、P50、P95、错误率和原始结果保存方式，并分别列出商品列表、商品详情、收藏、询价、行为上报、后台 30 日趋势、数据导出的补测负责人和前置条件。未实现或未执行场景只能标记 blocked/not_run。

## 未覆盖项

- 本机缺少 Docker、PHP、Composer 和 MySQL，不能执行 Compose 解析、构建或应用启动。
- 本任务不访问 registry/服务器；候选 digest 可解析性、目标架构摘要、镜像 ID和端口状态未验证。
- 不执行数据库、备份恢复、浏览器、HTTP、性能或回滚演练；这些属于 L4 部署及后续功能任务。

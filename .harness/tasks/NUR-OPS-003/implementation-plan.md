# NUR-OPS-003 实施计划

## 实施步骤

1. 固定 ShopXO 运行合同。使用 PHP 8.2-FPM，document root 为 `public/`；Dockerfile 声明并在 L4 构建时检查必需 PHP 扩展和 `fsockopen`。源码只读，写路径限于 `runtime`、上传、下载和可选 storage 卷。
2. 集中记录候选镜像 tag+digest：PHP 8.2 FPM、Composer 2.8、Nginx stable-alpine、MySQL 8.0，禁止 `latest`。本任务只做离线固定值检查；目标 `linux/amd64` 摘要与镜像 ID由 `NUR-OPS-001` 核验。
3. 在 `deploy/compose.yaml` 定义三个长期服务 `web`、`app`、`db`，以及 `edge`、`backend` 网络。只有 `web` 设计发布 `88:8080`；`backend` 设为 internal；FPM/MySQL 不发布端口。所有服务声明健康检查、资源限制、日志限制、`no-new-privileges` 和 Watchtower 禁用标签，不挂 Docker socket。
4. 构建应用/网页镜像。应用镜像多阶段安装 Composer 依赖，运行阶段移除编译工具并使用非 root UID；网页镜像只包含 `public/` 静态资产和显式 Nginx 配置，拒绝 `install.php`、隐藏文件、敏感路径和上传目录 PHP 执行。
5. 编写非敏感配置。Compose secrets 只引用 `/etc/miaomu/secrets/**`；MySQL 使用 `_FILE`。提交 `deploy/config/database.php.example`，由 L4 任务在仓库外生成 `/etc/miaomu/config/database.php` 并只读挂载；该文件从 `/run/secrets/mysql_app_password` 读取口令。
6. 编写 `stack-policy.json` 和 `tests/ops/test_deployment_contract.py`。标准库测试检查服务/端口/网络/卷、固定镜像、非 root、只读、安全选项、健康检查、安装器拒绝、Docker socket 禁止、secret 路径、文档章节和敏感值模式，不手写 YAML 解析器冒充 Compose。
7. 编写单目录、部署、备份恢复和性能基线文档。所有会联网、构建、启动、初始化、打开端口或访问服务器的命令明确标记为 `NUR-OPS-001` 待执行项，不在本任务运行。

## 验证顺序

1. `python scripts/harness.py source-check`。
2. `python scripts/harness_selftest.py`。
3. `python tests/ops/test_deployment_contract.py`。
4. 本地逐文件敏感信息检查和预期文件清单复核。
5. 进入 verifying 后运行 `verify`、`scope-check`、`evidence-check` 和 `review-pack`，记录真实退出码与限制。

Compose `config --quiet`、registry/目标架构核验、镜像构建、容器健康、数据库初始化、备份恢复、端口 88 冒烟和性能测试只写入 L4 交付清单，由 `NUR-OPS-001` 获批后执行并在其证据中记录。

## 数据库与核心适配

无数据库结构或数据变更，无 ShopXO 核心适配。本任务不得运行 `config/shopxo.sql`，不得修改仓库中的 `config/database.php`，差异只允许位于 `deploy/**`、`tests/ops/**` 和 `docs/operations/**`。

## 失败处理与回滚

发现真实密钥、网络访问、未固定镜像、数据库/FPM 宿主机端口、Docker socket、root 应用、全源码写权限、安装器开放或未核验路径时立即停止，不将缺口表述为通过。

回滚只还原本任务授权路径，随后运行 `source-check` 与 Harness 自检，并确认 Git 差异和任务证据中没有网络命令、远端执行或服务器状态声明。服务器状态复核属于 `NUR-OPS-001`，不在本任务回滚中执行。

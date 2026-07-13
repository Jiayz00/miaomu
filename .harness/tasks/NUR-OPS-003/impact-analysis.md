# NUR-OPS-003 影响分析

## 需求与当前事实

任务关联 `NFR-SEC-006`、`NFR-PERF-005`。ShopXO 固定为 6.9.0、上游提交 `d1825c5404054b535255d8fcad675a5dae0ab633`，完整源码基线为 `846eb6a1cf7f94415ae9ae4c3eefb87d4fa9da3e`，`source-check` 已通过。源码核验确认最低 PHP 8.0.2，安全 document root 为 `public/`，HTTP 入口为 `public/index.php`、`public/admin.php`、`public/api.php`。

当前本机没有 PHP、Composer、Docker 或 MySQL，自动门禁只能使用 Python 3.11 标准库。`NUR-OPS-001` 合同已进入分支，但其证据仍未完成；服务器系统、资源、Docker/Compose 版本、潜在共享服务、端口 88、目标目录和镜像运行事实均视为待 L4 核验。

源码和锁文件要求 curl、GD、mbstring、PDO/PDO MySQL、Zip、Fileinfo、iconv、ctype、json、filter、hash、libxml、DOM、SimpleXML、XML、XMLReader、XMLWriter、zlib，并需保证 `fsockopen` 可用。稳态候选写路径为 `runtime`、`public/static/upload`、`public/download` 和可选 `public/storage`；无法确认的目录不得通过全源码可写规避。

候选 manifest-list digest 集中固定为 PHP 8.2 FPM、Composer 2.8、Nginx stable-alpine 和 MySQL 8.0 的明确 digest。本任务只检查固定值、禁止 `latest` 和集中策略；可解析性、`linux/amd64` 目标摘要及最终镜像 ID由 `NUR-OPS-001` 真实核验，候选值不是运行证据。

## 当前调用链与数据

本任务不进入控制器、服务、权限、事件或业务表。设计拓扑为外部 88 -> Web -> PHP-FPM -> 内部 MySQL；只有 Web 设计为发布宿主机端口，FPM/MySQL 不发布端口，后端网络设为 internal。服务、网络和卷使用 `miaomu` 命名空间，只按潜在共享主机进行隔离设计，不声明 Caddy/Beszel 当前真实状态。

ShopXO 原生从 `config/database.php` 读取连接信息。仓库只提交 `deploy/config/database.php.example`；L4 任务在仓库外生成完整 `/etc/miaomu/config/database.php` 并只读挂载，该文件从 `/run/secrets/mysql_app_password` 读取口令。MySQL 使用 `_FILE` 变量。口令不进入 Compose 环境、Git、命令行或日志，也不修改仓库中的 `config/database.php`。

安装器会要求广泛写权限并生成数据库配置、改名后台入口，这不是稳态最小权限依据。本栈拒绝访问 `install.php`，源码镜像只读，只给已核验数据目录写权限。

## 影响范围

- 用户端、管理端、API 与数据库：无行为或 schema 变化，容器不启动。
- 安全：离线检查密钥注入、非 root、只读源码、Docker socket 禁止、端口隔离、上传 PHP 禁止和 Watchtower 禁用。
- 性能：固定测量协议，不声明任何业务场景结果。
- 升级：镜像输入集中固定，禁用在线自动覆盖；实际兼容性由 L4 构建验证。
- 审批：因 `NFR-SEC-006` 为 L3，计划与合并均由 `Jiayz00` 独立审批；实现者不得自批。

## 方案比较

1. 配置：端口、网络、卷、资源、安全选项和 secret 路径集中在部署制品。
2. 现有服务：不依赖或修改潜在共享服务，实际存在性由 `NUR-OPS-001` 核验。
3. 插件钩子与 `nursery` 插件：环境任务不需要业务扩展点。
4. 独立模块：使用 `deploy/**`、`tests/ops/**`、`docs/operations/**` 隔离运维制品。
5. 核心适配：无，不修改 ShopXO、vendor 或数据库。

宿主机直接安装会扩大污染面；新建第二 checkout 违反单目录约束；复用潜在共享反向代理会扩大影响范围，均不采用。

## 风险与边界

静态合同不能证明 YAML 可解析、镜像可构建或应用可运行；这些必须由 L4 任务补证。候选 digest 可能失效或不适配目标架构；不得把离线文本检查写成镜像核验。任何真实密钥、Docker socket、宿主机数据库端口、root 应用、全源码写权限或远端命令出现即失败。

回滚只还原本任务提交的授权路径，并检查本任务证据没有网络命令或服务器状态声明。本任务不创建远端状态、卷或数据，因此不得在回滚验证中执行远端盘点。

## 预计文件

- `deploy/compose.yaml`、`deploy/stack-policy.json`、`deploy/docker/**` 和 `deploy/config/database.php.example`。
- `tests/ops/test_deployment_contract.py`。
- `docs/operations/LOCAL_STACK.md`、`DEPLOYMENT.md`、`BACKUP_RESTORE.md`、`PERFORMANCE_BASELINE.md`。
- 不修改 ShopXO 业务代码、`config/shopxo.sql`、仓库中的 `config/database.php`、Harness 策略或核心登记。

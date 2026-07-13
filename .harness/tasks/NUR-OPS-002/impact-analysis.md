# NUR-OPS-002 影响分析

## 需求与当前事实

任务关联 `NFR-PERF-005`。ShopXO 固定为 6.9.0、上游提交 `d1825c5404054b535255d8fcad675a5dae0ab633`，完整源码基线为 `846eb6a1cf7f94415ae9ae4c3eefb87d4fa9da3e`，`source-check` 已通过。`NUR-OPS-001` 合同已进入当前分支，但其证据仍未完成；服务器系统、Docker/Compose 版本、资源、现有服务、端口 88 和目标目录状态在本任务中均视为待 L4 核验，不能作为已通过事实。

当前仓库没有项目级 Docker Compose、Dockerfile 或 ops 测试。Windows 本机缺少 PHP、Composer 和 Docker，因此本任务的自动门禁必须使用 Python 3.11 标准库；最终 Compose 语义由 `NUR-OPS-001` 在获批 L4 实施中使用目标服务器的真实 `docker compose config` 核验，本任务只提供命令和判定标准。

源码核验确认 `public/core.php` 强制 PHP `>=8.0.2`，安全 document root 是 `public/`，HTTP 入口为 `public/index.php`、`public/admin.php`、`public/api.php`；根目录入口仅是兼容代理。安装器与锁文件要求 curl、GD、mbstring、PDO/PDO MySQL、Zip、Fileinfo、XML/DOM/SimpleXML/XMLReader/XMLWriter 及 PHP 标准扩展。稳态必须持久化 `runtime`、`public/static/upload`、`public/download`，可选 `public/storage`；数据库配置由仓库外受控文件挂载为 `config/database.php`。

计划采用以下候选多架构 manifest-list digest：`php:8.2-fpm-bookworm@sha256:a335d57be82b3a392fe5c6287571de29d0b11c491826c783318ccb785dc0f262`、`composer:2.8@sha256:5248900ab8b5f7f880c2d62180e40960cd87f60149ec9a1abfd62ac72a02577c`、`nginx:stable-alpine@sha256:0d3b80406a13a767339fbe2f41406d6c7da727ab89cf8fae399e81f780f814d1`、`mysql:8.0@sha256:7dcddc01f13bab2f15cde676d44d01f61fc9f99fe7785e86196dfc07d358ae2b`。本任务只检查这些值被集中固定且不是 `latest`；`NUR-OPS-001` 必须联网核验其可解析性、目标 `linux/amd64` manifest 与最终镜像 ID，核验前不得称为运行证据。

## 当前调用链与数据

本任务不进入控制器、服务、视图、接口、权限、事件或业务表调用链。计划中的运行拓扑为：外部 88 -> Web 容器 -> PHP-FPM 应用容器 -> 内部 MySQL；源码、运行时、上传和数据库分别按最小写权限挂载。数据库连接值只在运行时从未跟踪配置注入，配置样例只声明变量名和生成方式。

PHP 扩展、前端入口、安装期写入文件、运行时与上传目录已从当前固定源码核验。无法确认的目录不得直接给整个源码树写权限。

安装器要求根目录、config、插件、主题、路由和 public 多处可写，并会生成 `config/database.php`、随机改名后台入口；这是安装期行为，不是稳态最小权限依据。本栈不开放浏览器安装器：L4 任务在空测试库受控初始化，在仓库外生成完整 `config/database.php` 并只读挂载；该文件按受控样例读取 `/run/secrets/mysql_app_password`，稳态源码镜像只读，只给已核验的数据目录写权限。

## 影响范围

- 用户端、管理端和 API：无行为变化，容器不启动。
- 数据库和历史数据：无 schema、数据或连接操作；只设计持久化与备份合同。
- 安全：防止真实密钥入库、数据库端口外露、Docker socket 挂载、root 应用进程、可执行上传和 Watchtower 自动覆盖固定版本。
- 性能：固定服务资源边界、健康检查与测量协议，但不声明任何业务性能结果。
- 升级：镜像和依赖版本集中记录；不得使用 `latest`，后续升级必须显式审查与验证。
- 共享服务器：服务、网络、卷和项目名均使用 `miaomu` 前缀，不触及现有 Caddy/Beszel。

## 方案比较

1. 配置：复用 ShopXO 固定源码和服务器现有 Docker/Compose，端口、卷、健康检查和资源限制集中声明。
2. 现有服务：不复用现有 Caddy，因为它承载其他项目且监听 80/443；苗木栈直接设计为端口 88。
3. 插件钩子与 `nursery` 插件：环境制品不需要业务钩子或插件。
4. 独立模块：`deploy/**`、`tests/ops/**`、`docs/operations/**` 与业务源码隔离，是最小可维护边界。
5. 核心适配：无。容器化不需要修改 ShopXO 框架、服务或 vendor。

宿主机直接安装 PHP/MySQL 会污染共享测试服务器并增加版本漂移；新建第二本地 checkout 违反用户单目录约束；两者均不采用。

## 风险与边界

- Compose 静态文件可能语法正确但运行失败；本任务只交付离线合同，必须由 L4 任务使用目标 Docker Compose 解析器核验并执行构建和健康检查。
- 镜像 tag 和 manifest list 可变化或不适配目标架构；候选摘要不是运行证据，必须由 L4 任务复核后记录目标架构摘要与镜像 ID。
- ShopXO 可能需要安装期写配置或插件生成文件；只读源码策略必须依据实际写路径收敛，不能用全树可写掩盖问题。
- MySQL 固定为 8.0，字符集使用 utf8mb4；该选择与 `config/shopxo.sql` 的 MySQL 8.0.42 导出事实一致。认证插件、SQL mode 和时区仍须在 L4 空库安装时真实验证，不能为通过而关闭严格模式。
- 配置样例和测试输出必须扫描密钥；任何真实值出现即失败。
- 本任务与 L4 部署边界必须保持：不得因已有 Compose 文件就提前启动或开放 88。

## 预计文件

- 新增 `deploy/compose.yaml`、`deploy/docker/**`、`deploy/config/**` 和不含凭据的操作入口或样例。
- 新增 `tests/ops/test_deployment_contract.py`，使用标准库检查结构化策略、文件合同和敏感信息规则。
- 新增 `docs/operations/LOCAL_STACK.md`、`DEPLOYMENT.md`、`BACKUP_RESTORE.md`、`PERFORMANCE_BASELINE.md`。
- 不修改 `.gitignore`、ShopXO 源码、`config/shopxo.sql`、Harness 策略或核心登记。

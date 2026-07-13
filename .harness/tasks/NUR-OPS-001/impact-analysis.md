# NUR-OPS-001 影响分析

## 需求与当前事实

本任务关联 `NFR-SEC-006`、`NFR-PERF-005`，并落实第一阶段“部署和确认 ShopXO 版本”的前置工作。上游固定为 ShopXO 6.9.0、提交 `d1825c5404054b535255d8fcad675a5dae0ab633`；`composer.json` 要求 PHP `>=8.0.0`。完整源码事实基线提交为 `846eb6a1cf7f94415ae9ae4c3eefb87d4fa9da3e`，GitHub `origin` 指向 `Jiayz00/miaomu`，`upstream` 保留 `gongfuxiang/shopxo`。

2026-07-13 的真实检查显示：火绒已信任并允许恢复 `app/common.php`，其 blob 为固定上游的 `74422022b2f384c1c97e3eafabd946d2bb5ec219`；四份事实基线已在 bootstrap 分支刷新，`source-check` 通过且工作区无源码差异。`python scripts/harness.py doctor` 可运行，但 Windows 主机没有 PHP 和 Composer，严格 doctor 仍应如实标记工具链缺口。

服务器 `38.12.21.18:22` 现已通过已有 `known_hosts` 和 `Jia-8u8g` 配置完成严格主机校验与只读认证。服务器为 Ubuntu 22.04、8 vCPU、约 7.8 GiB 内存、无 swap、根盘约 35 GiB 可用；Docker 29.4.2 与 Compose 5.1.3 可用，宿主机没有 PHP、Composer、MySQL CLI。现有 Compose 项目为 `caddy` 和 `beszel-monitoring`，Caddy 使用 host network 监听 80/443，Beszel 监听本机 8090；端口 88 未监听，`/root/jia/miaomu` 不存在。

## 当前调用链与数据

任务不改变控制器、服务、视图、接口、权限、事件或业务表。运行链路确定为：本地唯一工作区产生经审查提交 -> GitHub 受保护分支 -> 非生产服务器 `/root/jia/miaomu` 的固定提交 -> 独立 `miaomu` Docker Compose 项目 -> 端口 88 Web 服务/PHP-FPM -> ShopXO -> Compose 内部 MySQL。现有 Caddy、Beszel 和端口 80/443/8090 不参与调用链。

测试库初始化只允许使用固定上游安装基线，凭据通过仓库外受限配置注入。MySQL 只加入 Compose 内部网络，不发布宿主机端口；数据库、上传和运行时数据使用任务专属命名卷或 `/root/jia/miaomu` 下的受限持久化目录。镜像摘要、卷布局、备份工具和应用服务账号需在实现前按实际 Dockerfile/Compose 配置固定。

## 影响范围

- 用户端/管理端/API：仅建立可启动和冒烟的底座，不改变页面与响应语义。
- 数据：不修改 schema；测试库初始化、备份和恢复是人工 L4 步骤，必须在空库或明确测试数据上执行。
- 安全：主要风险是密钥进入 Git/日志、误把服务器当生产、配置权限过宽、以 root 长期运行应用、Docker socket 暴露或数据库端口暴露。脚本和文档只能引用环境变量名或仓库外路径，不记录值；应用容器不得挂载 Docker socket。
- 性能：固定测量方法和环境事实；当前尚无苗木数据/业务入口，除现有 ShopXO 基础页面外不得宣称未来流程达标。
- 升级：`upstream` 与固定 commit 分离，部署必须使用可追溯提交；不得运行 ShopXO 在线升级覆盖二开文件。
- 本地环境：只允许 `D:/苗木网站` 一份工作区，不创建 WSL clone、第二 worktree 或同级项目目录。

## 方案比较

1. 配置：端口 88、项目名 `miaomu`、数据卷和仓库外配置集中声明；不修改现有 Caddy 与 80/443。
2. 现有服务：复用服务器 Docker/Compose 以及 ShopXO `composer.json`、`composer.lock`、安装 SQL和原生入口，不在宿主机搭建第二套常驻 PHP/MySQL 服务。
3. 插件钩子与 `nursery` 插件：环境任务不需要业务钩子或插件，暂不引入。
4. 独立模块：部署资料集中到 `deploy/**`，环境检查集中到 `tests/ops/**`，运行手册集中到 `docs/operations/**`，避免把运维逻辑散落进业务目录。
5. 核心适配：无。`app/common.php` 只允许从固定提交恢复到精确 blob，恢复后 Git diff 应为空，不构成核心改动。

方案选择为独立 Docker Compose：宿主机缺少 PHP/Composer/MySQL，而 Docker/Compose 已稳定运行；容器化可避免污染现有 Caddy/Beszel，并能固定版本、网络和卷。宿主机原生安装会扩大升级与端口冲突面；复用现有 Caddy 会触及其他项目；WSL/ext4 clone 违反用户的单本地项目目录约束，均不采用。

## 风险与边界

- L4 独立审批：计划/合并由 `Jiayz00` 审查，release 必须由第三个真实身份批准；不得由子代理伪造身份。
- 生产边界：若服务器是生产或含真实用户数据，本任务立即停止；Harness 不授权生产访问。
- 数据损失：任何数据库初始化、覆盖部署或服务切换前必须确认空环境或完成可恢复备份。
- 可达性：TCP/22 和严格 SSH 认证已通过；88 尚未监听，必须在获批实施并启动独立 Compose 栈后验证。
- 源码完整性：`app/common.php` 已恢复并通过 baseline freshness gate；后续若再次缺失必须立即停止，不允许用跳过 `source-check`、`skip-worktree` 或修改门禁来绕过。
- 密钥：不得读取或提交 `C:/Users/25390/.ssh` 私钥内容；SSH 客户端只引用现有密钥路径。对话中的生图 Key 不参与本任务。
- 兼容性：Ubuntu/Docker/Compose 已确认；PHP/MySQL/Nginx 镜像与扩展必须由 Dockerfile/Compose 固定版本和摘要，不能使用 `latest`。
- 共享主机：`caddy` 和 `beszel-monitoring` 已运行；任务不得停止、重建、改名或挂载其路径/卷/网络，并为所有苗木容器设置 `com.centurylinklabs.watchtower.enable=false`。
- PX 与统计：本任务不改变 PX 路由和指标口径，后续独立任务必须继续验证。

## 预计文件

- 新增 `deploy/compose.yaml` 与 `deploy/docker/**`：独立 `miaomu` Web/PHP/MySQL 栈、固定镜像、健康检查、资源约束、内部数据库网络和持久卷。
- 新增 `deploy/**` 其他文件：非敏感服务器预检、配置样例、备份、部署、回滚和冒烟入口。
- 新增 `tests/ops/test_deployment_contract.py`：离线检查路径、端口、占位符、回滚和敏感信息规则。
- 新增 `tests/ops/environment_check.php`：服务器 PHP/扩展、源码完整性、权限和非生产标记检查。
- 新增 `docs/operations/**`：单目录开发、服务器验证、性能基线与发布手册。
- 不修改 `.gitignore`；业务 OPS 任务不得授权 Harness/bootstrap 策略路径，本地运行产物必须写入已有忽略目录或保持在授权目录内且不提交。
- 无数据库迁移、无 ShopXO 核心修改、无需 `.harness/core-changes/REGISTER.md` 登记。

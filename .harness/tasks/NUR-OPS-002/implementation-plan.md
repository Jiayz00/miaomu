# NUR-OPS-002 实施计划

## 实施步骤

1. 落实已核验的 ShopXO 源码运行要求。使用 PHP 8.2-FPM，document root 固定为 `public/`；Dockerfile 声明构建 curl、GD、mbstring、PDO/PDO MySQL、Zip、Fileinfo、XML/DOM/SimpleXML/XMLReader/XMLWriter、iconv、ctype、json、filter、hash、libxml 和 zlib，并在 L4 构建中实际检查。源码镜像只读，稳态写路径只包含 `runtime`、`public/static/upload`、`public/download` 和可选 `public/storage`。
2. 固定候选镜像输入。Dockerfile/Compose 使用 `php:8.2-fpm-bookworm@sha256:a335d57be82b3a392fe5c6287571de29d0b11c491826c783318ccb785dc0f262`、`composer:2.8@sha256:5248900ab8b5f7f880c2d62180e40960cd87f60149ec9a1abfd62ac72a02577c`、`nginx:stable-alpine@sha256:0d3b80406a13a767339fbe2f41406d6c7da727ab89cf8fae399e81f780f814d1`、`mysql:8.0@sha256:7dcddc01f13bab2f15cde676d44d01f61fc9f99fe7785e86196dfc07d358ae2b`。本任务只验证固定值和禁止 `latest`；L4 任务负责联网核验可解析性、`linux/amd64` 目标摘要和最终镜像 ID。应用镜像以 Git SHA 标记，构建阶段执行 Composer validate/install/platform checks，运行阶段不带编译工具。
3. 编写 `deploy/compose.yaml` 与 `deploy/docker/**`。定义 `web`、`app`、`db` 三个长期服务、`edge` 与 `backend` 网络、端口 88、健康检查、资源限制、持久化 bind 目录、只读根文件系统、cap drop、no-new-privileges、日志限制和 Watchtower 禁用标签；`backend` 为 internal，MySQL/FPM 不发布宿主机端口，应用不挂 Docker socket。现有 Caddy/Beszel 不加入任何苗木网络。
4. 编写非敏感配置合同。Compose secrets 从 `/etc/miaomu/secrets/**` 仓库外受限路径挂载；MySQL 使用 `_FILE` 变量。仓库只提交 `deploy/config/database.php.example`，L4 任务将其审核后写入仓库外 `/etc/miaomu/config/database.php` 并只读挂载到 ShopXO `config/database.php`；该完整配置文件只从 `/run/secrets/mysql_app_password` 读取口令，不在环境变量、Compose 展开结果或日志中记录口令。明确安装 SQL 只在 L4 空测试库初始化时使用，`install.php` 在稳态 Web 配置中拒绝访问。
5. 编写运维文档。记录单目录命令、构建/启动前提、备份范围、恢复演练、版本回滚、现有服务隔离和性能测量协议；所有会修改服务器的命令标注为 `NUR-OPS-001` 阶段步骤。
6. 实现 `tests/ops/test_deployment_contract.py`。用 Python 标准库解析 `deploy/stack-policy.json`，并检查 Compose/Dockerfile/Nginx/PHP/文档的必需文件、固定 tag+digest、public document root、端口、网络、持久路径、健康检查、资源限制、非 root、Watchtower、安装器拒绝、Docker socket 禁止、敏感信息和占位值。YAML 完整语义由真实 Docker Compose 解析器负责，不手写 YAML parser。
7. 运行自动门禁后，在运维文档中交付由 `NUR-OPS-001` 执行的 `docker compose config --quiet`、镜像核验、构建和健康检查命令及判定标准。本任务不调用 SSH、registry 或 Docker daemon，也不创建远端文件、镜像、容器、网络或卷。

## 验证顺序

1. `python scripts/harness.py source-check`。
2. `harness_selftest`：`python scripts/harness_selftest.py`。
3. `deployment_contract`：`python tests/ops/test_deployment_contract.py`。
4. 本地逐文件敏感信息复核和预期文件清单复核；Compose 解析作为未执行的 L4 交付项记录。
5. 进入 verifying 后运行 `verify`、`scope-check`、`evidence-check` 和 `review-pack`，记录稳定合同哈希与真实退出码。

## 数据库与核心适配

无数据库结构或数据变更，无 ShopXO 核心适配。Compose 中的数据库服务只是未启动的运行合同；本任务不得运行 `config/shopxo.sql`。差异必须完全位于 `deploy/**`、`tests/ops/**`、`docs/operations/**` 和任务运行制品。

## 失败处理与回滚

发现真实密钥、未固定镜像、数据库宿主机端口、Docker socket、root 应用进程、全源码写权限、现有服务名/端口冲突、Compose 解析失败或未核验 ShopXO 写路径时立即停止，不将缺口表述为通过。

回滚只还原本任务的仓库提交；由于不运行容器或修改服务器，不存在卷、数据库或远端文件回滚。回滚后运行 `source-check` 和 Harness 自检，并通过只读服务器盘点确认现有容器与端口没有变化。

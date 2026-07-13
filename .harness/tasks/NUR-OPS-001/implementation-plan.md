# NUR-OPS-001 实施计划

## 实施步骤

1. 关闭剩余外部前置条件。完整源码、TCP/22、严格主机校验和只读 SSH 认证已经通过。远端写操作前复核 `38.12.21.18` 无生产数据，并指定真实 `release_approver`；任一项未完成则保持 draft/blocked，不运行 preflight 或远端写操作。
2. 复核源码与固定基线。完整源码事实基线为 `846eb6a1cf7f94415ae9ae4c3eefb87d4fa9da3e`，`app/common.php` blob 为 `74422022b2f384c1c97e3eafabd946d2bb5ec219`。在计划审批前再次运行 `source-check` 和 `doctor --strict`；本机缺少 PHP/Composer 时严格 doctor 必须保持 blocked，不能靠改 Harness 降级，完整工具链最终在测试服务器证明。
3. 固定服务器事实与隔离边界。记录 Ubuntu 22.04、Docker 29.4.2、Compose 5.1.3、8 vCPU、约 7.8 GiB 内存和 35 GiB 可用空间；记录现有 `caddy`、`beszel-monitoring`、80/443/8090。禁止操作既有项目、路径、卷、网络和容器；若发现生产标记或真实数据立即停止。
4. 实现仓库内运维制品。在 `deploy/compose.yaml` 和 `deploy/docker/**` 定义独立 `miaomu` Web/PHP/MySQL 栈：只将 Web 端口发布为 `0.0.0.0:88`，MySQL 仅内部网络，固定镜像版本/摘要，使用健康检查、资源限制、非 root 应用进程、持久卷和 `watchtower.enable=false` 标签。其余 `deploy/**` 提供不含凭据的配置样例和幂等预检/备份/部署/回滚/冒烟入口；`tests/ops/**` 实现合同与容器环境检查。
5. 先验证后发布。提交获批计划并确保工作区干净后运行 `preflight`，进入 implementing；执行离线 Harness、部署合同、Composer 和 PHP 环境检查。失败时不继续部署，保留退出码和脱敏输出。
6. 初始化非生产实例。发布前确认 `/root/jia/miaomu` 仍不存在或备份其测试内容，将获批提交部署到该目录；只在空测试库中使用固定上游安装基线。以 Compose 项目名 `miaomu` 构建并启动，数据库不发布宿主机端口，Web 只监听 88，应用进程使用最小权限账号。每个远端写步骤需能单独回滚，且不得调用 `docker compose down` 而未显式指定 `-p miaomu -f deploy/compose.yaml`。
7. 冒烟与性能基线。先在服务器本机检查 88 端口，再从外部浏览器验证；记录首页和现有商品入口状态、响应时间测量方法与环境规格。收藏、询价、行为上报、30 日趋势和导出尚未实现时，登记对应后续任务和数据夹具，不写通过结果。
8. 完成证据与审查。转入 verifying，运行合同声明的真实测试，补全 `evidence.md`、release note、范围检查和 review pack；由独立 reviewer 完成合并审查，由第三身份完成 release 审批后才允许发布切换或关闭任务。

## 验证顺序

1. `python scripts/harness.py source-check` 和 `python scripts/harness.py doctor --strict` 验证源码及工具链；它们是 preflight 前置，不以缺失工具为通过。
2. `harness_selftest`：`python scripts/harness_selftest.py`。
3. `deploy_contract`：`python tests/ops/test_deployment_contract.py`。
4. `compose_config`：`docker compose -p miaomu -f deploy/compose.yaml config --quiet`。
5. `composer_validate`：在 `miaomu` 应用容器内运行 `composer validate --no-check-publish --strict`。
6. `server_environment`：在 `miaomu` 应用容器内运行 `php tests/ops/environment_check.php`。
7. 运行 `verify`、`scope-check`、`evidence-check` 和 `review-pack`，保存合同哈希与退出码。
8. 手工核验备份可读、回滚演练、既有容器未变化、服务器本地和外部端口 88、敏感信息扫描以及性能基线记录。网络/SSH/HTTP 命令不放入 required_tests，也不得借 Python 包装绕过 Harness 网络禁令。

## 数据库与核心适配

无数据库结构变更、无 ShopXO 核心适配。测试库初始化只复用固定上游全量安装基线，不修改 `config/shopxo.sql`，也不把它伪装成苗木增量迁移。`app/common.php` 恢复到已提交 blob 后必须是零差异；若内容需要改动，应停止并创建独立核心影响任务。

## 失败处理与回滚

停止条件包括：服务器被判定为生产、SSH 主机指纹异常、备份失败、源码/锁文件不一致、密钥出现在 diff 或输出、数据库不是空测试库、端口 88 被未知服务占用、任何 required test 失败。失败输出只保留脱敏摘要，密钥与完整配置不进入 Harness runs/evidence。

发布前记录上一提交、服务配置和备份校验值。失败时停止新实例，恢复上一提交与对应 Web/PHP 配置，按需恢复测试库和上传资源，再执行上一版本健康检查。若此前无实例，移除本任务创建的测试服务配置并确认 88 端口不再暴露失败版本。回滚失败时保持任务 blocked，不继续业务开发。

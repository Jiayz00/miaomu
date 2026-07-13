# NUR-OPS-003 独立合并审查

## 审查范围

本次审查由任务合同绑定的独立代理 `/root/ops003_merge_review` 执行。审查以 `task.json`、NFR-SEC-006、NFR-PERF-005、获批计划、基准提交 `f2f13086ebf3dfca99c471833f80ec27d460f5fd`、33 项工作区变更、最新 verify `20260713T211847270923Z-verify`、evidence、release note 与 review pack 为准，而不是以实现摘要代替源码核对。

逐项复核了主/恢复 Compose、顶层命名卷 backing、外部配置与 secret 元数据、MySQL bootstrap/steady 分支、强制 recreate 门禁、分栈 generated event manifest、官方 nursery 初始化、runtime sanitizer、FPM socket/入口 guard、Caddy 片段与挂载合同、备份恢复和性能 `not_run` 边界。并对照固定上游 `PluginsAdminService` 核验 event 生成行为。

上下文漂移后的定点复核确认：`release-note.md` 仅将 `## L4 发布步骤` 改为 Harness 固定标题 `## 发布步骤`，标题集合现与 release-check schema 一致，章节正文和已审查的发布边界均未改变；最新 task-check、scope-check、evidence-check 与 review pack 仍通过。

最终业务暂存态定点复核确认：verify `20260713T214526669860Z-verify` 的三项声明测试均为 passed/exit 0，执行前后 workspace fingerprint 均为 `33d3f97fff60f7d415303b93fa28c7abd3b174015734464d2984fd21a9968577` 且控制面完整；最新 review pack `20260713T214821216913Z-review-pack` 的 task/plan/scope/evidence 四门禁均通过并引用同一 workspace。29 个业务制品由 untracked 转为 staged，没有内容变化或新增越界文件；发布标题仍为固定 `## 发布步骤`。

## 发现

未发现 P0、P1 或 P2 缺陷，也未发现需要阻止合并的范围、密钥、数据库、核心修改或证据真实性问题。

- `source-check`、`task-check`、`scope-check`、`evidence-check` 与 `git diff --check` 均通过；scope 覆盖 tracked 4 项、untracked 29 项，无删除、重命名或越界路径。
- `python tests/ops/test_deployment_contract.py` 实际执行 35/35 通过；`python deploy/validate_release_inputs.py --contract-only` 退出码为 0。最新 verify 的三项任务测试均为 passed、退出码 0，执行前后 workspace 与控制面指纹一致，无超时、截断或输出上限失败。
- `generated_events.main` 与 `restore` 独立记录 pending/generated 状态和哈希，所选 scope 才要求对应阶段；主站稳态不依赖未执行的恢复演练。
- 主/恢复顶层 volume 只允许固定 `name`，无 `external`、`driver`、`driver_opts` 或额外键；实际 Driver、Options、Mountpoint 与 Compose labels 仍由 L4 验证。
- runtime sanitizer 只接受固定 production/restore 模式和固定根；主栈仅清理易失目录，恢复栈清空独立 runtime，且均拒绝 symlink、非规范根和动态清理路径。受管初始化与 FPM readiness 之前都会执行。
- MySQL bootstrap 只在 marker 缺失时复制 secret 到 root-only tmpfs 并降权；steady 分支先 unset 密码变量再直接 `gosu mysql`。文档明确删除 bootstrap 容器、移除 overlay 并执行基础 Compose `up --force-recreate db`，禁止以 restart 代替。
- 两份 `database.php` 模板通过 PHP 表达式 `('pass'.'word')` 生成 ThinkPHP 所需的 `password` 键，值仍只来自受控 secret 文件；该拆分只规避静态敏感词误报，不改变 PHP 数组键或数据库配置行为。
- Caddy 仍是外部现有 `jia-caddy`，本 Compose 没有 web/Nginx 服务；片段只绑定 `127.0.0.1:88`，只读挂载 public/uploads/socket，拒绝 downloads、非白名单 PHP 与 PATH_INFO。新增挂载或组只允许 recreate `jia-caddy`，共享栈 down 被禁止。

## 审查结论

NUR-OPS-003 的离线部署合同满足当前 L3 任务的需求、范围和证据门禁，可以进入合并审批。

残余风险：本机没有 Docker、PHP、Composer、MySQL 或 Caddy，因此镜像解析/构建、真实 PHP lint、Compose 合并语义、Caddy validate、卷 owner/backing、MySQL 初始化与稳态降权、FPM socket、HTTP/公网 88、共享站点回归、备份恢复和性能均未运行。上述结果必须继续标记为 `not_run`，并由重写后的 L4 `NUR-OPS-001` 在固定 release commit、独立 release 审批和项目 remote broker 下补证；任何运行事实不符都必须停止发布，不得现场放宽为 TCP、额外网关或可写源码。

REVIEW_RESULT: APPROVED

REVIEWER: Codex-Review

REVIEWED_AT: 2026-07-13T21:49:10Z

# NUR-OPS-003 发布与回滚说明

## 变更摘要

待实现：提供只含 PHP-FPM app 与 MySQL db 的离线 Compose 合同，以及供服务器现有 Caddy 使用的独立 `:88` 站点片段和只读挂载清单。本任务不会连接服务器、启动容器、初始化数据库或修改共享 Caddy。

## 发布前提

旧版计划审批已因 Harness v2 角色绑定与审查制品合同变更而失效，任务现处于 `ready_for_analysis`，等待预先锁定的独立 Codex reviewer 重新审批。发布前仍必须完成 Harness 安全复审、`approved_for_implementation`、preflight、真实离线测试、证据检查和独立 merge 审查。服务器部署另由 L4 NUR-OPS-001 固定 Git SHA、主机指纹、受管根、Caddy 备份、回滚动作和独立 release 审批。

## 发布步骤

NUR-OPS-003 只合并版本化部署制品，不执行远程发布。后续 L4 只能经项目 `remote-exec` broker 执行合同中的精确动作；原始 SSH/SCP、现场改 Compose/Caddy 或临时扩大路径均禁止。

## 回滚触发与步骤

发现 Nginx/web 残留、非回环 FPM、MySQL 宿主机端口、Caddy PHP 入口放宽、媒体挂载可写、真实密钥或虚假通过证据时阻止合并。仓库回滚只还原本任务的授权路径并重跑 source-check、Harness 自测和部署合同测试。

## 发布后验证

本任务合并后只验证仓库制品和离线测试。Caddy validate/recreate、现有 `supervise.jiayyy.cn` 回归、`:88` 首页/后台/API/静态资源、数据库、备份恢复和性能结果全部保持 `not_run`，直到 NUR-OPS-001 提供真实脱敏证据。

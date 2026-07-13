# ShopXO 二次开发边界

## 目标布局

ShopXO 源码应位于仓库根目录。接入版本和 commit 写入 `.harness/baselines/repository.json`；未确认版本时不得把需求文档中的路径视为事实。

## 修改优先级

```text
后台配置/菜单/权限
→ 现有 ShopXO 服务
→ 已验证的插件钩子
→ 独立 nursery 插件
→ 独立模块
→ 小范围核心适配
→ 大规模核心修改（默认禁止）
```

每个任务的影响分析必须说明尝试过的更高优先级方案及放弃原因。

## 当前插件约定

固定上游的 `app/plugins/` 只有占位文件，没有可直接复制的已安装插件。根据 `PluginsAdminService` 脚手架和插件网关，`nursery` 的候选结构是：

```text
app/plugins/nursery/
├─ config.json
├─ Hook.php
├─ Event.php
├─ service/BaseService.php
├─ admin/
├─ index/
├─ api/
├─ view/
├─ install.sql
├─ update.sql
└─ uninstall.sql

public/static/plugins/nursery/
├─ css/
├─ js/
└─ images/
```

原需求中的 `controller/admin`、`controller/index`、`controller/api`、`install/` 和插件内 `static/` 不是当前约定。最终结构仍需用一个真实可安装插件验证数据库记录、`is_enable` 和生成的 `app/event.php`；`app/event.php` 是生成文件，不手工维护。

逻辑标识 `nursery` 可承载询价、询价管理、价格历史、行为事件、日汇总、运营看板和苗木专用配置。

## 核心修改

以下修改默认视为核心影响，实际路径在导入源码后通过基线收敛：

- `app/service/**` 中通用商品、用户、收藏、权限和插件服务；
- `app/admin/controller/**`、`app/index/controller/**` 中通用控制器；
- `config/shopxo.sql` 及上游安装/升级基础；
- 框架、公共中间件、认证和权限基础设施；
- `vendor/**` 和第三方包文件。

核心修改必须在 `.harness/core-changes/REGISTER.md` 登记，并由独立审查者批准。`vendor/**` 不得直接修改。

## 上游同步

- 记录 `upstream` URL、基线 commit 和本地差异。
- 自定义代码尽量集中，避免无关格式化和批量重写。
- 同步上游前先运行 Harness 基线、范围和回归检查。
- 对失效钩子或插件规范重新做只读发现，不依赖旧文档。

## 数据边界

优先复用接入版本中的商品、分类、规格、媒体、收藏、用户、管理员权限和插件配置。新增表名、字段、索引和迁移方式必须以实际 `config/shopxo.sql` 与运行数据库为准。

当前上游没有标准 migration 台账。项目应维护自己的版本化迁移记录，并按 ShopXO 兼容需要生成插件 `install.sql`/`update.sql`/`uninstall.sql`。不得直接修改完整的 `config/shopxo.sql` 充当增量迁移，也不能只相信 `SqlConsoleService` 的成功返回而不核验实际 schema。

## 已确认的核心缺口

- `GoodsDelete` 物理删除商品及相关数据，删除 Hook 在删除后才执行；第一阶段应关闭删除权限，仅允许下架，逻辑删除需要专门设计。
- 收藏采用“先查再插入”，没有 `(user_id, goods_id)` 唯一索引且没有收藏 Hook；并发唯一性和事件采集需要迁移及最小适配。
- 上游已有 `sxo_search_history`，可记录筛选、结果和无结果搜索；新增搜索表前先做复用与 visitor/session 关联设计。
- 商品保存 Hook 位于不同事务时点；价格历史应在事务内捕获旧值并比较新值，不能只依赖提交后的 Hook。
- 系统在线升级和插件在线升级会直接覆盖文件；二开仓库应通过固定上游 commit 和显式合并任务升级，并关闭相关后台权限。

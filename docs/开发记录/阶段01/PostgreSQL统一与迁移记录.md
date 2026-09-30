# PostgreSQL统一与迁移记录

版本：V0.1\
更新日期：2026-09-29\
范围：现有分析小闭环的数据库底座、测试隔离及旧数据切换；不代表阶段01整体完成。

> 历史记录说明（2026-09-30补充）：本文保留2026-09-29数据库统一交付当时的迁移版本、测试结果和未完成边界。后续已实现认证与项目隔离、初始化管理员并认领历史项目，最新状态见[登录与项目归属交付记录](登录与项目归属交付记录.md)及[阶段01清单](../../开发阶段/阶段01-数据库迁移与用户项目基础.md)。不要把本文当时“认证尚未实现”或 `0001_postgresql` 视为当前状态。

## 1. 迁移当时的结论与边界

应用与集成测试已统一使用 PostgreSQL，旧 schema 6 数据已完成离线导入；原 SQLite 已归档，原有 Excel、PNG、DOCX 资产路径保持不变。后端完整回归 **289项通过**，前端 **78项通过**；构建、lint和依赖检查通过。原有前端和 `/api/v1` 业务合约不变。

SQLite 仅保留在离线导入代码、导入测试来源及历史备份中。应用启动、健康检查、业务存储和测试目标均不支持 SQLite 回退；缺失或错误的 PostgreSQL 配置会失败。早期文档中保留SQLite、自动升级schema 1—6的描述是历史方案，已被本次统一决定替代。

用户认证、用户级资源隔离、项目中心、统一任务队列及后续模块尚未完成。所有后续模块继续按[阶段总览](../../开发阶段/00-开发路线与使用说明.md)的“数据库 → 后端 → 前端 → 验收”逐项开发，不提前建立全部未来业务表，也不因本次底座切换勾选尚未实现的产品功能。

## 2. 已验证环境与权限

| 项目 | 当前值或边界 |
| --- | --- |
| 服务 | 本机 `localhost:5432`，PostgreSQL `18.1` |
| 开发库 | `paperassist_system`，UTF8，owner `paperassist_app`，schema `public` |
| 测试库 | `paperassist_system_test`，UTF8，owner `paperassist_test` |
| 角色属性 | 两角色均为NOSUPERUSER、NOCREATEDB、NOCREATEROLE、NOREPLICATION |
| 连接授权 | 两库已撤销PUBLIC CONNECT；分别授予对应角色。实查各角色连接自己库为true、连接对方库为false |
| 迁移权限 | 各角色拥有自己的数据库，可执行schema迁移；不是仅有业务DML权限的运行账号 |
| 开发资产 | `C:\Users\86182\Desktop\PaperAssist-System\backend\data`，继续保存原Excel、PNG与DOCX |
| 测试隔离 | 每例集成测试生成 `pa_test_<uuid32>` schema并使用pytest临时资产目录；纯配置测试不连接数据库 |
| 当前迁移版本 | Alembic `0001_postgresql` |

数据库连接权限分开不等同于产品中的用户权限。数据库owner与运行角色进一步分权、生产SSL/网络方案、长期备份策略和完整恢复演练仍待后续落实。

## 3. 配置、显式迁移与测试规则

只使用以下项目专用配置；真实连接串存放在被Git忽略的 `backend/.env`，环境变量优先。本文和 `.env.example` 不保存密码。

| 配置键 | 用途 |
| --- | --- |
| `PAPERASSIST_ENV` | 日常开发为 `development`；pytest fixture显式设置 `test` |
| `PAPERASSIST_DATABASE_URL` | 开发连接，数据库名必须为 `paperassist_system` |
| `PAPERASSIST_TEST_DATABASE_URL` | 测试连接，数据库名必须为 `paperassist_system_test` |
| `PAPERASSIST_DB_SCHEMA` | 开发为 `public`；测试由fixture替换为本例新建的 `pa_test_` + 32位小写UUID十六进制 |
| `PAPERASSIST_DATA_DIR` | 资产目录，相对路径以 `backend` 为基准；不决定数据库目标 |
| `PAPERASSIST_PLOT_WORKER_ENABLED` | 测试、切换和只读联调设置为 `0`，关闭图表与解释恢复扫描 |

禁止使用通用 `DATABASE_URL` / `TEST_DATABASE_URL`；本机全局测试连接属于其他项目，项目配置不读取或修改它们。测试连接缺失、目标错误或数据库不可用时直接失败，不回退开发库或SQLite。

在 `backend` 目录安装依赖后显式执行：

```powershell
.\.venv\Scripts\python.exe -m app.database upgrade
.\.venv\Scripts\python.exe -m app.database check
```

每条命令失败时先处理配置、权限或版本错误，不能继续启动服务。`upgrade` 迁移已存在的目标schema；不创建数据库或角色。`check` 使用只读事务核对当前schema的版本。应用启动及 `GET /api/v1/health` 通过独立的 `check_database_ready()` 检查连通性和版本，不执行DDL或准备资产目录；健康检查保留原有文件目录故障下的可用行为。

数据库实现采用SQLAlchemy Core + psycopg；Alembic版本明确存放在所选schema。读事务使用只读一致快照；写事务以事务级advisory lock保持既有串行写入语义，在提交或异常时释放连接和锁。该选择保留现有配置竞争、幂等与来源校验行为，不代表已完成多用户容量验证。

pytest只在专用测试库创建本例schema，显式迁移后运行；清理前再次核对数据库，只删除本例实际创建且名称匹配的schema。清理不接受任意环境输入作为删除目标。测试默认清空 `OPENAI_API_KEY`、关闭恢复扫描，并使用独立临时资产目录；需要模型配置的用例显式设置假key并使用模拟云端响应。

## 4. 旧数据备份与导入规则

实现入口为 `backend/scripts/migrate_sqlite.py`，导入逻辑在 `backend/app/legacy_import.py`。执行前停止应用与worker，确保没有源库、目标库或资产写入；导入不启动后台扫描，不调用OpenAI。

- 只读打开schema 6 SQLite，检查准确九表及列、完整性、外键、JSON与文件引用；schema 1—5需先由匹配旧程序升级独立副本。
- 原始Excel、PNG、DOCX按原记录校验大小、SHA256及路径；拒绝缺失、变化或越界资产。
- 可先创建独立新备份目录，保留源库及全部资产和 `manifest.json`；不会覆盖已有备份目录。
- 导入整个事务一次提交，保留原ID、配置修订、业务JSON快照、来源关联及job顺序；导入后再次核对全行值、哈希及源资产。
- 空目标可导入；完全一致的既有目标返回 `already_imported`；部分、无关或变化目标直接拒绝，不覆盖、不追加部分数据。
- 导入失败回滚目标事务，保留源库和资产；当前应用不提供SQLite双写或连接回退。

以下命令从 `backend` 执行，使用本次已核验的备份作为源、原资产目录作为运行路径；它们展示可复核步骤，重复导入后如应用已产生新数据，应预期目标差异导致拒绝：

```powershell
.\.venv\Scripts\python.exe .\scripts\migrate_sqlite.py --help
.\.venv\Scripts\python.exe .\scripts\migrate_sqlite.py --source .\backups\postgres-cutover-20260929T084906Z\data\paperassist.sqlite3 --data-dir .\data --dry-run
.\.venv\Scripts\python.exe -m app.database upgrade
.\.venv\Scripts\python.exe .\scripts\migrate_sqlite.py --source .\backups\postgres-cutover-20260929T084906Z\data\paperassist.sqlite3 --data-dir .\data
.\.venv\Scripts\python.exe -m app.database check
```

`--dry-run`验证来源及资产，不连接PostgreSQL。`--backup-dir <新目录> --backup-only`只建立并校验备份；备份目录必须不存在且位于源资产目录之外。`--migrate`可在正式导入前显式执行迁移，不能与 `--dry-run` 或 `--backup-only` 组合；本文采用单独的 `upgrade` 步骤便于定位错误。

## 5. 本次实际切换证据

2026-09-29已完成下列操作与核对，未重新调用收费模型API。

| 证据 | 实际结果 |
| --- | --- |
| 备份 | `backend/backups/postgres-cutover-20260929T084906Z/data/`含 `paperassist.sqlite3`与5份资产；校验清单 `manifest.json`位于该备份根目录 |
| 显式迁移 | 开发库 `upgrade` / `check` 通过，版本 `0001_postgresql` |
| 正式导入 | 九张业务表全行值、ID、关联、版本、快照与哈希一致，计数见下表 |
| 重复导入 | 返回 `already_imported`，无重复记录 |
| 资产核对 | 2份Excel、2份PNG、1份DOCX大小与SHA256全部一致，运行资产路径不变 |
| 应用读取 | 关闭worker并清空本次联调进程OpenAI密钥，实际FastAPI应用两次TestClient生命周期；释放连接池后重新连接，共38次GET检查通过 |
| 实际下载 | 每轮下载2份Excel、2份PNG、1份DOCX，两轮共10次下载SHA256核对通过；读取前后业务行不变 |
| 原库归档 | `backend/backups/postgres-cutover-20260929T084906Z/retired-original.sqlite3`，哈希与原备份清单一致 |
| 归档后检查 | 活跃 `backend/data` 无SQLite文件；应用启动、health及项目读取仍通过 |

| 业务表 | 导入前后记录数 |
| --- | ---: |
| `projects` | 1 |
| `files` | 2 |
| `analysis_setups` | 1 |
| `analysis_runs` | 2 |
| `figures` | 2 |
| `figure_jobs` | 2 |
| `explanations` | 1 |
| `explanation_jobs` | 1 |
| `reports` | 1 |

该核对证明现有数据在本轮切换中保持一致；不代表认证、生产部署、任意历史schema或所有科研样本均已验证。迁移后的读取检查使用真实应用和PostgreSQL，但不是新增的浏览器人工验收或真实云端生成。

## 6. 本轮回归与限制

项目根目录的验证命令及结果：

| 命令/检查 | 结果 |
| --- | --- |
| `.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests -q` | **289 passed in 168.67s** |
| `npm.cmd --prefix .\frontend test` | **78项通过** |
| `npm.cmd --prefix .\frontend run build` | 通过 |
| `npm.cmd --prefix .\frontend run lint` | 通过 |
| `.\backend\.venv\Scripts\python.exe -m pip check` | 通过 |
| 测试后只读检查 | `remaining_test_schemas=0`，`test_public_tables=0` |

回归覆盖现有业务闭环、专用连接保护、事务、健康检查、只读导入、重复/冲突/失败导入及资产核验。第一次完整后端回归发现健康检查误依赖资产目录，已改为独立检查PostgreSQL，保留原文件故障契约；另外验证测试默认清空真实模型密钥。不以此前部分通过结果代替最终结果。

尚未完成的边界：

- 当前开发/测试角色各自拥有数据库，未拆成仅DML运行角色与独立迁移角色；角色无全实例管理权限不等于最小运行权限已完备。
- 本轮保留既有九表结构及业务JSON快照，未新增用户、会话、项目所有者或全部未来业务模型；认证与用户隔离按阶段01继续。
- SQLite源库与备份保留以供审计或使用匹配的历史程序恢复，当前版本不允许通过改连接串回退SQLite；完整恢复演练和长期备份保留期限未完成。
- PostgreSQL日常备份需同时保留数据库及同一静止时点的资产，单独复制 `backend/data` 不构成完整备份；自动备份、恢复目标及生产部署在阶段10落实。
- 本轮使用模拟云端响应做自动回归；已有真实云端和Word/WPS人工验收属于此前闭环记录。多用户容量、全部图像/文档排版场景及更多真实科研样本未验证。

实现入口与清单：[README](../../../README.md)、[阶段00](../../开发阶段/阶段00-开发准备与边界确认.md)、[阶段01](../../开发阶段/阶段01-数据库迁移与用户项目基础.md)、[需求覆盖与决策台账](../项目管理/需求覆盖与决策台账.md)。

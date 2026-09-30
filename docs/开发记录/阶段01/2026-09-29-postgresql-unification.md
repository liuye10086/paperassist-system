# PostgreSQL统一实施记录

版本：V0.1；日期：2026-09-29。

目标：按用户决定让开发、运行和自动测试统一使用PostgreSQL，保留现有Excel到Word闭环与历史成果。

架构：SQLAlchemy Core＋psycopg连接，Alembic显式管理九张现有表；运行代码不再连接或回退SQLite。JSON和时间字段本次保持原有契约，迁移不改变现有API。只读SQLite导入器仅服务离线历史迁移。

执行：使用 `subagent-driven-development` 协作完成基础连接、测试改造和历史导入；主任务负责业务存储、实际切换和整体验证。本次不扩展账号登录、论文功能或完整任务队列。

## 约束

- 开发库固定 `paperassist_system`，测试库固定 `paperassist_system_test`。
- 专用配置使用 `PAPERASSIST_DATABASE_URL`、`PAPERASSIST_TEST_DATABASE_URL`；禁止回退到指向其他项目的全局 `TEST_DATABASE_URL`。
- 测试使用独立 `pa_test_<uuid>` schema和临时文件，不访问开发库或真实API；默认清空模型密钥，需要模型配置的用例显式注入假密钥与模拟响应。
- 主程序不执行DDL；数据库版本不匹配时明确报错，升级通过显式Alembic命令完成。
- 原始Excel、PNG、DOCX继续使用本地资产目录；数据库保存元数据、版本及来源关系。
- 旧SQLite与资产先一致备份，再只读导入；原始ID、JSON快照、关系及文件哈希必须一致。
- 写事务使用schema范围事务锁保持原闭环的串行写入语义，读事务保持一致快照；扩展并发优化另行测试。
- 密码只保存受Git忽略的本地环境文件，日志和文档不包含凭据。

## 执行清单

- [x] PG01：新增 `backend/app/database.py`、`db_schema.py` 及Alembic基线，先验证配置缺失、错误库和不安全schema被拒绝。
- [x] PG02：配置独立非超级用户和专用连接，确认开发/测试目标及Git忽略边界。
- [x] PG03：将 `storage.py`、`explanation_store.py`、`report_store.py` 改为PostgreSQL查询和显式事务，不保留SQLite运行分支。
- [x] PG04：将 `backend/tests/conftest.py` 与原有数据库测试切到真实PostgreSQL独立schema，保留故障、幂等、竞态及两版闭环断言。
- [x] PG05：新增只读离线导入工具，覆盖旧版本拒绝、目标冲突、回滚、幂等、资产验证和源文件不变。
- [x] PG06：备份原目录和SQLite，在空开发库显式建表；导入全部九表并核对数量、值和资产哈希。
- [x] PG07：补充启动配置校验、数据库健康检查、环境示例及实际升级命令。
- [x] PG08：运行后端回归、前端测试/构建及依赖检查；实际读取已迁移项目和下载旧成果。
- [x] PG09：只保留离线SQLite备份/导入路径，统一README与阶段文档当前状态并记录结果。

## 验证命令与证据

环境配置由前缀变量选择，测试fixture额外核对实际 `current_database()` 与schema；下列命令不能使用通用测试URL覆盖保护。

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend\tests
npm.cmd --prefix .\frontend test
npm.cmd --prefix .\frontend run build
.\backend\.venv\Scripts\python.exe -m pip check
```

### 2026-09-29执行结果

- 后端：`python -m pytest backend/tests -q`，**289 passed in 168.67s**；包含真实 PostgreSQL 业务回归、事务、配置边界、启动/健康检查及离线导入。
- 前端：`npm test`，**78 passed**；`npm run build`、`npm run lint` 均通过。`pip check` 无损坏依赖。
- 先观察到测试失败后修复：旧存储未连接 PostgreSQL、启动/健康未检查迁移版本、导入未拒绝错误迁移版本、测试URL参数可覆盖目标；另修复健康检查误依赖资产目录的回归，保留原目录故障契约。
- 独立代码审查发现的三项问题均已复核关闭，`git diff --check` 通过。
- 开发库显式升级至 `0001_postgresql`，九表导入并逐行核对：项目1、文件2、配置1、统计2、图表2、绘图任务2、解释1、解释任务1、报告1；原ID、JSON、外键关系和任务顺序保留。
- 5份资产（2个Excel、2个PNG、1个DOCX）校验一致；实际应用完成两次生命周期/数据库重连、38次GET读取与10次下载哈希校验，数据未改变；重复导入返回 `already_imported`。
- 完整回归结束后，测试库遗留 `pa_test_<uuid32>` schema为0、`public`业务表为0。开发/测试角色各自CONNECT为真、交叉CONNECT为假；均非超级用户且无建库/建角色/复制权限。
- 一致备份位于 `backend/backups/postgres-cutover-20260929T084906Z`；旧运行文件已移到其中 `retired-original.sqlite3`，原SHA256保持一致。`backend/data`不再含SQLite文件，归档后启动及读取正常。
- 备份、导入和实际读取证据分别保存在该备份目录的 `manifest.json`、`postgres-import-result.json`、`postgres-smoke-result.json`；与本地 `.env` 一并确认受Git忽略。

本次实际切换检查关闭云端恢复扫描，未调用真实模型。更广泛的人工浏览器/Word排版验收、自动备份恢复演练及运行/迁移角色进一步分权仍按后续阶段实施，不能由本次数据库回归推断完成。

实现接口参考：[SQLAlchemy连接和事务](https://docs.sqlalchemy.org/en/20/core/connections.html)、[psycopg事务管理](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)、[Alembic按schema迁移说明](https://alembic.sqlalchemy.org/en/latest/cookbook.html#rudimental-schema-level-multi-tenancy-for-postgresql-mysql-other-databases)。具体兼容性以本仓库锁定版本和测试结果为准。

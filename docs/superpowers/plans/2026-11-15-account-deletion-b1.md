# B1 账号删除与失败重试实施记录

**Goal:** 修复并发会话刷新造成的账号删除漏删，以及已有 pending 删除无法重试完成的问题。

**Architecture:** 保留 0080，以 0081 前向迁移替换删除函数。在用户行锁之前按稳定顺序锁定目标会话；pending 收尾按 user_id 幂等清理 sessions 和 session_revocations。项目图遍历、文件清单和跨客户保护规则不变。

**Tech Stack:** Python、PostgreSQL、Alembic、pytest；Windows PowerShell。

## 边界

- 用户只授权 B1；不改 B2/B3，不提交、推送或合并。
- 继续现有干净 feat/frontend-rework，起点 3932384。
- 数据库验证使用既有 tests/conftest.py：必须连接 paperassist_system_test，逐用例创建 pa_test_<uuid> schema，文件放 pytest 临时目录。
- 初轮不升级开发库。后续用户因启动报数据库版本不兼容，明确授权升级本机开发库并进行 Edge 验收；开发库仅迁移及无损检查，账号删除继续使用隔离测试库。

## 执行顺序

- [x] 核对分支和工作区；既有 tests/api/test_account_deletion.py 基线 2 项通过。
- [x] 新增 tests/api/test_account_deletion_sessions.py：在函数捕获 ctid 后设置仅测试库可用的同步点，触发真实 resolve_session；验证删除成功、会话失效，且不相关用户会话不受阻塞。
- [x] 在隔离库复现 pending 遗留 sessions / session_revocations 的失败；补充正常和过期会话已持锁时的并发删除用例。
- [x] 新增 alembic/versions/0081_account_deletion_sessions.py 及 SQL，更新 app/db/database.py 的 SCHEMA_HEAD；保留原 SECURITY DEFINER、固定 search_path、执行权限和删除边界。
- [x] 覆盖 0080 → 0081 升级、已有 pending 保留及恢复、回退后重新升级和运行角色权限。
- [x] 运行下述五个文件的定向验证，25 项通过。
- [x] 独立只读复核未发现明确可行动问题；记录结果及限制，停在 B1 等待用户确认。

## 锁与恢复约定

先检查操作者为有效管理员，再执行 `SELECT ... FROM sessions WHERE user_id = target_id ORDER BY token_hash FOR UPDATE`，随后锁定并验证用户。普通会话读取仍不获取 schema 写锁，避免阻塞不相关用户。

pending 收尾必须先确认删除清单存在，再按用户清理 sessions、session_revocations，最后删除用户；异常沿用事务回滚与原文件清单重试。

## 验证结果

- 基线：原账号删除 API 2 项通过。
- 修复前：新增 4 项均按预期失败。真实 PostgreSQL 复现了 sessions 外键阻止最终删除、session_revocations 外键阻止重试，以及过期会话撤销与删除的死锁。
- 修复后：相同 4 项全部通过；随后补充正常会话已持锁及迁移验证。
- 最终定向结果：**25 passed in 149.82s**。包括删除 API 2 项、删除/会话竞争及旧 pending 恢复 5 项、迁移 2 项、资产边界 8 项、既有会话并发 8 项。
- 验证了其他客户项目保留、分析员代传文件保留、共享引用保留、部分文件删除失败后重试、原删除清单保留、迁移期间记录不变和函数执行权限不扩大。
- 所有数据库用例由 fixture 强制检查目标为 `paperassist_system_test`，使用独立 `pa_test_<uuid>` schema，结束后由 fixture 清除；文件删除仅在 pytest 临时目录执行。
- 使用 Windows PowerShell、本机 Python 3.11 和现有测试依赖。初轮未启动应用服务或进行 Edge 验收；后续启动恢复和浏览器验证见下文。未运行全量回归。

执行命令（工作目录为 backend）：

```powershell
$env:PYTHONUTF8='1'
python -m pytest tests/api/test_account_deletion.py tests/api/test_account_deletion_sessions.py tests/integration/test_account_deletion_migration.py tests/domain/test_account_deletion_assets.py tests/auth/test_session_concurrency.py -q --tb=short
```

## 后续启动恢复与 Edge 验收

用户报告后端启动时 `check_database_ready` 提示版本不兼容，并明确授权更新数据库。经核对，本机开发库 `paperassist_system/public` 仍为 0080，而代码要求 0081。

- 已执行 `python -m app.db.database upgrade` 和 `python -m app.db.database check`，开发库升级为 `0081_account_deletion_sessions`，schema 与运行角色权限检查通过。
- 升级前后及现有账号浏览器检查后，记录数均保持：users=3、projects=5、files=21、reports=1、tasks=21、account_deletions=0。
- 删除函数仍为 `SECURITY DEFINER`，运行角色可执行，PUBLIC 不可执行；0080 文件未修改。
- 用户自行启动前后端并打开 Edge。管理员登录和账号列表读取成功；管理员行只读；客户删除弹窗取消后账号仍保留。
- 客户登录后读取到 2 个已有项目，打开项目资料并刷新后可恢复原项目上下文。
- 分析员登录后读取到 1 个分配项目，打开项目资料、进度和历史客户反馈；本轮所查开发页面控制台未捕获 error。未保存任何业务字段。
- 另起临时后端 18081 与前端 `http://localhost:15173`，使用 `paperassist_system_test` 独立 schema 和系统临时文件目录。合成 1 个待删除客户、1 个保留客户及各自的项目/文件；仅对目标合成文件注入一次 `Path.unlink` 的 `PermissionError`，用于浏览器验证失败后重试。
- 用户在具体删除弹窗确认首次删除和失败重试后，通过 Edge 完成：首次 DELETE 返回 503，显示“本机清理未完成，请重试删除”；关闭弹窗后目标显示停用且仅剩删除操作；刷新页面后再次删除返回 200，显示“账号已永久删除”，列表由 3 条变为 2 条。
- 首次失败后只读断言：目标账号存在但 active=false，pending 清单存在，目标项目已移除、会话为 0、未删文件保留；其他客户的账号、项目、文件记录及文件 SHA256 均保留。
- 重试后只读断言：目标账号、项目、pending 清单、sessions、session_revocations 及残留文件均无；其他客户记录与文件 SHA256 仍保留。
- Edge 验证目标账号再次登录返回 401/“账号或密码错误”；保留客户可登录、打开原项目、查看并下载 `retained-synthetic.xlsx`，下载件 SHA256 与原文件一致。浏览器下载事件等待曾超时，已根据实际生成的本地下载文件及 SHA256 完成验证，未将工具超时记为产品故障。
- 本轮临时服务均正常退出，测试 schema `pa_test_f305d65d73a14c308e4db2d751afc11e` 已删除并只读复核不存在；18081/15173 已关闭，用户启动的 8000/5173 保持运行。开发库上述业务记录数仍不变。

本机证据目录（系统临时目录，未加入 Git）：

`C:\Users\86182\AppData\Local\Temp\paperassist-b1-browser-83d1ab7905c34eb483edebb4f8291ce8`

包含隔离环境脚本、`before.json`、`pending.json`、`after.json`、`download-verification.json`、`cleanup.json`、`final-check.json`，以及 `confirm-delete.jpg`、`failed-delete.jpg`、`retry-success.jpg`、`retained-file.jpg`。失败注入只存在于临时测试进程，未修改应用源码或开发服务。

## 交付边界

源码与本机开发库迁移头均为 `0081_account_deletion_sessions`；生产库未操作。回退至 0080 会恢复旧删除函数及其缺陷。未在真实业务账号上执行删除，未进行云端或生产并发验证。

B1 的本机迁移、启动与 Edge 删除失败重试验收已完成。并发会话和旧 pending 恢复由前述真实隔离 PostgreSQL 定向测试覆盖；浏览器文件失败使用一次性注入，并非真实磁盘故障。未扩展为全量回归，也未验证 B2/B3。

B2/B3 未开始；没有暂存、提交、推送或合并。用户确认 `outputs/` 为与项目无关的测试产物且已自行清理，本批不处理该目录。

# 登录与项目归属实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理员开通账号，用户用邮箱密码登录后只能访问自己的项目及其全部资源。

**Architecture:** PostgreSQL 保存账号、可撤销会话和登录限流记录；Cookie 携带随机会话凭据，数据库只保存摘要。HTTP 项目存储按当前用户过滤，内部恢复任务保持原有运行方式。前端使用统一请求函数和登录边界，在退出或会话失效时卸载整个工作区。

**Tech Stack:** FastAPI、SQLAlchemy Core、Alembic、PostgreSQL、Argon2id、React、TypeScript、pytest、Vitest。

## Global Constraints

- 仅使用项目专用 PostgreSQL 配置；测试只能写入 paperassist_system_test 的独立 pa_test_<uuid32> schema 和临时资产目录。
- 不读取或使用全局 TEST_DATABASE_URL，不执行真实云端生成，不输出密码、连接串或会话凭据。
- 管理员没有其他用户研究内容的读取特权；跨用户资源和未知资源均返回 404。
- 首个管理员邮箱为 admin@paperassist.local；用户已确认历史项目归首个管理员。密码通过本机交互式初始化，不在聊天传递。
- 不公开注册，不接邮件，不增加团队共享、项目编辑/分页或完整管理员网页。账号管理先通过受本机权限保护的 CLI。
- 保留现有项目 ID、文件资产、统计/图表/解释/报告来源链与后台恢复能力。
- 本轮不提交、推送，不执行破坏性数据清理；阶段01的未实现事项继续保持未勾选。

## 共同接口与默认值

`POST /api/v1/auth/login` 接收 `{email, password}`，成功 200，返回 `{user: {id,email,role}, csrf_token}` 并设置 `paperassist_session` Cookie；`GET /api/v1/auth/me` 返回同一结构；`POST /api/v1/auth/logout` 成功 204，撤销服务端会话并清理 Cookie。错误沿用 `{detail:{code,message}}`，不回显输入密码。

Cookie 使用 HttpOnly、SameSite=Lax、Path=/，production 强制 Secure。默认绝对期限 7 天、闲置期限 30 分钟，可通过专用配置缩短；明确过期时重新登录。所有 API 默认要求登录，仅 health 和 login 公开。变更请求发送 `X-PaperAssist-Client: web`，已登录变更请求另外发送 `X-CSRF-Token`；校验 Origin（缺失时允许非浏览器客户端，但自定义标头/CSRF仍必需）及 Sec-Fetch-Site，拒绝跨站请求。开发允许 localhost/127.0.0.1 的 5173、8000 源，测试配置允许 http://testserver；生产必须显式配置受信源，不使用不可信转发头推断源。

Argon2id 使用至少 19MiB、2 次迭代、并行度1；密码 12–128 字符（空白保留，不截断）。邮箱去首尾空白并小写，验证普通 addr@domain 结构，允许 .local。登录错误统一返回账号或密码错误；数据库记录每邮箱 15 分钟内最多 5 次、每直接客户端 IP 最多 30 次失败尝试，超限返回 429 和 Retry-After。账号停用和密码重置使旧会话失效。

后端对外测试/管理服务接口：`app.auth.service.create_user(email, password, role='user', claim_legacy=False)` 返回含 id/email/role 的字典；`bootstrap_admin(email,password)` 仅允许首个账号并事务认领所有 owner_id IS NULL 的历史项目；`reset_password(email,password)`、`set_user_active(email,active)` 撤销旧会话。`app.auth.middleware.AuthMiddleware` 将当前用户放入 `request.state.user`（字典）；`app.auth.routes.router` 提供上述三接口。

`get_project_store()` 仅供内部任务；新增 `get_request_project_store(request)` 只接受已验证的 request.state.user，并构造 `ProjectStore(directory, owner_id=user['id'])`。没有 owner 的历史项目在初始化认领前不通过 HTTP 可见。

## Task 1：认证底座、迁移与本地账号管理

负责文件：新增 `backend/app/auth/`、`backend/app/manage_users.py`、`backend/alembic/versions/0002_auth_ownership.py`、`backend/tests/test_auth.py`；修改 `db_schema.py`、`database.py`（SCHEMA_HEAD）、`main.py`、`requirements.txt`、`.env.example`。

- [x] 先写未登录访问、密码摘要、登录/退出、会话过期/撤销、CSRF、限流、首管理员事务认领测试并确认失败。
- [x] 追加 users、sessions、auth_login_attempts 表和 projects.owner_id 可空外键及索引；不修改冻结的0001；metadata 列顺序与升级后实际表一致。
- [x] 实现共同接口；认证中间件数据库错误沿用安全 StorageError 响应；API 响应禁止缓存，cookie不泄漏到日志。
- [x] 提供 `python -m app.manage_users bootstrap --email admin@paperassist.local` 和 `create --email ...`、`reset-password --email ...`、`disable --email ...`、`enable --email ...`；密码只用 getpass 交互读取两次，拒绝无TTY明文回退，不接受命令行密码。
- [x] `bootstrap_admin` 仅首个管理员创建时认领历史无所有者项目，返回认领项目 ID/数量，重复调用拒绝且不改变归属；普通 create 不认领。
- [x] 在独立测试 schema 跑 `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_auth.py -q`（工作目录 backend 时去掉 backend 前缀），记录 RED/GREEN；依赖安装到本项目 venv 并执行 pip check。

## Task 2：前端登录边界及统一请求

负责文件：`frontend/src/App.tsx`、`App.css`、新增 `auth/` 与 `api.ts` 和测试；现有业务组件仅替换 fetch 为 apiFetch。

- [x] 先写匿名登录、恢复会话、错误/限流、退出、过期、旧响应迟到等 Vitest 测试，确认失败。
- [x] 登录页提供有标签的邮箱/密码表单、自动填充、忙碌反馈，显示“账号由管理员创建”；无注册和邮件恢复按钮。
- [x] `apiFetch` 使用同源 Cookie；CSRF token 仅保存在内存，变更请求附共同接口标头。请求归属会话代数，旧会话迟到的401不得踢掉新会话，旧响应不得回填工作区。
- [x] 初始 me 恢复完成后才挂载工作区；401 清空会话并显示登录提示；网络/503 错误提供重试。主动退出成功后清理 hash 和工作区状态；退出失败不得虚报已撤销服务端会话。
- [x] 替换业务组件 fetch，保持原业务交互；下载链接/图片仍由后端 Cookie 校验。核对退出后用户资料不会通过迟到响应闪现。
- [x] 执行 `npm test -- --run`、`npm run build`、`npm run lint`，记录结果。

## Task 3：项目存储与所有资源权限

负责文件：`backend/app/storage.py`、`projects.py`、`analysis.py`；新增 `backend/tests/test_project_ownership.py`。

- [x] 写两个普通账号和管理员的列表/创建/猜测ID测试，先观察失败。
- [x] 项目列表按 owner_id 过滤；项目详情使用 id+owner_id；创建明确列名写当前用户，忽略客户端自报 owner；HTTP 依赖无登录时拒绝，禁止调用无作用域存储。
- [x] 审计文件、配置、统计、图表、解释、报告及下载路由都先校验项目→文件→结果来源；内部 worker 继续从系统存储恢复任务。
- [x] 两用户分别创建 sci/thesis，验证他人 GET/POST/PUT 和全部下载返回404，历史 NULL 项目不可见，管理员不能绕过。

## Task 4：既有回归、实际迁移与交付记录

负责文件：既有 `backend/tests/` 的认证fixture及跨进程读取；README、阶段01、路线、决策台账、登录交付记录。

- [x] 旧业务测试通过真实测试账号登录，跨进程传测试会话；不关闭认证/CSRF，不改掉原有业务断言。裸连接项目 INSERT 改为显式列名。
- [x] 开发库变更前保存 PostgreSQL 备份、九表快照与5份资产 SHA256；确认没有应用写入，显式升级到新 HEAD；复查所有业务值/资产不变。
- [x] 用户已反馈通过本机初始化设置密码；2026-09-30只读确认 admin@paperassist.local 已启用、角色为管理员，原1个历史项目已归该账号，无主项目为0；未读取或验证密码，映射证据见交付记录。
- [x] 后端全量 pytest、前端测试/build/lint、pip check、git diff --check；审查权限矩阵、凭据泄漏、Cookie/CSRF、会话竞态与现有闭环。
- [x] 更新 PaperQA 接收总数8、历史归属/管理员权限决定、已验收勾选项和本机初始化操作；独立代码审查修复后交付。

参考依据：[OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)、[Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)、[CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)。

## 最终执行记录

2026-09-30：后端313项、前端96项通过；build/lint/pip check通过；独立审查发现的P1认证竞态已修复并复审通过。开发库已备份并升级0002，迁移时九表原值与5份资产不变。两轮浏览器验收仅使用专用测试schema。用户随后反馈本机密码已设置，只读核对确认管理员已启用、原1个历史项目已认领；用户登录后人工核对历史资料仍待反馈。详细证据见[交付记录](登录与项目归属交付记录.md)。后续文档整理未重跑上述功能回归；未提交或推送。

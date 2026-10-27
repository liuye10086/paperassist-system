# PaperAssist System

截至2026-10-27，阶段10第四批已通过用户验收，按当前非付费本机内测范围阶段性收尾：**63/92，剩29项**。验收服务已停止；QA11性能门槛未过、DOCX/PDF池2对照缺证及真实材料/完整双语/许可等边界继续保留，不代表生产发布。见[阶段10收尾记录](docs/开发记录/阶段10/2026-10-27-第四批验收与阶段收尾记录.md)与[内测支持范围](docs/运行维护/内测支持范围与已知限制.md)。

阶段10及正式前端六批改造已合入 `main`；本次整理基线为 `9b02a262cae37adb29ee9c0412047b0fc8c08b14`，原功能分支已删除。历史记录中的分支、迁移、服务和“未提交”均按原日期理解。

本次源码、样式、旧原型和入口文档的清理范围与定向验证见[main项目清理记录](docs/开发记录/项目维护/2026-10-27-main项目清理记录.md)。

面向生物医学、药学科研场景的科研论文辅助系统。

## 当前进度

- 前端：React + TypeScript + Vite
- 后端：Python + FastAPI
- 健康检查接口：GET /api/v1/health
- 前端页面可展示后端连接状态
- 界面支持简体中文与英语；登录后恢复并保存账号语言偏好，匿名切换仅保存在内存
- 项目默认输出语言独立保存；各类输出按具体任务合同选择语言，历史成果、用户内容和已提交任务保持原文
- 网页支持`.xlsx`、标准未加密`.docx`、未加密`.pdf`及静态`.png/.jpg/.jpeg`混合批量上传；每文件10 MiB、每批10项、同时上传2项，由Linux Worker受限独立进程解析，旧Excel单文件入口保留兼容
- Word输入文件提供正文/表格/图片/显式样式和来源预览、不可变版本、重新解析及原件/JSON/图片下载；不还原分页、不做OCR或直接统计Word表格
- PDF输入最多100页，提供文字/有边框表格候选、物理页与区域来源、不可变版本、按页预览和下载；另可选择1—10页作本地OCR，不覆盖文本版本
- PNG/JPEG上传自动识别，支持重新识别、原图与文字框核对；原OCR始终保留待核对状态。第9步新增逐块人工决定、进度保存和独立核对历史，已通过用户验收，不直接统计或自动确认
- 切换工作表，查看列名、数据行列数与前 20 行
- 无效格式、零字节文件、损坏文件、空工作表和超限反馈
- 上传大小和解析规模可配置；保留现有 Vite `/api` 代理
- 新建项目，填写名称、研究主题，选择 SCI 科研论文或毕业论文
- 编辑自己项目的名称和研究主题，支持保存、取消、失败保留草稿与超时重新读取；创建时必须明确选择类型，创建后类型固定，编辑不清空当前文件预览
- 项目列表展示名称、类型、创建/更新时间和文件数，固定每页5个项目，支持名称搜索与类型筛选；已打开工作区独立于当前页，翻页/筛选保留草稿和预览，项目失权后清理旧内容并提供恢复入口
- 按项目保存原始 Excel、上传时间、大小、SHA256、解析状态和有限预览
- 文件历史列表每页5项，详情支持多用途编辑、引用计数与内测保留说明；翻页保留当前预览，分析选择保留全部Excel文件，刷新页面或重启后端后可重新预览和下载原文件
- 同名上传生成独立记录，不覆盖旧文件；解析失败保留原文件和原因
- 原始结构可指定表头和数据区域，确认字段名/单位，预览去除文本首尾空白与指定文本转缺失；确认后发布新整理版本，保留原件与历史版本
- 选择“描述统计＋箱线图”、原始或整理数据版本、工作表、数值列和可选分组列，查看对应版本字段类型和缺失情况
- 第10步字段概况已通过用户验收：按明确原始/整理版本完整扫描，展示数值、分类、四类时间及缺失/异常候选/重复位置，20条分页核对真实Excel坐标；纯本地只读，不自动清洗
- 检查可用记录与分组数量，保存分析配置；刷新或重启后选择同一文件可恢复配置
- 按保存的配置执行真实描述统计，显示总体/分组结果，并保存来源、计算口径和版本；刷新或重启后恢复结果
- 第三步已接入 OpenAI 官方 Responses API + Code Interpreter：云端运行 Python 计算并生成箱线图，本地核对后保存 PNG、图注与来源；真实 API 联调和图像视觉验收情况见下方验证记录
- 第四步调用 OpenAI 官方 Responses API，根据已保存的统计汇总与图表元数据生成六部分中文解释；程序填入事实引用并保存证据和版本，刷新/重启后恢复，内容仍需人工审核
- 第五步将同一配置版本的数据检查、真实统计、原始 PNG、图注、解释和依据导出为可编辑 `.docx`；本地生成，不额外调用 API；报告持久化，支持重复下载和刷新/重启恢复
- 已接入有限相关/组间/配对/建模方法、图表工作台与报告集合、文献检索和引用核验、SCI/毕业论文稿件、学校模板/期刊指南及多轮评审；实际支持条件见[内测支持范围](docs/运行维护/内测支持范围与已知限制.md)。
- 运营入口提供账号、任务安全投影、用量/日志、配置版本、存储治理与运行状态；管理员研究内容权限仍按账号归属控制。

应用与集成测试统一使用 PostgreSQL，磁盘保存原文件与派生成果。SQLite仅作为旧schema 6数据的离线导入来源；SQLAlchemy Core + psycopg + Alembic承接数据库访问，显式迁移，启动和健康检查只核对版本。异步任务复用Celery/RabbitMQ、统一模型调用与三级预算；各阶段完整条目、决定和未验证范围见[开发路线](docs/开发阶段/00-开发路线与使用说明.md)与[文档索引](docs/README.md)。

## 后续开发文档

后续按模块分阶段推进，每阶段遵循“数据库 → 后端 → 前端 → 验收”，使用带编号的勾选框记录功能进度：

- [文档导航与存放规则](docs/README.md)
- [开发路线与阶段导航](docs/开发阶段/00-开发路线与使用说明.md)
- [开发前准备与测试边界](docs/开发阶段/阶段00-开发准备与边界确认.md)
- [参考项目接收与复用清单](docs/开发记录/项目管理/参考项目接收与复用清单.md)
- [需求覆盖与决策台账](docs/开发记录/项目管理/需求覆盖与决策台账.md)

本机 PostgreSQL 开发库为 `paperassist_system`，测试库为 `paperassist_system_test`。owner `paperassist_app`、`paperassist_test` 保留为迁移角色；应用分别使用 `paperassist_runtime`、`paperassist_test_runtime`。运行角色仅有业务DML、序列USAGE/SELECT和版本表SELECT，无owner、DDL、TEMP、TRUNCATE、TRIGGER及版本表写权限，且不能连接另一项目数据库；迁移角色仍非超级用户且无CREATEDB/CREATEROLE。应用使用项目专用连接变量，拒绝缺失或不匹配的配置；不读取通用 `DATABASE_URL` 或 `TEST_DATABASE_URL`，后者在本机属于其他项目。源码迁移头为 `0053_storage_governance`；每个实际环境通过下述 `check` 命令核对，历史升级和保留证据见[阶段10收尾记录](docs/开发记录/阶段10/2026-10-27-第四批验收与阶段收尾记录.md)及[分权交付记录](docs/开发记录/阶段01/迁移核查与运行账号分权交付记录.md)。

## 项目目录

正式前端采用 Arviva 浅灰绿色背景、白色工作区与深绿主色，已完成六批任务分层改造。工作台、项目任务分组及独立列表/详情/视图保留原业务状态、深链和草稿；设计规则见[DESIGN.md](DESIGN.md)、[正式六批方案](docs/设计/前端UI/2026-10-25-正式前端分批改造方案.md)与[保留的Arviva交互原型](docs/设计/前端UI/preview-arviva/index.html)。2026-10-07紫色旧原型已退役，其独立设计和交付记录继续保留。

详细目录树、职责和旧新路径映射见[项目结构](docs/项目结构.md)。

| 目录 | 职责 |
| --- | --- |
| `backend/app/api/` | HTTP 路由、依赖与请求限制 |
| `backend/app/domain/` | 分析计算、业务规则、成果与任务处理 |
| `backend/app/adapters/` | 数据持久化、Excel、OpenAI 和 Word 适配 |
| `backend/app/auth/` | 认证、会话、密码和撤销审计 |
| `backend/app/core/`、`db/` | 公共配置/错误/路径、数据库连接/权限/表结构 |
| `backend/app/maintenance/` | 离线导入、审计、核验报告与恢复演练 |
| `backend/app/workers/`、`infra/worker/`、`compose.workers.yml` | Celery执行、outbox分发、租约扫描及本机Linux容器 |
| `backend/alembic/`、`backend/scripts/` | 数据库 revision 与维护 CLI 入口 |
| `backend/tests/` | 按职责归组的回归测试与共享 fixture |
| `frontend/src/app/` | 应用组合和样式 |
| `frontend/src/features/` | 项目、文件/数据集、分析/成果、文献、稿件、学校模板、期刊、评审、任务和运营页面；具体模块见[项目结构](docs/项目结构.md) |
| `frontend/src/shared/` | 请求客户端、受控下载、语言与词典 |
| `frontend/src/test/` | 集成测试与合成夹具；组件单测与功能同目录 |
| `script/` | `dev.cmd`、`setup-database-roles.cmd`、`test-queue.cmd`；实现位于 `dev/`、`database/`，部署/回退入口位于 `release/`，测试位于 `tests/` |
| `compose.release.yml`、`infra/api/` | 本机内测独立部署、静态网页/API、维护与回退；使用[部署手册](docs/运行维护/本地内测部署与回退手册.md) |
| `docs/` | [文档导航](docs/README.md)、需求/方案、阶段清单及交付记录 |

应用启动入口仍为 `backend/app/main.py`；账号管理仍为 `backend/app/manage_users.py`，累计预算管理入口为 `backend/app/manage_model_budgets.py`，实际费用核对入口为 `backend/app/manage_model_reconciliation.py`；前端入口仍为 `frontend/src/main.tsx`。`backend/data/`、`backend/backups/`、`script/.runtime/` 和 `reference-projects/` 是 Git 忽略的本地资料，保持原位置。

## 本地运行

以下步骤适用于 Windows PowerShell，所有命令均从项目根目录（包含 `backend`、`frontend` 和本 README 的目录）执行。若终端已经在该目录，无需再次切换目录。
推荐使用 `script/dev.cmd` 统一管理前后端及队列服务；手动分别启动前后端只用于调试，执行新绘图、解释或Word任务还需要Worker栈。
后端命令直接调用虚拟环境内的 Python，无需先激活环境；前端使用 `npm.cmd`。

### 后端

在项目根目录执行。首次运行时创建虚拟环境：

```powershell
python -m venv .\backend\.venv
```

首次运行或 `backend/requirements.txt` 变更后安装依赖：

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
```

首次运行还需配置专用 PostgreSQL 连接。已有 `backend/.env` 时保留原内容；按 `backend/.env.example` 填写 `PAPERASSIST_ENV=development`、`PAPERASSIST_DATABASE_URL`、`PAPERASSIST_TEST_DATABASE_URL` 和 `PAPERASSIST_DB_SCHEMA=public`。本机已配置的 `.env` 不应被示例覆盖。密码仅存放在本地受 Git 忽略的文件中，连接串内的特殊字符需 URL 编码。

运行与迁移配置分开：运行账号为 `paperassist_runtime`、`paperassist_test_runtime`；原 owner `paperassist_app`、`paperassist_test` 作为迁移账号。新环境按照 `backend/.env.migrations.example` 单独填写 Git 忽略的 `backend/.env.migrations`，应用正常配置不会加载它，迁移连接缺失时不会回退运行账号。本机已完成[初始化与分权](script/README.md#数据库运行账号初始化第6项①)，无需重复初始化；新部署应对应用与迁移进程分别提供秘密。历史初始化、导入恢复和验收证据保留在[阶段01记录](docs/开发记录/阶段01/)。

首次部署或数据库迁移版本变化时，在 `backend` 目录显式执行；完成后回到项目根目录启动服务：

```powershell
Push-Location .\backend
try {
  .\.venv\Scripts\python.exe -m app.db.database upgrade
  if ($LASTEXITCODE -ne 0) { throw '数据库迁移失败' }
  .\.venv\Scripts\python.exe -m app.db.database check
  if ($LASTEXITCODE -ne 0) { throw '数据库版本检查失败' }
  .\.venv\Scripts\python.exe -m app.maintenance.database_audit
  if ($LASTEXITCODE -ne 0) { throw '数据库结构或数据格式核查失败' }
} finally {
  Pop-Location
}
```

`upgrade` 只迁移已存在的指定 schema；它不创建数据库或账号。旧 SQLite 数据需按[离线迁移流程](docs/开发记录/阶段01/PostgreSQL统一与迁移记录.md)导入，启动应用不会自动读取或迁移旧库。

显式迁移在 DDL 前向 stderr 输出环境、主机/端口、数据库、schema、迁移用户名、当前及目标版本，不输出密码或连接参数。每次迁移结束按 metadata 表名单重新授权业务 DML 和 sequence USAGE/SELECT，版本表只有 SELECT；不用全表默认 DML 授权。`check` 额外核查真实运行角色权限；`database_audit` 只读核对结构、索引、JSON、时间及成果来源链，输出汇总，不打印业务字段值。JSON/TEXT 时间及认证浮点秒保留原格式，审计不能代替数据库 JSON/时间 CHECK 或未来的数据类型迁移。

日常启动（已完成依赖、专用连接配置和迁移时）：

Windows 本机验收在项目根目录使用统一脚本，启动前后端及RabbitMQ、Worker、dispatcher并检查健康状态。需要已安装Docker Desktop并使用Linux容器；启动器可启动Docker Desktop，首次需构建镜像。配置及版本见[Worker说明](infra/worker/README.md)：

```powershell
.\script\dev.cmd start
.\script\dev.cmd status
.\script\dev.cmd stop
```

启动后打开 <http://127.0.0.1:5173>。验收完成后再停止；停止处理经身份核对的前后端及子进程、本项目三个容器，保留broker数据卷，不关闭全局Docker Desktop或PostgreSQL。使用说明见 [script/README.md](script/README.md)。用户反馈验收完成后先停止服务并更新文档，只有获得明确授权与提交信息才提交推送。以下为分别手动启动的命令：

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

健康检查：http://127.0.0.1:8000/api/v1/health

本机直连启动必须保留 `--no-proxy-headers`，使登录及密码操作按真实连接IP限流，忽略客户端伪造的 `X-Forwarded-For`。未来接入反向代理时需另行配置可信代理边界，不能直接启用任意代理头。

启动和健康检查都会检查 PostgreSQL 连通性及 Alembic 版本。缺少配置、数据库不可用或版本未迁移时会失败，不创建 SQLite，也不自动执行 DDL。

接口文档：http://127.0.0.1:8000/docs

### 首个管理员与登录

本机首个管理员与历史项目归属已完成初始化，无需再次执行。历史迁移与保留证据见[登录与项目归属交付记录](docs/开发记录/阶段01/登录与项目归属交付记录.md)及[双语交付记录](docs/开发记录/阶段01/双语界面与语言设置交付记录.md)。**以下命令仅供新环境首次初始化参考**：

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.manage_users bootstrap --email admin@paperassist.local
```

新环境初始化时按提示输入两次12–128字符密码（`getpass` 隐藏输入）；命令在同一事务创建首个管理员并认领历史项目。已有账号时再次执行会拒绝。账号管理同样使用 `app.manage_users` 的 `create`、`reset-password`、`disable`、`enable` 命令和 `--email`；密码重置或停用会使旧会话失效。管理员网页已接入账号运营管理；公开注册与邮件恢复继续保留条件边界，用户可自行改密或使用管理员签发的恢复码。

接口为 `/api/v1/auth/login`、`/api/v1/auth/me`、`/api/v1/auth/logout`。会话令牌只保存摘要，Cookie 使用 HttpOnly、SameSite=Lax，生产环境启用 Secure；绝对有效期 7 天、闲置期 30 分钟，状态修改请求检查 CSRF 与来源。15 分钟内失败限制为每邮箱 5 次、每 IP 30 次。管理员仅能读取自己名下研究内容，嵌套资源、写入与下载均核对项目归属，越权返回 404。

登录、会话、项目归属与迁移的历史测试结果见[登录与项目归属交付记录](docs/开发记录/阶段01/登录与项目归属交付记录.md)，不将原测试计数当作当前代码的回归结果。

### 修改密码与密码恢复

登录后点击“修改密码”，输入当前密码、新密码和确认新密码。密码仍为12–128个字符；成功后所有旧会话失效，需要重新登录。

忘记密码时联系管理员线下核验身份。管理员在交互式终端、`backend` 目录执行：

```powershell
.\.venv\Scripts\python.exe -m app.manage_users issue-recovery --email user@example.local
```

将示例邮箱替换为已核验账号，按提示输入 `YES`；恢复码只在当前终端显示一次，15分钟有效。管理员通过已核验的联系渠道交给账号持有人，用户在登录页点击“忘记密码”，输入恢复码并设置新密码。恢复码不要放入URL、聊天记录或日志；命令拒绝非交互环境及输出重定向，不接入邮件服务。

恢复码只存摘要，成功使用一次后失效；重新签发、改密、本机密码重置及账号停用/启用会使待用恢复码失效。改密及恢复成功均撤销该用户全部旧会话，并保留撤销原因和时间。15分钟内密码操作失败限制为每账号/恢复码5次、每直接客户端IP30次；超限返回429。请求超时不代表密码未变，请按页面提示重新登录或联系管理员。

`POST /api/v1/auth/change-password` 接收 `current_password/new_password`，需要登录和CSRF；`POST /api/v1/auth/reset-password` 接收 `recovery_code/new_password`，允许匿名但仍检查安全标头和来源。成功返回204并清除会话Cookie；错误不回显输入凭据。真实密码由用户自行输入，开发验证只使用隔离测试账号。

### 前端

在项目根目录新开一个终端。首次运行或前端依赖锁文件变更后安装依赖：

```powershell
npm.cmd --prefix .\frontend ci
```

日常启动：

```powershell
npm.cmd --prefix .\frontend run dev
```

页面地址：http://127.0.0.1:5173

前端开发服务器将 /api 请求转发到本地后端。

### 停止服务

统一启动的服务使用 `.\script\dev.cmd stop` 并以 `status` 复核。手动运行的前后端在对应终端按 Ctrl+C；若另行启动Worker栈，还需运行 `.\backend\.venv\Scripts\python.exe script/dev/worker_stack.py stop`，仅关闭终端不会停止容器。

### 虚拟环境创建被中断

如果 `python -m venv .\backend\.venv` 在 `ensurepip` 阶段出现 `KeyboardInterrupt`，说明创建过程收到了中断（通常是按了 Ctrl+C），不是项目根目录路径写错。此时 `.venv` 可能只创建了一部分，不能仅凭目录存在判断创建成功。

先在项目根目录检查：

```powershell
.\backend\.venv\Scripts\python.exe -m pip --version
```

若能显示 pip 版本及位于 `backend\.venv` 内的路径，可以继续安装后端依赖并启动。若提示找不到 Python 或 `No module named pip`，重新执行创建命令并等待正常结束，再检查 pip：

```powershell
python -m venv .\backend\.venv
.\backend\.venv\Scripts\python.exe -m pip --version
```

本文直接使用 `.venv` 内的 `python.exe`，无需运行 `activate`，提示符没有出现 `(.venv)` 也不影响这些命令。若需要手动激活，PowerShell 对应的脚本是 `.\backend\.venv\Scripts\Activate.ps1`；创建中断时该脚本可能尚未生成。

## 下一步

阶段10按63/92阶段性收尾，剩余29项和性能/真实材料/发布缺口见[收尾记录](docs/开发记录/阶段10/2026-10-27-第四批验收与阶段收尾记录.md)。后续工作由用户另行选择范围；真实或付费调用、提交推送和实际发布仍按各自明确授权执行。

## 模型调用与预算

项目概览及任务详情的“模型调用与预算”面板只读显示累计美元额度、原内部估算、预算已计金额、预留、可用额度和实际核对分项/状态，支持刷新与分页。未核对金额保持未知，明确零金额须有凭证；界面无预算或核对编辑入口。本机管理员预算命令见[预算管理说明](script/README.md#本机模型预算管理)，实际费用的show/preview/apply及原件要求见[核对使用说明](docs/开发记录/阶段02/实际用量核对使用说明.md)。

`ModelUsageService`、统一文字 Responses 门面和绘图工具门面已交付，调用前必须满足用户、项目、任务三级预算及受信价格策略；缺少预算或价格时拒绝发送。预算按累计 USD 计算，不自动按日/月重置，没有自动默认额度或价格。未知提交保留预留且不自动重发；有已知响应时只续取。绘图还需明确工具费用预留，缺少实际费用证据时保持待核对。原内部估算与实际核对金额分别保存，预算按已计金额和预留控制；这不是收费账本，也不承诺远端账单绝对不超限。

此面板仅统计经新统一门面的调用。项目任务详情另显示任务、项目和用户三级预算，并关联本任务已保存的精确历史成果。新绘图和解释可在预算或配置补足后显式恢复原任务，已有调用沿用保存结果，尚未提交的模型调用按原策略和预算执行。旧绘图和旧解释不补造统一历史账本；实际费用核对由本机管理员CLI执行，网页只读；旧绘图/解释只读映射已通过用户验收。本机项目“测试”已配置 `gpt-5.6-sol` 私有策略，所属用户和项目累计额度各5美元，单绘图任务1美元、单解释任务0.5美元；这些是获授权的测试配置，不是默认值，本轮收尾未调整。配置与历史真实调用证据见[第五步交付记录](docs/开发记录/阶段02/绘图任务迁移交付记录.md)，等待和恢复范围见[第六步交付记录](docs/开发记录/阶段02/任务界面与等待恢复交付记录.md)。

## 界面语言与项目默认输出语言

页面可切换简体中文和英语。匿名选择仅保存在当前页面内存；登录后读取账号偏好，保存成功后在刷新和重新登录时恢复。账号语言与项目默认输出语言分别保存，失败或超时按页面提示重新读取确认。保存语言不重新建立会话，也不重发业务生成请求。

项目默认输出语言与账号界面语言独立；具体输出语言和已支持的文档类型由各任务合同决定，见[内测支持范围](docs/运行维护/内测支持范围与已知限制.md)。用户名称、研究主题、文件名、工作表/字段/组名、历史成果正文及已提交任务快照保持原文。

## 使用与数据规则

1. 完成本机账号初始化后启动前后端，打开 http://127.0.0.1:5173，使用邮箱密码登录，确认进入工作台并显示项目列表或正常空态。
2. 新建项目：填写项目名称（1–120 字符）、研究主题（1–500 字符），明确选择项目类型；或在项目列表搜索/筛选后点击“打开项目”。列表固定每页5项，居中显示页数与翻页按钮，翻页/筛选保留当前工作区。已有项目可通过“编辑项目信息”修改名称/主题并保存或取消，类型创建后不可更改。
3. 选择 `.xlsx`，点击“上传并预览”。上传期间禁用重复提交，保存后文件出现在当前项目的文件列表。
4. 后端返回全部数据工作表的有限预览，默认展示第一张；通过“工作表”下拉框切换，无需再次上传。
5. 刷新页面后，地址中的项目 ID 会恢复当前项目和文件列表；点击文件的“预览”重新打开，点击“下载原文件”取得上传时的原始字节。
6. 重启前后端后，使用相同的 PostgreSQL 开发库、schema 和资产目录即可继续查看项目。切换项目会清除旧预览并取消旧页面请求。

- **同名文件**：每次上传生成独立 ID；名称只用于展示，不用于磁盘路径，不覆盖旧文件。
- **失败记录**：扩展名不支持、零字节或超过上传大小限制直接拒绝，不产生记录；通过基本校验但解析失败的 `.xlsx` 保存原文件和失败原因，可以下载，不能预览。
- **超时**：取消浏览器请求不保证后端停止处理。遇到上传或创建超时，应先刷新列表确认结果，避免重复提交。
- **项目编辑**：保存只提交本次改变的字段；15秒超时后先重新读取项目核对服务端结果。同一项目多标签编辑按最后成功提交覆盖，暂无冲突合并。历史Word保留生成时的项目快照，同一成果重复导出复用原报告；尚未生成的报告使用首次导出时的项目资料。

- **表头**：固定使用 Excel 第 1 行；空表头显示“未命名列 A/B/…”并提示；重复列名按原始顺序保留并提示，不合并字段。
- **数据行数**：从第 2 行到最后一个有值的行，不含表头，包含中间空行，忽略尾部空白及仅格式行。全空工作表返回 0 行、0 列；只有表头返回 0 数据行及相应列数。
- **列数**：从 A 列到最后一个有值的列，包含内部空列，忽略末尾仅格式列。扫描限制仍计算格式单元格的原始坐标。
- **预览**：最多显示前 20 个数据行，不跳过内部空行；左侧显示原始 Excel 行号。空值显示 `—`，数值 `0`、布尔 `FALSE` 不会被当作空值。
- **原始内容**：日期和时间转为 ISO 字符串；公式展示原文并提示未计算；合并单元格保留实际值，不自动补全。预览不还原 Excel 数字格式、颜色和合并布局。隐藏工作表仍可选择并有提示。

以下五步保留既有Excel→描述统计→箱线图→解释→Word兼容链路的操作与配置说明；该链路的局部能力边界不代表全项目范围，完整当前能力见[内测支持范围](docs/运行维护/内测支持范围与已知限制.md)。

## 第一步：选择分析任务与字段

先按上方命令安装更新后的 `backend/requirements.txt` 并显式迁移 PostgreSQL。当前版本为 Alembic `0012_task_errors`；旧 SQLite schema 1–5 自动升级至 schema 6 的说明属于历史实现，已被 PostgreSQL 统一方案替代。离线导入工具只接受 schema 6；更早的库需使用匹配的旧程序升级独立副本，不能让当前应用回退到 SQLite。

1. 进入已有项目，选择侧栏“数据分析”，在“字段配置”选择数据。上传与原文件预览位于侧栏“项目文件”。
2. 分析任务目前固定为“描述统计＋箱线图”；选择一份已保存且解析成功的 Excel。
3. 选择“分析工作表”。后端读取完整工作表，展示每列类型、非缺失数、缺失数及实际数值数量，不只检查前 20 行。
4. 选择一个数值列，以及可选的分组列；可填写单位。列使用 `A · 字段名` 的形式展示，区分重复列名。单位只是结果展示所用的说明，不执行单位换算。
5. 点击“检查字段”，查看可用行数、排除行数、每组记录数和提示；检查通过后点击“保存分析配置”。保存时后端再次验证原文件与所选字段。
6. 刷新页面或重启后端后，进入原项目并重新选择同一文件，自动载入保存的工作表、字段和单位。修改选择后需要重新检查再保存。

本步的规则：

- **数值列**：仅接受实际存储为有限整数/浮点数的非缺失值。`0` 是有效数值；布尔、日期、文本数字、公式及 Excel 错误不自动转换或丢弃，混合类型不能作为数值列。
- **缺失值**：空单元格、空字符串、纯空白字符串算缺失；`NA`、`NULL` 等文本不自动解释为缺失。统计行数仍沿用预览规则，包含内部空行。
- **分组列**：接受单一文本、数值或布尔类型。标签保留原文；数值编码可以作为分类标签。最多 20 个有效分组，超过上限需重新选列；分组数按有效数值与分组配对后的记录计算。
- **有效记录**：不分组时使用数值非缺失的行；分组时要求数值和分组均非缺失，规则固定为 `exclude_selected_missing`。没有有效记录时不能保存；不足 2 条的组给出提示，供后续统计处理。
- **配置保存**：每个文件保存一份当前配置，保存新的工作表或字段会更新旧配置。记录来源 SHA256、任务、工作表、列位置、单位、缺失规则、检查摘要、更新时间和修订号；本轮不保存多套历史配置。
- **同时编辑**：保存携带 `expected_revision`，其他页面已更新时返回冲突；点击“重新载入分析配置”后重新选择并保存。这个按钮会放弃当前尚未保存的表单修改。
- **检查范围**：提供支持本次分析所需的字段和完整记录检查，尚未实现自动清洗、去重、离群值判断、任意类型转换或复杂数据治理。

## 第二步：执行真实描述统计

1. 在“字段配置”检查并保存后，切换流程导航“描述统计”，点击“执行描述统计”。仅载入文件或切换流程不会自动执行。
2. 后端重新读取原始 Excel，按已保存的配置和完整记录规则进行真实计算；总体及各分组使用同一批有效记录。
3. 查看总体和分组统计表，以及有效/排除行数、所用字段、单位和计算时间。“计算来源与方法记录”展示文件名与时间，不渲染系统编号、哈希和工具版本。
4. 刷新或重启后，重新选择同一文件会自动读取已保存的结果。重复执行同一配置/工具版本返回同一结果，不重复创建记录。
5. 修改字段或单位后，须重新检查、保存，再执行。旧结果会标注为旧配置结果，并显示其自身的字段和单位；新结果保存后页面展示新结果，数据库继续保留旧结果。其他页面已修改配置时，点击“重新载入分析配置”再继续。
6. 网络失败或请求超时时，先点击“重新读取统计结果”确认后端是否已经保存，再决定是否重试。

计算口径：

| 指标 | 定义 |
| --- | --- |
| 样本数 `n` | 所选字段满足完整记录规则的行数，不自动去重 |
| 均值 `mean` | 算术平均值 |
| 样本标准差 `std` | 使用 `n−1` 分母；`n=1` 时返回 `null`，页面显示 `—` 并提示 |
| 最小/最大值 `min` / `max` | 有效记录的最小/最大值 |
| `Q1` / 中位数 / `Q3` | 排序后从 0 开始的位置 `(n−1)p` 线性插值，`p=0.25/0.5/0.75`；单条记录均取该值 |
| 四分位距 `iqr` | `Q3−Q1`，在分位数转成输出浮点数前计算，避免先舍入再相减造成失真 |

本地描述统计采用 Python 标准库 `statistics` 和 `fractions`，无需 pandas/SciPy 依赖。方法参考：[Python 3.11 statistics 官方文档](https://docs.python.org/3.11/library/statistics.html)。工具标识固定为 `descriptive_statistics_v1`，结果同时保存 Python、openpyxl 版本及开始/完成时间。分组按有效记录中首次出现的顺序展示。

数值及边界：

- 表格最多显示 6 位有效数字，鼠标悬停查看保存值；保存结果不按显示位数预先舍入。计算结果使用有限双精度数值，不承诺任意精度小数。IQR 在分位数最终舍入前计算，因此用已显示或已舍入的 Q3、Q1 手动相减可能与保存的 IQR 不同。
- 原文件数值列中存储为整数且超出 `±9007199254740991` 的值，在执行时返回 `422 numeric_precision`，提示具体单元格，不保存错误结果。这类文件仍可预览、检查和保存配置；需要核对数据或调整单位后重新上传。已在 Excel 中丢失的精度不能由系统恢复。
- 有效样本不足 2 条时标准差无法计算；标准差或四分位距超出输出数值范围时，对应指标返回 `null` 并解释，不输出 `NaN`/`Infinity` 或伪造为零。其他可计算指标仍保留。
- 不自动插补、去重、剔除离群值，也不执行单位换算；本步不做显著性检验、P 值或置信区间。
- 结果表按文件、配置修订号、工具版本唯一保存，写入时再次核对配置版本，防止执行中途修改配置后错配。失败不会覆盖之前的结果。页面目前只展示最新保存结果，完整历史结果选择和导出尚未实现。

## 第三步：OpenAI Code Interpreter 箱线图

本步通过官方 Python SDK 调用 **Responses API + Code Interpreter**。模型在 OpenAI 容器中运行 Python，读取所选有效数据、计算统计量并生成 `boxplot.png` 和 `result.json`。图片直接来自云端，本地只核验和保存。与直接生成图片的 GPT Image 接口不同；后者按用户要求留到后续独立接入。[Code Interpreter 官方说明](https://developers.openai.com/api/docs/guides/tools-code-interpreter)

### 配置与运行

在项目根目录 PowerShell 执行，已有 `.env` 时保留它：

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
if (-not (Test-Path .\backend\.env)) { Copy-Item .\backend\.env.example .\backend\.env }
notepad .\backend\.env
```

管理员参考 [plot-policy.example.json](backend/plot-policy.example.json) 创建 Git 忽略的 `backend/.env.plot-policy.json`，填写已核验的模型、价格快照、输入估算额度、输出上限、任务额度，以及显式工具费用预留和依据版本。在 `backend/.env` 设置策略路径和密钥：

```dotenv
OPENAI_API_KEY=在本机填写你的API密钥
PAPERASSIST_PLOT_POLICY_FILE=.env.plot-policy.json
```

也可通过 `OPENAI_API_KEY_FILE` 指定密钥文件。新绘图使用独立策略中的模型，不从旧 `OPENAI_MODEL` 推导价格或预算。模型须支持 Responses、后台执行及 Code Interpreter；模板的必填金额为 `null`，不能直接启用。用户和项目累计预算还需通过[管理员命令](script/README.md#本机模型预算管理)明确设置；只有任务策略不足以准入。

后端读取 `backend/.env`，PowerShell 环境变量优先；文件已被 Git 忽略。API 创建任务时冻结策略，Worker 使用快照执行；密钥只单独挂载给 Worker，变更后重启项目服务。不要把密钥放入前端、`VITE_*` 变量或提交到 Git。`/api/v1/ai/plot-config` 只返回本地配置状态及模型名，不返回密钥，也不验证远端权限。缺配置仍能上传、执行本地统计及查看历史成果。用 `script/dev.cmd start` 同时启动前后端与Worker栈，配置细节见[Worker说明](infra/worker/README.md#绘图模型策略)。

本机项目“测试”已按用户授权配置 `gpt-5.6-sol`，用户和项目累计额度各5美元、单绘图1美元、单解释0.5美元。原 `gpt-5.6` 别名查询返回404，完整名称查询成功；后续用户真实验收的新绘图与解释已持久化成功。这些配置不是其他环境的默认值，工具预留也不是实际账单。

### 使用与图表口径

1. 选择已保存的字段配置，先完成第二步描述统计。
2. 在流程导航“图表”点击“使用 OpenAI 生成箱线图”，先查看“发送前检查”中的范围、数量与名称，按需替换文字标签；确认后才提交生成请求。取消或仅打开页面不创建任务，单位文字修改不换算数值。
3. API只保存统一任务并返回排队状态，Linux Worker重算材料、检查预算，再分片创建容器、上传数据、提交与续取响应。页面GET只读本地保存状态；切换文件或关闭网页不影响Worker执行，等待期间可继续浏览工作台。
4. 云端结构化结果与本地总体/分组统计、样本数、分位数、须端、离群点及标签图注核对通过后保存 PNG。浮点量使用相对容差 `1e-10`，计数、来源及文字精确匹配。
5. 查看图及图注，点击“下载箱线图 PNG”。图号、标题、坐标轴字段/单位、分组和 n、完整图注均要求在 PNG 内；无分组绘制总体，有分组只绘制各组。图 1 是每次分析内的编号。
6. 刷新/重启后选择同一文件，可恢复已保存图；修改配置并重新统计后生成新图，旧图和旧结果保留。未保存字段或旧配置不能触发新生成。

箱体为 Q1–Q3，中线为中位数；分位数沿用线性 inclusive 算法。须端到 `[Q1−1.5×IQR, Q3+1.5×IQR]` 内最远实际观测；范围外观测为空心点，不从统计中删除。重复离群点可能重叠，记录同时保留真实个数。单条或常数数据显示重合线，不伪造箱体高度；未进行显著性检验。字段名/分组标签超过 160 字符会在调用前提示简化。

**核验边界：**代码校验结构化数值、标签/图注文本及 PNG 的格式、尺寸和可解码性，不能证明图片每个像素都与 JSON 一致。云端图的中文字体、轴刻度、标签和图注排版仍需人工查看；未通过人工验收前不要将图像视觉正确性当作已保证。

### 发送内容、重试与恢复

- 新任务确认后只上传所选完整有效数值/分组及确认标签（`labels/values/groups`），不上传其他列、整个Excel、文件/工作表名、项目研究主题或本地来源ID/hash。原始名称不会自动识别为敏感内容，需用户核对；旧无确认合同的任务沿用原接受约定。模型工具权限由后端固定。生成涉及OpenAI API与Code Interpreter费用。
- 保存模型名、response/container ID、模型实际执行代码、token 用量、原文件哈希、统计结果版本、PNG 哈希及提示词版本。模型报告的 Python/Matplotlib/字体环境也作为来源记录保存。
- 提交前建立统一任务并冻结来源和策略，相同结果重复点击复用进行中任务或已有图。SDK关闭自动重试；容器创建、文件上传、响应创建分别先记录开始标记，再保存回执。开始标记缺少回执时保留预算预留并等待核对，禁止通过重试盲目重发。
- 超时先点“重新读取图表”。已有回执时继续原阶段；已有response ID时只续取原响应，预算补足后可显式继续原任务。终态内容失败或明确容器过期后，只有用户点击带额外费用提示的再次生成才创建新任务；未知提交不开放此入口。
- 使用 OpenAI 后台响应模式，远端响应按其策略留存；每次创建独立容器并设置 20 分钟闲置过期。若后端停机过久，尚未下载的容器文件可能过期且不可恢复。已下载 PNG 不依赖远端容器；任务恢复不等于永久云端保存。[后台模式](https://developers.openai.com/api/docs/guides/background)、[容器生命周期](https://developers.openai.com/api/docs/guides/tools-code-interpreter)
- 新绘图由独立Worker执行，每片最多一个外部POST或一次响应续取，等待时释放租约。收到响应先记用量，再核对并下载成果；已验证的本地候选PNG可在租约恢复后发布，不必重做云端生成。来源变化、密钥失效、额度不足、模型不支持、结果不一致、图片损坏及存储失败均有反馈，失败不会覆盖旧图。旧绘图job仅兼容续取原响应，不补造统一调用或自动重新收费。

## 第四步：AI 分析解释

对应需求 V0.13 §5.7。新解释已迁入统一队列，由独立策略指定支持 Responses 后台模式与 Structured Outputs 的模型，不采用旧 `OPENAI_MODEL`。此步由模型组织文字，不启用 Code Interpreter 或图片生成工具，也不重复计算统计量。[结构化输出官方说明](https://developers.openai.com/api/docs/guides/structured-outputs)

管理员参考 [explanation-policy.example.json](backend/explanation-policy.example.json) 创建Git忽略的 `backend/.env.explanation-policy.json`，在 `.env` 设置 `PAPERASSIST_EXPLANATION_POLICY_FILE`，填入核实后的模型、价格、输入预留和任务额度；用户/项目累计额度用本机预算命令设置。密钥可用 `OPENAI_API_KEY_FILE`，否则使用 `OPENAI_API_KEY`；仅Worker挂载模型密钥，变更后须重启项目服务。示例必填金额为空，历史解释读取不依赖当前策略；本机项目“测试”的授权配置见上方绘图说明。单位和细节见[管理配置方式](docs/开发记录/阶段02/2026-10-08-解释任务迁移实施计划.md#管理配置方式)。

1. 选择已有配置，完成描述统计并生成、保存当前箱线图。
2. 切换流程导航“分析解释”，配置完整后点击“使用 OpenAI 生成解释”，先核对发送范围和文字标签（含图标题），确认后才创建任务。API返回排队状态，由Worker检查预算后调用收费API；缺策略/价格时不接受可收费新任务，缺用户/项目额度时进入等待。
3. 成功后显示**分析目的、使用数据、分析方法、主要结果、结果解释、论文描述文字**，每段可展开查看所引用的事实。分析目的仅描述本次统计任务；研究设计、实验步骤和样本背景不足时不补写。
4. 核对文字与表格/图片，再查看“解释限制”和“解释来源与核对记录”。页面只展示语言、保存时间及可读核对说明；模型、响应编号、用量、哈希和来源关联仍保存在后端，不渲染在工作区。
5. 刷新页面或重启服务后选择同一文件，恢复相同解释；重复点击复用已保存内容。修改并保存配置后，需依次重新统计、绘图、生成解释，旧解释仍绑定旧版本。

**发送和校验：**新任务仅发送经确认名称标注的统计事实和必要图表信息，不发送逐行数值、其他Excel列、完整文件、PNG、项目研究主题、文件/工作表名或本地来源ID/hash。旧无合同任务保持原材料约定。本地来源与统计校验继续保留；模型用`{{fact.key}}`引用事实，后端检查六段结构、必需引用、未知引用、裸写数字、篇幅和部分明显不支持的推断表述，再填入本地保存值。显示最多6位有效数字。

**核验边界：**自动校验确认引用存在且数值来自已保存结果，不能证明整段语义、标签关联或比较方向正确，也不能覆盖所有变相推断。文字是 AI 初稿，须人工核对；不把引用核对标记等同于科学结论正确。未执行显著性检验，不生成 P 值、置信区间、因果/疗效结论或文献引用；本步没有对图片像素进行识别。

**恢复和错误：**浏览器查询只读本地状态，Worker每片只做一次POST或GET，等待时释放租约并延迟续取。预算补足后显式恢复原任务；已有响应编号只GET。无编号的未知提交保留预留并等待核对，不允许盲目重试；已知响应404停止续取，不自动创建替代付费请求。坏输出先记用量再报失败，只有用户明确再次生成才创建可能收费的新任务。来源变化阻止挂接旧解释，但已知响应仍续取用量；历史已保存解释不依赖当前模型配置。

旧绘图job和旧 `explanation_jobs` 保留每轮完成后5秒的进程内兼容扫描，只续取已有响应；新绘图和解释由独立Worker执行。`PAPERASSIST_PLOT_WORKER_ENABLED=0` 只关闭前述历史扫描，不是新统一任务的总开关。自动测试另使用独立数据库schema、资产和队列，清空真实密钥/策略，以模拟供应商验证。

手动验收路径：**选择已有配置和图表 → 生成解释 → 核对六部分及每段依据 → 刷新/重启后确认恢复 → 修改并保存配置 → 重新统计和绘图 → 再生成解释，确认对应新版本。**Word 导出见第五步；解释编辑器和研究背景补充流程尚未实现。

## 第五步：Word 分析报告

1. 进入项目，选择已有分析文件，确认当前保存配置对应的统计、箱线图和六段解释都已完成。
2. 切换流程导航“Word报告”，点击“生成 Word 报告”，页面显示排队或生成状态，完成后点击“下载 Word 报告”。已有完整报告直接复用；已保存的图表与报告也可从项目侧栏“图表与报告”下载。
3. 用 Word 或 WPS 打开 `.docx`，检查数据概况、有效/排除行数、方法、两张统计表、原 PNG 与图注、六段解释、事实依据和来源记录。
4. 刷新页面，或停止并重启前后端后重新选择同一文件；下载入口自动恢复。同一解释和模板版本重复生成复用同一文件与编号。
5. 修改并保存配置后，先重新执行统计、绘图和解释，再导出新版本。未保存字段或旧结果不能生成新报告；旧报告不会覆盖，可保留其下载地址继续下载。

报告在本地由 python-docx 整理已有结果，不调用 OpenAI，也不要求当前存在 API 密钥。图表来自第三步已经保存的官方 Code Interpreter 输出；报告导出不改变绘图方式。统计表和正文可编辑，图像保持原始字节。主文和附录中的数值最多显示 6 位有效数字，缺失统计量写“无法计算”，完整数值仍在统计记录中。

导出前核对原文件、PNG 哈希、统计/图表/解释来源以及关键引用，保存事务中再次核对配置版本和来源记录；报告同时保存输入快照与哈希。并发重复请求仅保留一份报告。磁盘错误可重试；文件缺失或被修改时返回明确错误，不静默覆盖原报告。下载已保存报告仅校验项目/文件/统计归属和 DOCX 完整性，不依赖原 Excel 或 PNG 仍在磁盘，但缺失源文件时网页的分析读取仍会提示错误，已有报告可用保留的下载地址取得。

阶段02第二步起，新报告由独立Worker后台生成，前端只读轮询状态，刷新或重新打开后继续读取已保存任务。短暂提交期间防止重复操作，排队/生成期间不锁定整个分析工作台；来源变更会在提交成果前再次核对。查询失败可重新读取，任务失败后可明确重试；页面不会因轮询错误自动新建任务。任务显示成功但报告快照暂未返回时，会继续读取报告。

当前提供中文描述统计报告，包含 AI 初稿审核提示和研究背景待补充说明，不补写研究设计、显著性或因果结论；不包含完整论文、学校模板、英文报告或 PDF。版式为 Letter 纵向、2 cm 页边距，正文宋体/Arial 11 pt。用户已手动用 Word/WPS 核对并确认验收通过；本机自动渲染仍因缺少 LibreOffice 而不可用。该手动结果不代表所有数据和软件版本的排版均已验证。运行导出功能不需要 LibreOffice。

## 上传与解析配置

默认单文件上限 **10 MiB（10,485,760 字节）**。前端从后端读取限制，服务端再次校验。请求体在 multipart 解析前按实际接收字节限制，即使没有 `Content-Length` 也生效；multipart 额外允许 64 KiB 开销。

后端配置示例见 `backend/.env.example`。以下 `EXCEL_*` 配置均为正整数，修改后重启后端；无效的解析限制会阻止启动。可填写 `backend/.env`，也可在启动后端的 PowerShell 终端设置优先级更高的环境变量。在项目根目录执行：

```powershell
$env:EXCEL_MAX_UPLOAD_BYTES = '20971520'
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

该设置只影响当前终端及从它启动的进程，新开终端时需要重新设置。

| 环境变量 | 默认值 | 含义 |
| --- | --- | --- |
| `EXCEL_MAX_UPLOAD_BYTES` | `10485760` | 单个上传文件字节数 |
| `EXCEL_MAX_UNCOMPRESSED_BYTES` | `67108864` | ZIP 内所有条目的总解压字节数（64 MiB） |
| `EXCEL_MAX_SHEETS` | `50` | 数据工作表数量 |
| `EXCEL_MAX_ROWS` | `100000` | 每张表最大原始行坐标，包含表头和格式行 |
| `EXCEL_MAX_COLUMNS` | `256` | 每张表最大原始列坐标 |
| `EXCEL_MAX_CELLS` | `1000000` | 全部工作表的 XML 单元格节点总数和扫描槽位总数分别不得超过此值 |

此外，ZIP 条目数固定上限为 10,000，预览固定最多 20 行。解压/XML 预检使用 defusedxml，按工作簿关系找到实际工作表，限制坐标及节点数量，再用 openpyxl 只读扫描。只有扩展名正确不够，内容也必须是有效工作簿；不执行宏和公式。

这些是输入与解析资源边界，不是经过压力测试的生产容量承诺。提高文件上限并不会自动提高解析规模限制。

## 本地存储与备份

元数据、预览、配置、统计、图表/解释/报告快照与云端请求记录保存在 PostgreSQL。文件资产默认保存到 `backend/data`，不因启动终端所在目录改变：

```text
backend/data/
  files/<UUID>.xlsx      上传的原始文件，每次上传独立保存
  figures/<UUID>.png     核对通过后下载保存的云端箱线图
  reports/<UUID>.docx    由已保存的统计、图片及解释生成的 Word 报告
```

数据库连接必须显式配置，资产目录可使用默认值。需要更换资产目录时，在启动后端的 PowerShell 中设置：

```powershell
$env:PAPERASSIST_DATA_DIR = 'D:\PaperAssistData'
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

该变量默认是 `data`，相对路径以 `backend` 为基准，也接受绝对路径。更换目录不会自动迁移资产或切换数据库；不要指向临时目录。默认 `backend/data`、旧SQLite文件及本地备份已被Git忽略；若自定义到仓库中的其他目录，需要同时忽略资产与备份。

备份前须停止新增写入、排空任务并核实停写，再保存数据库及同一静止时点的完整资产目录、大小和SHA256清单；只复制 `backend/data` 不能备份数据库。当前独立内测栈的维护、成套备份、独立恢复与版本回退按[部署与回退手册](docs/运行维护/本地内测部署与回退手册.md)执行；开发环境统一启停入口继续保留。恢复必须匹配数据库版本、代码候选与同一份资产快照，不代表生产RTO/RPO已验证。旧库切换位置与边界见[迁移记录](docs/开发记录/阶段01/PostgreSQL统一与迁移记录.md)。不要手工修改数据库或UUID文件。下载校验大小及SHA256，历史预览使用已保存结果，调整解析限制不会自动重解析。

文件写入采用临时写入、重命名和数据库事务保存，任务候选及租约支持恢复；普通写入失败会尝试清理本次文件。存储治理提供容量、盘点、配额和受控处置，范围与保留策略见[第三批记录](docs/开发记录/阶段10/2026-10-26-第三批实施与验证记录.md)。原环境 `retain_all`、自动删除关闭继续保留；不能把盘点结果直接视为删除授权。

## 接口

统一任务提供项目分页、工作区详情、增量事件、三级预算与业务专用异步创建/恢复。`POST /tasks/{id}/resume` 使用必填幂等键、任务版本与输入版本，在事务内完成等待消费、状态变更和排队；前端只显示服务端允许的操作。资料补充、研究计划与后续稿件/评审沿业务专用消费者接入，通用任意创建和任务取消边界见[阶段清单](docs/开发阶段/阶段02-统一任务与模型调用.md)。旧详情及Word GET/下载合同保持，精确成果沿固定任务来源读取；错误保留 `detail.code/message/params` 与 `request_id/details`。下表保留已有兼容接口，完整当前路由以运行环境 `/docs` 及 `backend/app/api/` 为准；运营、存储、配置和运行状态位置见[项目结构](docs/项目结构.md)。

新绘图/解释分别增加只读`GET .../analysis-runs/{run_id}/boxplot/disclosure`和`GET .../analysis-runs/{run_id}/explanation/disclosure`；新模型任务POST携带`external_processing`版本、确认、来源摘要和标签。原键重放、历史成果与原任务恢复不强制补确认。冻结规则及新旧合同边界以[第九步交付记录](docs/开发记录/阶段02/外发资料说明与最小化交付记录.md#接口与代码位置)为准。

| 方法和路径 | 用途 |
| --- | --- |
| `GET /api/v1/health` | 保留 `{ "status": "ok", "service": "paperassist-system" }` |
| `GET /api/v1/tasks/{task_id}` | 当前用户的统一任务公开详情，只读；未知/他人任务404，不暴露原始输入快照 |
| `GET /api/v1/projects/{project_id}/tasks` | 项目统一任务分页；`page`从1、`page_size`缺省10且最大50，可按`status/task_type`筛选 |
| `GET /api/v1/tasks/{task_id}/workspace` | 只读任务、来源/配置版本、等待、允许操作及此任务的精确历史成果 |
| `POST /api/v1/tasks/{task_id}/resume` | 必填`Idempotency-Key`；请求含`operation`（resume/retry）、`wait_id`、`expected_task_revision`和`input_version`，成功202；冲突后重新读取 |
| `GET /api/v1/tasks/{task_id}/events` | 每任务增量事件，`after`缺省0、`limit`缺省50且最大100；不推进任务 |
| `GET /api/v1/projects/{project_id}/model-usage` | 本人项目的累计美元预算、内部估算、预算已计金额、预留、实际核对及调用分页，只读；`page`从1、`page_size`为1–50 |
| `GET /api/v1/tasks/{task_id}/model-usage` | 本人任务的调用和三级预算，只读；分页规则同项目查询，不触发模型请求 |
| `POST /api/v1/tasks/{task_id}/retry` | `{ "expected_revision": 当前任务修订号 }`；失败Word及允许恢复的绘图/解释，核对权限、来源、状态与版本；不允许未知提交盲目重发 |
| `GET/PATCH /api/v1/auth/preferences` | 读取/更新当前账号 `ui_language`，仅 `zh-CN/en`；写入检查当前会话与CSRF |
| `GET/PATCH /api/v1/projects/{project_id}/language` | 独立读取/更新项目 `default_output_language`，仅所有者可访问，返回完整Project |
| `GET /api/v1/ai/config` | 旧OpenAI配置兼容查询，不作为新绘图/解释准入依据 |
| `GET /api/v1/ai/plot-config` | 需登录；绘图专用策略/密钥本地可用状态及模型，不返回密钥/路径，不验证远端权限 |
| `GET /api/v1/ai/explanation-config` | 需登录；解释专用策略/密钥本地可用状态及模型，不返回密钥/路径，不验证远端权限 |
| `GET /api/v1/excel/config` | 返回 `max_upload_bytes`、`preview_row_limit` |
| `POST /api/v1/excel/preview` | 保留临时预览接口，multipart 字段 `file`；不保存项目文件 |
| `GET /api/v1/projects` | 无列表参数时返回兼容数组；显式传入任一 `page/page_size/q/type` 时返回分页对象，仅含当前用户项目 |
| `POST /api/v1/projects` | JSON字段 `name`、`research_topic`、`project_type`；可选 `default_output_language`（`zh-CN/en`，默认中文）；成功201 |
| `GET /api/v1/projects/{project_id}` | 单个项目的信息 |
| `GET /api/v1/projects/{project_id}/summary` | 只读任务/成果摘要；`task_page/artifact_page`独立分页，`page_size`缺省10、最大50；明确后续模块空态 |
| `GET /api/v1/projects/{project_id}/files/{file_id}/analysis-runs/{run_id}/figures/{figure_id}/download` | 下载指定历史PNG版本，检查归属、来源与完整性 |
| `PATCH /api/v1/projects/{project_id}` | 仅所有者可更新 `name`、`research_topic`，可提交任一或两个字段；成功200，返回完整项目，拒绝修改类型及其他字段 |
| `GET /api/v1/projects/{project_id}/files` | 无分页参数保留旧数组；显式 `page/page_size` 返回当前项目文件分页对象 |
| `POST /api/v1/projects/{project_id}/files` | multipart 字段 `file`；保存原文件及结果，成功 `201` |
| `GET /api/v1/projects/{project_id}/files/{file_id}/details` | 文件元数据、既有预览范围、引用计数及内测保留说明 |
| `PUT /api/v1/projects/{project_id}/files/{file_id}/purposes` | JSON `{ "expected_revision": 1, "purposes": ["raw_data"] }`；更新用途，使用独立文件元数据修订 |
| `GET /api/v1/projects/{project_id}/files/{file_id}/preview` | 重新读取保存的预览 |
| `GET /api/v1/projects/{project_id}/files/{file_id}/download` | 下载原文件，包括解析失败的原文件 |
| `GET /api/v1/projects/{project_id}/files/{file_id}/analysis-profile?sheet=...` | 整表字段类型及非缺失、缺失、实际数值数量 |
| `POST /api/v1/projects/{project_id}/files/{file_id}/analysis-check` | 检查选中字段、可用行数和有效分组；不执行统计 |
| `GET /api/v1/projects/{project_id}/files/{file_id}/analysis-setup` | 读取当前配置；未保存时返回 JSON `null` |
| `PUT /api/v1/projects/{project_id}/files/{file_id}/analysis-setup` | 重新校验并保存当前配置，返回递增修订号 |
| `POST /api/v1/projects/{project_id}/files/{file_id}/analysis-runs` | JSON `{"expected_revision": 1}`；执行该已保存配置，或返回同配置/工具版本的已有结果 |
| `GET /api/v1/projects/{project_id}/files/{file_id}/analysis-result` | 返回最新保存结果、当前配置修订号及结果是否匹配 |
| `GET .../analysis-runs/{run_id}/boxplot` | 只读本地图表、统一task和兼容旧job，不执行供应商请求 |
| `POST .../analysis-runs/{run_id}/boxplot` | `{ "expected_revision": 1 }`；可选 `Idempotency-Key`；新任务202，已有图复用200，允许的明确重试增加 `"retry": true` |
| `GET .../analysis-runs/{run_id}/boxplot/image` | 读取已保存 PNG；`?download=true` 作为附件下载 |
| `GET .../analysis-runs/{run_id}/explanation` | 只读本地解释、统一task和兼容旧job，不执行供应商请求 |
| `POST .../analysis-runs/{run_id}/explanation` | `{ "expected_revision": 1, "figure_id": "当前图表编号" }`；可选 `Idempotency-Key`；新任务202，完整解释复用200，允许的明确重试兼容 `"retry": true` |
| `GET .../analysis-runs/{run_id}/report` | 只读报告、准备状态及对应 `task`，不生成、不推进执行 |
| `POST .../analysis-runs/{run_id}/report` | `{ "expected_revision": 1, "figure_id": "当前图表编号", "explanation_id": "当前解释编号" }`；可选 `Idempotency-Key`；任务接受 `202`，已有完整报告复用 `200` |
| `GET .../analysis-runs/{run_id}/report/{report_id}/download` | 下载 Word 附件，检查归属及报告大小/哈希；允许下载旧配置的报告 |

项目列表分页对象为 `{items, total, page, page_size}`，默认页码1、每页10项；`page` 为1–1,000,000，`page_size` 为1–100，HTTP只接受ASCII十进制整数字符串。`q` 去首尾空白后最长120字符，按名称作不区分大小写的字面子串搜索；`type` 只接受 `sci/thesis`。分页按 `updated_at DESC, id ASC` 排序，当前用户的总数与条目读取同一只读快照。前端显式消费分页合约，详情从hash独立恢复；项目路径精确`project_not_found`清旧工作区，普通资源404/410不清项目。证据及边界见[列表交付记录](docs/开发记录/阶段01/项目列表分页与权限空态交付记录.md)。

文件分页对象为 `{items,total,page,page_size}`，`page`为1–1,000,000、`page_size`为1–100，显式启用分页后缺省值为1/10；HTTP只接受ASCII十进制整数字符串，按 `uploaded_at DESC,id ASC` 排序。网页固定每页5项，分析文件来源保留完整旧数组。分页条目增加 `purposes`、`metadata_revision` 和 `uploader_recorded`；历史上传者未知、用途未指定，不补造解析版本。用途请求的 `expected_revision` 为至少1的严格整数，集合最多6项且不得重复，允许 `raw_data/figure/methods/school_template/paper/revision_material`，空集合表示未指定，拒绝额外字段。旧修订且集合已等于当前保存值时幂等返回，其余修订冲突返回409/`file_metadata_conflict`；用途修改不改变分析配置、任务来源或成果。引用汇总只说明当前依赖，无删除入口。合同与验证边界见[本步交付记录](docs/开发记录/阶段03/2026-10-09-文件基座与历史兼容交付记录.md)。

项目编辑使用非空JSON对象。名称去首尾空白后1–120字符，研究主题1–500字符；字段错误返回422/`project_update_invalid`，任何 `project_type` 更新返回422/`project_type_immutable`。未知或他人项目的合法更新请求返回404；同值更新不更新时间。原ID、owner、创建时间、文件及历史成果保持不变，旧Word保留生成时的信息，同一成果重复导出复用原报告；详情见[项目编辑交付记录](docs/开发记录/阶段01/项目基础信息编辑交付记录.md)。

字段检查的 JSON 请求示例；保存时额外携带 `expected_revision`（首次为 `0`，之后使用读取到的当前修订号）：

```json
{
  "task_type": "descriptive_boxplot",
  "sheet_name": "Sheet1",
  "numeric_column": "A",
  "group_column": "B",
  "unit": "mg/L",
  "missing_policy": "exclude_selected_missing"
}
```

`group_column` 为 `null` 表示不分组。检查接口返回 `ready`、`row_count`、`valid_count`、`excluded_count`、`groups`、`issues` 和 `warnings`；只有 `ready: true` 时才可以保存。保存结果的 `status: configured` 只表示配置已准备好。非法列/工作表或不可用配置返回 `422`，过期修订号返回 `409`，存储失败返回 `503`。

统计执行返回 `id`、`file_id`、`filename`、`source_sha256`、`setup_revision`、`selection`、`check`、`numeric_name`、`group_name`、`engine`、`started_at`、`completed_at`、`overall` 和 `groups`。`overall` 包含上述 9 个统计指标及 `warnings`；`groups` 每项包含 `label` 和相同结构的 `statistics`。读取结果返回 `{"current_revision": 1, "is_current": true, "result": {...}}`；未执行时 `result: null`、`is_current: false`。执行和复用结果均返回 `200`；未保存或配置过期返回 `409`，解析限制或精度不支持返回 `422`。所有结果接口仍校验项目归属和原文件完整性。复用已有结果时不重新计算，首次计算才重新应用当前解析限制。

图表路径的 `...` 为 `/api/v1/projects/{project_id}/files/{file_id}`。GET/POST返回 `{current_revision,is_current,figure,job,task}`；新任务使用 `task`，`job`只兼容真实旧记录，不造旧job。GET只读且200；新任务POST接受202，已有图复用200。`is_current` 表示统计结果是否对应当前配置，即使尚无图也可为 `true`。新成果与模型调用关联，任务公开可空 `result_figure_id`；内部候选及provider状态不公开。缺策略/密钥503，配置版本或幂等冲突409，无结果/无图404，图片缺失410、篡改409；PNG下载始终核对归属、原始文件和图片哈希。

解释接口使用相同路径前缀，返回 `{current_revision,is_current,figure_id,explanation,job,task}`。新任务使用 `task`，`job`只兼容真实旧记录，不造旧job。GET只读且200；新任务POST接受202，已有解释复用200。`is_current` 表示统计是否匹配当前配置；尚无图时 `figure_id: null`，POST返回409。新任务缺模型策略/价格/密钥503，错误图号、旧版本或幂等冲突409。解释保留六段 `sections`（`key/title/text/evidence`）、`limitations`及来源；新产物的 `provenance` 增加模型调用关联，任务有可空 `result_explanation_id`。`verification.status=references_checked` 仅表示引用检查通过，不表示文字语义已自动审核。

报告 GET/POST 返回 `{current_revision,is_current,ready,issues,report}`；缺少图表或解释时 GET 返回 `ready: false` 并说明原因。`report` 含报告、统计、图表和解释 ID、配置版本、来源/图片/报告/输入 SHA256、时间、文件名、大小、语言和模板引擎版本。错误来源或旧配置 `409`，缺少报告 `404`，报告文件缺失 `410`，报告被修改 `409`，文档内容无法生成 `422`，存储失败 `503`。报告文件不可变，输入快照仅存本地数据库，不通过状态接口返回。

临时预览接口返回结构（项目上传结果中的 `preview` 也使用此结构）：

```json
{
  "filename": "example.xlsx",
  "sheets": [{
    "name": "Sheet1",
    "columns": ["编号", "测量值"],
    "row_count": 1,
    "column_count": 2,
    "preview_rows": [["S01", 12.5]],
    "warnings": []
  }]
}
```

项目上传返回 `{"file": {...}, "preview": {...}}`。`file` 包含 `id`、`project_id`、`filename`、`file_type`、`size_bytes`、`sha256`、`uploaded_at`、`parse_status`、`error`。解析失败但原文件已成功保存时也返回 `201`，此时 `parse_status` 为 `failed`，`error` 含 `code` / `message`，`preview` 为 `null`；`201` 表示保存成功，不等于解析成功。

业务错误结构为 `{"detail":{"code":"parse_failed","message":"可读的中文说明"}}`；输入模型校验使用 FastAPI 标准 `detail` 数组。状态码：`415` 不支持扩展名；`413` 文件或请求体过大；`422` 输入不合法、缺少文件或临时预览解析失败；`404` 项目不存在或文件不属于当前项目；`409` 原文件内容变化；`410` 原文件缺失；`503` 数据目录或数据库不可用。可读取的空工作表正常返回预览，通过 `warnings` 说明。

通过 Vite 代理手动调用（PowerShell，替换为自己的文件路径；使用 `curl.exe`）：

```powershell
curl.exe -F 'file=@C:\path\to\example.xlsx' http://127.0.0.1:5173/api/v1/excel/preview
```

HTTP错误统一为 `{detail:{code,message,params}}`，保留原状态码和兼容中文message，前端只按已知code与安全params翻译；未知异常显示本地通用提示。任务和AI配置响应提供 `message_code/message_params`，旧任务只读兼容，不回写历史JSON。

## 依赖文件说明

后端统一使用 `backend/requirements.txt` 管理运行依赖和测试工具（`pytest`、`httpx2`）。第三步加入官方 `openai` SDK、`python-dotenv` 和用于校验 PNG 的 Pillow，以及 SDK 的必要依赖；第四步沿用这些依赖，没有新增依赖文件，也不需要本地安装 Matplotlib 来生成图。

第五步在同一文件新增 `python-docx==1.2.0` 和 `lxml==6.1.3`，用于生成可编辑 Word 文档；没有拆分新的依赖清单。实现参考 [python-docx 官方文档](https://python-docx.readthedocs.io/en/latest/user/quickstart.html)。

PostgreSQL 统一在同一文件固定 `SQLAlchemy==2.1.1`、`psycopg[binary]==3.3.6` 和 `alembic==1.20.0`。SQLAlchemy Core 承接已有 SQL 与事务，不要求为所有未来模块预建 ORM 模型。

阶段02第二步固定 `celery==5.6.3`，使用普通AMQP依赖及Linux Worker；RabbitMQ和Python容器镜像固定digest。不使用SQLAlchemy extra或Celery结果后端；详细版本与运行边界见[Worker说明](infra/worker/README.md)。


## 验证方法与结果

本节保留可执行命令；按变更影响范围选择专项验证。历史通过数、失败复验、真实/合成调用及用户验收分别见[阶段10收尾记录](docs/开发记录/阶段10/2026-10-27-第四批验收与阶段收尾记录.md)、[阶段02整轮记录](docs/开发记录/阶段02/阶段整轮回归与剩余证据核定交付记录.md)、[阶段01交付索引](docs/开发记录/阶段01/)及[早期Excel→Word闭环记录](docs/开发记录/历史小闭环/2026-09-29-workflow-acceptance.md)。入口精简不构成新的业务回归或真实调用结果。

后端：先在本地配置可用的 `PAPERASSIST_TEST_DATABASE_URL`，目标必须为 `paperassist_system_test`。在项目根目录打开 PowerShell 执行，无需激活虚拟环境。

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests -q
.\backend\.venv\Scripts\python.exe -m pip check
```

前端：在项目根目录新开一个 PowerShell 终端执行。

```powershell
npm.cmd --prefix .\frontend ci
npm.cmd --prefix .\frontend test
npm.cmd --prefix .\frontend run build
npm.cmd --prefix .\frontend run lint
```

除纯配置检查外，每例后端测试都创建独立的 `pa_test_<uuid32>` PostgreSQL schema、显式迁移并使用临时资产目录；结束时只清理本例创建的 schema。测试配置缺失、错误目标或连接失败会失败，不回退到 SQLite，也不使用全局通用连接变量。测试默认清空真实模型密钥、关闭恢复扫描；需要模型配置的用例显式注入假密钥与模拟响应。

真实队列测试需显式选择隔离测试环境：在根目录运行 `.\script\test-queue.cmd`，仅使用专用测试库UUID schema、临时资产、独立broker/队列和模拟供应商。详见[Worker说明](infra/worker/README.md)；默认后端测试不启动真实队列。

手动验收：创建项目 → 上传文件 → 刷新页面并再次预览 → 停止并重启后端再预览 → 同名上传确认旧记录仍在 → 上传损坏的 `.xlsx` 确认失败记录和下载入口。可再创建第二个项目确认文件列表分开。

本步手动验收：进入项目 → 选择分析文件与工作表 → 选择数值列、可选分组列和单位 → 检查有效/排除行数 → 保存分析配置 → 刷新或重启后重新选择该文件，确认选择恢复。补充检查：空表不可保存、混合列不可选为数值列、修改字段后必须重新检查。

描述统计手动验收路径：选择已有配置 → 执行描述统计 → 核对总体/分组指标和缺失排除行数 → 刷新或重启后确认相同结果恢复 → 修改配置并保存，确认旧结果提示 → 再次执行并确认新结果。补充检查：单条记录标准差显示 `—`；未保存的字段不能直接执行；同一配置重复执行不产生新结果编号。历史验收结果见[闭环记录](docs/开发记录/历史小闭环/2026-09-29-workflow-acceptance.md)。

测试使用生成的合成工作簿与独立临时目录，未使用真实科研数据。解析依据：[openpyxl 只读模式说明](https://openpyxl.readthedocs.io/en/stable/optimized.html)、[FastAPI 文件上传说明](https://fastapi.tiangolo.com/tutorial/request-files/)。

Word 导出手动验收路径：先安装更新后的后端依赖并启动前后端 → 选择已有解释 → 生成报告 → 下载并用 Word/WPS 核对正文、统计表、图像、图注和依据 → 刷新/重启后确认恢复并再次下载 → 修改配置并重新统计、绘图、解释后导出新报告。历史主流程用户验收结果见[Word交付记录](docs/开发记录/历史小闭环/2026-09-29-word-report.md)。补充检查：同版本重复导出编号和文件不变、未保存字段不能导出、无 API 密钥但已有完整结果时仍可导出；这些补充场景的证据以对应独立记录为准。

## 尚未解决与使用边界

完整当前边界见[内测支持范围与已知限制](docs/运行维护/内测支持范围与已知限制.md)和[第三方组件与素材清单](docs/运行维护/第三方组件与素材清单.md)。QA11读延迟门槛未过、DOCX/PDF池2对照缺证；生产容量、真实科研/模型质量、完整学校与期刊材料适配、完整语言/许可及对外发布仍保留条件，不将合成工程或用户内测验收扩成这些结论。

模型图像须逐张检查，AI文字须人工审核语义、比较关系与研究适用性；数值和引用核对不能替代人工判断。Word与PDF采用公共导出链，Office/WPS及字体差异可能影响分页，具体输出仍需按用途核对。

- Excel首批支持 `.xlsx`，不支持 `.xls`、`.xlsm`、带密码文件、图表工作表预览或复杂多行表头识别。原始结构保留公式、缓存及合并范围，缓存有效性和原始单位未确认，首行仅作候选显示名；整理版本另行保存用户确认的表头和单位，不计算公式或填补合并值。结构输出上限4 MiB，上传文件小于10 MiB不代表完整结构可容纳。标准未加密Word/PDF已支持本地解析，扫描PDF所选页及静态PNG/JPEG已支持本地OCR；原OCR字符串始终待核对，第9步另存人工决定和独立核对版本（已验收）；不直接统计文档表格或识别值。

- 历史单文件接口仍在线程池内同步解析，前端120秒等待超时不强制终止该后端解析。Excel/Word/文本PDF新批次在Linux受限独立进程异步解析，墙钟60秒、CPU30秒、地址空间512 MiB；OCR另限180秒墙钟、120秒CPU和2 GiB虚拟地址空间。各格式结构JSON限4 MiB，文本PDF输出信封限8 MiB，OCR信封限32 MiB及派生图合计16 MiB，独立边界和实测规模见对应交付记录。多用户并发及所有10 MiB上限输入的容量尚未实测。

项目内容按账号归属控制，管理员身份不授予跨账号研究资料读取权限。本机独立部署、HTTPS与恢复操作已有内测实现，生产发布、容量和恢复目标继续按独立验收门槛处理。

## 历史授权注记

2026-10-23阶段09用户确认提交信息，并明确授权提交、推送 `feat/stage09-review-revisions`；该授权只适用于当时的阶段09Git操作，不包含合并main、删除分支或进入阶段10。实际后续集成状态以本页所列Git基线为准。本注记保留原README中唯一的后续授权记录；其他历史摘要可从[独立交付索引](docs/README.md)及清理前Git基线恢复。

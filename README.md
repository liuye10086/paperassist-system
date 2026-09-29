# PaperAssist System

面向生物医学、药学科研场景的科研论文辅助系统。

## 当前进度

已完成前后端基础工程、Excel 上传预览，以及本地项目与文件持久化：

- 前端：React + TypeScript + Vite
- 后端：Python + FastAPI
- 健康检查接口：GET /api/v1/health
- 前端页面可展示后端连接状态
- 网页选择一个 `.xlsx` 文件，后端使用 openpyxl 真实解析
- 切换工作表，查看列名、数据行列数与前 20 行
- 无效格式、零字节文件、损坏文件、空工作表和超限反馈
- 上传大小和解析规模可配置；保留现有 Vite `/api` 代理
- 新建项目，填写名称、研究主题，选择 SCI 科研论文或毕业论文
- 按项目保存原始 Excel、上传时间、大小、SHA256、解析状态和有限预览
- 文件历史列表、重新预览和原文件下载；刷新页面或重启后端后仍可继续使用
- 同名上传生成独立记录，不覆盖旧文件；解析失败保留原文件和原因

本次覆盖需求 V0.13 中项目创建、Excel 文件管理与预览的基础流程，不代表整个 M1 已完成。结合现有本地单用户代码，使用 Python 内置 SQLite 保存元数据、磁盘目录保存原文件，无需安装数据库服务；技术方案中的 PostgreSQL、pandas 和 Worker 尚未引入。

## 项目目录

- docs：需求、参考资料和技术实现方案
- backend：后端代码
- backend/tests：使用合成工作簿的接口与解析回归测试
- backend/app/projects.py、backend/app/storage.py：项目接口与本地存储
- backend/data：首次访问项目接口时自动创建的数据库和原文件目录，不提交 Git
- frontend：前端代码
- frontend/src/ProjectWorkspace.tsx：项目创建、选择和文件历史
- frontend/src/ExcelPreview.tsx：上传、切表和数据预览组件
- script：预留脚本目录

## 本地运行

以下步骤适用于 Windows PowerShell，所有命令均从项目根目录（包含 `backend`、`frontend` 和本 README 的目录）执行。若终端已经在该目录，无需再次切换目录。
前端和后端分别使用一个终端运行。
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

日常启动（已完成上述安装时，只执行这一条）：

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

健康检查：http://127.0.0.1:8000/api/v1/health

接口文档：http://127.0.0.1:8000/docs

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

在对应终端按 Ctrl+C。

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

在项目与文件保存的基础上，按需求推进字段类型识别、字段角色设置和数据质量分析，再接入统计与报告。

## 使用与数据规则

1. 启动前后端，打开 http://127.0.0.1:5173，确认“后端连接成功”。
2. 新建项目：填写项目名称（1–120 字符）、研究主题（1–500 字符）、项目类型；或从“当前项目”选择已有项目。
3. 选择 `.xlsx`，点击“上传并预览”。上传期间禁用重复提交，保存后文件出现在当前项目的文件列表。
4. 后端返回全部数据工作表的有限预览，默认展示第一张；通过“工作表”下拉框切换，无需再次上传。
5. 刷新页面后，地址中的项目 ID 会恢复当前项目和文件列表；点击文件的“预览”重新打开，点击“下载原文件”取得上传时的原始字节。
6. 重启前后端后，使用相同的数据目录即可继续查看项目。切换项目会清除旧预览并取消旧页面请求。

- **同名文件**：每次上传生成独立 ID；名称只用于展示，不用于磁盘路径，不覆盖旧文件。
- **失败记录**：扩展名不支持、零字节或超过上传大小限制直接拒绝，不产生记录；通过基本校验但解析失败的 `.xlsx` 保存原文件和失败原因，可以下载，不能预览。
- **超时**：取消浏览器请求不保证后端停止处理。遇到上传或创建超时，应先刷新列表确认结果，避免重复提交。

- **表头**：固定使用 Excel 第 1 行；空表头显示“未命名列 A/B/…”并提示；重复列名按原始顺序保留并提示，不合并字段。
- **数据行数**：从第 2 行到最后一个有值的行，不含表头，包含中间空行，忽略尾部空白及仅格式行。全空工作表返回 0 行、0 列；只有表头返回 0 数据行及相应列数。
- **列数**：从 A 列到最后一个有值的列，包含内部空列，忽略末尾仅格式列。扫描限制仍计算格式单元格的原始坐标。
- **预览**：最多显示前 20 个数据行，不跳过内部空行；左侧显示原始 Excel 行号。空值显示 `—`，数值 `0`、布尔 `FALSE` 不会被当作空值。
- **原始内容**：日期和时间转为 ISO 字符串；公式展示原文并提示未计算；合并单元格保留实际值，不自动补全。预览不还原 Excel 数字格式、颜色和合并布局。隐藏工作表仍可选择并有提示。

## 上传与解析配置

默认单文件上限 **10 MiB（10,485,760 字节）**。前端从后端读取限制，服务端再次校验。请求体在 multipart 解析前按实际接收字节限制，即使没有 `Content-Length` 也生效；multipart 额外允许 64 KiB 开销。

后端配置示例见 `backend/.env.example`。以下 `EXCEL_*` 配置均为正整数，修改后重启后端；无效的解析限制会阻止启动。当前**不自动加载 `.env`**，须在启动后端的 PowerShell 终端设置环境变量。在项目根目录执行：

```powershell
$env:EXCEL_MAX_UPLOAD_BYTES = '20971520'
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
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

这些是本地原型的临时保护值，不是经过压力测试的生产容量承诺。提高文件上限并不会自动提高解析规模限制。

## 本地存储与备份

默认保存到 `backend/data`，不因启动终端所在目录改变：

```text
backend/data/
  paperassist.sqlite3     项目、文件信息、错误原因及前 20 行等有限预览
  files/<UUID>.xlsx      上传的原始文件，每次上传独立保存
```

无需复制 `.env.example` 即可使用默认值。需要更换目录时，在启动后端的 PowerShell 中设置：

```powershell
$env:PAPERASSIST_DATA_DIR = 'D:\PaperAssistData'
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

该变量默认是 `data`，相对路径以 `backend` 为基准，也接受绝对路径。更换目录不会自动迁移数据；不要指向临时目录。默认 `backend/data` 和 SQLite 文件已被 Git 忽略；若自定义到仓库中的其他目录，需要同时忽略其中的原文件。

备份时先停止后端，再完整复制数据目录；恢复时数据库和 `files` 必须来自同一份备份。不要手工修改数据库或 UUID 原文件。预览和下载会检查原文件大小及 SHA256，文件缺失或内容改变时给出明确错误。历史预览使用上传时保存的结果，调整解析限制不会自动重新解析已有记录。

写入流程为原文件临时写入、重命名、数据库事务保存。普通磁盘或数据库写入失败会尝试清理本次文件；进程被强制终止或清理本身失败时，仍可能留下孤立文件，尚无自动恢复工具。

## 接口

| 方法和路径 | 用途 |
| --- | --- |
| `GET /api/v1/health` | 保留 `{ "status": "ok", "service": "paperassist-system" }` |
| `GET /api/v1/excel/config` | 返回 `max_upload_bytes`、`preview_row_limit` |
| `POST /api/v1/excel/preview` | 保留临时预览接口，multipart 字段 `file`；不保存项目文件 |
| `GET /api/v1/projects` | 项目列表，含文件数量，按最近更新时间排序 |
| `POST /api/v1/projects` | JSON 字段 `name`、`research_topic`、`project_type`（`sci` / `thesis`）；成功 `201` |
| `GET /api/v1/projects/{project_id}` | 单个项目的信息 |
| `GET /api/v1/projects/{project_id}/files` | 当前项目文件列表、状态及错误原因 |
| `POST /api/v1/projects/{project_id}/files` | multipart 字段 `file`；保存原文件及结果，成功 `201` |
| `GET /api/v1/projects/{project_id}/files/{file_id}/preview` | 重新读取保存的预览 |
| `GET /api/v1/projects/{project_id}/files/{file_id}/download` | 下载原文件，包括解析失败的原文件 |

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

## 依赖文件说明

后端统一使用 `backend/requirements.txt` 管理运行依赖和测试工具（`pytest`、`httpx2`），安装这一份文件即可运行服务和执行测试。

## 验证方法与结果

后端：在项目根目录打开 PowerShell 执行，无需激活虚拟环境。

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

2026-09-29，Windows、Python 3.11.4、Node.js 22.15.0、npm 10.9.2 下已验证：

- 后端 **52 项测试通过**：原有 31 项 Excel/健康检查测试，加上项目创建校验、上传与下载一致性、同名隔离、失败记录、跨项目归属、独立 Python 进程读取、原文件缺失或改变、数据库写入失败回滚、存储目录不可用，以及并发上传更新时间不回退。
- 回归覆盖省略单元格坐标、错误工作表尺寸、重复 XML 单元格、非标准工作表路径、未知关系类型与缺失工作表，防止误拒绝、限制绕过或静默丢表。
- 前端 **16 项交互测试通过**（Vitest + Testing Library，模拟 API）：原有 8 项上传预览测试，以及项目创建、历史预览、刷新恢复、项目内上传、失败记录下载入口、项目切换迟到响应隔离、网络重试和原文件缺失后重试。
- `npm.cmd --prefix .\frontend run build`、`npm.cmd --prefix .\frontend run lint`、`pip check` 通过；没有增加第三方依赖，仍只使用一份 `backend/requirements.txt`。
- 使用独立临时数据目录实际启动 FastAPI 和 Vite，经 `127.0.0.1:5173/api` 验证项目创建、两次同名上传、失败记录、列表、历史预览和逐字节原文件下载；正常工作簿返回 3 张表、25 行数据、前 20 行预览。
- 停止并重新启动实际 Uvicorn 进程后，2 个测试项目和 3 条文件记录仍在，所有原文件 SHA256 保持一致，成功预览和失败原因均可恢复。
- 本轮浏览器自动化验证了创建毕业论文项目、切换项目、历史预览、空表切换、刷新恢复，以及后端重启后重新打开预览；上传动作通过真实 HTTP 和组件测试验证。文件选择器此前发生工具超时，本轮未将浏览器选文件至上传的完整链路列为已自动验证。
- 上一轮（2026-09-28）用户手动确认的 5 项均通过：后端连接、选择并上传 Excel、列名/行列数/前 20 行、切表、空表提示。
- 本轮（2026-09-29）用户手动启动前后端，确认“创建项目 → 上传 → 刷新 → 重启后再次预览”验收通过。该结果来自用户手动验证；同名上传、解析失败和跨项目归属等其他场景已有自动测试，尚未收到用户的手动验收结果。

手动验收：创建项目 → 上传文件 → 刷新页面并再次预览 → 停止并重启后端再预览 → 同名上传确认旧记录仍在 → 上传损坏的 `.xlsx` 确认失败记录和下载入口。可再创建第二个项目确认文件列表分开。

测试使用生成的合成工作簿与独立临时目录，未使用真实科研数据。解析依据：[openpyxl 只读模式说明](https://openpyxl.readthedocs.io/en/stable/optimized.html)、[FastAPI 文件上传说明](https://fastapi.tiangolo.com/tutorial/request-files/)。

## 尚未解决与本次边界

- 项目与文件已持久化，但尚未实现项目编辑/删除、文件删除、显式版本关联、后台重解析、迁移工具或自动备份；同名上传目前是独立记录。
- 只支持 `.xlsx`；不支持 `.xls`、`.xlsm`、带密码文件、图表工作表预览或复杂多行表头识别。公式仅展示原文，不执行、不判断缓存新旧；合并布局不还原。
- 目前是中文界面；字段类型推断、缺失值分析、统计、AI、报告、英文界面仍待后续开发。
- 解析在线程池内同步执行；尚无独立解析进程、服务端硬超时和多用户并发容量验证。前端等待上限 120 秒，超时不会强制终止已经开始的后端解析。
- 列表尚未分页，未限制整个数据目录的累计大小；数据量增大后的查询性能、磁盘配额和崩溃恢复仍需完善。
- 尚未接入认证和用户级项目权限。文件路由只校验项目归属，不能作为多用户隔离机制；继续仅绑定 `127.0.0.1` 用于本地开发。生产环境的反向代理、上传超时、并发配额及数据库迁移仍需另行实现。

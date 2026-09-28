# PaperAssist System

面向生物医学、药学科研场景的科研论文辅助系统。

## 当前进度

已完成前后端基础工程、接口连通以及 Excel 上传与数据预览：

- 前端：React + TypeScript + Vite
- 后端：Python + FastAPI
- 健康检查接口：GET /api/v1/health
- 前端页面可展示后端连接状态
- 网页选择一个 `.xlsx` 文件，后端使用 openpyxl 真实解析
- 切换工作表，查看列名、数据行列数与前 20 行
- 无效格式、零字节文件、损坏文件、空工作表和超限反馈
- 上传大小和解析规模可配置；保留现有 Vite `/api` 代理

本次实现是需求 V0.13 第 5.2–5.3 节的预览子流程，不代表整个 M1 或文件管理模块已完成。技术方案中的 pandas、数据库和 Worker 尚未引入。

## 项目目录

- docs：需求、参考资料和技术实现方案
- backend：后端代码
- backend/tests：使用合成工作簿的接口与解析回归测试
- frontend：前端代码
- frontend/src/ExcelPreview.tsx：上传、切表和数据预览组件
- script：预留脚本目录

## 本地运行

以下步骤适用于 Windows PowerShell。前端和后端分别使用一个终端运行。
后端命令直接调用虚拟环境内的 Python，无需先激活环境；前端使用 `npm.cmd`。

### 后端

在项目根目录执行。首次运行时创建虚拟环境：

```powershell
python -m venv .\backend\.venv
```

安装依赖并启动（已有虚拟环境时直接从这里开始）：

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

健康检查：http://127.0.0.1:8000/api/v1/health

接口文档：http://127.0.0.1:8000/docs

### 前端

在项目根目录新开一个终端，执行：

```powershell
Set-Location .\frontend
npm.cmd ci
npm.cmd run dev
```

页面地址：http://127.0.0.1:5173

前端开发服务器将 /api 请求转发到本地后端。

### 停止服务

在对应终端按 Ctrl+C。

## 下一步

在当前预览链路基础上，按需求推进项目与文件持久化、字段类型和数据质量分析，再接入统计与报告。

## 使用与数据规则

1. 启动前后端，打开 http://127.0.0.1:5173，确认“后端连接成功”。
2. 选择 `.xlsx`，点击“上传并预览”。上传期间禁用重复提交；失败后可重新提交同一文件。
3. 后端一次返回全部数据工作表的有限预览，默认展示第一张；通过“工作表”下拉框切换，无需再次上传。
4. 更换文件时清除旧预览。刷新页面后需要重新上传。

- **表头**：固定使用 Excel 第 1 行；空表头显示“未命名列 A/B/…”并提示；重复列名按原始顺序保留并提示，不合并字段。
- **数据行数**：从第 2 行到最后一个有值的行，不含表头，包含中间空行，忽略尾部空白及仅格式行。全空工作表返回 0 行、0 列；只有表头返回 0 数据行及相应列数。
- **列数**：从 A 列到最后一个有值的列，包含内部空列，忽略末尾仅格式列。扫描限制仍计算格式单元格的原始坐标。
- **预览**：最多显示前 20 个数据行，不跳过内部空行；左侧显示原始 Excel 行号。空值显示 `—`，数值 `0`、布尔 `FALSE` 不会被当作空值。
- **原始内容**：日期和时间转为 ISO 字符串；公式展示原文并提示未计算；合并单元格保留实际值，不自动补全。预览不还原 Excel 数字格式、颜色和合并布局。隐藏工作表仍可选择并有提示。

## 上传与解析配置

默认单文件上限 **10 MiB（10,485,760 字节）**。前端从后端读取限制，服务端再次校验。请求体在 multipart 解析前按实际接收字节限制，即使没有 `Content-Length` 也生效；multipart 额外允许 64 KiB 开销。

后端配置示例见 `backend/.env.example`。所有配置均为正整数，修改后重启后端；错误配置会阻止启动。当前**不自动加载 `.env`**，须在启动后端的 PowerShell 终端设置环境变量。在项目根目录执行：

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

## 接口

| 方法和路径 | 用途 |
| --- | --- |
| `GET /api/v1/health` | 保留 `{ "status": "ok", "service": "paperassist-system" }` |
| `GET /api/v1/excel/config` | 返回 `max_upload_bytes`、`preview_row_limit` |
| `POST /api/v1/excel/preview` | multipart 表单字段 `file`，接收一个 `.xlsx` |

上传返回结构：

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

业务错误结构为 `{"detail":{"code":"parse_failed","message":"可读的中文说明"}}`。状态码：`415` 不支持扩展名；`413` 文件或请求体过大；`422` 缺少文件、无效内容、解析失败或超过解析规模限制。可读取的空工作表正常返回 `200`，通过 `warnings` 说明。

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
Set-Location .\frontend
npm.cmd ci
npm.cmd test
npm.cmd run build
npm.cmd run lint
```

2026-09-28，Windows、Python 3.11.4、Node.js 22.15.0、npm 10.9.2 下已验证：

- 后端 **31 项测试通过**：健康检查、多表、20 行截断、日期/布尔/空值、重复和空表头、公式、合并单元格、空表与仅表头、扩展名、损坏内容、缺失文件、大小边界、无 Content-Length 请求和各项解析上限。
- 回归覆盖省略单元格坐标、错误工作表尺寸、重复 XML 单元格、非标准工作表路径、未知关系类型与缺失工作表，防止误拒绝、限制绕过或静默丢表。
- 前端 **8 项交互测试通过**（Vitest + Testing Library，模拟 API）：FormData 上传、切表、错误重试、替换文件清理、空文件及超限校验、配置重试、上传中防重复提交、空值/0/FALSE/仅表头显示。
- `npm run build`、`npm run lint`、`pip check` 通过；没有改变已有前端依赖的锁定版本。
- 实际启动 FastAPI 和 Vite，经 `127.0.0.1:5173/api` 上传合成工作簿：返回 3 个工作表、25 个数据行及前 20 行；健康检查正常。
- 用户已在手动启动前后端后完成浏览器验证，以下 5 项全部通过：后端连接成功、选择 `.xlsx` 并上传、核对列名/行列数/前 20 行预览、切换工作表、空工作表提示。因此，正常上传与预览流程已通过用户手动验证。
- 浏览器自动化工具仍存在文件选择器事件超时的问题，尚未完成整条流程的浏览器自动化验证。上述浏览器结果来自用户手动验证；自动检查由真实 HTTP 联调及前端组件测试覆盖。无效文件和超限等异常场景已有自动测试，本次用户反馈未包含这些场景的手动验证。

测试文件在内存生成，未使用真实科研数据。解析依据：[openpyxl 只读模式说明](https://openpyxl.readthedocs.io/en/stable/optimized.html)、[FastAPI 文件上传说明](https://fastapi.tiangolo.com/tutorial/request-files/)。

## 尚未解决与本次边界

- 原文件只在请求期间处理（multipart 库可能使用临时文件，处理后关闭），服务端不持久保存原文件或预览；尚未实现需求中的项目归属、上传历史、文件状态和版本管理。
- 只支持 `.xlsx`；不支持 `.xls`、`.xlsm`、带密码文件、图表工作表预览或复杂多行表头识别。公式仅展示原文，不执行、不判断缓存新旧；合并布局不还原。
- 目前是中文界面；字段类型推断、缺失值分析、统计、AI、报告、英文界面仍待后续开发。
- 解析在线程池内同步执行；尚无独立解析进程、服务端硬超时和多用户并发容量验证。前端等待上限 120 秒，超时不会强制终止已经开始的后端解析。
- 尚未接入认证和项目权限，继续仅绑定 `127.0.0.1` 用于本地开发。生产环境的反向代理、上传超时、并发配额与持久化策略仍需另行实现。

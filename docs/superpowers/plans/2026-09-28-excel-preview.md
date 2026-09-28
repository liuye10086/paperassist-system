# Excel 上传与数据预览实施记录

依据：需求 V0.13 §5.2–5.3，技术方案 V0.1 §6.1、§14.3；本次仅实现预览子流程。

## 方案与边界

- 沿用 FastAPI、React、TypeScript、Vite 代理。openpyxl 只读解析；暂不引入 pandas、数据库、Worker。
- `GET /api/v1/excel/config` 返回上传限制；`POST /api/v1/excel/preview` 接收 multipart `file`，返回文件名、各表名称、列名、行列数、前 20 行和提示。
- 一次返回所有表的有限预览，切表不重新上传。相比服务端文件缓存，该方式无需生命周期管理；代价是首次请求需要扫描全部工作表以准确计数。
- 第 1 行为表头；数据范围从第 2 行到最后非空行，内部空行保留；列范围从 A 到最后非空列，格式空白不扩大范围。保留重复表头，空表头按 Excel 列字母补名并警告。
- 公式按原文预览，不执行、不猜测缓存。合并单元格只保留实际值，不自动填充。日期 ISO，布尔值和空值保留类型。
- 文件默认 10 MiB；请求体额外允许 64 KiB multipart 开销；限制解压大小、工作表数量、扫描行列和总单元格数。配置通过环境变量设置，错误配置拒绝启动。
- 不持久保存原文件，不实现项目归属、类型分析、统计或报告。这些仍在总体产品范围内。

## 执行清单

- [x] 后端：先写真实工作簿接口测试并确认新接口 404；新增配置、Schema、解析器、路由、请求大小限制，保留 health。
  - 文件：`backend/tests/test_excel.py`、`backend/app/config.py`、`backend/app/excel.py`、`backend/app/main.py`、依赖文件。
  - 验证：`backend/.venv/Scripts/python.exe -m pytest backend/tests -q`。
- [x] 前端：先写上传、切表、空态、错误与重复选择测试并确认失败；新增 ExcelPreview 组件与样式，在 App 中保留连接状态。
  - 文件：`frontend/src/ExcelPreview.tsx`、`frontend/src/ExcelPreview.test.tsx`、`frontend/src/App.tsx`、`frontend/src/App.css`、测试配置。
  - 验证：`npm test`、`npm run build`、`npm run lint`。
- [x] 集成：启动本机服务，通过 Vite 代理上传合成工作簿；核对 health、20 行截断和多个工作表。
- [x] 文档与复核：README 记录运行命令、环境变量、接口、计数规则、实际测试结果及限制；检查 diff，无无关改动，不自动提交或推送。

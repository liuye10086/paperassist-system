# R2 生信与其他组学报告入口实施计划

> 使用 subagent-driven-development 逐项实施和复核。用户已确认 R2，无需重复申请实施授权；本批不提交、推送或合并。

**目标：** 单细胞、注释/亚群、差异/富集/专题、Bulk 和现有其他组学入口采用 R1 的详细解读标准，选材、下载和交付保持一致。

**架构：** 新增 owner/project 范围的不可变 `bio_report_context`，精确固定原生选材。该上下文作为一个研究来源生成 finding；综合报告直接读取上下文的有序原图和明确结果表，不创建会重新缩放图片的逐图包装任务。解读、预算/账本、异步导出和发布复用 R1。

**技术：** FastAPI/Pydantic、PostgreSQL/Alembic、现有 Word/XLSX/ZIP 渲染器、React/TypeScript；Windows PowerShell。

## 全局约束

- 工作区 `C:/Users/86182/Desktop/paperassist-system`，分支 `feat/frontend-rework`，HEAD `3932384616b186d2ec3b1df7e3856c0c9365a56c`。保留 B1/B2/B3/R1 已有未提交修改。
- 不提交、推送、合并，不进入 R3，不重算原始分析，不恢复 PDF 报告输出。
- 原图/指定重绘、指定注释、主比较与有序附件、筛选口径、语言都必须固定；禁止隐式切换到最新注释或最新重绘。
- 中英文同一证据标准，七节正文和每图四类解释；正文不暴露代码、内部 ID、哈希或软件版本。原始结果和复现资料保持完整。
- 只有用户确认过的解读生成调用模型；prepare、GET 下载、离线重建、候选和发布不能新增付费调用。既有结果优先复用；不挪用不匹配的旧缓存。
- 客户/分析员权限、项目归属按服务端现有规则执行。分析员候选复用 `research_report_member`，不放宽系统 ZIP 的快照/发布禁令。
- 迁移和删除边界只先在隔离 PostgreSQL 验证；通过后才升级开发库并核对原数据保留。测试按影响面定向运行。
- 产品活跃页面的旧短版 Word 下载由新入口接替；旧兼容 API、原分析/资源复现 ZIP 和真实历史文件须单列，不能把动态生成冒充历史文件。
- 证据保存在忽略目录 `script/.runtime/reader-report-r2-20261115`。其中 `baseline/` 保存本批前 101 个已修改/未跟踪路径，用于限定 R2 差异。

## 入口覆盖

| 入口 | 必须保留的选择 | 目标 |
| --- | --- | --- |
| BioAnalysisResult：单细胞/亚群 | processed、明确原图或有序重绘、语言 | 共用详细报告 |
| SingleCellAnnotationWorkspace | processed、exact annotation、图和语言 | 注释事实与图片绑定 |
| InsightDelivery | result、原图或有序重绘、语言 | 差异/ORA/GSEA/专题详细报告 |
| BulkDelivery 与 Bulk 快捷 Word | 主比较、有序附件、selections、sensitivity、evidence、facts_digest、语言 | 同一固定口径、完整复现材料 |
| TabularAnalysisResult / 其他组学 | processed/source/行/图选择 | 进入同一详细报告链 |
| 分析员保存候选/客户冻结交付 | 明确报告成员及版本 | 原字节复用和范围限制 |

## Task 1：固定原生来源与公共导出适配

文件：新增 `backend/app/domain/bio_reader_reports/{__init__,contracts,materials,bulk,service}.py` 和 `backend/app/db/bio_report_context_schema.py`；修改研究来源契约/解析、事实投影、表格与报告冻结、文件引用/来源变更追踪；新增 `0083_bio_report_contexts` 迁移。

- [x] 只读盘点并确认复用路线，三份 inventory 写入运行目录。
- [x] 编写隔离用例并观察失败：不同注释/图序/语言不得复用；外项目来源拒绝；原图 SHA 和明确所选表保持；历史上下文不改成最新值。
- [x] 实现固定来源、幂等复用、源文件即时保护、SHA/归属重验。CSV 明确保存格式和扩展名，不能按 TSV 解析；历史 TSV 描述兼容。
- [x] 报告从唯一 context 装配原生图，禁止 context 与任意附加研究图混合；保留原顺序/字节。表格按 context 的明确选择导出，不递归扩成所有结果。
- [x] 隔离迁移升级/降级/重升、scope FK、seal、账号删除归属及文件阻断验证；运行聚焦后端测试并独立复核。读者说明已区分样本比较、空间点及细胞组成口径。开发库升级至0083后，原记录及249条文件引用SHA保持不变。

核心用例形态：`assert frozen['figures'][0]['document_image']['sha256'] == original_sha`；`assert exported_table_values == selected_original_rows`；跨项目请求返回 404/403，不能 fallback 到另一结果。

## Task 2：正式准备入口、兼容路径与交付/复现

文件：新增 `backend/app/api/bio_reader_reports.py` 及 service；修改 main/router 权限登记、原生报告/复现适配和需要的候选/冻结来源读取。

- [x] 准备契约使用严格的 processed / insight / bulk 联合选材，返回可复用的 `ResearchReportRequest` 与固定源回链；幂等键和未知提交查询可恢复。
- [x] 复用 R1 `ReaderReportService` 和 `ResearchReportService`，成功产物直接复用，不新造付费下载或另一套发布事务。
- [x] 旧原生 Word 兼容入口支持读取同一固定正式产物，活跃 UI 不再旁路旧短版。明确保存旧兼容语义，防止误称历史文件。
- [x] Bulk 完整复现包保留原有分析支持材料，报告与 XLSX 消费同一冻结正式成员；选定重绘/附件不能扩成未选成果。
- [x] 候选保存/冻结/发布使用同一 DOCX/XLSX，拒绝跨项目和权限不符；历史已冻结注释报告不因新注释变更而丢失下载。
- [x] 定向 API/交付测试并独立复核。

## Task 3：前端所有正式入口

文件：新增 `frontend/src/features/bio-reader-reports/` 共用面板/状态；修改 BioAnalysisResult、SingleCellAnnotationWorkspace、InsightDelivery、BulkDelivery、TabularAnalysisResult、相关导航/候选组件与测试。

- [x] 以失败的交互用例覆盖完整 selection 传递、语言变化失效、有序重绘、刷新/任务回链、未知请求恢复、客户与分析员边界。
- [x] 共用准备 → 外发/费用预览 → 显式生成解读 → 冻结导出 → 下载/保存候选流程；沿用 R1 状态机制。
- [x] 保留源页面返回上下文与已提交需求中的 requirement/scope/intent；另存不能把原生图 ID 当研究图 ID。
- [x] 单细胞/注释/专题/Bulk 活跃页面替换旧动态 Word 按钮；分析/资源原复现功能保留且名称说明准确。
- [x] 定向前端测试、TypeScript、受影响文件 lint 和生产构建；独立复核。

## Task 4：真实与隔离验收、收尾

- [x] 先查现有结果、合格解读和可复用报告；只对确有必要的未覆盖材料调用真实模型，记录调用数/tokens/估算及未结算用量。
- [x] 隔离合成数据覆盖指定注释/亚群、有序重绘、CSV、Bulk 口径及附件、其他组学来源、越权与历史下载。合成证据与真实数据/模型分开报告。
- [x] 实际检查中英文 Word/XLSX/成果包的内容、原图/表格、顺序与可读性；原生版式检查，不向用户交付 QA PDF。
- [x] 直接操作 Edge 复查正式入口、回链、选材变化、成功复用及实际下载；下载件与已验正式成员逐字节核对。
- [x] 全批次限定差异复核、git diff --check、分支/暂存区和数据保留核对；更新验收记录，停在 R2 等用户验收。

## 证据与进度

Task 1–4 已完成，整批独立复核通过，等待用户验收。完整范围、证据、用量和限制见 [R2 验收记录](2026-11-15-reader-report-r2-acceptance.md)。运行目录的 `progress.md`、各任务 report/review 和 `r2-final-review-report.md` 保留完整过程证据。

开发库已升级至0083，升级前原记录及249条文件引用实际SHA保持不变。后端针对性证据包含 Task 2 原13项、材料许可失效专项1项、流式下载与既有Bulk合约7项、普通重绘和任务回链4项；这些组有覆盖重叠，不相加为总测试数。报告最终展示领域组131项通过，中英文模型材料缓存标识保持。前端主组355项、复核修复149项、最后注释Back专项18项分别通过；TypeScript、lint、最终build和diff检查通过。

现有空间数据和16张原生图已经过两次真实解读，中英文任务与正式导出均成功。本批共146349 tokens，费用估算US$0.486237，供应方用量尚待结算。本次断点续作新增真实调用0次。中英文各23页Word、完整XLSX及复现包通过实际检查，Edge六个正式下载逐SHA一致。16图报告执行约8分钟，主要耗时在多阶段来源校验，暂未做性能优化。隔离蛋白组、外部差异、Bulk、轨迹与注释五类正式文件已验；浏览器固定选材、草稿、回链、权限和下载验收通过。隔离工程数据不替代真实科学或用户验收。

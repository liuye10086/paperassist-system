# 第五步：Word 分析报告导出

依据：需求 V0.13 §5.5–5.8、技术方案 V0.1 §5、§6.5、§14.1，结合当前 SQLite、FastAPI、React 实现。

## 范围与约束

- 当前小闭环第五步；中文 `.docx` 分析报告，不扩展到完整论文、学校模板、英文或 PDF。
- 直接复用当前配置版本的真实统计、已有 PNG、已核对的六段 AI 解释；不新增 OpenAI 调用。
- 内容包括数据概况、质量与排除规则、方法、统计表、带标签图片和图注、解释与依据、限制、来源记录。
- 不编造研究背景或推断检验结论；AI 草稿须人工审核，图中像素仍未经过自动核验。
- 导出保存在同一数据目录，源版本绑定且不可变；重复请求复用文件。旧导出可按其下载地址继续下载。
- 保存时再次核对源版本，原文件/图片哈希不匹配、数据缺失、磁盘错误返回明确反馈。
- 保留已有代码与用户数据，在当前工作目录实现；开发阶段不提交或推送，用户验收并明确授权后再提交；单一 requirements.txt、PowerShell 命令。

## 接口约定

沿用 base `/api/v1/projects/{project_id}/files/{file_id}/analysis-runs/{run_id}`。

- `GET /report`：`{current_revision: number|null, is_current: boolean, ready: boolean, issues: string[], report: Report|null}`。
- `POST /report`：严格请求 `{expected_revision: number, figure_id: string, explanation_id: string}`；响应同 GET；新建 201，复用 200。仅生成本地 DOCX，无任务轮询。
- `GET /report/{report_id}/download`：校验项目/文件/统计归属和 DOCX 哈希，返回附件；不因后续配置更新而拒绝旧报告。
- `Report`：`id, analysis_run_id, figure_id, explanation_id, setup_revision, source_sha256, figure_sha256, created_at, filename, size_bytes, sha256, language: 'zh-CN', engine: {id, python_docx}, input_sha256`。
- 不要求存在 API 密钥。GET 不执行生成，不访问云端。

## Task 1：后端与文档生成

先补失败用例，再实现 `report_docx.py`、`report_store.py`、`reports.py`。SQLite 迁移至 6，新增 reports 表和 reports 目录。python-docx 固定版本加入单一依赖文件。

文档采用简洁正式排版：Letter 纵向、2 cm 页边距、中文宋体/拉丁 Arial、正文 11 pt、黑色标题。两张注明指标类别的统计表避免过宽；表格重复表头、浅灰边框、自然换行、非固定行高。原 PNG 等比嵌入，图注可编辑。记录所有六段解释及事实依据和来源版本。缺失指标写“无法计算”，不补零。

验证 DOCX 内文、表格、媒体哈希、来源、空值/极值、版本冲突、重复/并发导出、持久化重启、旧报告下载、归属隔离、损坏/缺失文件和失败清理，不进行付费 API 测试。

## Task 2：前端导出面板

新增 `frontend/src/WordReport.tsx` 及测试，在 AnalysisExplanation 已保存解释之后挂载。Props：`base, runId, revision, figureId, explanationId, canGenerate, disabled, onBusyChange`；base 是文件 API base（不含 analysis-runs）。状态和接口见上。

展示“第五步 · Word 分析报告”、“生成 Word 报告”、“重新读取报告”和“下载 Word 报告”链接；说明直接整理已有结果、不再次调用 API、AI 文字需人工审核。展示版本、生成时间、文件大小和必要来源。旧结果标注版本，允许下载历史报告但禁止生成。生成不依赖 OpenAI 配置。请求有 30 秒超时、可重读恢复、错误信息、AbortController，切换文件/统计/解释时重置；防重复提交并通过 busy 锁定上层配置。不要自动重复 POST。

AnalysisExplanation 合并自身忙碌与报告忙碌，报告正在生成时禁止 AI 生成/重读；避免把报告自身 busy 再传给其 disabled 造成循环。已有解释 GET 成功后才挂载；解释变化应重挂载报告。

测试先行：生成→下载→重新挂载恢复、请求正确 IDs、无密钥也可导出、未保存/旧版本禁用、GET/POST 错误和超时恢复、切换中止、防重复点击、上层忙碌传递。只改相关前端文件，不重构网络层，不改后端/README，不提交。

## Task 3：整体验证与文档

代码审查；运行后端全套、前端全套、build、lint、pip check、diff check。使用隔离的已保存合成数据、真实 PNG 与解释进行 HTTP/浏览器导出下载、重启复读验证；不触碰用户项目目录。尝试 documents 技能 render_docx.py 并检查所有页；如本机缺少渲染器，记录准确限制，不能声称自动分页预览已验证。更新 README 的接口、运行、备份、测试结果和人工验收流程。

## 进度

- 设计与接口：已确定。
- 后端：完成；全量 211 项通过（新增 16 项报告测试）；图题重复编号修正后报告测试 16 项再次通过。
- 前端：完成；全量 78 项通过，build / lint 通过。
- 集成/审查/文档：浏览器无密钥生成及下载、实际 Uvicorn 重启、重复 POST 哈希保持一致；只读审查无阻断项，唯一图题重复编号问题已修正；README 已更新。
- 用户验收（2026-09-29）：已确认“选择已有解释 → 生成报告 → 下载并用 Word/WPS 核对 → 刷新/重启确认恢复 → 修改配置并重新统计、绘图、解释后导出新报告”通过。
- 限制：documents 的 render_docx.py 因本机缺少 LibreOffice 失败；DOCX 内容/XML/原图哈希已检查，Word/WPS 核对由用户手动验收覆盖，尚未系统验证所有数据场景和软件版本的排版兼容性。

第五步已验收，用户授权以“测试：word分析报告导出”提交并推送。剩余第六步：完整小闭环验收与收尾，等待用户确认后开始。

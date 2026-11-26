# PaperAssist-System Skills B09 整理与验收记录

**状态** · 2026-11-26 · 整理及定向验证完成 · 用户验收通过

B00–B03 在三条写作入口和统计解释接入规则与冻结机制，也用两个只读面板验证了 Skills 运行时。B05 接入报告详细解读，形成五条生成入口。B04–B08 已用这五条入口完成正文质量改进和验收。B09 检查哪些试点和过渡代码仍服务正常流程，在整理后用同一批材料核对读稿、续跑和交付。 [总领方案](2026-11-25-PaperAssist-Skills生成质量提升总领方案.md#b09--项目整理与收口--最后一批) · [B08 用户验收](2026-11-26-PaperAssist-Skills-B08三模块留出验收记录.md#8-用户验收与-b09-交接)

## 1. 整理清单

| 项目 | 使用与依赖 | 处置和影响 | 恢复点 |
| --- | --- | --- | --- |
| Bulk 固定 QC/PCA 试点 | `BulkFixedPreview` 是 `GET /bio-processed-datasets/{version_id}/bulk-fixed-preview` 的唯一界面调用。报告和重绘直接使用正式固定成员。 | 删除面板、接口、权限表条目和 `bulk-result-reading`。QC 页仍可直接看样本质控表，PCA 页默认打开样本得分并可切换方差表。逐样本缺失比例和 PCA 分组、批次图数据从同页下载原 JSON。 [正式结果页](../../../frontend/src/features/bioinformatics/TabularAnalysisResult.tsx) · [接口回归](../../../backend/tests/api/test_bio_bulk_fixed_results.py) | 恢复前后端试点、运行时条目和配套 manifest。 |
| 单细胞固定组成试点 | `FixedCompositionReading` 是 `GET /bio-insight-results/{version_id}/composition-preview` 的唯一界面调用。正式结果已有供者层级、分析方法和 `composition_results.tsv`。 | 删除面板、接口、权限表条目和 `single-cell-composition-reading`。正式结果优先打开组成结果表，保留供者数、方向、调整后 P 值、原表下载及推断边界。 [正式结果页](../../../frontend/src/features/bio-insights/InsightResults.tsx) · [接口回归](../../../backend/tests/api/test_single_cell_fixed_composition.py) | 恢复前后端试点、运行时条目和配套 manifest。 |
| Skills 设置与发布检查 | API、Worker 的同源配置、Worker 指纹及发行包校验仍有调用方。 | 配置示例列五条生成工作流，旧环境中的两个退役选项被忽略。启动校验复用正常加载。更新 Worker 指纹和启动测试夹具。活动的七个 Skill 文件及其资源逐字节一致，两项退役版本摘要进入历史。 [运行时](../../../backend/app/domain/runtime_skills/runtime.py) · [发行文件回执](../../../script/.runtime/pa-skills-b09/release-skills-files.json) | 与代码一同恢复清单和清单 pin。 |
| 统计解释、写作和报告冻结 | 统计 Worker 生成后即覆盖一份基础指令，SCI 和学校写作追加相同的证据要求。报告有一个无人调用的策略包装函数。 | 统计 Worker 直接使用已冻结指令。SCI 和学校写作在原顺序共用同一拼接。删除未用策略函数。报告复用比较允许整包摘要变化，继续匹配实际选中的技能、指令、材料摘要和模型策略。 [统计执行](../../../backend/app/domain/figure_workbench/execution.py) · [写作冻结](../../../backend/app/domain/manuscript_writing/frozen.py) · [报告复用](../../../backend/app/domain/reader_reports/service.py) | 按受影响文件恢复，复查同一冻结材料和原回执。 |
| 旧 OpenAI 适配器 | `CloudPlot.start`、`CloudExplanation.start` 无生产调用方。新提交走 `ModelGateway`，历史绘图和解释还有取回调用。 | 删除两个提交方法和专属测试。保留旧回执取回、绘图文件下载及现行网关所引用的合同。 | 分别恢复两个旧 adapter 方法及相关测试。 |
| 测试夹具、开发记录和本机材料 | B08 原件、响应、对照稿和回放日志用于质量验收和复现。 | 试点测试迁到正式结果入口。网关集成用例显式依赖隔离 PostgreSQL 夹具，Worker 路径测试使用常规临时目录。B01、B03 历史记录注明当前入口。 | 复查已归档证据及定向用例。 |

根据整理前快照和当前工作树比较，B09 涉及 42 个非文档路径，源码、配置和规则净减 470 行，计入测试净减 573 行。 [逐文件对照](../../../script/.runtime/pa-skills-b09/code-comparison.json)

## 2. 验证结果

| 核对项 | 结果 |
| --- | --- |
| 五条生成路径与 Word | `STAT-02`、`REPORT-02`、`REVIEW-02`、`SCI-02`、`THESIS-02` 复用 B08 原始响应回放通过。五组模型请求和响应字节一致，导出 Word 正文文字和嵌图像素一致。原报告的 XLSX 和 ZIP 仍可下载。真实模型调用 0 次。 [逐例对照](../../../script/.runtime/pa-skills-b09/b08-replay-equivalence.json) · [统计回放](../../../script/.runtime/pa-skills-b09/b09-analysis-replay/replay.log) · [报告最终回放](../../../script/.runtime/pa-skills-b09/b09-report-final-replay/replay.log) · [SCI 回放](../../../script/.runtime/pa-skills-b09/b09-sci-replay/replay.log) · [学位论文回放](../../../script/.runtime/pa-skills-b09/b09-thesis-replay/replay.log) |
| 正式结果和报告复用 | 隔离库 19 项通过。包括指派分析员读取 Bulk 样本 QC 与原 PCA 表，撤权及跨项目拒绝，文件摘要和损坏报告，单细胞原始组成值、分页与下载。只替换整包摘要后，报告继续命中已有解读，旧确认和新确认均返回原记录。 [API 回归](../../../script/.runtime/pa-skills-b09/b09-api-final/regression.log) |
| 统计审批、历史回执与 Word | 隔离库 8 项通过，覆盖配置停用时禁止新提交、已受理任务恢复，以及 v7/v8 版本的生成、读稿和原图交付。 [统计集成回归](../../../script/.runtime/pa-skills-b09/b09-statistics-regression/regression.log) |
| 后端解释、写作冻结与网关 | 解释、写作和适配器 1,156 项，Skills 运行时 21 项，网关隔离库 37 项通过。旧 OpenAI 适配器覆盖成功取回、超时及脱敏，现用网关覆盖提交与账本。 [后端定向回归](../../../script/.runtime/pa-skills-b09/backend-domain-final.log) · [运行时回归](../../../script/.runtime/pa-skills-b09/runtime-green.log) · [网关回归](../../../script/.runtime/pa-skills-b09/b09-gateway-regression/regression.log) |
| 前端、启动与发行 | 前端 6 个文件 107 项通过，TypeScript 和隔离目录 Vite 构建成功。启动 6 项、Worker 32 项、发行脚本 14 项通过。Worker 复跑使用常规临时目录，解决了用户主目录不可写导致的用例超时。发行预检复用 B02 已核对的镜像 ID 和 20 个锁定字体，使用 B09 新构建的前端。候选源清单含 7 个活动 Skill 对应的 9 个文件。 [前端用例](../../../script/.runtime/pa-skills-b09/frontend-final.log) · [构建](../../../script/.runtime/pa-skills-b09/vite-final-build.log) · [启动用例](../../../script/.runtime/pa-skills-b09/launcher-regression.log) · [Worker 用例](../../../script/.runtime/pa-skills-b09/worker-final-repeat.log) · [发行用例](../../../script/.runtime/pa-skills-b09/release-regression.log) · [发行预检](../../../script/.runtime/pa-skills-b09/release-preflight.json) |

首轮网关测试漏加载隔离夹具，在本机开发库生成一组替身数据。按本次创建时间和固定测试 ID 核对后，已在事务内移除该组合成项目、任务、调用和用量事件。测试账号 `gateway@test.local` 已停用，创建与停用的审计记录保留。应用测试已改为要求隔离数据库夹具，并在隔离库通过。 [本机恢复回执](../../../script/.runtime/pa-skills-b09/gateway-dev-recovery.json) · [隔离夹具验证](../../../script/.runtime/pa-skills-b09/gateway-missing-fixture.log)

## 3. 回退方式和验证范围

整理前基线为 `feat/runtime-skills@d8f3429` 的 B08 已验收工作树，其中包括当时未提交的改动。已经逐一核对恢复包的 135 个文件摘要。需要回退时只恢复涉及条目的源文件、测试和相应 manifest，脚本按需要恢复固定清单摘要，再核对 API、Worker 与前端版本。已受理任务按原快照续取，已有分析和成果保持原版本。使用旧统计预览且尚未提交的请求，在版本切换后重新打开预览确认。 [整理前快照](../../../script/.runtime/pa-skills-b09/before.zip) · [逐文件摘要](../../../script/.runtime/pa-skills-b09/before.json)

本批为本机定向与隔离回归，包含发行预检，临时测试容器已退出。用户验收范围为当前工作树，生产启用、全量回归和生产规模 P95 仍按各自发布范围验证。未暂存、提交或推送。

## 4. 本机材料盘点

原件、已交付稿、备份及 B08 固定复现实例均保留。以下两组早期失败日志可按实际留存需要单独确认。每个目录均只有 `regression-cleanup.json`、`regression-environment.json`、`regression.log`。保留它们便于回查失败阶段，两组场景均已有最终通过日志。

| 本机目录 | 精确大小 | 内容 |
| --- | ---: | --- |
| [`report-import-red`](../../../script/.runtime/pa-skills-b08/report-import-red) | 5,705 B | 文库数和特征数缺口的红测。 |
| [`report-import-repeat-red`](../../../script/.runtime/pa-skills-b08/report-import-repeat-red) | 6,191 B | 重复扫描源文件的红测。 |

## 5. 用户验收与提交确认

2026-11-26 用户确认 B09 验收通过。验收覆盖两处试点退役、正式结果页和原件读取、历史任务恢复、五条生成链路的原响应回放及本机发行预检。B04–B09 的验收均已完成，生产规模验证沿原发布范围处理。

B04–B09 拟在 `feat/runtime-skills@d8f3429` 的现有工作树上一次提交，范围为代码、Skills、配置示例、测试和开发记录。原件、样稿、备份和运行证据在本机留存。提交信息和逐文件范围待用户确认，确认前保持未暂存、未提交、未推送。 [生成质量总领方案](2026-11-25-PaperAssist-Skills生成质量提升总领方案.md)

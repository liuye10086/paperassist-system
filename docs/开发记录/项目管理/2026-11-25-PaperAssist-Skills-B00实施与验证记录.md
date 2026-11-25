# PaperAssist-System Skills B00 实施与验证记录

**验收状态** · 2026-11-25 · B00 用户验收通过，并已确认启动 B01

本批按已确认的[总领方案](2026-11-25-PaperAssist-Skills技能系统总领方案.md)固定最新主线和两条离线试点对照，修复一处报告测试夹具。B01 的技能目录、路由和执行功能在下批实施。

## 1. 实施基线

| 项目 | 本轮核对 |
| --- | --- |
| Git | 在 `feat/runtime-skills` 上执行，HEAD、本地及跟踪的 `main` 与 `git ls-remote` 返回的远端主线同为 `5de3df8c219c4cd0db325b1a45a9c9dcedd9926b`。基线包含 `1273a84` 和 `5de3df8` 的论文与 Bulk 更新。 |
| 数据库 | 源码迁移头为 `0094_sci_revision_chat`，开发库 `public` 的 Alembic 版本只读核对一致。接口测试使用现有专用 PostgreSQL 测试库和独立 `pa_test_*` schema，按仓库测试夹具构建并清理。 [源码迁移头](../../../backend/app/db/database.py) · [隔离夹具](../../../backend/tests/conftest.py) |
| 开发 Worker | 原开发 Worker 健康，镜像 `paperassist-5aa27c31a6a9-worker:local`，ID `sha256:5627b4a64e34a793c9aa8d7c5fffa024810ff233ad58d2df40ab0d2679950c9b`。固定图表用例使用同一镜像的科学解释器、当前仓库代码的只读挂载和断网容器。 |
| 渲染 | 当前源码报告 `research_report_v1`，代码摘要 `9a06e9ae035f1323fe614ae50f4b3883af0b9d1ea56841b6100063d6bbdb6704`。拼版 `research_bitmap_v1`，代码摘要 `28950ed3ddaba3dd8127ad39fbfacf408b594620fb0fbccfaa9943ea6314c0ba`。原开发 Word 渲染服务的容器镜像 ID 为 `sha256:4880ea8c9d8738d824d58e611fe2e83e894cb2abd75f1ff3be119340c15497a8`，Docker 报告健康。 [报告渲染](../../../backend/app/adapters/research_report_render.py) · [拼版渲染](../../../backend/app/adapters/research_figure_render.py) |
| 本地测试工具 | Python 3.11.4、pytest 8.4.2、python-docx 1.2.0，Node.js 22.15.0、Vitest 3.2.4。Bulk 接口复测用已有隔离目录加载 Matplotlib 3.10.7，依赖锁与常驻服务沿用原配置。 |

## 2. 生信报告导出夹具

修复[导出测试](../../../backend/tests/api/test_bio_reader_report_export.py)对已退役 `authorize_user_and_project` 的导入和调用。修复前单独收集用例可复现 `ImportError`。修复后沿现有报告政策夹具、外发预览、显式同意和模型替身执行。当前模型启用配置为关闭时仍由现有接口拒绝入队。 [当前报告授权测试](../../../backend/tests/api/test_reader_report_narratives.py)

两条导出用例继续验证上下文和选中图绑定、并发幂等、错误任务恢复范围、版本历史、DOCX/XLSX/ZIP 下载、离线重建和历史文件逐字节读取。第三条验证已固定的报告语言。业务代码与断言口径沿用主线。

## 3. 固定回归材料

### 3.1 SCI 叙述性综述初稿

**可重建的离线对照**使用仓库已有测试 `test_customer_narrative_review_exports_suggested_excerpts_and_review_structure`。从客户 `narrative_review` 项目进入，用 `CitationNcbi(3)` 注入书目和摘要，再走选文献、冻结事实稿、预览、按次数授权、写作任务、候选读取和 Word。记录只读摘要范围，输出主题段绑定真实存在的测试证据别名，引用出现在 Word，候选保持待复核。预览前无模型调用，替身收到与冻结预览完全相同的一次请求。团队改过的主题合章另由 `test_sci_template_combines_review_topics_in_the_confirmed_chapter` 对照。两项本轮均通过。 [SCI 主链](../../../backend/tests/integration/test_customer_sci_to_word.py) · [合章用例](../../../backend/tests/api/test_sci_simple_draft.py) · [检索替身](../../../backend/tests/api/test_literature_citations.py)

**可回读的真实公开材料参考**沿用 11 月 17 日的成人心脏叙述性综述，目录为 `script/.runtime/manuscript-real-qa/`。本轮读取留存记录，核对 5 条摘要和收据里的 8 处摘录记录。保留的 PMID 顺序为 `32971526`、`35959412`、`35732739`、`37438528`、`32403949`。历史收据中的 5 个 DOI 均有书目比对记录。实际 DOCX 与保留的导出收据一致，内部包完整，含 `Bedi KC Jr`。 [11 月 17 日验收范围](2026-11-17-SCI与毕业论文客户工作台-B01-B04用户验收记录.md)

| 相对归档目录的文件 | 实际 SHA-256 |
| --- | --- |
| `pubmed.json` | `a3423a148aa277984d99e951f0a5d4cd4eb3bb938c64bdc2bd030fa0cebcf59c` |
| `literature/pubmed-source-audit.json` | `7e11144ade74df0ac5d329e83deb95ea2e898b63e886b3408f191d1fbca69094` |
| `review-clean-export.json` | `c9edaf15351dab84710dfbd56c85251c996ce219c88ca85a0d6bde77f2819a3e` |
| `outputs/SCI-Adult-human-heart-narrative-review-clean.docx` | `1e15d165217358d22ce1fbeb8265ea1bd058bb26fcd296763767272943d66157` |

B01 的回归以仓库内替身样本为执行输入。公开历史归档作为文献范围和 Word 对照，留在原位置。模型真实质量、各篇摘要再使用和外发的权利在 B02 按实际用途核对。

### 3.2 Bulk RNA-seq 固定 QC/PCA

**工程对照**复用现有 `processed_fixture(..., assay='bulk_rna_counts')` 和 `published_bulk`。输入为 3 个特征与 6 个合成样本，样本顺序固定为 `B0, B1, B2, A0, A1, A2`。使用 `tabular_quantitative_v1` 与计数输入，normalization、transform、scaling 均为 `none`，无预设排除，`pca_components=10`，实际保存 2 个主成分。用于交付支线的对照为 `B_A`，独立两组，拟合系数由工程替身提供。 [输入和导入确认](../../../backend/tests/api/test_bio_quantitative_lifecycle.py) · [固定比较及报告夹具](../../../backend/tests/helpers/bio_report_contexts.py)

| 一次成功运行的身份 | 固定记录 |
| --- | --- |
| 合成测试项目 | `c5673428-3033-4ec9-846a-13a5cd887fd4` |
| 处理任务及版本 | `85c21718-128d-5e0a-a275-6d4e8dc61641` · `81fae09e-874f-5185-bb4e-8448467a63ff` |
| 发布的处理清单 SHA-256 | `1eebcaaf7945915b923447b089c5b2c585e2d1616138e2ff8aaad9acc19ebc2d` |
| 比较任务及版本 | `99b969ae-3d14-5a12-a645-7c7ebb693da8` · `1b4187e7-4a3b-5dd3-81f2-9042061da9ce` |
| 发布的比较清单 SHA-256 | `60d2b2d3454afe15e33ad253e4278dc79f6e1d1cf1cf303394735c6bed58c196` |

归档位于 `script/.runtime/pa-skills-b00-bulk-e2918951/test_bulk_preparation_uses_nat0/b00-bulk-baseline/`。其中 `baseline.json` 的 SHA-256 为 `fb648ee26e7a13cc01089d9a9e5a9ce5e068c811a90250fec52353c9b29a43dd`，同目录保存两份发布清单、8 个源成员和三个预览的完整配置与预期数据。回归测试会重新分配隔离 schema 和项目 ID，样本输入与预览断言可重建。上表 ID 对应本次已归档样本。

| 主要源成员 | SHA-256 |
| --- | --- |
| `qc_missing_data.json` | `46ec49992991028b1d4d4000246475148c1041e79f15512de4db9c6bc95c038e` |
| `pca_data.json` | `2da37fe8715510f11aaf0765cb3701528874260ef72325a191f3c5024c952d99` |
| `pca_scores.tsv` | `b61f3e001d6aa3e09d499151f9f59bb3627e7c5538cb1a987b009f3eae6caa58` |
| `pca_variance_ratio.tsv` | `1c12eb434d5cee025173e073c28accfe672a9474b164771dbcbac93cafab70e8` |
| `model_counts.tsv` | `f092fdc04a34ff0b463fe026f5640552a94c772735f01a388c5ae6da7c5e70b7` |
| `comparison_results.tsv` | `c9e5eb051aadb138233ca4c807b2f994091527761bfc6a1f45abccd80610bd10` |

对归档字节重新调用现有 `bulk_plot_data` 核对 `qc_missing`、`pca_scores` 和 `pca_variance`。六个样本缺失率均为 0，PC1/PC2 的方差比例为 `0.986929200789437`、`0.013070799210562981`，逐样本得分见 `baseline.json`。该步骤只读固定成员。断网用例还用仓库内 `processed` 夹具覆盖非零缺失、QC 和 PCA 的不同样本轴及 PCA 不可计算分支，可脱离本机归档重跑。 [适配器](../../../backend/app/adapters/bio_insights_engine/bulk_figures.py) · [固定值用例](../../../backend/tests/numeric/test_bio_b05_figures.py)

原处理成员仍经 `bio-processed-datasets/{version_id}/members/{member_id}/download` 读取，原比较成员经 `bio-insight-results/{version_id}/members/{member_id}/download` 读取。当前预算回归验证报告按整表保留比较和筛选表，说明省略数量，并确认原 `model_counts` 下载响应及 SHA-256。B08 的 `airway`、`pasilla`、`fission` 仍作为历史真实分析证据，本机文档所列 B08 归档路径本轮未定位到。 [处理下载](../../../backend/app/api/bio_analysis.py) · [比较下载](../../../backend/app/api/bio_insights.py) · [预算回归](../../../backend/tests/api/test_bio_reader_report_bulk.py) · [B08 证据边界](../阶段04/2026-11-11-Bulk-B08-真实数据独立参考与兼容验收记录.md)

## 4. 定向验证结果

| 范围 | 结果与覆盖 |
| --- | --- |
| PostgreSQL 隔离集成 | **15 项通过**。旧夹具导出 3 项，叙述授权与幂等 3 项，SCI 综述和主题合章 2 项、流式改稿 1 项、旧金额型授权拒绝 1 项、SCI/毕业论文拼版基准版本与旧渲染器 3 项、Bulk 原报告与工作簿预算 2 项。用 TestClient 跑实际 API、存储和测试库，业务 Worker 入口进程内执行。 [流式改稿](../../../backend/tests/integration/test_customer_sci_draft_revision.py) · [旧授权](../../../backend/tests/api/test_manuscript_writing_live.py) · [拼版](../../../backend/tests/api/test_sci_figures.py) |
| 后端离线单测与合同 | **23 项通过**。模型流式回执与续取、拼版版本、报告预算 15 项，Bulk 显示范围和业务合同 8 项。 [流式模型](../../../backend/tests/adapters/test_frozen_writing_stream.py) · [预算](../../../backend/tests/domain/test_research_reports.py) · [显示合同](../../../backend/tests/domain/test_bio_b05_display_contracts.py) |
| 断网 Linux 固定值检查 | **8 项通过**。验证 QC/PCA 固定值绘制、真实成员哈希与不可计算状态，测试阻断分析重算。业务层的三个合同用例最初和科学测试混跑，科学解释器缺业务 DB 库和挂载清单，改用应用环境后通过，计入上行的 8 个合同用例。 |
| 前端 | **5 个文件、80 项通过**。SCI 初稿、流式改稿、拼版、Bulk 工作流与读者报告。运行在 jsdom，使用接口替身。 [初稿](../../../frontend/src/features/customer/SciDraftGenerator.test.tsx) · [改稿](../../../frontend/src/features/customer/SciDraftRevision.test.tsx) · [拼版](../../../frontend/src/features/customer/CustomerSciFigures.test.tsx) · [Bulk](../../../frontend/src/features/bio-insights/BulkWorkflow.test.tsx) · [报告](../../../frontend/src/features/bio-reader-reports/BioReaderReport.test.tsx) |

后端本轮定向通过共 **46 项**。Bulk 的两个接口用例最初在 Windows 应用解释器内缺绘图库，在 QC 阶段失败。复用了已在 `script/.runtime/bulk-report-test-wheels/site` 的隔离依赖，原有测试完整复跑 **2/2**。一次额外取证尝试错用了比较下载响应的 `filename` 字段，已改为从通过的原用例留存产物核对并归档。正式用例始终使用原断言。

重跑入口见各用例链接。Windows Bulk 接口用例在 `backend` 下使用现有 `.venv`，仅对测试进程将上述 `site` 加入 `PYTHONPATH`。 `--basetemp` 指向 Git 忽略目录内的独立路径。其他 Windows 集成用例依赖仓库的隔离 PostgreSQL 测试夹具。Linux 固定值用 `/opt/paperassist-bio-insights/bin/python`，只读挂载代码和测试目录，启用 `--network none`。本批未调用真实模型或外部文献服务。

## 5. 待验证与交接

| 待确认或验证 | 阶段 |
| --- | --- |
| 新 Skills 的注册、组合、按需加载、任务追踪、启停、旧任务兼容，以及正常业务入口的权限回归。 | B01，使用本文已固定的两份工程对照。 |
| 真实账户、允许外发的公开资料和留存条件、单次模型调用和预算上限、目标部署的网络出口。发行 Compose 的默认配置关闭实时写作和 NCBI。 [发行配置](../../../compose.release.yml) | 进入 B02 真调用前确认。历史公开摘要收据只用于对照，相关授权按本次用途复核。 |
| 真实 PubMed/GPT、SCI 科学审读、真实 Bulk 样本回读、Edge 实走、Word/WPS 原生版面、队列负载和服务发布回滚。 | B02 分项验证。B00 的组件测试、离线替身和独立数据库覆盖不推导真实结果。 |
| 有无 Skills 的 Token、时延和实际费用。 | B02 用同模型、同材料和相同目标对照，B00 保存实验基线，不把定向测试用时当产品耗时。 |

本批只修改测试夹具与项目文档。原业务代码、现有开发数据与常驻服务按原配置运行。冻结材料保存在原历史归档和独立测试运行目录，用户验收本批后确认启动 B01。 [B01 实施与验证记录](2026-11-25-PaperAssist-Skills-B01实施与验证记录.md)

# PaperAssist-System Skills B04 质量基线与评审记录

**批次** · 2026-11-26 · B04 固定基线、样本和评分表

**状态** · 2026-11-26 · 用户验收通过

**范围** · 数据分析、SCI 和毕业论文的五条正文生成路径。每条固定一例改进材料和一例留出材料，供 B05–B08 按同题原稿比较。

## 1. 为什么固定这批材料

B00–B03 建通了 Skills 运行时、授权、任务和原件交付。B02 的 SCI 两份真实综述原稿都漏掉了固定摘录中的 6 个和 8 个心脏区域，后续才在 Word 副本补齐。B03 验证了统计解释和两类写作能产出合法结构、保住重要数字及交付原件。B04 把这些原稿和已知缺口固定下来。后续每次改规则，都可以核对客户实际读到的正文具体进步在哪里。 [生成质量总领方案](2026-11-25-PaperAssist-Skills生成质量提升总领方案.md) · [B02 对照](2026-11-25-PaperAssist-Skills-B02实施与验证记录.md) · [B03 收口](2026-11-25-PaperAssist-Skills-B03收口与验收记录.md)

本机核对的代码基线为 `feat/runtime-skills@d8f3429418a210aacfafa581536f5cee5a532c8e`。它与本地 `origin/feat/runtime-skills` 跟踪引用一致，本地 `main` 为 `5de3df8c219c4cd0db325b1a45a9c9dcedd9926b`。B04 的样本、评审表与原始回执在本机 `script/.runtime` 留存。材料清单以路径、字节数和 SHA-256 标识已核对的文件，沿用原件可避免重复生成。 [本机基线清单](../../../script/.runtime/pa-skills-b04/基线清单.json) · [盲评表](../../../script/.runtime/pa-skills-b04/评审表.md)

## 2. 五条现有入口

| 正文入口 | 实际角色与提交 | A 版开关和模型输入 | 成果 |
| --- | --- | --- | --- |
| 固定统计图件六节解释 | 本人项目或有效指派的分析员，在统计结果的图表工作台用 `/figures/{figure_id}/explanation-preview` 核对材料，再用 `/explanations` 确认。 | `statistical_explanation` 启用 `statistical-reading@1.0.0`，并使用生效管理配置或 `PAPERASSIST_EXPLANATION_POLICY_FILE`。外发包括固定事实、逐节事实引用和有效指令。PNG 摘要用于审批和成果绑定。 | 图表工作台及任务工作区读取六节，原图与解释可进既有报告 Word。 [解释审批](../../../backend/app/domain/figure_workbench/skill_approval.py) · [现有测试](../../../backend/tests/integration/test_statistical_skill_approval.py) |
| 研究报告详细解读 | 作者在项目成果的报告选材中确认版本和已选图件。生信可先走 `/bio-reader-reports/prepare`，再由 `/research-report-narratives/preview` 和同路径提交。 | 原 `reader_report_v1` 指令，真实调用受 `PAPERASSIST_READER_REPORT_MODEL_ENABLED`、生效管理配置和策略约束。送模型的是报告事实投影和选定图件原 PNG。 | 七段报告正文及逐图解读绑定当前版本，正式报告提供 Word、XLSX 和 ZIP。 [接口](../../../backend/app/api/reader_reports.py) · [材料投影](../../../backend/app/domain/reader_reports/content.py) · [现有测试](../../../backend/tests/api/test_bio_reader_report_api.py) |
| SCI 叙述性综述首稿 | 所属客户在 SCI 文献与初稿入口选已确认文献和摘录，预览、授权、生成。 | `sci_narrative_review`，冻结全文任务规则、结构、文献别名和用户实际选入的摘录。 | 待复核稿、正文和 Word。 [工作台](../../../frontend/src/features/customer/SciDraftGenerator.tsx) · [现有测试](../../../backend/tests/integration/test_customer_sci_to_word.py) |
| SCI 研究论文首稿 | 所属客户确认底稿、方法资料、结果资料和已绑定图件后生成。 | `sci_research_article`，冻结方法与结果的来源角色、数字位置、文献与图题说明。 | 待复核稿及固定图件 Word，可核对计划与已报告结果。 [写作冻结](../../../backend/app/domain/manuscript_writing/frozen.py) · [读稿 API](../../../backend/app/api/sci_draft_reader.py) |
| 毕业论文学校模板首稿 | 所属客户绑定确认过的学校模板，整理资料和文献，核对外发预览后生成。 | `thesis_initial_draft`，冻结学校章节用途、章级语言、材料和固定图件说明。已有稿的修订沿各自的合同。 | 待复核稿、章级读稿、固定图件 Word 及历史版本。 [学校首稿](../../../backend/app/domain/manuscript_writing/school_live.py) · [现有测试](../../../backend/tests/integration/test_customer_thesis_to_word.py) |

三条写作都走 `writing-previews`、`writing-authorizations`、`writing-requests` 和现有写作 Worker。已选 Skills 由 `PAPERASSIST_SKILL_WORKFLOWS` 启用，写作真实调用还需要 `PAPERASSIST_WRITING_LIVE_ENABLED=1`、有效服务端配置与账号授权。原冻结写作请求和当前网关的材料摘要各有用途，本批分别留证。 [写作 API](../../../backend/app/api/manuscript_writing.py) · [写作开关](../../../backend/app/domain/manuscript_writing/policy.py) · [提交网关](../../../backend/app/domain/model_usage/gateway.py)

## 3. 10 例固定样本及原稿复用

| 入口 | 改进样本 | 保留给独立复核 | B04 固定基线时的原稿情况 |
| --- | --- | --- | --- |
| 统计图件解释 | `STAT-01` · 英文描述性折线及原统计口径差异。 | `STAT-02` · 中文回归森林图。 | B03 原响应、六节和固定图件摘要在库。A 候选按原固定图、英文、v8 指令与 `gpt-6.1-sol` 复用。输入预留 24,000、输出上限 6,000，原请求材料摘要 `997077cb…`。 |
| 研究报告解读 | `REPORT-01` · Bulk 比较结果、阈值敏感性及已选富集重绘。 | `REPORT-02` · 固定单细胞轨迹结果。 | 两例有合成源材料、固定结果、外发结构和导出回执。正文由合成替身返回，A 版真实原稿留到相应批次。 |
| SCI 叙述性综述 | `REVIEW-01` · 两段公开心脏图谱摘要。 | `REVIEW-02` · 合成摘要与已冻结书目。 | B02 启用版原 Word 和读稿可按 `c6556ad8…` 复用。`gpt-6.1-sol`，输出上限 12,000，输入配置上限 100,000。当前加载的规则和资源重组出同一请求。旧关闭版是历史同题对照，Word 补写稿有独立回执。 |
| SCI 研究首稿 | `SCI-01` · B03 合成测量练习、方法与结果资料及固定图。 | `SCI-02` · 独立上传的合成协议、结果日志和示意图。 | B03 原候选的模型正文与原 Word 可按 `d140689…` 复用。需保留该批管理附加指令、`gpt-6.1-sol`、24,000 输入配置上限与 12,000 输出上限。 |
| 毕业论文首稿 | `THESIS-01` · B03 合成测量记录论文及双语学校章节。 | `THESIS-02` · 合成双语记录规范论文。 | B03 成功任务的原响应、读稿及 Word 可按 `3336de96…` 复用。需保留该批管理附加指令、模型及原预算。Word 含七个可写章和两个受保护章。早期失败任务与本地回放 Word 单独保留。 |

四份历史原稿是有条件的 A 版候选。每组实际开评前按清单核对原材料、版本、模型、语种、附加指令和调用设置。B02 综述保留了候选读稿、Word 与调用回执，本机档案缺独立的供应商原响应包。SCI 和毕业论文的 B03 原稿仍处于待科学审阅状态。合成样本的结论适用于相应夹具。B04 固定基线时，五份留出和 `REPORT-01` 共六例缺少可评分的真实 A。`REPORT-01` 的真实 A 已在 B05 补齐，五份留出材料用于 B08。 [样本与原稿索引](../../../script/.runtime/pa-skills-b04/基线清单.json) · [B05 原稿对照记录](2026-11-26-PaperAssist-Skills-B05数据分析生成质量记录.md)

两份报告的冻结请求已看到证据投影缺口。`REPORT-01` 已包含预过滤阈值与特征排除状态，解释该排除所需的特征总计数与具体原因在原表。`REPORT-02` 已包含轨迹汇总及图件，逐细胞伪时间、权重、样本文库信息仍在本地固定材料。B05 可按报告问题补投影。评分表逐项记源材料是否支持、请求是否包含及正文是否覆盖。 [数据分析材料索引](../../../script/.runtime/pa-skills-b04/domains/analysis/cases.json) · [评审表](../../../script/.runtime/pa-skills-b04/评审表.md)

## 4. 盲评与批次通过条件

1. 冻结同一份原材料、模板、图件和结果版本。记录 A/B 实际送达的证据、模型、输出语种和生成预算。材料投影属于该次改动时，写明变更的证据项。保存两份未经人工修改的正文和对应读稿或 Word。
2. 由组织评审的人随机给两稿分配甲、乙。使用同一呈现格式，保留段落、引用和图号。先逐项查必写事实和证据位置，再看论证和表达，最后揭晓版本。评审者按预先固定的维度评分。
3. 关键数字、计算口径、引用和证据边界必须正确，可证实的必写事实全部覆盖。每条评分项按 0 缺失、1 有提及但依据或推理不足、2 具体且可追到原材料记录。改进例和留出例都须通过硬门槛，目标项有带段落证据的进步，其余关键项无退化。
4. 保存评语、判定、原稿路径、模型使用量、耗时和费用。授权/结果绑定、代表 Word 或原件回读同时过关，再给出入口验收结论。B04 评分表空栏用于后续成对原稿，当前没有给替身正文评质量分。 [本机盲评表](../../../script/.runtime/pa-skills-b04/评审表.md)

## 5. 其他入口与 B09 整理候选

以下是代码和界面核查结果，待使用量与典型问题确认优先级。

| 实际入口 | 核查结果及优先级 |
| --- | --- |
| 分析推荐、统计绘图和旧版解释 | 分析推荐有独立模型策略和任务，以建议方法、列角色和待确认事项为主。部分绘图走 `submit_plot`，旧解释也有独立 Worker。发生建议列错配、统计口径错配或图件质量问题时，先固定典型样本再决定批次。 [推荐页](../../../frontend/src/features/analysisPlan/AnalysisRecommendation.tsx) · [绘图执行](../../../backend/app/domain/figure_workbench/execution.py) · [旧解释执行](../../../backend/app/domain/tasks/explanation_execution.py) |
| 文献辅助、学校规则建议 | 文献辅助有单独冻结的公开材料调用路径，学校规则建议需 `PAPERASSIST_SCHOOL_RULE_MODEL_ENABLED`。两者的输出用于核对和采用，呈现在正文入口之前。优先保持选材、引文和校规输入到首稿的准确性。 [文献辅助执行](../../../backend/app/domain/literature_assistance/execution.py) · [学校规则建议](../../../backend/app/domain/school_templates/suggestion_execution.py) |
| SCI、毕业论文的改写与复核 | 现有定向改写和流式建议复用写作网关的各自冻结合同。科学与语句复核接口另有人工核对和规则校验。优先保护已有稿和确认记录。可用同一稿的范围外变更或来源遗漏作后续验证点。 [改写合同](../../../backend/app/domain/manuscript_writing/frozen.py) · [复核 API](../../../backend/app/api/manuscript_writing.py) |
| 期刊适配和外审修订 | 可从既有工作台组织交付和修订。期刊适配执行有独立规则，外审修订工作流有独立任务。先按实际是否生成新的业务正文核对使用场景，再安排质量样本。 [期刊适配执行](../../../backend/app/domain/journals/adaptation_execution.py) · [外审修订执行](../../../backend/app/domain/review_rounds/revision_execution.py) |

1. `BulkFixedPreview.tsx` 和 `FixedCompositionReading.tsx` 已接在结果页并受各自工作流开关控制，读取原件无模型提交。B09 首先核对正常结果页、报告选材和指派角色是否使用同样的数据。重叠展示优先合并，保留仍被依赖的结果接口及成员下载。 [Bulk 结果页](../../../frontend/src/features/bioinformatics/TabularAnalysisResult.tsx) · [单细胞结果页](../../../frontend/src/features/bio-insights/InsightResults.tsx) · [工作流开关](../../../backend/app/domain/runtime_skills/runtime.py)
2. 统计解释的 v5 内容合同与 v8 Skills 审批同时参与冻结和历史回读。先查当前指令来源和重复组装点，简化新预览。历史任务涉及的版本和摘要按原回执核对。 [内容合同](../../../backend/app/domain/figure_workbench/explanation_v5.py) · [冻结与回读](../../../backend/app/domain/figure_workbench/skill_approval.py)
3. `CloudPlot` 和 `CloudExplanation` 仍有历史响应 `fetch` 的调用点，当前统一网关另有提交适配器。B09 可先列出旧提交方法、共享 schema 与轮询调用方，再确定能移除的代码。 [旧绘图回读](../../../backend/app/domain/boxplot.py) · [旧解释回读](../../../backend/app/domain/explanations.py) · [现用网关](../../../backend/app/domain/model_usage/gateway.py)

## 6. 变更、验证与回退

正常生成路径沿用代码基线。修复 `test_bio_reader_report_api.py` 中对已删除的 `authorize_user_and_project` 的导入和调用，测试继续走当前报告材料、显式确认和任务授权。改动限于该测试夹具。 [修正位置](../../../backend/tests/api/test_bio_reader_report_api.py)

| 已完成项 | 结果 |
| --- | --- |
| 已有契约测试 | 5 项通过。含统计图固定版本与 Word 原件、生信 Bulk 报告闭包、SCI 综述与研究首稿、毕业论文初稿和历史读回。 [测试日志](../../../script/.runtime/pa-skills-b04/baseline-4/pytest.log) |
| 补充样本探针 | 3 项通过。含统计留出样本的固定事实与六节阅读、轨迹报告留出样本的原表和图件、SCI 独立协议与结果来源的 Word 回读。 [测试日志](../../../script/.runtime/pa-skills-b04/holdout-2/pytest.log) |
| 材料复核 | 10 个样本均核对源文件。重算四份历史 A 候选的请求或材料摘要，并核对六份通过用例的替身回执、请求摘要与归档文件。 [基线清单](../../../script/.runtime/pa-skills-b04/基线清单.json) |

定向测试经过已登录的正常 HTTP 入口和 Worker，使用原有依赖镜像、其中的生信绘图依赖、两份仓库生信依赖锁和隔离 PostgreSQL。完成后已移除本批临时容器。此次模型新提交 0 次，费用 US$0。Word 验证覆盖内容、嵌图和下载，实际 Office/WPS 排版和全量回归此批未跑。 [主验证环境](../../../script/.runtime/pa-skills-b04/baseline-4/environment.json) · [留出验证环境](../../../script/.runtime/pa-skills-b04/holdout-2/environment.json)

如需撤销 B04，只需按文件恢复这次的测试夹具与评审记录。原始稿件、成果、配置和历史响应沿现有版本保留。合成替身回归用于证明入口和材料绑定，B05–B08 的 A/B 原始稿用于判断内容质量。

## 7. 用户验收与 B05 交接

2026-11-26 用户确认 B04 的固定基线、样本清单及评分表验收通过。B05 使用 `STAT-01`、`REPORT-01` 的固定材料与评审标准完成对照和补验，同日获用户验收。 [B05 验收记录](2026-11-26-PaperAssist-Skills-B05数据分析生成质量记录.md#8-用户验收与-b06-交接) · [生成质量总领方案](2026-11-25-PaperAssist-Skills生成质量提升总领方案.md#b05--数据分析的统计解释与报告解读)

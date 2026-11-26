# PaperAssist-System Skills B05 数据分析生成质量记录

**批次** · 2026-11-26 · 固定统计解释与研究报告详细解读

**状态** · 2026-11-26 · 用户验收通过

B05 使用 B04 固定的原图和事实改进模型生成的正文。统计解释说明比较的量、两类记录口径及结果能支持的结论。研究报告说明主要发现、对应的原表或图件和影响解读的限制。 [B04 基线与评审记录](2026-11-26-PaperAssist-Skills-B04质量基线与评审记录.md) · [生成质量总领方案](2026-11-25-PaperAssist-Skills生成质量提升总领方案.md)

## 1. 实现

| 入口 | 客户和分析员会看到的变化 | 实现与边界 |
| --- | --- | --- |
| 固定图六节解释 | 六节分别承担说明阅读目的、样本口径、处理方法、数据模式、解释边界和论文表述的任务。数字要说明来自哪些记录，报告的效应和不确定性要和原方法及总体对应。 | 首轮 `statistical-reading@1.1.1` 用简短示例替换了整套句架。`1.2.0` 进一步调整论文段的行文和引用要求，准确的坐标、处理细节和证据引用继续保存在对应栏目。已确认的 v8 请求继续使用原快照。 [规则](../../../SKILLS/statistical-reading/SKILL.md) · [冻结及回读](../../../backend/app/domain/figure_workbench/skill_approval.py) |
| 报告详细解读 | 开头给出主要发现，再说明比较方向、数量级及对应的表或图。质量控制交代排除或筛选的时点、原因及结果影响。 | `research-report-reading@1.0.1` 接入原预览和 Worker，提供已选比较的预过滤事实及小型轨迹的伪时间、权重和覆盖关系。`1.0.2` 将同一排除理由集中在质量控制，沿用同一事实投影、七段正文和逐图结构。 [规则](../../../SKILLS/research-report-reading/SKILL.md) · [表证据投影](../../../backend/app/domain/reader_reports/table_evidence.py) |

新增报告投影只传递有限的科学字段。逐样本计数、细胞条码和样本名称仍由原结果交付。大轨迹表保留结果行数和原有汇总。已知选入样本数仅统计原表明确记录的标签，留空的样本身份按缺口处理。外发预览显示明确的检验排除与原因。模型沿所选的图件字节和已确认请求生成，恢复任务时保留冻结文本，重新读取匹配的原图校验摘要。 [材料及图件](../../../backend/app/domain/reader_reports/content.py) · [报告提交与历史读取](../../../backend/app/domain/reader_reports/service.py) · [外发预览](../../../frontend/src/shared/components/ReadableDetails.tsx)

统计指令吸收了开源 K-Dense `statistical-analysis` 2.0 对估计对象、观测单位、效应、不确定性和诊断边界的组织方式，并按 PaperAssist 的固定事实重新撰写。采用的是写作方法，计算、依赖和业务校验沿项目现有实现。源版本为 `c21d13b3cc2894680229ba9959a53281acb9200e`。 [上游固定版](https://github.com/K-Dense-AI/scientific-agent-skills/blob/c21d13b3cc2894680229ba9959a53281acb9200e/skills/statistical-analysis/SKILL.md) · [MIT 许可](https://github.com/K-Dense-AI/scientific-agent-skills/blob/c21d13b3cc2894680229ba9959a53281acb9200e/LICENSE.md)

## 2. 同题对照条件

- `STAT-01` 复用 B03 的真实英文原稿。新旧图件 PNG 的 SHA-256 均为 `0720cac7ee772184a5132d9ff9e708fad25d9e3e7ae862bf54e81fd80f02f860`，模型事实逐项一致。两版都是 `gpt-6.1-sol`，输入预留 24,000、输出上限 6,000。新解释使用隔离项目重建的同源图件，旧图本身保留已有解释回读。 [历史原稿](../../../script/.runtime/pa-skills-b03/closeout/model/records/statistics-workspace.json)
- `REPORT-01` 复用 B04 固定合成源、比较选择与富集重绘。原五张 PNG 的字节与顺序均通过核对。两次隔离运行的确认时间、样本别名和内部标识不同，去除这三类差异后，旧臂模型科学材料与 B04 一致。真实 A/B 使用同一个科学选择、`gpt-6.1-sol`、英文、输入预留 200,000 和输出上限 8,000。新臂额外带入表证据与 Skill 指令。已付 A 原正文原样重放用于同一隔离上下文的正式成果导出。 [本机 B04 材料](../../../script/.runtime/pa-skills-b04/基线清单.json) · [报告请求和原图核对](../../../script/.runtime/pa-skills-b05/live-pairs-2/report-01-preflight.json)
- `STAT-02` 与 `REPORT-02` 保留给留出评审。B05 离线核对了轨迹报告投影，统计留出沿用 B04 固定材料。两例的真实配对评审随 B08 执行。

## 3. REPORT-01 真实原稿与盲评

旧稿和新稿都通过 `reader_report_v1` 产品校验。独立评审先看甲乙正文，按固定事实检查后给分。揭晓结果为甲=A、乙=B。 [甲稿](../../../script/.runtime/pa-skills-b05/blind/REPORT-01-甲.md) · [乙稿](../../../script/.runtime/pa-skills-b05/blind/REPORT-01-乙.md) · [揭晓记录](../../../script/.runtime/pa-skills-b05/REPORT-01-unblind.json)

| 评分维度 | A | B | 可在原稿中核对的差别 |
| --- | --- | --- | --- |
| 开篇主线、比较与不确定性 | 1 | 2 | A 从样本、质控和 PCA 起笔。B 第一段直接写出 B 相对 A 的主要发现，带上效应量、标准误及校正范围。 |
| 质量、阈值与结果影响 | 1 | 2 | 两稿均说明同一拟合在阈值收紧后失去两项筛选结果。B 进一步解释 f3 保留在处理矩阵，模型输入总计数 6，低于检验前阈值 10，因此未检验。 |
| 图表、原表与验证局限 | 2 | 2 | 两稿都把图形观察和精确原表数值分开，说明富集重绘所展示的两条合成术语和验证边界。 |
| 学术结构和去重复 | 1 | 2 | B 将研究问题、质控选择和主要发现串起来，篇幅相近，局限和读者提示的内容更集中。 |
| 合计 | **5/8** | **8/8** | 该分数适用于本组合成样本。 |

B 的必写事实均有出处。富集源的 `fixed-sets.gmt` 夹具确实含两个术语，文字中关于人类分类的陈述应理解为资源物种设置。B 已说明样本、估计器和分析均用于合成验证。两版的 Word、XLSX 和 ZIP 已按成员摘要回读，Word 内嵌的五张图与固定图像素一致，ZIP 中原 PNG 字节全部吻合。A 第一次生成完成后，导出任务排在另一条解读任务之后。本机复核按串行顺序完成两条解读，再使用原 A 响应导出，无第二次 A 提交。 [旧版 Word](../../../script/.runtime/pa-skills-b05/live-pairs-2/report-01-a.docx) · [新版 Word](../../../script/.runtime/pa-skills-b05/live-pairs-2/report-01-b.docx) · [B 的读稿回执](../../../script/.runtime/pa-skills-b05/live-pairs-2/report-01-b-readback.json)

## 4. STAT-01 真实原稿与盲评

固定工作表的投影含 5 条源记录、4 条绘图有效记录、1 条绘图排除记录。另有 3 条原统计有效记录。两稿均使用同一 A/C 图件及固定观测，列单位和独立参与人数保持未知。甲乙评审完成后揭晓甲=B、乙=A。 [甲稿](../../../script/.runtime/pa-skills-b05/blind/STAT-01-甲.md) · [乙稿](../../../script/.runtime/pa-skills-b05/blind/STAT-01-乙.md) · [揭晓记录](../../../script/.runtime/pa-skills-b05/STAT-01-unblind.json)

| 评分维度 | A | B | 可在原稿中核对的差别 |
| --- | --- | --- | --- |
| 主问题和比较 | 1 | 2 | B 说明是观察纵轴值随横坐标如何变化。A 罗列变量范围和图型。 |
| 记录数及观察单位口径 | 1 | 2 | B 把绘图 4 条和原分析 3 条放进同一段说明，两者取决于不同入组条件。A 将两种记录数直接并列，区分口径的说明在后文。 |
| 真实模式和限制 | 1 | 2 | B 概括横轴增大时纵轴值下降，并保留四个坐标及相应记录数。A 给出了坐标，由读者自行归纳趋势。两者均保留描述性解释边界。 |
| 论文段整合与学术表达 | 0 | 1 | B 用同一句组织两个总体的记录数，并承接主要模式。仍有冒号式事实标签和较多程序核验措辞。 |
| 合计 | **3/8** | **7/8** | 两稿的关键数值与推断范围均通过检查。 |

统计的两次模型响应均完成。产品原校验先拒绝了两份稿，主要原因是完整句谓语、绑定坐标的连接方式和明确否定独立性的表达。定位后扩大了少量可识别的中性句式，仍检查固定引用、数值口径和肯定性科学断言。第二次真实原响应随后原样通过产品 Worker 校验及工作区回读，共六节，覆盖全部 42 个必需事实引用。重放使用同样的事实、指令和图件，新增模型提交 0 次。首次响应和两次原始任务状态均留存。 [首次供应商回执](../../../script/.runtime/pa-skills-b05/live-pairs-1/stat-01-b-provider-response.json) · [第二次供应商回执](../../../script/.runtime/pa-skills-b05/live-pairs-2/stat-01-b-provider-response.json) · [原响应重放](../../../script/.runtime/pa-skills-b05/stat-replay/stat-01-b-replay.json) · [工作区读稿](../../../script/.runtime/pa-skills-b05/stat-replay/stat-01-b-workspace.json)

原分析的 Pearson 方法和 B 列只出现在本机源材料。为了复用精确历史 A，两版保持同一冻结统计事实，评分记录保留此证据缺口。该统计图为同字节工程占位图，正文趋势由固定坐标核对。

## 5. 定向测试与调用台账

| 验证 | 结果 |
| --- | --- |
| 统计 v5 正负控 | 879 项通过，含绑定坐标、明确否定独立性、肯定疗效排除及历史校验。 [日志](../../../script/.runtime/pa-skills-b05-statistics/pytest-english-guard-green.log) |
| Skills、报告内容和模型适配 | 48 项通过。包含已选 Bulk 投影、小型轨迹行及图片实际请求合同。 |
| 产品定向回归 | 10 项通过，覆盖冻结报告开关切换、旧响应复用、已选图片顺序、Bulk 原件、统计授权撤回和旧响应续取。 [日志](../../../script/.runtime/pa-skills-b05/regression-2/pytest.log) |
| 固定材料预检与重放 | 3 项预检及 1 项统计原响应重放通过。报告留出用例验证四行的伪时间与权重，未把缺少样本标签解释为零。 [预检日志](../../../script/.runtime/pa-skills-b05/pair-preflight-final/pytest.log) · [重放日志](../../../script/.runtime/pa-skills-b05/stat-replay/pytest.log) |
| 前端报告与外发预览 | 22 项组件测试通过，新增验证明确排除状态和阈值原因的呈现。 |

| 真实提交 | 输入令牌 | 输出令牌 | 台账估算费用 | 任务结果 |
| --- | ---: | ---: | ---: | --- |
| `STAT-01` 首次 B | 2,148 | 963 | US$0.014999 | 供应商完成，产品拒绝部分连接语。 |
| `REPORT-01` A | 44,935 | 5,743 | US$0.169766 | 产品校验通过。复用原正文完成正式导出。 |
| `STAT-01` 第二次 B | 2,297 | 848 | US$0.014221 | 供应商完成，修正表达校验后原样重放通过。 |
| `REPORT-01` B | 45,425 | 5,623 | US$0.169791 | 产品校验、读稿及正式导出通过。 |
| 合计 | 94,805 | 13,177 | **US$0.368777** | B03 统计 A 直接复用，四次计费提交均有回执。 |

实际调用走隔离的认证 API、任务 Worker 和官方模型适配器。按实际用量与本项目冻结费率列费用。已清理本批临时数据库和容器。DOCX 验证覆盖内容、内嵌图与下载。验收结论只覆盖所列样本及定向用例，五个入口的独立留出质量按 B08 执行。 [第一轮真实日志](../../../script/.runtime/pa-skills-b05/live-pairs-1/pytest.log) · [第二轮真实及导出日志](../../../script/.runtime/pa-skills-b05/live-pairs-2/pytest.log)

## 6. 启用和回退

`PAPERASSIST_SKILL_WORKFLOWS` 在原列表中加入 `research_report_reading` 可启用新版详细解读，现有 `statistical_explanation` 使用更新后的统计规则。报告仍走现有真实模型开关、策略和确认流程。回退新报告时从列表去掉 `research_report_reading`。统计需要保留启用状态时，恢复已验收版本的统计 Skill 和配套清单。已有响应沿对应的已保存请求与任务继续读取。重启或发布前用项目的 Skills 命令校验包和清单。 [配置示例](../../../backend/.env.example) · [清单](../../../SKILLS/manifest.json) · [退回方案](2026-11-25-PaperAssist-Skills生成质量提升总领方案.md#6-统一回退和确认)

## 7. 客户反馈后的表述补验

`STAT-01` 初版论文段被要求复述全部结果和限制，成稿还会逐项插入事实字段名。新版论文段只要求绑定研究范围、图型、记录口径、主发现和相关科学限制。代表性的无缺口数字折线可在论文段引用首末坐标，结果栏仍展示完整坐标，解释栏仍包含全部限制。已保存稿、在途任务和纯样式复用按所绑定的规则版本处理。

同一图件及冻结事实下，新论文段由 422 个英文空白分词缩到 64 个，保留了 4 条绘图记录、3 条原统计记录和从 `(1, 9)` 到 `(4, 6)` 的观测变化。`Variable scope:`、`Applicable limitation:` 等字段标签退出论文段。新模型原响应第一次保存时因趋势谓语和明确否定独立性的措辞被误拒。修正这些误判后，已付响应按原指令和输入原样重放，六节工作区读回成功。旧版 `1.1.1` 原响应也在当前代码下重放成功，读回六节与原记录一致。 [前后原文](../../../script/.runtime/pa-skills-b05/prose-comparison.md) · [新版重放](../../../script/.runtime/pa-skills-b05/prose-new-replay/stat-01-b-replay.json) · [旧版重放](../../../script/.runtime/pa-skills-b05/prose-legacy-replay/stat-01-b-replay.json)

`REPORT-01` 使用同一份科学材料、五张原图和模型策略。新版只在质量控制集中说明一次 `f3` 仍在数据中、六个入模样本的总计数为 6、最低要求为 10，因此检验前排除且没有差异检验结果。新版 Word 中提及 `f3` 的段落从 6 段减到 2 段，另一段是来源特征清单。新版通过报告校验、Word 和打包下载回读。 [新版 Word](../../../script/.runtime/pa-skills-b05/prose-live/report-01-b.docx) · [产品读回](../../../script/.runtime/pa-skills-b05/prose-live/report-01-b-readback.json)

补验通过 926 项定向领域测试、10 项认证产品回归、3 项固定材料预检及新旧统计各 1 项原响应重放。真实新提交各 1 次，统计 US$0.014559、Bulk US$0.165054，合计估算 US$0.179613。B05 累计 6 次，估算 US$0.548390。补验结论适用于这两例固定材料，独立留出样本仍按 B08 评审。 [领域测试](../../../script/.runtime/pa-skills-b05/prose-domain.log) · [认证回归](../../../script/.runtime/pa-skills-b05/prose-regression/pytest.log) · [预检](../../../script/.runtime/pa-skills-b05/prose-preflight/pytest.log)

## 8. 用户验收与 B06 交接

2026-11-26 用户确认 B05 验收通过，范围包括固定统计图解释和 Bulk 报告解读的改动、成对原稿、表述补验及本批定向验证。`STAT-02` 和 `REPORT-02` 的留出对照按计划在 B08 执行。下一批 B06 涉及 SCI 叙述性综述和研究稿，待用户明确确认开工。 [B06 范围](2026-11-25-PaperAssist-Skills生成质量提升总领方案.md#b06--sci-综述及研究稿的论证)

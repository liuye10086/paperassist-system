# PaperAssist Skills B08 三模块留出对照与交付验收

**状态** · 2026-11-26 · 五组对照、定向修复和两项补验完成 · 用户验收通过

## 1. 来由与范围

B04 固定了五个用于独立复核的留出样本。B05–B07 各自用改进样本调整统计解释、报告解读、SCI 两种初稿和毕业论文初稿。用户验收 B07 后确认开展 B08。本批用留出材料检查改进能否延伸到之前未参与调参的样本，同时核对三个模块的客户或分析员能否继续读取并交付成果。 [总领方案](2026-11-25-PaperAssist-Skills生成质量提升总领方案.md#b08--三模块留出对照与交付验收) · [B04 固定材料](2026-11-26-PaperAssist-Skills-B04质量基线与评审记录.md#3-10-例固定样本及原稿复用) · [B07 用户验收](2026-11-26-PaperAssist-Skills-B07毕业论文章节质量记录.md#7-用户验收与-b08-交接)

| 留出样本 | 材料与核对重点 |
| --- | --- |
| `STAT-02` | 中文回归森林图。核对建模对象、OR 和置信区间、模型口径及适用限制。 |
| `REPORT-02` | 单细胞轨迹固定报告。核对图表、逐细胞伪时间和权重、唯一文库及证据边界。 |
| `REVIEW-02` | 合成协议摘要的英文叙述性综述。核对摘要范围、文献归属、关键资料与推论限度。 |
| `SCI-02` | 独立的合成方法协议、结果日志和固定示意图。核对实际来源、方法与结果区分、效应量和讨论。 |
| `THESIS-02` | 合成双语论文、学校确认章序和受保护字段。核对两份摘要、正文论点、图件和 Word。 |

## 2. 实施顺序

1. 使用 `d8f3429418a210aacfafa581536f5cee5a532c8e` 的应用和 Skills 作为 A。B 取工作树内 B05–B07 已验规则。逐组核对原件、材料范围、正常授权与 Worker 冻结请求。A/B 使用相同模型和组内输出上限，登记本轮改动涉及的证据投影。
2. 在本机隔离环境通过合成夹具检查请求和成果路径。五组留出材料未发现可直接复用的真实 A/B 原稿。沿用已授权的模型配置，每组各提交两份固定请求。实际发送内容限于 B04 合成材料、已固定图件及其来源线索，按响应 ID 续取并保存原稿、耗时和用量。
3. 用原始响应在产品路径读回正文、Word 和原件。检查分析员及客户的正常授权、旧版本回读和关闭工作流后已冻结任务的使用。只对当前交接中可复现的缺陷做定向修改和回归。
4. 按 B04 量表匿名复核正文。记录证据硬门槛和评分区别，指出未通过项的处置和回退，交用户验收。项目级整理按 B09 的确认范围开展。

## 3. 固定请求和实际交付

A 从 `d8f3429` 导出应用、迁移及 Skills，只读挂载到测试容器。B 使用当前分支工作树。用独立 PostgreSQL 和项目已有 Word 渲染镜像运行。五组均使用 `gpt-6.1-sol` 和组内相同输出上限。写作三组的选材、语种和输出结构一致，差异在规则。统计两版使用同一份工作簿、同一张冻结森林图和同一零变更质控确认。报告两版使用同一轨迹结果和图件，新版还获得逐细胞轨迹表投影。 [固定请求对照](../../../script/.runtime/pa-skills-b08/pair-checks) · [历史源码存档摘要](../../../script/.runtime/pa-skills-b08/baseline-d8f3429/archive.sha256)

通过实际登录、角色分配、材料确认和 Worker 在隔离环境冻结请求。仅将验过摘要的固定请求发往 OpenAI。取得响应后，在无网络的隔离环境按同一冻结请求原样交给 Worker。试运行替身只用于核对请求、权限和下载。原响应、客户端读稿与 Word 分别留存。SCI 和毕业论文的原图、身份字段与模板留在本机，模型请求使用已选的文字和图件上下文。详细报告请求含同一张合成轨迹 PNG。 [调用与文件摘要](../../../script/.runtime/pa-skills-b08/usage.json) · [B04 固定材料](../../../script/.runtime/pa-skills-b04/基线清单.json)

| 入口 | 实际角色和产物 |
| --- | --- |
| `STAT-02` | 客户项目的指派分析员确认固定图，回读正常工作台的六节内容和论文段，下载原 PNG、原 XLSX、图件包及统计 Word。新版论文段在工作台显示 95% 区间和按单位的比值比。集合 Word 使用现有方法、结果、解释栏目，核对码值及两端区间。Word 嵌图经过 RGB 转码，逐像素同原图；原件入口和图件包保持原 PNG 字节。 [A 版读稿](../../../script/.runtime/pa-skills-b08/analysis-a4-export/STAT-02/replay/reading.json) · [B 版读稿](../../../script/.runtime/pa-skills-b08/statistics-final-delivery/STAT-02/replay/reading.json) · [B 版 Word](../../../script/.runtime/pa-skills-b08/statistics-final-delivery/STAT-02/replay/report.docx) · [最终回放日志](../../../script/.runtime/pa-skills-b08/statistics-final-delivery/replay.log) |
| `REPORT-02` | 客户项目下的指派分析员使用固定报告预览、授权与成果。原样重放两份，分别回读七节正文并下载 Word、XLSX 和 ZIP。四张源表及原 PNG 与 B04 固定件一致。无关联用户被拒绝。 [A 版 Word](../../../script/.runtime/pa-skills-b08/analysis-a2/REPORT-02/replay/report.docx) · [B 版 Word](../../../script/.runtime/pa-skills-b08/analysis-b2/REPORT-02/replay/report.docx) |
| `REVIEW-02` | 项目客户使用选定书目完成英文综述首稿，可在读稿、历史和 Word 中回读唯一引文与冻结 e1。非成员请求读稿和 Word 返回 `404`。 [A 版 Word](../../../script/.runtime/pa-skills-b08/sci-a/REVIEW-02/draft.docx) · [B 版 Word](../../../script/.runtime/pa-skills-b08/sci-b/REVIEW-02/draft.docx) |
| `SCI-02` | 项目客户的协议和日志为独立上传，下载原件逐字节一致。读稿、历史和 Word 保留图 1A，两版 Word 内嵌同一 B04 PNG。非成员请求读稿和 Word 返回 `404`。 [A 版 Word](../../../script/.runtime/pa-skills-b08/sci-a/SCI-02/draft.docx) · [B 版 Word](../../../script/.runtime/pa-skills-b08/sci-b/SCI-02/draft.docx) |
| `THESIS-02` | 项目客户上传学校模板、确认章级语种和样式，使用自己的冻结稿和历史下载。修订版通过提交前相同请求和原响应回放，核对宋体 14 pt、二级章、原 PNG 和四条跨项目拒绝。 [A 版 Word](../../../script/.runtime/pa-skills-b08/thesis-a-fixed/THESIS-02/draft.docx) · [B 版 Word](../../../script/.runtime/pa-skills-b08/thesis-b-cited-verified/THESIS-02/draft.docx) · [读稿和原件核对](../../../script/.runtime/pa-skills-b08/thesis-b-cited-verified/THESIS-02/delivery.json) |

## 4. 复现和修正

### 毕业论文协议引文

A 和 `thesis-writing@1.1.2` 都收到了 e1，模型未生成句级锚点，正文和书目都漏掉这一来源。`1.1.3` 要求在已选、与问题相关的协议摘要支持某句话时，陈述所供协议及可证实的结果缺口，并绑定该句的冻结证据。重用完全相同的输入和生成上限，补验原稿在绪论、工程讨论交付三处引文和一条编号参考文献，两种摘要保留 8 条的计划口径。合成来源原始返回的摘要只有被选中这一句，稿中的“该摘要”对应这个已核对范围。保留旧版本冻结回读所需的历史清单项。 [修订规则](../../../SKILLS/thesis-writing/SKILL.md) · [原版遗漏核查](../../../script/.runtime/pa-skills-b08/thesis-b/THESIS-02/delivery-structure-recheck.json) · [修订版回执](../../../script/.runtime/pa-skills-b08/thesis-b-cited-verified/THESIS-02/delivery.json)

### Logistic 森林图的证据和交付

初轮模型说明能辨认非截距效应，但两版发送材料均缺模型归一后的二元结局编码和冻结图的横轴参考线。新版 `statistical-reading@1.2.1` 把结局的拟合编码和固定图参考线带入确认。原始类别标签未加入外发。数值和坐标来自原统计结果与冻结绘图配置。旧任务按原 Skill 版本重建材料。 [固定证据投影](../../../backend/app/domain/figure_workbench/explanation_v5.py) · [三版请求差异](../../../script/.runtime/pa-skills-b08/analysis/STAT-02-three-versions.json)

真实新版候选的论文段通过校验，其余说明里的常用词撞上了旧规则。例如“参”有 Unicode 数字值，而“参数”在这里是普通词。修正了词法误判，并让新版 Logistic 森林图的前五节直接从对应的冻结事实生成。真实论文段仍使用模型原文及事实替换。原 `1.2.0` 及修正前 `1.2.1` 的失败回执仍可查。 [修正前拒绝回执](../../../script/.runtime/pa-skills-b08/analysis-b6/STAT-02/replay/receipt.json) · [定向复现](../../../script/.runtime/pa-skills-b08/logistic-delivery-red.log)

原模型输出仍须是完整的六个非空文本字段。论文段必须绑定实际绘制的非截距效应及相应科学限制，单提模型规模或拟合指标无法代替核心结果。回归覆盖无内容、过长文本、拟合指标替代效应、旧 `1.2.0` 投影和新输出历史回读。 [字段回归](../../../backend/tests/domain/test_explanation_v5.py) · [旧版本回归](../../../script/.runtime/pa-skills-b08/statistics-historical-final/regression.log)

首次成功回读仍出现同一参数名称重复和区间只显示原始字段的情况。最终论文段用一次参数身份加比值比和 95% 置信区间表达主要结果，分类变量保留冻结参照水平，连续变量写明按单位的含义。完整 beta、Wald P 和诊断在核对栏目保留。固定解释交代截距基线、区间宽度和事件优势与概率的关系。重放继续使用首次修订的同一真实响应与同一冻结请求。 [首次回读中的重复](../../../script/.runtime/pa-skills-b08/analysis-b6-verified/STAT-02/replay/reading.json) · [对应回归](../../../script/.runtime/pa-skills-b08/logistic-manuscript-red.log)

## 5. 首验盲评与覆盖结果

逐组按 B04 预设事实和深度维度评审。评审收到同格式的匿名成稿及固定评分表。描述原图或下载、语种及学校样式的分项另以交付物核对。分数来自本批留出样本，适用于各自题目。

| 样本 | A → B | 内容证据与判断 |
| --- | --- | --- |
| `STAT-02` | 4/10 → 7/10 | 新版工作台论文段给出 Exposure 每增加 1 单位的 OR `9` 和 95% CI `2.15086–37.6593`，支撑栏目说明 OR=1 参考线、1/0 编码、非截距绘图和优势与概率的区别。原图标题可核对合成材料标注。盲评正文仍未直接点明本例区间较宽及独立样本验证边界。 [最终盲评](../../../script/.runtime/pa-skills-b08/blind-final/statistics-review.md) · [最终读稿](../../../script/.runtime/pa-skills-b08/statistics-final-delivery/STAT-02/replay/reading.json) |
| `REPORT-02` | 6/10 → 9/10 | B 用轨迹原表写出四个细胞的相对伪时间 `0、1、2、3`、权重均为 `1`、全覆盖，区分图上 PCA 投影和表内排序。保留了单分析单元、未确认细胞标签和缺少独立重复的边界。上游原始档的文库数、样本标记与特征数仍未进入批准的专题请求，固定必写项未全覆盖。 [盲评](../../../script/.runtime/pa-skills-b08/blind/report-review.md) |
| `REVIEW-02` | 8/8 → 8/8 | 两版均提到唯一的协议摘要及其无研究结果属性，引文和书目正确。新版更明确指出可综合的是协议类型与范围，无法比较不同研究的结果。未观察到分数提升。 [盲评](../../../script/.runtime/pa-skills-b08/blind/sci-review.md#review-02) |
| `SCI-02` | 10/10 → 10/10 | 两版将协议计划的 9 张、日志报告的 7 张分别归源。新版讨论指出需要逐卡执行记录来区分实际未完成和漏记。盲评文字各 9/10，随后核对两版的独立上传记录、候选图件绑定及相同原 PNG，完成余下图件分项。 [盲评](../../../script/.runtime/pa-skills-b08/blind/sci-review.md#sci-02) · [新版原件索引](../../../script/.runtime/pa-skills-b08/sci-b/SCI-02/materials.json) |
| `THESIS-02` | 5/10 → 8/10 | 新版把选定的合成协议引入绪论和讨论，明确该摘要无研究结果。中英文摘要均保留 8 条计划，结论守住缺少实际记录的边界。盲评标出的摘录范围已查合成原响应，选中的一句就是该 fixture 的完整摘要正文。 [盲评](../../../script/.runtime/pa-skills-b08/blind/thesis-review.md) · [摘要原件](../../../backend/tests/helpers/literature.py) |

`REPORT-02` 的 B04 原包与 B08 原包 SHA-256 均为 `af0ae9fea50d26e1260ab0dc6ee4e4e99ad11079a95adc36f6293ea5b0bbd7b6`，源矩阵 2 个特征 × 4 个细胞，导入声明为一个合成文库 `L1` 与一个样本 `S1`。专题表四行的样本字段均为空，其唯一分析单元也无样本分配。从这一个分析单元无法推断独立生物样本数。B05 已登记这项报告上下文范围，B08 首验沿用相同选材，专题导出和四行表证据均已通过。首验的上游元数据覆盖未通过，补验结果见第 7 节。 [原输入夹具](../../../backend/tests/helpers/bio_report_topics.py) · [专题样本表](../../../script/.runtime/pa-skills-b08/analysis-b2/REPORT-02/topic_selection.tsv) · [首验请求差异](../../../script/.runtime/pa-skills-b08/pair-checks/REPORT-02.json)

## 6. 用量、回退与验证范围

五对留出原稿 10 次新提交。毕业论文协议引文与统计森林图证据各验证一次，首验累计 **12 次**，费用按正式返回的缓存及输入输出用量估算 **US$0.282282**。全部获得终态原响应，耗时 15–419 秒。本机按原响应 ID 续取和离线重放不增加提交。补验的增量和总计见第 7 节。 [用量台账](../../../script/.runtime/pa-skills-b08/usage.json) · [模型官方单价](https://developers.openai.com/api/docs/models/gpt-6.1-sol)

需要退回新生成规则时，恢复 `statistical-reading@1.2.0` 或 `thesis-writing@1.1.2` 的对应规则和清单。保留读取 `1.2.1` 和 `1.1.3` 成果所需的版本兼容代码。已冻结任务按持有的规则版本重建材料，在用初稿、原图和响应 ID 沿原版本回读。测试在本机隔离环境完成。生产负载、跨学科材料、生产灰度及其他 Office 版本仍按各批次的既有验证范围处理。

| 定向回归 | 结果 |
| --- | --- |
| 统计 v5 六节、中文用词、旧冻结稿与真实候选 | 最终 886 项通过。 [日志](../../../script/.runtime/pa-skills-b08/explanation-final.log) |
| 跨三个模块的正常入口与历史成果 | 初轮合并回归 34 项通过。统计授权、恢复和已有 Word 回归另跑 14 项通过，最终森林图实际回放通过。 [合并日志](../../../script/.runtime/pa-skills-b08/integration-reference/regression.log) · [统计历史日志](../../../script/.runtime/pa-skills-b08/statistics-historical-final/regression.log) |
| 学校冻结、模板、引用和实际读稿 | 引文修正后 24 项通过，修订原稿完成独立 Word 回放。 [回归日志](../../../script/.runtime/pa-skills-b08/thesis-citation-regression/regression.log) · [新稿回放](../../../script/.runtime/pa-skills-b08/thesis-b-cited-verified/replay.log) |
| 前端正常阅读入口 | 统计、解读报告、SCI 与毕业论文六组界面测试 77 项通过。 [日志](../../../script/.runtime/pa-skills-b08/frontend-targeted.log) |

## 7. 同题补验

用户要求补齐首验留下的两项。复用 B04 原件、同一报告专题、同一森林图与已存统计响应。以下为补验后的实际读稿和导出结果，首验盲评保留在第 5 节。

| 入口 | 补验前 | 补验后 |
| --- | --- | --- |
| `REPORT-02` | 报告有 4 条轨迹记录和 1 个分析单元。冻结材料中缺原始文库数和特征数，正文未写出这两项。 | 模型在“设计与数据”写出 “The source input is recorded as containing 1 library and 2 features before processing.”，并区分下游 4 个入选细胞和 1 个分析单元。独立生物重复数仍明示未知。已核对读稿及 Word 同句。 [补前 Word](../../../script/.runtime/pa-skills-b08/analysis-b2/REPORT-02/replay/report.docx) · [补后 Word](../../../script/.runtime/pa-skills-b08/report-import-final/REPORT-02/replay/report.docx) · [冻结请求差异](../../../script/.runtime/pa-skills-b08/report-import-supplement/frozen-difference.json) · [交付复核](../../../script/.runtime/pa-skills-b08/report-import-final/delivery-checks.json) |
| `STAT-02` | 论文段给出每单位 OR `9` 和 95% CI `2.15086–37.6593`，只概括这是本地效应投影。 | 论文段和解释都明确本例区间较宽，上限超过下限的 10 倍，效应幅度估计精度有限。图件核对只使用已保存的估计和区间，未加入独立样本或重新拟合，无法验证关联能否在新样本复现。已核对工作台论文段、解释和集合 Word。 [补前读稿](../../../script/.runtime/pa-skills-b08/statistics-final-delivery/STAT-02/replay/reading.json) · [补后读稿](../../../script/.runtime/pa-skills-b08/stat-interval-supplement/STAT-02/replay/reading.json) · [补后 Word](../../../script/.runtime/pa-skills-b08/stat-interval-supplement/STAT-02/replay/report.docx) · [交付复核](../../../script/.runtime/pa-skills-b08/stat-interval-supplement/delivery-checks.json) |

轨迹报告走指派分析员的正常预览、确认、Worker 与下载。新预览沿已核验的专题父版本访问原始导入清单，计数投影只读取元数据。冻结请求在 `facts.table_evidence.trajectory.source_import` 增加匿名计数 `library_count=1`、`feature_count=2`。原矩阵、四张专题表、原图、模型和输出上限均与首验一致。`research-report-reading@1.0.3` 要求在数据部分交代原始输入维度。无文库声明时，冻结材料省略该计数。已确认任务仍读取原冻结请求。真实响应原样通过离线回放，Word、XLSX 和 ZIP 均完成下载检查。 [报告取证](../../../backend/app/domain/reader_reports/table_evidence.py) · [报告回放日志](../../../script/.runtime/pa-skills-b08/report-import-final/replay.log)

统计补验使用原响应和原冻结请求，二者逐字节一致。以已绘制的非截距效应及冻结区间为准，在上下界跨越一个数量级时补充区间宽度说明。本例的上界约为下界的 17.5 倍。图件验证边界取自已匹配的本地效应投影。新生成的稿有本地渲染标记，旧 `1.2.1` 解读仍可按原产物校验，原始模型材料摘要与 Word 嵌图像素核对通过。 [统计稿渲染](../../../backend/app/domain/figure_workbench/explanation_v5.py) · [统计回放日志](../../../script/.runtime/pa-skills-b08/stat-interval-supplement/replay.log)

本轮报告域 41 项、报告接口 17 项、统计解释 890 项定向回归通过。报告接口覆盖计数进入预览和冻结包、完整源校验次数、旧任务继续按原冻结包执行。新增 1 次 `gpt-6.1-sol` 真实提交，用于轨迹报告，用时 42 秒，估算 **US$0.0452885**。统计未新增提交。B08 累计 **13 次**，估算 **US$0.3275705**。两项补验针对 B04 固定合成样本，已清理临时容器。 [报告域回归](../../../script/.runtime/pa-skills-b08/report-import-final-domain.log) · [报告接口回归](../../../script/.runtime/pa-skills-b08/report-import-final-regression/regression.log) · [统计回归](../../../script/.runtime/pa-skills-b08/stat-interval-regression.log) · [用量台账](../../../script/.runtime/pa-skills-b08/usage.json)

## 8. 用户验收与 B09 交接

2026-11-26 用户确认 B08 验收通过，并授权按生成质量总领方案开始 B09。B08 以五组留出对照、两项补验及其 Word 和原请求回执作为整理前基线。验收时分支为 `feat/runtime-skills@d8f3429`，变更保留在工作树。B09 按用户要求在本地整理，交用户验收前不提交、不推送。 [B09 整理与验证记录](2026-11-26-PaperAssist-Skills-B09整理与验收记录.md)

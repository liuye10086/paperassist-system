# PaperAssist Skills B07 毕业论文章节质量记录

**状态** · 2026-11-26 · 用户验收通过 · 已确认开始 B08

## 1. 来由和本批范围

B06 验收通过后，用户同意开始 B07。B06 改进的是 SCI 首稿。毕业论文使用自己的一套学校章序、语种、选材和 Word 排版规则。原毕业论文 Skill 提到按章生成与双语一致，固定原稿也守住了事实边界，但绪论没有提出可检查的问题，讨论多次重述计划和缺证，后续应补什么与能得出什么结论的关系需要写清楚。 [B06 验收记录](2026-11-26-PaperAssist-Skills-B06-SCI写作质量记录.md#8-用户验收与-b07-交接) · [质量总领方案](2026-11-25-PaperAssist-Skills生成质量提升总领方案.md#b07--毕业论文章节质量) · [固定旧稿](../../../script/.runtime/pa-skills-b03/closeout/model/records/thesis-real-model.docx)

本批将学校首稿的 `thesis-writing` 更新为 `1.1.2`。绪论用已有研究在对象、方法或指标上的差异引出论文问题，并保留选定证据已报告的样本单位及数量。方法交代已记录的操作与最影响复现的缺项。结果先写本研究的数值或实际留存的图件。讨论在同一段内说明本研究和前人发现的可比程度。双语摘要核对同一目的、方法、数值、单位、方向和解释界限。结论给出受到证据约束的回答和下一步最需要补齐的材料。章节风格修改通过现有学校初稿工作流的冻结指令生效。 [毕业论文 Skill](../../../SKILLS/thesis-writing/SKILL.md) · [发布清单](../../../SKILLS/manifest.json) · [学校首稿合同](../../../backend/app/domain/manuscript_writing/school_live.py)

规则编写参考 Kalaris 按段落确认论点与证据、按章分配任务的做法，以及 K-Dense 让题名、摘要、正文与研究证据对齐的方法。按 PaperAssist 已有章用途、章节语种、数字绑定和选材范围编写本地指令。 [Kalaris 论文指南](https://github.com/KalarisLabs/research-agent-skills/blob/a74b0dbe5fa865d73b9f250ba5b0c9f107bd1baa/docs/guides/thesis-and-dissertation.md) · [Kalaris 学术写作](https://github.com/KalarisLabs/research-agent-skills/blob/a74b0dbe5fa865d73b9f250ba5b0c9f107bd1baa/skills/unslop-academic-writing/SKILL.md) · [K-Dense 科学写作](https://github.com/K-Dense-AI/scientific-agent-skills/blob/c21d13b3cc2894680229ba9959a53281acb9200e/skills/scientific-writing/SKILL.md)

## 2. 同题材料和生成条件

| 样本 | 材料与可报告范围 |
| --- | --- |
| `THESIS-01` · B04 固定改进样本 | 复用 B03 原学校模板和材料 Word。设计计划记录 5 行，保存一张无文字合成示意图。实际记录、测量结果、计算和已选文献均缺。A 复用 B03 已归档的真实原稿。B 用相同文件和章位重建。 [B04 记录](2026-11-26-PaperAssist-Skills-B04质量基线与评审记录.md#3-10-例固定样本及原稿复用) |
| `THESIS-LIT-01` · 含文献补测 | 保持同一学校模板。冻结已报告的 12 对假设树脂牙冠复制体宽度、人工读数减数字读数的描述性均差 `+0.120 mm` 和未估计推断不确定性。逐对原表保存在本地合成 Word。模型读取的是已选材料中的方法和汇总结果。另选两篇公开论文的三条摘要摘录，分别涉及 30 名患者的石膏模型与 `0.150 mm` 均差、以及上下颌和牙弓分区的一致性。 [Brawańska 等](https://www.mdpi.com/2077-0383/15/15/5911) · [Petrović 等](https://www.mdpi.com/2077-0383/13/3/730) |

两组均使用 `gpt-6.1-sol`、同一题内相同的管理附加指令、学校章序、输入资料和输出 JSON 结构，输出上限 12,000 Token。冻结请求的提供商报文只有 `instructions` 不同。旧 `THESIS-01` 的 16,850 输入预留恰好装满旧报文。隔离测试将新版输入上限设为 20,000，以装入新增写作规则。`THESIS-LIT-01` 两臂的上限均为 24,000。两个项目用既有客户接口确认和派发，经 Worker 逐份核对外发报文。 [预检记录](../../../script/.runtime/pa-skills-b07/preflight-complete/run.log) · [历史冻结请求](../../../script/.runtime/pa-skills-b03/closeout/model/records/thesis-frozen-envelope.json)

## 3. 改前改后的正文与 Word

| 样本与段落 | A 原写法 | B 新写法 |
| --- | --- | --- |
| `THESIS-01` 绪论与讨论 | 绪论把任务描述为“虚构工程核验文本的组织与边界说明”。讨论提醒计划和合成图不能替代实际测量，并列出待补资料。 | 绪论提出“这些记录是否足以支持可核查的工程验证结论”。讨论具体指出，缺少图件和实际测量的可追溯联系时，“图名中的‘方向’不能被解释为已观测到的变化方向”。 |
| `THESIS-01` 双语摘要、方法和结论 | 两份摘要已有相同的 5 行计划、合成图和缺证口径。方法只列缺少的测量与分析信息。 | 两份摘要均交代 5 行计划、留存的合成方向图与缺少实测对应。方法说明单凭行数无法确定独立观测单元。结果指出缺少图件对应的测量数据、变量与坐标含义。结论列出实际记录和数据到图示的可追溯映射。 |
| `THESIS-LIT-01` 绪论 | 分段介绍两篇研究，再交代本研究使用合成数据。 | 写明第一篇的 30 名正畸患者石膏模型和 `0.150 mm`，以及第二篇的分区一致性，比较两者的结果指标与可读范围。随后把研究问题限于合成数据中人工和数字宽度的平均差异方向与幅度。 |
| `THESIS-LIT-01` 讨论和结论 | 讨论解释本研究的正向均差与准确性、可互换性的区别，未把文献结果放到讨论中。 | 同段对照人工测量平均高 `0.120 mm` 和文献报告的 `0.150 mm`。解释两项方向相符，再用合成树脂复制体和 30 名患者石膏模型的差异限定可比范围。把第二篇分区一致性与本题只有总体均差的限制连起来，说明评价方法互换需要个体差异及预先定义的允许差异。 |

按 B04 的四项规则盲评，固定样本 **7/8 → 8/8**，改进项是章节任务与衔接。含文献样本 **7/8 → 8/8**，改进项是讨论与局限。两例正文硬门槛均通过，两个摘要与正文中的核心事实、数字和边界一致。最终版含文献样本在绪论和讨论都保留 30 名患者这一细节，两项均差各自绑定到已选文献和本研究汇总，结果章只使用本研究数字。 [固定样本盲评](../../../script/.runtime/pa-skills-b07/blind-complete-thesis.md) · [含文献样本盲评](../../../script/.runtime/pa-skills-b07/blind-complete-literature.md) · [揭晓与文件摘要](../../../script/.runtime/pa-skills-b07/blind-complete-key.json) · [数字绑定核对](../../../script/.runtime/pa-skills-b07/verification-complete.json)

固定样本摘要的“现有材料仅记录了”可收窄为“现有结果材料仅记录了”，使同段已说明的设计计划与结果材料界限更明确。含文献样本讨论可直接表述为现有材料无法比较两组均差的大小，原因是对象、流程与可比的不确定性信息不足。生成原稿保留供验收。 [固定样本文字细节](../../../script/.runtime/pa-skills-b07/blind-complete-thesis.md#剩余措辞细节) · [含文献样本文字细节](../../../script/.runtime/pa-skills-b07/blind-complete-literature.md#剩余措辞细节)

| 样本 | A 原始生成内容 | B 原始生成内容 |
| --- | --- | --- |
| `THESIS-01` | [B03 归档 Word](../../../script/.runtime/pa-skills-b03/closeout/model/records/thesis-real-model.docx) | [B07 Word](../../../script/.runtime/pa-skills-b07/live-thesis-complete/thesis-draft.docx) |
| `THESIS-LIT-01` | [旧规则 Word](../../../script/.runtime/pa-skills-b07/live-literature-final/literature-before-draft.docx) | [新规则 Word](../../../script/.runtime/pa-skills-b07/live-literature-complete/literature-after-draft.docx) |

## 4. 定向回归与真实验证

| 检查 | 结果 |
| --- | --- |
| 本机定向回归 | 236 项通过。覆盖包清单、冻结请求、学校首稿、数字和章内材料、精选文档、封面字段和排版修改。 [定向日志](../../../script/.runtime/pa-skills-b07/domain-complete.log) |
| 隔离集成 | 毕业论文的原路径、Skills 路径各一条通过。覆盖上传模板、规则确认、写作确认、审阅和现行与历史 Word 下载。关停工作流后重取已冻结预览，继续用其原指令完成任务。 [集成日志](../../../script/.runtime/pa-skills-b07/integration-complete/run.log) · [集成用例](../../../backend/tests/integration/test_customer_thesis_to_word.py) |
| 客户读稿与 Word | 核对本次下载的稿件逐段对齐候选和读稿。核对九章章序、两个受本地控制的章、双语摘要样式、正文宋体 14 pt、实际渲染服务填入的目录页码以及前置页和正文页码格式。固定样本嵌图与输入图片 SHA-256 一致。含文献两稿逐项核对 Word 书目与读稿。 [Word 与调用核对](../../../script/.runtime/pa-skills-b07/verification-complete.json) |

首次真实调用的正文已成功生成，隔离环境的 Word 目录渲染服务缺失，下载返回 `503`。随后挂载项目已有的渲染镜像和受锁定的字体。补测旧规则稿以字节相同的冻结请求原样重放已保存的响应，正文摘要一致，补下载新增外部请求 0 次。`1.1.1` 减少同一缺项在多章重复出现。该版含文献样本的盲评分由 6 升至 7，但省略了所选摘要中的 30 名患者，事实和来源得分由 2 降至 1。`1.1.2` 增补保留报告样本单位与数量的写法，并将缺项表述限定在选定材料可核对的范围。 [首次下载日志](../../../script/.runtime/pa-skills-b07/live-literature/run.log) · [重放核对](../../../script/.runtime/pa-skills-b07/live-literature-final/literature-before-replay.json) · [1.1.1 盲评](../../../script/.runtime/pa-skills-b07/blind-review-literature.md)

| 真实提交 | 输入 Token | 输出 Token | 费用估算 |
| --- | ---: | ---: | ---: |
| `THESIS-01` · 首轮规则 `1.1.0` | 2,736 | 1,841 | US$0.025249 |
| `THESIS-LIT-01` · 原规则 `1.0.0` | 3,149 | 3,459 | US$0.042461 |
| `THESIS-01` · 润色规则 `1.1.1` | 2,769 | 1,845 | US$0.025371 |
| `THESIS-LIT-01` · 润色规则 `1.1.1` | 3,501 | 3,361 | US$0.042361 |
| `THESIS-01` · 最终规则 `1.1.2` | 2,805 | 1,835 | US$0.025361 |
| `THESIS-LIT-01` · 最终规则 `1.1.2` | 3,537 | 3,740 | US$0.046241 |
| 合计 · 6 次新提交 | 18,497 | 16,081 | **US$0.207044** |

按模型回执与项目冻结价格估算。六次请求的预留额合计 US$1.023712，其他 69 次为按响应 ID 续取。外发的科学材料是合成写作选材和已选公开摘要。模板原件、图片和学校字段在本地用于 Word。各稿均为待科学和语言审核的首稿。 [调用回执](../../../script/.runtime/pa-skills-b07/verification-complete.json) · [OpenAI 模型价格](https://developers.openai.com/api/docs/models/gpt-6.1-sol)

## 5. 回退与交接边界

如需回到本批前的章节写法，从已保存的批前包恢复 `thesis-writing@1.0.0` 及对应发布清单，并撤回本批新增的集成版本断言。按原冻结快照处理已确认预览，按登记版本下载旧稿。两组材料均用于 B07 改进验证，毕业论文留出样本 `THESIS-02` 归 B08 审查。两份合成模板稿和一份真实院校模板稿的本机应用验证见第 6 节。 [批前 Skill](../../../script/.runtime/pa-skills-b07/skills-before/thesis-writing/SKILL.md) · [批前清单](../../../script/.runtime/pa-skills-b07/skills-before/manifest.json)

隔离测试用 PostgreSQL、应用容器和渲染容器已退出并移除。分支变更保留在工作树。 [固定样本环境回执](../../../script/.runtime/pa-skills-b07/live-thesis-complete/cleanup.json) · [含文献样本环境回执](../../../script/.runtime/pa-skills-b07/live-literature-complete/cleanup.json)

## 6. Word、WPS 与真实院校模板补验

2026-11-26 按用户要求使用 Computer Use 操作本机 Microsoft Word `16.0.20625.20108` 和 WPS 文字 `12.1.0.29690`。Word 在受保护的视图中阅读，WPS 打开的验收副本与交付稿逐字节一致。

| 代表稿 | Word | WPS | 交叉核对 |
| --- | --- | --- | --- |
| `THESIS-01` | 10 页。目录六项，结果页页脚为 `3`，图 3.1 和图注随结果段显示。作者和声明的人工项保留占位。 | 10 页。六项目录显示 `1、1、2、3、4、5`。图 3.1 在第 8 张物理页，正文光标处的字体栏显示宋体四号。 | 代表页位置一致。WPS 打开时未出现缺字或缺失字体提示。 [Word 原稿](../../../script/.runtime/pa-skills-b07/live-thesis-complete/thesis-draft.docx) · [WPS 副本](../../../script/.runtime/pa-skills-b07/native-office/B07-WPS-THESIS-01.docx) |
| `THESIS-LIT-01` | 10 页。绪论和讨论显示 `30`、`0.120 mm`、`0.150 mm` 及对应引用。末页书目两条，页脚为 `5`。 | 10 页。同一组量值与引用可读，末页两条书目及 DOI 完整。 | 绪论和末页书目的位置与 Word 一致。WPS 打开时未出现缺字或缺失字体提示。 [Word 原稿](../../../script/.runtime/pa-skills-b07/live-literature-complete/literature-after-draft.docx) · [WPS 副本](../../../script/.runtime/pa-skills-b07/native-office/B07-WPS-THESIS-LIT-01.docx) |

北京体育大学研究生院公布的 GS501 学术型硕士模板原件重新下载并核对，其 SHA-256 与此前留存原件一致。隔离客户项目解析到 42 个模板章，按固定的前置字段与章用途确认 13 章、8 个前置字段。使用同一组 B07 合成测量和三段已选公开摘要。官方模板、学校身份和签署项留在本机，冻结请求只含获选材料与七个可写章。Windows 本机 27 项前置版式测试通过，Linux 隔离环境将专属解析进程用例一并覆盖，28 项通过。 [官方模板下载页](https://grs.bsu.edu.cn/cyxz/11439.htm) · [模板确认回执](../../../script/.runtime/pa-skills-b07/gs501-preflight/gs501-template.json) · [Linux 定向测试](../../../script/.runtime/pa-skills-b07/gs501-regression/run.log)

GS501 请求提交一次，服务端用时 844 秒，超过首轮隔离运行的 260 秒等待窗口。随后按原响应 ID 续取至完成，用字节一致的冻结报文与原响应离线复测正常客户读稿、Word 下载。两份摘要与结果保持 12 对、人工减数字 `+0.120 mm`，绪论和文献综述保留外部 30 名患者及 `0.150 mm` 的归属。补验的一次调用估算 US$0.045004，B07 累计 7 次新提交、估算 US$0.252048。 [原响应续取回执](../../../script/.runtime/pa-skills-b07/native-office/gs501-retrieval.json) · [离线恢复回执](../../../script/.runtime/pa-skills-b07/gs501-font-fixed/gs501-replay.json) · [OpenAI 模型单价](https://developers.openai.com/api/docs/models/gpt-6.1-sol)

版式测试先复用已有 B07 正文独立验证官方模板。脚本最初将原件正文的示例图也纳入完整性检查，经 OOXML 关系确认，前四页实际引用三张图。改用前四页实际引用的图件后复验通过。原件前四页的章节分隔、三张表和三张图片均在最终稿中核对。 [版式定向日志](../../../script/.runtime/pa-skills-b07/gs501-layout-final/run.log) · [真实首稿版式校验](../../../script/.runtime/pa-skills-b07/gs501-font-fixed/gs501-word-checks.json)

GS501 首稿在 WPS 状态栏复现“缺失字体”。授权书标题的段落标记保留了原件中的复杂文字字体别名 `LiSu+1`。原件字体表为它指定 `Times New Roman`。只替换这个字段的诊断副本消除了警告，仍为 16 页。项目现于复制 GS501 前置表单时解析这一个别名到源模板给出的字体。其余三个字体属性、学校原件、冻结的正文和受保护信息均通过复核。回归先在旧代码中复现这一字段差异，再在修后通过 Linux 前置版式 28 项和毕业论文原路径、Skills 路径 2 项。 [修复代码](../../../backend/app/adapters/bsu_gs501_docx.py) · [定向断言](../../../backend/tests/adapters/test_school_front_matter.py) · [修前复现](../../../script/.runtime/pa-skills-b07/native-office/gs501-font-red.log) · [修后版式回归](../../../script/.runtime/pa-skills-b07/gs501-font-regression/run.log) · [修后集成回归](../../../script/.runtime/pa-skills-b07/native-regression/run.log)

在 Word 和 WPS 分别打开了修后导出稿，均为 **16 页**。封面、题名和答辩委员会页、原创性声明及非公开审批表、使用授权书维持前四页顺序，签署项留空。两应用目录页都显示 7 项及相同页码 `1、2、3、4、5、6、8`。WPS 修后稿未再显示缺失字体提示，章序和模型正文与修前一致。本次无需用户手动操作，覆盖北京体育大学这一版官方模板及本机两款应用的代表页。隔离服务已移除。 [修前 Word](../../../script/.runtime/pa-skills-b07/gs501-replay/gs501-draft.docx) · [修后 Word](../../../script/.runtime/pa-skills-b07/gs501-font-fixed/gs501-draft.docx) · [WPS 同字节副本](../../../script/.runtime/pa-skills-b07/native-office/B07-WPS-GS501-fixed.docx) · [环境清理回执](../../../script/.runtime/pa-skills-b07/gs501-font-fixed/cleanup.json)

## 7. 用户验收与 B08 交接

2026-11-26 用户确认 B07 通过，验收包含两组同题稿质量、Word 和 WPS 桌面核对、GS501 官方模板补验与字体修正。B07 最终规则为 `thesis-writing@1.1.2`。留出材料 `THESIS-02` 随 B08 的三模块成对验证使用。其他院校模板或 Office 版本仍以实际使用条件为准。

用户同意按总领方案开始 B08。验收时分支为 `feat/runtime-skills`，HEAD 为 `d8f3429418a210aacfafa581536f5cee5a532c8e`，B07 变更仍在工作树。用户要求 B08 暂不提交或推送。 [B08 批次范围](2026-11-25-PaperAssist-Skills生成质量提升总领方案.md#b08--三模块留出对照与交付验收) · [B08 留出验收记录](2026-11-26-PaperAssist-Skills-B08三模块留出验收记录.md)

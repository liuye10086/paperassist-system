# PaperAssist-System Skills B06 SCI 写作质量记录

**批次** · 2026-11-26 · SCI 叙述性综述与研究论文首稿

**状态** · 2026-11-26 · 用户验收通过

B06 复用 B04 固定的两组改进材料。综述要把同一问题下两篇研究的对象、方法和实际覆盖范围放到同一条论证中。研究稿要用已提供的计划、观察和图件解释结果，再指出哪些证据缺口会改变结论。 [总领方案](2026-11-25-PaperAssist-Skills生成质量提升总领方案.md#b06--sci-综述及研究稿的论证) · [B04 固定材料](2026-11-26-PaperAssist-Skills-B04质量基线与评审记录.md)

## 1. 实现与取舍

| 入口 | 本批实现 |
| --- | --- |
| SCI 叙述性综述 | `narrative-review@1.1.1` 按主题组织逐篇证据和跨研究综合。正文把决定比较的范围、方法和原引用放在同段。题名使用各篇证据共同支持的人群范围。新版综述初稿将摘录中明确的独立英文基数词纳入现有数值目录。原摘录保留，候选数字仍需对应本段的证据别名和精确数值路径。人工科学复核继续要求新审核证据，可用同一原词核对对应数值。 [规则](../../../SKILLS/narrative-review/SKILL.md) · [数字目录](../../../backend/app/domain/manuscript_writing/numeric_contract.py) |
| SCI 研究稿 | `research-article@1.1.1` 按 Methods、Results、Discussion 分配信息。计划和执行分别依照协议和记录，图示和测量各有来源。讨论将具体缺口与受限制的判断对应起来，有可比文献时比较具体对象、方法或结果。摘要保留理解主要结果所需的关键计数与归属。 [规则](../../../SKILLS/research-article/SKILL.md) |

英文数值投影覆盖独立基数词。复合或有符号的词形保留在原摘录供人工阅读。新旧规则的预览和执行沿冻结请求，已生成原稿按原版本读回。毕业论文继续使用已有的共享科研写作规则及学校模板。修正了旧的未知提交状态测试桩，使其返回服务实际使用的二元组，并继续验证未获响应 ID 时不重复构造或调用供应商。 [文章材料](../../../backend/app/domain/manuscript_writing/article_contract.py) · [科学复核数值](../../../backend/app/domain/manuscript_writing/live_review_candidate.py)

写作规则参考 K-Dense 的主题综合和研究间比较，以及方法与结果一致性和证据边界处理，按 PaperAssist 的冻结摘录、数值和图件重新编写。上游固定版本 `c21d13b3cc2894680229ba9959a53281acb9200e`，MIT 许可。 [文献综述方法](https://github.com/K-Dense-AI/scientific-agent-skills/blob/c21d13b3cc2894680229ba9959a53281acb9200e/skills/literature-review/SKILL.md) · [科研写作方法](https://github.com/K-Dense-AI/scientific-agent-skills/blob/c21d13b3cc2894680229ba9959a53281acb9200e/skills/scientific-writing/SKILL.md) · [许可](https://github.com/K-Dense-AI/scientific-agent-skills/blob/c21d13b3cc2894680229ba9959a53281acb9200e/LICENSE.md)

## 2. 同题条件与 Word 对照

- `REVIEW-01` 以 B02 启用版未经人工补写的原稿为 A。B 在隔离客户项目中用 B02 归档回放两段已批准摘要及书目，按原顺序选择。模型 `gpt-6.1-sol`、英文、输入配置上限 100,000、输出上限 12,000、管理员附加指令为空。原摘录与全部书目逐字段对齐，生成输入的数值目录增加 `e1=6`、`e2=8` 两项，输出合同相应允许原有的精确数字绑定。 [原 Word](../../../script/.runtime/pa-skills-b02-1fa8d6fd/review-01.docx) · [新版 Word](../../../script/.runtime/pa-skills-b06/live-review-title/review-draft.docx)
- `SCI-01` 以 B03 原候选及 Word 为 A。B 使用相同合成尺量材料、英文、模型、原管理员附加指令、输入配置上限 24,000 和输出上限 12,000。冻结的科学输入和输出结构与 A 逐字节一致。Figure 1A 使用原 PNG 字节，SHA-256 为 `3b49f2dbaca2c4a22ce046823fe9079461ed597fbc417565dd5aa0f40120d975`。 [原 Word](../../../script/.runtime/pa-skills-b03/supplement/model/records/research-real-model.docx) · [新版 Word](../../../script/.runtime/pa-skills-b06/live-research-unit/research-draft.docx)

两组评审使用从 Word 提取的原文。独立评审先按硬性事实和四项质量标准判断甲乙，再揭晓版本。两条新版候选均保留待科学复核状态。 [原稿和验收核对](../../../script/.runtime/pa-skills-b06/verification.json)

## 3. REVIEW-01 · 综述对照

匿名稿甲为 B，乙为 A。A 已正确关联单细胞及单核分析、单细胞及空间分析和生态位研究目的。两个区域数在摘录中出现，未写入 A 正文。B 的主题正文使用各自的独立段落和原编号证据。

| 维度 | A | B | 原稿中的可见变化 |
| --- | ---: | ---: | --- |
| 事实覆盖及引用归属 | 1 | 2 | B 在 `themes:1` 随 [1] 写出 Litviňuková 等分析 6 个成人心脏解剖区域，在 `themes:2` 随 [2] 写出 Kanemaru 等以单细胞及空间数据研究 8 个人类心脏区域，生态位发现表述为研究目的。 |
| 跨研究综合 | 1 | 2 | B 将区域数、模态和问题并排解释，指出不同总数无法判断区域是否覆盖、是否采用不同分区以及图谱完整程度。 |
| 人群及证据边界 | 1 | 2 | B 标题使用人类心脏图谱，成人限定只用于 [1]。第二篇的年龄范围、两篇的区域对应和实际生态位结果在摘录中缺证。 |
| 学术结构和文字 | 2 | 2 | 两稿结构可读。B 对照顺序更明确，摘要和引言的设问略有重复。 |
| 合计 | **5/8** | **8/8** | 新版达到本组必要事实和引用要求，两份 Word 的参考文献编号与条目均与固定书目一致。 |

首轮 `1.1.0` 已找回区域数，但沿用把成人范围写入整篇的拟题。调整题名规则和逐篇引用位置后重跑综述，采用 `1.1.1` 的真实原稿作为 B。 [甲稿](../../../script/.runtime/pa-skills-b06/blind/REVIEW-01-甲.md) · [乙稿](../../../script/.runtime/pa-skills-b06/blind/REVIEW-01-乙.md) · [揭晓](../../../script/.runtime/pa-skills-b06/blind-key.json)

## 4. SCI-01 · 研究稿对照

匿名稿甲为 A，乙为 B。两稿都准确地区分了计划量、用户所报留存量和示意图。B 让摘要读者可以一次看到关键数字，并指出核查方向和解释留存差异分别需要哪些资料。

| 维度 | A | B | 原稿中的可见变化 |
| --- | ---: | ---: | --- |
| 方法、结果及图示角色 | 2 | 2 | Methods 均写计划 5 次，Results 将保留 4 次与向上方向归于用户记录。B 进一步交代观测单位和实际流程未提供，Figure 1A 的数值边界明确。 |
| 讨论及所需证据 | 1 | 2 | A 已指出缺少读数和程序细节。B 对应到具体判断，核查向上方向需要原始读数和顺序或比较基准，解释 5 与 4 的差异需要留存记录。 |
| 摘要与正文的一致性和细节 | 1 | 2 | A 摘要省略两个具体计数。B 摘要同时交代计划 5 次、报告保留 4 次、报告方向和差异原因未知。数值分别绑定原方法与用户报告。 |
| 学术结构和文字 | 2 | 2 | 两稿的章节功能清楚。B 部分句子的主语还可进一步润色，例如可直接归因给用户记录。 |
| 合计 | **6/8** | **8/8** | 两稿通过本组合成材料的原始事实核查。 |

首轮 `1.1.0` 的 Methods 把单次读数写成了已定义的观测单位。补验版明确保留该资料缺口并区分计数差异与未知成因，真实原稿 `1.1.1` 按上述同题条件重新盲评。 [甲稿](../../../script/.runtime/pa-skills-b06/blind-research-final/SCI-01-甲.md) · [乙稿](../../../script/.runtime/pa-skills-b06/blind-research-final/SCI-01-乙.md) · [揭晓](../../../script/.runtime/pa-skills-b06/blind-research-final-key.json)

## 5. 定向验证与真实用量

| 项目 | 结果 |
| --- | --- |
| 写作领域与历史合同 | 370 项通过，含两项新增数字回归。检查摘录数字的错配拒绝、人工精确证据和既有冻结请求恢复。 [日志](../../../script/.runtime/pa-skills-b06/domain.log) |
| 客户 API 和 Word 回归 | 5 项通过，覆盖两类 SCI 启用与原路径，以及共享规则下的毕业论文原流程。 [日志](../../../script/.runtime/pa-skills-b06/final-customer-regression/run.log) |
| 真实 SCI 两条路径 | 走客户预览、授权、队列、Worker、认证读稿和 Word。四次真实调用各一条 POST。后续续取同一响应。最终 Word 验证综述原引用和数字对应、研究稿 Figure 1A 的原字节。 [综述](../../../script/.runtime/pa-skills-b06/live-review-title/run.log) · [研究稿](../../../script/.runtime/pa-skills-b06/live-research-unit/run.log) |
| 最终版本预检 | 两条冻结材料在最终清单下重建与各自成功实发的请求逐字节一致。B02 原冻结请求仍通过当前校验。 [预检](../../../script/.runtime/pa-skills-b06/final-preflight/run.log) · [回执](../../../script/.runtime/pa-skills-b06/verification.json) |

| 实际提交 | 输入令牌 | 输出令牌 | 台账估算费用 |
| --- | ---: | ---: | ---: |
| 综述首轮 | 3,591 | 1,935 | US$0.028326 |
| 综述题名及引文补验 | 3,627 | 1,780 | US$0.026866 |
| 研究稿首轮 | 2,694 | 1,160 | US$0.018334 |
| 研究稿观察单位及原因补验 | 2,728 | 957 | US$0.016389 |
| 合计 | **12,640** | **5,832** | **US$0.089915** |

这四次外发使用两段已批准的公开摘录及书目和 B03 的合成工程材料。文献选材由本地归档回放。验证使用专用本机容器与数据库，结束后移除。Word 检查覆盖正文、书目、引用、内嵌图和下载。`SCI-01` 缺外部对照文献，独立的含文献用例见第 7 节。`REVIEW-02`、`SCI-02` 仍按 B08 完成留出对照。

## 6. 回退和批次交接

如生成质量退化，可恢复上一套 SCI Skill 与匹配清单，或停用 `sci_narrative_review` 或 `sci_research_article` 对应入口的 Skills。已确认请求按原快照续取。 [运行清单](../../../SKILLS/manifest.json) · [总领方案](2026-11-25-PaperAssist-Skills生成质量提升总领方案.md#6-统一回退和确认)

## 7. 措辞润色与外部文献对照补验

两条 SCI 规则升到 `1.1.2`。综述让摘要先交代主要比较，让引言说明比较为什么重要。研究稿用明确的主体和资料来源叙述，讨论先说明具体结果能支持哪一步。在含文献时并列本研究和已选文献的原量值、单位及对象，说明可比的部分和限制。综述的已有数值投影继续用于此版本，已冻结的旧稿按原规则回读。 [综述规则](../../../SKILLS/narrative-review/SKILL.md) · [研究稿规则](../../../SKILLS/research-article/SKILL.md)

### 原两份初稿的措辞对照

两例均与前一版 `1.1.1` 使用相同模型、科学输入与输出协议。只更换写作指令，各真实生成一次，直接使用原响应及产品导出的 Word。

| 初稿 | 润色前 | 润色后 |
| --- | --- | --- |
| `REVIEW-01` | 摘要和引言分别以 “What can reported anatomical coverage …” 和 “How do anatomical coverage …” 提问，两个开头重复相近的话题。 | 摘要开头直接比较区域转录组表征与空间生态位研究。引言从解读问题起笔，说明取样覆盖范围与测量能回答的问题各指什么。主题正文的 6、8 及 [1]、[2] 逐项核对通过。 [润色前 Word](../../../script/.runtime/pa-skills-b06/live-review-title/review-draft.docx) · [润色后 Word](../../../script/.runtime/pa-skills-b06/supplement-review/review-draft.docx) |
| `SCI-01` | Results 写 “The user-reported outcome retained …”，将结果当作执行主体。Discussion 的 “supports only the conclusion” 范围超出了该段要判断的方向。 | Results 以用户提供的报告作归因。Discussion 明确说向上是定性描述，说明需要原始读数、单位、顺序和不确定性来核查。摘要中保留计划 5 次和报告保留 4 次。Figure 1A 字节校验通过。 [润色前 Word](../../../script/.runtime/pa-skills-b06/live-research-unit/research-draft.docx) · [润色后 Word](../../../script/.runtime/pa-skills-b06/supplement-research/research-draft.docx) |

### SCI-EXT-01 · 配对量值与外部研究对照

在独立客户项目中准备 12 对合成树脂冠复制件的宽度记录，逐对按手工减数字计算均差，复核为 `+0.120 mm`。模型工作包带用户报告的摘要值。Brawańska 等的公开研究使用正畸患者石膏模型，发表的手工测量均值比数字测量高 `0.150 mm`。工作包只选入同篇摘要的两段短摘录和绑定书目，开放获取许可为 CC BY 4.0。 [原研究](https://www.mdpi.com/2077-0383/15/15/5911) · [PubMed 摘要](https://pubmed.ncbi.nlm.nih.gov/42590014/)

| 对照环节 | `1.1.1` 实测 | `1.1.2` 实测 |
| --- | --- | --- |
| 数量和方向 | Results 写本例 `0.120 mm`。Discussion 写文献 `0.150 mm`，并定性指出方向相同。 | Discussion 在同段对照本例 `0.120 mm` 和文献 `0.150 mm`，分别绑定用户结果 `c1` 和文献摘录 `e2`。 |
| 可比性 | 说明测量对象不同，难以推断性能可比。 | 明确指出树脂冠复制件与患者石膏模型的对象差异，所选文献片段也无法确认宽度定义和工作流程一致。比较限于均差方向，结论保持在描述层面。 |
| 引用与边界 | 讨论指向同篇已选摘要，局限说明缺少逐对读数及变异。 | Word 的比较段指向 [1]，书目保留 DOI `10.3390/jcm15155911`。讨论说明还需要逐对读数、数据来源及参考标准来评价一致性与准确度。 |

两臂英语、`gpt-6.1-sol`、输入配置上限 24,000、输出上限 12,000、附加指令、科学材料及输出合同相同。只改变冻结 Skills 指令，各经一次真实提交。 [对照前 Word](../../../script/.runtime/pa-skills-b06/supplement-external-2/external-before-draft.docx) · [对照后 Word](../../../script/.runtime/pa-skills-b06/supplement-external-2/external-after-draft.docx) · [运行日志](../../../script/.runtime/pa-skills-b06/supplement-external-2/run.log)

373 项写作领域测试和 5 项认证客户流程回归通过。四份补验原稿均经客户授权、Worker 保存、读稿及 Word 核对。此次新增真实提交 4 次，估算 US$0.084105。B06 累计 8 次，估算 US$0.174020。含文献实测覆盖这一个英文合成案例与一篇公开研究。两个独立留出样本仍在 B08。 [定向测试](../../../script/.runtime/pa-skills-b06/supplement-domain.log) · [客户回归](../../../script/.runtime/pa-skills-b06/supplement-regression/run.log) · [补验回执](../../../script/.runtime/pa-skills-b06/supplement-verification.json)

## 8. 用户验收与 B07 交接

2026-11-26 用户确认 B06 验收通过，范围包括两条 SCI 首稿的质量改进、措辞与外部文献对照补验，以及本批的 Word 和定向回归证据。同日用户授权启动 B07 毕业论文章节质量改进。 [B07 范围](2026-11-25-PaperAssist-Skills生成质量提升总领方案.md#b07--毕业论文章节质量) · [B07 实施记录](2026-11-26-PaperAssist-Skills-B07毕业论文章节质量记录.md)

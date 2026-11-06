# 第5批独立代码审查

2026-11-05。审查者仅修改本文件；没有提交、推送、清理或运行重容器。冻结 R / Word、组成与同类型 DE 后端以及前端合同审查已完成。首轮7项实质问题已修复；后续配对 Word 数字拆行和数字样式ID保真问题均已修复复核，当前无遗留阻断审查项。真实公开数据正式队列及最终API报告一致性验收仍属于主任务，不由代码审查替代。

## 审查发现与复核状态

1. **P2 / 已复核修复 — Word 组成结果丢失状态类别身份与未计算原因。** 原 `backend/app/adapters/single_cell_insight_report.py:99` 的列只保留 `label_id` 和数值，而实际 `composition_results` 的 unknown / uncertain 等类别使用 `category` 表达、`label_id` 为空。导出结果行因而显示 NA，无法区分这些类别，`inference_status/reason` 同时被省略。现已显示 `category_label`，另列状态和原因表；内存 DOCX 回归通过。

2. **P2 / 已复核修复 — Word pseudobulk 单位表使用错误字段名。** 原同文件 `:100` 选择 `cells/total_counts`，实际 `bio_insights_engine/comparison.py` 的 `_donor` 输出 `spot_count/library_counts`。现已改正确字段；内存生成 DOCX 的 `137/56789` 已保留。

3. **P2 / 已静态复核修复 — Propeller 成功回执丢失原生后续日志并把请求的 robust 当实际方法。** 原 `single_cell_r/propeller.R:23` 在原生调用前复制 `logs` 到 `base`，`:33` 调用后仍返回旧 `base`。固定 speckle 1.6.0 在受检类别不超过两个时发送消息并强制 `robust=FALSE`，原桥接却无条件记录 `robust=True`。现已在调用后更新日志，返回 `robust_effective`，参数区分 `robust_requested` 与实际 `robust`；新增测试覆盖两类别及消息。已读取主代理保存的 `script/.runtime/single-cell-batch5/propeller-review-tests.json`，记录当前真实固定镜像7通过/10.47s与新增测试RED；独立审查没有重跑 R。旧6通过日志保留，没有覆盖。

4. **P2 / 已复核修复 — Word 接口接受不属于供者 DE 的 comparison 并给出错误方法说明。** 原构建器对任何非组成 comparison 都写供者 DE 和整数 counts pseudobulk。现已按模式区分供者 DE 与通用比较；新增独立内存检查确认 `spot_exploratory` 不再出现这些错误文字。

5. **P2 / 已复核修复 — batch 调整单一水平时预检放行、执行失败。** 原 `domain/bio_insights/single_cell_composition.py` 只检查 batch 完整/唯一，没有阻断所有 donor 只有同一个 batch。现增加 `single_batch_adjustment` 阻断；独立纯 Python 回归确认预检不再放行。

6. **P2 / 已复核修复 — Word 供者 DE 缺失可读的实际对比方向。** 原配置中的 `contrasts` 被过滤，结果仅展示对比 ID。现新增从保存配置读取的三列方向表；独立内存 DOCX 回归确认 numerator / denominator 的具体条件及方向说明均存在。

7. **P2 / 已静态复核修复 — 同类型 DE 专用摘要读取了不存在的后端路径。** 原 `frontend/src/features/bio-insights/SingleCellInsightSummary.tsx` 从 `result.methods.config.single_cell_selection` 判断同类型 DE；实际后端为顶层 `methods.single_cell_selection`。现优先读取顶层，兼容 config；新增 `InsightResults.test.tsx` 真实后端结构 fixture。已阅读修复、测试及前端报告的4个结果测试通过记录，独立审查没有重跑前端测试。

## 已检查与证据边界

- 读取固定 speckle 1.6.0 保留源包中的 `getTransformedProps`、`propeller.ttest`，确认桥接调用真实导出函数；paired 模型含 donor，contrast 的方向为 numerator − denominator；原始组均值不是协变量调整后的均值。
- 静态核对整数 counts、20k 总细胞上限、轴唯一、完整供者对、独立供者、设计秩及剩余自由度检查，未发现本轮需要另报的设计正确性问题。
- Word 下载通过所有者/项目作用域的结果查询、来源复核及正式成员 hash 校验读取保存结果，没有额外统计计算或 PDF 路径；本轮未发现权限绕过。
- 已读取现有六个原工具数值测试及镜像安装/固定版本代码；其通过结论来自此前报告，本审查未重跑重容器，不将该报告替代公开数据队列验收。
- Word 检查仅为内存 DOCX 文本/表格验证，不是页面视觉验收。
- 修复后独立直接调用现有 7 个 Word 测试用例，另执行一个 `spot_exploratory` 文字回归，全部通过；未通过 pytest/DB fixture，也未写入 DOCX 文件。
- 第二轮已静态核查组成计数/预检、同类型 DE 成员校验、技术样本聚合、稀疏估算、来源 currentness、transport 投影、正常 runtime/probe 和隔离前模块加载。除第5项预检不一致外，目前未发现额外阻断问题。
- 前端已核对 schema5 请求不混入 DE family 字段、同类型 condition × assigned label 选择、标签变更清空成员、身份确认不自动发生、组成全部类别分母、实际 donor/cell n 和结果/Word入口。新增发现第7项已修复。
- ORA/GSEA沿用既有实现。本轮核对新DE继续发布实际受检全集并保持既有富集来源路径；未重复全面审查已存在的统计实现。

## 主任务仍需完成的验证

- 最终科学代码 digest 的真实正常 runtime/组成 gate 已在下述追加复核中确认；后续若修改科学代码仍需重新核验。
- 完成正式 HTTP / DB / 队列公开供者数据、同类型 PyDESeq2→ORA/GSEA验收，明确小型原工具/fixture与真实数据证据的区别。
- 完成浏览器交互和直接 Word 页面视觉核查，不能用本审查的内存文本检查替代。

## 审查后必要小修的追加复核

主代理要求追加核查单条件描述、旧 comparison 序列化兼容、insights 独立 NPROC 调整及 resident 父服务线程配置。本轮未修改实现、未运行重容器，结论为**未发现新的阻断问题**。

- **单条件描述：** 只有 `descriptive` 允许 numerator==denominator，推断仍拒绝。遍历保留细胞只发生一次，设计将不存在的第二侧 donor/cell n 置0、完整配对数置0；计算路径将第二侧均值、组间 difference/ratio/P 置空，并记录 `single_condition_description`。父校验同时拒绝非空效应和描述 P 值。独立直接调用两个纯合同/序列化回归函数，再实算单条件 fixture：12 cells、计数表分子合计12、实际3 donors、第二侧0、pairs0，全部通过。数值表全流程测试由后端报告记录，本审查未重复运行。
- **页面单条件表达：** 已核对配置检查允许描述相同条件；配置页面明确不做组间比较；预检及结果均向 `DesignUnits` 传递 `singleCondition`，仅展示实际条件、供者 n、细胞 n，不并列虚构的第二组。已阅读相应前端结果 fixture。
- **旧 wire 兼容：** `ComparisonConfig` wrap serializer 只在 `single_cell_selection is None` 时省略新键，实际选择继续完整序列化。独立直接执行 `test_existing_spatial_comparison_wire_omits_absent_single_cell_selection` 通过；未改变已有其他配置字段。
- **NPROC 调整范围：** 代码改动仅位于 insights sandbox，将共享 real UID guard 从64改为256。数值线程设置仍为1，AS仍为3GiB；RSS仍由父监测和输出校验限制为2GiB。seccomp的 clone 同进程线程 flags 约束、fork/exec默认拒绝没有改变；其他 bio/excel sandbox 的 NPROC 仍为0。256表示共享UID计数上限，不能写作允许256个数值工作线程。
- **最终 gate 与源码一致性：** 独立计算当前 `engine_code_digest()` 为 `6cca5ecb02f6caefa28f60d3bede9b18d935ccbd3c263dec1ca7360df93756f9`，与 `script/.runtime/single-cell-batch5/bio-insights-runtime.json` 及 `insights-parent-probe-final.json` 完全一致。已读取实际回执：aggregation / deseq2_fit / gsea / single_cell_propeller 均 true，numeric_threads / warm_threads 均1，shared_uid_process_limit=[256,256]，file/network/fork/subprocess均denied，AS3GiB。正常父子配对60-cell探针实际3对、rank4/df2、child峰RSS1,220,488KiB。回执的容器cgroup内存4GiB与科学子进程RSS2GiB属于不同限制，不混称为同一资源预算。
- **正在运行的父服务：** 仅执行只读 `docker ps/inspect`，未启动、停止或exec容器。确认当前 acceptance API、worker、dispatcher 三个服务的 OPENBLAS_NUM_THREADS / OMP_NUM_THREADS / MKL_NUM_THREADS / NUMEXPR_NUM_THREADS / VECLIB_MAXIMUM_THREADS 均为1。

以上 gate 是有界合成科学数据证据；公开供者任务、浏览器及最终 Word PNG 仍按主任务另验。

## 真实数据 transport 补丁与组成描述 Word 逐页复核

主代理通知真实 Kang 组成描述与8对 propeller 已走正式队列成功后，审查者追加只读检查最新 transport 补丁及 `composition-description-preview.docx` 对应的 `word-preview-description/page-1.png` 至 `page-9.png`。本轮**未发现新的阻断代码问题、报告内容错误或明显布局缺陷**。

- **transport：** 仅本批 single-cell comparison 去掉重复 `metadata.assignments` 和已冗余的 label 成员列表；完整冻结来源不改，声明的 assignments 文件路径/hash仍保留。`hydrate_single_cell_annotations()` 读取声明成员时沿用 `document()` 的真实文件size/hash验证，结果放进独立副本；`worker.main` 明确先 `enter(...)` 再 `run(...)`，因此恢复发生在隔离后。数值运算使用恢复副本，recipe/manifest使用compact副本；父校验按相同projection比对source_bindings和recipe，组成计数仍根据完整冻结来源重验。已阅读篡改成员拒绝与projection幂等测试；本轮不运行科学任务。
- **最新科学身份：** 独立计算当前code digest为 `7a8af1dba86641e3f0f7861f0ad0db84b0ff7f969525e67e67ab06f68dce975c`，与当前 `bio-insights-runtime.json` 完全相同。该回执status=passed、四项科学检查true、file/network/fork/subprocess均denied。上一节 `6cca5ecb...` 是必要小修阶段的历史记录，当前以 `7a8af1db...` 为准。
- **真实输入传输证据：** 已读取 `kang-parent-transport-check.json`，记录发送体1,525,554B、6400cells、16单位、8个完整供者对、child峰RSS1,333,676KiB及正常父子执行passed；这是本次已保存材料核查，不冒称本审查另跑正式队列。
- **第1—2页：** 标题、固定来源、SHA、标签依据、供者/capture混杂限制、描述模式及参数可读；6400cells/16单位/8对一致，未给出描述模式推断P值。参数表跨页重复表头，无裁切、重叠或缺字。
- **第3—7页：** 16个供者条件单位每个400cells；组成表明确标注展示200/208行，非完整表未被冒称为完整表。类别名称、unknown/uncertain/conflict/unlabeled/other和零值均保留；跨页表头一致，长标签正常换行，未见表格越界或行内容裁切。
- **第8页：** 13/13类别的描述差值/比值、P/统计量NA、逐类not_requested/descriptive_only及零分母原因均可读；没有把NA改写为阴性结论。
- **第9页：** 保存的组成图完整显示16根柱、坐标、图例和SHA，图件没有压住正文；解释边界与0/NA说明完整可读。

本次实际查看了全部9张既有PNG，没有生成PDF、没有修改DOCX。视觉通过范围仅限这份组成描述报告；不自动代表供者DE、富集及其他报告的页面已验收。

## 配对 propeller Word 10页逐页复核

已实际逐页打开 `word-composition-paired/page-1.png` 至 `page-10.png`（`composition-paired.docx` 的Word直接输出）。发现以下一项需修复的明确布局问题；未改文档或生产代码。

**P2 / 已在本地修复预览复核 — 第8—9页统计数值被硬拆行。** 原 `composition_results` 六列表使用完整约17位小数，列宽不足使数值拆为2—3行，部分负号单独占行。主代理仅改变Word数值展示为6位有效数字并明示完整精度在下载表。已逐页重看 `word-composition-paired-fixed/page-1.png` 至 `page-10.png`；第8—9页数值保持单行、负号完整，0/NA不混淆，其他页面无新增裁切或叠压。该文件是 `composition-paired-layout-preview.docx` 本地修复预览，尚非重启API后的最终下载回执。

其他检查：第1—2页source/hash、配对与capture混杂限制、asin、真实speckle版本和实际robust参数完整；第3页8对/rank9/残差df7正确显示；第3—8页16×400cells、组成分母及200/208摘录说明完整；第9页八个受检类别标记tested，五个恒零状态类别为not_computable/no_testable_variation、P/FDR为NA；第10页16根柱、坐标、图例和解释边界完整。所有页面未发现文字/表格裁切或叠压。

描述preview与最终文件仅core.xml变化、其他17个parts一致，是主代理提供的对比结论；本轮未重复该二进制对比。此前描述报告视觉QA可按此对应关系复用。DE/ORA/GSEA报告尚未纳入此次视觉QA。

**P2 / 已复核修复 — 六位展示格式不应应用于标识字符串。** 初版 `_table_value` 按字符串正则处理所有表列，独立调用曾确认 `001.20→1.2`、`1e5→100000`、版本 `1.0→1`。主代理现已将格式化限制于明确的统计数值列，身份列和参数键值原文保留。独立只读回归确认 donor `001.20`、unit_id `1e5`、参数value `1.0` 均不变，`proportion_difference=-0.0123456789012345`仍正确显示 `-0.0123457`；已阅读新增DOCX回归及主代理报告的最终9测试通过结果。无需科学重算。

该标识修复不改变本次Kang结果第8—9页的统计数字排版；已通过的修复预览视觉结论仍有效。最终API下载文件与此预览内容一致性由主代理随后核对，本审查不将本地预览当作最终API回执。

## CD4 pseudobulk 与 ORA Word 逐页复核

已实际打开 `word-CD4-pseudobulk/page-1.png` 至 `page-4.png`，以及 `word-CD4-ORA/page-1.png` 至 `page-4.png`，共8页。来源分别为 `CD4-pseudobulk-layout-preview.docx`、`CD4-ORA-layout-preview.docx`。**未发现新增阻断内容错误或明显布局缺陷。** 本轮只读PNG，未修改文档、未生成PDF、未启动统计计算。

- **DE第1—2页：** 英文方向明确为 numerator相对denominator，实际表格为stim/ctrl；方法保留donor_paired、PyDESeq2 Wald、单数值线程和未做LFC shrinkage。实际n为8+8、完整供者对8、rank9、残差df7；NA P值计数4、有效P值8511、family8515一致显示。固定作者标签依据与capture/condition完全混杂限制可读，未冒称生物学确认。
- **DE第3—4页：** 16/16行聚合单位完整，`spot_count`和`library_counts`均为实际整数，供者、condition及capture ID保留。结果摘录明确20/35635行，效应单位为log2 count fold change；NA、excluded/tested、负效应符号和统计有效数字正常显示。跨页表头重复，无数值拆断、遮挡或裁切。保存的中文warnings在英文报告中仍原文展示，不改变其含义。
- **ORA第1—2页：** 上游DE及基因集来源ID/SHA完整；明确both方向、q阈值0.05、绝对效应阈值1.0、集合大小15—500、实际受检全集背景及BH校正范围。资源记录保留Reactome官方来源、冻结下载标识和未推定release number说明；长键值正常换行、无裁切。
- **ORA第3—4页：** 概况为1020条受检term、25个显著term；背景表明确N=8515、前景n=275并解释两者含义。结果摘录明确20/1020行，term ID/名称及P/Q可读，0/NA边界说明完整；没有根据摘录冒称完整结果或作生物学解释。

以上是主代理从正式已发布成员核对SHA后、用当前adapter生成的本地版式预览；成员SHA核对属于主代理提供的前置证据，本审查未重做。最终API下载与预览的内容部件一致性仍由主任务核对；GSEA报告尚未纳入本轮视觉QA。

## 最终 API Word 内容一致性追加核验

主代理仅重启API后取得最终文件；审查者已读取 `word-api-content-checks.json`，并独立用ZIP读取逐部件二进制比较（只排除 `docProps/core.xml`）。四份最终文件与此前实际逐页QA预览均无内容部件差异，可复用对应视觉结论：

| 文件 | 相同部件数 | 最终字节数 | SHA256 |
| --- | ---: | ---: | --- |
| composition-description.docx | 17 | 100080 | fb708399dd91a28f1b1978b4ab4b04fc6ed750a95cfe5e8a1994cae05652113f |
| composition-paired.docx | 17 | 100372 | 9d03e9068a61f5d78a0550248813ad44f4effb37136b0290491e6888d8ea02a4 |
| CD4-pseudobulk.docx | 16 | 40614 | f127077c37cc4ec728e943ad5382bb7c286a99cc725307ac55abfafdc260ba92 |
| CD4-ORA.docx | 16 | 39974 | 422ed61593ff9dee326aa91f691621bbab10809001e740e1739145e3c7095bce |

其中后三份SHA/bytes与API记录一致；描述报告沿用此前正确的最终下载文件。该核验不重复科学计算，也不等于生物学解释验收。

## GSEA 最小内存修复独立复核

已只读审查 `bio_insights_engine/enrichment.py` 的新改动、`test_single_cell_batch5_gsea_memory.py`、既有GSEA回归、保存的GSEApy 1.3.1实际源码及正常父子执行证据。**未发现本次修复的实质阻断问题。** 审查者没有修改生产代码或重跑科学任务。

- **原生入口及完整null族：** 固定1.3.1 `Prerank.run()` 的单排名permutation分支调用同一个 `gseapy.gse.prerank_rs`，genes/scores/完整terms/weight/min/max/permutations/threads/seed参数顺序一致。新代码只调用一次、校验summary数量与term集合完全相同，没有分批拟合或拆分FDR族。ES/NES/nominal P/FDR/FWER直接读取同一native summary；原`to_df()`不再重算统计，只把全部曲线复制进Python对象，省略它不会改成BH或其他校正。
- **排序与表达：** 现有显式映射、有限分数过滤、many-to-one排除、statistic降序/ID升序、集合交集去重和大小过滤均未改。原高层使用`ascending=None`，源码确认不再重排ties。原`RES`即`gs.run_es`；新代码保留原peak选择、hit索引和leading-edge集合逻辑。负向leading-edge列表顺序沿用原引擎升rank顺序，公开API文本列表是反序；本次未改变集合含义或此前输出约定。
- **回归证据：** 新测试阻断高层`prerank`路径以确认不再物化全部Python曲线；两组正/反向fixture包含重叠集合、相同分数只命中一个gene的`tie_split`及乱序gene list，显式比较高层实际ranking的IDs/分数、五类统计量、hit索引和leading-edge集合。读取最终 `gsea-memory-tests-green.log`：12 passed in 3.80s；后端代理确认这是增强tie断言之后的最终日志，审查者未重复执行。
- **真实输入与原预算：** `gsea-streamed-resources.json`为passed、子进程退出0，实际8511排名、1019 eligible sets、1000 permutations；方法记录完整共同null族。正常parent→sandbox→parent路径的RSS high-water为1,864,864KiB，AS峰值2,770,744KiB，低于原RSS2GiB/AS3GiB；cgroup oom/oom_kill均0。保留原工作量/瞬时曲线准入预算、参数和单数值线程；native侧仍持有完整曲线，只将Python物化限制为逐term，不宣称native计算完全流式。
- **最终科学身份：** 独立计算当前digest为 `afa03529ba863948f7e045334d50c797ac6ed4f681276d2373f5b5db3b62b97f`，与当前 `bio-insights-runtime.json`一致，status=passed、aggregation/deseq2_fit/gsea/single_cell_propeller均true。原RSS/AS/CPU/时间/线程限制保持，file/network/fork/subprocess仍denied。前述 `7a8af1db...`属于修复前历史身份，现以本digest为准。

验证边界：本轮等价性针对明确映射后的精确ID输入、固定原工具版本和上述fixture。高层GSEApy另含mixed-case自动大写启发式，新入口不引入隐式ID转换；当前真实Ensembl精确ID不受影响，不将此结果扩写为所有任意大小写输入的行为完全等价。该成功回执是原失败输入的正常父子隔离复现；正式队列重试及GSEA最终Word页面仍由主任务继续验收。

## GSEA 正式结果 Word 四页视觉复核

主代理通知正式API队列重试成功，结果版本为 `644fc9a2-4c5e-5c3a-acc4-e6adf344b5fa`。审查者读取 `CD4-GSEA-result.json`，确认版本与1019条/8511排名/1824排除term的摘要；实际逐页打开 `word-CD4-GSEA/page-1.png` 至 `page-4.png`（`CD4-GSEA-layout-preview.docx`）。**未发现新增实质内容错误或明显布局缺陷。** 未修改DOCX或重复科学计算。

- **第1页：** 正式版本、上游DE与冻结基因集来源和SHA完整；complete_ranking/complete_input_universe为true，signed ranking、statistic、1000 permutations、seed0、weight1.0保留。校正明确为`GSEA_joint_null_FDR_not_BH`，exclusions显示4，未冒充BH结果。
- **第2页：** 排序明确statistic descending/stable ID ascending、ties0、native入口及完整family说明可读；`zero_empirical_p_note`明确零值保留且不代表无限显著性。资源出处及未推定release number说明完整。1019个eligible集合及完整family标志正常显示。
- **第3—4页：** 总排名8511、term行数1019与保存摘要一致，结果表明确20/1019摘录。NES正负号、nominal P和FDR有效数字均完整单行；首行nominal P=0保留为0，`fdr_q_value`为实际数值，通用`q_value`为NA。长term名称正常换行，跨页表头重复，无裁切或重叠；解释边界完整。

本报告方向由可读的`CD4_stim_vs_ctrl`对比标识及保存的降序statistic方法定位；页面仅显示排除数4，具体排除原因保留在下载表，不将页面核查写成已展示逐基因NA原因。正式队列峰RSS1,865,100KiB为主代理提供的执行证据，本审查未重复采样。该文档当前是从正式成员核对SHA后生成的本地版式预览，最终API下载与预览部件一致性仍待主任务核验。

**GSEA最终API文件追加核验：** 已读取更新的 `word-api-content-checks.json`，并独立比较 `CD4-GSEA.docx` 与上述已逐页检查预览。排除core.xml后16个ZIP部件全部相同；最终40107bytes、SHA256 `fea64a2901dced5d26600ca2831fef5ce9ad00abdd0c7eb2dc8ba9c853e2212b` 与API记录一致，视觉结论可用于此最终文件。

## PBMC 单供者描述最终 Word 四页复核

已实际逐页打开 `word-PBMC-description/page-1.png` 至 `page-4.png`，对应正式API下载的 `PBMC-one-donor-description.docx`，结果版本 `7ff54513-df4a-584a-adf5-073286b71672`；另读取 `pbmc-description-checks.json` 的保存断言与计数。**未发现新增实质内容错误或明显布局缺陷。** 本轮没有改文档、重算科学结果或启动容器。

- **第1—2页：** 单原始供者、单healthy条件、仅描述模式及候选标签来源清楚；config/methods/summary的labels_confirmed均为false。明确“不构造第二组，不计算组间差值、比值或P值”，并说明候选标签不能解释为已确认细胞身份。总细胞2368、condition_count=1、unit_count=1。原始设计字段n_numerator=0/n_denominator=1、pairs/rank/df=0忠实保留同条件合同，正文未将其解释为两组比较。
- **第3页：** 唯一供者条件单位healthy含2368cells；七类完整表为1059候选标签、875unknown、434uncertain，另一个候选标签/conflict/unlabeled/other为0；全部使用2368分母且合计2368，无漏掉未知或重复计数。七行差值/比值/t/P/q全部NA，状态为not_requested、原因single_condition_description、比值状态not_applicable_single_condition，空值没有写成零效应或阴性结论。
- **第4页：** 保存组成图为单一供者/healthy柱，三段可见比例与表格约0.447/0.370/0.183相符；零类保留图例，纵轴、长横轴标签、图例和SHA完整，无裁切或叠压。解释边界未把技术重复或候选标签当作独立供者/生物学验证。

本次完成最后这份单供者描述的直接Word页面QA。独立绘图任务的最后GSEA bar图由主代理另行检查，本审查不把Word页面结论扩展为该后续图件已验证。


## 主代理最终交付补充

GSEA bar正式结果3157bcdc-2843-5b8c-b3bd-6619c773f9d5已发布，主代理实际查看2700×1800 PNG，标签及NES正负方向清晰。1019原结果条目和15个显示条目与原dot完全一致，FDR=0表述经保存值核对；未重算GSEA。6份正式API Word共35页已完成既定视觉与内容比对，交付时四个服务healthy、当前全部分析任务succeeded，机器记录batch5-delivery-checks.json。

2026-11-06用户明确验收通过，本批4个服务已停止且容器保留，其他运行服务未变。数据库数量及6份Word和本次核对的输入文件哈希停服前后一致；收尾证据见`script/.runtime/single-cell-batch5/batch5-closeout.json`，详细记录见七批实施记录。第6—7批未开始，等待用户确认第6批。

# 第5批后端接线与验证记录

2026-11-05。本分工负责 bio-insights 合同、来源/预检、隔离数值执行及父进程验证。沿用现有 comparison 任务/计划/存储，不增加审批或对象版本体系；未提交、推送、清理或操作业务 schema。前端、R 原生桥接、镜像和 Word 由其他分工负责。

## 已实现

- `SingleCellCompositionConfig` 使用既有 `comparison` 的 `schema_version=5` 分派。支持 `descriptive / donor_unpaired / donor_paired`，冻结 processed、annotation、选定标签和条件、人工依据、供者独立性依据及 batch 项。缺少供者时可以仅描述，不产生 P 值。
- 按 donor × condition 合并技术 sample；供者未知时按已知 sample 作描述单元（仍无独立供者 n）。选定条件内全部保留细胞是分母；assigned 且选中标签进入对应 label，其余 assigned 进入 other，unknown / uncertain / conflict / unlabeled 单独保留。每个细胞仅分配一次。没有某个条件时仅描述现有条件，缺失侧比例与差值为空。
- 推断检查每组至少3供者或3完整供者对、明确映射/独立性、成对完整性、batch唯一/完整/至少两水平、混杂、矩阵秩及残差自由度。不合格在排队前阻断；工程下限不是功效保证。
- 用真实 speckle 桥接，原生设计、contrast、比例、变换、日志、版本另存 `propeller_native`。完全无可检验变异保存 `not_computable` 和空 P/FDR。原生安装及独立工具对照见 R 分工报告。
- 同类型 DE 在原 `ComparisonConfig` 增加 `single_cell_selection`，服务端与数值子进程各自重验固定 annotation、保留细胞、assigned 标签成员。继续使用原整数 raw counts 聚合与 PyDESeq2 0.5.4，并保留受检全集供原 ORA/GSEA 使用。旧空间请求的多 batch 预检语义保留。
- 修复供者 DE 按 cell × gene 稠密内存估算的误拒绝：按现有10m nnz稀疏上限、元数据和 donor × gene 稠密聚合/拟合块估算；未扩大20k cells、100k features、10m nnz及2GiB RSS / 3GiB AS限制。
- Worker 与正常 runtime probe 在固定 ABI bootstrap 后、一切用户输入读取前，初始化最小 propeller；不预热其他单细胞 R 计算。额外仅授予固定 R 前缀只读和本 attempt `/tmp/b04-propeller-*` scratch。网络、fork、任意用户文件仍禁止。
- 固定科学代码 digest 包含新合同和 R 实现；组成 gate 除正常 gate 外还需真实隔离 `single_cell_propeller` 检查与固定 R/speckle/limma/statmod 版本。rpy2 初始化的 stdout 诊断被转到 stderr，避免污染 JSON 协议。
- 完整 frozen source 仍保留原始标签 cell_ids/cluster_ids；数值 transport 仅删去 assignments 已覆盖的重复标签成员列表。
- 父进程独立重算组成分子、分母、成员、实际供者和均值，核对保存表、方法、方向、原生结果与发布摘要；描述结果带 P 值会被拒绝。

## 接口

配置必需字段：`kind='comparison', schema_version=5, method='single_cell_composition', processed_source_id, annotation_source_id, label_ids, numerator, denominator`。

其余字段：`labels_confirmed, label_basis, mode, mapping_confirmed, independence_confirmed, independence_basis, batch_adjustment, transform='asin', output_language, purpose`。组成不需要虚构基因 namespace；来源中真实已有声明仍保留。

同类型 DE 保持原合同，新增 `single_cell_selection={processed_source_id,annotation_source_id,label_ids,labels_confirmed,label_basis}`；`contrasts.*.observation_keys` 必须是指定标签与条件的明确交集，不能注入其他细胞。

| 成员 | 主要字段 |
| --- | --- |
| composition_counts | unit_id, donor, condition, category, label_id, cell_count, denominator_cells, proportion |
| composition_units | unit_id, donor, condition, batch, batches[], samples[], cell_count, batch_complete |
| composition_assignments | processed_version_id, barcode, unit_id, donor, condition, sample, batch, category, label_id, annotation_status, annotation_label_id |
| composition_results | category, label_id, numerator, denominator, mean_proportion_denominator/numerator, proportion_difference/ratio, ratio_status, t_statistic, p_value, p_adjust, inference_status, reason |
| composition_design / composition_methods | 既有 DesignPreview；固定 config、actual_units、warnings、label_names、R设计/版本/日志/引用 |
| propeller_native | 真实桥接返回的全部数值，仅推断运行存在 |
| composition_plot | 保存比例的 PNG，标签使用冻结 annotation 的 name，原 ID 保留在数值表 |

`actual_units` 复用 `n_numerator/n_denominator, spots_numerator/spots_denominator, complete_pairs, numerator_donors/denominator_donors, design_columns, design_rank, residual_degrees_freedom`；spots字段在本路径明确表示 cell 数。描述存储 scope 沿用 `sample_exploratory`，方法名为 `single_cell_composition_descriptive`，不声称独立样本推断；推断 scope 为 `donor_inference`。

## 本机与隔离 DB 验证

- 初始 `backend/.venv/Scripts/python.exe -m pytest backend/tests/domain/test_single_cell_composition.py -q --tb=short`：7 failed，证明 schema5 缺口、未知状态计数路径缺口以及原 `aggregate_batch_not_unique/resource_budget_exceeded` 实际误拒绝。修复后7 passed。
- 数值 fixture 初始3 failed，修正测试 sources 的 list 类型后重跑：真实失败落在 schema5 分派缺失与 DE 选择未约束；实现后描述发布、PNG、选择拒绝、父进程分母篡改拒绝通过。此类 fixture 不代表真实 R 模型。
- 新增单条件描述与旧空间 batch 兼容：2 failed → 通过。
- 新增 transport 冗余成员与标签可读名字：各1 failed → 通过。
- 审查指出单一 batch 启用调整的预检/原生不一致：`test_adjustment_requires_multiple_real_batches_before_queueing` 1 failed → `single_batch_adjustment` 阻断后通过。
- 最终本机定向命令：`backend/.venv/Scripts/python.exe -m pytest backend/tests/domain/test_single_cell_composition.py backend/tests/numeric/test_single_cell_composition.py backend/tests/domain/test_bio_insights_process.py -q --tb=short`：**41 passed in 4.60s**。
- 隔离 DB 命令：`backend/.venv/Scripts/python.exe -m pytest backend/tests/api/test_single_cell_batch5_insights.py backend/tests/numeric/test_single_cell_composition.py backend/tests/domain/test_single_cell_composition.py -q --tb=short`：当时 **14 passed in 24.94s**。HTTP测试真实创建独立 `pa_test_*` schema，走 preview、confirmed plan、排队任务、来源隔离和标签变化检查，基础分析计算次数仍为1。父基础分析使用明示 fixture；runtime仅该生命周期测试中注入，不作为科学 gate 证据。最初把可读的历史 get_run 元信息误当作来源检查端点，已改为验证会重新检查来源的 get_plan；未改变历史读取语义。
- 新增 `test_single_cell_batch5_pseudobulk.py`：专测真实 PyDESeq2 选定细胞原 counts、技术样本合并、受检背景 ORA 与 GSEA。Windows缺少固定 pydeseq2，运行报 `ModuleNotFoundError`，未假称通过；等待串行科学容器时段执行。

## 正式科学环境与待补

R分工报告已证实小型隔离 speckle 调用真实完成、file/network/fork denied，RSS约809MiB；这不是完整正式 gate。`run-insights-probe.ps1` 已准备于本批 runtime 目录，将只保存实际 JSON 成功结果至 `bio-insights-runtime.json`。配置环境变量为 `PAPERASSIST_BIO_INSIGHTS_RUNTIME_MANIFEST` 指向容器内这份文件。

本记录写入时，正常完整 insights gate、selected-cell PyDESeq2→ORA/GSEA容器测试、真实公开Kang供者HTTP/队列/Worker及Word/页面验收尚待串行运行；不以本机fixture或mock环境代替。上述后续证据完成后在此续记。

## 后续实际科学证据（续记）

- 经主代理分配串行运行时段，`paperassist-single-cell-worker:b5-propeller` 中 `/opt/paperassist-bio-insights/bin/python -m pytest tests/numeric/test_single_cell_batch5_pseudobulk.py -q --tb=short`，network none / 1CPU / 2GiB：**1 passed in 4.36s**。独立核对6个donor×condition聚合单元、12个实际选定细胞、逐基因原始整数 counts 与原矩阵行和完全一致；DE保留80个原始基因而非仅2个processed保留基因，零计数g79不入受检背景；ORA真实背景N=79且空前景合法；真实GSEA仅取实际可用统计量，保留donor_inference上游范围。日志：`script/.runtime/single-cell-batch5/pseudobulk-numeric.log`。
- 首次完整正常 `runtime_probe` 真实通过：aggregation/deseq2_fit/gsea/single_cell_propeller均true、单线程、RSS **1,079,976KiB**，file/network/fork/subprocess均denied，版本R4.4.3/speckle1.6.0/limma3.62.1/statmod1.5.2。receipt保存至本批 `bio-insights-runtime.json`，诊断stderr另存，stdout为单一JSON。
- 继续验证正常父服务解释器→隔离Worker时，捕获真实失败 `environment_identity`。差异探针证实 Worker 的 `actual_identity()` 固定导入skbio.stats.distance，加载了额外scikit_bio OpenMP库，而原probe没有同样预导入。已仅在probe采集真实库存前补相同导入；没有更改identity比较、伪造available或放宽native核验。差异材料：`insights-identity-diff.json`。新的完整gate及parent调用等待串行时段重跑。
- 兼容性定向命令：`backend/.venv/Scripts/python.exe -m pytest backend/tests/domain/test_bio_insight_contracts.py backend/tests/domain/test_bio_insight_design.py backend/tests/domain/test_bio_insight_service_feature_axis.py backend/tests/domain/test_bio_insight_transport_projection.py backend/tests/domain/test_bio_sample_enrichment_design.py -q --tb=short`：**56 passed in 5.95s**。`git diff --check`针对本分工改动通过。

## 最终接线核验与冻结

- UI核对补充单条件合同：仅descriptive允许numerator==denominator；condition_count=1，只有实际单条件分母与均值，第二组n/cell数为0、均值为空，组间difference/ratio/P均为空，reason=`single_condition_description`。推断仍拒相同条件。两个新增测试 **2 failed → 通过**。
- 历史兼容自审补充：ComparisonConfig新增optional字段若把None序列化入旧frozen wire，会改变旧请求。新增失败测试后，采用现有合同相同的wrap serializer，仅在single_cell_selection为None时省略该键，真实选择完整保存。命令覆盖组成、父process、旧合同/设计/transport，共 **94 passed in 11.64s**。
- 最终正常probe已对齐真实Worker的scikit-bio原生库库存；先前真实parent失败已消除。**未替换identity比较或伪造available**。三类正常parent调用均真实经过服务解释器→固定数值解释器→沙箱→父校验：双条件描述60cells、配对propeller60cells completed、单条件描述30cells。保存于`insights-parent-probe.json`。
- 启动本批resident后，GSEA实际出现EAGAIN。实测新Worker属于UID10001且空闲cgroup已有39 tasks；原RLIMIT_NPROC=64按同一real UID跨PID namespace计线程/进程，不能代表本数值子进程的并发。这与probe自身pids未到容器256、但新建单个GSEA线程失败相符。主代理明确授权按实证修复；**仅insights sandbox将该共享UID guard改为256**。没有改其他sandbox、RSS2GiB/AS3GiB、数值线程1、same-process clone约束、fork/exec拒绝。主代理另将本批parent服务的BLAS/OMP/MKL/NUMEXPR固定1，防止API/Worker各自预开32线程；256不是计算线程数。
- 最终完整probe：**status=passed，numeric_threads=warm_threads=1，shared_uid_process_limit=[256,256]，file/network/fork/subprocess全部denied，aggregation/deseq2_fit/gsea/single_cell_propeller全部true，峰RSS1,144,120KiB**。最终code digest：`6cca5ecb02f6caefa28f60d3bede9b18d935ccbd3c263dec1ca7360df93756f9`；environment digest：`fa6b07fd4b1a2f1af87659cd1fcfb34a44627619581ffaca57660301cfa169af`。正式receipt：`script/.runtime/single-cell-batch5/bio-insights-runtime.json`。
- 最终receipt下再次正常parent调用：runtime_identity和composition_runtime_identity均真实available，paired60cells完成、3个完整供者对、模型rank4/残差df2、child峰RSS1,220,488KiB，仍低于2GiB。材料：`insights-parent-probe-final.json`。此为有界合成科学数据的完整父子/隔离检查，不替代公开Kang队列验收。
- `git diff --check`针对本分工修改通过。后端源码已通知主代理冻结；真实公开Kang HTTP/queue/Worker、页面和Word最终结果由主代理继续记录。本分工没有提交、推送、停止他人服务、删除输入或修改业务schema。

## 公开数据独立核验脚本准备（尚未声称结果通过）

主代理补充分工后，新增仅运行材料 `script/.runtime/single-cell-batch5/verify_public.py`。脚本不导入业务服务、不接DB、不创建/重试任务、不修改state或源矩阵；除本地API登录外只GET。账号、cookie、CSRF仅内存，输出与cache不含凭证。

准备检查命令：`backend/.venv/Scripts/python.exe script/.runtime/single-cell-batch5/verify_public.py --check-inputs`，输出`inputs_verified_only`：6400个唯一capture-prefixed细胞、35635个稳定基因、8完整供者对，每个donor-condition400cells；输入文件逐项SHA与provenance一致。**results_verified=false**，尚未运行真实结果核验。

完整模式从`single-cell-acceptance/state.json`的`batch5_cases.kang`读取真实ID，经本地API下载并校验每个保存成员SHA/字节。分10万坐标块读取原MTX，逐值比对已导入raw CSR和processed selected raw counts，并独立聚合16×35635的CD4 donor-condition整数块；验证作者2584个CD4细胞成员、原counts逐基因和、8pairs、全部DE基因及预过滤受检全集。组成独立按原作者metadata重计分子/分母、全部6400cells/16units×400。ORA背景/前景与实际DE tested/阈值匹配，GSEA验证全部有限可排序统计量无截断、顺序/数值/row key一致、缺失值排除可追溯。只验证身份、计数和保存数值，不重新拟合模型或推断生物学结论。

待真实result IDs就绪，由主代理运行默认命令；输出`public-data-verification.json`。未就绪返回`not_ready`，不会伪造通过。

## 真实6400细胞 transport 缺陷与修复

主代理正式composition-description任务`468a0316-a812-504c-97f7-e0352e64758f`在数值进程启动前失败。只读重新解析该任务冻结来源后实测：完整snapshot **3,033,557B**；旧数值wire **2,151,354B**，超过固定2MiB（2,097,152B）54,202B。大字段为processed observations **1,486,332B**和重复annotation assignments **626,175B**，geometry仅593B。不是模型错误或内存超限。

最小修复仅从本批single-cell comparison transport删除已存为hash声明成员的重复`metadata.assignments`；全部观测对应表逐值保留，完整冻结snapshot不变，assignment成员路径/hash不变。数值pipeline只在Worker进入隔离后，从该成员校验实际bytes/hash并恢复独立副本供现有数值代码使用。manifest/recipe保持compact source bindings，避免结果JSON再次重复膨胀。未新增紧凑表版本/框架，未抽样或缩数据，未提高2MiB/2GiB上限。

- 新增两个失败测试：重复字段仍在wire、隔离后恢复函数缺失；修复后组成/父process/原transport定向 **48 passed in5.61s**。成员实际字节被篡改时恢复拒绝；projection幂等、恢复副本不修改compact源。
- 实测修后同一真实payload wire **1,525,164B**；含正常runtime和output路径的实际发送体 **1,525,554B**。真实2584 CD4细胞选择的DE合同干测 **1,794,106B**，均低于2MiB。材料：`transport-size-before.json`、`transport-size-after.json`、`de-transport-size.json`。
- 正常完整gate已重跑通过；最终code digest **`7a8af1dba86641e3f0f7861f0ad0db84b0ff7f969525e67e67ab06f68dce975c`**，环境digest不变。正式receipt仍是本批`bio-insights-runtime.json`。
- 使用失败任务的**实际6400公开细胞来源与原组成config**，仅以当前真实runtime做独立正常parent执行（不创建任务、不写DB、不发表结果），完整parent→固定数值解释器→沙箱→父校验通过：**6400cells、16units、8完整供者对、child峰RSS1,333,676KiB**。材料`kang-parent-transport-check.json`和独立输出目录。原失败task/staging/input/source/数据全部保留。
- 已通知主代理restart本批服务加载parent与新gate后，复用已保存plan/source_digest，用新run请求键正常重试；正式队列成功与公开数据独立结果audit仍由主代理后续记录。

## 剩余正式请求合同只读检查

主代理运行真实DE后要求轻量检查后续请求。离线从当前`seed_batch5.py`提取resource/enrichment/figures函数，仅用拦截器捕获构造值，未发HTTP/创建任务/修改脚本或state。1个ResourceImportRequest及5个InsightPlanRequest（ORA、GSEA、3个figure）全部通过当前严格模型。上传实际服务代码返回扁平`file_id/sha256/...`，脚本fallback表达式正确；GMT不要求parse_version。图件省略显式列也正确：volcano自动effect_value/q_within_contrast，ORA使用gene_ratio/q_value，GSEA富集点图使用NES/fdr_q_value。当前GSEA图为富集点图，不冒充running curve。材料`remaining-request-contract-audit.json`。此检查只证明请求合同与返回形状，未声称尚未完成的模型、预算或图件验证通过。

## 真实GSEA RSS失败：定位、等价优化与实际复现

正式任务`190ebfe1-b152-581c-9b41-86c5dda7afc0`失败后，先按systematic-debugging读取保存attempt及当前parent/child限制。原attempt仅输入和receipt，没有输出或Python失败诊断；通用child runner原有stderr为DEVNULL，无法从旧stderr倒推异常。居民worker cgroup memory.events中oom/oom_kill均0。

经主代理串行授权，使用该任务的实际冻结来源/配置（不重算DE/资源、不给任务/DB写入）做一次正常parent→隔离Worker复现，仅在运行材料脚本中捕获stderr和50ms /proc计数，原2GiB RSS / 3GiB AS / 1000置换 / 单数值线程 / 沙箱均不变。证据`gsea-reproduce-resources.json`：**47.967s后returncode=-9，VmRSS/VmHWM2,108,296KiB超过2GiB(2,097,152KiB)，VmPeak3,014,124KiB低于3GiB，容器oom=oom_kill=0**。最后约1s RSS从1.86GiB连续上升至2.01GiB，故为parent RSS监控SIGKILL，不是AS、输出或容器OOM。被杀前数值是旧路径峰值下界，未声称旧路径完整运行最终峰值。

直接读取安装的锁定GSEApy1.3.1源码：`gsea.py:605-615`的Prerank.run permutation路径调用`gseapy.gse.prerank_rs`，随后`base.py:_to_df`把全部`run_es`物化为Python float列表并保留在results/中间DataFrame。8511×约1019条完整曲线的这层驻留量约265MiB；本引擎最终只保存hit_indices和leading edge，无需全部Python曲线同时存在。安装源码快照留在`gseapy-1.3.1-source.json`。

主代理同意后，最小修改enrichment.py：**使用同一个锁定原生permutation入口、完整同一family一次拟合、完全相同genes/scores/terms/weight/min/max/seed/1000perm/threads1**，从完整native summaries逐term读取曲线接入原输出循环；没有复制ES/NES/FDR算法、拆分null族或减少排名/基因集/置换。原生summaries仍驻留并拥有完整曲线；只避免额外保留所有Python list/DF曲线，不把它描述为零曲线内存或按term分批统计。方法成员明确记录`native_entrypoint=gseapy.gse.prerank_rs`、`running_curve_materialization=one_term_at_a_time_from_complete_native_family`。

验证证据：

- 新增内存路径失败测试先**1 failed**（捕获旧高层prerank全曲线物化入口）；实现后通过。
- 固定工具原public `gseapy.prerank`独立对照：正向/反向并列排名、仅命中并列一侧且输入gene顺序打乱的term、重叠gene sets同一joint-null；以public实际returned ranking核对ID顺序和统计量，再逐项对照ES/NES/nominal P/FDR/FWER/hits/leading edge，rtol1e-12/atol1e-14。新增与既有GSEA数值套件：**12 passed in3.80s**。
- 科学镜像仅包含科学依赖，首次误加载通用DB conftest会报缺sqlalchemy；改为明确`--confcutdir=tests/numeric`运行纯文件/科学数值套件，无DB、无跳过数值断言。日志`gsea-memory-tests-green.log`。
- 本机父process/合同/组成兼容定向：**45 passed in7.39s**，`git diff --check`通过。
- 完全相同真实输入的优化路径在**原2GiB RSS/3GiB AS**正常parent→固定解释器→沙箱→父校验**47.946s完成，return0，child真实峰RSS1,864,864KiB（约1.78GiB），VmPeak2,770,744KiB，容器oom=oom_kill=0**。实际8511个完整可排序基因、2843资源terms按原规则筛为**1019**个合格terms（1824排除），1019个均完成同一联合null/FDR。之前1020为估算，最终记录以实际saved summary为准。证据`gsea-streamed-resources.json`、`gsea-streamed-child.stderr`和独立输出`gsea-reproduce-4_g99bin`。
- OS采样最多2个线程是主线程加原生单worker；原生调用threads=1、BLAS/OpenMP固定1未变。未启用额外数值并行、fork/网络或全局/专项内存扩容；经授权的3/4GiB诊断档未使用。

当前源码已冻结，正常insights gate重新验证后由主代理重启本批服务、复用旧plan以新run正常队列重试。原失败任务和全部输入/运行材料保留；以上direct真实数据复现尚不冒充新正式队列发布。

最终GSEA收尾补记：增强tie_split（只命中同分g0、不命中g1，gene set输入乱序）和原public实际returned ranking断言后，完整12项数值回归再次**12 passed in3.80s**，这是最终green日志。正式receipt先备份至`bio-insights-runtime-pre-final-gsea-gate.json`后，再次正常运行探针，status=passed，code digest **`afa03529ba863948f7e045334d50c797ac6ed4f681276d2373f5b5db3b62b97f`**，RSS2GiB/AS3GiB、numeric_threads1和四项隔离拒绝均保持。主代理/独立审查已核对当前digest与receipt相符；已通知源码冻结、无在跑Docker科学任务，可复用旧plan以新run队列重试。

等价性验证范围明确为本批真实Ensembl稳定ID及已测正反向/tie/重叠family输入。原public wrapper对某些mixed-case gene symbols与uppercase sets有自动大写预处理；新调用保持已显式匹配的原ID，不把所有任意大小写输入的wrapper预处理等价性写成已证明。负方向leading-edge输出顺序沿用本引擎原有升rank顺序，公开wrapper显示为反序；已验证集合与hit位置，未将其误记为本次新差异。

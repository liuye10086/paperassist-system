# Bulk RNA-seq 矩阵下游分析通路总领方案

日期：2026-11-09。开发分支：`feat/bulk-rna-downstream`。起始代码基线：`b520f776c8e5baa954c9122ff3fd6add088f9700`。

## 1. 文档用途、当前授权与状态

本文件统一管理整个 Bulk RNA-seq 矩阵下游通路的范围、统计方案、限制调整、实施批次和验收证据。后续批次在同一开发分支推进，优先扩展现有系统，不另建上传、任务调度、结果版本或报告平台。

**B01—B08 均已由用户验收通过。B08 已于 2026-11-11 登记为 `user_accepted`，相关服务已关闭，等待用户下一步指示。** 各批次的代码、配置、数据、验证证据和验收记录保留，已登记的科学及资源边界不变。依赖安装、数据或参考资源下载、真实用户数据分析、提交、推送、合并、生产部署、付费调用和客户数据外发分别按用户授权执行。

用户要求将应改造的实现和应放宽的限制纳入计划，不能把它们全部留到后续。容量提升必须贯穿上传、导入、传输、计算与导出，并通过实际验证确定支持范围；不能只调大一个常量。

### 1.1 A vs B 的含义

用户已澄清原图文字为 **A vs B**，即 A 组与 B 组的比较，属于差异分析主线，不增加独立功能或外部依赖。

- 在本通路中选择 **A vs B** 时，A 为 numerator / tested level，B 为 denominator / reference level。
- `log2FC > 0` 表示经模型估计 A 相对 B 上调，`log2FC < 0` 表示 A 相对 B 下调。不是对原始样本均值直接相除后代替统计模型。
- 显式保存比较方向、参考组和纳入样本；不根据字母顺序、上传列顺序或排序结果自动决定对照。
- 切换为 B vs A 是科学参数变化，须重新确认相应比较；可以复用适用的已拟合对象，但不能只替换标题或覆盖 A vs B 的历史结果。

### 1.2 状态口径

本文件的“已有”表示在基线源码中发现真实实现及调用，不表示当前环境已经运行通过。只读审查未运行测试、数值分析或业务服务；历史文档中的用户验收和旧门禁不作为本轮通过证据。

| 层级 | 当前状态 |
|---|---|
| 分支与总领计划 | B01—B08 已登记用户验收通过；B08 停服与文档收尾完成，等待用户下一步指示 |
| 本轮功能代码 | 覆盖输入、QC、模型审阅、共享拟合、固定结果发布、多比较筛选、候选查询、固定图件和本地注释与 ORA/GSEA |
| 当前依赖及真实计算 | 已在隔离 PostgreSQL、Docker 固定 worker 和 Edge 验证公开 `airway` 的 QC、配对差异、固定图件和 Reactome ORA/GSEA。已验证 GO OBO/GAF 和 ID 映射导入。真实用户数据和 60,000 × 50 大矩阵容量待验证 |
| 本轮真实数据与独立参考比较 | 公开 `airway`、`pasilla`、`fission` 四种设置已完成独立 R 全量对照，跨引擎超差原样留档 |
| 用户通路验收与生产部署 | B01—B06 用户验收通过，真实用户数据运行和生产部署待后续验证 |

## 2. 业务分工、目标与范围

实验、建库、测序，以及 FASTQ 上游质控、比对、定量和矩阵生成由实验室、测序机构或客户选择的生信服务商完成。本平台本次负责：

**基因 × 样本 raw counts + 样本信息 → 输入检查 → 样本 QC/PCA → 模型审阅与确认 → 差异表达 → 本地 ORA/GSEA → 图表、结果数据、分析对象和 Word。**

这里的 raw counts 是上游处理后得到的未归一化计数矩阵，不是 FASTQ。

| 范围类别 | 本次约定 |
|---|---|
| 必须真实实现 | 完整矩阵下游流程；必要的输入、设计、容量、运行环境、图表、资源和报告改造；失败路径、权限、恢复和单细胞兼容验证 |
| 优先复用 | 文件治理、研究设计、tabular 导入、PyDESeq2、离线富集、结果版本、任务队列、图表、证据关联、Word 和复现包 |
| 可选，默认不纳入核心验收 | Salmon/tximport 本地定量文件导入、LFC shrinkage、批量压缩包导入、UpSet/Venn；新增时先明确适用输入及验证范围 |
| 暂缓新增外接能力 | FASTQ 上游运行服务、新云计算平台、新第三方生信 API 的认证/上传/提交/轮询/计费/回收、依赖未取得授权或付费订阅的数据库 |
| 后续专题 | 交互项、随机/混合效应、复杂时间序列、差异剪接和转录本使用等；不能将简单 Wald 比较包装成这些能力 |
| 已有外部服务 | 保留既有可用接口、大模型与内部后端能力；本次核心计算不强制依赖新增外部生信服务 |

不把重型上游计算改成本地部署后绕过暂缓范围。不将用户数据自动发送给外部服务。软件和参考数据的部署期准备与运行时外部 API 依赖分别登记。

## 3. 现有能力与复用依据

以下路径相对仓库根目录；链接直达 owning source。源码判断基于上述代码基线。

| 编号 | 能力与具体依据 | 当前事实及本次缺口 |
|---|---|---|
| E01 | [file_batches.py](../../../backend/app/domain/file_batches.py) `BioUploadService`；[bio_datasets.py](../../../backend/app/api/bio_datasets.py) | 已有批次登记、原件上传、SHA、幂等和所属项目校验；上传上限当前 128 MiB，复用基础治理。 |
| E02 | [tabular_contracts.py](../../../backend/app/domain/bioinformatics/tabular_contracts.py) `BioImportRequestV3`；[tabular_assays.py](../../../backend/app/adapters/bio_engine/tabular_assays.py) `import_tabular` | 已有 Bulk counts、样本表、可选特征表和 CSV/TSV/XLSX；真实校验样本集合、重复 ID、非数值、缺失、负数和非整数。实际导入仍受 10 MiB / 累计 100 万单元格限制。 |
| E03 | [research_intake/contracts.py](../../../backend/app/domain/research_intake/contracts.py)；[quantitative_design.py](../../../backend/app/domain/bio_insights/quantitative_design.py) `validate_quantitative_design` | 研究设计和 Bulk 样本设计均存在；已有独立生物学单位、配对、批次、秩和残差自由度检查。需统一导入样本与研究设计的关联，扩展加性协变量模型。 |
| E04 | [tabular_assays.py](../../../backend/app/adapters/bio_engine/tabular_assays.py) `run_tabular` | 已实际计算样本 QC、中心化 SVD PCA、解释方差和 average-linkage 聚类。需补 Bulk 指标、VST、相关性/距离热图、分组及批次标注。 |
| E05 | [counts_model.py](../../../backend/app/adapters/bio_insights_engine/counts_model.py) `fit_counts`；[quantitative.py](../../../backend/app/adapters/bio_insights_engine/quantitative.py) `run_quantitative` | 已有真实 PyDESeq2 0.5.4 计数模型、Wald、原生 padj、size factors、模型矩阵与收敛记录。当前逐 contrast 两侧子集拟合，公式为独立/配对/批次三选一。 |
| E06 | [quantitative_contracts.py](../../../backend/app/domain/bio_insights/quantitative_contracts.py)；[InsightPlanEditor.tsx](../../../frontend/src/features/bio-insights/InsightPlanEditor.tsx) `start` | 现有 counts 合同拒绝 paired + batch；前端一次“开始分析”内自动预检、保存 confirmed 并提交任务。需先呈现最终模型，用户审阅后确认。 |
| E07 | [enrichment.py](../../../backend/app/adapters/bio_insights_engine/enrichment.py) `run_enrichment/_ora/_gsea`；[resources.py](../../../backend/app/adapters/bio_insights_engine/resources.py) | 已真实支持本地 ORA/GSEA、受检背景、映射审计、完整排名、leading edge 与曲线。需准备合法默认资源并连接 Bulk 完整流程。 |
| E08 | [figures.py](../../../backend/app/adapters/bio_insights_engine/figures.py) `run_figure`；[quantitative_figures.py](../../../backend/app/adapters/bio_insights_engine/quantitative_figures.py) | 已从固定结果绘图；热图行 z-score 是显式展示转换。需增加 MA、Bulk QC/PCA 重绘；火山图当前着色阈值固定，需与筛选一致。 |
| E09 | [task_execution_store.py](../../../backend/app/adapters/task_execution_store.py)；[local_cancel.py](../../../backend/app/domain/tasks/local_cancel.py)；[bio_insights/execution.py](../../../backend/app/domain/bio_insights/execution.py) | 可复用权限、租约、排队、执行、取消和受控重试。现有取消范围不完整覆盖 bio_import 与 waiting_confirmation，应补全相应用户流程。 |
| E10 | [analysis_service.py](../../../backend/app/domain/bioinformatics/analysis_service.py)；[bio_insights/service.py](../../../backend/app/domain/bio_insights/service.py) | 已按固定输入、参数、环境和结果完整性复用；需要补“当前研究设计改变后下游过期”的整条流程语义，不删除旧结果。 |
| E11 | [research_results/reports.py](../../../backend/app/domain/research_results/reports.py)；[research_report_docx.py](../../../backend/app/adapters/research_report_docx.py)；[reproducibility.py](../../../backend/app/domain/bio_insights/reproducibility.py) | 已有 Word 与复现包基础。Bulk 快捷交付部分共用单细胞报告适配器，需专用事实投影、标题/方向/指标及完整报告聚合；复现包不包含全部原生解释器。 |
| E12 | [infra/worker/Dockerfile](../../../infra/worker/Dockerfile)；[compose.workers.yml](../../../compose.workers.yml)；[worker_stack.py](../../../script/dev/worker_stack.py) | B03 已完成固定 worker 和重启恢复；B04 增加独立的 `bulk_model` 运行时收据并在同类隔离栈通过 `airway` 配对统计发布。真实用户数据待验证。 |
| E13 | [test_bio_quantitative_reference.py](../../../backend/tests/numeric/test_bio_quantitative_reference.py)；[test_bio_sample_enrichment.py](../../../backend/tests/numeric/test_bio_sample_enrichment.py) | 已有固定 R 输出对照和合成样本富集测试。它们可作回归基础，但不能替代本轮独立 R 重跑和真实 Bulk 端到端验收。 |

历史 [CR-B05 子包一记录](../阶段04/2026-11-01-客户需求完善第5批-子包一实施记录.md)记载 counts 等路径的验收，仅作为功能与材料线索。本次只读时，旧记录指向的 `script/.runtime/client-requirements-b05/references` 不存在；是否另有副本未核实，不根据旧路径承诺材料仍可用。

当前 checkout 是隔离 worktree，不会自动复制原工作目录的 ignored 依赖、运行配置、数据或参考资源。实施前要核对可复用位置，保留原业务资料，不能将新 worktree 的缺件解释为原材料已被删除。

## 4. 本次必须处理的限制

| 编号 | 当前限制/行为 | 计划调整及验收边界 |
|---|---|---|
| L01 | 上传 128 MiB，但 tabular 导入 10 MiB | 将 Bulk 导入预算与上传预算统一；用户提交前显示真实可用上限，不出现上传后才告知小文件门槛。 |
| L02 | 导入和模型等路径各自限制 100 万单元格 | 用统一、可配置的 Bulk 矩阵、峰值内存和时间预算替代散落限制；本次容量目标为 60,000 基因 × 50 样本，尚非已验证能力。 |
| L03 | 导入样本列、模型样本数和导出列数限制不一致 | 统一预检与执行校验，采用分块/流式数据处理；避免逐元素字典膨胀及导出时再次出现隐藏列数限制。 |
| L04 | 大型轴/元数据内联 JSON 可能超出传输预算 | 大数据以受管文件、固定轴文件和 SHA 引用传输；完整性、安全路径和输出白名单照常检查。 |
| L05 | 每组/配对固定至少 3 | 计划允许每组至少 2 个独立生物学单位或至少 2 个完整配对，并要求模型满秩、残差自由度大于 0 等条件；小样本明确警告。该数量只是准入下界，不等于功效保证；单重复不做正式推断。 |
| L06 | paired 与 batch 互斥 | 满秩且可估计时允许供者、批次及适用协变量同时入模；不能自动删除混杂项，不能把显示校正当统计调整。 |
| L07 | 多组指定比较反复抽出两组拟合 | 新方法按同一确认设计统一拟合，再提取指定 contrasts；冻结包含样本与模型，旧方法结果不追溯改写。 |
| L08 | Bulk 新草稿可能从空间/continuous 默认配置开始 | 按 assay 初始化新 Bulk 草稿；已有草稿与历史深链原样保留。 |
| L09 | 开跑自动把计划写成 confirmed | 独立展示最终样本、过滤、公式、参考组、contrasts 与警告，用户确认后提交；变化后旧确认失效。 |
| L10 | 火山图阈值固定、QC/PCA 重绘入口缺失 | 绑定当前筛选口径，支持保存数值重绘；修改 Top N/颜色/尺寸不重新拟合。热图 z-score 会改变展示值，应明确标注。 |
| L11 | 复用报告可能带单细胞名称与固定说明 | Bulk 专用事实合同及章节；有据可查才写“已完成”，禁止用固定 fallback 断言缺失数据或未执行方法。 |

保留身份认证、项目隔离、原始输入类型、设计可估计性、文件安全、磁盘配额、超时与内存治理。调整针对 Bulk 实际需求，避免无依据地全局放宽其他 assay。重任务沿用串行执行策略，查询、取消和心跳仍应响应。

## 5. 输入、统计与工程方案

### 5.1 输入与准备材料

- 必填：gene × sample 未归一化 raw counts、sample_metadata、物种 taxon、基因 ID namespace、参考版本、上游生成方式、实验组/对照及明确比较。
- 设计需要时填写 donor / biological_unit_id、pair_id、batch 和分类/连续协变量。列映射后确认样本集合与对应关系；不按位置猜测配对。
- 优先 CSV/TSV；保留并验证已有 XLSX 路径，要求显式工作表。批量压缩包/Salmon 文件导入默认不纳入本次核心验收。
- 整数只是 counts 的必要检查之一，同时核对用户的数据来源与处理阶段声明。TPM、FPKM、log、VST、rlog、Z-score 及单细胞 gene × cell 矩阵不进入普通 Bulk counts 推断。
- 不取整、补零或静默删行来伪造合规输入。重复标识、缺失、非法值、全零样本和不一致样本给出具体位置、原因及修复建议。
- 上游质量报告作为用户提供材料关联；Q30、比对率、接头污染等不得从表达矩阵凭空生成，报告标明来源。

### 5.2 主引擎和数据对象

保留 **PyDESeq2 0.5.4 + 现有 SciPy ORA + GSEApy 1.3.1**。R DESeq2 用于独立数值验证，不新建重复的生产引擎。采用现有 React/TypeScript、FastAPI、PostgreSQL、Celery/RabbitMQ、受管文件和结果版本机制。

分别保存原始 counts、样本/基因轴、过滤规则与 mask、过滤后 counts、size factors、normalized counts、VST、模型设计、完整比较表和诊断。Bulk 交付 B03 已验收的版本化 NPZ+JSON 分析对象、固定 NPY 矩阵成员和方法及环境记录。对象恢复能力以已验证的匹配版本环境为准，读取器禁用 pickle。

标准化默认 median-of-ratios；需要 poscounts 时显式选择、确认和记录，不静默换方法。QC 的 VST 用于展示，不回灌原始 counts 检验；VST 不是批次校正。低表达过滤根据纳入样本和最小比较组的生物学重复数制定可配置规则，确认前冻结，记录逐基因原因。

PCA 和样本关系分析使用预先声明的合格/高变基因集合，不使用显著 DEG 来证明分组质量。保存变换、缩放、基因选择、样本距离/相关性算法及解释方差。

### 5.3 模型、比较和诊断

支持独立两组、简单配对、多组指定比较及设计允许的加性协变量模型，例如 `~ condition`、`~ donor + condition`、`~ batch + condition` 和可估计的组合。字段类型、参考水平、编码和公式由结构化合同生成；不接受任意执行脚本。

检查矩阵秩、自由度、真实独立单位、完整配对、协变量缺失、组别与批次混杂。疑似异常样本不能仅因不与同组聚集而自动删除；改变纳入样本必须提供理由并确认。

正式差异前确认：输入版本、纳入/排除样本、过滤、归一化方法、模型因素、设计矩阵含义、A vs B 方向、比较族和重要警告。科学参数变化使确认失效，复用现有后台版本机制，不让客户手动填写 UUID 或哈希。

保存 baseMean、MLE log2FC、标准误、Wald、P、原生 padj、平台比较内/比较族 q、基因注释、tested/test_status 和原因。记录拟合方式、收敛、Cook 过滤、独立过滤和所有 NA 原因；诊断无法可靠区分时如实写组合原因，不伪造精确分类。

首版默认不启用 LFC shrinkage 和异常计数替换，保留当前方法边界；若另行纳入 shrink，则保存 MLE 与收缩结果，并验证支持的系数/contrast 类型。不能把任意线性组合 contrast 当成可直接收缩的系数。

### 5.4 显著性、Top N 与功能分析

- 保留现有 `q_within_contrast`、`q_global_family` 与原生 `original_method_adjustment`，分别说明检验族与过滤方法。默认建议使用比较内 q；筛选、图、ORA 和报告必须选用同一明确口径，不能笼统全部称为 DESeq2 padj。
- 默认筛选建议 q ≤ 0.05 且 |MLE log2FC| ≥ 1，可配置；这是统计结果后的筛选，不冒充以效应量阈值为原假设的检验。
- 全量受检表、显著 DEG、上调/下调集合、展示 Top N 分开保存。默认 DEG Top N 按所选 q 升序、绝对效应降序及稳定 ID 排序；高变基因按展示层方差排序；富集按所选调整指标与稳定 term ID 排序。不足 N 就展示实际数量。
- ORA 默认从本次预先定义的受检基因构建背景，经同一明确映射进入资源；记录与数据库交集、映射率和背景规模。上调/下调可分开处理，不默认全基因组背景。
- GSEA 默认用完整有效、有方向的 Wald 排名；记录 NA、重复/歧义映射、并列值、seed、置换和资源版本。无 DEG 不阻断合格 GSEA，禁止用 Top20/Top100 替代完整排名。
- 区分 ORA 的 BH 与现有 GSEA 联合置换零分布 FDR。不同统计方法的 q 不应强制数值相等。

### 5.5 工作流、失效和交付

界面采用研究设计、数据与样本、质控、差异分析、功能分析、报告与下载六个可切换视图，复用已有草稿、路由和自动保存。一次模型确认足以覆盖对应科学方案，不新增无意义的逐步确认。

状态明确区分 queued/running/waiting_confirmation、成功、失败、取消、跳过、不适用和依赖阻塞。运行成功但无显著结果仍是合法结果；空前景造成 ORA 不适用时写明原因，不当作已经执行了有效富集。历史版本完整性与当前流程是否过期分别显示。

改变输入、样本纳入、模型或方法后，仅使受影响下游过期，原结果保持可读。修改筛选、Top N、配色和尺寸复用已保存统计；若变更参数影响原生 independent filtering 或模型拟合，则按科学变化处理，不能当成纯显示修改。

Word 汇总样本/QC、设计、A vs B、完整结果概况、图表、富集/GSEA、资源、方法与局限；报告表格可以摘要展示，完整表另行下载。交付包括对象、参数、日志、软件/资源版本、输入清单、复现脚本与环境说明。PDF 输入和历史文件保留，不新增 PDF 生成要求。

大模型只辅助解释和撰写，确定性报告可独立交付；统计数值、图件与完成状态取自真实程序。模型使用沿用现有授权，下载仅复用与事实摘要绑定的缓存，不临时调用外部模型或使用写死结论。

## 6. 18 项能力覆盖矩阵

资源类型：**本地**为用户文件或保存结果，**部署准备**为软件/参考快照，**已有服务**为项目现有内部能力。核心链路不新增运行时远端生信 API。

| 编号 | 环节、现有依据与缺口 | 输入 → 输出；工具与资源 | 人工确认及验收；主批次 |
|---|---|---|---|
| C01 | 研究问题与实验设计；E03，需统一对应关系 | 问题/分组/供者/批次 → 结构化设计与指定比较；既有研究设计服务，本地/已有服务 | 确认真实重复及方向，不自动全两两比较；2、4 |
| C02 | 读取与完整性；E01/E02，需容量和定位错误 | counts/样本表 → 原始对象、映射与检查报告；现有解析器，本地 | 确认轴/对应；拒绝不适用输入且原件不变；1、2 |
| C03 | 基因标识与注释；E07，需部署可用资源 | 物种/原始 ID/参考版本 → 注释、映射和未映射表；本地版本快照，部署准备 | 明确物种及版本；后缀/冲突不静默合并；2、6 |
| C04 | 分析对象和留存；E04/E05，需完整对象交付 | 原始数据/配方 → counts、normalized、VST、模型；NPZ/JSON/NPY，本地 | 轴、含义、SHA 一致，对象往返可核对；3、4、7 |
| C05 | 样本 QC 与低表达过滤；E04，需 Bulk 指标 | counts/设计 → library size、检测基因、分布、过滤原因；现有数值库，本地 | 用户决定样本排除；过滤数量和原因完整；3 |
| C06 | 标准化与展示转换；E04/E05，需统一层 | counts → size factors、normalized、VST；PyDESeq2，部署准备/本地 | 展示数据不作为 counts 模型输入；3、4 |
| C07 | 样本关系探索；E04，需相关性和注释 | 展示层 → PCA/方差/距离/聚类/热图；NumPy/SciPy/Matplotlib，本地 | 不用 DEG 选择证明样本质量，不自动删异常样本；3、5 |
| C08 | 批次、混杂与模型；E03/E06，需组合模型 | 样本/协变量 → 编码、秩、自由度和阻断原因；设计检查与主引擎，本地 | 满秩且可估计；混杂不靠删项掩盖；4 |
| C09 | 关键方案确认；E06，需先展示后确认 | QC/样本/参数/方向 → 确认记录；现有计划版本，已有服务 | 确认绑定输入和科学参数，变更后失效；4、7 |
| C10 | 差异表达；E05，需统一多组模型 | 确认对象/contrasts → 完整统计与状态；PyDESeq2，部署准备/本地 | 独立/配对/多组/协变量真实运行；方向与参考核对；4、8 |
| C11 | 拟合诊断与异常；E05，需完善原因和展示 | 模型 → warnings/Cook/收敛/NA 原因；主引擎，本地 | 不可估计时阻断，未检验/NA 可解释；4 |
| C12 | DEG 筛选与排序；E05/E08，需口径统一 | 完整表/阈值 → 全量/显著/上调/下调集合；已有候选服务，本地 | 无 DEG 不放宽阈值；口径明确可回查；5 |
| C13 | 图与 Top100/20；E08，需 MA/QC 重绘 | 保存表与展示层 → 火山/MA/热图/表达/数量图；已有绘图，本地 | 排序和不足 N 明确；纯样式不重新拟合；5 |
| C14 | ORA；E07，需合法默认资源闭环 | 前景/受检背景/映射 → ORA 表、图与审计；SciPy 超几何/BH，部署准备 | 明确背景/方向/映射率；空前景不是任务故障；6、8 |
| C15 | GSEA；E07，需 Bulk 完整链验收 | 全部有效排名/基因集 → ES/NES/FDR/leading edge/曲线；GSEApy，部署准备 | 非 Top N 输入，无 DEG 可继续；6、8 |
| C16 | 多比较与候选查询；E05/E08，需统一视图 | 固定比较/基因查询 → 查询与汇总；现有候选/分页，本地 | 不混淆方向、q 口径或同名映射；5、7 |
| C17 | 稳健性和材料关联；E10/E11，需 Bulk 承接 | 确认的参数/样本变体及材料 → 结果对照/证据；既有运行与关联，本地/已有服务 | 不覆盖基线；预测、独立分析和实验验证分别标注；7、8 |
| C18 | 结果与报告；E11，需 Bulk 事实层和聚合 | 全流程事实/图/版本 → Word、数据、对象、脚本和日志包；现有报告/下载，已有服务 | 数值、方向、资源和状态一致，未执行不写成功；7、8 |

## 7. 工具、资源和版本准备

以下官方来源在 2026-11-09 规划审查时查阅。页面版本是当时可取得的内容，不将其等同为生产环境已安装或已验证版本。

| 工具/资源 | 选型、许可及准备方式 |
|---|---|
| PyDESeq2 | 保留锁定 0.5.4，MIT，Python 3.11 科学环境。[官方包页](https://pypi.org/project/pydeseq2/0.5.4/)、[0.5.4 API](https://pydeseq2.readthedocs.io/en/v0.5.4/api/docstrings/pydeseq2.dds.DeseqDataSet.html)。独立实现与 R 可存在数值差异，不承诺逐位一致。 |
| GSEApy | 保留锁定 1.3.1，BSD-3-Clause。[官方包页](https://pypi.org/project/gseapy/1.3.1/)。使用本地基因集与既有固定算法，不因新版可用而顺带升级或引入 Enrichr/Biomart 运行时调用。 |
| NumPy/SciPy/Pandas/AnnData/Matplotlib | 沿用 [requirements-bio-insights.in](../../../backend/requirements-bio-insights.in) 与对应 hash 锁文件；新增使用方式、传递依赖和分发声明逐项核对。 |
| R DESeq2 参考环境 | [官方页](https://bioconductor.org/packages/release/bioc/html/DESeq2.html)当时显示 1.52.0、LGPL≥3；[发布表](https://bioconductor.org/about/release-announcements/)对应页面 BioC 3.23/R 4.6。验证环境独立固定，不能把该组合直接混入仓库 R 4.4 单细胞环境。构建可用性本轮未验。 |
| Reactome | 首条完整离线 ORA/GSEA 链候选；[官方许可](https://reactome.org/license)将数据库及衍生数据列为 CC0，图形素材另有条款。固定物种、release、ID 与推断/人工整理来源，不把非人类推断当人工验证。 |
| GO | 复用 OBO/GAF 导入；[官方许可](https://geneontology.org/page/use-and-license)为 CC BY 4.0。固定 ontology、annotation、传播关系、NOT/obsolete/root 排除及归属信息。 |
| 基因注释/映射 | 首批准备人/鼠适用快照；其他物种必须匹配资源。核对 [Ensembl 使用条件](https://useast.ensembl.org/info/about/legal/disclaimer.html)，自产数据和第三方材料条件分别处理。 |
| KEGG/MSigDB/GENCODE 等 | 不把包装软件许可当成数据库许可；按实际资源集合及来源条款核验，不默认全库可商用或自动启用。缺少许可依据时使用已核验的本地替代资源。 |

资源清单至少包括：来源 URL、release、取得日期、物种/assembly、namespace、许可与引用、SHA、转换脚本/参数、映射覆盖率及适用限制。先检查是否已有正确且可用的资源，避免整批重新下载。更新资源生成新版本，不覆盖历史分析使用的快照。

## 8. 八批实施与验收计划

每批按“明确差异和验收用例 → 实现 → 定向验证 → 更新事实记录 → 用户验收”推进；状态分别记录代码、真实工具、真实数据和用户接受。批次之间可复用正确成果，不重复生成已正确的整批输出。

| 批次 | 名称 | 依赖 | 当前状态 |
|---|---|---|---|
| B01 | 运行环境与容量统一 | 用户已确认 | 已实施，用户验收通过 |
| B02 | 输入模板、样本映射与设计接线 | B01 基础运行可用 | 已实施，PostgreSQL 补测与修复完成，用户验收通过 |
| B03 | Bulk QC、展示转换与分析对象 | B02 合规输入 | 已实施，定向验证完成，用户验收通过 |
| B04 | 模型确认与完整差异表达 | B03 QC/对象 | `user_accepted`（2026-11-10） |
| B05 | 图表、筛选、多比较与候选查询 | B04 固定结果 | `user_accepted`（2026-11-10） |
| B06 | 本地注释与 ORA/GSEA 闭环 | B01 资源、B04 结果 | `user_accepted`（2026-11-10） |
| B07 | 连续流程、稳健性和 Word 交付 | B02—B06 | `user_accepted`（2026-11-11） |
| B08 | 真实数据、独立参考和兼容验收 | B01—B07 | 用户验收通过 `user_accepted`，已停服收尾（2026-11-11） |

### B01. 运行环境与容量统一

**主要位置：**`infra/worker/Dockerfile`、`compose.workers.yml`、`script/dev/worker_stack.py`、`backend/app/domain/bioinformatics/{settings,tabular_contracts,tabular_settings}.py`、`backend/app/domain/bio_insights/settings.py`、`backend/app/adapters/bio_engine/tabular_assays.py`、`backend/app/adapters/bio_insights_engine/{counts_model,quantitative,inputs,tables}.py` 及相关进程传输/结果校验模块。

- [x] 接通 insights 锁文件对应的固定解释器构建、runtime gate 收据挂载和独立 staging；保留现有单细胞 Python/R 环境和依赖身份。
- [x] 统一 L01—L04 的配置入口和执行边界：Bulk 文件 128 MiB、展开 256 MiB、矩阵 500 万单元格、样本列 512；分块/流式读写的完整大样本性能仍待真实运行验证。
- [x] 保留串行 Worker、现有 CPU/内存/超时及取消治理，并把 insights 运行时收据接入同一 Worker 编排。
- [x] 登记本批实现文件和定向测试证据；未下载新增参考资源，未启用新增远端计算。

**交付物：**可安装的固定科学环境、正确挂载与门禁、统一容量策略、资源占用记录和明确的用户错误。

**验收：**本批代码、配置和定向测试已完成，用户已验收通过；真实工具版本/隔离检查、跨越旧门槛的 60,000 × 50 counts 导入/计算/完整导出、时间/RSS/磁盘/取消仍未执行，保留到后续真实运行验收。容量合成案例只证明工程规模，不算真实生物数据验证。

### B02. 输入模板、样本映射与设计接线

**主要位置：**`backend/app/domain/bioinformatics/tabular_contracts.py`、`backend/app/adapters/bio_engine/tabular_assays.py`、`backend/app/domain/research_intake/`、`backend/app/domain/bio_insights/sources.py`、`frontend/src/features/bioinformatics/{TabularImportFields,TabularAnalysisSetup}.tsx`。

- [x] 提供 CSV/TSV counts、sample_metadata 模板、字段说明和明确标为演示的例子；保留受支持的 XLSX 显式工作表导入。
- [x] 实现上传后的矩阵方向、列映射与样本对应确认，关联研究设计，保留来源和原始标识。
- [x] 增强 raw-count 声明与适用性检查，区分单细胞、TPM/FPKM、log/VST/rlog/Z-score 和未知尺度。
- [x] 错误定位到文件/工作表/行列或样本/基因键；重复 ID 和版本后缀冲突不静默聚合。
- [x] 接收用户的上游质量报告并标明来源，不由矩阵重算测序质量指标。

**交付物：**输入模板、说明、预览和可执行样本映射记录。

**B02 实施状态（2026-11-09）：** 已完成 Bulk canonical 样本元数据列映射、样本轴对账和来源审计；质量报告以独立原件角色登记，不参与矩阵重算；前端加入模板下载、演示标识、输入来源声明、512 样本容量提示和研究设计样本覆盖预览；研究设计保存前执行输入样本集合精确对账。补测已找到原项目测试数据库配置并使用真实 PostgreSQL 隔离 schema，修复空设计绕过对账、错误码未公开、失效断言和既有公共错误合同缺口；后端组合 67、数值 60、公共错误合同 17、前端 477 项通过，构建通过。用户已确认 B02 验收通过，状态为 `user_accepted`，详见[B02 实施与验收记录](../阶段04/2026-11-09-Bulk-B02-输入模板样本映射与设计接线-实施与验收记录.md)。记录明确区分真实数据库/本机注入式数值调用与 Docker 端到端验证；真实容器构建、真实用户文件导入、长耗时容量仍未完成。B02 文档收尾完成，等待用户另行确认后进入 B03。

**验收：**合规 counts 接受；样本集合不匹配、重复/缺失/非法值/负值/全零样本等有具体诊断；来源原件保持不变；CSV/TSV/XLSX 分别记录验证结果；格式支持不从其他 assay 推断。

### B03. Bulk QC、展示转换与分析对象

**主要位置：**`backend/app/adapters/bio_engine/tabular_assays.py`、tabular 配方合同与结果校验、`frontend/src/features/bioinformatics/{TabularAnalysisSetup,TabularAnalysisResult,BioFigureDetail}.tsx`。按职责拆出 Bulk QC/对象辅助模块，避免把全部逻辑继续堆入单文件。

- [x] 计算总计数、检测基因数、零比例和表达分布，记录样本/基因过滤规则和原因。
- [x] 分别保存原始/过滤后 counts、normalized counts、VST 和完整轴；提供 NPZ+JSON 版本化分析对象及往返校验。
- [x] 完成 PCA/解释方差、相关性和距离热图、层次聚类、按组别/批次标注；PCA 只使用完整非恒定特征，不使用 DEG 预筛。
- [x] 为疑似异常样本提供检查提示和人工排除入口，不自动按聚类结果删样本；API 有界预览支持四个 B03 处理层。

**交付物：**可审阅 QC、完整展示数据、图数据、NPZ+JSON 分析对象及下一步模型入口。

**B03 实施状态（2026-11-10）：** 已完成 QC 指标和表达分布、显式人工过滤规则、raw/filtered/normalized/VST 层、PCA/解释方差、样本聚类、相关/距离热图、condition/batch 标注、便携式分析对象及异常样本复核入口。B03 数值 66、PostgreSQL foundation 4、API/setup/schema/integration 10、domain/错误合同 23、前端 19 项通过，Python compileall、`git diff --check` 和前端构建通过。随后用公开 `airway` 矩阵完成 64,102 feature × 8 样本的真实导入和完整 B03 计算，API 四层预览和 Edge 结果/PCA/聚类/实验设计页面已验证。既有 Docker 导入队列 1 passed，本轮 Docker B03 分析队列 1 passed（122.08 秒），固定 Linux worker 完成确认、重启恢复、结果发布和逐层读取。详见[B03 实施与验收记录](../阶段04/2026-11-10-Bulk-B03-QC展示转换与分析对象-实施与验收记录.md)。B03 已登记为 `user_accepted`。

**验收：**各层含义和数值不混用；PCA 与保存矩阵/解释方差一致；低样本或恒定基因等不可计算原因明确；对象往返保存与轴/参数核对；没有使用 DEG 预筛 PCA。

### B04. 模型确认与完整差异表达

**主要位置：**`backend/app/domain/bio_insights/{quantitative_contracts,quantitative_design,service}.py`、`backend/app/adapters/bio_insights_engine/{counts_model,quantitative,quantitative_inputs}.py`、`frontend/src/features/bio-insights/QuantitativeComparisonSetup.tsx`、`frontend/src/features/bio-insights/InsightPlanEditor.tsx`、`frontend/src/features/bio-insights/state.ts`、`frontend/src/features/bio-insights/quantitative.ts`。

- [x] 增加结构化分类/连续协变量与可估计的配对＋批次方案，旧合同和历史结果保留原方法。
- [x] 将新 Bulk 方法拆分为同一设计拟合与指定 contrast 提取，支持多组指定比较，避免重复拟合。
- [x] 完成 L05—L09，呈现模型公式、真实独立单位、配对、样本排除、过滤、方向和警告；用户确认后开跑。
- [x] 保存完整检验表、固定模型记录及其设计/样本/计数成员、size factors、原生及平台调整指标、warnings、拟合/异常/NA 状态。
- [x] A vs B/B vs A 的方向、显示、导出及确认失效一致；旧结果不覆盖。

**交付物：**从 QC 到明确模型确认和真实差异表达的业务链。

**验收：**独立、配对、多组指定比较和可估计协变量；小样本警告、单重复/混杂/秩不足阻断；确认后变更被检测；完整数值与独立参考检查。只调整格式/Top N 不重新拟合。若本批参考条件未齐，明确保留到 B08，不先计为真实验证通过。

**B04 已于 2026-11-10 由用户验收通过。** 隔离 PostgreSQL 和固定 Docker worker 已完成 `airway` 的 4 对样本、双向 contrast 计算与发布。Edge 验证独立确认、启动、打开固定结果、全量 TSV 和复现包下载，128,204 行完成方向和校正指标对账。前端回归修复后，426 个文件、3,374 项全量测试通过，构建通过。固定 R 参考已验证独立两组数值，同输入独立 R 全量对照和其他真实设计扩展留 B08。图表样式、Top N 和重绘的专题验收归 B05。详见[B04 实施与验收记录](../阶段04/2026-11-10-Bulk-B04-模型确认与差异表达-实施与验收记录.md)。

### B05. 图表、筛选、多比较与候选查询

**主要位置：**`backend/app/adapters/bio_insights_engine/{figures,quantitative_figures,candidates}.py`、`backend/app/domain/bio_insights/contracts.py`、`frontend/src/features/bio-insights/` 的绘图/候选/结果视图，以及 Bulk QC/PCA 重绘入口。

- [x] 火山图、MA、DEG/高变基因热图、候选表达图和数量汇总均使用保存数值，阈值与当前 q/效应量一致。
- [x] 区分 DEG、上下调、高变基因和富集 Top N，冻结候选范围、排序和不足 N 行为。
- [x] 多比较分别保存、查询和汇总，显示 A vs B 及各比较的统计口径。
- [x] 改色、尺寸和 Top N 复用统计对象，z-score 只改变展示层并记录转换参数。

**交付物：**可查询的比较与候选、可下载/重绘的研究图及完整图数据。

**验收：**每张图与固定表对账；0 DEG、NA、少于 N 的结果正确；重绘不调用 DE；PCA 重绘不重新分解原始矩阵；旧单细胞/空间图不受影响。

**B05 已于 2026-11-10 由用户验收通过。** Edge 实测双向差异查询、完整候选与 Top 20、火山图新旧版本、固定 PCA、实际下载和离线包重绘。其余固定图件完成逐项对账，前端全量 427 个文件、3,384 项通过。测试口径、实际结果和未验证范围见 [B05 实施与验收记录](../阶段04/2026-11-10-Bulk-B05-图表筛选多比较与候选查询-实施与验收记录.md)。

### B06. 本地注释与 ORA/GSEA 闭环

**主要位置：**`backend/app/adapters/bio_insights_engine/{resources,mapping,enrichment}.py`、`backend/app/domain/bio_insights/` 资源及设计服务、`frontend/src/features/bio-insights/EnrichmentSetup.tsx` 和结果视图。

- [x] 登记固定 Reactome v98、人类 GO OBO/GAF 和显式 ID 映射，使用本地资源执行富集。
- [x] 提供物种下拉框，显示物种、namespace 与参考兼容性，保留原始 ID、歧义和未映射审计。
- [x] 将真实 Bulk 完整结果接入 ORA/GSEA，固定背景、方向、统计口径、完整排名和资源版本。
- [x] 区分无显著富集、空前景、映射不足和资源缺失或不适用，QC/DE 保持各自的独立准入。

**交付物：**本地资源登记、实际富集表、leading edge、曲线、图和方法说明。

**验收：**断网运行核心富集；真实 Bulk 全结果进入功能分析；无 DEG 可 GSEA；受检背景/映射/多重检验正确；ORA 与独立公式/实现核对，GSEA ES/方向/leading edge 核对。不同零分布与校正方法不能简单用 q 数值相等验收。

**B06 已于 2026-11-10 由用户验收通过。** Edge 从 B04 固定结果完成物种选择、兼容性预检、Reactome ORA/GSEA、空前景、图件发布和实际下载。独立核对 1,323 条上调 ORA 检验和 1,313 条 GSEA 的 ES 与 leading edge，GO 和 ID 映射完成实际导入。具体证据与边界见 [B06 实施与验收记录](../阶段04/2026-11-10-Bulk-B06-本地注释与ORA-GSEA-实施与验收记录.md)。

### B07. 连续流程、稳健性和 Word 交付

**主要位置：**现有项目/生信工作区与任务导航、`backend/app/domain/bioinformatics/analysis_service.py`、`backend/app/domain/bio_insights/service.py`、`backend/app/domain/research_results/`、`backend/app/adapters/{research_report_docx,single_cell_insight_report,bio_reader_narrative}.py`、`backend/app/domain/bio_insights/reproducibility.py`。

- [x] 连接六个主视图、草稿恢复、排队/日志/错误/重试/取消和结果下载；改动影响的结果过期但历史可读。
- [x] 支持经确认的参数敏感性和样本处理前后结果对照，关联独立分析及实验材料，不把计算支持写成实验验证。
- [x] 增加 Bulk 专用事实投影与整合 Word，包含 QC、设计、比较、图、富集、方法、来源与局限；复用确定性导出，不重建 Word 平台。
- [x] 保留基因、比较、样本和物种语义；模型叙述缓存绑定事实摘要，缺缓存使用真实确定性内容，不写死科学结论。
- [x] 交付完整/筛选数据、对象、软件/资源版本、日志、参数、复现脚本和匹配环境说明。

**交付物：**从材料到 Word/完整包的连贯客户流程及运维说明。

**验收：**权限隔离、未知提交回查、失败/重试/取消、过期/复用和下载；报告无单细胞错标题及错误成功状态；基因、A vs B、数值/阈值/图源一致；实际 Word 版面核查；复现包在匹配环境执行一次必要复算，不重复正确整批结果。

**B07 已于 2026-11-11 由用户验收通过。** 复用公开 `airway` 固定结果，从 Edge 验证六个视图、草稿恢复、样本 8 → 6 的固定对照和实际下载。Microsoft Word 16.0 实际分页 13 页。完整包校验通过，在匹配环境离线复算 1,323 条 Reactome ORA。详见 [B07 实施与验收记录](../阶段04/2026-11-10-Bulk-B07-连续流程稳健性与Word实施与验收记录.md)。

### B08. 真实数据、独立参考和兼容验收

**主要位置：**扩展现有 `backend/tests/{domain,api,numeric,integration}/`、受影响前端 Vitest 用例及 `script/` 验收工具；新增证据记录落在 `docs/开发记录/阶段04/`，运行产物使用既有受管目录，不把客户数据入 Git。

+ [x] 准备并核验下节明确来源和许可的真实 gene counts；冻结原件、转换脚本、样本设计和参考资源。
+ [x] 同一输入在平台与独立 R DESeq2 分别运行，核对全量结果、size factors、设计、NA/异常和方向；不使用平台生成结果作为参考答案。
+ [x] 执行核心完整链及错误/空结果/依赖阻塞测试，运行受影响的单细胞、空间及通用定量回归。
+ [x] 记录真实环境、数据、命令、SHA、完整结果差异、性能、失败与保留限制；提交明确的用户验收路径。

**交付物：**可复现的真实数据证据、独立数值核对、兼容结果、用户验收材料与支持范围。

**验收：**单元、mock、真实工具、真实数据 E2E、独立数值和用户接受分别登记；不以接口成功/图存在/历史报告判定整条通路通过。生产部署不在该验收中自动完成。B08 已于 2026-11-11 由用户验收通过，相关服务已关闭；工程与真实数据证据、跨引擎数值超差和资源范围完整保留。

## 9. 真实材料和验收矩阵

### 9.1 真实数据准备

| 数据 | 官方事实与用途 | 限制与准备规则 |
|---|---|---|
| [airway](https://bioconductor.org/packages/release/data/experiment/html/airway.html) | 人类原代气道平滑肌细胞，4 个供者来源细胞系各 untreated/Dex，共 8 样本，用于配对及完整人类下游链。[官方说明](https://bioconductor.org/packages/release/data/experiment/vignettes/airway/inst/doc/airway.html) | 取 gene read-count `airway` 对象，不误取 Salmon/tximeta 对象；保留 cell 配对。官方包许可 LGPL，注释参考历史 GRCh37/Ensembl75；不能无说明换成现代 GRCh38。 |
| [pasilla](https://bioconductor.org/packages/release/data/experiment/html/pasilla.html) | 果蝇细胞，3 treated 与 4 untreated 生物学重复，gene counts 可检验独立两组及真实测序类型协变量。[构建说明](https://bioconductor.org/packages/release/data/experiment/vignettes/pasilla/inst/doc/create_objects.html) | 取 gene counts，不能使用 exon 表替代；single/paired-end 是测序类型，不是供者配对或虚构批次。包许可 LGPL；样本名按真实映射对齐。 |
| [fission](https://bioconductor.org/packages/release/data/experiment/html/fission.html) | 裂殖酵母 2 strains × 6 时间点 × 3 生物学重复，共 36 样本；作者提供 gene read counts，可选固定 strain 的 3 时间点做指定比较。[构建说明](https://bioconductor.org/packages/3.23/data/experiment/vignettes/fission/inst/doc/fission.html) | 包许可 LGPL；不使用 GEO RPKM 替代 counts。保留 replicate，跨时间是否同培养系列须核实；必要时用 `~ replicate + minute` 的阻断设计，不能宣称 9 个样本已证明完全独立。 |

优先复用仍存在且身份正确的既有材料。数据与依赖下载在实施授权后进行；本轮没有取得新数据。上述真实数据用于不同验收目的，不将同源不同表示当成独立验证队列。

### 9.2 验收用例

| 用例 | 预期与证据类型 |
|---|---|
| 两组独立、简单配对、多组指定 contrasts、可估计协变量 | 真实工具运行及合格真实数据参考比较；每例记录真实独立单位和方向 |
| A vs B / B vs A | 对应方向正确；对称设定下效应方向与统计量核对，容差按方法冻结，不能只看图标题 |
| 完全混杂、秩不足、自由度不足、单重复、不完整配对 | 在正式推断前阻断；错误指出具体因素和材料需求 |
| 2 生物重复/2 配对 | 仅可估计时允许并提示小样本限制；不称为功效充分 |
| TPM/FPKM/log/VST、单细胞 counts、来源不明表 | 不进入普通 Bulk raw-count 引擎；错误说明所需材料 |
| 样本不一致、重复 ID、缺失/负值、非有限值、全零样本 | 定位问题，不静默取整/补零/删行 |
| 无显著 DEG、无显著富集 | 合法空结果；不改阈值制造结论；合格 GSEA 仍可执行 |
| 注释不足/资源缺失/物种不匹配 | 精确记录映射和阻塞范围，QC/DE 不因可选富集资源缺失而失效 |
| 未配置新增外部服务或运行时断网 | 已准备依赖/资源的核心下游链可完成，无隐式联网查询 |
| 大矩阵与输出容量 | 超过旧限制的完整输入/计算/导出；内存/时间/磁盘/取消有实际测量 |
| 失败/重试/取消/未知提交、权限与数据隔离 | 用实际任务状态/接口验证，不仅 mock；旧结果不覆盖、不越权下载 |
| 样式/Top N 修改、输入/模型变更 | 前者复用统计，后者相关确认和下游适用性失效；旧版本仍可读 |
| Word、对象、数据及复现脚本 | 实际文件内容和版面核对；完整表/NA/状态一致；匹配环境必要复算 |
| 单细胞/空间/通用定量回归 | 按实际共享修改选择现有测试和代表链，保留历史输入/草稿/结果/下载 |

独立参考从同一冻结 counts 重建 R DESeq2 对象，显式对齐过滤、size-factor 方法、设计、contrast、异常值替换/Cook、independent filtering、alpha 和 shrink 开关。逐基因核对全量结果，不仅核对显著集合。

数值容差需在观察新结果前登记并由方法依据决定：整数、轴、模型设计与方向严格比较；浮点按 size factors、LFC/Wald、概率/下溢分别处理。沿用已有固定 R 基准的数值门槛时，只对其原适用范围使用。真实数据超差先调查并记录，不事后任意放宽为通过。

## 10. 风险、依赖与完成定义

主要风险是容量放宽后的峰值内存和多次加载、研究设计与样本表双重来源、旧合同兼容、小样本/复杂设计的可估计性、参考版本与物种不匹配、报告的事实丢失/缓存失配，以及代码门禁与实际运行环境脱节。分别由 B01、B02/B04、B04/B08、B06、B07 和 B01/B08 收口。

科学状态不能由勾选确认代替：样本表和用户声明支持设计检查，但不是对真实生物学独立性或实验真实性的自动证明。独立计算复核、独立队列证据、实验验证和生产质量是不同层级。

| 完成层级 | 判定条件 |
|---|---|
| 代码完成 | C01—C18 有实现与对应测试；没有模拟成功路径；共享模块兼容通过 |
| 真实计算可用 | 当前固定环境/资源通过工具和隔离门禁，核心流程无需新增外部生信服务实际运行 |
| 真实数据验证通过 | 合格真实输入全链、独立数值参考、实际图表/Word/复现核对完成，限制和差异留有证据 |
| 用户验收通过 | 用户按代表流程检查后明确接受，记录接受范围，不自动扩大到未验物种/规模 |
| 可交付运营 | 支持范围、资源准备、部署差异、容量、恢复和运维说明齐全；生产部署另行确认 |

仅在相关验收完成后，才能表述：“已完成从表达矩阵开始的 Bulk RNA-seq 下游分析；原始测序数据处理和需要新增外接服务的能力暂未纳入本次实现。”

## 11. 批次记录规则与本轮登记

每批实施记录应追加：用户授权范围、实际分支/基线、改动文件、输入/参数/资源身份、执行命令、通过/失败/跳过/未执行、复用的正确证据、真实数值和图件核查、未验证边界及用户接受状态。计划内容改变时先说明影响，不用完成记录倒改过去的事实。

2026-11-09 实施阶段记录（历史状态）：从 `b520f77` 在现有隔离 worktree 创建 `feat/bulk-rna-downstream`；编写本总领方案并加入文档导航；确认 A vs B 已归入差异比较方向。经用户确认后完整实施 B01：集中 Bulk 容量边界、放宽旧 tabular 门槛至 128 MiB 文件/256 MiB 展开/500 万单元格预算，统一样本列上限至 512，并接入 bio-insights 固定解释器的 Docker 构建、运行时收据和独立 staging 挂载；完成定向测试和静态检查后由用户验收通过。随后按用户确认完整实施 B02：增加 CSV/TSV/演示模板、Bulk canonical 样本元数据映射、样本轴和设计样本集对账、来源坐标诊断、raw-count 输入来源声明及上游质量报告登记，并保留 XLSX 显式工作表导入；定向测试和前端构建通过，当时等待用户验收。未提交、推送、部署，也未执行真实容器构建、真实用户文件导入或 60,000 × 50 实际分析。

2026-11-09 补充验证与修复（历史状态）：用户先表示接受 B02，随后要求完成已有本机测试数据库的查找与测试后重新交付，并授权修复发现的问题。确认原项目测试数据库及配置一直存在，之前的 fixture 阻断源于 worktree 未继承 ignored 配置；仅对子进程加载两个测试数据库变量，完成真实 PostgreSQL 迁移/存储/任务链。修复设计空样本集合、公共错误码与双语消息、过时数据库断言、错误发出器误分类及非法映射测试；注入式数值测试绘图后端与 worker 统一为 Agg。最终定向测试合计 621 passed（67 + 60 + 17 + 477），前端构建通过。早期两例间歇数值失败及原始完整异常栈未留存的限制已记入 B02，不倒写为从未失败。当时待用户重新验收；B01 验收状态保持，B03—B08 未启动，未提交、推送或部署。

2026-11-09 B02 用户验收与文档收尾：用户明确确认“B02 我已验收，通过，更新相关文档和验收记录，等我确认后再进入 B03。”现登记 B02 为 `user_accepted`，同步本总领方案、B01/B02 验收记录和文档导航。沿用已记录的 621 项测试及构建证据，本次仅核对并更新文档，没有重跑测试或计算；现有代码、数据和运行证据保留，未验证事项不扩大为通过。B02 已收尾，等待用户另行确认后进入 B03；未提交、推送或部署。

2026-11-10 B03 实施与定向验证：用户确认开始 B03 后，在同一分支完成 QC 指标、显式人工过滤规则、raw/filtered/normalized/VST 层、PCA/解释方差、样本聚类、相关/距离热图、组别/批次标注、便携式 `NPZ + JSON` 分析对象和异常样本人工复核入口。完成数值、PostgreSQL foundation、API/setup/schema/integration、domain/错误合同、前端定向测试，Python `compileall`、前端构建和 `git diff --check` 通过；结果层预览、对象轴和前端异常提示兼容问题已修复并复验。B03 当前等待用户验收，B04 未启动；未提交、推送或部署。

2026-11-10 B03 补充真实数据、Docker 与 Edge 验证：复用 Bioconductor `airway` 公开 counts/metadata CSV，保存适配文件、SHA256、来源地址和隔离 schema 收据。真实 PostgreSQL 隔离库完成 64,102 feature × 8 样本导入、B03 parser/计算和固定结果读取，API health、四层矩阵预览和图件成员核对通过。Edge 浏览器验证 QC 对账、四层语义、分析对象往返、PCA、样本聚类、人工排除输入入口和实验设计集合一致。既有 `test_bio_import_queue.py` 通过 1 项，本轮 Docker B03 分析队列通过 1 项（122.08 秒），覆盖 worker 重启、任务确认、结果发布和四层读取。B03 等待用户验收期间用户已确认通过，现登记为 `user_accepted`；未提交、推送、部署或启动 B04。

2026-11-10 B03 用户验收收尾：用户明确“B03我已验收，通过，更新相关文档和验收记录，等我确认后再进入B04”。本次仅更新 B03 验收记录、总领方案和文档导航，保留现有代码、结果、测试数据、运行收据与未验证边界；B04 等待用户另行确认。

2026-11-10 B04 实施与工程验证。经用户确认实施 B04，完成 raw counts 模型预检、独立确认、一次拟合多个 contrast、固定结果与诊断发布。复用 `airway` 公开数据，在隔离 PostgreSQL、Docker worker 和 Edge 完成真实配对统计、128,204 行双向对账及下载校验。交付工程验证记录时，B04 等待用户验收。

2026-11-10 B04 用户验收与文档收尾。前端回归修复后，426 个文件、3,374 项全量测试通过，构建通过。用户确认 B04 验收通过，登记为 `user_accepted`。本次核对并同步文档、验收证据与待验证事项，B05 等待用户另行确认。

2026-11-10 B05 实施与工程验证。用户确认启动 B05 后，复用 B04 固定差异表和 B03 固定 QC/PCA，完成多比较查询、完整候选与独立 Top N、固定图件发布和样式新版本。Edge 在公开 `airway` 上核对实际任务、候选表、图件、下载和重绘，下载复现包通过离线重绘比对。交付工程验证记录时，B05 等待用户验收。

2026-11-10 B05 用户验收与文档收尾。用户确认 B05 验收通过，登记为 `user_accepted`。本次沿用工程验证证据，同步验收记录和文档索引。真实用户数据、大矩阵容量与性能、独立 R DESeq2 全量对照仍待验证。B06 待用户另行确认后启动。

2026-11-10 B06 实施与工程验证。用户确认启动 B06，并要求物种使用选项框。复用公开 `airway` 固定差异结果和已有 Reactome 快照，登记人类 GO 与 ID 映射。实际队列、Edge、断网计算、结果下载及独立数值核对完成。交付工程验证记录时，B06 等待用户验收。

2026-11-10 B06 用户验收与文档收尾。用户确认 B06 验收通过，登记为 `user_accepted`。沿用既有工程验证证据，同步验收记录和文档索引。其他物种、真实用户数据、GO GSEA、60,000 × 50 矩阵容量与性能以及独立 R DESeq2 全量对照仍待验证。B07 待用户另行确认后启动。

2026-11-11 B07 用户验收与停服收尾。用户确认通过，登记为 `user_accepted`。关闭 B07 专用前端、API 和隔离验收栈，核对 Word 和复现包 SHA-256，沿用既有工程验证及其边界。B08 待用户另行确认启动。

2026-11-11 B08 实施、补充修复与验证（验收前历史记录）。用户确认启动并授权必要修改、核查及开源扩展获取后，完成公开 airway/pasilla/fission 的冻结输入和独立 R 逐基因对照、60,000 × 50 容量与取消、交付下载及匹配环境复算，具体证据和跨引擎超差见 [B08 验收记录](../阶段04/2026-11-11-Bulk-B08-真实数据独立参考与兼容验收记录.md)。补建 Propeller/Topics R 镜像并修复缺失 DelayedMatrixStats，原工具对照 12 项和环境隔离测试 4 项通过；原始准入收据、本机准入与四种方法 Worker 实际环境身份一致。原 Bulk 栈有效收据及固定结果保留，当时恢复验收 API/前端并等待用户验收。数值超差、CellChat 演示资源范围和未扩大的生物学证据明确保留。未提交、推送或生产部署。

2026-11-11 B08 用户验收与停服收尾。用户明确“我已验收，通过，关闭相关服务后，更新相关文档，之后再告诉你下一步”。登记 B08 为 `user_accepted`，同步总领方案、文档导航和 B08 验收记录。停止本批本机前端、API 及 5 个隔离验收容器，确认 5178、8010、8008 和此前容量栈 8009 均不再监听；共享 PostgreSQL 和 Docker 构建服务保持原状。191 个已有非文档修改文件保持原字节，Word/复现包及运行收据核对保留，镜像、卷、测试 schema 和运行目录未删除。停服与验收回执为 `script/.runtime/bulk-b08-validation/user-acceptance.json`。本次仅执行停服、保留核查和文档更新，没有重跑测试或计算、提交、推送、部署或开展后续实施，等待用户下一步指示。

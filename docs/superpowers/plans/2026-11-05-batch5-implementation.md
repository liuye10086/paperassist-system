# 第5批：组成、供者比较和富集实施计划

> For agentic workers: 按 subagent-driven-development / executing-plans 执行，用户已批准本批及顺序；不再重复确认或提交代码。本文复用总领及七批计划，作为本批分工和进度记录。

**Goal:** 将已处理单细胞结果及固定人工标签接入供者级组成、真实propeller、同类型pseudobulk/PyDESeq2与ORA/GSEA，并用真实供者设计公开矩阵完成工程验收。

**Architecture:** 复用现有bio-insights来源、comparison任务、预检、异步执行、结果成员、绘图与Word。组成配置作为既有comparison配置分派的一种分析方法，不新增逐步审批/对象版本体系。原始counts用于供者DE；标签只决定选择与分组，不修改基础表达。

**Tech Stack:** FastAPI/PostgreSQL/React、既有隔离Python数值引擎、R4.4.3/rpy2/speckle、PyDESeq2 0.5.4、GSEApy 1.3.1、python-docx。

## Global Constraints

- 仅第5批获授权；完成后启动本批服务供用户验收，用户通过后才停服务并等下一批指示。
- 沿用`feat/single-cell-cloud-workflow`和已有未提交成果；不新建分支/工作树，不提交、推送、合并或部署。
- 保留所有输入、结果、运行材料、容器/镜像/卷；测试仅使用隔离schema和专用验证容器，禁止操作其他项目服务。
- 阿里云真实FASTQ待账号，不调用云、付费或模型API。可下载公开、来源及使用条件可核实的数据/依赖。
- 只生成Word，排版检查也不生成PDF。
- 复用现有框架，不添加额外审批、通用版本管理或无关防御性框架；实际科学/来源一致性和有意义的失败路径必须核对。
- 技术文库合并不增加独立供者数。非配对每组至少3名供者、配对至少3个完整供者对是工程下限，不能作为统计功效保证。
- 缺少供者/重复/设计时只做描述；不伪造P值、富集或候选身份确认。unknown/uncertain应保留在明确的计数分母中。
- 基础single-cell上限20k cells/100k features/10m nnz，单线程，R类任务RSS4GiB/AS5GiB；不因本批默认扩大资源或配额。科学探针必须真实通过，不注入available回执。
- Docker资源有限，较重科学计算及镜像运行串行协调；轻量前后端测试可独立执行。

## 已确定的实现取舍

现有`ComparisonConfig`与`comparison.py`已经实现原counts按供者/条件聚合及PyDESeq2，`enrichment.py`已有受检背景ORA和真实GSEA。因此沿用这些路径，补缺口与单细胞标签选择，而非复制统计实现。组成采用已有comparison配置分派方式，使用独立schema标识只作兼容合同，不增加用户可见的版本管理流程。

首期组成针对一个已合并多样本/文库的固定单细胞processed结果及一个匹配的人工annotation；可以覆盖多个donor/condition。以全部选定条件内保留细胞为分母，每个细胞最多分配一次；未标记、unknown、uncertain或冲突单独计数，不静默丢弃。自动候选不能自动当作研究者确认标签。人工标签是否确认、选择哪些标签及其依据均记录。

组成默认可描述；推断需要明确两组、独立性依据和供者映射。按donor×condition汇总，多个技术sample合并不增加n。配对模型保留donor项；非配对可加入真实batch项，缺失、完全混杂、秩不足或无残差自由度阻断推断。无可检验变异返回明确not_computable，不制造显著性。

同类型DE使用明确标签/cluster和condition交集，服务端重新验证选择属于固定标签/保留细胞；引用annotation作为来源使标签变化正常使依赖过期。pseudobulk保存细胞成员、聚合整数counts、实际供者数、模型/方向和受检特征全集。技术batch不参与模型时，多技术batch不能被误作独立重复；batch参与模型时必须可表示且不混杂。

ORA/GSEA选择上述实际DE结果和明确物种/namespace的固定基因集，背景为实际受检集合；没有显著项允许空结果。结果、图、Word均来自保存数值，缺失/未执行如实显示。

## 分工及接口

### 1. 数据和官方方法依据

- [x] 核实有真实donor/condition/celltype/原counts的公开矩阵及使用条件；候选Kang18_8vs8，8名供者ctrl/stim配对。
- [x] 大数据可确定性抽取有界真实细胞子集并完整记录选择、原始身份及影响，不能把拆分同供者当独立重复。
- [x] 核实Reactome等许可明确的基因集及稳定ID匹配；记录下载SHA和来源，不反推未知metadata。

报告：`2026-11-05-batch5-data-report.md`。数据仅位于`script/.runtime/single-cell-batch5/`，不运行重科学计算。

### 2. 组成/DE后端与数值路径

负责：`domain/bio_insights/`、`adapters/bio_insights_engine/`、相关service/source/输出校验与tests。不修改R桥接、Docker、前端和Word报告文件。

- [x] 先写有意义失败测试：unknown分母、技术样本合并、不足重复、配对/批次混杂、来源错配、标签过期、原counts聚合、正确受检背景。
- [x] 在既有comparison配置分派增加组成合同（建议schema_version=5），保持kind/task/storage框架；配置/预检/transport/执行/结果发布全链可用，description和inference分开。
- [x] 新增小而明确的`single_cell_composition_contracts.py`、`single_cell_composition.py`等；R原生执行由下述propeller桥接提供。生成组成分子/分母表、供者单位/模型表、真实比较结果、PNG及方法来源。保留不确定状态。
- [x] 修正既有供者DE在单细胞规模下按cell×gene稠密估计而误阻断的实际问题：依据稀疏加载和供者聚合稠密块估算，不抬高全局上限；不按细胞密集展开。
- [x] 补同类型选择字段与服务端标签成员约束，复用原PyDESeq2及富集，不改变旧空间请求语义。
- [x] 核验normal runtime_identity与隔离路径；新模块须隔离前导入，用户数据只能隔离后读取。R路径如确需专用4GiB档位，与主代理协调，不能全局扩大。
- [x] 给前端简洁合同/实际响应fixture和可用入口；跑定向合同/数值/隔离DB测试并写报告。

R接口拟定：`get_bridge().propeller(counts, sample_ids, label_ids, conditions, donors, batches, mode, transform='asin', batch_adjustment=False)`。counts为已按donor×condition聚合的样本×类别整数矩阵；返回status/reason/rows/transformed/design/design_columns/logs/versions/parameters。具体字段由后端和R代理协调后记入报告，禁止各自猜测。

### 3. R propeller环境与原工具对照

负责：`adapters/single_cell_r/`、`infra/single-cell-r/`及新的propeller数值测试。不修改bio-insights业务/worker/settings（提供接线说明由后端代理处理）。

- [x] 官方文档/源码核对speckle兼容R4.4/Bioconductor3.20的固定版本及GPL许可；参考getTransformedProps与propeller.ttest原API。
- [x] 真实桥接，保留样本/类别顺序、原始比例与变换、实际模型矩阵、contrast、日志、版本；不把分数当概率。
- [x] 最小预热propeller与必要固定代码，不预热scDblFinder/decontX等无关计算；用户输入隔离后读取，保持单线程/无网络/无fork。
- [x] 为insights解释器准备rpy2及固定原生库加载，确认无需改变其锁定PyDESeq2/GSEA版本；镜像叠加到保留的b4-ready，使用新本地tag，不覆盖旧镜像。
- [x] 用同一输入对照直接speckle原生调用（非配对、配对、批次与零比例），验证结果方向/数值/设计，不以mock或安装成功替代。

### 4. 页面、Word与整体验收（主代理协调）

- [x] 复用bio-insights入口，提供组成配置、同类型供者比较、资源/ORA/GSEA选择、设计原因、实际n及结果/图件下载。
- [x] 单细胞结果可到达新路径；状态/重试/来源变化依赖沿用既有机制。
- [x] Word包含实际方法、分子分母/供者数/配对设计、标签依据和富集边界，只导出Word。
- [x] 有界公开真实donor矩阵走正式HTTP/队列/Worker，完成描述、propeller、pseudobulk/PyDESeq2、ORA/GSEA；不足供者示例只描述。
- [x] 保存counts/标签/来源/受检背景核验、原工具对照、浏览器与Word直接PNG视觉结果；修复实际缺陷后独立代码审查。
- [x] 总领、七批计划、实施记录同步；启动本批服务供用户验收，2026-11-06用户通过后停服并保留数据与结果。

## 当前进度

2026-11-05 本批实现与验证完成；2026-11-06 用户明确确认“我已验收，通过”，本批API、Worker、dispatcher、RabbitMQ已停止，4个容器均为exited。停服前无未完成任务，所有本批最终分析/绘图任务成功；历史失败保留。停服前后数据库记录数量及6份Word哈希一致，其他运行服务未变。当前分支不变，未提交、推送或部署，第6—7批未开始。

真实Kang 6400 cells/8对供者完成两种组成、CD4原counts差异、Reactome ORA/GSEA；单供者2368 cells仅描述。独立公开数据数值核验、原工具对照、图件保存值核验、页面检查、6份Word共35页直接PNG检查已通过。GSEA峰值通过减少同一原生核返回曲线的额外Python副本降到约1.78GiB，RSS2GiB/AS3GiB不变；不减少排名、完整通路族或1000次置换。没有PDF。

原本地验收入口：http://127.0.0.1:8000/ （当前服务已停止，暂不可访问）。正式结果ID、用户入口、测试数、源数据及解释边界见`docs/开发记录/阶段04/2026-11-05-单细胞七批实施记录.md`末尾；交付验证为`script/.runtime/single-cell-batch5/batch5-delivery-checks.json`，验收停服及保留核验为同目录`batch5-closeout.json`。

第5批用户验收与收尾已完成，数据、结果、Word及运行材料保留。等待用户明确指示后再开始第6批。大文件来源读取性能和统一成果入口仍留第7批；真实FASTQ/阿里云仍待账号。

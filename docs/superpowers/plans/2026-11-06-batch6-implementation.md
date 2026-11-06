# 第6批：三个可选专题实施计划

> 按已批准总领和七批计划，使用 subagent-driven-development / executing-plans 执行；本批已获用户授权，不重复确认、不提交代码。

**Goal:** 顺序接通 Slingshot 轨迹、GENIE3 调控和 CellChat 通讯的真实计算、参数、结果、图件和 Word，并启动本地服务供用户验收。

**Architecture:** 复用 bio-insights 的固定来源、异步任务、隔离执行、结果成员和 Word 下载。新增清晰的单细胞专题配置；R适配器只负责原工具计算，Python负责轴、来源、供者单位和结果接线。标签变化沿用已有依赖失效机制，不重跑基础分析。

**Tech Stack:** FastAPI/PostgreSQL/React，既有 Python 数值引擎，R4.4.3/rpy2，Slingshot、GENIE3、CellChat，python-docx。

## Global Constraints

- 仅第6批已授权；第1—5批数据与结果保留，第7批不提前实施。完成本批后启动服务，用户验收通过后再停止，等待下一批指示。
- 沿用`feat/single-cell-cloud-workflow`，不新建分支/工作树、不提交、推送、合并或部署。
- 不调用阿里云、付费或模型API；可获取许可与来源明确的公开工具、参考和数据。
- 只生成Word，图件与排版检查均不生成PDF。
- 复用当前服务、任务和资源框架，不增加用户审批或通用版本管理。原始counts、旧结果、运行材料、容器、镜像和卷保留。
- 测试只写独立schema和本批目录；其他运行服务不动。重科学计算串行，数值线程1，不默认提高既有资源上限。
- 科学工具与方法条件真实核查；未执行、不可计算、工程验证和生物学验证分别记录。

## 实现取舍

1. Slingshot使用明确选定的已有PCA/整合表示、cluster和根cluster。逐细胞保存原ID、每条分支的pseudotime/weight及未覆盖状态，保存曲线和来源；不能称为真实时间、命运或因果。现有PBMC只作工程验证，不以离散免疫类型声称真实连续谱系。
2. GENIE3使用明确选定细胞、未整合log1p表达、目标基因和显式TF清单；有界细胞/基因/树数与固定种子，不隐式将所有基因当TF。重复两个种子给出边权/排名稳定性，保留完整实际计算边；权重不是P值或因果。
3. CellChat使用未整合非负表达及固定标签，物种与LR资源匹配。按供者×条件独立计算，技术文库不增加n；缺少供者时只能明确的描述网络。跨条件比较汇总供者网络，细胞置换P不当供者层P。资源来源、许可、版本与hash明确；不自动冒充用户确认的标签。
4. 用户只选择分析需要的信息，不增加逐步审核。根节点依据、TF和LR来源、标签依据是科学参数/来源，缺失时给出具体不可执行原因。

## 任务与检查

### 1. 原工具、资源和R接口

Files: `adapters/single_cell_r/topics.py`、`topics.R`、`infra/single-cell-r/Dockerfile.topics`、对应数值测试。

- [x] 核实官方版本、依赖、许可证与参考适用条件，保存来源说明；构建兼容现有环境的固定镜像，不覆盖旧镜像。
- [x] 按Slingshot→GENIE3→CellChat顺序实现并对照原API；单线程、隔离前仅可信预热，用户输入隔离后读取。
- [x] 轨迹检查轴/根/未覆盖；调控检查TF-target方向、非负权重及两种子稳定性；通讯检查供者单位、缺标签和LR匹配、真实原工具返回值。

### 2. 专题合同、执行和结果

Files: `domain/bio_insights/single_cell_topic_contracts.py`、`single_cell_topics.py`、`adapters/bio_insights_engine/single_cell_topics.py`及现有contracts/service/task/worker/pipeline/result接线。

- [x] 先验证必要来源、参数边界、根存在、TF/表达ID匹配、非整合层和供者条件；补有意义的失败测试。
- [x] 接既有预检、运行、取消/重试、结果发布与依赖机制，不添加审批框架。
- [x] 三专题逐一保存完整表、实际图、参数/版本/日志和未覆盖/不可计算原因；原counts与父基础结果不变。
- [x] 定向合同、结果校验和隔离任务测试；runtime gate必须实际通过，不注入available回执。

### 3. 页面和Word

Files: `features/bio-insights/SingleCellTopicSetup.tsx`、工作区入口/配置/结果，Word适配器及对应测试。

- [x] 实现从已处理单细胞结果进入专题，明确三种方法及必要选项，显示任务状态、结果与科学解释边界；实际浏览器交互验收见下方未验证项。
- [x] 参数与结果遵从后端合同；图表及Word引用保存数值，未执行/NA不改成零。
- [x] 定向前端测试、lint/build通过。
- [x] 四份正式Word逐页直接PNG检查：Slingshot4页、GENIE34页、Kang CellChat7页、皮肤CellChat7页，共22页。
- [ ] 自动浏览器交互检查：工具无法可靠识别Edge当前网址而停止，此自动检查仍未完成；用户已明确确认本批验收通过，不将用户验收改写为自动测试通过。

### 4. 真实公开矩阵验收与收尾

- [x] 复用已验收PBMC/Kang原始矩阵及固定结果，明确有界真实子集、TF/LR选择和身份；不重算正确基础分析。
- [x] 顺序通过正式HTTP/队列/Worker完成三个专题，保存原工具对照与工程/生物学边界。
- [x] 独立审查修复后核对当前全部专题任务、图件和Word；更新总领、七批计划和实施记录，启动服务供验收。

## 当前进度

### 公开真实数据补测（用户追加要求）

Kang CellChat 已通过正式队列并保存结果，但432条网络记录均为0，27条供者比较均因无可估计方差而为NA。这仅验证零值/不可检验分支，不能据此宣布CellChat完整验收通过。用户要求网上寻找材料重测：保留现有结果，补充来源明确、原始整数counts和标签/供者映射可核实的公开皮肤数据，验证真实非零输出；不通过改变triMean、置换次数或筛选显著边来凑结果。第6批继续执行，尚不提交验收，第7批不启动。

优先核查CELLxGENE公开GSE204765皮肤图谱的raw.X及元数据。CellChat原论文GSE147424教程对象与GEO补充矩阵为归一化数据，不能伪装为原始counts导入。最终数据选择、来源、子集规则、数值与Word证据另据实际结果更新。

2026-11-06 用户明确“OK，开始第6批”。三个专题的R原生接口、参数合同、任务分派、结果/图件及Word接线已实现，真实公开矩阵正式队列验证、非零补测及Word检查已完成，用户已于2026-11-06确认验收通过，停服保留数据完成。

- 复用`integration`任务，配置`schema_version=2`只区分内部合同，不新增用户版本管理。Slingshot2.14.0、GENIE3 1.28.0、CellChat2.2.0.9001均固定；真实原API数值对照4例及1个存在性检查通过，3个独立内核沙箱与联合沙箱通过。联合小夹具RSS约1.032GiB，不能当作大规模容量结论。
- 许可核实后，CellChat不默认使用授权未明确的官方全DB。采用依据CC-BY4原论文独立整理的`human-demo-literature-v1`（3条LR，含CD74/CD44复合物），完整署名、来源与hash保留；明确为工程演示小集合，非全库。资源说明见`2026-11-06-batch6-methods-resources.md`。
- 最终领域/Word/发布/历史来源及物种合同50项、数值汇总5项、Word新旧场景13项通过（集合有重叠，不累加）；前端最终5文件13项及build通过（已有大bundle提示，scoped lint无error/1个FastRefresh提示）。R层及应用接线独立审查修复了映射覆盖、全NA边保留、Word逐边实际供者数、发布scope遗漏、旧来源派生字段兼容和缺物种声明入口；真实HTTP已复核第5批CD4及本批前两专题可读取且hash不变。
- 既有单细胞/QC/整合/注释环境实际探针通过；统计环境实际聚合、DE/GSEA/propeller及三topic内核探针通过，未注入可用回执。环境证据位于`script/.runtime/single-cell-batch6/`。
- Slingshot正式发布2553细胞/2分支/5106行，GENIE3正式发布2584 CD4/20TF/200基因/3980边，完整表和原生输出独立核对；两份Word各4页已检查，API Word/PNG/表下载通过。Kang CellChat按8对供者、3标签、3LR正式队列完成，但全部为零，仅作为零值/NA分支；已按用户要求完成皮肤10对供者补测，获得74条非零记录和11项可估计供者检验。旧processed没有物种字段，按Kang/GSE96583原样本资料明确声明9606及依据，未猜测或改变原始数据。
- 物种声明变更后的实际gate code_digest为`9914908295f82cb547a997255ea8d51bb5467561db9598483442e7deee1d4e25`。本批居民服务运行时探针可用内存门槛未通过，空闲时暂时停本批4服务后探针实际通过，随后恢复healthy；其他服务未操作，科学资源限制未增加。


## 本批交付与验收收尾

2026-11-06：公开皮肤raw.X完整整数检查、5985细胞固定选择、正式导入/基础处理/标签/CellChat队列已完成。输出540条完整网络记录，MIF41条、CXCL1233条非零，CCL19保持0；按原counts解析重算概率最大误差8.33e-17。27预设比较每项10对供者，11项t/P/BH可估计、16项零方差NA，最小q0.539686，无显著效应声明。独立审核核对全部原生值、绘图数据、成员hash和实际n，不重跑正确模型。

真实非零Word下载发现插图循环误嵌在全零说明分支。新增5种实际嵌图行为回归（修前4失败/1通过）后，将插图恢复为独立if figures；最终相关64项测试通过，独立复审通过；数值代码摘要和已发布成员不变，只重启API载入报告修复。新Word7页直接PNG逐页检查完成；0份PDF。

证据：`retest-skin/counts-verification.json`、`metadata-reference-checks.json`、`import-counts-check.json`、`cellchat-value-checks.json`、`native-expression-checks.json`、`api-delivery-cellchat.json`及根目录`batch6-delivery-checks.json`。交付时4服务healthy且12个既有第5批核对文件hash不变；用户确认通过后，现已停止本批4服务并核对30文件哈希不变，第7批未开始。浏览器自动交互仍未验证的事实保留，用户已确认本批验收通过；3LR资源和有界数据不等于完整生物学验证。

补充实际回归：修复后通过HTTP重新读取Slingshot/GENIE3 Word，两者document.xml及嵌入PNG与原已逐页检查文件完全相同，未覆盖旧Word或重算模型。证据word-image-regression-api.json；前端静态入口HTTP200，不能替代浏览器交互验收。

### 用户验收收尾

- [x] 用户明确确认第6批验收通过。
- [x] 仅停止本批4服务，数据库、数据、结果、Word及容器保留，停服前后核对一致。
- [ ] 第7批：未授权开始，等待用户确认。

2026-11-06 用户明确确认第6批验收通过，并要求停服保留数据。本批API、Worker、dispatcher、RabbitMQ已全部停止（4个容器均exited且保留），127.0.0.1:8000已关闭；其他4个原运行容器状态/身份不变。停服前后数据库均为4项目、10处理结果、36任务（32成功/4历史失败）、5注释集合、6注释版本和14个insight结果；结果manifest标识一致。核对的30个原始输入、结果、Word和运行文件SHA256均不变，包括公开皮肤H5AD、原counts子集及4份Word。数据目录、staging、RabbitMQ数据、容器与镜像保留，没有删除操作或分析重算。

收尾证据：`script/.runtime/single-cell-batch6/batch6-closeout.json`；交付时证据`batch6-delivery-checks.json`原样保留。第7批未开始，等待用户明确确认；阿里云真实FASTQ仍待账号。仅Word约束及现有科学验证限制不变。

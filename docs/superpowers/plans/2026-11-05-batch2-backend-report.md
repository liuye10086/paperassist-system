# 第2批后端实施与验证记录

2026-11-05。范围为已批准的第2批后端 brief；保留现有分支和全部已有未提交工作，未创建分支、提交、推送、调用云、改数据库或生成 PDF。初版后端实现与合成数据真实 R/隔离验证已通过；随后公开矩阵揭示内存边界不足，已按实测实施仅 R 任务的有界预算调整，新的最终代码真实验收由主 agent 继续，不能混同为已完成发布。

## 已实现

- `single_cell_contracts.py`：`library_qc_overrides` 按明确 `library_id` 覆盖 `min_counts/min_genes/max_counts/max_mt_fraction`，空值继承全局；拒绝重复、未知文库、继承后倒置 counts 阈值及未确认线粒体规则。可选 `doublet={enabled,exclude_predicted,expected_rate}`、`decontx={enabled}` 默认关闭。保存配方前根据原始 manifest.samples 校验文库。
- `bio_engine/qc.py`：逐细胞原因和逐文库阈值/保留/排除汇总。`pipeline.py` 使用原始导入映射中的文库 ID，独立保留可编辑供者/分组映射。工具在初步 QC 后的细胞与表达基因上按捕获文库独立执行；预测、评分与可选排除分开保存。
- `adapters/single_cell_r/{bootstrap.py,bridge.py,tools.R,algorithms.py}`：固定版本的内嵌 rpy2/R 桥接；直接将 cells×genes CSR 槽位作为 genes×cells dgCMatrix，检查整数总和不超过 2^53−1，不制造密集交换矩阵。固定 seed、SerialParam、单线程；加载两个包并以可信合成矩阵实际预热后检查进程线程数。
- R 版本合同为 R 4.4、scDblFinder 1.20.2、decontX 1.4.0；兼容依赖实际 R packageVersion 为 xgboost 2.1.4.1（Conda 包 2.1.4）和 RcppParallel 5.1.9。实际版本均保存。工具调用参数依据对应原包源码，未使用新版的 `xgb.nthreads` 参数。
- `worker.py`、`runtime_probe.py`：固定 R 前缀的 libgcc/libstdc++/libcrypto/libssl 在数值和 hashlib/ssl 导入之前预载，避免先加载基础镜像不兼容 ABI；不替换系统库、不采用泛化 LD_LIBRARY_PATH。R 初始化/包加载错误归为 `bio_environment_unavailable`，exception chaining 保留原始 traceback。
- `sandbox.py`：仅按需加入 `/opt/paperassist-single-cell-r` 只读 grant 和唯一 `/tmp/paperassist-single-cell-r-*` scratch 的精确读写 grant；未增加 fork/exec/network syscall，未授权整个 `/tmp`。原有 CPU、地址空间、FD、输出限制保留，父进程 RSS 与超时监测保留。
- 严格单线程诊断发现 igraph 间接加载的 cli 默认启动进度 tick pthread；逐包 `/proc/self/task/*/comm,wchan` 证据定位后使用上游支持的 `CLI_NO_THREAD=1` 禁止该显示线程，未杀线程或放宽单线程门禁。R 结果显式拷贝为 Python 自有数组，逐库结果汇总后执行固定 R gc，再进入 Scanpy。
- `decontx_counts` 独立 sparse float64 层，仅全部建模文库完成才输出完整层；部分失败保留污染率/状态/原因，不将未经校正值混充校正层。可选 doublet 排除后同步最终 counts、污染层、H5AD、嵌入和聚合轴。原始整数 counts 继续驱动规范化、marker 与 pseudobulk。
- 输出表 `library_qc/library_algorithms/single_cell_tool_versions`，工具日志 `single_cell_tool_logs`，逐细胞模型状态/评分/预测/排除/污染率，steps `scdblfinder/decontx`，summary `single_cell_algorithms`。父进程允许这两个步骤明确保留 `partial/failed`，并独立检查校正层浮点类型、CSR 结构、最终轴、非负及不超过原 counts。
- `bio_analysis_store.py`、`api/bio_analysis.py`：能力返回原始 `single_cell_libraries`，矩阵预览按实际存在的独立层开放 `decontx_counts`。
- `single_cell_report.py`：Word 增加中英文模型状态、细胞/文库完成数、预测/排除、完整层可用性、原 counts 边界、软件版本，以及逐库可读指标/实际参数；不把原始内部 JSON 用作主要解释。`single_cell_resources.py` 明确估算未含内嵌 R/校正副本开销。`analysis_settings.py` 将独立 Python/R 源文件加入既有 code_digest。`CONTRACT.md` 记录接口。

## 红绿证据

1. 新合同测试最初因字段未存在出现 5 failed，实施后 6 passed；随后新增原始文库引用测试先因函数不存在失败，实施后通过。
2. 分文库 QC 首次 3 failed（缺 `library_ids` 接口）；实施后 3 passed。原始映射被编辑的 pipeline 测试先因未知文库失败，接入原始轴后通过。
3. 算法编排首次 3 failed（adapter 不存在）；实施后通过。零 QC 文库测试先因缺 `all_libraries` 失败，实施后通过。
4. Word 模型章节先因缺状态/版本失败；用户可读呈现、逐库模型表和 R 内存边界新增测试也先红后绿。
5. 父进程新增状态/校正层测试先有 6 failed（partial/failed 被拒、错误校正数据未检查），实施后通过。

## 已执行验证

- Windows 轻量测试：`test_bio_analysis_process.py`、`test_single_cell_batch2_contracts.py`、`test_single_cell_contracts.py`、`test_single_cell_report.py`、`test_single_cell_resources.py`，**41 passed**，使用 `--confcutdir=backend/tests/domain`，不加载数据库 fixture。
- 既有 Linux 数值镜像：`test_single_cell_samples.py`、`test_single_cell_worker.py`、本批 QC/算法测试首轮合计 **13 passed**；新增空文库测试后的本批 QC/算法合计 **8 passed**。
- 最终细化：文库汇总的 `exclusion_reason_counts.predicted_doublet` 与 final excluded_cells 同轴；该聚焦测试先红后绿。加入 R gc 调用验证后，本批 QC/算法最新 **9 passed**，记录 `qc-algorithms-green.log`。
- 既有单细胞/空间定向回归：`test_single_cell.py`、`test_bio_pipeline.py`、`test_bio_errors.py`、`test_bio_engine_transport.py`，**26 passed**，包含实际隔离空间 compute/H5AD/图像/transport。没有默认运行全套回归。
- `git diff --check` 已通过。

## 真实 R 执行状态

测试位于 `backend/tests/numeric/test_single_cell_batch2_r.py`，包含独立 COO 构造后直接原工具数值对照、重复两文库一致性、原 counts 不变与预测过滤、真实隔离 compute Worker/H5AD/浮点层最终轴，以及 R scratch grant 下未授权文件/network/fork/exec 仍被拒绝。数据均为合成矩阵，非生物学真实数据验收。

证据目录：`script/.runtime/single-cell-batch2/backend/`。测试容器使用 `--network none --memory 3g --cpus 1`，backend 只读挂载，证据目录读写挂载，固定数值解释器，各数值线程为 1。

- `real-r-attempt1.log`：3 failed，实际错误为基础镜像 libstdc++ 缺 `CXXABI_1.3.15`；完整 Worker stderr/stdout 保留在同名目录。
- `real-r-attempt2.log`：3 failed；证明 worker 提前预载 C++ 已跨过首次加载错误，进一步发现 Rsamtools/libcurl 依赖的 OpenSSL 3.2/3.3 版本与 Python 先加载的基础镜像 OpenSSL 不符；直接 pytest 也会在测试收集前固定旧 C++/hashlib 依赖。未放宽隔离。
- `real-r-attempt3.log`：3 failed；已实际加载并跑通两工具可信预热，但严格单线程检查发现 cli 的进度计时线程。逐包日志 `thread-package-diagnostic2.log` 定位到 igraph 引入 cli，原工具后续未再增加线程；使用 CLI_NO_THREAD=1 修复。
- `real-r-attempt4.log`：**2 passed，1 failed**。独立 COO 直接原工具对照、两文库一致性/过滤/counts 保持，以及真实隔离 compute Worker/H5AD/浮点校正层轴均通过。最后一个安全测试因首个测试设置的 TMPDIR 被后续子进程继承，scratch 创建到了 `/evidence` 而被 sandbox 的严格 `/tmp` 路径检查拒绝；测试和 Worker 的 scratch 创建均已显式指定 `dir='/tmp'`，未放宽路径或权限。
- 最终修复后主 agent 执行 `r-model-worker-probe`：**3 passed in 94.99s，exit_code=0**，实际证据为 `script/.runtime/single-cell-batch2/r-model-worker-probe.{stdout,stderr,run.json}`。三项分别确认独立原工具数值/轴/文库一致性/原 counts 保持、实际隔离 compute Worker，以及 R scratch 精确 grant 下未授权文件/network/fork/exec 仍拒绝；stderr 为空。
- 160×96 合成 Worker 实际预测双细胞 11 并按配置排除 11，decontX 对 160 个初步 QC 细胞成功；最终 counts 与 H5AD/校正层为 149×96。该次 manifest peak RSS 为 1,875,584 KiB（含预热），pipeline wall 6.98 秒；这只是该合成用例证据，不是公开数据或容量承诺。
- 最终 numeric runtime probe 也已通过；主 agent 继续公开矩阵/API 流程。既有 single-cell-probe 入口曾因先导入 hashlib 固定旧 OpenSSL 失败，已定位为启动器导入顺序问题；主 agent 统一为所有探针启动器先调用固定 bootstrap，科学代码保持冻结。

真实测试启动形式为固定解释器 `python -c "from app.adapters.single_cell_r.bootstrap import preload_runtime_libraries; preload_runtime_libraries(); import pytest; raise SystemExit(pytest.main([...]))"`，避免 pytest 插件早于 bootstrap 固定系统依赖。

## 未验证与限制

初版真实 R 独立工具对照、隔离 compute 及最后安全测试三项均有实际通过证据，不能以接口测试替代。公开真实矩阵、服务/API 主流程验收和报告视觉复核由主 agent 继续执行。资源估算不构成 R 模型峰值承诺；资源边界不会因工具失败而自动放宽，本次仅按下述实际测量与明确授权调整 R 专用上限。模型预测不是已证实双细胞，污染校正不是生物学验证；不声称真实数据科学质量、云性能或发布完成。

## 公开矩阵测量后的 R 专用预算调整

初次 PBMC3k 完整 API/Worker 用例在 analysis 返回 `bio_resource_exceeded`。主 agent 保留证据后直接运行原有 Worker，测得 peak RSS 2275.25 MiB，超过原父进程 2 GiB 门禁；VmSize 达到原 AS 3072 MiB。scDblFinder 完成并预测 136 个双细胞，decontX 实际错误为 `cannot allocate vector of size 103.0 Mb`，未伪称污染校正成功。测量证据为 `script/.runtime/single-cell-batch2/memory-single/measurement.json` 和相应 `output/single_cell_tool_logs.txt`。

根据该实际证据，实施已授权的最小 R 专用边界：

- `single_cell_resources.analysis_limits_for/memory_bounds` 统一选择。仅单细胞 analysis 且启用 doublet/decontx 选择 RSS 3 GiB、AS 4 GiB；基础、空间、导入与图形任务仍 RSS 2 GiB、AS 3 GiB，CPU/时间/输出/矩阵规模和系统调用策略未调整。
- 冻结 snapshot.limits、snapshot 校验、resource_estimate、父进程 RSS 监控、子进程 sandbox 和 manifest.resources 使用一致预算。R snapshot 的 memory_bytes 必须恰为选定 3 GiB，拒绝写 2 GiB 而实际运行 3 GiB 的不一致状态。没有增加用户可选的 profile、版本或审批流程。
- 单细胞 resource_estimate 额外提供 `optional_r_limits` 完整模型值；初始 default `configured_limits` 仍为基础预算，实际传入 R 参数时按新预算计算，供前端无需额外 API 回合正确显示。
- 每次 R 工具返回且数组已复制后立即 GC，可信预热的两个模型之间也立即 GC，减少跨模型残留；不改变 seed、输入、算法参数或数值语义。
- 仅针对实际 failed 日志里的明确 `cannot allocate vector of size`／`cannot allocate memory block of size` 分类 `resource_insufficient`；不将 permission 等错误归类为内存不足。全部文库同为该原因失败时 summary 保留该具体原因；Word 中英文显示“计算内存不足”／“Insufficient computation memory”及原代码。

此次红绿包括 R/基础预算选择、错误冻结预算拒绝、optional_r_limits、逐工具 GC、窄范围分配错误分类和聚合、Word 可读原因。最新验证为 **53 passed** 轻量测试（`memory-lightweight-green.log`），以及 **16 passed** Linux 数值/QC/编排/基础实际 Worker/完整 FD sandbox 回归（`memory-bounds-regression-green.log`）。基础 Worker 实际 manifest 仍为 RSS 2 GiB／AS 3 GiB。重 R 测试已补 3／4 GiB manifest 与实际 RLIMIT_AS 断言，由主 agent 在代码冻结后重新执行，随后复验公开 single/multiple 主流程及资源记录。

新的 R 专用预算是基于当前公开用例测量的有限调整，不代表所有 20k 细胞范围均可完成；新的最终真实验收状态以主 agent 后续证据为准。初版 3 项真实 R 通过结果仍属初版边界的证据，不能直接替代本次预算调整后的最终验收。

## 用户明确指定的最终 4 GiB 上限

在上述测量和 3／4 GiB 调整后，用户明确指示“那直接提高上限到4gib呗”。已据此将仅启用 R 模型的单细胞任务最终上限调整为 **RSS 4 GiB／AS 5 GiB**，替代前述中间的 RSS 3 GiB／AS 4 GiB。基础、空间、导入和图形任务仍为 RSS 2 GiB／AS 3 GiB。主 agent 将验收容器设为 5 GiB，为应用父进程保留空间，数值子进程 RSS 仍有实际 4 GiB 门禁。

同一共享选择函数驱动冻结 snapshot、严格校验、optional_r_limits、实际 estimate、parent RSS 监控、child AS 和 manifest.resources。R snapshot 接受当前选定 4 GiB，拒绝旧 3／2 GiB 以免记录与执行不一致；没有新增 profile 控件或任务版本。

预算测试先出现 5 failed，调整后预算与资源估算定向测试 **13 passed**（`backend/memory-4g-budget-green.log`），`git diff --check` 通过。重 R 测试的实际 manifest 和 RLIMIT_AS 断言同步为 4／5 GiB；新的真实 R 和公开 single/multiple 验收等待主 agent 的冻结后复验，不重用旧 3／4 GiB 运行结果冒充当前通过。

## 多文库实际输出预算修复

4 GiB RAM 版本的公开 single 已由主 agent 实际通过：两模型均覆盖 2700 细胞，scDblFinder 预测 136，峰值 RSS 2165329920 bytes，并生成 11 张 PNG 与 DOCX。8119 细胞 multiple 仍失败；直接诊断证据 `memory-multiple/measurement.json` 表明 peak RSS 2811.8867 MiB、VSZ 3740 MiB，均低于 4／5 GiB 限制，两个文库的两个模型都已完成。stderr 明确定位 `pipeline.py` 写入 H5AD 后 `manifest.py` 的 `output_budget_exceeded`，实际目录总量 547633773 bytes（522.26 MiB），超过原聚合 512 MiB；H5AD 261215833 bytes 小于单文件 256 MiB。因此此次修复针对输出聚合，不提高内存或单文件上限，也不引入压缩或内存重构。

修改前将当前文件保存到 `script/.runtime/single-cell-batch2/before-output-budget-fix/`，文件清单见 `saved-files.json`。最小改动为：

- 仅启用 R 工具的单细胞 analysis 的 `SingleCellRAnalysisLimits.max_output_bytes` 为 1 GiB。普通单细胞、空间、导入、图形仍总输出 512 MiB；`max_member_bytes` 始终 256 MiB，RSS 4 GiB／AS 5 GiB 不变。
- 冻结 snapshot、严格校验、resource_estimate 与 optional_r_limits 同步；拒绝 R 任务仍冻结旧的 512 MiB 聚合限额而实际执行 1 GiB。
- `Writer` 构造接收选定聚合预算，pipeline 传入共享 helper 的预算；默认 Writer 仍为 512 MiB。add 与 existing 同时执行选定总量，单 leaf 和 FSIZE 未调整。
- 父进程 `validate_artifacts/validate_engine_result` 接收可信父进程选择的预算；不会根据子进程自报 manifest 放大限额。`bio_analysis_execution.build_candidate` 的发布 staging 同样使用冻结任务语义选择预算，消除后续发布仍被旧 512 MiB 拒绝的路径。实际 manifest/resources 记录总量和单文件上限。

针对性测试使用真实的小字节文件和合成的已登记先前成员元数据，验证 512 MiB 拒绝、1 GiB 接受、精确到上限接受/超出 1 byte 拒绝、add/existing 一致、单文件限额保留，以及 R/默认/空间/图形发布选择。没有为边界测试分配巨型内容。合同/父进程第一轮 8 failed 后修复；Writer 新测试 9 failed 后修复；发布 staging 新场景 3 failed 后修复。最终针对性结果为 **43 passed** 合同/父进程/资源验证，**9 passed** Writer 聚合边界（日志 `backend/output-budget-parent-final-green.log`、`backend/output-budget-writer-green.log`）。

科学代码已冻结，主 agent 重新运行 runtime probe、公开 multiple 和验收；尚不将旧运行结果作为本次最终代码的通过证据。没有提交或推送，现有数据和失败诊断文件均保留。

发布 helper 对旧轻量 fixture 缺 `task_type` 采用保守默认 512 MiB（`task.get`），不改变真实任务的 R 限额选择；既有非 DB publication fixture 先 2 failed，修复后 **2 passed**（`backend/output-publication-compat-green.log`），未并行执行数据库测试。该父进程文件不进入 engine_code_digest。审查增量为 `before-output-budget-fix/review-delta.diff`，修改路径清单为同目录 `changed-paths.json`。

主 agent 冻结后新的 runtime probe 已实际通过，engine code digest 为 `5ba7ed7274662d55d0123f7cd5b812667a6141f8173d682ee6d9fa93e94d119f`，真实 R 三项 **3 passed in 102.83s**。公开 multiple 完整 API/Worker/持久化验收正在执行，最终公开数据状态仍待其实际结果。

## 默认中文图负号的最小显示修复

主 agent 随后确认公开 multiple API/Worker 用例成功，另经实际队列生成英文验收示例 `374a0a1f-e9c1-5e2a-a38d-cdef112b6a42`。Word 视觉 QA 又发现既有默认中文 PCA/UMAP 负刻度显示方块。实际固定字体 `WenQuanYi Zen Hei` 的 FT2Font charmap 不含 Unicode U+2212，含 ASCII U+002D，而 Matplotlib `axes.unicode_minus` 默认为 True。`plots.save` 会给中文图的 Text 统一设置该字体；现有独立单细胞绘图已有 ASCII 负号 rc_context，默认 analysis 路径未使用，故显示不一致。

最小修复只在 `worker.py` 为默认 single_cell 且 zh-CN 的 analysis 使用同样的 `plt.rc_context({'axes.unicode_minus':False})`，不改坐标、模型、R 参数、Word 取图来源、API 或版本行为。英文、空间分析和既有独立绘图路径保留原设置。改前 worker 保存在 `before-font-fix/backend/app/adapters/bio_engine/worker.py`，审查差异见 `before-font-fix/review-delta.diff`。

针对性测试先 2 failed（默认 analysis 缺该设置），修复后 **2 passed**，实际绘制负坐标 PNG、确认没有 Glyph 8722 缺字警告、导出的 JSON 坐标与原数组完全相等、rc 设置退出后恢复，且英文/空间路径设置不受影响。证据 `backend/default-font-green.log`，PNG 与数据保存在 `backend/default-font-qa/`。没有在此子任务重跑 R。主 agent 将重新执行实际 runtime probe，并只重建中文 single 验收结果以核对默认 Word，保留字体修复前材料；数值语义不变，旧数值证据仍明确标注原运行状态。

## 最终复验与用户验收状态

主 agent 已完成上述后续验证：输出限额修复后的公开双文库API用例 **1 passed in 283.97s**，8119细胞完整输出553,843,756 bytes并成功发布；字体修复后的完整运行探针通过，真实R对照及隔离Worker **3 passed in 113.11s**，代码摘要`b0fb40e1334364bcc10035a7f38150c1d4e9695f6b69728eafa7a15136e51e91`。

最终中文实际队列结果`a4b0cb93-edb2-5450-ab39-d78b78ca9e9a`保留2368细胞，预测并排除112；英文实际队列结果保留7899细胞，预测508且不排除。修复前后中文20个科学结果成员哈希一致，PCA/UMAP负号显示已纠正；中英文Word分别17/16页，全部页面已完成直接PNG视觉检查，不生成PDF。英文结果复用未受字体变更影响的先前成功运行，不冒充以最新摘要重跑。

用户于2026-11-05确认第2批验收通过。本批API、dispatcher、Worker、RabbitMQ已停止并核对4个容器为exited，数据库、输入、结果、Word和诊断材料保留；第3—7批未开始，等待用户确认。验收入口、停止核验、测量和科学解释边界统一见[实施记录](../../开发记录/阶段04/2026-11-05-单细胞七批实施记录.md)。

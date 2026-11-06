# 第3批后端实现报告

日期：2026-11-05。已完成授权后端增量；未提交、推送、部署、停止服务或清理既有材料。公开真实矩阵、最终完整探针、正式服务/API验收和Word页面视觉复核由主agent完成，本报告不提前宣称该部分通过。

## 实际合同与实现

- 历史 `SingleCellParameters` 缺字段为 `hvg_batch_key=null`、`technical_covariates=[]`、`harmony.enabled=false`。`new_single_cell_parameters()` 提供新默认：batch HVG、log1p_total_counts、Harmony启用。直接新建请求和 `SingleCellSetupRequest.expected_revision==0` 的部分参数也合并这三个新默认；旧配方更新revision>0不合并。显式关闭优先。lambda为JSON别名，嵌套model_dump与严格往返已测。
- 参数上限：theta 0–20；lambda >0且≤100；max_iter 1–100；拒绝非有限值、重复协变量与生物组别字段。前端可使用更窄输入控件范围。
- HVG在最终保留细胞上使用已知有效batch或原始library_id。批次模式调用原生Scanpy Seurat `n_top_genes=n_top,n_bins=20`，按批内命中次数、dispersion和稳定feature ID排序，保留非恒定/有限筛选。缺批次、单批次、singleton批次明确回退global。hvg表保留means、dispersion、chosen、batch_hits与strategy。
- 协变量仅作用于HVG dense副本，受原20M dense预算限制，原生 `scanpy.pp.regress_out(n_jobs=1)` 后scale/PCA。log1p_total_counts来自原QC total_counts；mt_fraction要求已确认规则。缺失、非有限、常量、含截距设计秩不足、残差变异不足整项不应用，不悄悄丢列。原counts/normalized/log1p、marker表达与pseudobulk输入不替换。
- 保留未回归PCA、实际PCA与成功Harmony矩阵。固定R harmony 1.2.3 `RunHarmony`，theta/sigma/lambda/max_iter/early_stop/ncores/seed显式记录；原生默认nclust<2时明确not_computable，不创造替代模型。输入cells×PCs，R行名和Python返回shape/有限值/细胞顺序均核对。批次与多研究组完全混杂不应用；缺研究组允许探索性运行，另记录混杂无法评估。失败保留PCA下游。
- Harmony-only纳入既有R预算选择、隔离前可信合成预热与R scratch。R限额仍4GiB RSS/5GiB AS、总输出1GiB/leaf256MiB；基础Worker预算2GiB/3GiB实际回归通过。无权限扩张。
- 诊断在同细胞同维数上计算，固定seed最多1000细胞，silhouette和15邻居异批比例仅为描述指标。按batch/group计数，协变量前后PC图及成功Harmony前后图均保存实际坐标、细胞ID和状态。Harmony轴明确不是PCA解释方差。

### Summary/产物键

`summary.single_cell_integration={hvg,technical_covariates,harmony,design,downstream_representation,versions,diagnostics}`。这是compute结果；QC-only不冒充执行整合。

- technical_covariates.requested/columns是列数组，applied是bool。harmony.requested/applied是bool。
- hvg.strategy为global_seurat或batch_aware_seurat；fallback是bool，fallback_reason和reason记录同一明确原因；状态保持completed表示HVG确已选取。
- 下游表示仅 `X_pca` 或 `X_pca_harmony`；H5AD保存 `X_pca_unadjusted`/`X_pca`/成功时`X_pca_harmony`，另有 `paperassist_integration_json`。
- 新成员：`integration_summary`, `integration_coordinates`, `integration_design`, `integration_diagnostics`, `integration_tool_versions`, `integration_tool_logs`, `integration_x_pca_unadjusted`, `integration_x_pca`, 成功时`integration_x_pca_harmony`。
- PNG/data/manifest前缀：`integration_covariates`、成功时`integration_harmony`。`BioDefaultFigureConfig`只扩展内部默认图发布种类，保留正式figure记录和下载；独立图请求未扩展。Word取同一实际PNG并加入状态、参数、版本和诊断段落，仅DOCX。
- 原因代码：batch_values_missing、single_batch、batch_too_small、batch_group_completely_confounded、group_missing_confounding_unassessed、covariate_missing_or_nonfinite、covariate_constant、mitochondrial_rule_unconfirmed、covariate_design_rank_deficient、insufficient_residual_variation、insufficient_cells_for_harmony_default_clusters、regression_failed、harmony_failed、resource_insufficient。

## 改动文件

- `backend/app/domain/bioinformatics/single_cell_contracts.py`：参数/新建与历史边界。
- `backend/app/domain/bioinformatics/single_cell_resources.py`：Harmony R预算选择。
- `backend/app/domain/bioinformatics/analysis_contracts.py`：内部默认图合同。
- `backend/app/adapters/bio_analysis_store.py`：capabilities新默认；resource_estimate保留基础configured_limits+optional_r_limits供前端开关选择。
- `backend/app/adapters/bio_engine/integration.py`：HVG、协变量、设计适用性、Harmony编排、诊断和输出。
- `backend/app/adapters/bio_engine/embedding.py`、`pipeline.py`、`worker.py`：真实下游表示、H5AD/methods/steps、可信预热。
- `backend/app/adapters/single_cell_r/bridge.py`、`tools.R`：固定Harmony、版本、轴与预热。
- `backend/app/adapters/bio_figure_store.py`、`single_cell_report.py`：正式默认图与Word接线。
- `backend/app/adapters/bio_engine/CONTRACT.md`：结果合同。
- 新测 `backend/tests/numeric/test_single_cell_batch3_{contracts,algorithms,outputs,r}.py`。
- `backend/tests/api/test_single_cell_public_worker.py`：新增 `PAPERASSIST_SC_INTEGRATION_TOOLS=1` 开关和实际图/summary断言；未运行公开测试。

## TDD与实际验证

所有本次命令均为定向、无数据库。Windows轻量使用 `.venv/Scripts/python.exe -m pytest --noconftest ... -q`；Linux数值使用保留镜像 `paperassist-single-cell-worker:local`、`--network none --cpus 1`，挂载backend，解释器 `/opt/paperassist-bio/bin/python`，先 `preload_runtime_libraries()` 再导入pytest，`--noconftest`，OPENBLAS/NUMBA/OMP线程为1。

红测与修复证据（实际工具输出）：

- 参数/预算初始2 failed、5 passed：缺hvg新字段、Harmony未选择4GiB。新增部分新请求默认、旧编辑、嵌套lambda往返逐次先红后绿。
- 算法首轮9 failed：integration实现不存在；完成后9 passed，原生Scanpy HVG hits/means/dispersion和regress_out数值一致。
- Harmony邻居路由和R方法两项先2 failed，后11 passed（路由测试替代R只测编排，真实R另见下项）。
- 完整pipeline先缺summary失败；Word先缺Harmony段落失败；正式发布两图先2 failed；修复后全部通过。
- singleton批次原生Scanpy出现IndexError，新增明确batch_too_small回退后通过。
- 合同/资源/Word/内部发布及第2批相关回归最终 **44 passed in 2.40s**：`tests/numeric/test_single_cell_batch3_contracts.py tests/domain/test_single_cell_resources.py tests/domain/test_single_cell_memory_limits.py tests/domain/test_single_cell_report.py tests/domain/test_single_cell_batch2_contracts.py tests/domain/test_single_cell_output_parent.py`。
- Linux算法/完整输出与第2批相关回归最终 **32 passed in 40.98s**：`tests/numeric/test_single_cell_batch3_algorithms.py tests/numeric/test_single_cell_batch3_outputs.py tests/numeric/test_single_cell_batch2_qc.py tests/numeric/test_single_cell_batch2_algorithms.py`。包括关闭所有新项与旧embedding数组完全一致、Harmony失败与旧PCA下游完全一致、混杂/缺批次不调用R、原表达层不变和H5AD roundtrip。
- 真实R **2 passed in 89.88s**：`tests/numeric/test_single_cell_batch3_r.py`，容器5GiB，`--basetemp=/app/batch3-r-evidence`。第一项直接调用固定原生RunHarmony，细胞倒序且返回严格对齐，float32保存与原生float64结果在1e-6内一致；第二项实际隔离Worker执行HV​​G+回归+Harmony，邻居表示明确X_pca_harmony，保存H5AD/两张PNG/实际R日志，counts不变、4GiB预算。证据在 `backend/batch3-r-evidence/`；实际版本R4.4.3、harmony1.2.3、Scanpy1.11.5。
- 基础非R隔离Worker **1 passed in 26.65s**：`tests/numeric/test_single_cell_worker.py`，实际manifest仍2GiB RSS/3GiB AS。
- `git diff --check`通过。当前科学代码digest：`33ac1d1b37d28b025a981c81544dbea7158c181daba3036be4eedd8fd60c0c44`。真实R运行后仅新增singleton HVG回退和请求编辑边界等已定向验证变动，最终完整探针由主agent冻结后重跑，不能将早先R测试声称为当前所有字节的完整验证。

## 限制与交接

数值与R试验使用有界合成数据，不是生物学质量或独立供者推断验证。Harmony和测序深度回归基于用户选定的技术效应假设，可能移除生物信号；混合指标不证明更好生物学结果。缺研究组只允许探索并标明未评估混杂。未执行云/付费/模型调用。

Scanpy原生regress_out首次JIT出现2条NumbaPerformanceWarning（非连续数组性能提示）；无数值失败。R保留运行时提示reticulate/rpy2历史兼容警告，真实隔离测试已通过；未隐藏警告。实际网络/fork/exec禁止策略沿用，完整安全探针由主agent最终运行。

主agent需要运行最终runtime probe及batch2_r+batch3_r、公开单/双文库和真实队列组合，检查正式页面/下载/Word可读性及内存/输出上限。产物默认图kind新增已以内部发布编排测覆盖，真正数据库发布与浏览器尚属主agent验收范围。旧recipe编辑缺字段行为已单独保护。没有改已有科学测试以掩盖回归。

## 冻结前可读性补充

按主agent复核要求，对本批新增Word段和PC图做最小中英文可读接线。Word中HVG策略/回退原因、两方法请求与实际应用状态、设计适用性均使用中英文标签；design不再打印不存在的requested/applied None。诊断保留原数值，以表示、抽样细胞、维数、批次轮廓系数、异批邻居比例的带标签段落呈现；不再输出整段诊断JSON。精确工具参数/版本仍保留复现记录。图标题使用协变量处理前/后、Harmony前/后；未实际回归明确标注“未应用”，Harmony图保留“不代表PCA解释方差”的说明。未改数值、输入或工具参数。

对应Word红测1 failed和图标题红测1 failed后修复；最新Word/合同/现有报告回归 **16 passed in 3.55s**，图标题定向 **1 passed in 3.41s**。`git diff --check`通过。最终科学digest以主agent冻结后探针实测记录为准（上一节33ac...是此显示文案调整前）。所有后端代码现已冻结，主agent接手完整探针及真实矩阵/队列/Word视觉验收。

## 最终审查：整合图配色溯源修复

审查确认整合图实际调用项目 `categorical_colors(..., palette='tab20')`，该策略对应 `paperassist_golden_angle_hsl_v1`，而旧整合图manifest缺palette，正式发布会错误回落viridis。本次仅在 `backend/app/adapters/bio_engine/integration.py` 保存真实 `category_colors` 与 `effective_palette` 到图data，并在config明确 `palette=cmap='tab20'`、`effective_palette='paperassist_golden_angle_hsl_v1'`。颜色RGBA、排序、坐标与数值算法均未改变；tab20是已有项目策略标识，不伪称直接使用Matplotlib tab20色表。

对应focused测试增强在 `backend/tests/numeric/test_single_cell_batch3_algorithms.py::test_integration_plot_titles_describe_before_after_in_output_language`：同时断言两个图的config、data算法名、每个类别的导出RGBA与真实Matplotlib artist facecolors完全相等。先出现1 failed（缺palette），修复后 **1 passed, 17 deselected in 4.61s**。仅1GiB/1CPU无网络轻量容器，无R模型初始化或重型测试。`git diff --check`通过；新的科学代码digest：`824e2dc11730a3f75cf35395980cb3930b939728a84eefe31f2cbc837ef2ce4d`。再次冻结，后续必要探针刷新由主agent执行。

## 公开API失败后的父进程门禁修复

主agent最新完整probe包括真实R五项通过，但公开API单/双文库均出现bio_output_invalid。根因定位发现下载数组member键曾使用大写X，父 `validate_artifacts` 明确只允许 `[a-z][a-z0-9_-]{0,100}`；用保留真实R输出检查，恰三个integration数组违规，独立父校验复现bio_output_invalid。增强80细胞实际pipeline测试，在完整输出上直接调用 `validate_engine_result`，红测明确失败于该正则门禁，证明不是默认图kind失败。

最小修复：integration.py只把下载member名改为小写 `integration_x_pca_unadjusted`、`integration_x_pca`、`integration_x_pca_harmony`；H5AD obsm、summary表示名、矩阵和数值均保留X_pca规范。未放宽artifact正则。更新输出测试、真实R测试和文档，真实R测试也新增完整父结果及processed arrays验证，供主agent后续probe执行。

同时确认brief允许的协变量/Harmony失败回退会被父step门禁误拒绝；`bio_analysis_process.py`仅对technical_covariates/harmony精确允许failed，保留其它步骤约束，不允许这两项partial。两项红测先2 failed，修复后已绿，并显式断言pca failed仍拒绝。

实际验证：轻量合同/父门禁/现有process定向回归 **42 passed in 4.98s**；实际pipeline完整 `validate_engine_result`（包含所有member哈希、图片、JSON、数组、目录及steps等检查）和 `validate_processed_arrays` **1 passed in 60.89s**，保留证据 `backend/batch3-parent-green-evidence/test_pipeline_exports_adjustme0/output/`，仍仅出现既有NumbaPerformanceWarning。对该真实pipeline全部11张图逐项调用正式 `publish_defaults`，仅替代数据库insert/object查找，全部配置校验通过，integration_covariates正式配置kind正确、palette=tab20、2400×1200像素；这属于真实产物的发布编排验证，不是数据库事务验收。

未重跑公开数据、未运行DB测试、未更改探针回执、未运行完整probe。`git diff --check`通过。再次冻结digest：`a246273e5b8bd834f2693a665582746c10677983e33fedb6ace1a83fed206ff9`。由主agent重跑正常probe与公开API确认交付路径。

## 第二轮公开API：Word投影错误专项修复

主agent第二轮公开单/双文库测试已完成数值计算、正式发布和所有PNG下载断言，但report.docx GET仍500，381.18s的两个case不能列为全流程通过。使用此前真实工具生成的两份完整manifest（80细胞协变量、120细胞隔离Harmony）直接调用 `build_single_cell_report` 均复现相同完整栈：`single_cell_report.py → project_bio_facts → _methods`，在 `dict(step.params)` 遇到真实technical_covariates列数组 `['log1p_total_counts']` 抛出 `ValueError: dictionary update sequence element #0 has length 18; 2 is required`。不是R日志XML控制字符，也不是PNG损坏。

仅修改 `backend/app/domain/research_results/bio_projection.py`：对已知technical_covariates步骤的list参数投影成 `{'columns':[...]}`，其余步骤仍用原映射逻辑；不改保存manifest、FrozenResearchSource、实际参数、计算算法或结果。科学digest仍为 `a246273e5b8bd834f2693a665582746c10677983e33fedb6ace1a83fed206ff9`，不需要为报告转换重算科学结果或重跑探针。

新 `backend/tests/numeric/test_single_cell_batch3_real_manifest_report.py` 使用两份逐字复制的完整真实manifest小fixture（24,107/26,030 bytes），位于 `backend/tests/fixtures/single_cell/batch3_covariates_complete_manifest.json` 和 `batch3_harmony_complete_manifest.json`。无需runtime大文件、数据库、容器或R；四个“完整manifest × 中英文Word”组合先4 failed后通过，并核对方法参数、执行状态、原输入未修改。报告/合同/原事实投影定向回归合计 **33 passed in 4.16s**。`git diff --check`通过。

另将保留真实计算产物的全部PNG送入实际Word builder，中英文各生成一份covariates和harmony报告，均成功并逐一核对inline_shapes与输入图数完全相等，产物保存在 `backend/batch3-report-green-evidence/`。这是报告构建和结构检查，非视觉验收；正式API下载和页面视觉核对由主agent对现有正式结果执行，无需再次运行大型科学计算。两轮公开测试失败日志保留，报告修复后的完整交付状态以主agent专项API/视觉验收证据为准。

# 第3批：批次整合与技术协变量设计核查

日期：2026-11-05。范围：只读检查当前 `feat/single-cell-cloud-workflow` 的预处理、embedding、pipeline、合同及 R 接口；仅新增本说明。没有修改代码、服务、数据、运行环境或版本管理状态。研究结论不代表实现或验收已完成。

## 结论与授权口径

用户补充要求“需要有整合和协变量处理，启用”：新建单细胞分析默认启用 Harmony 与测序深度协变量处理，仍可关闭；验收必须包含真实启用的任务。建议默认批次感知 HVG 使用 `batch`，协变量仅 `log1p_total_counts`，不默认同时回归 `detected_genes` 或组别。

沿用已有 log1p + Seurat dispersion HVG，不在本批增加 Seurat v3/scikit-misc、SCTransform 或 Pearson residuals。实际 R Harmony 固定到 1.2.3，并使用独立 PC 矩阵接口。协变量处理在 HVG 表达副本发生，Harmony 在 PCA 表示发生；counts、normalized、log1p 及 pseudobulk 输入保持原定义。

备选方案：直接去除 PCA 对技术协变量的线性投影实现更小，但与 Scanpy 标准表达回归流程不同，不能声称与 `regress_out` 等价；增加其他整合算法超出本批必要范围。因此推荐真实 `sc.pp.regress_out` + 固定 R `RunHarmony`。

## 已核实的现状

- `preprocess.py` 用 float32 稀疏 normalize_total/log1p，现有 HVG 以 `flavor='seurat'` 计算 dispersion，再按稳定基因 ID 解决排序同值。
- `embedding.py` 仅将 HVG 子矩阵密集化，预算 20,000,000 值；scale/clip10、PCA/arpack、sklearn 邻居、UMAP、Leiden 在一个函数中。拆出 PCA 和 graph/UMAP 两段便于保存与比较表示。
- `pipeline.py` 对保留细胞/基因建模，marker 用原 counts、normalized、logged；H5AD X=log1p，counts 层保持整数；现有 roundtrip 已核对所有 obsm/obsp，新增表示可沿用该核对。
- `single_cell_contracts.py` 已有 strict 参数模型和 known/pending 等元数据状态；模型值应在 known 时使用，不能用显示用字符串 unknown 代替真实批次。
- `single_cell_r` 已采用隔离前加载可信代码与合成预热、隔离后输入、rpy2 内嵌 R、单线程及固定 scratch；无需新增外部进程或网络权限。
- `infra/single-cell-r/environment.yml` 固定 R 4.4、scDblFinder 1.20.2、decontX 1.4.0；compatibility 文件还锁 xgboost/RcppParallel。Python 固定 Scanpy 1.11.5。
- `worker.py` 和 `single_cell_resources.py` 的可选 R 判断目前只包含 doublet/decontx；Harmony-only 请求也必须进入相同 R 预热、资源与隔离路径。

## 建议最小参数合同

字段名称可随主实现统一；下面明确行为，不要求创建额外版本系统。

```json
{
  "hvg_batch_key": "batch",
  "technical_covariates": ["log1p_total_counts"],
  "harmony": {
    "enabled": true,
    "batch_key": "batch",
    "theta": 2.0,
    "lambda": 1.0,
    "max_iter": 10
  }
}
```

- `hvg_batch_key`: null / batch / library_id；null 明确关闭。library_id 是显式选择，不能在缺 batch 时悄悄替换。
- `technical_covariates`: 唯一值列表，允许 `log1p_total_counts` 与 `mt_fraction`，空列表关闭。禁止 group/donor/sample_id/cell_label 进入这份技术协变量列表。
- 建议 `log1p_total_counts = log1p(raw total_counts)`，在最终保留细胞上取值，精确记录为“QC 前原始 Gene Expression counts 的逐细胞总量”；如果实现改用过滤基因后总量，名称和方法必须显式一致，不能两者混用。`mt_fraction` 沿用既有 QC 定义，不重新猜线粒体基因。
- Harmony 仅接受 batch 或用户显式选定的 library_id；theta >= 0、lambda > 0、max_iter 正整数有上限。sigma=.1、ncores=1、early_stop=true 可固定并输出有效值，不必增加 UI 旋钮。
- 默认变更适用于新建请求；已有 recipe 的缺字段重放不能悄悄改变算法。建议在新建入口显式存完整参数，并在历史 snapshot 缺字段的兼容路径保留旧关闭含义。实际采取哪条路径需核对现有序列化点。

## HVG：必须防止“批次感知”名实不符

官方 Seurat dispersion 接口使用 log 数据，而 seurat_v3 才要求 counts。带 batch_key 时按批内 HVG 次数优先、聚合 dispersion 次优选基因。[Scanpy 1.11 文档](https://scanpy.readthedocs.io/en/1.11.x/generated/scanpy.pp.highly_variable_genes.html)

批次分支调用 `highly_variable_genes(..., flavor='seurat', batch_key=..., n_top_genes=n_top, n_bins=20)`，提取 `highly_variable_nbatches`、dispersion、means；最终以 `(-nbatches, -dispersion, stable_feature_id)` 排序，并沿用有限值与非恒定过滤。导出实际排名、nbatches、chosen、有效批次数、requested/actual 策略。

不能将现有 `n_top_genes=None` 和全开放阈值直接加 batch_key：那会让每批近乎所有基因算作 HVG，削弱 nbatches 的本意。源码显示批内选择与合并排序都受 n_top_genes 控制。[Scanpy 1.11.5 源码](https://raw.githubusercontent.com/scverse/scanpy/1.11.5/src/scanpy/preprocessing/_highly_variable_genes.py)

缺批次、单批次、某批次少于2细胞或可计算方差不足时，采用既有全局 HVG，沿用已支持的节点状态并另记 `fallback=true`、原因与 actual_strategy=global，不增加新状态枚举；禁止删除缺失细胞后仅以子集代替完整分析。2细胞是本地可计算性防线，不代表科学充分性阈值。更小批次和严重数量不均衡均可附加警示。

## 协变量：仅改变降维分支

官方 `scanpy.pp.regress_out` 使用线性回归，文档明确提示某些情形可能过度校正；它不是自动识别技术效应的因果模型。[Scanpy regress_out](https://scanpy.readthedocs.io/en/stable/generated/scanpy.pp.regress_out.html)

推荐顺序：确定最终细胞、HVG → 建 HVG dense copy → 保存未回归 PCA → 在另一个副本建立只含所选连续技术协变量的 obs → `sc.pp.regress_out(..., n_jobs=1)` → scale/clip10 → PCA。回归残差允许负数，只用于表示，不写入 X、counts、normalized 或用于 marker 的 log1p。

在调用前检查值完整、有限、非恒定，含截距设计矩阵满列秩、剩余自由度充足；明确拒绝/记不可计算，而不任意填均值、删细胞或默默丢列。所选字段任一不可用时推荐整项协变量处理 not_computable，输出字段级原因，继续使用未回归 PCA；不要声称完整执行。线粒体协变量另要求已有 confirmed 规则且 QC 可计算。

同时选择两个高度相关但未严格共线的变量可记录条件数/相关系数警示；不要以任意相关阈值自动认定疾病效应或改动组别。默认仅深度避免不必要的共线性。原始测序深度也可能含生物信号，报告需说明该处理基于用户选定假设。

若回归使某些 HVG 恒定，要报告实际 PCA gene mask 和 dimensions；前后 PCA 比较宜使用相同有效基因子集及同一成分数，或者明确它们不同，不把变化全归因于校正。

## Harmony：版本、API 与边界

CRAN 1.2.3 DESCRIPTION 声明 R>=3.5，R 4.4 满足此声明；这只是依赖条件，实际安装、二进制 ABI 和隔离执行需本地验证。[1.2.3 DESCRIPTION](https://raw.githubusercontent.com/cran/harmony/1.2.3/DESCRIPTION)

固定调用形态：

```r
set.seed(seed)
harmony::RunHarmony(
  data_mat=pcs, meta_data=metadata, vars_use="batch",
  theta=2, sigma=0.1, lambda=1,
  max_iter=10, early_stop=TRUE, ncores=1,
  plot_convergence=FALSE, return_object=FALSE, verbose=TRUE
)
```

矩阵为 cells × PCs float64，meta_data 同序且 rownames=cells。独立新增 `run_harmony`/`pa_harmony`，不要复用只接收整数 counts 的 pa_run 参数，也不要将其包装成假的 genes × cells counts。返回必须严格验证 shape、有限值、细胞顺序，之后才转存 float32。1.2.3 返回矩阵；不是旧文档中的 HarmonyMatrix/do_pca API。[1.2.3 matrix API](https://raw.githubusercontent.com/cran/harmony/1.2.3/R/ui.R)

保持 scale 后常规 PCA scores，不额外对每个 PC 做单位方差 whitening；上游 Seurat 方法直接传入 PCA embeddings，可作为对照。[1.2.3 Seurat 接口](https://raw.githubusercontent.com/cran/harmony/1.2.3/R/RunHarmony.R)

不要浮动安装 master：检查时上游 master DESCRIPTION 已为2.1.0，独立接口 lambda 默认值为NULL，与1.2.3不同。[上游当前 DESCRIPTION](https://raw.githubusercontent.com/immunogenomics/harmony/master/DESCRIPTION)、[上游当前接口](https://raw.githubusercontent.com/immunogenomics/harmony/master/R/ui.R)

conda-forge 发布目录有1.2.3版本记录，但本次浏览未确认对应 linux-64/R4.4 的确切 build；应由实现者 dry solve/镜像构建决定，并锁实际 explicit-spec，不能据此声称兼容已验证。[发布目录](https://anaconda.org/conda-forge/r-harmony)

tiny 数据要处理 nclust 默认 min(round(N/30),100) 可能为0/1的情况。建议显式有界 nclust=max(2,min(round(N/30),100,N-1))，作为本地参数策略写入有效参数与原工具对照；若避免偏离默认，则对这类数据 not_computable，不能静默当作正常多群整合。最少细胞/批次规则是本地适用性政策，不能描述为 Harmony 官方科学保证。

Harmony 完成后仅以 X_pca_harmony 重建 neighbors/UMAP/Leiden。保留 X_pca；不要将 corrected embedding 称为已校正基因表达，不能替换 pseudobulk counts。环境缺失/工具失败保留 failed 与原因；数学/设计条件不足为 not_computable；用户关闭为 not_requested。若继续输出未整合探索结果，其 downstream_representation 必须明确。

## 缺失与混杂设计

- 批次完整指最终保留细胞全部具有 known、非空批次；pending/unknown/not_applicable 不变成一个有效批次。
- 缺批次：not_computable/missing_batch_metadata；单批次：not_computable/single_batch。
- group 完整且至少2组时，输出 batch × group 列联表，按样本/供者去重汇总辅助理解，细胞数仅是组成不是独立重复。
- 完全混杂的直接检查：每个 batch 仅属于一个 group，且存在至少2个 group，即 group 被 batch 完全决定。此时 block Harmony，reason=complete_batch_group_confounding；不能凭算法“混匀”区分技术和生物差异。
- group 缺失/部分未知：design_status=unknown，展示已知比例，无法排除混杂；允许普通探索性整合，不一概阻断。
- 部分重叠、不平衡或部分不可识别：记录 partial/imbalanced 与具体表；不宣称生物信号已保留，不产生供者级统计结论。可用固定 one-hot 设计秩辅助报告，但不能将细胞数当样本重复。
- donor 与 batch 对应关系单独报告，donor 不进入默认要移除变量。疾病对照及独立供者比较仍属于后续批次。

## 结果合同与诊断

每个节点都输出 requested、status、reason、applied、实际输入层/表示、有效参数、版本；总结果输出 downstream_representation。已与主任务实施brief统一：摘要使用 `summary.single_cell_integration`，新图/表/member key以 `integration_` 开头，结构建议：

```json
{
  "hvg": {"requested_strategy":"batch_aware","actual_strategy":"batch_aware","status":"completed","reason":null,"fallback":false},
  "technical_covariates": {"requested":true,"status":"completed","applied":true,"columns":["log1p_total_counts"]},
  "harmony": {"requested":true,"status":"completed","applied":true,"method":"R_harmony","version":"1.2.3"},
  "design": {"status":"unknown","reason":"group_metadata_unavailable"},
  "downstream_representation":"X_pca_harmony"
}
```

保留 `X_pca_unadjusted`、`X_pca`（协变量后/Harmony前）、成功时的 `X_pca_harmony`；图需保存精确输入坐标和类别色表。最低前后图：相同细胞/HVG/成分数的 Harmony 前后二维 PC/校正表示，各以 batch 着色，group 可用时增加组成表或着色；协变量前后 PCA 图或 PC–深度相关诊断。布局可拼成 PNG，Word 直接引用，不生成 PDF。Harmony轴是校正坐标，不应继续标注原PCA解释方差。本批不要求额外计算前处理UMAP，避免运行与资源膨胀。

`X_umap` 继续表示实际下游选用表示的UMAP。若以后补充两次UMAP，需相同图参数/seed且明确输入；其坐标轴旋转、缩放和整体布局没有逐点可比意义，图上不能用点位移宣称改善。完全未处理baseline、协变量处理后/Harmony前、Harmony后三种状态的命名必须分开。

推荐定量诊断均为描述性指标：

1. 在全维 PC/Harmony 空间按相同 k、欧式距离重新计算 kNN，排除自身，计算每细胞异批邻居比例；导出逐批均值、宏平均及按细胞数加权均值。另给随机抽邻居时由整体批次比例决定的期望基线，提醒不平衡影响。
2. 可计算邻域 batch entropy `-sum(p_b*log(p_b))/log(B)`；B>=2，有界0..1。它是归一化邻域熵，不应标 iLISI/kBET，也没有显著性 p 值。
3. 前后 kNN 集合 Jaccard/重叠率揭示表示变化幅度，但不是生物保真分数。
4. 协变量与各PC的 Pearson 相关绝对值，保存实际PC数、constant/undefined原因；更低相关只说明线性关联下降。
5. batch/group/cluster 组成表用于人工检查。完全混杂或 group 不足时明确生物保留不可验证。不要用新发现的 cluster 标签冒充已知细胞类型评价质量。

不设“混合更好即成功”的硬阈值；不同细胞组成本来就可能不应完全混合。工具完成、技术混合变化、科学合理性/生物验证必须分开呈现。

## 最小验证方案

1. 合同：默认开启/显式关闭、合法字段、重复/非法协变量、theta/lambda/max_iter边界；历史参数缺字段重放语义。
2. HVG：2批有共享及批次特异高变基因，直接 Scanpy 对照 nbatches/dispersion；稳定ID排序策略单独验证；缺批次、单批次、小批次明确 fallback。
3. 回归：同一密集HVG输入直接 `sc.pp.regress_out(n_jobs=1)` 对照残差，再验证PCA；缺失/非有限/常量/共线性状态及原logged/counts未变。
4. 真实 R：相同float64 PC矩阵、细胞顺序、batch、seed、所有参数；独立调用 `harmony::RunHarmony`，不调用 pa_harmony 生成基准。比较float64输出严容差；最终float32存储采用符合舍入的容差并解释。
5. 沙箱：Harmony-only 请求实际启用R，预热仅合成输入，隔离后工具运行；单线程、无socket/fork/exec，未授权scratch访问拒绝。
6. 管线：counts/normalized/log1p逐值未变，H5AD轴/新增obsm roundtrip，neighbors实际来源验证；marker/pseudobulk仍读原定义表达。校正可以改变聚类因此marker结果可变化，不要求开启前后marker数值完全一致。
7. 边界：缺batch、单batch、完整混杂、group未知、工具故障、资源不足、全部/部分协变量失败；UI、Word、methods、recipe、表格对同一状态一致。
8. 真实公开已保留矩阵复用；多文库任务真启用回归与Harmony，导出前后图/指标、运行版本、峰值与耗时。PBMC3k+PBMC6k同供者只能验证工程和探索一致性，不能证明跨供者生物保真。
9. 图件PNG与中英文Word直接渲染检查；不生成PDF。不因本说明运行云调用、修改业务数据或提交代码。

## 仍待实现者确定/验证

- 新建默认与历史snapshot兼容实现点；brief已选旧SingleCellParameters缺字段保留关闭、新建工厂显式启用。
- 1.2.3实际R4.4构建、依赖锁及Harmony-only预热/资源接线。
- nclust小数据明确策略，精确日志/收敛证据；若不获取模型对象，不从日志缺失编造收敛状态。
- 默认深度已按brief确定QC前Gene Expression总量；核对方法与实际数据来源一致。
- 前后PCA、Harmony、描述诊断的实际耗时与内存，既有资源上限是否足够；没有运行峰值实测前不扩容承诺。

本文件为已检查源码和官方资料基础上的设计建议；尚未执行本批原工具数值对照、实际Harmony安装、真实矩阵运行或页面/Word验收。

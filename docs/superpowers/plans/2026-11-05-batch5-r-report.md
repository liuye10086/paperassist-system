# 第5批 speckle / propeller 运行桥接报告

2026-11-05。R 适配器及叠加镜像已完成，小型原工具数值对照已通过。本文不将这些证据等同于公开 donor 数据正式队列验收或生物学有效性；整体验收由主代理另记。

## 固定原工具、来源与许可

- [Bioconductor 3.20 官方镜像发布页](https://bioconductor.posit.co/packages/3.20/bioc/html/speckle.html)明确 R 4.4、speckle 1.6.0、GPL-3。
- [官方源包](https://bioconductor.posit.co/packages/3.20/bioc/src/contrib/speckle_1.6.0.tar.gz)：SHA256 `37c10a800662f8e73dec695fa943956d00d6c6a6a61bcbebbfbb8a31e39829c7`。实际读取 DESCRIPTION：Bioconductor 3.20 / RELEASE_3_20 / commit `5919895`（2024-10-29）、GPL-3、无需编译。保留原包及许可，没有抽取函数冒称完整安装。
- 已直接读取此固定源包中的 `R/getTransformedProps.R`、`R/propeller.ttest.R` 和 NAMESPACE，执行使用安装后的导出函数。上游现行源码可参照 [getTransformedProps](https://github.com/phipsonlab/speckle/blob/master/R/getTransformedProps.R)、[propeller.ttest](https://github.com/phipsonlab/speckle/blob/master/R/propeller.ttest.R)，固定发布源包为实际版本依据。
- 方法引用：[Phipson et al., propeller, Bioinformatics 2022, btac582](https://doi.org/10.1093/bioinformatics/btac582)。检验为原生 limma lmFit / contrasts.fit / eBayes；robust=TRUE、trend=FALSE、sort=FALSE，少于三个受检类别时由原工具自动关闭 robust。
- 真实版本：R **4.4.3**、speckle **1.6.0**、limma **3.62.1**、statmod **1.5.2**、rpy2 **3.5.17 ABI**。speckle 的 Seurat 等 Imports 复用原镜像既有包，不进行 Conda 环境重解。

## 实现与接线合同

文件：`backend/app/adapters/single_cell_r/{bridge.py,propeller.py,propeller.R}`；镜像：`infra/single-cell-r/Dockerfile.propeller`。

固定 ABI bootstrap 必须早于 numpy/scipy/hashlib 等原生模块；调用 `initialize_propeller(Path(scratch))` 后再计算 runtime identity、进入原有 sandbox。该方法只用固定小型合成计数预热 speckle，提前导入固定 Python decoder、读取固定 R 脚本，**不读取用户数据、不预热 scDblFinder/decontX/Harmony/SingleR 计算**。R 包的必需 Imports 会正常加载。用户输入只在隔离后打开；只需既有 R 固定安装前缀只读和本 attempt scratch 读写，不开放应用源码、网络或 fork。

```python
get_bridge().propeller(
    counts, sample_ids, label_ids, conditions, donors, batches,
    mode, transform='asin', batch_adjustment=False,
    numerator='stim', denominator='ctrl',
)
```

- `counts` 是 samples × labels 的非负整数矩阵；总和最多 20k，每行总数必须大于零。sample/label 轴唯一且顺序保留；不按字母重排。sample 已是 donor × condition 的汇总，不把技术文库当独立重复。
- `mode` 为 `unpaired` / `paired`，兼容后端 `donor_unpaired` / `donor_paired`。非配对必须 donor 唯一、每组至少三人；配对必须至少三个完整且唯一的双条件 donor 对。
- `batches` 可为 None；启用 batch_adjustment 时必须完整、有至少两个实际 batch。设计实际使用 `~0+group`，paired 加 donor，启用批次加 batch。R QR 检查秩和残差自由度，不放行混杂。
- 建议始终显式传 numerator / denominator；省略时按 conditions 首次出现的两组依次作为 denominator / numerator。contrast 始终为 `[-1,+1,0,...]`，方向为 numerator − denominator。
- transform 显式 `asin` 或 `logit`；原包文档声称默认 asin，但固定源码的 NULL 默认实际是 logit，因此桥接不使用默认。logit 零比例处理由原生 0.5 伪计数完成；原始比例保持实际 counts 分母。
- 返回：`status/reason/logs/versions/parameters/rows/sample_ids/label_ids`；取得设计后另有 `proportions/transformed/design/design_columns/contrast`，数值均为可 JSON 序列化 list。前两个矩阵为 samples × labels，design 为 samples × coefficients。
- row 保留 label_id、status/reason、`mean_proportion_denominator/mean_proportion_numerator/proportion_difference/proportion_ratio/ratio_status/t_statistic/p_value/p_adjust`。PropMean 和 PropRatio 保留原工具定义：原始组均值及比值，不能解释为协变量调整后比例。零分母非有限比值序列化为 None 并说明 ratio_status。
- 单类别完全无比例变异不进受检集合，row `not_computable/no_testable_variation`、P/FDR=null，仍保留原有比例及分母。全部无变异、全无残差变异、秩不足或无残差自由度返回整体 not_computable；R 工具异常返回 failed 与真实日志。

## 镜像与环境核验

新本地 tag：`paperassist-single-cell-worker:b5-propeller`。基底 `b4-ready` 保留，没有覆盖旧镜像、清理容器或删除输入/结果。

最终镜像 ID：`sha256:a8067d45f4fabde92b105be1c2f91de35ffd9317f87fdd6efb355338271a665a`。

Dockerfile 安装源包前验证上述 SHA；安装后检查真实 R 包版本、insights `pip check`、PyDESeq2 0.5.4 / GSEApy 1.3.1。insights 解释器只新增固定 rpy2 及 cffi 2.1.1 / pycparser 3.12 / Jinja2 3.1.6 / MarkupSafe 3.0.4 / tzlocal 5.4.5。与 b4-ready 的**所有既有 Python distribution 版本逐项比较 `changed_existing={}`**，没有修改锁定 PyDESeq2/GSEA 包。证据 `script/.runtime/single-cell-batch5/propeller-package-inventory.json`、`propeller-image-build.log`。

`warm_render_environment + initialize_propeller` 在单个 2GiB、1CPU、network none 容器实测成功：峰 RSS **1,001,048 KiB（约978 MiB）**、VmPeak **1,742,548 KiB（约1.66 GiB）**、实际线程 **1**。证据 `propeller-memory.py` / `propeller-memory.json`。这是小型预热与环境装载证据，未宣称任意公开矩阵都满足预算。R 初始化新增 R 的 BLAS/OpenMP 库，因此已告知后端：所有正常 probe / Worker 必须一致预载最小 R，再计算环境身份；不能只对 schema5 改变 inventory。

## 红绿与原工具数值对照

新增 `backend/tests/numeric/test_single_cell_batch5_propeller.py`。实现前在保留 b4-ready 容器运行时 **5 failed**，均为断言 `initialize_propeller` 缺失；这确认测试覆盖新增桥接缺口。Windows 无固定 R 环境仅 skip，不作为通过证据。

实现后在最终 b5-propeller 的 **insights 解释器**、network none、2GiB/1CPU 中：**6 passed in 7.82s**，日志 `script/.runtime/single-cell-batch5/propeller-numeric.stdout`。

- 同一输入以独立 R 函数展开实际计数，直接调用 `speckle::getTransformedProps` / `speckle::propeller.ttest`，不调用桥接 R 包装函数生成期望值。
- 非配对、配对、真实 batch 项、零比例 logit 四种情形逐项对照原始比例、变换、设计、contrast、两组 PropMean、PropRatio、T、P 和 FDR，容差 rtol=1e-12 / atol=1e-14（比例/变换 atol=1e-14）。样本采用逆字序确认没有静默重排；正向 T 与预设方向一致。
- 有意义失败：伪造独立 donor、完整配对不足、完全 batch 混杂、浮点假 counts、全常数比例。
- 额外检查：恒为零的未分配类别仍保留且 P/FDR=null；显式交换 numerator/denominator 时 T 反号、P 不变、ratio 互为倒数。

后端完成 sandbox 接线后，另以 `propeller-isolation.py` 在单个 2GiB/1CPU/network none 的 insights 容器做小型直接隔离验证：固定模块/最小 R 在隔离前加载，声明的用户 counts 仅隔离后 `np.load` 读取，真实 propeller 完成；`/etc/passwd`、socket 和 fork 均被拒绝。证据 `propeller-isolation.json`。首次测试使用了不符合 scratch 固定前缀的目录，被既有检查正确拒绝；改为后端要求的 `/tmp/b04-propeller-*` 后通过，没有放宽规则。

本报告不生成 PDF。正常 HTTP / DB / 队列、真实公开 donor 数值与完整运行探针由主代理和后端代理负责验收；上述小型测试本身没有替代这些证据。

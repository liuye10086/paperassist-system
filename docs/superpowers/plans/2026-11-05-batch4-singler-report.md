# 第4批 SingleR 真实适配与离线参考

2026-11-05。科学适配子任务已实现并完成定向原工具数值验证；公开PBMC矩阵的正式API/RabbitMQ、隔离Worker、权限、标签保存及Word验收由第4批主任务继续执行。本报告不把适配器通过当作整批验收或生物学验证。

## 实现与接口

- `backend/app/adapters/single_cell_r/bridge.py`：`get_bridge().classify(expression_csr,cells,stable_gene_ids,reference_config,seed)`；输入是cells × genes CSR的非负log-normalized表达，直接有界映射到genes × cells `dgCMatrix`。不得传协变量回归/Harmony表示；原始counts不修改。
- `tools.R`：真实`SingleR::SingleR`，固定classic、quantile=.8、fine.tune=TRUE、tune.thresh=.05、prune=TRUE、`SerialParam`和`KmknnParam`。预热只使用代码内固定合成参考/表达，实际参考在隔离后由classify读取。
- `annotation.py`：轴、非负有限值、reference config/metadata/checksum、exact稳定ID交集、结果矩阵验证与unknown表示。`reference_catalog()`无R/无网络；可从运维环境变量`PAPERASSIST_SINGLE_CELL_REFERENCE_ROOT`读取已发布元数据，available的scope明确为元数据发布，实际执行仍校验RDS。
- 输出`status/reason/logs`、`cells`、`candidate_labels`、`pruned_labels`、`label_status`、`scores`、`score_labels`、`candidate_ranks`、`delta_next`、`delta_median`、`reference`、`matching`。R数值复制到Python后才能释放R临时对象。pruned NA输出unknown，未pruned自动标签仍是candidate，绝不写confirmed。

固定配置：

```python
{"reference_id":"monaco_immune_1.0.0", "species":"Homo sapiens",
 "gene_id_type":"ensembl_gene_id", "label_level":"main"}
```

物种/ID必须显式匹配，main/fine可选择；不猜symbol、不去Ensembl版本后缀。少于50个共同基因拒绝计算是工程最低条件，不是科学质量保证。任何测试细胞在共同基因上无表达，记录`no_expression_on_common_genes`，不强行给标签。初始score排名与fine-tuned候选可能不同，两者分别保留；相关性分位score不是概率。delta.next是fine-tuning后第一与第二分差，delta_median是最终候选对应初始score与本细胞score中位数之差。

## 官方来源、版本与许可

固定参考是celldex的Monaco免疫参考legacy **1.0.0**，ExperimentHub **EH3496/EH3497**；对应fetch路径编号为**3512/3513**，不能把EH编号直接当fetch路径。官方metadata数据库已核对rdatapath为`celldex/monaco_immune/1.0.0/{logcounts,coldata}.rds`。gypsum的2024-02-26端点本机返回403，因此没有把旧版内容冒称2024版。

114个人类bulk RNA-seq样本、10个main/29个fine标签；原46077行按固定HGNC的approved symbol精确映射到30381个唯一Ensembl gene IDs，丢弃15696个未映射/歧义行。转换不使用用户数据、不推断alias。官方reference表达列名与标签行名已实查完全相同（114样本）。

来源及许可分别记录，未把包许可、文章许可和GEO数据混为一个声明：

- [SingleR Bioconductor 3.20官方包页](https://bioconductor.posit.co/packages/3.20/bioc/html/SingleR.html)：SingleR2.8.0对应R4.4，GPL-3。
- [celldex Bioconductor 3.20官方包页](https://bioconductor.posit.co/packages/3.20/data/experiment/html/celldex.html)：celldex1.16.0，GPL-3；[Monaco官方函数源码](https://raw.githubusercontent.com/LTLA/celldex/master/R/MonacoImmuneData.R)记录参考、标签及legacy路线。
- [Monaco原论文官方PMC全文](https://pmc.ncbi.nlm.nih.gov/articles/PMC6367568/)：Monaco et al., Cell Reports 26, 1627–1640.e7 (2019), DOI 10.1016/j.celrep.2019.01.041，文章CC-BY-4.0。[GEO GSE107011](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE107011)为公开来源，未额外断言其单独dataset license。
- [HGNC官方下载说明](https://www.genenames.org/download/)、[HGNC许可](https://hgnc.genenames.org/about/license/)：映射源CC0，固定下载内容的SHA，不浮动接受后续文件变化。
- [SingleR官方classic模式说明](https://bioconductor.org/books/release/SingleRBook/classic-mode.html)、[官方pruning诊断](https://www.bioconductor.org/packages/release/bioc/vignettes/SingleR/inst/doc/SingleR.html)：支持参考/测试共同基因匹配、候选/pruned及score解释；具体API以已安装2.8.0实际执行为准。

`infra/single-cell-r/prepare_reference.py`固定原输入SHA，`prepare_reference.R`验证样本轴/标签/矩阵后构建RDS；所有来源SHA和转换策略完整保存在reference.json：

| 文件 | SHA256 |
|---|---|
| Monaco logcounts.rds | `e3b00cc5a067c30f4e0771bee0d55123b99792d6ec8a8f37c5402563c6bba456` |
| Monaco coldata.rds | `b0f2d858616c48e835ec79376732dac41ae0564708d3707b7b039a994fc3208b` |
| HGNC complete set | `d93ce6b22d01dc1e1ded28857246951d605ead47ed17ef973ad1142b1d13bed0` |
| 最终reference.rds | `e6b98c0e89e9ca070ab50f502af57ed2b3a200b45d60f28319771dd4d5de0993` |

最终reference.rds为15757956 bytes，runtime固定位置`/opt/paperassist-single-cell-r/share/paperassist-reference/monaco_immune_1.0.0/`。宿主准备材料在`script/.runtime/single-cell-batch4/reference-source/`和`reference/`，不把大文件提交进仓库。

## 镜像与实际验证

构建最终镜像 **`paperassist-single-cell-worker:b4-ready`**，`Dockerfile.annotation`和`Dockerfile.reference`及README提供可复现命令。原R4.4.3、scDblFinder1.20.2、decontX1.4.0、Harmony1.2.3、xgboost2.1.4.1、RcppParallel5.1.9保持；runtime仅增加SingleR2.8.0、DelayedMatrixStats1.28.0、sparseMatrixStats1.18.0与只读参考。

最初给runtime加入celldex及31项依赖后，原`initialize`检查实际发现15条`V8 DefaultWorke`后台线程。根因是V8被既有rstan发现并加载，故celldex只留在reference builder，最终runtime从原Worker复制必需的三个R包，不携带V8/其他28项。修复后原固定合成QC/Harmony/SingleR预热通过单线程检查，未放松沙箱、线程或网络规则。

已执行：

- 首先运行缺失接口的RED测试，原生环境正确失败于`EmbeddedR.classify`不存在；另记录并修复pytest先载入系统OpenSSL/C++库的测试启动顺序，使用原bootstrap再import pytest。
- `tests/numeric/test_single_cell_batch4_singler.py`原5项在Linux真实R镜像 **5 passed in 21.63s**，包含CSR轴、负数/nonfinite、物种/ID与reference校验、unknown/候选排名、真实SingleR对照；native score及delta.next与直接调用SingleR的结果按1e-12容差比较通过，乱序细胞轴保持。
- 随后补metadata catalog及零表达/ID版本不匹配分支；最后宿主 **5 passed, 1 skipped in 0.47s**，跳过为缺少Windows R环境的native项。扩展native分支随主任务最终probe再运行；此处不预报其结果。
- 官方参考样本列与标签行114项严格相同的独立R检查通过；`git diff --check`指定科学代码目录无输出。原工具日志与镜像构建日志保留在`script/.runtime/single-cell-batch4/`。

尚未在本子任务宣称：真实PBMC3k/多文库SingleR正式队列验收、独立生物学ground truth、参考对所有疾病/组织适用、容量承诺、生产部署或用户验收。上述公开数据正式验证由主任务复用既有processed数据完成，避免重复基础计算。只生成原有非PDF对象/PNG/Word材料。

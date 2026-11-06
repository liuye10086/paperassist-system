# 第6批：真实方法、版本与资源核查

日期：2026-11-06。范围仅官方文档、源码和原论文研究；本报告未安装/运行算法、未启动服务、未调用云/付费/生成模型、未生成PDF。产品交付仍为Word only。下述兼容性是版本元数据支持，不等同已在本项目R4.4.3实测。

## 结论与推荐顺序

按 Slingshot → GENIE3 → CellChat 实施。前两者固定Bioconductor3.20版本；CellChat固定官方源码SHA。CellChat软件当前GPL-3，但官方CellChatDB包含KEGG来源，不能把软件许可当作上游数据库全部授权。本批优先使用**独立从CC-BY4论文正文编制的3行演示custom LR资源**，真实调用CellChat，明确非官方CellChatDB、非全库。不要因全库授权未明而阻断其他方法或该小资源路径。

## 1. Slingshot

已验证官方Bioc3.20页面：版本2.14.0，Artistic-2.0，R>=4.0，页面对应R4.4。Depends princurve>=2.0.4、TrajectoryUtils；Imports igraph、matrixStats、S4Vectors、SingleCellExperiment、SummarizedExperiment及R标准包。该页提供Windows binary；Linux源码依赖是否完整仍需镜像实测。

建议使用PCA（cells×components）和显式cluster标签：`slingshot(rd, clusterLabels=labels, start.clus=root)`；有确切终点先验时才设置`end.clus`。读取`slingPseudotime()`（cells×lineages，非所属谱系NA）、`slingCurveWeights()`、`slingLineages()`及曲线坐标。保存root/cluster集合、使用维度、随机种子、细胞顺序、版本、参数。不要把NA强填为0，也不要把多条lineage压成唯一生物时间。

PBMC3k/6k可验证根选择、cluster变化、真实调用、谱系输出、图和Word内容；目前没有已确认连续发育谱系，故只标“工程轨迹验证”，不宣称分化方向、发育时间或因果。可以预选相近T细胞亚群以避免跨淋巴/髓系硬连；没有足够cluster时明确拒绝，而不是造轨迹。

来源：[Bioc3.20官方包页](https://bioconductor.org/packages/3.20/bioc/html/slingshot.html)；[作者官方vignette源码](https://github.com/kstreet13/slingshot/blob/master/vignettes/vignette.Rmd)。后者为开发分支说明，实施时应检查2.14.0安装后的正式API。

## 2. GENIE3

已验证Bioc3.20官方镜像：版本1.28.0、GPL>=2；Imports stats、reshape2、dplyr，NeedsCompilation（作者源码）；多核需foreach/doRNG/doParallel，仅验收建议`nCores=1`。作者GitHub master DESCRIPTION仍1.17.1，因此**不要直接install_github替代Bioc3.20锁版**。

输入genes×cells数值表达矩阵，固定gene symbol映射；优先同类细胞内log-normalized表达。`GENIE3(exprMatrix, regulators=tf_symbols, targets=target_symbols, treeMethod="RF", K="sqrt", nTrees=1000, nCores=1)`；验收可明确降到50–100树、有限targets，并报告参数缩减。`getLinkList(weightMat, reportMax=...)`输出TF→target权重。权重是预测重要性，不是p值、结合证据或因果调控。每个target使用所有候选TF，不能先按整个输入HVG丢掉全部TF。

用户TF清单：上传UTF-8 txt/tsv，单列symbol（可扩展resource_id/species/source/license）；去空白去重，与表达genes求交，输出上传/匹配/缺失数及名单，不悄悄把全genes当TF。ENSG→symbol多对一必须记录合并规则。

可接受的明确演示human TF清单（20项，人工选择，**非全量human TF数据库**）：`STAT1, STAT2, IRF1, IRF7, IRF8, SPI1, CEBPB, NFKB1, RELA, JUN, FOS, ETS1, GATA3, TBX21, BCL11B, TCF7, LEF1, RUNX1, PAX5, BCL11A`。命名可用HGNC CC0核对；选择本身为项目工程示例，不得把HGNC命名许可说成HGNC已背书本项目TF功能分类。PBMC中未表达的候选如实剔除。

Lambert humanTFs站点说明1639个known/likely TF，但本次打开页面未找到明确可再分发数据许可；Aerts公开`allTFs_hg38.txt`目录可取得，也未在目录看到独立数据许可，故不作为默认“许可已清晰全库”。将用户自主上传作为正式扩展入口。

来源：[Bioc3.20官方镜像包页](https://bioconductor.statistik.tu-dortmund.de/packages/3.20/bioc/html/GENIE3.html)、[作者官方API源码](https://github.com/aertslab/GENIE3/blob/master/R/GENIE3.R)、[官方vignette](https://github.com/aertslab/GENIE3/blob/master/vignettes/GENIE3.Rmd)、[HGNC CC0](https://www.genenames.org/about/license/)、[Lambert官网](https://humantfs.ccbr.utoronto.ca/)、[Aerts TF目录](https://resources.aertslab.org/cistarget/tf_lists/)。

## 3. CellChat版本、依赖与资源许可

官方jinworks/CellChat此次main SHA：`75253cd0c9e68410e6e721a6d3a0419a1d7e358f`，DESCRIPTION版本2.2.0.9001、R>=3.6、GPL-3，LICENSE确为GPLv3全文。当前README区分v1/v2仓库与SpatialCellChat v3，本批非空间scRNA应固定此v2仓库SHA，不漂移安装新仓库。

Depends dplyr、igraph、ggplot2。Imports future、future.apply、pbapply、irlba、NMF>=0.23.0、ggalluvial、stringr、svglite、Matrix、ggrepel、circlize>=0.4.12、RColorBrewer、cowplot、methods、ComplexHeatmap、RSpectra、Rcpp、reticulate、scales、sna、reshape2、FNN、shape、BiocGenerics、magrittr、patchwork、colorspace、plyr、ggpubr、ggnetwork、BiocNeighbors、plotly、shiny、bslib、collapse；LinkingTo Rcpp/RcppEigen。核心推断无需运行UMAP/Python/交互Shiny，不能因此说所有Imports安装都可省略。R4.4.3满足声明下限，具体igraph等兼容性未实跑证实。

CellChatDB原始论文明确有KEGG来源。KEGG当前官方条款：非学术使用需商业许可，提供服务的学术使用也要求相应服务许可。论文的CC-BY4不自动清除不属于作者权利范围的第三方数据库条款。因此本批不默认分发/商用完整官方数据库；也不简单以`evidence != KEGG`过滤便宣称所有来源干净。此处是资源工程判断，不替代法律意见。

### 推荐可立即实现的开放演示LR路径

只依据Jin等2021原论文**人皮肤Fig7正文**，手工独立整理以下三行：

| interaction_name | ligand | receptor | complex | pathway_name | 来源 |
|---|---|---|---|---|---|
| DEMO_CCL19_CCR7 | CCL19 | CCR7 | 无 | CCL | Fig7d–f正文 |
| DEMO_MIF_CD74_CD44 | MIF | DEMO_CD74_CD44 | CD74 + CD44 | MIF | Fig7d正文 |
| DEMO_CXCL12_CXCR4 | CXCL12 | CXCR4 | 无 | CXCL | Fig7d正文 |

资源id `human-demo-literature-v1`；species human；许可`CC-BY-4.0`；作者Jin et al.；DOI `10.1038/s41467-021-21246-9`；标记“手工整理、结构化和重命名；仅3条文献演示相互作用，非全库/非官方CellChatDB”。保留来源URL、图号和许可URL。该paper明确覆盖所列人基因配对，不把其小鼠Tgfb1示例擅自升格为人类验证。

custom DB按CellChat结构自行构建四表：`interaction`（至少interaction_name/pathway_name/ligand/receptor/agonist/antagonist/co_A_receptor/co_I_receptor/evidence/annotation/interaction_name_2）、`complex`（DEMO_CD74_CD44行，subunit_1=CD74、subunit_2=CD44，额外列空字符串）、`cofactor`（结构合法空表）、`geneInfo`（只包含输入symbol/该3条所需符号，用HGNC CC0命名映射或项目输入映射，不复制官方全库）。未在该小资源描述的cofactor留空，不能宣称生物上不存在。保留复合物各subunit，缺任一subunit必须不计该相互作用。

这条路径真实运行CellChat而不改用简化配对均值算法；图与Word明确显示resource_id、LR范围和缺失情况。3行不保证PBMC显著结果。零值应作为合法原始输出保留，但不足以单独证明第6批CellChat完整验收；按用户追加要求，需补充真实非零和可估计供者统计路径。原Kang实际全零原因与新皮肤补测见后续记录。

完整官方DB已作为研究证据取得，不是本批默认生产资源：`script/.runtime/single-cell-batch6/research/CellChatDB.human.rda`（固定SHA URL和SHA256见download-manifest.json）。这能证明可取得，不能证明所有下游用途已授权。CellPhoneDB-data公开仓库没有显式根LICENSE（此次页面），不可凭其公开性直接认定适合商用。GtoPdb许可ODbL+CC-BY-SA4但当前下载需注册、商业访问另收费，不符合本批无付费直接取得的简化要求，故不优先。

### 最小真实运行API与供者比较

输入原counts先按细胞库大小normalize并log1p，CellChat需归一化表达genes×cells、列名与meta行名严格相等、human symbol。`createCellChat(object=norm, meta=meta, group.by="cell_type")`；设置自建`@DB`；`subsetData` → `identifyOverExpressedGenes` → `identifyOverExpressedInteractions` → `computeCommunProb(type="triMean",raw.use=TRUE,population.size=FALSE,nboot=100,seed.use=...)` → `filterCommunication(min.cells=10)` → `computeCommunProbPathway` → `aggregateNet`；`subsetCommunication`读取LR表。`raw.use=TRUE`指normalized signaling矩阵而非raw counts。源码filterCommunication当前剔除`<=min.cells`组，因此需要每组至少11 cells，不能仅依照注释写成>=10。

Kang8paired_400（任务给定6400 cells、8 donor×2 conditions）：先核对实际meta与原ENSG+symbol/counts，再**16个donor×condition各自建CellChat对象**。同一resource、细胞类型定义、均值方法、LR全集、nboot、seed和过滤规则。不能按condition先池化所有细胞，也不能用CellChat内部bootstrap p值冒充8名供者的条件效应p值。

最小供者层方案：为每个source×target×LR导出16个网络分数；只对双条件source/target均达到预设细胞数且全必需基因可用的供者纳入配对；结构性缺组记NA，不补0。真实可估计但无表达/边时可记0，区分与NA。按供者计算stim−ctrl，报告配对n、8个差值/均值或中位数、方向一致性；如需p值使用供者层精确配对符号翻转（8对至多256次）或明确配对Wilcoxon，跨边BH校正，报告有限样本/大量ties限制。不要将16个网络当16个独立生物重复，也不要将细胞数作为比较n。

正式效应比较可使用不经每样本p阈值硬筛选的原始网络概率，避免检测阈值制造差异；另列内部p值作为单网络证据。选定群体集合和细胞数门槛在看条件效应前固定。因400 cells/样本和稀有群体易不足，最小验收先限定2–4个充足大类，缺组/零边/少配对均明确展示。给出描述性结果不等于已证明真实通讯或疾病机制。

来源：[官方仓库](https://github.com/jinworks/CellChat)、[固定DESCRIPTION](https://raw.githubusercontent.com/jinworks/CellChat/75253cd0c9e68410e6e721a6d3a0419a1d7e358f/DESCRIPTION)、[固定LICENSE](https://raw.githubusercontent.com/jinworks/CellChat/75253cd0c9e68410e6e721a6d3a0419a1d7e358f/LICENSE)、[官方教程源码](https://github.com/jinworks/CellChat/blob/75253cd0c9e68410e6e721a6d3a0419a1d7e358f/tutorial/CellChat-vignette.Rmd)、[官方模型源码](https://github.com/jinworks/CellChat/blob/75253cd0c9e68410e6e721a6d3a0419a1d7e358f/R/modeling.R)、[Jin2021原论文及CC-BY4](https://pmc.ncbi.nlm.nih.gov/articles/PMC7889871/)、[KEGG用途条款](https://www.kegg.jp/kegg/legal.html)、[CellPhoneDB-data](https://github.com/ventolab/CellphoneDB-data)、[GtoPdb许可](https://www.guidetopharmacology.org/about.jsp)、[GtoPdb下载登录及商业访问声明](https://www.guidetopharmacology.org/download.jsp)。

## 已验证与未验证边界

已浏览官方页面和源码，固定下载CellChat human DB并记录hash；原源码/元数据保存在research目录。Bioc3.20主站GENIE3页面抓取失败，改用Bioconductor官方镜像包页核实1.28.0；两个Bioc源码tar尝试因本机证书校验失败未取得，未关闭TLS校验。本报告未证明本地R依赖可安装、算法数值正确、PBMC存在连续谱系或演示LR有非零边。下一步需镜像实际安装及小规模真实方法调用，分别记录工程验收、数值核对和生物解释边界。

## 小规模资源落地核对

已按主代理授权将上述3行独立演示资源写入`backend/app/adapters/single_cell_r/topics_resource.json`；包括metadata、interactions、complexes、cofactors、gene_symbols。canonical payload SHA256：`9f7e7250fe0603615dfabb0c501c4ef6b5ea9f28734b3e874fb5df6723e31e19`。已核对JSON可解析、3个唯一interaction、复合物subunit全部可在gene_symbols匹配、所有ligand/receptor引用有效和hash一致；尚未运行CellChat，不能称算法验收通过。

## 已有输入的确定性工程选择（不重算分析）

`script/.runtime/single-cell-batch6/genie3-selection.json`固定20个TF和200个targets（既有CD4 pseudobulk base_mean降序的180个非TF唯一symbol + 20TF，ENSG字典序打破同值；不按差异显著性/效应选择）。20TF均在processed-kept features并可与原Kang TSV精确映射，CD4保留pseudobulk计数均非零；PAX5仅2 counts、BCL11A仅4 counts，属于低表达演示候选，不能据此称稳定调控证据。20个TF不是完整TF目录；高表达targets有较多核糖体基因，选择代表工程规模控制而非生物目标优选。

CD4 annotation集合与metadata作者CD4标签逐cell_id完全相等，共2584cells。CellChat建议CD4_T/CD14_Mono/B：16 donor×condition分层最低细胞数分别78/55/23，均>10。工程轨迹可用CD4内部既有processed cluster2/3/7（2314/202/37cells），以最大cluster2作为明确的工程根，生物根未验证；这不代表连续发育谱系成立。选择JSON包含全标签16分层计数、cluster分布、全部source SHA256。仅读取现有结果/计数表，没有重算DE或基础矩阵。


## 最终实现与真实补测状态（2026-11-06）

上文为调研阶段建议；最终实际实现以保存的topic_methods和R适配器为准。CellChat调用createCellChat、subsetData、computeCommunProb（显式LR.use为原3条、triMean、population.size=FALSE、100boot）、filterCommunication；不以隐式差异表达筛选删去预先声明的LR，不以只含显著边的导出代替完整结果。供者层采用paired t（非配对为Welch t）及完整可计算家族BH，非Wilcoxon或符号置换；无可估计方差保留NA。该选择已通过合成统计测试，真实非退化统计由本次皮肤数据补测。

Kang实际16单位、432条网络评分全0：CCL19未检出，MIF/CXCL12在该有界子集各分组triMean均0；27条供者比较为no_estimable_variance。此结果只验证零值/不可计算路径，不能作为完整CellChat验收。

新增[Fiskin2026原文](https://www.nature.com/articles/s41467-026-69587-7)对应[CELLxGENE公开图谱](https://cellxgene.cziscience.com/collections/5e143645-177c-45b6-952d-48770e29a54b)，按官方公开数据政策CC-BY4使用。固定H5AD版本e046218f-6a66-46f9-a91c-7f26b4ee00c2，SHA256 53754ede1febf43d6df0e727b9ca5332b2534aa98f585a3f58fa99be6a4e25fe。280518×32118的raw.X全部421138573个存储值已逐块验证有限、非负整数；原参考GRCh38与GEO processing相符。

使用全部10对AD供者，原作者Cell_type=Fibroblasts/DC/T/NK，每donor×condition×label按原cell ID固定SHA256排序取前100，不足则全取（唯一85的层），共5985细胞、全部32118基因。未按LR表达/方向/P值选细胞；原channel、ind_sample与标签保留。GEO title/file/channel与所有280518行供者/条件交叉核对无差异；多channel不增加供者数。正式导入CSR的7738441个非零计数及细胞/基因轴与子集精确一致。14项原gene_name缺失在导出中为字符串None，ENSG ID/counts保留且不匹配LR资源符号；未声称这些是实际基因名。

原官方CellChat皮肤教程GSE147424补充矩阵是归一化log表达，未将其伪装成counts。新图谱的公开作者标签也不是本项目独立生物学身份验证，T/NK为混合粗群。本轮仍是3LR有界真实工程验证，不是全图谱/全CellChatDB生物学结论。完整来源、固定选择与数值核对在script/.runtime/single-cell-batch6/retest-skin/。

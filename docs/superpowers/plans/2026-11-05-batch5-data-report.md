# 第5批真实供者矩阵与富集资源调研

日期：2026-11-05。范围：只读源码、公开资料核实、下载与确定性输入材料；未实施统计引擎、未跑DE/富集、未提交代码。

## 决策

首选 **Kang et al. 2018 / GSE96583 batch2**：8名真实SLE供者，每人ctrl/stim配对，原始整数UMI counts与原作者细胞类型标签齐备。使用8 pairs，绝不将单供者细胞或技术文库视为生物重复。公开GEO数据可按官方开放使用说明用于本地工具验证；其权利依据按GEO原文记录，不声称原数据CC0/MIT。`muscData`包的MIT属于包软件及文档，不扩大为原数据许可。

本地目录：`script/.runtime/single-cell-batch5/`。确定性子集目录：`kang8paired_400/`，每donor×condition取400个原singlet且cell标签非NA细胞，共6400 cells、35635 genes；基因轴直接用原始ENSEMBL列，SYMBOL保留，不猜ID、不按差异结果挑细胞。SHA256排序前缀固定`PaperAssist-batch5-v1|donor|condition|barcode`，按原矩阵顺序恢复输出；不按celltype均衡抽取以免人为固定组成。实际nnz、counts范围、文件哈希见该目录`provenance.json`。该子集仅原矩阵行/列选择，不归一化、不取整污染校正数据。

## 原始来源与获取

- 原论文：[Kang et al., Multiplexed droplet single-cell RNA-sequencing using natural genetic variation](https://pmc.ncbi.nlm.nih.gov/articles/PMC5784859/)，DOI `10.1038/nbt.4042`。论文说明自然遗传变异经demuxlet确定供者与multiplet；8人各自PBMC以IFN-beta刺激或不刺激6h后各形成一个pool。论文出版年2018，muscData旧源码注释误写2019，引用应沿用论文真实2018。
- [原作者GEO记录](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE96583)；网页本次有reCAPTCHA，已通过官方FTP成功下载SOFT，记录`Genome_build: hg19`，batch2使用Cell Ranger 1.2。
- [GEO FTP目录](https://ftp.ncbi.nlm.nih.gov/geo/series/GSE96nnn/GSE96583/suppl/)，其`filelist.txt`已保存。
- [原counts压缩包](https://ftp.ncbi.nlm.nih.gov/geo/series/GSE96nnn/GSE96583/suppl/GSE96583_RAW.tar)：**76,195,840 bytes**，已下载。只提取batch2两矩阵及各自barcodes，没有重做FASTQ。
- `GSM2560248_2.1.mtx.gz`：28,545,918 bytes；35635×14619；8,732,747条非零值。
- `GSM2560249_2.2.mtx.gz`：29,050,932 bytes；35635×14446；8,838,098条非零值。
- [原细胞metadata](https://ftp.ncbi.nlm.nih.gov/geo/series/GSE96nnn/GSE96583/suppl/GSE96583_batch2.total.tsne.df.tsv.gz)，已下载，29,065行。注意TSV首列为**未在header命名的barcode行名**，需要显式补`metadata_barcode`，否则所有字段错移一列。
- [原基因metadata](https://ftp.ncbi.nlm.nih.gov/geo/series/GSE96nnn/GSE96583/suppl/GSE96583_batch2.genes.tsv.gz)，已下载，无header，两列`ENSEMBL`、`SYMBOL`；35635条真实ENSEMBL，子集准备时检查ID唯一。
- [GEO SOFT](https://ftp.ncbi.nlm.nih.gov/geo/series/GSE96nnn/GSE96583/soft/GSE96583_family.soft.gz)，已下载，保留研究设计和处理软件说明。

原MTX header声明`real general`，不能仅据header称原始整数；子集准备遍历原两矩阵全部值，检查非负且数值为整数，再按原值写integer MatrixMarket。轴对应采用原作者制备源码的ctrl后接stim顺序，并逐位置验证barcode：ctrl完全一致；stim共313个metadata barcode恰为跨capture重复的原barcode追加字符1，其他均一致。输出同时保留metadata_barcode和original_barcode；不按改写后的meta条码强行集合对齐。

## 元数据身份与标签

原字段：`ind`真实匿名供者；`stim`原条件ctrl/stim；`cluster`原聚类；`cell`原作者细胞类型；`multiplets`原demuxlet标签；`tsne1/tsne2`原降维坐标。子集完整保留这些原字段，增加`cell_id=capture_id:original_barcode`、`donor_id=ind`、`paired_id=ind`、`condition=stim`、真实`capture_id`（ctrl=GSM2560248，stim=GSM2560249），避免跨capture同barcode冲突。

原作者标签8类：CD4 T cells、CD8 T cells、B cells、NK cells、CD14+ Monocytes、FCGR3A+ Monocytes、Dendritic cells、Megakaryocytes；原标签不能写成此项目重新生物学验证的真值。本次不重跑SingleR，不以预测替代已有原作者标签。

原metadata：24679 singlets、3169 doublets、1217 ambs；其中singlet且cell非NA有24673 cells。真实donor IDs：101、1015、1016、1039、107、1244、1256、1488。每人ctrl/stim均有461–2738可用细胞，满足400的确定性抽取。

[muscData官方vignette](https://bioconductor.org/packages/3.23/data/experiment/vignettes/muscData/inst/doc/muscData.html)提供相同数据SCE入口`Kang18_8vs8()` / `ExperimentHub()[["EH2259"]]`，公开其35635×29065维度、counts及metadata。更直接的[制备源码](https://raw.githubusercontent.com/HelenaLC/muscData/master/inst/scripts/make-data_Kang18.R)明确来自上述两MTX和metadata，支持原counts/轴绑定来源。已保存`muscData_1.26.0.tar.gz`供离线审计，不要求安装整个包。

**许可边界：** [GEO Disclaimer](https://www.ncbi.nlm.nih.gov/geo/info/disclaimer.html)说明NCBI不限制GEO数据使用或分发，同时明确提交者可能持有版权等权利，NCBI不能代授无限制许可；[GEO FAQ](https://www.ncbi.nlm.nih.gov/geo/info/faq.html)明确任何人可不登录访问、下载公共数据以及公开后的reuse。此次未发现GSE96583独有的附加使用限制。不能把公开可访问写成CC0；若未来要打包向第三方再分发，仍应随原始来源说明保留权利边界。此结论不是法律保证。

## 统计适用性与限制

1. paired pseudobulk设计可用`~ donor + condition`，按同celltype、donor×condition聚合原counts；真实n=8 pairs。各celltype需重新验证每对供者的细胞数/受检基因数，不能因总cells足够忽略稀有类缺失。
2. 两条件各来自一个pool/capture，**capture与condition完全混杂**。不可同时加入capture和condition而声称已解开混杂；不得假装8个donor×condition是16个独立捕获文库。结果是此队列的条件关联与工具验证，不能排除处理池技术差异、不能当疾病因果或跨队列泛化证据。
3. propeller分子是供者级该type细胞数，分母是该供者该条件全部纳入细胞。6400细胞子集是均匀抽样后的组成，必须披露抽样；不预期一定显著，原论文报告IFN-beta未明显改变细胞组成。配对设计/稀有type和当前引擎支持需实际实现检验。
4. 3pairs/每组3donor仅工程门槛；8pairs也非功效保证。本次未跑任何统计模型，不承诺显著DE/ORA/GSEA。
5. PBMC3k/6k此前同供者材料只能描述，不用于这次合格重复推断。

## ORA/GSEA基因集

采用Reactome**官方数据CC0**：[License](https://reactome.org/license)的Data条款明确数据库及派生数据CC0；软件/插图分别为其他许可，不混写。

首选直接ENSEMBL namespace：

- [官方下载页](https://reactome.org/download-data)
- 最低层路径映射：`https://reactome.org/download/current/Ensembl2Reactome.txt`
- 所有层级映射：`https://reactome.org/download/current/Ensembl2Reactome_All_Levels.txt`，本次HEAD返回200，Last-Modified `2026-10-18 04:28:30 GMT`，服务器未给Content-Length，**尚未下载/不编造大小**。
- 文件按tab读取，保留原gene ID、稳定pathway ID、名称/URL/evidence/species；只取`Homo sapiens`，按稳定pathway ID收集基因并去重。与counts实际ENSEMBL直接相交；不要把human symbol GMT当ENSEMBL。绑定下载日期、完整SHA256和实际release；`current`会变化，未来优先冻结官方季度[Zenodo archive](https://reactome.org/download-data)中的固定发布资源。
- ORA背景必须为该celltype该比较中实际受检、通过预先过滤的基因，而非全35635或全Reactome。GSEA排名用同一合格pseudobulk全部可排序统计量、保留方向，不能只交显著基因。空结果允许；重叠不足应显示原因。

已下载官方symbol资源 [ReactomePathways.gmt.zip](https://reactome.org/download/current/ReactomePathways.gmt.zip)：300128 bytes，Last-Modified `2026-10-19 18:46:22 GMT`，内容`ReactomePathways.gmt`的第1列路径名、第2列R-HSA稳定ID、第3列起是SYMBOL（已实际查看BANF1/HMGA1/LIG4等）。本输入优先用ENSEMBL映射；若复用symbol GMT，必须根据**此原gene metadata的ENSEMBL–SYMBOL**显式映射、报告一对多/无法映射，绝不外推猜ID。此备选GMT已下载不代表富集已运行。

## 备选及下载材料注意

可选清晰CC BY 4.0的小鼠Crowell19_4vs4（4Vehicle/4LPS，8只独立雄鼠）原始[Figshare API](https://api.figshare.com/v2/articles/8976473)元数据已保存`Crowell19_figshare_metadata.json`，内含明确license、每样本ZIP和大小；但不替代Kang首选。本次额外下载其官方ExperimentHub对象187725556 bytes，供保留参考，未用于统计。

Hub资源**不要将EH号直接当/fetch数字**：sqlite`resources`与`rdatapaths`映射不同；EH3297对应rdatapaths id3313。`/fetch/3297`实际返回其他bulk表达对象（20202×11），已重命名`unrelated_resource_fetch3297.rds`并明确排除。正确对象路径由官方metadata SQLite解析：`https://mghp.osn.xsede.org/bir190004-bucket01/ExperimentHub/muscData/Crowell19_4vs4.Rda`。SQLite文件已保存。没有把错误对象作为成功数据证据；不删除这些下载材料。

本次仅下载/检查原数据与准备确定性输入；未跑基础单细胞流水线、propeller、PyDESeq2、ORA/GSEA或Word验收；这些均由后续真实任务另行报告。


### 输入准备补充

原metadata的stim段有313个barcode因与ctrl相同而追加字符1（原`AAACGCTGTGTCAG-1`对应metadata `AAACGCTGTGTCAG-11`）。已验证每一处差异都恰符合跨capture重复，其他逐位置一致；保留两种条码，绝不将-11误当原10x条码。确定性抽样hash使用**原barcodes.tsv的original_barcode**。输出metadata同时保存真实capture_id、cell_id及所有原字段。该识别来自实际文件核对及原作者按顺序构造SCE的公开源码。

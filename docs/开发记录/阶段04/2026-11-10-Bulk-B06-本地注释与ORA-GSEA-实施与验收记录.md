# Bulk RNA-seq B06 本地注释与 ORA/GSEA 实施与验收记录

2026-11-10 · `feat/bulk-rna-downstream` · 起始基线 `b520f776c8e5baa954c9122ff3fd6add088f9700`

**B06 已于 2026-11-10 由用户验收通过，状态为 `user_accepted`。** B07 待用户另行确认后启动。

## 1. 实现与统计口径

- 从 B04 已确认的 `shared_wald_v1` 固定差异结果进入。ORA 继承 B05 应用的比较、方向、q 口径和效应阈值。GSEA 固定使用该比较的全部有效有符号 Wald 统计量，页面筛选和 Top N 与排名无关。
- 固定结果已有物种时直接显示。缺失时，从物种下拉框选择并记录证据，原结果保持独立版本。离线资源导入也提供物种下拉框。兼容性预检检查物种、命名空间、映射方向和声明的参考版本，并显示未声明组装版本的稳定 ID 资源。
- ORA 以本比较完整受检基因为背景。对每个 collection 使用同一映射规则，将背景和前景与其全部基因交集后再按集合大小筛选。超几何右尾使用 `N/n/K/k`，BH 按比较、方向和 collection 分族。用户显式选择时可合并 collection 校正，零命中且符合大小条件的条目仍进入检验族。
- GSEA 复用锁定的 GSEApy `1.3.1`。按 Wald 降序、稳定 ID 升序冻结完整排名。可计算且通过比较质量状态检查的有限分数进入排名。缺失、Cook 过滤等不可计算行、歧义与映射冲突在审计中有独立原因。身份匹配的资源外基因留在排名中作为未命中。置换次数、seed、权重、并列和资源版本均保存，FDR 来自联合置换零分布。
- 结果区分有显著条目、已计算但无显著条目及不适用。空前景、有效映射不足和无合格集合有明确原因。固定富集表、完整排名、leading edge、曲线数据、原始 ID 映射与排除审计可下载。点图、条图和单条 GSEA 曲线读取已发布成员，Top N 按所用调整指标与稳定 term ID 排序。
- 发布前从固定来源对账映射行、ORA 检验族、概率与派生比率，以及 GSEA 排名、集合成员、ES 与 leading edge。发布校验和重绘均复用固定统计和置换输出。

## 2. 本地资源

| 资源 | 固定版本、来源与已验证内容 |
|---|---|
| Reactome 人类 Ensembl 基因集 | v98，2026-10-27 发布。沿用 2026-11-05 快照，版本标识 `download-2026-11-05-sha256-dc6ff6afcbfc`。官方 v98 原映射 SHA-256 为 `3f6ed306adf9e87716644b12d2dfbf425b79d2e7ea3d8749181214930b132616`。筛人类 ENSG，保留 IEA/TAS，去重后重新生成的 GMT 与本机既有文件逐字节一致。GMT SHA-256 为 `dc6ff6afcbfc15f8ecae02a94af45847b4487798ee83a0e9a66507196ca55df2`。2,843 条通路、13,193 个基因、160,436 条成员关系。资源记录 CC0，提供基因稳定 ID，无组装版本声明。[v98 归档](https://doi.org/10.5281/zenodo.24067822) · [原映射](https://reactome.org/download/98/Ensembl2Reactome_All_Levels.txt) · [许可](https://reactome.org/license) |
| 人类 GO OBO/GAF | 固定 EBI GOEX `2026-06-16` 快照，OBO/GAF 标头均为 `2026-06-15`。GAF 保留人类 UniProtKB 注释，沿用 OBO/GAF 导入器排除 NOT、过时及根术语，按 `is_a`、`part_of` 传播。38,242 个本体术语中 20,992 个有成员，19,738 个 UniProtKB accession 和 1,456,475 条传播后成员关系。[GO 使用与许可](https://geneontology.org/page/use-and-license/) |
| Ensembl → UniProtKB 显式映射 | 使用同一 GOEX 人类 GPI 中显式交叉引用。59,617 条关系经过归一化后有 10,449 个可用源 ID、9,078 个目标 ID、11,956 个歧义源 ID 和 816 个多对一目标。以版本化 `id_mapping` 注册，逐行保留冲突和排除审计。[UniProt 数据与支持](https://www.uniprot.org/api-documentation/support-data) |

资源的原始与派生文件哈希、筛选参数、取得日期和运行收据在本机 `script/.runtime/bulk-b06-validation/resources/`。其中 `reactome-b06-provenance.json`、`reactome-upstream-verification.json`、`ebi-goex-2026-06-16/go-b06-provenance.json` 和 `worker-import-verification.json` 可供复核。

## 3. 离线实算与回归

固定环境沿用原容器与依赖锁。B06 任务使用独立的离线富集能力校验，探针实际运行资源导入、ORA、GSEA 和曲线重绘，并验证隔离阻断网络、未授权文件、fork 和子进程。最终 worker 代码摘要为 `3be853504ddedfb1ffa10e5b6b8d9d3588bf32985023ba81a49de7af64486eba`。隔离探针峰值 RSS 为 307,008 KiB。

- 公开 `airway` 直接离线实算复用 B04 固定差异表。Reactome 双向 ORA 每个比较 1,323 条，双向阈值下合计 28 条显著。正向完整 GSEA 使用 22,187 个排名、1,000 次置换和 seed 0，得到 1,313 条，其中 16 条原生 FDR ≤ 0.05。该次直跑耗时 82.37 秒，峰值 RSS 1,717,680 KiB。
- GO 与 GPI 映射直接离线实算覆盖正向上调。有效背景 5,430 个，前景 199 个，2,789 条检验项中 825 条零命中，3 条 BH ≤ 0.05。逐条独立超几何与 BH 最大相对误差分别为 `2.44e-15` 和 `2.00e-15`。
- 后端 PostgreSQL/API/合同等定向回归 59 项通过，随后更新发布校验并补跑 39 项定向检查。固定 Linux 引擎 30 项数值测试通过，含 11 项新增 Bulk 场景。既有样本夹具出现 4 条 NumPy 警告。另有 20 项渲染回归通过。
- 前端 B06 和相关路径定向 31 项通过，`npm run build` 通过，有 Vite 产物体积提示。默认 5 秒时限的两轮全量出现既有页面集成用例超时。使用 `npm run test -- --maxWorkers=4 --testTimeout=12000` 完成全量复跑，428 个文件、3,392 项全部通过，耗时 329.82 秒，含 B06 8 项。原始及复跑日志保留在本轮证据目录。

## 4. 实际 API、worker 和 Edge 验收

沿用 B04 隔离 PostgreSQL 项目、公开 `airway` 固定差异版本 `b8c84019-c8fe-5afa-b052-b303eddaa285` 和专用 RabbitMQ/Docker worker。差异表包含两个方向共 128,204 行，SHA-256 为 `d270734ea77b38620269eeb538b26979c09a3316de4d1c8aa9db9f94a588f74d`。Edge 使用 `127.0.0.1:5175`，本轮正式验收 API 使用 `127.0.0.1:8003`。

Edge 验证缺失物种时下拉框默认留空，选择人类后固定 taxon `9606` 及来源依据。离线资源导入的物种同样通过下拉框选择。预检显示 Ensembl 基因命名空间、固定 release 和稳定 ID 资源未声明组装版本。公开数据的物种以数据包描述为依据。[Bioconductor airway](https://www.bioconductor.org/packages/release/data/experiment/html/airway.html)

| 正式发布 | 任务 ID | 版本 ID |
|---|---|---|
| Reactome v98 人类基因集 | `936c3d50-09d9-5ec5-a6ce-10fcada8409e` | `05ce71ce-6add-5d1d-beab-7ac0dd78a867` |
| GO OBO/GAF 人类基因集 | `92930fbc-5e04-5d48-b5fb-6b51a7cce44a` | `4a820dce-9008-51be-b902-e86fe54f51e8` |
| GO Ensembl → UniProtKB 映射 | `d1bc54d6-0b57-5b0b-8c01-742fb2fbf48e` | `214d0c7a-0a7d-5d4c-be4d-43da93b840b8` |
| Reactome 正向上调 ORA | `9ad67c76-feae-57b2-a2d0-b73ad307181a` | `b23f3c84-4bed-57fd-bab0-003768f9dce9` |
| Reactome 正向完整排名 GSEA | `3e4a2bcf-6473-5dc7-ba32-a5c13a2ed5c9` | `00f819ff-14c7-59b0-a4db-1a9ed57f41e6` |
| ORA Top 12 点图 | `a7905bbe-4b35-5c00-9823-19b4692263f7` | `357e55c4-5643-562b-aa2a-fd5ab9561271` |
| Reactome 空前景 ORA | `cf7f5331-c129-5146-ac2a-c4212a8fb8dc` | `d94f89c5-df5e-5520-ab11-ceea9b8e205a` |
| `R-HSA-109581` 固定 GSEA 曲线 | `97daa36a-0ee4-5fae-9b85-a0a3f294b86f` | `42db6a3c-8cda-5de0-b7b4-8dd07efc014b` |

- 正向 `Dex_vs_Untreated` 上调 ORA 使用比较内 q ≤ 0.05 和 ｜MLE log2FC｜≥ 1。原始受检背景 22,298 个基因，含 111 个不可计算行。原始前景 536 个基因。取 Reactome 交集后 N = 8,897、n = 289。集合大小 15–500，1,323 条检验项中 637 条零命中，2 条 BH ≤ 0.05。独立公式逐条核对超几何与 BH，最大相对误差分别为 `1.89e-15` 和 `1.55e-15`。
- 从匹配 0 行的 DEG 页面提交同一比较的 GSEA。实际结果含 22,187 个有效排名，其中 13,358 个资源外基因保留在排序中。独立核对 1,313 条通路的 hit、ES 和 leading edge，880 条正向、433 条负向，ES 最大绝对误差 `1.05e-15`。16 条原生 FDR ≤ 0.05。另有 1,299 条的原生 FDR 与对名义 p 另算的 BH 不同。
- 同一零 DEG 筛选的 ORA 保存背景 N = 8,897、前景 n = 0，状态为 `not_applicable/empty_foreground`，完整推断表为 0 行。
- 点图从 Edge 生成 Top 12，条图在断网的同一固定 worker 镜像中读取相同已发布 ORA 表。两图的 Top 12 与固定 q/term ID 顺序一致，完整图数据只在样式字段有差异。两图均生成 PNG、SVG、TIFF，收据记录 `analysis_recomputed=false`。
- Edge 从已发布的 GSEA 结果选中 `R-HSA-109581` 绘制曲线，发布 PNG、SVG、TIFF 及完整图数据。独立核对 22,187 个秩位置，曲线最大绝对误差 `1.46e-16`。

| Edge 下载文件 | 字节数 | SHA-256 |
|---|---:|---|
| `enrichment_results.tsv` | 836,915 | `3d467adf26c77ce3d8d1e0714ef3fb6e8a2108d6b38bdedda87f083f3439e279` |
| `gsea_ranking.tsv` | 2,706,178 | `ebb4677f6cbf8784ac4578e01df4d4b33687395f317125fa97b1c6f8c85fef69` |
| `gsea_curves.json` | 1,325,488 | `312ba29d88ce707ddc6162b2ee0be42ca8117f8284fb7f44c4df7e162ffd9d7e` |
| `bio-insight-reproduction.zip` | 152,395,980 | `8aa7937ee0bdc9ca2be7c38f4f4fe4d1d80871321d2dd91c2991d01c0ba86b25` |

三份结果下载与已发布成员字节一致。复现包校验了 141 个清单成员、冻结 GSEA 配方和离线运行收据。

本机验收证据集中在 `script/.runtime/bulk-b06-validation/`。数值与版本绑定见 `independent-result-verification.json`，下载对账见 `edge-download-integrity.json`，物种选择和已发布曲线分别见 `b06-edge-species.jpg` 和 `b06-edge-gsea-curve.jpg`。前端最终全量见 `frontend-full-suite-timed.log`，固定环境见 `worker-acceptance-final.log`。

## 5. 验收边界

- 实际端到端富集使用公开人类 `airway` 固定结果。GO 实算覆盖显式 ID 映射后的 ORA。其他物种、真实用户数据、GO GSEA 及 60,000 × 50 矩阵容量与性能待验证。
- 未声明组装版本的稳定 ID 资源按物种、命名空间和实测覆盖记录兼容情况。独立 R DESeq2 全量对照仍归 B08。
- 本轮复现包通过成员与环境校验。下载包内的 1,000 次 GSEA 置换属于复算选项，本轮实算证据见第 3、4 节。

## 6. 用户验收登记

2026-11-10 用户确认如下。

> B06我已验收，通过，更新相关文档和验收记录，等我确认后再进入B07。

本次登记沿用公开 `airway` 富集实算、独立数值对账、Edge 发布与下载、离线运行和前端全量复跑的既有证据。待验证事项见第 5 节。

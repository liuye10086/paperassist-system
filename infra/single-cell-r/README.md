# 单细胞质量模型运行环境

本镜像在已有应用 Worker 上补充 R 与 rpy2，供单细胞矩阵的 scDblFinder、decontX 和 Harmony 使用。它不是 FASTQ 云服务，不需要阿里云账号，也不改变已有任务队列。只产出科学结果、PNG 和 Word，不安装 PDF 生成流程。

## 构建和验证

在仓库根目录执行：

```powershell
docker build -f infra/single-cell-r/Dockerfile -t paperassist-single-cell-worker:local .
backend/.venv/Scripts/python.exe script/dev/single_cell_runtime.py probe --image paperassist-single-cell-worker:local --qc-tools
backend/.venv/Scripts/python.exe script/dev/single_cell_runtime.py verify --image paperassist-single-cell-worker:local --qc-tools
# 第3批：加入Harmony/协变量验证，保留独立运行材料
backend/.venv/Scripts/python.exe script/dev/single_cell_runtime.py probe --image paperassist-single-cell-worker:local --integration-tools
backend/.venv/Scripts/python.exe script/dev/single_cell_runtime.py verify --image paperassist-single-cell-worker:local --integration-tools
```

默认基底是本机保留的 `paperassist-client-b06-w1-worker:local`；其他环境可通过 `--build-arg WORKER_IMAGE=...` 指定具备现有 `/opt/paperassist-bio` 数值环境的应用 Worker。构建需要访问 conda-forge、Bioconda 和 PyPI；任务计算不需要联网。`verify` 只使用配置中明确的本地 `paperassist_system_test` 数据库与独立测试 schema。

`environment.yml` 安装 R 4.4、scDblFinder 1.20.2、decontX 1.4.0；`compatibility.txt` 固定 CPU xgboost 2.1.4、RcppParallel 5.1.9、R 4.4 和 Harmony 1.2.3。实际 R 包版本 xgboost 为 **2.1.4.1**，与 Conda 包名中的版本不同。rpy2 使用 3.5.17 ABI 模式。构建检查三种 R 工具实际加载，并运行 `pip check`；安装成功不等于分析已验证。第3批环境实际构建通过，日志保留在`script/.runtime/single-cell-batch3/image-build.log`，后续科学/公开数据验证状态见实施记录。

首次实测发现新版 RcppParallel 6.2.1 与 rstan 2.32.7 的 TBB 符号不兼容；降至 5.1.9 后加载通过。scDblFinder 1.20.2 早于 xgboost 3.x 接口变更，不能仅按依赖解析器选择最新版。依据：[scDblFinder 上游说明](https://github.com/plger/scDblFinder)、[RcppParallel 变更记录](https://github.com/RcppCore/RcppParallel/blob/master/NEWS.md)。

安装后的完整 R 包清单位于镜像 `/opt/paperassist-single-cell-r/explicit-spec.txt`。验证入口将清单摘要和实际 R 包版本计入既有环境摘要，并执行真实原工具对照与隔离 Worker 测试；全部通过才生成原有格式的运行回执。第2批材料保存在 `script/.runtime/single-cell-batch2/`，第3批使用`script/.runtime/single-cell-batch3/`；前两批证据与结果保留。

## 执行及科学边界

- 固定 R 脚本在读取用户矩阵之前预热；进入原有沙箱后直接交换稀疏数组，cells × genes CSR 映射为 genes × cells `dgCMatrix`。保持显式细胞/基因顺序，检查整数精度，不建立稠密交换文件。
- 按原始捕获文库分别运行，固定随机种子，串行计算。固定前缀预载所需C++/OpenSSL库以匹配实际R依赖；通过 [cli 上游支持的 CLI_NO_THREAD](https://github.com/r-lib/cli/blob/main/src/thread.c) 关闭进度计时线程，仍检查进程实际只有一个线程。仅增加固定 R 安装目录的只读访问与本次 R scratch 目录的读写访问；不开放 fork、exec 或网络。
- scDblFinder 保存评分、预测与实际排除。可选预期双细胞比例；留空使用工具估计，这不能替代建库信息和实验验证。方法及适用条件见 [scDblFinder 1.20 文档](https://bioconductor.posit.co/packages/3.20/bioc/vignettes/scDblFinder/inst/doc/scDblFinder.html)。
- decontX 使用每个文库的群体结构估计污染。缺乏模型条件时记录不可计算；失败或部分成功保留原因与日志。仅全部初步 QC 文库成功时输出完整浮点 `decontx_counts`，再按最终细胞筛选对齐；原始整数 counts 和现有下游输入保持不变。方法见 [decontX 1.4 文档](https://bioconductor.posit.co/packages/3.20/bioc/vignettes/decontX/inst/doc/decontX.html)。
- PBMC3k实测超过原2GiB RSS与3GiB地址空间边界后，仅启用R工具的单细胞任务采用RSS4GiB/AS5GiB，测试及验收Worker容器5GiB；基础/空间任务仍为原边界。4GiB是计算进程的驻留内存上限；额外空间用于虚拟内存映射和Worker应用进程开销。每个模型结果复制后释放R临时对象。细胞/矩阵尺寸估算不包括 R 模型的全部内存开销；公开矩阵测得的峰值不等于服务器容量承诺。

- 双文库增加浮点校正层后，实际结果总量约522MiB，触及原512MiB上限；启用R模型时结果总量上限采用1GiB，单文件上限仍为256MiB。基础/空间任务结果总量保持512MiB。这是磁盘结果大小限制，与4GiB计算内存分别计算。

当前验证状态、真实矩阵结果和用户验收情况以[七批实施记录](../../docs/开发记录/阶段04/2026-11-05-单细胞七批实施记录.md)为准。官方方法支持、代码接通、原工具数值对照、公开数据运行和生物学验证分别记录。

## 第5批：真实 propeller 组成检验

`Dockerfile.propeller` 叠加保留的 `paperassist-single-cell-worker:b4-ready`，只安装官方 Bioconductor 3.20 的 speckle 1.6.0（GPL-3，源包 SHA256 固定），并在 insights 解释器添加固定 rpy2 3.5.17 及其依赖。原有 Python 包版本全部保持，R 为 4.4.3 / limma 3.62.1 / statmod 1.5.2。

```powershell
docker build -f infra/single-cell-r/Dockerfile.propeller -t paperassist-single-cell-worker:b5-propeller .
```

组成 Worker 使用 `initialize_propeller(scratch)`，只预热 speckle 所需工具，不调用 scDblFinder、decontX、Harmony 或 SingleR 的计算预热。ABI bootstrap、固定桥接/decoder 与 R 脚本均在隔离前加载；用户矩阵在隔离后才读取。R 扩充原生 BLAS 清单，因此运行探针和 Worker 必须一致预载后再计算环境身份。固定 R 前缀只读、attempt scratch 读写沿用现有 R 边界，网络和 fork 保持禁止。

`get_bridge().propeller(counts,sample_ids,label_ids,conditions,donors,batches,mode,transform='asin',batch_adjustment=False,numerator=...,denominator=...)` 使用 samples × labels 非负整数 counts，最多 20k 总细胞；样本为已合并技术文库的 donor × condition 单位。默认显式 asin，亦支持原工具的 logit（0.5 伪计数），不依赖上游存在文档差异的默认 transform。原生 `getTransformedProps` 保持 factor 轴顺序；`propeller.ttest` 使用无截距的双组设计，配对加 donor，批次可加 batch；contrast 为 numerator − denominator。工具返回的 PropMean / PropRatio 是原始组比例均值及其比值，即使检验设计包含协变量，也不能称为协变量调整后的比例。

单类别无比例变异时保留分母、均值及明确 `not_computable`，P/FDR 为 null；从经验贝叶斯受检集合中排除该类别。全无变异、完全混杂、秩不足或无残差自由度均不制造 P 值。非配对每组至少三个独立 donor，配对至少三对；这是工程门槛而非统计功效承诺。完整接口、原工具数值对照及内存证据见[第5批 R 报告](../../docs/superpowers/plans/2026-11-05-batch5-r-report.md)。

## 第4批：离线 SingleR 候选注释

第4批在已有QC/Harmony镜像上增SingleR 2.8.0、DelayedMatrixStats 1.28.0和sparseMatrixStats 1.18.0。celldex 1.16.0只用于构建阶段及来源核对，不进入最终Worker；其依赖V8会让既有rstan发现并启动后台线程，实际不符合Worker原有单线程要求。最终镜像保留原线程检查，不开放网络/fork/exec。

```powershell
docker build -f infra/single-cell-r/Dockerfile.annotation -t paperassist-single-cell-worker:b4-singler .
# 准备阶段需要一次公开数据下载。固定SHA不匹配会拒绝使用新内容，不自动浮动更新。
docker build --target annotation-builder -f infra/single-cell-r/Dockerfile.annotation -t paperassist-single-cell-worker:b4-reference-builder .
docker run --rm --memory 2g --cpus 1 -v "${PWD}:/workspace" -w /workspace --entrypoint /opt/paperassist-bio/bin/python paperassist-single-cell-worker:b4-reference-builder infra/single-cell-r/prepare_reference.py --source script/.runtime/single-cell-batch4/reference-source --output script/.runtime/single-cell-batch4/reference
docker build -f infra/single-cell-r/Dockerfile.reference -t paperassist-single-cell-worker:b4-ready script/.runtime/single-cell-batch4/reference
```

固定参考为官方ExperimentHub的Monaco免疫参考1.0.0（EH3496/EH3497，对应下载path编号3512/3513），114个人类bulk RNA-seq样本、10个main/29个fine标签。原46077行按固定HGNC文件的approved symbol映射到30381个唯一Ensembl gene IDs，丢弃缺失及歧义映射；不猜alias，不按表达猜物种。参考RDS约15MiB，运行时从`/opt/paperassist-single-cell-r/share/paperassist-reference/monaco_immune_1.0.0/`只读，实际读入前验证SHA256。元数据完整记录来源、转换、原文件SHA、引用与许可；celldex GPL-3、上游论文CC-BY-4.0、HGNC映射CC0分别列明，未替GEO数据虚构单独许可。官方gypsum的2024-02-26端点本机403，因此未把旧参考冒称2024内容。

API可通过运维环境变量`PAPERASSIST_SINGLE_CELL_REFERENCE_ROOT`只读访问发布的reference.json；目录只影响轻量catalog，不能让用户指定Worker参考路径。catalog的available仅指元数据已发布，Worker执行时仍核对实际RDS内容。

`get_bridge().classify(expression_csr,cells,stable_gene_ids,reference_config,seed)`输入为未回归/未Harmony的非负log-normalized表达；参考要求显式Homo sapiens与ensembl_gene_id，按exact稳定ID交集匹配，不剥离版本。少于50个共同基因仅作为工程最低条件拒绝计算，不代表达到该阈值即有科学质量。真实SingleR classic、fine-tune及默认pruning使用SerialParam/KmknnParam。输出initial score全矩阵、fine-tuned候选、pruned/unknown、delta.next及delta-to-median；分数是相关性分位值而非概率，初始rank第一名可能与fine-tuned候选不同。所有自动标签保留candidate身份，人工确认另存。预热只用固定合成参考/表达，不在隔离前读取用户数据或实际参考。

方法、官方链接、数值对照和限制见[第4批SingleR报告](../../docs/superpowers/plans/2026-11-05-batch4-singler-report.md)。

第3批在新建单细胞请求中默认启用测序深度协变量处理和Harmony，仍可关闭；历史缺字段参数保留旧行为。协变量仅作用于HVG降维副本，Harmony仅处理PC矩阵，不替换counts/normalized/log1p。Harmony 1.2.3使用固定`RunHarmony`接口，不浮动采用不同API或默认值；官方资料和混杂/缺批次适用边界见[设计核查](../../docs/superpowers/plans/2026-11-05-batch3-design-notes.md)。Harmony启用沿用本节R任务4/5GiB和1GiB输出预算，未承诺更大数据可用。

## B08 复用的开源 R 扩展镜像

当前 B08 Bulk 镜像没有内置 R。`Dockerfile.b08-propeller` 在 `paperassist-b08-tabular:capacity-delivery` 上复用现有环境定义，补齐 R 4.4.3、Bioconductor 3.20、DelayedMatrixStats 1.28.0、rpy2 3.5.17 和官方 speckle 1.6.0。既有 `Dockerfile.topics` 接续安装 Slingshot 2.14.0、GENIE3 1.28.0、CellChat 2.2.0.9001 及固定源码依赖。核心版本和源码 SHA 固定，实际完整 Conda 清单另行留证；不声称所有传递依赖均由输入锁文件固定。CellChat 运行时仍使用仓库中带 SHA 校验的 CC-BY-4.0 三条人类文献演示资源，不代表完整 CellChatDB。

```powershell
docker build --network default --build-arg WORKER_IMAGE=paperassist-b08-tabular:capacity-delivery -f infra/single-cell-r/Dockerfile.b08-propeller -t paperassist-b08-tabular:single-cell-r-propeller .
docker build --network default --build-arg WORKER_IMAGE=paperassist-b08-tabular:single-cell-r-propeller -f infra/single-cell-r/Dockerfile.topics -t paperassist-b08-tabular:single-cell-r-topics .
docker run --rm --network none --memory 2g --cpus 1 --entrypoint /opt/paperassist-bio-insights/bin/python paperassist-b08-tabular:single-cell-r-topics -m app.adapters.bio_insights_engine.runtime_probe
```

2026-11-11 最终实测镜像为 `sha256:728b440e94d7708a5bbf983da746ccf6e5ca2d93f93acd19c2dc19cc937c5d57`。断网、单 CPU、2 GiB 容器中的综合探针通过 Propeller、Slingshot、GENIE3、CellChat，进程峰值 RSS 为 1,390,512 KiB（约 1.33 GiB）。另在 4 GiB 容器中分开执行原工具数值对照（7 + 5 项）与运行环境/隔离测试（4 项），共 16 项通过。数值对照使用合成夹具与真实 R 原工具，不替代新公开队列或生物学验证。

最终材料位于 `script/.runtime/bulk-b08-validation/single-cell-r-final/`：`bio-insights-runtime.json` 为程序可直接读取的原始准入收据，`summary.json` 为验证汇总，`commands.json` 保存命令、退出码及耗时；完整包清单、源码 SHA 和初次失败日志均保留。此前的 `single-cell-r-extensions-runtime.json` 仅为历史汇总，不能作为当前镜像的程序准入收据。

本机应用与镜像内四种方法独立预热后的实际 Worker 身份均与最终收据一致，环境摘要为 `fa6b07fd4b1a2f1af87659cd1fcfb34a44627619581ffaca57660301cfa169af`。部署时将同一原始收据通过 `PAPERASSIST_BIO_INSIGHTS_RUNTIME_MANIFEST` 配置给独立单细胞 API/Worker，并使用匹配镜像；仅配置 API 变量不会安装 R。当前 Bulk 验收栈保持独立镜像及原有有效收据。

运行 R 原工具测试前，沿用 `script/dev/single_cell_runtime.py` 的启动次序，先调用 `preload_runtime_libraries()`，再导入 pytest，避免 pytest 提前加载 Debian OpenSSL 与 Conda R 的 ABI 冲突。原工具测试与启动新子进程的综合探针分别运行，防止父进程保留的 R 堆占用 Docker 全局可用内存门槛；没有修改内存或隔离检查。

# 第3批后端实现任务

用户已授权第3批且要求“需要有整合和协变量处理，启用”。这是已批准七批计划的第3批，必须接真实工具、结果及Word，不能只写占位接口。范围如下。

## 约束与分工

- 当前`feat/single-cell-cloud-workflow`有大量第1/2批和云入口已验收未提交工作。只增量修改，不回滚；不新建分支、提交、推送、合并、部署或清理。只生成Word/PNG，无PDF。无云/付费/模型调用。
- 你负责`backend/`内本批参数合同、算法、R桥、Worker/资源选择、结果发布接线、Word和定向测试。主agent负责`infra/single-cell-r/`安装Harmony、`script/dev/single_cell_runtime.py`验证编排、前端、总领和实际验收。不要修改主agent负责文件。
- 研究接口建议见同目录`2026-11-05-batch3-design-notes.md`（研究agent正在完成）；若文件暂不存在按下述合同开始。
- 沿用已有4GiB RSS/5GiB AS、R任务总输出1GiB/单文件256MiB；Harmony启用也走这套R限额。基础/空间及既有导入/单图行为不变。不增加资源版本、重复审批或新任务类型。
- 只跑定向测试。数据库测试须串行，不与主agent验收并行；重R/容器测试先通知主agent避免内存重叠。不重启现有服务。只读探针及合成对照不能冒充真实数据验证。

## 新参数与向后兼容

- `hvg_batch_key: null | 'batch' | 'library_id'`，新建默认`'batch'`。
- `technical_covariates: list[Literal['log1p_total_counts','mt_fraction']]`，不重复，新建默认`['log1p_total_counts']`。
- `harmony: {enabled: bool, batch_key: 'batch'|'library_id', theta: float=2, lambda: float=1, max_iter: int=10}`，新建默认enabled=true、batch_key='batch'。合理有界参数并拒绝非有限值。
- 历史已持久化参数缺这些字段不能在重放时自动变成启用。建议SingleCellParameters缺字段保持旧行为，另一个`new_single_cell_parameters`工厂用于新建请求默认值和capabilities.default_params。前端会显式提交全部新参数。
- enabled=false / 空协变量 / hvg null必须保留第2批科学行为。新字段不应用到空间任务。

## 科学实现

1. 在QC最终保留细胞后用有效映射的batch或原始library_id作分组；缺失值不填unknown后假装真实批次。HVG仍使用log1p输入的Scanpy seurat dispersion。批次可用时按Scanpy batch-aware语义选择，稳定ID用于同分确定次序；保存means、dispersion、批次命中数/选择信息及实际策略。批次缺失/仅单批次时退回原global HVG并明确状态/reason。
2. 可选技术协变量只在HVG独立dense copy上处理（检查已有20M dense上限），处理顺序log1p→regress_out→scale→PCA。默认用原始QC总counts的log1p，mt_fraction仅已确认mt规则且完整时可用。检查缺失/非有限、常量、设计矩阵含截距的共线性；无效请求整体not_computable并明确未应用，不悄悄丢列；group/donor等生物组别不可作为技术协变量。用原生`scanpy.pp.regress_out(...,n_jobs=1)`并做真实数值对照；必要预热在沙箱前仅合成数据执行。
3. 保留无协变量PCA和应用协变量后的PCA；应用后PCA仍为`X_pca`，额外`X_pca_unadjusted`。Harmony用真实固定R harmony 1.2.3 `RunHarmony(data_mat=PCs,meta_data=...,vars_use='batch',theta=...,sigma=.1,lambda=...,max_iter=...,early_stop=TRUE,ncores=1,return_object=FALSE)`，seed固定、细胞轴显式核对。保留`X_pca_harmony`；实际neighbors/UMAP/Leiden只用明确选定表示，成功则Harmony、未应用则PCA。counts/normalized/log1p、markers和pseudobulk输入不替换。R包安装主agent负责。
4. batch缺失/只有一批/批次与多个研究组完全混杂时Harmony not_computable，原因明确；缺group标记混杂未能评估但允许探索性Harmony。失败记录failed并保留PCA下游，不生成伪Harmony结果；结果页面与Word必须看得出requested/applied与实际表示。预热固定R函数和最小合成输入，保持网络/fork/exec/线程约束。
5. 前后诊断：同细胞/同维数的批次描述指标（如固定种子有界样本batch silhouette及kNN异批比例，明确不是生物学质量评分）、按batch/group计数与混杂表。按batch着色的PC前/后对比PNG，需清楚标注PCA vsHarmony维度（Harmony轴不是PCA解释方差），协变量前后PC诊断同样保留。可以少量图，避免为每个元数据复制大量UMAP。原PCA和Harmony数组/表、状态、实际工具参数/版本/日志完整可下载且Word纳入。

## 结果合同（尽早通知主agent实际键）

建议`summary.single_cell_integration={hvg:{...},technical_covariates:{status,reason,requested,applied,columns,...},harmony:{status,reason,requested,applied,batch_key,...},design:{status,reason,...},downstream_representation:'X_pca'|'X_pca_harmony',versions:{...}}`。
新表/图/member key使用`integration_`前缀，前端会放到PCA/UMAP页，并显示摘要卡。现有hvg表可增加逐批信息。步骤状态使用现有completed/not_requested/not_computable/failed，不新增无支持的状态。记录HVG fallback另用字段。
Word新段落中英文可读，声明未改原计数与指标科学边界，不生成PDF。复现methods和H5AD需记录实际表示、状态、参数、版本。

## 验证与交付

TDD针对有意义科学/合同行为：新建默认与历史重放隔离、批次HVG原生对照及缺批次fallback、单协变量原生对照/缺失/常量/共线性/原层不变、Harmony原调用对照/轴顺序、成功时邻居确用整合表示、混杂/缺批次未应用、H5AD与输出完整性及沙箱运行。
不改已有测试来掩盖回归；新默认对旧fixture的影响应明确用历史关闭参数或新默认预期。测试入口参考`test_single_cell_batch2_r.py`，新重R文件建议`test_single_cell_batch3_r.py`供主agent统一运行。

完成报告写`docs/superpowers/plans/2026-11-05-batch3-backend-report.md`，包含文件、实际命令/输出、红绿证据、未验证/限制。最终回复状态、测试简述、合同键和报告路径。不要提交。代码完成通知主agent冻结后再运行全探针/公开矩阵。

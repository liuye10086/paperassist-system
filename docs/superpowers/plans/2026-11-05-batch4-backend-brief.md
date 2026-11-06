# 第4批后端实现简述

约束：沿用当前分支与未提交成果；Word only，不生成中间PDF；无云/付费调用。后端定向验证使用隔离测试schema，不触碰业务数据；实际计算和服务验收由主任务统一执行。

1. 人工注释沿用 `BioAnnotationRequest` / `BioAnnotationStore` / annotation sets与versions。单细胞使用已处理 observations 的 kept cells，不要求 positions。标签增加 cell_ids 与 uncertain；依据沿用 evidence 表，增加 reference/manual（说明写入 note），marker/file保留。标签编辑只产生新注释版本，不启动基础任务。
2. `POST /projects/{project}/bio-single-cell-subsets`：请求明确 parent_processed_source、cluster_ids/cell_ids、name、params。服务验证父来源/权限/所选存活细胞；冻结 resolved_cell_ids；沿用 bio_analysis_v3 direct、recipe/run/task/object出版。传科学入口 payload.processed 与 payload.subset；基于父counts和稳定原轴切片，跳过双细胞/decontX捕获文库计算，可重跑表示/整合/聚类。父子关系保存在 snapshot/manifest，无新增逐步版本系统。
3. SingleR独立于人工标签及基础processed：新增轻量 `bio_annotation` 任务冻结父processed与参考，复用现有任务/租约/存储出版流程，mode=annotation调用真实SingleR。候选、wide scores、参考来源、参数和日志通过已有annotation对象下载；人工采纳另存人工注释集合，不把机器结果写成研究者确认。
4. 失效沿用现有来源校验：旧注释对象保留可追溯，依赖标签的当前性比较加入 annotation set current_version_id 校验；基础processed不受影响。编辑时不删除旧结果。

接口协调：前端沿用已有 annotation POST/version GET；新增查询当前processed注释列表；子集启动返回已有run/task结构。科学代理负责子集counts切片与SingleR真实工具；后端负责来源冻结和publication。关键路径采用测试先失败后修复。

## 本代理实际实现与验证

- SingleR最终独立 `bio_annotation` task；请求/轮询 `bio-single-cell-annotation-runs`，父结果下 `annotation-runs` 支持刷新恢复；`bio-requests?kind=annotation_run` 复用请求回执。使用现有租约、dispatcher、task workspace、重试、admission与settlement，不新增业务表或基础processed副本。
- 参考目录由 `PAPERASSIST_SINGLE_CELL_REFERENCE_ROOT` 暴露纯metadata；固定参考为 `monaco_immune_1.0.0`，Worker运行前自行验证RDS字节；父样本必须全部明确human。候选/剪枝、wide scores、来源、参数与日志通过annotation版本的成员下载。
- 候选保存在独立set，标明SingleR/candidate_only，人工采纳另存manual set；模型候选set不允许直接手工覆盖。manual/reference依据最小数据库CHECK扩展，迁移为 `0072_single_cell_annotations`。
- 子集冻结父processed source与resolved cells；继承父recipe映射/设计，清空旧cluster label参数，关闭doublet、exclude_predicted、decontX；科学pipeline由主代理实现父counts/轴与QC继承。
- 单细胞annotation图复用既有bio_figure入口；标签版本更新只使明确引用旧版本的图/insight来源过期，历史对象保留，基础任务不新增。
- 26项离线合同/选择/父输出校验测试通过。3项隔离PostgreSQL schema流程测试通过（48.82秒），另单项真实DB失败→generic retry→成功测试通过（23.38秒）。旧direct_start的4项DB测试通过；以上科学输出注入合成叶对象，仅证明工程接线，不等同真实SingleR/真实矩阵或生物学验证。
- 测试证据：仓库根 `batch4-db-tests.txt`、`batch4-retry-db-tests.txt`。实际R/Worker队列、页面/Word与用户验收由主代理另行记录。本代理未启动/停止既有服务、未操作业务schema、未提交或推送。

最终review补充：`annotation_run`查请求必须返回标准receipt（kind/id/root_id/request_digest/task_id），不能直接返回run detail，真实API先失败后修复验证通过（23.38秒）。研究来源仅对显式依赖旧注释的 `bio_figure_version` 增加current检查，沿已有finding/report bindings递归传递，使研究报告任务source_current=false，并拒绝以旧标签新建报告；历史报告/研究图GET和成员下载以内部 `allow_stale_labels=True` 只跳过标签latest-pointer检查，仍验证owner、对象hash、固定来源和taskstatus。真实DB链已验证报告对象出版后改标签、旧图/旧报告成员可下载、新报告拒绝。证据追加 `batch4-receipt-db-tests.txt`、`batch4-research-stale-db-tests.txt`、`batch4-research-history-db-tests.txt`。轻量回归总数现30项通过。

历史兼容审阅：空 `labels.cell_ids=[]` 新默认字段不改变空间选择；仅对这种无cell选择的请求接受省略该默认字段的旧digest，以保留已有空间注释幂等回执。新写入保留完整digest，存在真实cell选择时不接受省略selector。新增离线回归先失败后通过，轻量总数31项（2.50秒）。最终研究图出版/报告历史currentness/原始来源防篡改3项DB回归46.02秒全通过。

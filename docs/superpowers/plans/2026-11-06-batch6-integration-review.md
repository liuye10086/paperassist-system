# 第6批应用接线与科学语义独立审查

日期：2026-11-06。范围：integration/schema_version=2 的 Slingshot、GENIE3、CellChat 应用接线、选择轴、统计单位、保存结果与 Word、界面草稿/导航。R 内部以 `2026-11-06-batch6-r-review.md` 的独立审查为边界，本次不重复审查。

## 结论

- Spec：复审通过本次限定范围。初审的 1 个 P1 和 2 个 P2 已在当前源码中修复。
- Quality：复审通过；当前未保留需要阻断本批的接线或科学语义缺陷。既有全量测试没有重复执行；新版 runtimegate 在本次复审时仍在进行，属于父任务后续验证，不能据本结论宣称已完成。
- 本结论来自当前源码只读核查及一次最小函数调用，不代表真实公开矩阵正式队列验证完成，也不代表生物学适用性、最大规模容量或用户验收。

## 初审发现（以下均已修复，保留原始触发条件）

### P1：所选观测映射在界面应用，却在专题后端被静默忽略

- `frontend/src/features/bio-insights/SingleCellTopicSetup.tsx:15` 将所有选中 `bio_observation_map_version` 传给 `readFixedObservations`；`frontend/src/features/bio-insights/observations.ts:12` 按匹配 raw dataset 覆盖 condition/donor 等字段。专题界面显示和条件选择依据这些新值。
- `backend/app/domain/bio_insights/sources.py:270` 将映射覆盖逻辑限定为 `config.kind=='comparison'`。因此 `integration/schema_version=2` 虽允许冻结映射来源，却仍使用 processed 原 observations。
- `backend/app/domain/bio_insights/single_cell_topics.py:28`、`:33`、`:43` 依据上述旧 observations 选择条件并建立 donor×condition 单位。新映射可能使界面与实际选择不同，出现零选择/错误阻断；更严重的是条件相同但 donor 重新映射时仍按旧 donor 计算。
- 建议：使专题使用同一已冻结、raw 身份匹配的映射覆盖；至少不得静默接受并在界面展示与实际执行不同的来源。验证 condition 和 donor 分别改变的案例，确认 preview、child、parent validation 与界面一致。保留映射源依赖。

### P2：所有单位都不可计算的预声明边从供者比较表消失

- `backend/app/adapters/bio_insights_engine/single_cell_topics.py:125-131` 只在 `status=='computed'` 时创建 family。因此某个 sender×receiver×LR 全部不可计算时，`communication_comparisons` 中没有该边，而不是 n=0、P/q=NA、not_computable 和原因。
- 完整单位层 `communication_results` 的缺失值仍被保留（`:179-184`）；问题局限于供者比较输出轴丢失，不是将缺失值转换成零。
- 本次用 AST 提取原 `communication_comparison` 函数，传入一个请求边且其单位状态为 not_computable；实际返回 `[]`。这是最小只读复现，未运行 R、服务或整个测试套件。
- 建议：先由请求行建立完整 family，再只用 computed 行填入供者数值；全缺失边保存显式不可计算行。BH 仍仅作用于实际可检验 P。

### P2：Word 中的供者数量与逐边实际检验数量可能不一致

- `backend/app/adapters/bio_insights_engine/single_cell_topics.py:44` 保存的全局 `actual_units` 来自设计预检；`:133-148` 的实际比较会按可计算网络删去缺失供者/不完整对，逐边真实 n 已正确保存至 TSV。
- `backend/app/adapters/single_cell_insight_report.py:120-124` 展示全局设计 n；`:131` 的 comparison 摘录只展示边、difference、P/q，未展示实际 n/complete_pairs/status/reason。
- 例如设计 4 对供者，其中一对某边不可计算：Word 展示 4 对及来自 3 对的 P，无法在报告内明确对应实际统计单位；不可计算 P=NA 的逐边原因也不可见。完整下载 TSV 正确，但不能据此认定报告自身已准确说明统计设计。
- 建议：把全局计数明确标为入选设计数量，并补充独立的逐边 n/完整对数/状态/原因表，避免将宽表强行塞入一张表。定向检查缺失单位与不足 3 对两个情况即可。

## 已核查的正确接线与语义

- 合同继续使用既有 integration kind，`contracts.py:372-378` 按 schema_version=2 分派，`:413-415` 要求选中对应 processed/annotation 来源；无新增 task/API/DB 审批路径。
- `single_cell_topic_contracts.py:40-53` 要求 Slingshot 明确 root/basis、GENIE3 显式 gene/TF 轴及两个不同 seed、CellChat 标签及比较条件；选择函数拒绝重复细胞、错误 annotation parent，按状态排除 uncertain/unlabeled 并保存排除数。
- `bio_insights_engine/single_cell_topics.py:23-32` 检查固定 cluster 叶与 metadata、annotation 叶与 assignments；`:55-76` 保留逐细胞/lineage PT 和 weight、NA 与原曲线；`:80-104` 按显式 gene/TF 次序输入未整合 log1p，真实执行两个 seed 并保存稳定性。
- 同文件 `:107-119` 以全部原始 Gene Expression counts 为归一化分母，按精确 symbol 合并重复，再 log1p；`:162-184` 按 donor×condition 单独计算，缺失供者只允许实际 sample 的描述单位，不把技术文库计作 donor。`:132-153` 使用 donor 分数进行 paired/Welch t 和 BH，不用 cell permutation P 替代 donor P；不足供者和无方差保留 NA。
- `service.py:104-106` 设计分派、`:303-307` runtime gate、`pipeline.py:28-30` 数值分派、`bio_insights_process.py:167-169` 配置解析和 `:219-222` parent validation 均接入专题；transport 保留来源绑定并在隔离后从已验证叶恢复 annotation。`settings.py:13-16` 维持 RSS 2 GiB / AS 3 GiB / 单线程，`:29-36` 将专题 Python/R/资源纳入代码摘要。
- `bio_single_cell_topic_validation.py:16-39` 校验配置、选择、图件和轨迹轴，`:44-70` 校验 GENIE3/CellChat 轴与数值范围。该检查不是独立重算统计，本次不将其解释为数值验证。
- `BioAnalysisResult.tsx:31` 有专题入口，`BioInsightsWorkspace.tsx:52` 解释 intent；`InsightPlanEditor.tsx:27-31` 为专题设独立草稿 scope 并保留普通草稿/未决请求。`hooks.ts:9-17` 按账户/项目/scope 存草稿且会话改变失效；workspace 会话变化后停止内容展示。未见专题新增跨账号状态保留。
- `InsightResults.tsx:23` 可达结果表、固定 PNG、下载与 Word；Word 直接读保存结果，不调用 PDF；`reproducibility.py:149-150` 明示专题独立样式重绘未实现，保存 PNG 可用，没有误标支持。
- 图件按保存数据绘制：Slingshot 表示前两维及原曲线、GENIE3 两 seed 权重、CellChat 逐单位 LR 概率和的均值。CellChat 图标题说明文献 demo 子集，NA 不画成零；热图为跨单位描述汇总，不能读成条件效应或 donor 显著性。

## 验证范围

父任务报告的前端 5 tests/build、domain 9/report 3/statistics 4、runtimegate 小夹具通过，本次未重复执行，也未据此宣称真实矩阵正式队列已通过。本次只运行上述全缺失比较函数最小复现；其余为源码核查。未修改功能代码、Git、服务、数据、预算或依赖；仅写本审查记录。

## 修复后复审

- 来源覆盖：`backend/app/domain/bio_insights/sources.py:22-34` 抽取相同 raw 身份的固定映射 helper，`:285-293` 明确对 comparison 及 integration/schema_version=2 调用；condition/donor/sample/batch/section 依照 known 状态覆盖。前端 `observations.ts:12` 同步覆盖 sample_id。之前前端应用而后端忽略的专题接线问题已解决。新增两例分别检查新 donor/condition/sample 和同 barcode 不同 raw 的隔离。
- 全缺失边：`backend/app/adapters/bio_insights_engine/single_cell_topics.py:127-130` 现在先登记请求 family，再跳过不可计算数值；原后续逻辑会输出 n=0、NA、not_computable、insufficient_computable_donors。已有 donor 数值检验和 BH 范围未改变。新增 all-uncomputable 回归覆盖初审复现。
- Word：`backend/app/adapters/single_cell_insight_report.py:123` 显式标明全局是设计入选数量；`:162-165` 为与结果相同的摘录边补充逐边实际 n、完整对数、状态和原因表。新增测试同时含设计 4 对/实际 3 对和全缺失边，检查记录保留。本次确认内容/结构，未独立进行 Word 视觉渲染检查。
- `frontend/src/features/bio-insights/SingleCellTopicSetup.tsx:18-19` 新增会话改变时 abort、清空加载行、禁止继续读取及回写；与 workspace/session guard 一致。
- 父任务提供修复后的执行证据：domain topics + report 共 15 passed；统计容器共 5 passed，并已见相应失败用例红→绿。本次已读这些新增用例及对应实现，没有重复运行。新版实际 runtimegate 正在重新生成科学代码摘要证明；最终运行状态由父任务核实。本次源码复审不替代该环境证明，也不替代真实公开矩阵正式队列或生物学验证。

## 正式队列触发的发布补查

此前静态复审遗漏了 `BioInsightsService.publish` 的第二处 inference_scope 分派，限定通过不应被解读为端到端队列完成。真实 Slingshot task `0addbd1c-206c-5d72-aadf-b28439e3f80a` 数值后失败，暴露此遗漏。

- 本次通过已有 worker 容器和 `SET TRANSACTION READ ONLY` 检查：task 为 failed/bio_insight_source_conflict；checkpoint seq 1 为 check，seq 2 为 publish；同一 task 的 `service.require_sources` 实际通过。因此已到发布阶段，未发现冻结来源变化。
- 根因：`service.py` 发布逻辑将 integration 默认解释为 derived，拒绝专题保存的 sample_exploratory/donor_inference；数值校验已有正确专题分派，发布分支缺失。
- 父任务追加授权后，仅补 `backend/app/domain/bio_insights/service.py:450-451` 的 integration/schema_version=2 分支，与计算及验证一致。Slingshot、GENIE3、CellChat per_donor 为 sample_exploratory；CellChat paired/unpaired 为 donor_inference。未修改 DB、重启服务、重新运行数值或扩展 retry 策略。
- 新增 `backend/tests/domain/test_single_cell_topic_publication.py`：直接执行真实 publish 方法，替换来源/对象读取与数据库写入边界；覆盖 5 种成功分类到 result/member insert、run update、finish，并验证不正确 scope 在写入前拒绝。本审查代理亲跑修复前 5 failed / 1 passed，修复后 6 passed。
- 该证据是发布方法级回归，不是数据库集成测试；修复后正式队列发布、服务加载新代码与交付验证仍由父任务完成。当前源码层已无此未修复缺陷，但端到端结果必须另以正式队列证据确认。

## 第5批历史来源兼容补查

父任务指出新增 single-cell 派生 metadata 可能破坏历史严格快照后，本代理进行了真实只读核查，而非仅凭代码推断：

- 第5批 CD4 result `09aaaadc-19d9-5a3b-94be-f932789a9100` 的 succeeded task `5b52e452-3076-5f22-8b42-60b4a34c2925` 在 `require_sources(runtime=False)` 中确实于 frozen envelope 比较失败。
- 不输出来源内容的差异检查确认：processed 来源的 kind/id/role/sha256/project/locator 全一致，仅当前 metadata 新增 `cell_clusters` 和 `retained_feature_ids`，没有共享字段变化；annotation 身份也一致。
- 经父任务明确授权，`service.py:frozen_envelope_projection` 新增窄范围兼容：只对双方 assay=single_cell、observation_level=cell 且完整身份相同的 processed 来源，从当前比较投影中移除旧快照没有的上述两个派生字段；不修改存储快照，已冻结字段、source hash、成员 hash 及其他字段仍严格比较。
- 在 `test_bio_insight_historical_sources.py` 增加缺一个/两个字段、已冻结字段变化、source id/hash/project 变化用例；本代理亲跑修复前 3 failed / 13 passed，修复后连同发布回归共 22 passed。测试确认当前及历史输入不被投影函数修改。
- 修复后再次在容器只读事务对同一真实第5批 task 调用 `require_sources(runtime=False)`，实际 PASS。这里只证明历史来源/快照读取恢复，不宣称已重新下载或视觉检查该 Word。
- 未修改数值引擎、数据库、原有结果或服务；运行中第6批正式任务由父任务继续管理。

## CellChat 旧来源缺物种声明补充

父任务的真实 preview 发现 Kang 旧 processed 未记录 species_taxon_id。经明确授权，本代理增加可选显式声明，不推断物种：

- `single_cell_topic_contracts.py` 新增 species_taxon_id / species_basis；非默认值仅 CellChat 可用，须同时有正整数 taxon 和非空依据。默认 None/空通过 Field(exclude_if) 不序列化，保持已发布 Slingshot/GENIE3 完整配置字典 roundtrip 不变。
- 复用已有 sources `_resolve_many_in_phase` 的缺值补全；已有来源物种不被覆盖。`single_cell_topics.py` 的设计预检拒绝声明与固定来源冲突；未知且未声明仍阻塞。方法记录和 Word 的保存 config 会保留用户声明及依据。
- 新增测试实际经过 `_resolve_many_in_phase` 和 service `_design`（替换来源读取/phase 边界），覆盖缺值补全、未声明、两个方向的冲突、相同声明、旧配置与声明依据。最终 topics/report/publication/historical 四个定向文件共 48 passed，本代理亲跑。
- 科学 code digest 范围变化仅两个领域文件：`domain/bio_insights/single_cell_topic_contracts.py`、`domain/bio_insights/single_cell_topics.py`。未改 R 或数值适配器、来源 helper、UI、DB、服务；父任务负责 UI/验收 seed/新版 gate。此处未宣称真实 CellChat 队列已通过。

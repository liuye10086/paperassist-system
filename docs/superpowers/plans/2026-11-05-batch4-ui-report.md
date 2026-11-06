# 第4批前端实施报告

本报告仅描述前端实现与离线定向验证。当前分支 `feat/single-cell-cloud-workflow`，没有新建分支、提交、推送或启动/停止服务；没有云、付费 API 或 PDF 操作。

## 已实现

- 复用 `bio-result` 的 `spatial` tab，单细胞显示“细胞注释与亚群”。空间结果仍使用原来的空间画布与区域编辑流程。
- `BioAnnotationEditor` 按 assay 适配：单细胞支持 cluster IDs、明确 cell IDs、proposed/confirmed/unknown/uncertain、marker/file/manual/reference 依据；不显示区域绘制控件，不请求空间坐标。创建与编辑仍只写 annotation set/version，不触发基础分析。
- 当前人工注释列表、版本编辑与来源校验；固定注释详情在 processed/raw 来源不匹配时拒绝显示编辑器。SingleR 固定版本以候选说明返回工作区，不在原机器集合中直接编辑。人工草稿打开后不会被另一次候选采纳覆盖。
- SingleR 使用本地 reference catalog，显式选择可用参考后创建独立 `bio_annotation` 任务；运行列表和详情轮询支持离开后返回继续查看，链接既有任务中心。成功后刷新候选列表，展示逐 cell candidate、pruned、delta.next、delta.median 与来源元信息，提供完整 scores、参考、参数与工具日志的既有成员下载。
- 人工显式勾选候选后，按逐 cell assignments 建立独立人工草稿；保留 proposed/uncertain/unknown 状态和固定候选版本/参考依据，不默认 confirmed，不写回候选集合。每页仅渲染 50 条逐 cell 候选行。
- 子集选择父 cluster 或明确 cell IDs，显示选择标识数及固定父来源。继承父参数，仅提供 HVG、PCA、邻居数、resolution、seed 等重聚类参数；显式禁用双细胞和 decontX 重算，说明继承父 QC 与保留基因。只调用 `bio-single-cell-subsets`，导航到现有 child run。子结果从 `manifest.subset.parent_processed_source` 打开父链接。
- 报告显式选择当前人工标签，Word 下载附 `annotation_version_id`。同一选择可“按此标签绘制 UMAP”，只创建既有 `bio-figures` annotation 图任务，不重算基础处理。单图配置允许单细胞 annotation 类型并校验同来源人工标签；历史图件保留原固定标签版本选项。
- 任务解析补齐 `bio_annotation_v1`、返回注释工作区链接，以及现有直启/子集使用的 `bio_analysis_v3`。写入恢复支持 `annotation_run` 的空 root_id 回执，丢失 POST 回应后仅按原 key GET 核对。
- 根据实际后端响应修复旧注释详情把 object checks 当 array 导致的崩溃，同时兼容已有 array checks。

## 文件范围

新增 `SingleCellAnnotationWorkspace.tsx`、`SingleCellCandidates.tsx`、`SingleCellAnnotations.test.tsx`、`tasks/bioAnnotationTask.test.tsx`。修改现有 `BioAnalysisResult.tsx`、`BioAnnotationEditor.tsx`、`BioFigureDetail.tsx` 及其测试、`spatialContracts.ts`、`useBioWrite.ts` 及其测试、`tasks/taskTypes.ts`、`tasks/BioTaskLinks.tsx`。

## 验证

关键路径按先失败后实现验证：人工标签显式 IDs/uncertain 依据、来源错配、单细胞无 coordinates、独立子集请求、SingleR 启动与手工采纳、机器版本只读、真实 object checks、独立 annotation UMAP、任务合同与 v3 接线。SingleR 原请求恢复还经过旧条件失败→恢复修复后通过的回归验证。

最后一次组合命令（在 `frontend`）通过 12 个文件、187 条测试：

```powershell
npm test -- src/features/bioinformatics/SingleCellAnnotations.test.tsx src/features/bioinformatics/BioFigureDetail.test.tsx src/features/bioinformatics/BioAnnotationEditor.test.tsx src/features/bioinformatics/BioSpatialResult.test.tsx src/features/bioinformatics/BioSpatialWorkflow.test.tsx src/features/bioinformatics/spatialLifecycle.test.tsx src/features/bioinformatics/spatialContracts.test.ts src/features/bioinformatics/useBioWrite.test.tsx src/features/tasks/bioAnnotationTask.test.tsx src/features/tasks/bioAnalysisTask.test.ts src/features/tasks/taskTypes.test.ts src/features/projects/bioAnalysisNavigation.test.tsx
```

另一次相邻范围命令通过 43 条测试，覆盖 SingleCellIntegration、SingleCellDirectStart、BioSpatialWorkflow、spatialLifecycle、bioAnalysisNavigation、useBioWrite；与最终组合有重叠，不累加为唯一测试总数。

`npm run build`：TypeScript 与 Vite 构建通过；保留现有大 bundle 的 >500 kB 警告。

针对本批所改 13 个 TS/TSX 文件运行 `npx oxlint <files>`：退出码 0，无错误或警告。

## 边界与待验收

- 上述浏览器交互均为 Vitest/jsdom，HTTP 用项目 API client mock；断言实际发出的 URL、JSON body、幂等 key、来源过滤及导航，并非后端真实计算或真实数据验证。
- 已与后端确认并读取 annotation/reference/run 的实际合同及实现；尚未由本代理运行真实 API/Worker、数据库集成或原生浏览器视觉验收。服务启动及真实数据/SingleR/图件/Word 验收由主代理统一执行。
- SingleR 参考可用与物种/稳定基因匹配以服务端及 Worker 校验为准；分数和候选不代表生物学身份确认。
- 本批没有重构通用 UI、清理已有数据或生成额外 PDF。

## 实际验收发现的小修与最终构建

主代理实际队列与浏览器检查发现父manifest含旧共用参数min_gene_spots，子集请求直接继承会422；已只在请求转换删除此字段并清空cell_labels，保留父其他参数和整合设置。实际父字段请求回归先红后绿。另将人工注释详情父来源等待阶段改为加载提示，延迟响应回归先红后绿，最终18项、lint及build通过，dist为index-1S5ifWP_.js。实际队列、页面与两份Word逐页结果见七批实施记录，不以本文件的mock测试替代。

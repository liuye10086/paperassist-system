# 第1批 输入元数据与资源估算实施记录

## 范围

本记录仅覆盖剩余七批第1批中的 metadata/resource/UI/Word 接线；真实运行探针、公开矩阵与峰值测量由主任务另行记录。不修改第2批算法，不执行云调用、提交、推送、业务库迁移或服务停止。

## 改动

- `SingleCellSample` 增加可空的 `species_taxon_id`、`reference_id`、`reference_version`、`library_chemistry`、`pair_id`。Taxon ID 严格为正整数，其他声明拒绝空白。旧请求继续可用，缺失值为 `None`，不猜测身份。
- 多文库明确给出的物种、参考标识或版本不同即拒绝合并；相同 `sample_id` 继续要求 donor/group 一致。文库不同建库方案或配对编号不人为视作冲突。
- raw manifest 的 `samples` 保留完整原始清单；原始 observation mapping 保存新增声明和 known/pending 状态。流水线从原始导入 mapping 取来源信息，后续手工 mapping 可修改既有设计字段，但不覆盖来源声明、文库编号与原始条码。
- observations TSV、H5AD obs、H5AD 的 `paperassist_import_samples_json`、processed manifest 的 `samples` 均保留来源信息。H5AD 字符串显示 `unknown` 时另存 pending 状态；原始 JSON 中仍为 `null`。
- Word 继续使用既有报告模块和已保存结果，末尾新增“导入文库来源信息”，同时保留有效映射的 donor/group 表。只生成 DOCX，不经过 PDF。
- 新增 `single_cell_resources.resource_estimate`；能力接口返回有名称的 `resource_estimate`：矩阵维度/nnz、CSR 字节、当前 HVG 参数对应的 float32 密集块上界、现有配置限额、blockers 和 `estimate_only`。`peak_memory_bytes` 为 `None`，不伪装成实测峰值。
- CSR 估算为 `nnz × (8+4) + (cells+1) × 8`；HVG 为 `cells × min(hvg_count, features) × 4`。保留 20,000 cells、100,000 features、10,000,000 nnz、20,000,000 dense values 和 2 GiB 进程限制。没有放宽限额或新增 resource profile/version 对象。
- `save_recipe` 在写 setup 前按实际请求参数校验；页面在开始前显示规模、估算与上限，HVG 改动即时更新密集块估算。默认 HVG 超界可减少 HVG 后启动，仍只有一次启动请求。

## 验证

测试遵循先新增定向用例、观察缺少字段/缺少资源估算/丢失 pipeline 与 Word 元数据/缺少 UI 展示的失败，再补实现的顺序。

- 数值：现有 `paperassist-client-b06-w1-worker:local`，`--network none`，backend `/workspace:ro`，科学解释器 `/opt/paperassist-bio/bin/python`，`MPLBACKEND=Agg`，`pytest --confcutdir=/workspace/tests/numeric -p no:cacheprovider tests/numeric/test_single_cell_samples.py tests/numeric/test_single_cell.py -q`：**16 passed**。覆盖新增 metadata、manual mapping 保留来源、原 counts 与轴不变、PNG/H5AD 输出。
- 前端：`SingleCellSampleFields.test.ts`、`SingleCellDirectStart.test.tsx`、`BioNewAnalysis.test.tsx`、`BioImportsV2.test.tsx`：**12 passed**。包含实际填写5字段、冲突校验、HVG 超界→降低参数→一次 POST。
- `npx tsc -b`：exit 0。
- 定向 `oxlint`：exit 0；保留 `SingleCellSampleFields.tsx` 既有组件与纯函数同文件的 Fast Refresh warning，无新增规则屏蔽。
- `git diff --check`：exit 0。
- 后端 `.venv/Scripts/python.exe`、`MPLBACKEND=Agg` 与测试框架隔离 PostgreSQL schema：合同/估算/Word/单次启动第一轮 **12 passed**。最终增加 API 能力响应与按请求 HVG 提前拒绝用例后，**14 passed, 1 teardown error**；该错误发生在已有合同用例的 `DROP SCHEMA ... CASCADE`，PostgreSQL 报共享锁内存不足并提示 `max_locks_per_transaction`，功能断言全部通过。与主任务同时执行测试 schema 创建/清理可能加剧锁竞争，这是推断；后续与主任务协调串行复核，不修改数据库配置或重启。
- 串行复核 `test_single_cell_setup_rejects_tissue_filter_and_preserves_label_evidence`：**1 passed in 4.71s**，包括 schema teardown。仅本轮确认遗留的 `pa_test_82666b6000f54a7384e2899fb85519f9` 已使用既有 migration 配置在 `paperassist_system_test` 内删除，未操作其他 schema。此次 teardown 限制已通过串行验证消除；后续数据库测试避免并行建删大 schema。

## 限制

内存估算是 QC 前按原始 cells/features 的保守上界，不包括 normalization 副本、scale/PCA 工作区、邻居、绘图、H5AD 和解释器开销；不能据此承诺进程峰值。原始物种/参考属于用户输入声明，不代表自动验证了数据身份。

Word 本子任务完成结构、文本、有效映射与原始来源并存验证；公开矩阵 Word 的视觉检查、实际 runtime identity 和进程峰值由主任务统一验收。合成数值测试不替代真实数据工具验证或生物学验证。

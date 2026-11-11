# Bulk RNA-seq B03 QC、展示转换与分析对象实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在已验收的 B02 输入、样本映射和研究设计接线上，完成 Bulk QC、可追溯展示层、PCA/聚类/相关性展示、分析对象往返校验和异常样本人工排除入口。

**Architecture:** 复用现有 `run_tabular`、processed dataset manifest、TSV/NPY/JSON artifact 和 recipe 版本链；新增 B03 层与 QC 产物时保持 raw 输入不可变。QC 只产生指标、规则和人工复核建议，排除必须通过新的 recipe `exclude_samples` 保存，聚类结果不自动删除样本。对象采用显式版本化的 JSON/NPZ artifact bundle，声明轴、参数、层和代码/环境身份，不冒充未实现的 h5ad。

**Tech Stack:** Python、NumPy、SciPy、Matplotlib、Pydantic、PostgreSQL 现有 processed dataset/API；React、TypeScript、Vitest。

## Global Constraints

- B02 已验收；不得修改 raw dataset、样本映射来源和研究设计版本。
- Bulk counts 的 raw counts、normalized counts、VST、PCA/聚类展示层必须有明确尺度、单位、轴和方法记录。
- PCA 不得使用 DEG 预筛；只能使用完整、非恒定特征，并记录不可计算原因。
- 疑似异常样本只提示；人工排除必须生成新 recipe 版本并保留原结果。
- 低样本、缺失值、恒定特征和不具备计算条件时输出可审阅状态，不伪造数值。
- 本批只完成 B03；不实现 B04 的差异表达、模型确认或通路分析。

## Tasks

### Task 1: 后端 B03 产物与契约

**Files:**
- Modify: `backend/app/domain/bioinformatics/tabular_contracts.py`
- Modify: `backend/app/adapters/bio_engine/tabular_assays.py`
- Modify: `backend/app/adapters/bio_analysis_store.py`
- Modify: `backend/app/core/errors.py`
- Test: `backend/tests/numeric/test_bio_tabular_assays.py`
- Test: `backend/tests/api/test_bio_tabular_foundation.py`

- [ ] 先写失败测试，覆盖 Bulk QC 总计数/检测特征/零比例/表达分布、VST 层、相关/距离热图数据、组别/批次标注、对象往返和 outlier advisory 不自动排除。
- [ ] 运行该定向测试，确认失败原因来自缺少 B03 字段/产物，而不是测试配置错误。
- [ ] 扩展 recipe 合同，增加可选 `vst` 展示层和明确过滤规则参数；保持旧请求可解析。
- [ ] 在 `run_tabular` 生成独立 raw/filtered/normalized/vst 层描述和对象 bundle，保存完整 sample/feature axes、参数、manifest digest、环境/代码身份和 round-trip digest。
- [ ] 生成 sample QC 指标与表达分布/库大小、相关性或距离热图数据；从样本表读取 condition/batch 并写入 figure data，不按聚类结果修改 observation mask。
- [ ] 生成基于透明规则的 outlier advisory（例如高缺失、高零比例、低检测特征或距离异常），只写建议和理由；人工 exclusion 仍使用现有 recipe 版本链。
- [ ] 运行后端数值和 API 定向测试，修复回归。

### Task 2: 前端 B03 审阅和人工排除

**Files:**
- Modify: `frontend/src/features/bioinformatics/tabularContracts.ts`
- Modify: `frontend/src/features/bioinformatics/TabularAnalysisResult.tsx`
- Modify: `frontend/src/features/bioinformatics/BioQcSummary.tsx`
- Modify: `frontend/src/features/bioinformatics/TabularAnalysisSetup.tsx`
- Test: `frontend/src/features/bioinformatics/TabularAnalysis.test.tsx`

- [ ] 先写失败测试，覆盖 B03 指标、层语义、异常提示和排除动作。
- [ ] 运行测试确认失败。
- [ ] 增加 B03 manifest/table/figure/object 类型，渲染 total counts、detected features、zero fraction、表达分布、规则和原因。
- [ ] 渲染 raw/filtered/normalized/VST 的尺度说明、PCA 方差、相关/距离图、condition/batch 标注和对象往返状态。
- [ ] 提供“建议排除”列表和逐样本人工选择，提交现有 recipe `exclude_samples`；明确不会按聚类自动删除。
- [ ] 运行定向 Vitest 和 TypeScript build。

### Task 3: 文档、验收证据和回归

**Files:**
- Create: `docs/开发记录/阶段04/2026-11-10-Bulk-B03-QC展示转换与分析对象-实施与验收记录.md`
- Modify: `docs/开发记录/项目管理/2026-11-09-Bulk-RNA-seq矩阵下游通路总领方案.md`
- Modify: `docs/README.md`

- [ ] 记录 B03 实际范围、变更文件、命令、测试计数、对象与层语义、限制和失败项。
- [ ] 更新总领方案 B03 状态为“实施完成，待用户验收”；B04 保持未启动。
- [ ] 运行 `git diff --check`、Python compileall、后端定向测试、前端定向测试和 build。
- [ ] 停在 B03 用户验收，不提交、不推送、不进入 B04。

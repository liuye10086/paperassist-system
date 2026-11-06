# 单细胞矩阵主流程实施计划

> For agentic workers: 使用 subagent-driven-development / test-driven-development 执行；用户已授权继续，不再次索要方案确认。云提供商变更本轮仅改文档。

**Goal:** 不依赖云账号，完成矩阵及样本信息输入、一次启动基础分析、查看图表和下载 Word 的主流程。
**Architecture:** 复用 bio_import_v4、single_cell_explore_v1、现有任务和文件治理，不新建工作流/逐步骤版本系统。科学计算复用实际 Scanpy 基础链；供者推断和高级专题不以基础探索通过替代。
**Tech Stack:** 现有 FastAPI/PostgreSQL/React/TypeScript、稀疏 AnnData/Scanpy、python-docx；本地现有 Linux 生信镜像用于真实工具检查。

## Global Constraints

- 用户选择阿里云 EasyGene/OSS，香港平台调用内地公网 API；本轮不实现或调用阿里云适配，不开通/购买/上传真实云数据。
- 不新增多次确认或逐步骤版本界面。保留已有数据和兼容历史流程，正常单细胞分析一次启动。
- 不提交、推送、合并、部署，不修改业务数据库，不停止已有服务；测试只用隔离测试schema和新建本地验证容器。
- 原始整数 counts 保留；样本/文库/供者不混淆；未知供者仅限制推断，不妨碍探索。不得伪造物种、参考或生物学结论。
- 文档只生成 DOCX，默认图使用 PNG及数据/manifest；不生成 PDF，包括排版核验中间件。
- 验证区分真实工具/合成矩阵、模拟API、真实生物数据；测试失败与未验证事项如实记录。

## Task 1：修复默认图发布

Files: `backend/app/adapters/bio_figure_store.py`；相关publication测试。
- [x] 用仅含PNG/data/manifest的当前实际图件合同复现默认图发布失败。
- [x] 复用现有默认图登记，去掉新成果对PDF的强制要求；历史PDF记录仍可读，不修改原文件。
- [x] 定向验证默认图登记、结果读取/下载及已有权限边界。

## Task 2：矩阵携带样本信息

Files: `single_cell_contracts.py`、`bio_engine/single_cell.py`、必要的pipeline读取；numeric与API合同测试。
- [x] 在现有单细胞导入请求增加可选样本清单，每个样本包含sample_id、library_id、donor、batch、group及其file_ids；无清单兼容原入口。
- [x] 多样本首期采用相同输入representation、相同基因集合，按稳定gene ID对齐；不凭symbol合并或猜缺失基因。文库barcode加命名空间并保留原barcode，按稀疏矩阵合并。
- [x] 写入现有raw member中的observation_map_index，基础分析读取；独立设计缺失时只作探索，不自动允许供者差异推断。
- [x] 验证重名barcode隔离、基因顺序重排、counts守恒、样本信息保留与无清单兼容。

## Task 3：一次启动基础分析

Files: 现有bio-analysis请求/服务/执行和API；前端single-cell操作入口。
- [x] 单细胞增加便捷启动请求，复用保存配方和现有run，输入参数一次提交；不要要求用户先创建配置版本。
- [x] 新便捷路径直接执行完整compute，含QC结果，不先暂停等待QC再次确认；原手动QC流程继续兼容。
- [x] 默认图、H5AD和表格按现有发布路径保存，前端沿用现有结果工作区。
- [x] 定向测试一次提交、统一Worker、无中途确认、错误显示及重复请求复用。

## Task 4：基础分析 Word 出口

Files: bioinformatics报告服务/现有DOCX格式工具、bio_analysis API、结果组件。
- [x] 基于已保存成功分析生成可下载DOCX，包含输入/样本、实际QC及保留数量、方法参数、已完成步骤、默认图和局限；无LLM或云账号依赖。
- [x] 只引用已保存表格与图件，不编造生物学注释、统计显著性或未执行的专题。
- [x] 前端提供一个“下载分析报告”入口，复用已有成果下载权限。
- [x] 使用合成矩阵的真实工具产物验证DOCX内容、图件与结构；可用时渲染核查。

## Task 5：接线与验证

- [x] 前端导入表单支持样本清单，保留原矩阵入口；多样本只在需要时展开，不加审批界面。
- [x] 使用现有本地Linux生信镜像运行小型矩阵的完整基础链，验证PNG默认图发布修复和报告内容。
- [x] 运行受影响后端/前端定向测试及build；更新总领与本轮交付记录。

此批优先打通基础主链。双细胞/环境RNA/R整合、自动注释、供者比较专题及全22步的剩余功能仍按总领后续推进，不能把本批通过记为全部完成。

## 本批完成记录

上述基础主链已实现并经定向验证。真实 Linux 工具的合成矩阵数值测试 16 项通过；真实 HTTP/隔离测试库/Docker Scanpy/发布/Word 下载主链通过。Word 以本机 Word 直接渲染为 PNG，英文合成报告 13 页逐页检查，无 PDF 中间件；不代表真实生物样本或生产环境验收。详见 `docs/开发记录/阶段04/2026-11-05-单细胞矩阵主流程实施与验证记录.md`。

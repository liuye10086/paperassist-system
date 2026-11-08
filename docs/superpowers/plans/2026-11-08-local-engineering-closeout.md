# 本地工程收口批 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不接入云账号、不调用真实模型或外部 API、不重跑既有分析的前提下，完成单细胞/矩阵平台本地文档状态、失败归因、Word/回归质量与云接口离线合同收口，并启动验收服务。

**Architecture:** 保留既有已验收功能和运行材料，所有新增证据写入独立的 `script/.runtime/local-engineering-closeout/`。文档更新只修正当前状态与本批事实，不改写历史回执。云接口采用 provider-neutral 的离线合同和 mock 测试，AWS 适配保留为历史实现，阿里云只记录所需字段和未完成边界。

**Tech Stack:** Python/FastAPI/PostgreSQL/Celery/RabbitMQ、React/TypeScript/Vitest、pytest、python-docx/Word 渲染工具、PowerShell/Docker Compose。

## Global Constraints

- 不提交、不推送、不部署，不删除文件，不清理工作区，不创建额外版本体系。
- 保留现有数据、结果、Word、失败记录、运行材料和 `.runtime`。
- 计算和测试尽量串行；前端测试使用 `--maxWorkers=1 --no-file-parallelism`。
- 只生成 Word，不生成 PDF。
- 不开通账号、不调用阿里云、不上传真实 FASTQ、不调用真实模型。
- 结果中明确区分源码支持、离线工程验证、真实数据验证、外部服务验证和生物学验证。

### Task 1: 文档状态与证据清理

**Files:**
- Modify: `docs/开发记录/项目管理/2026-11-05-单细胞完整通路与外部计算接入总领方案.md`
- Modify: `docs/开发记录/项目管理/2026-11-06-矩阵下游平台体验与运行优化总领方案.md`
- Modify: `docs/开发记录/阶段04/2026-11-05-单细胞七批实施记录.md`
- Modify: `docs/开发记录/跨阶段补齐/2026-10-28-第七批完整原句与保留缺口.md`
- Create: `script/.runtime/local-engineering-closeout/document-state.md`
- Create: `script/.runtime/local-engineering-closeout/document-cleanup.json`

- [ ] 修正顶部旧快照，明确矩阵优化第1—6批和原七批已用户验收收尾。
- [ ] 将本批剩余事项分为本地任务、材料依赖、外部资源依赖。
- [ ] 清理控制字符与明显文案错误，保留原始历史回执，不改写已验收事实。
- [ ] 用脚本扫描目标文档控制字符并通过 `git diff --check`。

### Task 2: 失败归因与性能只读调查

**Files:**
- Create: `script/.runtime/local-engineering-closeout/storage-failure-readonly.json`
- Create: `script/.runtime/local-engineering-closeout/performance-readonly.md`
- Modify: 主领方案第12/13节和对应实施记录，补入本批只读证据

- [ ] 只读核对任务 `2084d3f7-6617-5f72-b635-9fb912366278` 的项目配额、占用、reservation、intent、ledger、失败阶段和原始错误。
- [ ] 只读定位来源核验、写锁等待、租约恢复、报告来源读取耗时，区分证据和推断。
- [ ] 不改配额、不重跑、不重试、不修改原失败记录，不把配额错误归因内存不足。
- [ ] 记录查询命令、时间、数据库/日志来源和限制。

### Task 3: Word 与前端回归质量收口

**Files:**
- Modify: 研究结果目录中与旧 UI 文案/版本断言相关的最小测试/fixture
- Modify: 测试夹具中残留的 `<details>/<summary>` 标记（仅夹具）
- Create: `script/.runtime/local-engineering-closeout/frontend-regression-classification.md`
- Create: `script/.runtime/local-engineering-closeout/word-browser-download.json`
- Create: `script/.runtime/local-engineering-closeout/word-pages/`
- Modify: 相关实施记录

- [ ] 串行复跑历史前端回归，按真实回归、旧断言、mock 缺口、集成超时分类。
- [ ] 最小更新旧 UI 文案/版本断言；补齐必要 mock；不扩大到未授权的全量重构。
- [ ] 清理测试夹具折叠标记，不恢复生产折叠面板。
- [ ] 启动验收服务后完成 Word 浏览器下载和必要逐页视觉检查；不生成 PDF。
- [ ] 记录主 JS 包体积与 gzip 值，作为已知限制。

### Task 4: 云接口离线合同

**Files:**
- Modify/Create: `backend/app/domain/bio_cloud/provider.py`, `backend/app/domain/bio_cloud/contracts.py`, `backend/app/domain/bio_cloud/settings.py`（仅必要最小改动）
- Modify/Create: `backend/tests/bio_cloud_unit/test_adapter.py` 与相关离线合同测试
- Create: `script/.runtime/local-engineering-closeout/cloud-contract-audit.md`

- [ ] 明确 provider-neutral 的能力、任务 ID、状态、未知提交、取消和结果完整性字段。
- [ ] 审计任务幂等、取消、未知提交和结果清单/size/etag/sha256 合同。
- [ ] 明确阿里云 EasyGene/OSS 所需 provider、CreateRun/GetRun/AbortRun 映射及结果字段；不实现真实适配，不声称已接入。
- [ ] 区分当前 AWS 专用配置字段和未来阿里云配置字段。
- [ ] 先写失败离线测试，再做最小实现，使用 mock/stub，确保不会联网。

### Task 5: 验证与验收服务

**Files:**
- Create: `script/.runtime/local-engineering-closeout/verification-summary.json`
- Modify: `script/.runtime/local-engineering-closeout/acceptance-ready.md`

- [ ] 运行后端定向 pytest、前端定向 Vitest/build/lint、文档扫描、Word XML/逐页检查。
- [ ] 使用现有验收启动脚本启动 `paperassist-single-cell-acceptance`，确认 `http://127.0.0.1:8000` 可访问。
- [ ] 保留服务运行，等待用户验收；不自动停服、不进入下一批。

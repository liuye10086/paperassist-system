# 主链路性能与前端连续性设计

**日期：** 2026-11-08
**范围：** PaperAssist-System 主链路首批改造
**基线：** `06cb24fe7841e56ea0c8a3fb6765f46d6480f2ae`（现有未提交改动不纳入）

## 目标

在不替换现有分析引擎、任务幂等、草稿保护、深链接和 Word 交付逻辑的前提下，缩短“新建项目 → 上传材料 → 选择需求 → 执行分析 → 查看结果 → 继续写作”的读取链路，并让用户始终知道当前步骤、阻塞原因和唯一推荐的下一步。

性能验收采用请求级回归：记录改造前后的请求数量、重复读取次数和串行链长度；相同输入的重复提交不能创建新任务。暂不承诺未经实测的绝对秒数。

## 外部参考与取舍

- Galaxy History 将输入、输出、状态、重跑和中间结果组织在同一工作区，并使用集合和隐藏中间结果降低复杂度。参考：[History system](https://galaxyproject.github.io/training-material/topics/galaxy-interface/tutorials/history/tutorial.html)。
- Seqera Platform 的 Runs 统一呈现 `submitted/running/succeeded/failed/cancelled/unknown` 状态，并允许从运行记录继续保存配置。参考：[Runs monitoring](https://docs.seqera.io/platform-cloud/monitoring/overview/)。
- Galaxy 的 History Graph 计划要求服务端提供规范化、稳定 ID、一次性遍历的来源图，避免客户端逐个接口拼接。参考：[History Graph issue](https://github.com/galaxyproject/galaxy/issues/21659)。
- cellxgene 将元数据、主视图和特征视图分开读取，并在筛选条件较大时使用 POST，适合本项目“材料—分析—结果”分层读取。参考：[REST API](https://github.com/chanzuckerberg/cellxgene/blob/main/dev_docs/REST_API.md)。
- Label Studio 把项目壳、数据管理器和编辑器拆成独立前端边界，适合本项目保留侧边栏、材料管理和主流程轨。参考：[Repository structure](https://github.com/HumanSignal/label-studio/blob/develop/CONTRIBUTING.md)。

本批只吸收状态投影、单一运行/步骤视图、按需读取和稳定来源边界；不引入 Galaxy/Nextflow/Airflow 全套运行时，也不引入实时 SSE、全量 lineage 图或矩阵选择令牌化。

## 方案

### 1. 轻量流程状态投影

新增只读接口：

```text
GET /api/v1/projects/{project_id}/workflow-state
```

返回：

```json
{
  "project_id": "project-id",
  "project_type": "research",
  "files": { "total": 3, "ready": 2 },
  "requirements": {
    "saved": true,
    "version": 4,
    "services": ["analysis", "sci_draft"]
  },
  "results": { "available": true },
  "next_step": "analysis"
}
```

约束：

- 接口只在一个只读事务中读取项目归属、文件就绪计数、当前需求版本/服务和已有结果计数。
- 不返回任务详情、图表内容、原始矩阵、下载地址或内部对象标识。
- 项目不存在或无权访问沿用现有 `404/403`，前端沿用 `watchProjectAccess` 清理工作区。
- `next_step` 只代表产品流程上的下一步，不代表分析、科学结论、生产或交付已完成。
- 上传、解析、保存需求、生成结果后由现有刷新回调重新读取；响应按请求序列丢弃，避免旧响应覆盖新状态。

后端建议新增：

- `backend/app/domain/workflow_state.py`：只读查询与状态推导。
- `backend/app/api/projects.py`：`WorkflowState` Pydantic 契约和 GET 路由。
- `backend/tests/api/test_workflow_state.py`：所有权、空项目、文件就绪、需求服务、已有结果、404/403。

首批不新增迁移；查询复用现有 `projects`、`files`、`research_requirement_versions`、`research_intake_roots`、成果/分析结果表及现有索引。若现有结果表存在多种历史来源，状态只需回答“是否有可查看结果”，不合并历史内容。

### 2. 前端读取边界

修改 `frontend/src/features/projects/useProjectFlow.ts`：

- 读取 `workflow-state`，删除为了门禁而无条件读取的完整 `/summary`。
- `reason()` 继续只根据文件就绪、需求服务和项目类型返回阻塞原因。
- `savedRequirement` 仍由需求页使用的真实版本提供；流程投影只负责轻量门禁状态。
- `refresh()` 重新读取投影并保持当前项目隔离。

修改 `frontend/src/features/projects/ProjectResources.tsx`：

- 文件列表仅在 `section === 'files' || section === 'analysis'` 时读取。
- 上传或解析变化继续调用现有 `onSaved`/`refresh`。
- 不改变文件详情、质量控制、生信导入和分析设置的既有入口。

保持 `ResearchIntake` 在需求页面读取完整需求、材料引用和历史；不把轻量投影当作编辑数据源。

### 3. 主流程 UI

修改 `frontend/src/features/projects/ProjectJourney.tsx` 及其样式：

- 主流程固定为：项目资料、文件上传/整理、选择需求、执行分析/稿件写作、查看结果。
- 每一步显示状态标签：已完成、进行中、待补材料、可查看；状态来自投影和当前页面，不以“访问过页面”推断完成。
- 页面底部保留一个主“下一步”按钮和一个次要返回/查看入口。
- 结果页将 SCI、毕业论文、已有稿件与 Word、暂时结束统一为下一步卡片；服务缺失时回到需求页。
- 保留 `aria-current`、键盘焦点恢复、离开保护、移动端抽屉和横向滚动步骤轨。
- 侧边栏仍按材料准备、分析与成果、稿件写作、评审与修改分组，只承担上下文跳转；主流程轨承担引导。

修改 `frontend/src/features/projects/ProjectWorkspace.tsx`、`ProjectSummary.tsx`、相关 CSS 和 i18n：

- 保留现有 hash 路由与固定结果深链接。
- 不移除已有模块，只收敛重复的“继续”按钮和状态说明。
- 不向客户界面暴露内部哈希、原始 JSON 或服务端异常文本。

## 失败处理

- `workflow-state` 请求失败时，主流程显示可重试状态，不解除原有门禁。
- 项目 404/403 继续走现有项目不可用清理，不保留私有页面内容。
- 上传/需求保存的未知响应、冲突、草稿和幂等键处理不变。
- 只要接口返回的 `next_step` 与子页面状态不一致，子页面真实状态优先，流程轨显示“需要刷新/核对”，不自动推进。
- 本批不新增自动重试、不改变外部模型调用、不改变收费或任务取消语义。

## 验收

### 后端

- `workflow-state` 返回稳定字段和稳定错误码。
- 不同用户无法读取他人项目状态。
- 空项目返回 `files.ready = 0`、`requirements.saved = false`、`next_step = "upload"`。
- 保存需求、上传可分析材料、产生结果后状态按真实数据库记录改变。
- 同一幂等键和同一输入重复提交时，新任务数保持为 0；已有结果继续复用。

### 前端

- 项目打开时 `useProjectFlow` 只请求一次 `workflow-state`，不再请求 `/summary`。
- 概览/需求页面不额外请求 `/files`；文件/分析页面才请求。
- 保存需求或上传材料后，步骤状态和下一步按钮即时更新。
- 刷新、后退/前进、固定结果深链接、草稿离开保护和权限清理保持。
- 结果页只保留一个主继续动作；缺少服务时回到需求页。
- `npm run test -- --run` 的定向测试、`npm run build`、`npm run lint` 通过；记录 bundle 体积提示但不宣称已消除。
- 后端运行新增契约测试和受影响的任务/项目测试；不把合成数据、离线测试或本地页面检查描述为真实生物学或生产验证。

## 明确不在本批

- 大矩阵 cell ID 选择令牌化或输出分页协议。
- SSE/WebSocket 实时任务推送。
- 全量 lineage 图 API 和图形编辑器。
- 分析算法、模型策略、云端适配、数据库历史迁移、Word 生成和生产部署。
- 清理当前工作目录已有未提交修改，或覆盖既有运行材料和结果。

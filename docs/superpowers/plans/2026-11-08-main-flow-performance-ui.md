# 主链路性能与 UI 连续性优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 在不改变既有项目数据、任务幂等和科学分析语义的前提下，把“新建→上传→需求→分析→结果→写作”收敛为一个可恢复的主链路，并用轻量工作流状态、按需读取和可量化回归减少首屏与重复请求。

**Architecture:** 后端新增 owner-scoped 的 GET /api/v1/projects/{project_id}/workflow-state 只读投影，单个只读事务返回文件、需求、结果和下一步所需的最小状态；前端 useProjectFlow 只读取该投影，重型 summary 仅在结果页读取，文件列表仅在文件/分析页读取。ProjectJourney 作为唯一主流程导航，工作区侧栏保留上下文入口，状态与“下一步”动作由同一份投影驱动。

**Tech Stack:** FastAPI、Pydantic、PostgreSQL read-only transaction、React、TypeScript、Vitest、Testing Library、pytest。

## Global Constraints

- 保留当前工作区已有未提交改动；实现仅在 C:\Users\86182\.codex\worktrees\main-flow-performance-ui\paperassist-system 分支完成，不对主 checkout 做 reset、clean、删除或覆盖。
- 不修改任务幂等键、已有草稿、文件资产、分析算法、模型/云调用、Word 导出、生产部署或数据库迁移。
- workflow-state 只返回流程投影：不返回 task 明细、原始矩阵、下载 URL、内部 artifact ID 或科学结论；next_step 只表示 UI 下一步。
- 后端所有查询必须沿用当前 ProjectStore.owner_id 作用域；跨项目访问返回现有 project_not_found 语义。
- 文件“就绪”只统计 parse_status IN ('parsed','stored')；失败、排队和解析中的文件保留在总数中但不能推进流程。
- 需求服务优先从 current requirement 的 content_json.services 读取；缺失时使用有效 research_deliveries.kind，不猜测科学完成度。
- 不承诺未经实测的绝对秒数；验收记录请求数量、是否触发 summary、是否在 overview 触发 files、重复输入是否创建新任务。
- 代码和测试沿用现有中文界面文案、现有路由/hash 深链、草稿恢复、离开保护、焦点管理和移动端行为。
- 当前环境 backend 基线曾因缺少 defusedxml 在测试收集阶段失败；实现前先按仓库依赖安装，若仍无法安装，必须把阻塞写入验证结果，不得声称后端测试通过。

---

## 文件与职责映射

- Create: backend/app/domain/workflow_state.py — 定义响应模型、单事务读取和纯函数 derive_next_step。
- Modify: backend/app/api/projects.py — 注册 workflow-state GET 路由和响应模型。
- Create: backend/tests/api/test_workflow_state.py — 覆盖空项目、文件就绪、需求保存、结果可用、跨项目 owner 隔离。
- Modify: frontend/src/features/projects/useProjectFlow.ts — 用轻量投影替换无条件 summary 读取，保留已有 visited/acceptServices 逻辑。
- Modify: frontend/src/features/projects/ProjectResources.tsx — 将文件请求和相关导入读取限定到 files/analysis 区域。
- Modify: frontend/src/features/projects/ProjectJourney.tsx — 展示阶段状态和单一主“下一步”动作，保留现有导航回调。
- Modify: frontend/src/features/projects/ProjectWorkspace.tsx — 将 workflow-state 状态传给 ProjectJourney，刷新时只刷新轻量投影。
- Modify: frontend/src/features/projects/projectJourney.css — 增加状态徽标、下一步卡片和窄屏布局，不改变现有工作区壳层。
- Modify: frontend/src/shared/i18n/workflowMessages.ts — 增加本次新增的阶段状态和动作文案中英文键。
- Modify: frontend/src/features/projects/useProjectFlow.test.tsx — 覆盖 workflow-state 解析、结果页不提前 summary、刷新只触发轻量状态。
- Create: frontend/src/features/projects/ProjectJourney.test.tsx — 覆盖状态徽标、下一步按钮和阻塞文案。
- Modify: frontend/src/test/integration/WorkspaceDesign.test.tsx — 记录主链路请求预算和 overview 不读取 files 的回归断言。

---

### Task 1: 新增轻量 workflow-state 后端投影

**Files:**
- Create: backend/app/domain/workflow_state.py
- Modify: backend/app/api/projects.py
- Create: backend/tests/api/test_workflow_state.py

**Interfaces:**
- Consumes: ProjectStore.connection()、ProjectStore.owner_id、StorageError、现有 research_intakes / research_requirement_versions / research_deliveries / files / 结果表。
- Produces:
  - WorkflowState(BaseModel)
  - read_workflow_state(store: ProjectStore, project_id: str) -> WorkflowState
  - derive_next_step(*, ready_files: int, requirements_saved: bool, services: list[str], results_available: bool) -> Literal['upload','requirements','analysis','results','writing']
  - GET /api/v1/projects/{project_id}/workflow-state

- [ ] Step 1: Write failing contract and derivation tests

在 backend/tests/api/test_workflow_state.py 写入：

~~~python
from tests.api.test_projects import create_project, upload

def test_empty_project_points_to_upload(client):
    project = create_project(client, project_type="sci")
    response = client.get(f"/api/v1/projects/{project['id']}/workflow-state")
    assert response.status_code == 200
    assert response.json() == {
        "project_id": project["id"], "project_type": "sci",
        "files": {"total": 0, "ready": 0},
        "requirements": {"saved": False, "version": None, "services": []},
        "results": {"available": False},
        "next_step": "upload",
    }

def test_parsed_file_without_requirement_points_to_requirements(client):
    project = create_project(client, project_type="sci")
    upload(client, project["id"])
    body = client.get(f"/api/v1/projects/{project['id']}/workflow-state").json()
    assert body["files"] == {"total": 1, "ready": 1}
    assert body["next_step"] == "requirements"

def test_next_step_precedence():
    from app.domain.workflow_state import derive_next_step
    assert derive_next_step(ready_files=0, requirements_saved=True, services=["analysis"], results_available=True) == "upload"
    assert derive_next_step(ready_files=1, requirements_saved=False, services=[], results_available=False) == "requirements"
    assert derive_next_step(ready_files=1, requirements_saved=True, services=["analysis"], results_available=False) == "analysis"
    assert derive_next_step(ready_files=1, requirements_saved=True, services=["sci_draft"], results_available=True) == "results"
    assert derive_next_step(ready_files=1, requirements_saved=True, services=["sci_draft"], results_available=False) == "writing"
~~~

增加一个 owner 隔离测试：切换测试会话 owner 后访问另一个 owner 的项目，响应必须为 404，不能泄漏投影。

- [ ] Step 2: Run the focused tests and verify the intended failure

Run from backend:

~~~powershell
python -m pytest tests/api/test_workflow_state.py -q
~~~

Expected: failure because the route and app.domain.workflow_state do not exist. If collection stops at defusedxml, install repository backend requirements first and record that prerequisite.

- [ ] Step 3: Implement the minimal model and pure function

Create backend/app/domain/workflow_state.py:

~~~python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.adapters.storage import ProjectStore
from app.core.exceptions import StorageError

NextStep = Literal["upload", "requirements", "analysis", "results", "writing"]

class WorkflowFiles(BaseModel):
    total: int = Field(ge=0)
    ready: int = Field(ge=0)

class WorkflowRequirements(BaseModel):
    saved: bool
    version: int | None = Field(default=None, ge=1)
    services: list[Literal["analysis", "sci_draft", "thesis_draft"]] = Field(default_factory=list)

class WorkflowResults(BaseModel):
    available: bool

class WorkflowState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    project_type: Literal["sci", "thesis", "research"]
    files: WorkflowFiles
    requirements: WorkflowRequirements
    results: WorkflowResults
    next_step: NextStep

def derive_next_step(*, ready_files: int, requirements_saved: bool,
                     services: list[str], results_available: bool) -> NextStep:
    if ready_files == 0:
        return "upload"
    if not requirements_saved:
        return "requirements"
    if results_available:
        return "results"
    if "analysis" in services:
        return "analysis"
    return "writing"
~~~

- [ ] Step 4: Implement one read-only owner-scoped SQL snapshot

In read_workflow_state use one with store.connection() as db block. First select the project with WHERE p.id=%s and, when store.owner_id is not None, append AND p.owner_id=%s; raise StorageError("project_not_found", "项目不存在，请刷新项目列表。", 404) when absent.

In that same transaction execute a file aggregate and a scalar result/requirements query. Result availability uses EXISTS against analysis_runs JOIN files, bio_processed_dataset_versions, research_finding_versions, research_figure_versions, research_report_versions, and research_manuscript_candidates, constrained by project_id and user_id where present. Current requirements come from research_intakes joined to research_requirement_versions; parse content_json.services, intersect with ("analysis", "sci_draft", "thesis_draft"), and fall back to active research_deliveries.kind. Return saved=False/version=None/services=[] when neither exists. Never include content_json in the response.

- [ ] Step 5: Register the literal route before the dynamic project route

In backend/app/api/projects.py add:

~~~python
from app.domain.workflow_state import WorkflowState, read_workflow_state

@router.get("/{project_id}/workflow-state", response_model=WorkflowState)
def get_workflow_state(project_id: str, store: Store):
    return read_workflow_state(store, project_id)
~~~

Place it before the dynamic /{project_id} route.

- [ ] Step 6: Run focused backend tests

~~~powershell
python -m pytest tests/api/test_workflow_state.py tests/api/test_projects.py::test_upload_list_reopen_and_download_original -q
python -m pytest tests/api/test_research_intake.py -q
~~~

Expected: workflow-state, upload and intake tests pass. If dependency or database setup blocks execution, record the exact error and do not claim backend success.

- [ ] Step 7: Check diff hygiene

~~~powershell
git diff --check
git status --short
~~~

Expected: no whitespace errors and only the listed backend files are changed/untracked. Do not commit without separate authorization.

---

### Task 2: 收紧前端读取边界并替换 flow hook

**Files:**
- Modify: frontend/src/features/projects/useProjectFlow.ts
- Modify: frontend/src/features/projects/ProjectResources.tsx
- Modify: frontend/src/features/projects/useProjectFlow.test.tsx
- Modify: frontend/src/test/integration/WorkspaceDesign.test.tsx

**Interfaces:**
- Consumes: Task 1 workflow-state contract.
- Produces: useProjectFlow(...).workflowState with the same files/requirements/results/next_step shape; error is merged from the light request and intake only when intake is active.

- [ ] Step 1: Add a failing request-boundary test

Update the mocked read hook and add:

~~~tsx
it('reads lightweight state and never requests summary during flow navigation', () => {
  const { result } = renderHook(() => useProjectFlow(project, 'overview', 'settings'))
  expect(result.current.workflowState?.next_step).toBe('requirements')
  expect(result.current.summaryRequested).toBe(false)
})
~~~

In WorkspaceDesign.test.tsx make the fetcher return workflow-state and assert that opening a project on overview calls workflow-state once, does not call summary?, and does not call the exact /files endpoint.

- [ ] Step 2: Run focused frontend tests and verify failure

~~~powershell
npm test -- --run src/features/projects/useProjectFlow.test.tsx src/test/integration/WorkspaceDesign.test.tsx
~~~

Expected: failure because the hook still calls summary and has no workflowState field.

- [ ] Step 3: Replace summary with workflow-state while preserving guards

In useProjectFlow.ts:
- Add a typed WorkflowState interface matching Task 1.
- Call useResearchRead<WorkflowState>(id ? `/api/v1/projects/${id}/workflow-state` : '', !!id).
- Remove unconditional summary hook and all summary.data/summary.refresh references.
- Use workflow.data.requirements.services for hasAnalysis and requirementSaved; set existingResults = workflow.data?.results.available ?? false.
- Keep flowBlockReason and visited-page behavior unchanged.
- Return workflowState: workflow.data and summaryRequested: false.
- Make refresh call workflow.refresh() and intake.refresh() only.

- [ ] Step 4: Gate ProjectResources file reads

Change the file-list effect condition to exactly active && (section === 'files' || section === 'analysis'). When false, abort the pending controller, clear loading/error for that read, and return before calling fileRequest. Keep filesActive, analysisActive, imports, preview and leave-guard behavior unchanged.

- [ ] Step 5: Run focused frontend tests

~~~powershell
npm test -- --run src/features/projects/useProjectFlow.test.tsx src/test/integration/WorkspaceDesign.test.tsx
~~~

Expected: all existing and new tests pass; no exact /files request occurs on overview settings/requirements.

- [ ] Step 6: Verify request counts

Assert one workflow-state request per project activation; zero summary? and exact /files before files/analysis; files adds one request; artifacts adds one summary request; refresh is the only action that repeats workflow-state.

---

### Task 3: 将 ProjectJourney 收敛为唯一主流程导航

**Files:**
- Modify: frontend/src/features/projects/ProjectJourney.tsx
- Modify: frontend/src/features/projects/ProjectWorkspace.tsx
- Modify: frontend/src/features/projects/projectJourney.css
- Modify: frontend/src/shared/i18n/workflowMessages.ts
- Create: frontend/src/features/projects/ProjectJourney.test.tsx

**Interfaces:**
- Consumes: workflowState from Task 2, existing navigation callbacks and blocked guard.
- Produces: accessible primary rail with status labels, one 下一步 action, and unchanged hash/deep-link callback contracts.

- [ ] Step 1: Write failing UI tests

Create ProjectJourney.test.tsx with mocked i18n/context and assert:

~~~tsx
const state = {
  project_id: 'p1', project_type: 'research' as const,
  files: { total: 1, ready: 1 },
  requirements: { saved: true, version: 2, services: ['analysis'] as const },
  results: { available: false }, next_step: 'analysis' as const,
}
const props = {
  project: { id: 'p1', name: '研究', research_topic: '主题', project_type: 'research' as const,
    default_output_language: 'zh-CN' as const, file_count: 1, created_at: '', updated_at: '' },
  section: 'analysis' as const, overviewView: 'settings' as const,
  onOverview: vi.fn(), onUpload: vi.fn(), onAnalysis: vi.fn(), onResults: vi.fn(),
  onWriting: vi.fn(), blocked: vi.fn(() => ''), active: true, hasAnalysis: true,
  workflowState: state,
}

it('shows completed, active and waiting statuses from workflow state', () => {
  render(<ProjectJourney {...props} />)
  expect(screen.getByText('已完成')).toBeTruthy()
  expect(screen.getByText('进行中')).toBeTruthy()
  expect(screen.getByText('待处理')).toBeTruthy()
})

it('exposes one primary next action and keeps blocked steps disabled', () => {
  render(<ProjectJourney {...props} />)
  expect(screen.getByRole('button', { name: /下一步/ })).toBeTruthy()
  expect(screen.getAllByRole('button', { name: /第/ }).some(button => button.hasAttribute('disabled'))).toBe(true)
})
~~~

- [ ] Step 2: Run the new UI tests and verify failure

~~~powershell
npm test -- --run src/features/projects/ProjectJourney.test.tsx
~~~

Expected: failure because ProjectJourney has no workflowState prop, statuses or primary next action.

- [ ] Step 3: Implement the state-driven rail

Add the local WorkflowState prop type. Derive five stages:
1. project info — completed once project exists;
2. upload — completed when files.ready > 0, active when next_step is upload;
3. requirements — completed when requirements.saved, active when next_step is requirements;
4. analysis/writing — completed when results.available, active when next_step matches the selected service;
5. results — active/completed when results.available.

Render visible 已完成/进行中/待处理/待补材料 status text, preserve blocked as title and disabled state, and render exactly one button.button-primary in a journey-next-action card. Map upload to onUpload, requirements to onOverview('requirements'), analysis to onAnalysis, results to onResults, and writing to onWriting.

- [ ] Step 4: Wire ProjectWorkspace

Pass workflowState={flow.workflowState} to ProjectJourney. Keep existing project type, callbacks and guard props. ProjectWorkspace and useProjectSelection remain the only hash/deep-link owners.

- [ ] Step 5: Add message keys

Append only the keys used by this component to workflowMessages.ts: 已完成, 进行中, 待处理, 待补材料, 下一步, 上传并继续, 保存需求并继续, 开始分析, 查看结果, 继续写作, 项目操作步骤. Keep Chinese keys as source locale and add English values.

- [ ] Step 6: Implement responsive styles

Add .journey-status, .journey-next-action, .journey-next-action .button-primary and a @media (max-width: 720px) horizontal scroll rule in projectJourney.css. Do not change WorkspaceShell portal class names.

- [ ] Step 7: Run UI/build/lint checks

~~~powershell
npm test -- --run src/features/projects/ProjectJourney.test.tsx src/features/projects/useProjectFlow.test.tsx src/test/integration/WorkspaceDesign.test.tsx
npm run build
npm run lint
~~~

Expected: tests pass; build and lint have no new errors; hidden sections remain absent from the accessibility tree.

---

### Task 4: 端到端性能回归与验证记录

**Files:**
- Modify: frontend/src/test/integration/WorkspaceDesign.test.tsx
- Modify: frontend/src/features/projects/useProjectFlow.test.tsx
- Modify: backend/tests/api/test_batch10_statistics.py
- Create: docs/superpowers/verification/2026-11-08-main-flow-performance-ui.md

**Interfaces:**
- Consumes: Tasks 1–3 API and UI behavior.
- Produces: 可复核的请求计数、重复任务计数和验证边界记录；不把合成测试写成真实数据/模型/生产验证。

- [ ] Step 1: Add request-budget assertions

Use fetcher.mock.calls to assert:

~~~tsx
expect(calls.filter(([url]) => String(url).includes('/summary?'))).toHaveLength(0)
expect(calls.filter(([url]) => String(url).endsWith('/files'))).toHaveLength(0)
expect(calls.filter(([url]) => String(url).includes('/workflow-state'))).toHaveLength(1)
~~~

After switching to files/analysis, files increases by exactly one; after artifacts, summary increases by exactly one.

- [ ] Step 2: Add the repeated-input invariant

Extend backend/tests/api/test_batch10_statistics.py::test_analysis_post_queues_without_computing with a second database assertion: after the two identical POST calls, SELECT count(*) FROM tasks WHERE project_id=%s AND task_type='statistics_compute' must equal 1 and SELECT count(*) FROM task_outbox WHERE task_id=%s must equal 1. This verifies the existing idempotency boundary without adding fields or changing production APIs.

- [ ] Step 3: Run scoped verification

~~~powershell
cd backend
python -m pytest tests/api/test_workflow_state.py tests/api/test_projects.py tests/api/test_research_intake.py tests/api/test_batch10_statistics.py::test_analysis_post_queues_without_computing -q
cd ../frontend
npm test -- --run src/features/projects/ProjectJourney.test.tsx src/features/projects/useProjectFlow.test.tsx src/test/integration/WorkspaceDesign.test.tsx
npm run build
npm run lint
~~~

Expected: scoped backend/API/UI checks pass. If backend dependency or database setup is unavailable, record the exact error and do not mark backend verification as passed.

- [ ] Step 4: Record evidence and limits

Create docs/superpowers/verification/2026-11-08-main-flow-performance-ui.md containing baseline/after request counts, whether overview triggered summary/files, duplicate-task result, commands/output, and explicit limits: no real cloud/model call, no real biological dataset validation, no production deployment, no absolute latency claim.

- [ ] Step 5: Final diff hygiene

~~~powershell
git diff --check
git status --short
~~~

Expected: no whitespace errors; changed files match the approved design. Keep the worktree uncommitted until separate authorization for commit, push, merge or release.

---

## Self-review checklist

- Spec coverage: Task 1 covers one-transaction workflow-state, owner scope, result availability and next-step derivation; Task 2 covers summary/file request reduction and preserved guards; Task 3 covers sole primary rail, statuses, next action, deep links, focus and mobile styles; Task 4 covers quantitative request/idempotency regression and evidence boundaries.
- Placeholder scan: no unspecified work remains; each code change names an exact file, interface, test and command.
- Type consistency: Task 1’s WorkflowState fields are reused verbatim by Task 2 and Task 3; next_step values are identical across backend, hook and UI.
- Scope guard: no task changes analysis algorithms, model/cloud behavior, database schema, Word generation or deployment.

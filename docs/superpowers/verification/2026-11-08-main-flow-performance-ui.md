# 主链路性能与 UI 连续性优化验证记录

日期：2026-11-08
worktree：C:\Users\86182\.codex\worktrees\main-flow-performance-ui\paperassist-system
分支基线：feat/main-flow-performance-ui，基于 06cb24fe

## 已验证

前端请求边界与主流程回归：

- 运行 npm test -- --run src/features/projects/ProjectJourney.test.tsx src/features/projects/ProjectWorkspaceFlowRefresh.test.tsx src/features/projects/useProjectFlow.test.tsx src/test/integration/WorkspaceDesign.test.tsx
- 结果：4 个测试文件、13 个测试通过。
- 新增回归覆盖上传资料保存后的 workflow-state 刷新：上传回调完成后，下一步从“上传并继续”更新为“保存需求并继续”。
- 新增回归覆盖已有结果时“查看结果”保持“进行中”，避免主按钮和阶段状态同时显示完成。
- overview 打开项目时，集成测试记录 workflow-state 1 次、summary 0 次、精确 /files 0 次。
- 切换到 files/analysis 后，已有集成测试验证文件列表请求只在对应区域发生。
- 切换到 artifacts 后，已有集成测试验证 summary 请求按结果页进入发生；离开再进入不会产生额外重复请求。

浏览器主链路走查：

- 在 disposable PostgreSQL schema 中登录、创建项目、上传 `sample.xlsx`，完成测试用解析状态后刷新页面。
- 页面连续显示“项目资料已完成 → 上传文件已完成 → 选择需求进行中”，进入需求后勾选“数据分析”并保存，页面进入“执行分析”并显示字段配置入口。
- 该走查中的“批次状态读取失败”来自手工构造的最小解析结果缺少完整批次契约，属于测试夹具限制；workflow-state 和下一步门控本身已正确推进。

前端构建与静态检查：

- npm run build：通过，Vite 生产构建完成。
- npm run lint：退出码 0；仓库已有 hook/ref/set-state 警告仍存在，未将其扩大为本次阻塞。
- python -m compileall -q app tests/api/test_workflow_state.py：通过。
- git diff --check：通过。

后端 PostgreSQL 集成验证：

- 当前隔离 worktree 没有复制被 Git 忽略的 `backend/.env` 和 `backend/.env.migrations`；测试时仅将主 checkout 中的专用测试库配置注入进程，没有修改任何配置文件。
- `python -m pytest tests/api/test_workflow_state.py -q`：4 个测试通过，真实连接 PostgreSQL 测试库并完成独立 schema 迁移。
- `python -m pytest tests/api/test_workflow_state.py tests/api/test_projects.py::test_upload_list_reopen_and_download_original tests/api/test_batch10_statistics.py::test_analysis_post_queues_without_computing -q`：6 个测试通过。
- `python -m pytest tests/api -x -q`：前 5 个测试通过后，在既有 `test_admin_basic_ncbi.py::test_two_versions_share_one_database_limiter` 失败；实测第二个延迟为 `0.356256s`。
- 单独复跑该既有用例仍失败，第二个延迟为 `0.315951s`，固定断言要求大于 `0.4s`，说明当前环境下该断言稳定不满足；它不触及本批次改动文件，与 workflow-state、上传流程和分析幂等断言无直接关联。

性能基线与变更后对照（合成请求计数）：

| 场景 | 变更前观察 | 变更后 |
| --- | ---: | ---: |
| 项目 overview 打开时 summary 请求 | 2 | 0 |
| 项目 overview 打开时精确 /files 请求 | 2 | 0 |
| 项目 overview 打开时 workflow-state 请求 | 不存在 | 1 |
| 进入结果页新增 summary 请求 | 由初始全局读取承担 | 1 次按需读取 |

变更前数字来自同一集成测试在加入新断言后首次运行的失败输出；它是本地合成 UI 请求计数，不是生产网络耗时基线。

## 未完成或受限

- 完整 `python -m pytest tests -q` 在收集阶段仍受仓库已有生物分析可选依赖和平台差异阻塞：缺少 `matplotlib`、`gseapy`、`h5py`、`anndata`，Windows 环境也没有 `resource` 模块；这不影响本批次 API 定向测试结果。
- 已使用主 checkout 中已配置的 OpenAI 凭据完成 1 次真实 Responses background 调用（模型 `gpt-6.1-sol`），轮询返回六段结构化解释且 usage 存在；这只验证适配器连通性和响应契约，不代表完整业务链路、科学结论或生产稳定性。
- 未进行真实生物数据验证、生产部署或绝对延迟承诺；浏览器走查使用的是 disposable 测试 schema 和小型合成表格。
- 本次 workflow-state 的结果可用判断只作为流程门控信号，不代表科学结论、生产完成或写作质量。

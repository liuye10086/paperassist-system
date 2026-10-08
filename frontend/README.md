# PaperAssist 前端

使用React、TypeScript和Vite，负责登录后的项目工作台。后端启动、PostgreSQL连接及首个管理员初始化见[项目README](../README.md)；本机管理员已经初始化，不需要重复创建。

## 启动与检查

在项目根目录使用Windows PowerShell执行。首次运行或锁文件变化后安装依赖：

```powershell
npm.cmd --prefix frontend ci
```

本机验收可在根目录执行 `script/dev.cmd start` 后台启动前后端及绘图、解释、Word 异步任务所需的 RabbitMQ、Linux Worker 和 dispatcher，使用 `script/dev.cmd status` 检查状态，验收完成后执行 `script/dev.cmd stop`；详见[统一启停说明](../script/README.md)。分别手动启动时，先按根README准备后端和独立任务服务，再启动前端：

```powershell
npm.cmd --prefix frontend run dev
```

访问 `http://127.0.0.1:5173/`。Vite固定使用该地址与端口，将 `/api` 代理至 `http://127.0.0.1:8000`；Cookie和CSRF通过同源请求处理，前端不保存数据库或模型密钥。

```powershell
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run lint
```

测试使用Vitest、Testing Library和jsdom；`build`先执行TypeScript检查，再生成 `dist/`；`lint`使用Oxlint。脚本和依赖以[package.json](package.json)及锁文件为准。

## 模块入口

`src/main.tsx` 保留为 Vite 入口；`app/` 负责应用组合及全局样式，`features/` 按业务职责分组，`shared/` 保存请求、语言和下载等共享能力。组件单元测试与模块同目录，跨功能集成测试集中在 `src/test/integration/`，共用样例在 `src/test/fixtures/`。路径直接指向实际模块，不使用兼容转发文件；请求、项目访问和语言状态各保留一份模块实例。

| 文件 | 职责 |
| --- | --- |
| [app/App.tsx](src/app/App.tsx)、[global.css](src/app/global.css)、[App.css](src/app/App.css) | 应用组合与样式；全局样式先于应用样式加载 |
| [auth/AuthBoundary.tsx](src/features/auth/AuthBoundary.tsx)、[PasswordForm.tsx](src/features/auth/PasswordForm.tsx)、[LanguageControl.tsx](src/features/auth/LanguageControl.tsx) | 登录、改密/恢复、会话清理、跨标签同步与账号语言保存 |
| [projects/ProjectWorkspace.tsx](src/features/projects/ProjectWorkspace.tsx) | 项目创建、分页查询与文件工作区组合 |
| [ProjectList.tsx](src/features/projects/ProjectList.tsx)、[projectTypes.ts](src/features/projects/projectTypes.ts) | 列表字段、名称搜索、类型筛选、分页控件与项目类型 |
| [useProjectSelection.ts](src/features/projects/useProjectSelection.ts) | 独立选中项目、hash恢复及项目失权空态 |
| [ProjectDetails.tsx](src/features/projects/ProjectDetails.tsx)、[ProjectLanguage.tsx](src/features/projects/ProjectLanguage.tsx) | 名称/研究主题编辑、创建后类型只读与独立项目输出语言设置 |
| [ProjectSummary.tsx](src/features/projects/ProjectSummary.tsx)、[projectSummaryTypes.ts](src/features/projects/projectSummaryTypes.ts) | 真实任务/成果摘要、独立分页、来源与类型空态及响应校验 |
| [model-usage/ProjectModelUsage.tsx](src/features/model-usage/ProjectModelUsage.tsx)、[modelUsageMessages.ts](src/shared/i18n/modelUsageMessages.ts) | 概览中的累计美元预算、内部估算、预留、待核对与调用分页，只读且支持中英文 |
| [tasks/ProjectTasks.tsx](src/features/tasks/ProjectTasks.tsx)、[TaskDetail.tsx](src/features/tasks/TaskDetail.tsx)、[TaskEvents.tsx](src/features/tasks/TaskEvents.tsx) | 项目任务筛选分页、工作区精确历史成果和增量事件 |
| [tasks/TaskPendingAction.tsx](src/features/tasks/TaskPendingAction.tsx)、[TaskModelUsage.tsx](src/features/model-usage/TaskModelUsage.tsx)、[taskMessages.ts](src/shared/i18n/taskMessages.ts) | 服务端许可的幂等恢复、三级预算与任务页中英文 |
| [shared/api/client.ts](src/shared/api/client.ts)、[projectAccess.ts](src/shared/api/projectAccess.ts) | 会话/CSRF请求及工作区实例有效性检查 |
| [shared/i18n/index.ts](src/shared/i18n/index.ts)、[rootMessages.ts](src/shared/i18n/rootMessages.ts)、[errorMessages.ts](src/shared/i18n/errorMessages.ts)、[workflowMessages.ts](src/shared/i18n/workflowMessages.ts) | 全局中英文状态、稳定错误码翻译及分析流程文案；不翻译用户内容与历史成果 |
| [shared/components/ProjectDownloadLink.tsx](src/shared/components/ProjectDownloadLink.tsx) | Excel、PNG和Word受控下载 |
| [files/ExcelPreview.tsx](src/features/files/ExcelPreview.tsx)、[analysis/AnalysisSetup.tsx](src/features/analysis/AnalysisSetup.tsx) | Excel预览与分析字段配置 |
| [analysis/StatisticsResults.tsx](src/features/analysis/StatisticsResults.tsx)、[figures/BoxplotFigure.tsx](src/features/figures/BoxplotFigure.tsx) | 描述统计与云端箱线图 |
| [explanations/AnalysisExplanation.tsx](src/features/explanations/AnalysisExplanation.tsx)、[reports/WordReport.tsx](src/features/reports/WordReport.tsx) | AI解释与Word异步提交、状态轮询、失败重试及下载入口 |

## 当前进度

截至2026-10-08，阶段02第六步任务界面与等待恢复已通过用户验收，前六步均已验收。侧栏新增“项目任务”，提供统一任务分页/状态与类型筛选、来源和配置版本、详情、增量事件及待办；当前任务类型仅有箱线图、解释与Word。任务深链可刷新重开，跨项目、会话失效和失权清空旧内容；任务404不误移除项目。浏览器标签隐藏暂停读取，恢复可见后续读，进行中的恢复POST保持原请求，不因隐藏标签重复提交。

任务详情只读显示任务、项目和用户三级累计美元预算、内部估算、预留、待核对及调用分页；预算未配置不显示为零，未知用量不显示免费。成果按该任务保存的引用展示精确历史PNG、解释与Word，不跳到最新分析；Word下载文案隐藏系统文件名中的哈希。恢复按钮仅由服务端`allowed_actions`提供，使用必填幂等键及任务/输入版本，成功或冲突后重新读取，响应未确认且输入未变时复用原键和请求体。预算/配置等待可显式继续，尚未提交的模型调用按原策略和预算执行，已有调用沿用结果；未知提交及无消费者的资料/研究计划待办只读。LangGraph、检查点和取消尚未实现。

第六步验收前，前端全量385项（55.13秒）及build/lint通过；验收后`dev.cmd stop/status`均成功退出，前端、后端、Worker、dispatcher和RabbitMQ五项服务停止，broker卷保留。前六步作为本次阶段节点归档于 `feat/stage02-unified-tasks-models`，提交编号及远端同步状态以 Git 记录为准。此次收尾只停服和更新文档，未重跑功能回归，未调整本机模型配置、预算或预留。最新范围与证据见[阶段02清单](../docs/开发阶段/阶段02-统一任务与模型调用.md)和[第六步交付记录](../docs/开发记录/阶段02/任务界面与等待恢复交付记录.md)。验收后只读未发现新增Word或模型调用，等待/恢复记录为0；用户通过反馈不扩展为真实等待恢复或新增报告逐项手测。

历史记录：2026-10-08第三步统一模型调用与预算验收时，阶段02保守完成10/57项，绘图和解释当时尚未迁入；第三步前端全量340项、build和lint通过，两处旧测试的act警告未产生失败。该次范围见[第三步交付记录](../docs/开发记录/阶段02/统一模型调用与预算交付记录.md)。

阶段01适用范围已验收收尾，共75/79项并提交为 `4e0d139`；剩余4项为邮件服务及公开注册相关条件项（DB25、BE21、FE15、QA15），按当前范围延期。历史证据见[阶段01清单](../docs/开发阶段/阶段01-数据库迁移与用户项目基础.md)和[PC键盘操作与阶段验收记录](../docs/开发记录/阶段01/PC键盘操作与阶段验收记录.md)。

当前图表、解释和Word生成引擎仍为中文，项目默认输出语言尚未接入这些生成流程；切换界面语言或保存偏好不翻译用户输入、不回写历史成果、不重发生成请求。

2026-10-07项目结构整理、UI三步改版及分页、顶部栏和侧栏微调已通过用户手工验收。随后弹窗反向Tab焦点及分析解释页共享模型配置提示两项修复也已验收，交付时前端23文件299项测试、构建与lint通过，历史证据见[UI第三步交付记录](../docs/开发记录/项目维护/前端UI第三步交付记录.md)。

6项体验修复及侧栏切页动效优化已通过用户验收，涵盖切页定位、长列表预览反馈、进入成果时刷新、读取错误恢复、账号菜单自动收起及统一按钮反馈。交付时前端24文件322项测试、构建与lint通过，独立复查无未解决的P1/P2问题。验收后服务已停止，用户已授权纳入阶段01收尾统一提交推送；实际提交及同步以Git记录为准，验证范围见[前端体验修复交付记录](../docs/开发记录/项目维护/前端体验修复交付记录.md)。

## 历史交付记录

2026-09-30，项目列表分页、名称搜索、类型筛选、独立工作区与权限空态已实现；用户确认本轮功能手动验收通过。翻页或筛选保留已打开项目，确认项目失权后清除旧内容。交付时前端14文件195项测试及构建、lint通过，详细证据与限制见[列表交付记录](../docs/开发记录/阶段01/项目列表分页与权限空态交付记录.md)。

2026-10-03已实现项目任务与成果摘要，前端15文件206项测试、构建及lint通过。打开项目后可刷新摘要、查看历史状态与来源、下载已保存PNG/Word；未开放的写作、期刊、学校和修改功能明确显示空态。用户已启动前后端并确认人工验收通过、图片和Word下载正常；开发侧内置浏览器下载观察与用户验收证据分别记入[摘要交付记录](../docs/开发记录/阶段01/项目任务与成果摘要交付记录.md)。当时阶段01尚未完成，当前状态以[阶段01清单](../docs/开发阶段/阶段01-数据库迁移与用户项目基础.md)为准。

2026-10-03密码安全交付：新增登录后改密和登录页恢复码入口，成功清理工作区并要求重新登录；15秒超时、取消、错误及迟到Cookie响应重同步均有回归。当时前端16文件234项、build/lint通过，独立审查Approved；用户验收后已提交 `6d22d1f`，当时阶段01为60/79项，详见[密码安全交付记录](../docs/开发记录/阶段01/会话撤销审计与密码恢复交付记录.md)。

2026-10-05第5项已完成开发验证，用户已确认本轮验收通过；当时阶段01为66/79项。用户授权更新文档后以“开发阶段01：实现统一错误码、双语界面与语言设置”提交并推送，验收服务已停止，实际提交编号与远端同步以Git记录为准。共享i18n覆盖登录、密码、项目和Excel→Word界面；已登录账号通过独立 `PATCH /api/v1/auth/preferences` 保存 `ui_language`，登录/刷新恢复账号偏好，匿名切换只保存在内存。项目默认输出语言通过独立 `PATCH /api/v1/projects/{id}/language` 保存，不混入名称/主题编辑。错误按已知 `code/params` 翻译，未知异常使用本地安全提示，旧 `message` 仅为后端兼容字段。

第5项交付时，前端19文件256项通过（11.65秒），build/lint通过；隔离浏览器完成匿名EN、登录恢复ZH、账号/项目EN保存与刷新、旧统计和中文字段保持、退出清理与重新登录恢复，临时schema/资产/端口已清理。证据见[双语交付记录](../docs/开发记录/阶段01/双语界面与语言设置交付记录.md)。当时第6项①迁移目标摘要、约束/索引核查和运行/迁移权限分离尚待用户确认；后续结果以当前进度及阶段验收记录为准。

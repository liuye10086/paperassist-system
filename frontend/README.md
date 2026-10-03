# PaperAssist 前端

使用React、TypeScript和Vite，负责登录后的项目工作台。后端启动、PostgreSQL连接及首个管理员初始化见[项目README](../README.md)；本机管理员已经初始化，不需要重复创建。

## 启动与检查

在项目根目录使用Windows PowerShell执行。首次运行或锁文件变化后安装依赖：

```powershell
npm.cmd --prefix frontend ci
```

先按根README启动后端，再启动前端：

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

| 文件 | 职责 |
| --- | --- |
| [auth/AuthBoundary.tsx](src/auth/AuthBoundary.tsx)、[PasswordForm.tsx](src/auth/PasswordForm.tsx) | 登录、改密/恢复、会话清理及跨标签同步 |
| [ProjectWorkspace.tsx](src/ProjectWorkspace.tsx) | 项目创建、分页查询与文件工作区组合 |
| [ProjectList.tsx](src/ProjectList.tsx) | 列表字段、名称搜索、类型筛选和分页控件 |
| [useProjectSelection.ts](src/useProjectSelection.ts) | 独立选中项目、hash恢复及项目失权空态 |
| [ProjectDetails.tsx](src/ProjectDetails.tsx) | 名称/研究主题编辑与创建后类型只读 |
| [ProjectSummary.tsx](src/ProjectSummary.tsx)、[projectSummaryTypes.ts](src/projectSummaryTypes.ts) | 真实任务/成果摘要、独立分页、来源与类型空态及响应校验 |
| [api.ts](src/api.ts)、[projectAccess.ts](src/projectAccess.ts) | 会话/CSRF请求及工作区实例有效性检查 |
| [ProjectDownloadLink.tsx](src/ProjectDownloadLink.tsx) | Excel、PNG和Word受控下载 |
| [ExcelPreview.tsx](src/ExcelPreview.tsx)、[AnalysisSetup.tsx](src/AnalysisSetup.tsx) | Excel预览与分析字段配置 |
| [StatisticsResults.tsx](src/StatisticsResults.tsx)、[BoxplotFigure.tsx](src/BoxplotFigure.tsx) | 描述统计与云端箱线图 |
| [AnalysisExplanation.tsx](src/AnalysisExplanation.tsx)、[WordReport.tsx](src/WordReport.tsx) | AI解释与Word报告入口 |

## 当前进度

2026-09-30，项目列表分页、名称搜索、类型筛选、独立工作区与权限空态已实现；用户确认本轮功能手动验收通过。翻页或筛选保留已打开项目，确认项目失权后清除旧内容。交付时前端14文件195项测试及构建、lint通过，详细证据与限制见[列表交付记录](../docs/开发记录/阶段01/项目列表分页与权限空态交付记录.md)。

2026-10-03已实现项目任务与成果摘要，前端15文件206项测试、构建及lint通过。打开项目后可刷新摘要、查看历史状态与来源、下载已保存PNG/Word；未开放的写作、期刊、学校和修改功能明确显示空态。用户已启动前后端并确认人工验收通过、图片和Word下载正常；开发侧内置浏览器下载观察与用户验收证据分别记入[摘要交付记录](../docs/开发记录/阶段01/项目任务与成果摘要交付记录.md)。本轮后续已实现会话撤销审计与用户改密/恢复；完整双语等仍待开发，阶段01整体尚未完成，以[阶段01清单](../docs/开发阶段/阶段01-数据库迁移与用户项目基础.md)为准。

2026-10-03密码安全交付：新增登录后改密和登录页恢复码入口，成功清理工作区并要求重新登录；15秒超时、取消、错误及迟到Cookie响应重同步均有回归。前端16文件234项、build/lint通过，独立审查Approved；浏览器检查入口与表单，用户已确认本轮前后端验收通过。阶段01为60/79项，下一项为全局双语、错误码及语言设置，等待用户确认后开始，详见[密码安全交付记录](../docs/开发记录/阶段01/会话撤销审计与密码恢复交付记录.md)。

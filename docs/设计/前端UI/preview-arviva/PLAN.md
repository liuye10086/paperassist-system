# Arviva 交互预览实施计划

> 使用 `subagent-driven-development` 并行完成独立页面模块，由主代理整合并进行浏览器核对。

**Goal:** 根据根目录 DESIGN.md 提供可交互、可审阅的独立前端预览，供用户确认后再实施正式前端。

**Architecture:** 静态 HTML、CSS 与原生 JavaScript ES modules。全部数据为内存中的合成样例，通过独立 localhost 静态服务访问；不接入正式前端、数据库、模型或其他外部服务。

**Tech Stack:** 浏览器原生 DOM / SVG / dialog，Python 标准库静态服务器；无新 npm 依赖。

## 共同约束

- 仅新增 `docs/设计/前端UI/preview-arviva/` 下文件，不修改正式前端、后端或旧预览。
- 主色 `#35613C`，浅底 `#F7F9F5`，白卡片，文字 `#20271F`，橙色小面积点缀，设计尺寸以 DESIGN.md 为准。
- 全程明确标注“交互预览 / 合成数据”；所有生成、上传、任务和下载均为本地演示，不能被理解为真实结果。
- 界面中英双语；研究样例正文保持原文。手机导航、键盘焦点、弹窗、未保存编辑需要可操作。
- 不提交、不推送，不启动正式业务服务，不请求真实登录凭据。

## 模块契约

`shared.js` 提供 `state`, `project()`, `t(zh,en)`, `e(value)`, `icon(name,size=18)`, `button(label,act,variant='secondary',iconName='',attrs='')`, `badge(label,tone='neutral')`, `head(kicker,title,description,actions='')`, `card(title,content,extra='',className='')`。

可用图标：grid, folder, file, chart, book, pen, message, layers, check, clock, arrow, chevron, plus, search, upload, download, menu, close, settings, globe, user, leaf, alert, info, more, lock, logout, link, eye, save, refresh, filter, external, collapse。

页面模块导出 `renderResearch(page)` / `renderWriting(page)`，返回 HTML 字符串；不支持页面返回 null。模块导出 `handleResearch(action, element, api)` / `handleWriting(action, element, api)`，返回 boolean 表示是否处理。事件使用 `data-act`（click）、`data-change`（change）、`data-input`（input）；前缀分别为 `r-` 和 `w-`。

`api` 提供 `render()`, `toast(message)`, `modal({title,body,footer,guard})`, `closeModal()`, `navigate(page)`, `addTask(title,status,projectId)`。异步任务显式传入启动时冻结的项目 ID。所有用户输入输出使用 `e()`。事件委托由 app.js 负责。各模块只写自有状态 `state.research` / `state.writing`；公共当前项目由 `project()` 读取。

共享样式：`.button` + `.primary/.secondary/.ghost/.danger`，`.badge` + `.success/.warning/.info/.neutral/.danger`，`.card`、`.panel-head`、`.panel-body`、`.muted`、`.eyebrow`、`.grid-2`、`.table-scroll`、`.toolbar`、`.field`、`.tabs`、`.tab.active`、`.notice`、`.empty`、`.stack`、`.row`。

## 执行与验证

- [x] 应用壳、首页/项目列表、登录示例、用量/运营与弹窗交互（主代理）。
- [x] 文件、分析、成果、文献页面及本地演示交互（研究模块）。
- [x] 稿件、意见修改、学校模板/期刊页面及本地演示交互（写作模块）。
- [x] 整合样式，检查 JavaScript 语法及全部模块导出。
- [x] 浏览器验证：导航、新建项目、筛选、分析模拟、编辑保存、意见处理、语言切换、弹窗关闭、移动布局。
- [x] 核对无外部网络调用和正式业务修改，保存截图与 README 使用说明。

这是可逆的视觉原型，使用实际浏览器交互核对；不为样例渲染编写镜像单元测试，不运行正式项目全量回归。计划完成记录与限制写入本目录 README.md。

## 本轮：任务层次与视图拆分

用户要求：按同类功能或同一任务分组，避免进入任务后全部内容展开，优先页面跳转或视图切换，减少整页滚动。

采用项目 → 任务组 → 当前任务视图。项目概览只展示四类任务入口；侧栏按材料、分析、写作、修改分组；稿件正文/依据/检查/版本、评审意见/计划/对照/回复、分析概况/数据/方案/结果/图表分开显示。长正文与数据表允许必要滚动，不缩小字号或裁切内容来伪造无滚动。

- [x] 主代理修改 `app.js` / `shared.js` / `styles.css`：分组导航、紧凑工作台、项目任务入口、路径/视图路由与返回。
- [x] 研究模块代理修改 `research.js` / `research.css`：分析和成果视图拆分、文献列表/详情分开。
- [x] 写作模块代理修改 `writing.js` / `writing.css`：正文与辅助视图分开，单条评审意见按处理阶段切换。
- [x] 整合与独立审查：模块语法、视图切换不丢编辑、跨项目状态与浏览器前进/后退。
- [x] 浏览器核对桌面与窄屏布局、主操作可见性、实际交互，更新截图/说明/设计约束。

共享契约：`state.view` 表示当前页视图；`api.view(view)` 同页切换；`api.navigate(page, projectId?, view?)` 跨页导航。普通分段按钮使用 `.view-switcher`、`.view-button.active` 和 `aria-pressed`。只渲染当前视图，编辑草稿保持在项目内存状态；切页/换项目仍触发未保存保护。

仅迭代当前预览和设计文档。用户对本轮效果的确认与正式前端实施继续分开。

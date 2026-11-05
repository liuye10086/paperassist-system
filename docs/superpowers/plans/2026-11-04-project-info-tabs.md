# 第一步项目资料 UI 实施与验收

**目标：** 按 DESIGN.md 的模块切换规范，仅改造项目资料这一步；完成本地验收展示后等待用户确认。

**方案：** 沿用现有 `settings / activity / usage` 地址状态，以“项目资料 / 进展记录 / 项目用量”标签显示单一模块。资料编辑、记录及用量持续挂载，隐藏模块不参与布局和键盘访问，保留草稿、分页及用量子视图；长内容在当前模块内滚动。

**范围与约束：** React / TypeScript / CSS；不引入依赖，不修改 API、真实项目数据和后台任务。复用已有独立保存、取消及离开保护。保留另一会话修改，ProjectWorkspace.tsx 仅替换资料区接线。不提交、不推送，不进入第二步。

- [x] 更新 `projectHierarchy.test.tsx`：验证单模块显示、重复点击不收起、地址恢复、草稿与输出语言保留、键盘切换，以及跨项目离开保护；已确认新增预期在实现前失败。
- [x] 将 `ProjectInfoActions.tsx` 改为资料标签容器，用 `ProjectWorkspace.tsx` 传入现有资料表单和路由选择，删除重复的主题展示和下方展开入口。
- [x] 调整 `projectOverview.css`：紧凑标题与标签、清晰选中态、模块内部滚动、窄屏自然换行，不缩小正文或裁切操作。
- [x] 运行资料字段、项目层级、项目导航、用量相关定向测试与前端构建；检查修改差异，记录现存失败。
- [x] 复用已运行的本地服务，在独立 Edge 标签页检查资料、记录、用量切换、桌面与窄屏布局，保留验收入口。

验收边界：自动测试和浏览器布局检查不等同于用户验收；下一步需用户验收后继续。

## 本轮验证结果

- 5 个定向测试文件共 39 项通过：`ProjectInfoActions.test.tsx`、`projectHierarchy.test.tsx`、`ProjectDetails.fields.test.tsx`、`ProjectModelUsage.test.tsx`、`projectNavigationHistory.test.tsx`。最后调整用量保留后，相关 7 项再次通过。
- 补查 `ProjectDetails.test.tsx` 与 `projectWorkspaceNavigation.test.tsx`：合计 29 项通过、4 项既有失败。在运行时加载本轮 UI 修改前的源码、保留另一会话其余代码后，同样复现这 4 项失败：两个管理员返回后同地址任务入口、一个任务事件路由、一个文件列表读取次数断言。本轮未修改这些业务逻辑。基线源码和结果保存在 `script/.runtime/project-info-tabs-20261104/`，未回退工作区文件。
- 更新资料集成用例，使保存主题后验证实际编辑框中的已保存值；原用例查找的重复主题段落已按本轮 UI 设计删除。
- 前端构建通过；本轮 TypeScript 文件定向 lint 无警告；`git diff --check` 通过。构建仍提示现有主包大于 500 kB。
- Edge 实测 1366×900：单个可见模块、无业务折叠控件、页面无纵向溢出；390×844：页面宽度仍为 390，无横向溢出，字段与操作可读。
- 用量预算模块内部滚动到约 135 px，切换资料再返回后滚动位置与预算子视图均保留；浏览器前进/后退能恢复模块。临时名称草稿跨模块保留，验证后取消，未提交项目修改。
- 验收页面：`http://127.0.0.94:18094/#project=e8ba52c6-0e85-42ac-8205-dd70f1851f03&section=overview&view=settings`。复用已有隔离测试数据和服务；未重启另一会话后台任务。
- 截图：`script/.runtime/project-info-tabs-20261104/project-info-final.png`、`desktop-1366.png`、`mobile-390.png`。
- 当前状态：第 1 步等待用户验收；未提交、未推送；未开始第 2 步 UI 改造。

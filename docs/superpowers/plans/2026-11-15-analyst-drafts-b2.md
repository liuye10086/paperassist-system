# B2 分析员进度与补料草稿实施记录

**Goal:** 普通进度与补料说明在切换、关闭重开、刷新及提交后互不覆盖。

**Architecture:** 保留普通进度原有 `analyst-progress:<assignment>:<requirement>` 草稿范围，补料使用独立 `analyst-materials:<assignment>:<requirement>`。沿用 `useResearchDraft` 的账号和项目隔离、sessionStorage 持久化及登出清理。后端接口和已保存进度语义不变。

**Tech Stack:** React、TypeScript、Vitest、Testing Library、Edge；Windows PowerShell。

## 范围与选择

- 用户已验收 B1 并确认 B2；当前 `feat/frontend-rework`，HEAD `3932384616b186d2ec3b1df7e3856c0c9365a56c`。开始时只有 B1 的 6 个修改/新增文件，保留原状。
- 两个表单共享草稿键是覆盖根因；隐藏不同状态的草稿不能避免后续写入覆盖。选择拆分键，不改变通用草稿机制或增加后端草稿存储。
- 普通进度继续读取旧键，避免升级时丢失仍存于浏览器中的旧草稿。旧键无法可靠区分来源，因为普通进度也支持“待补材料”，因此不按状态猜测迁移，不复制到两个表单。
- 仅修改 `frontend/src/features/analyst/AnalystProgress.tsx`，在既有 `frontend/src/features/projects/AnalystWorkspace.test.tsx` 增加真实组件流程回归；不改 B1/B3，不提交、推送或合并。

## 执行与验证

- [x] 重新核对分支与工作区，跟踪两表单到 `useResearchDraft` 的读写路径。
- [x] 新增定向测试：普通进度两种状态与补料草稿隔离；关闭/重开与重新挂载保留；分别提交后另一草稿保留；保存失败后两草稿可恢复。
- [x] 在原代码运行新增用例，确认按预期复现覆盖。
- [x] 最小修复：按 `materialsOnly` 选 `analyst-materials` 或原 `analyst-progress` 前缀。
- [x] 执行分析员工作台、草稿恢复相关测试，TypeScript 与定向 lint。
- [x] Edge 在隔离测试环境验证草稿切换、刷新、提交及失败重试；不更改用户已有项目的进度。
- [x] 记录结果、限制与清理；等待 B3 确认。

定向命令（工作目录 `frontend`）：

```powershell
npm test -- src/features/projects/AnalystWorkspace.test.tsx src/features/research-results/researchDraftReload.test.ts src/features/research-results/researchDraftStrictRestore.test.tsx
npx tsc -b
npx oxlint src/features/analyst/AnalystProgress.tsx src/features/projects/AnalystWorkspace.test.tsx
```

## 验证结果

- 原代码：新增 5 个用例全部按预期失败，分别复现普通进度被补料替换、普通进度的待补材料草稿串入补料表单、提交了另一表单的内容、提交后另一草稿丢失、失败后重载串改。原有分析员工作台 21 项仍通过。
- 修复后：上述三个测试文件 **28 passed in 13.74s**（分析员工作台 26 项，其中新增 5 项；草稿恢复 2 项）。TypeScript 检查、改动文件 oxlint、`git diff --check` 均 exit 0。
- Edge 使用独立 `paperassist_system_test/pa_test_d3c31e98d7a1490090ff598e72232b1e`，临时后端 18081、前端 `http://localhost:15173`。创建临时分析员与两个合成项目，无外部模型调用。
- Edge 验证普通进度 A 与补料 B 在步骤切换、补料关闭重开、整页刷新后分别保留。普通进度首次提交注入 503 后两份草稿仍在；重试返回 200，发送的内容与首次请求完全一致。
- 保存普通进度 A 后补料 B 仍保留；新填普通进度 A2 后提交补料 B，服务端变为待补材料/B，而普通表单保留分析中/A2。再次整页刷新后，A2 原文与状态仍保留。
- 实际请求记录为 `[503, 200, 200]`；两个成功请求分别为普通进度 A / analyzing 和补料 B / needs_materials。另一项目没有进度写入，Edge 打开另一项目时进度输入为空。
- 隔离前后端已退出，测试 schema 已删除并只读复核；一次临时验收脚本启动失败所建的 schema 也已清理。用户的 8000/5173 服务仍运行。开发库业务记录数仍为 users=3、projects=5、files=21、reports=1、tasks=21、account_deletions=0。

本机证据目录（临时目录，未加入 Git）：

`C:\Users\86182\AppData\Local\Temp\paperassist-b2-browser-2f3de33f6bd24c1b9f4196c30f8c08cb`

包含隔离脚本、`fixture.json`、`progress-requests.json`、`progress-state.json`、`cleanup.json`、`final-check.json` 及 `materials-draft-retained.jpg`。失败注入只在临时服务外层生效，未改业务后端。

## 限制与交付边界

- 已被旧逻辑覆盖且没有其他副本的历史草稿无法自动恢复。旧共享键中的剩余草稿仍在普通进度入口读取，不猜测其来源。
- 草稿继续沿用既有浏览器会话存储，未增加跨浏览器或跨登录持久化。
- 保存失败的 Edge 场景为受控注入；未运行全量回归。B1 修改保留，B3 未开始，没有暂存、提交、推送或合并。

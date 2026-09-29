# 第四步：模型解释实施计划

用户已确认继续最小闭环的下一步；本步实现需求 V0.13 §5.7，完成后列出剩余步骤，不自动进入 Word 开发或提交推送。使用 writing-plans、test-driven-development 和 subagent-driven-development 工作流；沿用当前项目目录及已验收的组件。

## 设计与约束

选择“结构化解释 + 程序填入事实引用”，而非任意自由文本或纯固定模板：模型负责组织中文解释，程序只允许引用已有事实并填写数值。六部分为分析目的、使用数据、分析方法、主要结果、结果解释、论文描述；额外固定显示局限和待补充研究设计。自动引用核对不能保证语义正确，保留 AI 初稿标记与人工审核提示。

- 已保存当前统计结果和通过核对的 PNG 为前提；解释绑定 run ID、配置修订号、figure ID、两个文件哈希、提示词版本。
- 只发统计汇总、绘图元数据和必要标签；不发原始逐行数据、整份文件、图片、项目主题，不启用工具或再次计算。本步不识别图片像素，不编造研究目的、实验方法、显著性、因果或文献。
- 官方 Responses API 使用后台模式及 strict JSON Schema；沿用 backend/.env 的 OPENAI_API_KEY / OPENAI_MODEL，关闭 SDK 自动重试，无新增依赖。
- 模型文本通过 {{fact.key}} 引用受信事实；拒绝未知引用、裸写数字、缺失关键证据、额外字段和明显推断性结论。限制输出大小；标签作为数据，HTML 以纯文本呈现。
- SQLite schema 5 仅新增 explanations 与 explanation_jobs 表，旧项目、统计和图表保留。写入时再次检查配置/图版本；旧结果仍可读，新配置不能复用旧解释。
- 显式生成、幂等与并发锁、失败/不确定状态显式重试、后台查询、刷新/重启恢复；重新读取不提交新的收费请求。保存失败保留 response ID 继续读取。

## 后端契约

基础路径 `/api/v1/projects/{project_id}/files/{file_id}/analysis-runs/{run_id}`。

- GET `/explanation` 和 POST `/explanation` 返回 `{current_revision,is_current,figure_id,explanation,job}`。
- POST `{expected_revision:1,figure_id:"uuid",retry?:false}`；当前结果/图不匹配返回 409，尚未出图 409，未配置 API 503。初次/运行中 202，已保存/失败状态 200。
- job 为 `{id,status:submitting|running|completed|failed|uncertain,message,response_id,created_at}` 或 null。
- explanation 为 `{id,analysis_run_id,figure_id,figure_sha256,source_sha256,setup_revision,language,created_at,sections,limitations,engine,verification,provenance}` 或 null。
- sections 按顺序为 `{key,title,text,evidence:[{key,label,value}]}`，固定六部分，value 为已格式化字符串。engine 为 `{id,provider,model}`，verification 为 `{status,note}`。

## 任务及检查

- [x] 后端事实与 SDK：新增 explanation_content.py（事实/引用校验）、openai_explanation.py（提交/查询）；先测试未知引用、裸数值、缺失段落、单条/分组、恶意标签、拒绝与截断输出、官方 HTTP 契约，再实现。
- [x] 持久化与接口：新增 explanation_store.py（基于现有 ProjectStore 的组合存储）及 explanations.py；storage.py 仅升级 schema，main.py 增加路由和独立恢复循环。测试先观察 404，再验证版本绑定、幂等、并发、事务失败、重启、后台恢复、跨项目及文件完整性。
- [x] 前端独立任务：新增 AnalysisExplanation.tsx 及测试，嵌入 BoxplotFigure 已保存图之后；显式生成、轮询、错误/缺少密钥、旧版本、来源证据、切换取消；沿用现有样式与未保存字段保护。先失败再实现，通过 Vitest/build/lint。
- [x] 独立审查、后端全量 pytest、前端全量测试/build/lint、pip check、diff check。
- [x] 使用上一步独立临时目录内已生成的真实图进行一次真实解释 API 联调；检查段落及证据，浏览器恢复、重启及幂等；不修改用户项目数据，不显示密钥。
- [x] README 记录当前能力、配置、使用/验收路径、测试证据与限制；清晰区分自动验证和用户验收。

本步完成后，小闭环剩余：第五步 Word 分析报告（图、数据、解释和来源一起导出）；第六步完整闭环验收与收尾。PDF 仍是之后独立验证的完整产品能力，不混入此步。后续开发均等待用户确认。

## 完成记录

2026-09-29：后端 195 / 前端 64 项通过，build、lint、pip check、diff check 通过。独立审查两项内容校验问题已修复并复审。开发联调真实 API 生成一次，gpt-5.6-sol，六段 74 项事实引用；运行中重启且关闭网页后恢复，保存后再次重启及幂等验证通过。隐藏浏览器截图不可靠，未据此宣称完成全面视觉检查。

用户随后手动确认“选择已有图表 → 生成解释 → 核对文字和依据 → 刷新/重启确认恢复 → 修改配置并重新统计、绘图、生成解释”验收通过，并授权以“测试：AI分析解释”提交推送。README 已记录此结果并区分自动测试、开发联调和用户手动验证。Word 阶段尚未开始，等待用户确认。

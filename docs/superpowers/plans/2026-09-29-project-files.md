# 项目与文件保存实施计划

依据：需求 V0.13 §4.1、§5.2、§8；用户已确认本轮范围并要求开始开发。

## 方案

- 保留现有 FastAPI、React、Excel 解析和健康检查，不拆分依赖文件。
- 使用 Python 内置 SQLite 保存项目、文件信息、有限预览结果；UUID 命名的原文件放本地目录。相比 PostgreSQL 无需增加本机服务；相比散落 JSON 文件，关系和记录写入可用事务管理。多用户生产数据库仍待后续迁移。
- `PAPERASSIST_DATA_DIR` 控制存储目录，默认 `backend/data`，相对目录以 backend 为基准。数据库与原文件必须一同备份；数据目录不提交 Git。
- 项目字段：名称（1–120 字符）、研究主题（1–500 字符）、类型 sci/thesis、创建/更新时间、文件数。文件字段：独立 ID、所属项目、原始名称、类型、字节数、SHA256、上传时间、parsed/failed 状态和错误原因。
- 上传先校验文件基本属性，再解析；成功或解析失败均保存原始文件与结果记录。原文件先写临时文件并重命名，再事务写数据库；数据库写入失败时清理本次原文件。进程强制中止造成孤立文件的恢复不在本轮承诺范围。
- 新接口：GET/POST `/api/v1/projects`，GET `/api/v1/projects/{id}`，GET/POST `/api/v1/projects/{id}/files`，GET `/api/v1/projects/{id}/files/{file_id}/preview` 与 `/download`。文件入口核对项目归属。原临时 Excel 预览接口保留。
- 页面复用 ExcelPreview：新建/选择项目、项目文件列表、上传后立即预览、再次打开历史文件、原文件下载；更换项目清除旧视图并取消旧请求，避免迟到响应串入另一个项目。
- 不加入登录、删除、统计、AI、报告或自动推送。保留用户对 README 的已有修改。

## 执行与验证

- [x] 先写项目/上传/重新打开/失败记录/同名文件/跨项目隔离/重启持久化测试，确认新接口尚不存在。
- [x] 实现 `backend/app/projects.py` 路由与模型、`backend/app/storage.py` 存储，复用上传校验和请求限制；加入数据目录配置与 Git 忽略规则。
- [x] 先写前端项目创建/选择、已有文件预览、刷新恢复、失败记录、切换项目竞态测试，再实现 `frontend/src/ProjectWorkspace.tsx` 并扩展现有 ExcelPreview。
- [x] 执行 `python -m pytest backend/tests -q`、`npm.cmd --prefix frontend test`、`npm.cmd --prefix frontend run build`、`npm.cmd --prefix frontend run lint`。
- [x] 用独立临时数据目录启动实际服务，经 Vite 代理验证上传、列表、切表所需数据与后端重启后保留；审查并修复问题。
- [x] 更新 README 当前能力、存储结构、PowerShell 命令、验证结果及边界，保留用户已有修改。用户已在手动验收后授权提交并推送。

验证结果：后端 52 项、前端 16 项测试通过，构建、lint、pip check 通过。实际 HTTP 与浏览器已验证历史预览及刷新/重启恢复。审查发现的并发上传更新时间回退已用失败回归测试复现，并改为单调更新。完整浏览器选文件上传的自动化仍受此前工具文件选择器限制，由 HTTP 与组件测试覆盖。

2026-09-29，用户手动启动前后端，确认“创建项目 → 上传 → 刷新 → 重启后再次预览”验收通过。同名文件、解析失败及跨项目归属的手动验收结果尚未反馈，不据此扩展手动通过范围。

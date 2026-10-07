# PC键盘操作与阶段验收记录

日期：2026-10-05。范围：阶段01第6项③，S01-FE12、QA13。**开发验证完成，2026-10-07用户确认最终验收通过。** 用户已确认第6项①②验收通过并授权③。开发前停止了前后端，第6项所有改动统一纳入本次交付；2026-10-07用户已提供提交信息并授权提交推送。

FE12、QA13完成开发验证，当前清单为75/79。剩余4项条件工作保持未勾，详见下文。阶段人工验收与提交授权分别记录，不将开发验证或既有验收当作自动提交指令。

## 本轮修改与验证结果

| 范围 | 已验证结果 |
| --- | --- |
| PC键盘操作 | Tab/Shift+Tab可达、Enter/Space激活、select方向键、textarea换行；登录后聚焦项目名称，编辑/密码表单进入聚焦首字段，取消/保存返回对应入口 |
| 标签与反馈 | 现有label、busy/alert/status保持，新增workspace内统一focus-visible；真实必填校验和错误登录重试，组件验证超时结束busy及安全提示 |
| 重复与隔离 | 认证同步ref锁阻止同事件批次双提交；15秒涵盖请求及恢复/登录response body；超时/卸载/会话切换取消旧请求，保留apiFetch迟到Cookie重新核对机制 |
| 自动回归 | 后端553项；前端21文件271项；类型收窄修正后受影响4文件57项、build/lint；脚本6项unittest与pip check通过，详见下表 |
| 浏览器验证 | Codex内置浏览器，18006同源、随机测试schema、两个合成账号/项目与六行Excel；真实键盘路径详见下文；无真实管理员登录或云端调用 |
| 独立审查与清理 | 前端及第6项后端/运维审查Approved；临时服务/标签已关闭，18006关闭，测试schema和public业务表均0；开发16表及5资产保持 |
| 用户人工验收 | ①②已通过；2026-10-07用户确认③最终验收通过，现行内测适用范围验收完成 |

焦点修复只在认证/表单模式切换时发生，普通项目刷新、文本输入和语言重渲染不持续聚焦。保留原生键盘语义，没有自定义快捷键或焦点陷阱。认证超时文案区分“未确认登录结果”和“未确认撤销会话”，不把客户端中止误报成服务端回滚。项目/密码原有超时与代际保护继续保留，`api.ts`未改动。

新增`keyboardFlow.test.tsx`6项、`authTimeout.test.tsx`9项。先复现焦点丢失、同批次重复请求和请求/body悬挂，再修正；真实浏览器旧构建中“忘记密码→恢复密码”焦点落到BODY，新构建聚焦恢复码字段。完整构建首次发现嵌套函数对`AuthRequest | null`的TypeScript收窄错误，通过给`restore`显式传入已检查的`AuthRequest`解决，不改变请求身份；修正后构建及受影响回归通过。

| 实际执行命令 | 本轮结果 |
| --- | --- |
| `.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q` | 553 passed，330.17秒 |
| `npm.cmd --prefix frontend test` | 21文件 / 271 passed，11.24秒 |
| `npm.cmd --prefix frontend test -- src/authTimeout.test.tsx src/keyboardFlow.test.tsx src/api.test.ts src/App.test.tsx` | 类型收窄修正后4文件 / 57 passed，3.28秒 |
| `npm.cmd --prefix frontend run build`、`npm.cmd --prefix frontend run lint` | 最终均退出0 |
| `.\backend\.venv\Scripts\python.exe script/test_setup_database_roles.py` | 6 tests OK；从根目录按模块名启动曾因import路径失败，改用该文件入口通过，无功能修改 |
| `.\backend\.venv\Scripts\python.exe -m pip check`、`git diff --check` | 通过；Git仅有既有LF/CRLF转换提示 |

前端独立审查另运行4文件62项（3.19秒），随后第二审查确认显式参数的类型修正保持原语义；没有把各专项数累加为全量数。

## 隔离浏览器与数据保护证据

本轮使用`backend/backups/keyboard-acceptance-20261005T045434342059Z/`，独立schema为`pa_test_212c7a35d9554292aa863b7c1c76cd2d`。两个账号仅为`keyboard-a@example.local`、`keyboard-b@example.local`；A有合成SCI项目、六行Excel和配置v1/本地描述统计，B有空项目。关闭worker，API key为空。界面基于最终构建重新加载，未接触开发账号或开发资产。

实际路径与结果：

1. 邮箱初始焦点→Enter触发原生必填提示；Tab到忘记密码→Enter后恢复码获焦；四次Tab→Space返回登录，焦点回忘记密码。未输入新密码或提交改密/重置。
2. 输入错误合成密码显示“账号或密码错误”；Shift+Tab/Tab可回字段修改并Enter重试。登录A后项目名称获焦。
3. 键盘输入项目名，select方向键选择毕业论文，主题Enter保留换行，Tab/Enter创建；搜索框Enter筛选合成SCI，Tab/Enter打开结果。
4. Tab到编辑入口，Enter聚焦名称；Tab/Space取消返回编辑入口；再次编辑合成名称并保存，焦点仍回编辑入口，列表与详情同步更新。
5. 项目默认语言用方向键改英语、Space保存；来源信息Enter可展开。文件预览可键盘到达，六行两列表格及可滚动区可Tab聚焦；分析文件用方向键选择，恢复统计总体n=6、均值3.5，原配置和数值可读。
6. Shift+Tab可以逐项返回顶部，覆盖下载链接、上传控件、工作表、分析控件、摘要及项目控件。界面语言方向键切英语；合成项目名/原数据保持，改密入口Enter聚焦当前密码，取消后返回入口。
7. 退出A后清hash/工作区并恢复匿名中文，邮箱获焦；登录B只显示B的项目，不含A项目、文件或预览。最后退出B并关闭测试标签。

本轮可见紫色焦点经浏览器截图检查；合成账号B最终截图存于本机Codex可视化目录`keyboard-final-verified.jpg`。忙碌控件禁用时浏览器可能把activeElement暂置BODY；本轮错误登录和操作完成后的Tab/Shift+Tab仍从原位置继续，并非所有请求结束都强制聚焦。未将该观察夸大为屏幕阅读器或所有浏览器验证。

清理仅针对记录的进程PID、可执行路径、精确启动时间和本次创建的schema标记；服务进程树已停止，18006端口关闭，schema已删除，合成资产/证据保留。初次停止检查把PowerShell已解析的DateTime再次Parse，导致时间精度/时区不匹配并安全拒绝；修正为直接DateTime比较后通过。此前拒绝期间cleanup因端口未关而拒绝，没有删除仍运行的schema。初次fixture准备也曾因`inet_server_addr()::text`带CIDR后缀而拒绝，改用`host(inet_server_addr())`保留loopback检查后新建成功；失败state未创建schema。

`backend/backups/stage-final-evidence-20261005T045201920400Z/`保存本轮开发数据前后只读对照：16表（含版本表）列/全行值指纹一致，5份资产SHA256一致，测试库随机schema数0、public业务表数0。清理后的guard返回`verified`。以上对照在正常验收服务重新启动前完成；用户随后人工操作产生的数据变化不在该前后窗口内。

本轮将迁移报告、权限、接口与未验证边界汇总为当前版本快照。具体功能的历史测试、迁移和用户反馈继续以原交付记录为准，不重写其当时结论。

## 迁移演练与切换回退材料

| 材料 | 当前证据与详细记录 |
| --- | --- |
| 运行/迁移账号、数据库审计及0005升级 | [迁移核查与运行账号分权交付记录](迁移核查与运行账号分权交付记录.md)：独立角色、迁移秘密、目标/版本保护、最小权限、原数据与资产保持；①用户已验收 |
| 脱敏导入报告与复杂副本 | [导入与备份恢复演练交付记录](导入与备份恢复演练交付记录.md)：表计数/全值SHA、ID/seq映射、来源链、逐资产校验，真实子进程中断回滚、重试和重复幂等；②用户已验收 |
| 真实备份恢复 | 同上：独立PG18恢复指定0004成套备份，匹配旧代码读取，当前代码拒绝0004，显式升0005后原值/权限/读取检查；最终HTTP验证仅进程内ASGI |
| 切换与回退 | 同上“切换与回退操作约定”：停服和确认无写者→同一时间点成套备份→隔离实例恢复并核对→匹配程序读取→显式升级/复核→另行授权正式切换 |

实际证据保存在Git忽略的`backend/backups/`：导入`import-drill-20261005T042344224127Z`；恢复`recovery-drill-20261005T043041814743Z`；独立保护`rehearsal-evidence-20261005T041620830921Z`。失败现场及源码/资产副本保留；私有证据不进入Git。

当前开发目标为0005，运行与业务测试不支持SQLite回退。演练不恢复覆盖开发库或测试public、不改写归档、不代表开发库已回滚。正式切换另需授权；回退必须停服并恢复匹配时间点的数据库、资产和程序，不能只换连接、改版本号或盲目降级。可重跑命令及完整40字符`--legacy-ref`见演练交付记录。

## 当前权限矩阵

### HTTP与研究内容权限

| 能力或资源 | 匿名/失效会话 | 已登录所有者 | 他人项目或嵌套资源 | 管理员角色 |
| --- | --- | --- | --- | --- |
| health | 公开；配置/版本错误仍可失败 | 同左 | 同左 | 同左 |
| login/reset-password | 公开入口，仍需web安全标头/来源、凭据校验与限流 | 同规则 | 不提供读取他人凭据能力 | 不豁免认证保护 |
| me、偏好、改密、退出 | 401 | 仅本人/当前会话；改密成功撤销全部旧会话 | 无指定他人ID的绕过入口 | 仅本人能力 |
| 项目列表与创建 | 401 | 列表仅本人名下；创建绑定本人 | 他人项目不列出 | 列表仅自己名下 |
| 项目详情、编辑、默认语言、摘要 | 401 | 允许；项目类型创建后不可改 | 合法请求为404，含不存在/无主项目 | 无他人研究内容特权 |
| 文件、配置、统计、图表、解释、报告及下载 | 401 | 逐级核对owner与来源链 | 猜ID或替换嵌套资源不能越权 | 同样受归属检查 |
| 开通账号、停用、签发恢复码 | 无网页入口 | 无普通网页入口 | 无普通网页入口 | 本机CLI依赖OS/数据库凭据及明确操作，不是网页内容特权 |

当前会话Cookie为HttpOnly、SameSite=Lax，生产Secure由环境配置；绝对7天、闲置30分钟。修改请求需`X-PaperAssist-Client: web`及可信来源，已认证变更另需`X-CSRF-Token`。未认证401、安全保护失败403；合法跨归属请求404，畸形请求可能先返回422/403。会话切换清理旧工作区并忽略迟到响应。依据：[登录与项目归属交付记录](登录与项目归属交付记录.md)、[会话撤销审计与密码恢复交付记录](会话撤销审计与密码恢复交付记录.md)、[列表与权限空态交付记录](项目列表分页与权限空态交付记录.md)。

### PostgreSQL角色权限

| 操作 | 对应runtime | 对应迁移owner |
| --- | --- | --- |
| 数据库连接 | 仅各自项目数据库，禁止交叉CONNECT | 拥有各自数据库，供显式管理 |
| 业务表 | metadata白名单SELECT/INSERT/UPDATE/DELETE | 显式导入、迁移与维护 |
| schema/序列 | schema USAGE；sequence USAGE/SELECT | DDL与序列维护 |
| alembic_version | SELECT；拒绝变更与管理权限 | 显式迁移维护 |
| CREATE/ALTER/DROP/TRUNCATE/REFERENCES/TRIGGER、重置序列 | runtime拒绝 | 仅显式管理流程使用 |
| 管理属性与所有权 | 无superuser/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS、角色成员及所有权，无库CREATE/TEMP | owner不是服务运行账号；初始化超管只用于一次性本机交互 |

开发运行/迁移角色分别为`paperassist_runtime/paperassist_app`，测试为`paperassist_test_runtime/paperassist_test`。服务运行URL与私有迁移URL分开，服务不加载迁移秘密。数据库角色矩阵不能替代应用逐用户归属检查；未声明数据库RLS。详细验证见[分权交付记录](迁移核查与运行账号分权交付记录.md)。

## 当前接口契约索引

以下method/path/status按当前路由代码核对，本轮后端全量回归通过，但不把自动覆盖等同每个HTTP分支的人工穷举。路径均以`/api/v1`开头；`P=/projects/{project_id}`，`F=P/files/{file_id}`，`R=F/analysis-runs/{run_id}`。表内成功状态不代替认证、输入、冲突、资产或服务失败状态。

| Method / path | 成功状态与契约 | 详细材料 |
| --- | --- | --- |
| `GET /health` | 200，检查数据库连通/版本；不执行DDL | [数据库统一历史记录](PostgreSQL统一与迁移记录.md)、[当前分权](迁移核查与运行账号分权交付记录.md) |
| `POST /auth/login` | 200；email/password；设置Cookie，返回user/csrf_token | [登录](登录与项目归属交付记录.md) |
| `GET /auth/me` | 200；当前user/csrf_token | 同上；user已增ui_language，见[双语](双语界面与语言设置交付记录.md) |
| `POST /auth/logout` | 204；撤销会话并清Cookie | [登录](登录与项目归属交付记录.md)、[撤销审计](会话撤销审计与密码恢复交付记录.md) |
| `GET/PATCH /auth/preferences` | 200；`{ui_language}`，仅zh-CN/en | [双语](双语界面与语言设置交付记录.md) |
| `POST /auth/change-password` | 204；current_password/new_password，成功撤销全部旧会话并清Cookie | [密码安全](会话撤销审计与密码恢复交付记录.md) |
| `POST /auth/reset-password` | 204；recovery_code/new_password，15分钟单次码；成功撤销旧会话，不自动登录 | 同上 |
| `GET /projects` | 200；无分页参数返回数组，任一page/page_size/q/type参数出现返回items/total/page/page_size | [分页](项目列表分页与权限空态交付记录.md) |
| `POST /projects` | 201；name/research_topic/project_type，default_output_language默认zh-CN；返回Project | [项目编辑](项目基础信息编辑交付记录.md)、[双语增量](双语界面与语言设置交付记录.md) |
| `GET P`、`PATCH P` | 200；读取Project；PATCH仅name/research_topic，拒绝project_type及其他字段 | [项目编辑](项目基础信息编辑交付记录.md) |
| `GET/PATCH P/language` | 200；PATCH仅default_output_language，返回完整Project | [双语](双语界面与语言设置交付记录.md) |
| `GET P/summary` | 200；任务/成果独立分页及来源字段，future模块not_available，业务进展独立 | [任务与成果摘要](项目任务与成果摘要交付记录.md) |
| `GET P/files`、`POST P/files` | 200列表/201上传；multipart字段file，仅xlsx；解析失败可保存failed记录，返回file/preview | [历史小闭环验收](../历史小闭环/2026-09-29-workflow-acceptance.md) |
| `GET F/preview`、`GET F/download` | 200预览/原件字节；failed预览返回对应错误，下载继续归属与SHA核对 | 同上、[归属](登录与项目归属交付记录.md) |
| `GET F/analysis-profile`、`POST F/analysis-check` | 200字段/选择检查；profile需要sheet参数 | [历史小闭环验收](../历史小闭环/2026-09-29-workflow-acceptance.md) |
| `GET/PUT F/analysis-setup` | 200；GET配置或null；PUT按expected_revision保存并核对来源 | 同上 |
| `GET F/analysis-result`、`POST F/analysis-runs` | 200；统计状态/结果，POST期望修订一致，重复复用原run | 同上 |
| `GET R/boxplot`、`POST R/boxplot` | GET 200状态；POST运行中202，否则200；expected_revision与retry，幂等/来源校验 | [历史绘图契约](../历史小闭环/2026-09-29-boxplot.md) |
| `GET R/boxplot/image`、`GET R/figures/{figure_id}/download` | 200 PNG；前者download参数选择inline/attachment，后者按精确历史ID下载 | [摘要与历史成果](项目任务与成果摘要交付记录.md) |
| `GET R/explanation`、`POST R/explanation` | GET 200状态；POST运行中202，否则200；expected_revision/figure_id/retry | [历史小闭环验收](../历史小闭环/2026-09-29-workflow-acceptance.md) |
| `GET R/report`、`POST R/report` | GET 200状态；POST新报告201、复用200；校验修订/figure_id/explanation_id | 同上 |
| `GET R/report/{report_id}/download` | 200 DOCX字节；精确来源链及文件完整性检查 | [摘要与历史成果](项目任务与成果摘要交付记录.md) |

公开Project当前为8字段：id/name/research_topic/project_type/created_at/updated_at/file_count/default_output_language。分页历史记录中的7字段是语言功能加入前的快照，增量见双语交付。项目默认语言供未来任务使用，当前生成仍固定中文，不翻译历史成果。

统一HTTP错误为`{detail:{code,message,params}}`；保留HTTP状态，参数按码白名单过滤，未知异常安全兜底。401未认证，403安全保护，404合法资源不存在/不归属，409版本/来源/完整性冲突，410部分成果文件缺失，422请求/分析校验，429限流带Retry-After，503配置/存储/外部服务问题；具体错误由各入口契约决定，不能把状态码当作所有资源的完整列表。细节见[双语错误契约](双语界面与语言设置交付记录.md)及对应功能交付。

读取图表/解释状态可能触发现有云端任务查询和完成状态写回，不把所有GET宣称为纯只读。离线导入/恢复演练关闭worker和真实key；本轮键盘测试须使用合成任务或模拟provider，不触发真实云端。

## 条件工作与阶段完成口径

| 条目 | 暂缓原因与已有适用能力 |
| --- | --- |
| S01-DB25 | 邮件验证/恢复凭据分支未启用；管理员恢复码摘要、期限及使用/撤销状态已实现，不能当作邮件能力 |
| S01-BE21 | 现行内测由管理员CLI建号，不开放公开注册、邮件验证/激活 |
| S01-FE15 | 对应注册/邮箱验证/重发页面未启用；登录与管理员恢复码入口不代替它们 |
| S01-QA15 | 密码、恢复码与内测策略适用部分已验证；邮件/公开注册分支未实现，整体仍未勾 |

这4项不是已完成或被删除的需求。以后调整内测开通方式或启用邮件，应另行细化实现与验证。FE12/QA13本轮通过，当前口径为“开发侧75/79，现行内测策略下适用75项完成，4项条件工作暂缓；阶段人工验收已通过（2026-10-07）”，不写完整79项或完整产品完成。

## 已知限制与未验证范围

- 用户①②验收通过与此前图片/Word下载反馈分别保留；管理员全部历史研究资料逐项核对尚未单独确认，不由整体验收推定完成。
- 最终旧0004/当前0005恢复HTTP是进程内ASGI，不代表旧程序真实TCP或浏览器验证；只覆盖指定快照/匹配代码，不覆盖不同版本、备份之后的数据、开发库真实回退、断电/磁盘损坏/断网恢复。
- 合成未完成job导入证明状态保持与扫描发现，不证明业务job完成或真实云端续跑。未知JSON业务语义、AI解释研究适用性和全部PNG/Word排版仍需人工判断。
- 生产HTTPS/反向代理、多用户容量、消息队列/多worker可靠调度、管理员网页、长期备份保留/清理策略未完成；运行角色分权已完成本机指定范围，不能外推生产部署已就绪。
- 本轮键盘操作在一个PC内置浏览器实际观察；超时、同批次双提交与迟到响应依靠组件模拟测试，未在浏览器注入断网故障。密码提交由既有自动回归覆盖，本轮浏览器只进入与取消，未输入新密码。没有云端生成、全面WCAG、屏幕阅读器、移动端或所有浏览器兼容验证。

## 用户确认与后续

已确认：第6项①②验收通过；2026-10-07用户确认③最终验收通过，现行内测适用范围验收完成。用户要求第6项全部完成后再提交；2026-10-07已按约定停止前后端，用户随后提供提交信息并授权统一提交推送；不提前开始下一阶段或启用条件功能。

2026-10-05交付时运行`script/dev.cmd start`启动正常开发验收服务：前端`http://127.0.0.1:5173`，后端`http://127.0.0.1:8000`。`status`确认两进程运行，前端页面、后端health和前端代理health均200；匿名项目请求401。当时保留服务供用户验收；2026-10-07验收完成后已停止。提交前基线为`b9df4a4593c145acbaeb71aa9bb611462d060040`；随后提交与远端同步结果以Git记录为准。

2026-10-07用户最初确认验收通过时，仅同步用户验收结果、核对清单并停止验收服务；未修改功能代码或重跑功能全量回归，上述测试结果仍归属2026-10-05。清单保持75/79，四项条件工作继续未勾选；未提交推送。

## 统一提交前复核（2026-10-07）

用户已明确授权按“开发阶段01：实现：①分权与迁移核查，②导入与隔离真实恢复；③PC键盘与阶段记录”统一提交并推送，分支为`feat/auth-project-isolation`。此前等待提交信息的状态已结束，实际提交编号和远端同步结果以Git记录为准。

提交前重新运行：后端全量553项通过（351.21秒），前端21文件271项通过（13.53秒），build/lint、账号脚本6项unittest、pip check及diff检查通过。回归期间功能代码保持不变；浏览器与真实恢复证据沿用2026-10-05记录。候选52个文件均属于第6项代码、测试和文档；实际环境配置、研究资产、备份、运行证据、依赖和构建产物均未纳入提交，候选内容未命中本机现用秘密。验收服务保持停止，阶段01清单仍为75/79；提交后等待用户确认下一步。

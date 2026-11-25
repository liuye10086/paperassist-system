# PaperAssist Skills B02 真实验证与灰度确认清单

**2026-11-25 · B02 用户验收通过。** 本清单记录获批的一组 SCI 真实 A/B、一个公开 Bulk 固定版本和本机隔离灰度的账号、材料、费用与验证范围。 [实施与验证记录](2026-11-25-PaperAssist-Skills-B02实施与验证记录.md) · [总领方案](2026-11-25-PaperAssist-Skills技能系统总领方案.md) · [B01 记录](2026-11-25-PaperAssist-Skills-B01实施与验证记录.md)

## 1. 测试账号与项目

| 拟用身份 | 拟用项目及权限 |
| --- | --- |
| `b02-customer-a@paperassist.test` | 客户 A，拥有 `B02-SCI`。走综述初稿、材料确认、两份精确外发授权、候选回读与 Word。 |
| `b02-customer-b@paperassist.test` | 客户 B，拥有 `B02-BULK`。检查跨项目不可读、不可沿用对方授权，以及客户角色不能发起分析员预览。 |
| `b02-analyst@paperassist.test` | 分析员，只分配 `B02-BULK`。检查固定 QC/PCA、历史下载、分配撤回后的拒绝。 |
| `b02-admin@paperassist.test` | 隔离环境管理员，建立和撤回分配，配置写作准入和批次上限，核对任务、费用和运维日志。 |
| OpenAI 测试项目 | 初始范围指向 `paperassist-skills-b02`。用户后续确认使用与开发配置相同的密钥，即通过本机私有文件绑定的 `Default project`。控制台两条响应和用量已与回执匹配，当前组织数据控制已核对。支出日汇总含同密钥的另一笔请求，逐笔账单待核对。 [OpenAI 项目和服务账号](https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform) |
| NCBI `PaperAssist` | 沿现有应用标识，使用经确认可用于本轮的开发者联系邮箱。拟一次精确 PMID 检索，计划一次 ESearch、一次 EFetch，最多返回两条记录，按每秒不超过一次的目标串行运行。此规模可用无 API key 的模式。 [NCBI E-utilities 使用要求](https://www.ncbi.nlm.nih.gov/books/NBK25497/pdf/Bookshelf_NBK25497.pdf) |

四个 PaperAssist 测试账号及两个项目均已登记在隔离库。Bulk 保留历史显示名 `Airway public B03 acceptance`。OpenAI 密钥、会话凭据和 NCBI 联系信息通过本机私有文件或原配置管理。

## 2. 拟外发材料

**SCI 题目**为成人心脏图谱的解剖覆盖和证据范围。拟新建一份英文叙述性综述测试提纲，内容限定在两段摘要摘录所支持的方法、采样范围和局限。两臂使用同一份提纲、事实稿版本、来源顺序、输出语言和模型配置。

| B00 固定来源 | 本轮拟送入模型的摘要短摘录 |
| --- | --- |
| PMID `32971526` · PMCID `PMC7681775` · DOI `10.1038/s41586-020-2797-4` · CC BY 4.0 | “Here, using state-of-the-art analyses of large-scale single-cell and single-nucleus transcriptomes, we characterize six anatomical adult heart regions.” B00 摘要首段字符 `[354,505)`。 [文章与许可](https://pmc.ncbi.nlm.nih.gov/articles/PMC7681775/) |
| PMID `37438528` · PMCID `PMC10371870` · DOI `10.1038/s41586-023-06311-1` · CC BY 4.0 | “Here we combine single-cell and spatial transcriptomics data to discover cellular niches within eight regions of the human heart.” B00 摘要首段字符 `[130,259)`。 [文章与许可](https://pmc.ncbi.nlm.nih.gov/articles/PMC10371870/) |

摘录已逐字定位到 B00 的 `pubmed.json`，原文件 SHA-256 为 `a3423a148aa277984d99e951f0a5d4cd4eb3bb938c64bdc2bd030fa0cebcf59c`。两段 UTF-8 文本的 SHA-256 依次为 `c4ef0d23a95548b6b70a2c630a6789cb0133ce65e45825db77390a7aee5e5260`、`689a86a5ecdd1dcdde90f3dfb1cf3620a3242bbd19d1818e9f90eca4d6d0c4d9`。实际入包前比对实时书目和这两段字节，保存作者及来源、许可链接和摘录范围。PubMed 检索语句仅含 `32971526[PMID] OR 37438528[PMID]`。 [B00 固定材料](2026-11-25-PaperAssist-Skills-B00实施与验证记录.md#3-固定回归材料) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) · [PMC 转载与许可说明](https://pmc.ncbi.nlm.nih.gov/about/copyright/)

- **OpenAI 白名单。** 两段原文、配套公开书目字段及证据别名、上述新编提纲、既有写作合同和启用臂的固定技能指令。完整摘要、全文、补充材料、图表、旧 Word、其余三个历史 PMID、客户资料与原始科研文件留在外发白名单以外。
- **Bulk 本地材料。** 使用恢复的公开 `airway`（GSE52778）原固定处理版本 `e39f31ac-9fba-5e6a-91c1-cecf4d326103`，清单 SHA-256 为 `d02b9972241069a0b17e542edc90d3f23ae4e8e6ee3c8b69cd53ad80c2fce8ab`。隔离副本沿用原成员和标识，新增计算和模型外发均为 0。若以后原件不可恢复，备选为 Bioconductor 的公开 `airway` 1.32.0 counts 与样本元数据，按新来源登记输入摘要。B00 合成固定包继续作为工程对照。 [Bioconductor airway](https://bioconductor.org/packages/3.23/data/experiment/html/airway.html) · [原 Bulk 验收记录](../阶段04/2026-11-11-Bulk-B08-真实数据独立参考与兼容验收记录.md)
- **供应商留存。** SCI 的既有 Responses 合同为 `background=true`、`store=true`。按 OpenAI 标准应用状态口径估计响应留存至少 30 天，实际使用项以隔离项目的数据控制为准。确认范围包含这两份短摘录和生成结果按该合同由供应商处理和留存。 [OpenAI 数据控制](https://developers.openai.com/api/docs/guides/your-data)

## 3. 预算与提交上限

**推荐首轮模型费用授权上限 US$0.80（税费外）**。OpenAI `POST /v1/responses` 最多 **2 次**，Skills 关、开各一次，每次授权只含一份冻结请求，修正额度为 0。失败或状态未知占用该次名额。已取得响应 ID 时只对原 ID 续取。

| 核算项 | 首轮上限 |
| --- | --- |
| 模型和计价 | 仓库当前安装策略为 `gpt-6.1-sol` Standard 短上下文。每百万 Token 的输入、缓存读取、默认缓存写入、输出价格依次为 US$2.00、0.10、2.50、10.00。保持默认缓存档位，提交前核对实际有效策略和账单价格。 [官方模型价格](https://developers.openai.com/api/docs/models/gpt-6.1-sol) · [缓存档位](https://developers.openai.com/api/docs/guides/prompt-caching) |
| 单次预留 | 平台输入允许量最高 100,000，输出最高 12,000。按较高的默认缓存写入单价核算，最大预留 `100000 × 2.50/1000000 + 12000 × 10/1000000 = US$0.37`。两次合计最大预留 US$0.74。实际以两个冻结外发包的 `reserved_micro_usd` 和平台账单分别记录。 [平台计价](../../../backend/app/domain/model_usage/pricing.py) · [当前写作策略](../../../backend/app/domain/manuscript_writing/policy.py) |
| 支出围栏 | 仅给两份批准的请求摘要各签一次授权，环境采用每授权一提交、零修正。逐次核对已用和待确认额度、预留、响应 ID 和供应商费用。实际价格偏离、首笔状态未知或触及单次 US$0.40 / 合计 US$0.80 时暂停新提交。项目限额和提醒作为辅助控制。 [OpenAI 项目限额说明](https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform) |
| 其他 | NCBI 一轮只读业务检索。Bulk、Office、浏览器和回退检查的新增模型 POST 均为 0。本轮使用本机隔离环境。 |

## 4. 拟验收范围

| 项目 | 方法与通过条件 |
| --- | --- |
| SCI 真实对照 | 同一固定事实稿、两段证据、模型、语言、Schema、有效价格和资源上限。创建两份冻结预览，逐字段比对模型 wire，允许差异限定为 Skills 指令。逐次确认外发 SHA、调用/响应 ID、Token 与账单。候选结构通过现有校验，Word 可读；虚构引文、关键数字错误、把未确认论断标为已验证均为 0。两份稿件匿名后记录独立审读，不据一对样本推断普遍质量。 |
| Bulk 真实固定结果 | 先核对处理版本、清单和源成员 SHA，再读 `qc_missing`、`pca_scores`、`pca_variance`。逐项核对样本轴、缺失比例、得分和解释率，查原成员下载。预览过程新增计算任务、结果发布和模型提交均为 0。 |
| 角色、Office 与恢复 | 使用实际隔离账号在 Edge 走查两条入口，验证越权/撤回、角色路径、旧下载和已有响应 ID 的恢复。抽查代表性 SCI DOCX 在 Word、WPS 的章节、引文和版面。有响应 ID 按原 ID 续取，提交状态未知时仅对账。429/5xx、重复投递等异常继续用替身验证。 |
| 隔离灰度 | 拟用独立命名空间 `skills-b02`、浏览器地址 `https://localhost:18482`，仅绑定 `127.0.0.1`，使用独立库、队列、卷、账号和资产。API/Worker 固定同一 Skills 清单。两个批准项目限定角色与流程，外发准入锁定两份 SCI 预览摘要。外连限于 OpenAI 官方 Responses 和已批准的 NCBI E-utilities，Bulk 侧保持本地。依序演练暂停新请求、保留回执、原版本读取、开关回退和配对镜像回退。 |
| 样本量边界 | 首轮为 **一组真实写作 A/B、一个真实 Bulk 版本**。总领方案建议的 30 个写作案例和 20 个结果案例可先复用离线与固定夹具做矩阵。本轮记录逐次耗时、费用、队首等待与恢复，P95 和扩大灰度另按数据量确认。 |

## 5. 预检状态与启动顺序

- **已核对。** 基线 `5de3df8c219c4cd0db325b1a45a9c9dcedd9926b`、Skills 清单 `41d9a409636e7e174e02a561f3f7628c3bebaeafb40b0fa3f086aa71917f4c51`、B00 两份对照。Docker Linux 有 16 CPU、约 7.60 GiB，固定 PostgreSQL 与 RabbitMQ 镜像在本机，Edge、Word、WPS 已注册。默认发行底座缺失，备选底座 `sha256:8657a73a5633a7387d62e1af5ee8d68a64b70e3adcd6d91c175041fe6c133bca` 在断网容器中通过依赖精确匹配与进程身份检查。
- **灰度准入。** B01 的开关作用于进程。实施时须在 B02 隔离环境验证项目、流程、请求摘要及次数的准入。标准发行 Worker 位于内部网络，实时写作和 NCBI 默认关闭，需为批准的两个目标配置受控出口并先做拒绝用例。真实执行沿用发行运行模式和专用测试配置。 [发行配置](../../../compose.release.yml) · [写作准入](../../../backend/app/domain/manuscript_writing/policy.py)
- **发行预检已通过。** 用 R1 留存目录匹配全部 20 个锁定字体，系统 Python 运行官方发行脚本验证备选镜像、精确依赖、渲染器合约和进程身份。真实调用及本机部署均在预检通过后执行。 [发行预检](../../../script/release/release.py) · [字体版本锁](../../../backend/app/adapters/pdf_renderer_lock.json) · [实测回执](../../../script/.runtime/pa-skills-b02-1fa8d6fd/release-preflight.json)
- **批准后执行顺序。** 核对专用凭据、镜像和字体，构建及部署封闭灰度环境，验证项目准入、限额和白名单。完成批准的 PubMed 查证后固定同一事实稿，预览并授权两份 A/B 请求，按次数与预算执行。用实际账号检查 Bulk 与 Word/WPS，最后关闭新增外发并演练恢复和回退。确认、开关值、账单及测试结果均保留记录。

**执行结果**　NCBI ESearch、EFetch 各一次，OpenAI 共两次新提交。两臂预留合计 US$0.341000，按返回用量估算 US$0.047950。灰度外发已关闭。同批补验完成 Edge 四账号角色走查、两份 SCI Word 的区域数修订、WPS 字体复验及 OpenAI 项目与用量对账，新增模型提交为 0。逐笔实收金额受平台日汇总限制，扩大灰度与 P95 待另行验证。用户于同日另行批准启动 B03。 [B02 实施与验证记录](2026-11-25-PaperAssist-Skills-B02实施与验证记录.md) · [B03 实施与验证记录](2026-11-25-PaperAssist-Skills-B03实施与验证记录.md)

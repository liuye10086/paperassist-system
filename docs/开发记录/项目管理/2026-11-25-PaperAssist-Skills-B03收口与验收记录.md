# PaperAssist Skills B03 收口与验收记录

**用户验收通过 · 2026-11-25**。 [验收确认及范围](#8-用户验收)

2026 年 11 月 25 日，用户授权继续完成 B03 的剩余验证，沿用本机已有 OpenAI 测试配置和合成材料。原 B03 发布、失败回执和证据独立保留。分支为 `feat/runtime-skills`，基线为 `main@5de3df8c219c4cd0db325b1a45a9c9dcedd9926b`。 [B03 实施记录](2026-11-25-PaperAssist-Skills-B03实施与验证记录.md) · [首次补验记录](2026-11-25-PaperAssist-Skills-B03待验证项补验记录.md)

## 1. 修复与定向回归

- 毕业论文的呈现结构原先允许模型返回来源列表以外的标题。新首稿预览使用 `school-presentation-v2`，按冻结材料约束关键词、章标题和图题的别名及数组长度。未请求改写的标题数组长度为零。服务端仍核验别名集合、语言、证据和受保护的学校字段。旧 `school-presentation-v1` 的实际冻结请求已逐字节回读验证。 [学校呈现结构](../../../backend/app/domain/manuscript_writing/school_presentation.py) · [冻结协议](../../../backend/app/domain/manuscript_writing/frozen.py)
- 固定图件统计解释此前允许连接语自由调整，校验器对数值、记录口径和科学限制只接受受约束的句式。新 Skills 预览提供实际通过校验的六节句式，把坐标、分母口径、参与者和限制留在原事实变量中。审批摘要绑定此次实际指令。旧任务仍按它保存的指令和响应 ID 续取。 [统计句式](../../../backend/app/domain/figure_workbench/explanation_v5.py) · [外发审批](../../../backend/app/domain/figure_workbench/skill_approval.py)
- 三个针对性断言在改动前失败。实现后学校写作、统计解释、历史回执和 Skills 模块的 183 项定向回归通过。收口发行候选为 `sha256:420c2dbbe5a003a3a4be3279d2a4feece225d7716714881bf977f39067e8aa7c`，源清单 SHA-256 `444572bbbc68ed4e12fd81a924fbbee31e0be8baece89abeb1343e1c02a4b30d`。前端沿用 B03 构建，Skills 清单摘要保持 `5136e50e3a8d083e19d612b46343d537cb7e776194bea376f061dd56efb3c524`。 [失败复现](../../../script/.runtime/pa-skills-b03/closeout/product-red.log) · [定向回归](../../../script/.runtime/pa-skills-b03/closeout/product-green.log) · [发行回执](../../../script/.runtime/pa-skills-b03/release-image-closeout.json)
- 隔离 Linux API 与实际 PostgreSQL 的定向集成共通过 8 项，包含毕业论文到 Word、统计外发审批和 SCI 固定结果到 Word。测试库运行后已释放。 [集成回归](../../../script/.runtime/pa-skills-b03/supplement/office/closeout-model-contracts/pytest.log) · [测试库清理回执](../../../script/.runtime/pa-skills-b03/supplement/office/closeout-model-contracts/cleanup.json)
- 首次 Edge 回读拿到已保存的六节解释，任务页面按绘图任务的结构检查原图链接，误拒带固定原图的 `figure_explanation`。前端现按同一项目、文件和分析批次校验工作台的原图 ZIP，任务页按真实格式显示下载入口。旧绘图和历史下载继续用各自原来的路径规则。复现用例确认改动前失败，含该用例在内的 86 项前端定向测试全部通过。 [前端合同](../../../frontend/src/features/tasks/taskTypes.ts) · [复现记录](../../../script/.runtime/pa-skills-b03/closeout/frontend-stats-red.log) · [前端回归](../../../script/.runtime/pa-skills-b03/closeout/frontend-stats-green.log)
- 定向只读审查核对了新旧冻结合同、历史回执原样续取、统计发布校验和图包路径约束。审查无阻断项。学校标题的空集合来自真实回执，非空集合枚举和边界由定向测试覆盖。 [学校写作定向测试](../../../backend/tests/domain/test_school_writing_live.py) · [统计解释定向测试](../../../backend/tests/domain/test_explanation_v5.py)

## 2. Microsoft Word 原生复验

用户分别在两份合成副本启用编辑。Microsoft Word `16.0.20625.20108` 在毕业论文副本上执行「更新整个目录」，更新前后均为 10 页，6 项页码均为 `1、1、2、3、4、5`。保存后有 6 个 Word 生成的 `PAGEREF`，34 个可见文本段落和嵌入的 1 张 PNG 与原件一致。SCI 副本为 2 页，文件字节与原件一致。两份文档的 Word「字体替换」均报告所有字体可用。原件 SHA-256 核对通过。 [Word 原生回执](../../../script/.runtime/pa-skills-b03/closeout/office/word-closeout.json)

## 3. OpenAI 官方对账

复用项目密钥读取组织费用接口返回 `403`，权限响应报告缺少读取范围。用户在官方用量页登录后，导出 2026 年 11 月 25 日 UTC、同一密钥的分钟级请求与日级费用明细。首次补验的三次提交分别与唯一的分钟记录匹配，输入、短期缓存写入、缓存读入和输出用量逐项一致。按官方明细单价计算，三次分别为 US$0.0152635、US$0.022971 和 US$0.0121185，共 **US$0.050353**。同一密钥的日级基线共 6 次调用、US$0.1262235，全部令牌计费项逐一对平。费用以自然日分桶，单次归属由官方分钟活动与原响应回执匹配。 [本地对账回执](../../../script/.runtime/pa-skills-b03/closeout/billing-baseline.json) · [OpenAI 费用接口](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs) · [模型单价](https://developers.openai.com/api/docs/models/gpt-6.1-sol)

入账后同一密钥、同一模型的日级记录由 6 次、US$0.1262235 增至 8 次、US$0.161543。新增两次恰好与 `08:36`、`08:37` UTC 的唯一分钟记录匹配。费用分别为毕业论文 US$0.022471、统计解释 US$0.0128485，合计 **US$0.0353195**。各计费项目的令牌差额与新两次原回执一致。B03 两轮共 5 次提交，原来两次被产品校验拒收的调用也计费，归属本批合计 **US$0.0856725**。官方费用记录以日为粒度，按请求的归属由分钟用量、响应令牌和日级差额交叉确认。 [正式对账回执](../../../script/.runtime/pa-skills-b03/closeout/billing-verified.json) · [OpenAI 用量与成本说明](https://help.openai.com/en/articles/10478918-reviewing-api-usage-and-costs)

## 4. 两次真实提交和回读

使用同一 OpenAI 项目的 `gpt-6.1-sol`，仅提交两次原合成验证流程的新版冻结请求。外发材料为合成章内容和经约束的合成统计事实，图件和模板原文件保存在本机。以正常 API 完成预览、同意和派发，经 Worker 提交，使用原响应 ID 完成 7 次常规续取及 2 次凭回执读取原输出。两次提交均成功，预留共 US$0.282125。提交前的原失败回执保留，既有 SCI 首稿继续复用。 [真实任务回执](../../../script/.runtime/pa-skills-b03/closeout/model/records/verified-b03-model.json)

| 流程 | 验证结果 | 端到端任务用时 | 用量 |
| --- | --- | ---: | --- |
| 毕业论文首稿 | 九节可审核首稿，返回零组未请求的标题建议。Word 46,807 bytes，SHA-256 `2c86eafe10efe69f7fc94c7a319352302fe2da590f51de829ac7100158c22666`，嵌入原始 PNG 与冻结图件相同。 | 37.468 秒 | 输入 2,417，其中短期缓存写入 2,414。输出 1,643。 |
| 固定图件统计解释 | 通过原校验并保存六节初稿，图件仍绑定审批中的原始 PNG。 | 36.341 秒 | 输入 2,560，其中短期缓存写入 2,557。输出 645。 |

任务完成后撤回外发开关、临时外网转发及密钥注入。`skills-b03-closeout` 在回环 `https://localhost:18485` 提供成果复核，两条真实回执仍保存在原隔离库。修复统计任务页面后重新构建前端，TypeScript 检查通过。回读候选为 `sha256:1a05fc1935f400f58f8ac0cd2998a2db3305b092a3ac2d664f75498ee0b501ed`，源清单 SHA-256 `57c93473edabece21aef2a14241b039212b62d00200456d12b9c26191b59317d`。与真实提交候选对照，2,024 个非前端文件及其他各服务容器 ID 一致，仅替换收口命名空间的 API 静态构建。 [关闭外发记录](../../../script/.runtime/pa-skills-b03/closeout/model/records/external-closed.json) · [回读镜像](../../../script/.runtime/pa-skills-b03/release-image-closeout-readback.json) · [切换检查](../../../script/.runtime/pa-skills-b03/closeout/model/records/frontend-readback-switch.json) · [前端构建](../../../script/.runtime/pa-skills-b03/closeout/frontend-readback-build.log)

Edge `158.0.4370.33` 登录隔离的管理员、客户所有者和分析员。客户实际下载的毕业论文 Word 与原制品逐字节一致，分析员读取返回 `404`。指派分析员在成果页回读六节统计解释，实际下载图包，包内 PNG 与冻结原图相同。新的只读外发预览摘要与实际提交的摘要一致，客户访问原图、图包及统计任务均被拒。独立检查原模型输出及工作台保存材料，42 条必需事实的引用顺序、标签和取值均匹配。Edge 仅在测试进程校验本机服务公钥，Windows 证书安装和删除均为 0。 [Edge 回读](../../../script/.runtime/pa-skills-b03/closeout/model/edge-model-readback.json) · [事实回验](../../../script/.runtime/pa-skills-b03/closeout/model/records/live-output-verified.json) · [已导出 Word](../../../script/.runtime/pa-skills-b03/closeout/model/records/thesis-real-model.docx)

## 5. R 镜像发行审查

已对 B03 公开单细胞 Propeller 复算使用的 `sha256:728b440e94d7708a5bbf983da746ccf6e5ca2d93f93acd19c2dc19cc937c5d57` 生成并核对 SPDX 清单。核验包含 1,120 条 SPDX 记录、464 份独立告知或锁定文件、437/437 个 Conda 精确二进制与 458 条远程配方输入，Debian 精确源码 74/74，140 个 PyPI 源码包和 4 个无源码发行档的精确 wheel。868 个第一方镜像文件已与历史构建源逐字节对齐。公开 Aorta 固定队列的原生复算、项目发布、11 行组成 TSV 和 Edge 权限继续沿用首次补验的实测证据。 [发行审查](../../../script/.runtime/pa-skills-b03/closeout/r-distribution/README.md) · [机器核验](../../../script/.runtime/pa-skills-b03/closeout/r-distribution/verification.json) · [Aorta Edge 回执](../../../script/.runtime/pa-skills-b03/supplement/cell-r/gray-aorta-edge.json)

**原镜像外发暂缓。** 固定试点的目标镜像在数值进程内实际加载 `speckle → Seurat → cowplot`，较小的 Propeller 镜像也含这组依赖。按单一组合作品交付时，GPL-3 与 GPL-2-only 缺少已核实的兼容条款。仍有 ONNX Runtime `1.24.4` 的精确官方源码不可取，部分随 wheel 分发的原生库与资产未核销，第一方代码授权和实际接收方源码交付路径也需明确。本批保留内部复算，实际对外分发为 0。 [GNU GPL 兼容性说明](https://www.gnu.org/licenses/gpl-faq.html#AllCompatibility) · [GNU GPLv3 第 6 节](https://www.gnu.org/licenses/gpl-3.0.html#section6) · [明细和判定](../../../script/.runtime/pa-skills-b03/closeout/r-distribution/README.md#对外分发判定)

## 6. 本机容量与 P95

在原 B03 回环灰度 `18483` 对同一批固定成果测量 HTTP。API 和串行 Worker 各限制 1 CPU，Docker 可见 16 vCPU、约 7.60 GiB。空闲并发 1、4、8，另加混合任务时并发 4。每档五条路径、每路径 24 个样本。四档共 480 条有效请求，全部 HTTP 200，并通过内容摘要或原件校验。按最近秩计算百分位，P95 单位为秒。首次混合试跑被统计质控前置拦截，已完成固定源的正常确认，再复跑完整混合档。 [单并发原始记录](../../../script/.runtime/pa-skills-b03/closeout/capacity/20261125-081946-13607e/http-samples.csv) · [并发 4 和 8 原始记录](../../../script/.runtime/pa-skills-b03/closeout/capacity/20261125-084308-a673c8/http-samples.csv) · [混合原始记录](../../../script/.runtime/pa-skills-b03/closeout/capacity/20261125-090022-cb5d67/http-samples.csv)

| 读路径 | 空闲并发 1 | 空闲并发 4 | 空闲并发 8 | 混合并发 4 |
| --- | ---: | ---: | ---: | ---: |
| SCI 冻结预览 | 2.142 | 2.138 | 2.337 | 2.136 |
| 毕业论文冻结预览 | 2.108 | 2.111 | 2.445 | 2.114 |
| 历史论文 Word | 0.407 | 0.423 | 3.027 | 0.441 |
| Aorta 组成预览 | 8.359 | 6.873 | 11.514 | 10.117 |
| Aorta 原 TSV | 10.078 | 7.801 | 9.935 | 8.077 |

混合档并发读取与串行处理同时进行。12 个 DOCX 解析、6 个描述统计、4 个学校 Word 导出共 22 个任务，均首次执行成功，产物核对通过。统计覆盖 128、512、2,048 行三档，每档两份工作簿，各自核对记录数、均值与实际沙箱回执。77 条读取开始时间落在 Worker 实际执行期间。排队 P50/P95 为 227.33/322.22 秒，执行为 17.23/39.88 秒，端到端为 235.50/338.55 秒。从首次入队到末任务完成 566.82 秒。首次观察窗口到时后，只读追踪相同任务 ID 到完成，任务提交次数仍为 22。Worker 尝试无重叠，API/Worker OOM、模型调用和剩余队列均为 0。 [混合队列完整回执](../../../script/.runtime/pa-skills-b03/closeout/capacity/20261125-091233-ea2d3f-drained/summary.json) · [独立核验](../../../script/.runtime/pa-skills-b03/closeout/capacity/20261125-091233-ea2d3f-drained/independent-verification.json)

Aorta 是此次最慢的读取路径。该固定结果的来源验证涉及 93 项上游制品约 90.26 MiB，以及 11 个结果资产。Windows 对 `localhost` 的冷连接另观察到约 2 秒的 IPv6 回落，原始计时保留实际客户端耗时。六服务内存合计采样峰值为 1,460.55 MiB。Docker 的即时资源采样末尾缺约 32 秒，API 和 Worker 的累计 cgroup 计数覆盖该段，HTTP 和任务时间均完整。结论覆盖本机固定资料、只读接口及此档混合任务。生产规模 P95 仍需指定容量、峰值用量和目标指标，用代表性资料在对应环境实测。不同学校、数据和盲审质量按总领方案的样本范围登记。 [访问诊断](../../../script/.runtime/pa-skills-b03/closeout/capacity/loopback-connection-diagnosis.json) · [容量核验](../../../script/.runtime/pa-skills-b03/closeout/capacity/README.md)

## 7. 本机状态与回退

- `18483` 保留本机灰度，`18484` 保留首次真实调用和历史文件，`18485` 留作本轮改动及回执复核。三个回环健康端点均为 HTTP 200，两轮模型外发均已关闭。原任务、数据、图件与锁定文件留在各自命名空间，B02 原有灰度保持运行身份。 [环境复核](../../../script/.runtime/pa-skills-b03/closeout/environment-verified.json)
- 回退新增请求时，按总领方案关闭受影响的 Skills 流程和对应外发。继续使用可读取 `school-presentation-v2` 及已存统计 v8 指令的后端处理已冻结任务，有原响应 ID 的只续取。选择回读候选的同一后端配对，可单独回退前端应用，保持同一隔离库、资产和模型账本。仍处于早期候选的环境先暂停或排空当前冻结任务，再按配对回退手续更换版本。 [B03 回滚方案](2026-11-25-PaperAssist-Skills-B03实施与验证记录.md#5-停用与恢复)
- 当前工作区在 `feat/runtime-skills`。开发、测试和回执留存均在本机，Git 未暂存、提交或推送。用户手动操作已经完成。

## 8. 用户验收

2026 年 11 月 25 日，用户确认 B03 验收通过。验收依据包括本机灰度和角色走查、使用合成材料的真实模型回执、Word/WPS 代表样本、公开 Aorta 固定队列的 R 复算、官方费用对账和本机容量实测。 [B03 实施与范围](2026-11-25-PaperAssist-Skills-B03实施与验证记录.md) · [总领方案](2026-11-25-PaperAssist-Skills技能系统总领方案.md)

生产规模 P95 保留为目标环境实测项。R 原镜像对外分发继续暂缓。本批进入提交说明与文件范围确认，确认后在特性分支执行一次提交和推送。

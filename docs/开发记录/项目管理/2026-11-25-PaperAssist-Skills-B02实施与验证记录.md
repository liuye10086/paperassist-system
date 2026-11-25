# PaperAssist Skills B02 实施与验证记录

**2026-11-25 · B02 用户验收通过。** 验收范围包括发行预检、两条真实试点、本机隔离灰度及同批补验。 [总领方案](2026-11-25-PaperAssist-Skills技能系统总领方案.md) · [用户确认清单](2026-11-25-PaperAssist-Skills-B02真实验证与灰度确认清单.md)

## 1. 基线与隔离范围

- 工作分支为 `feat/runtime-skills`，基线为 `5de3df8c219c4cd0db325b1a45a9c9dcedd9926b`。沿用已验收的 B00 材料和 B01 工作区实现。B02 部署快照、白名单及测试脚本均存放在 Git 忽略的本机运行目录。
- 复用 R1 归档的 20 个字体原件。官方 `script/release/release.py preflight` 退出码为 0，字体摘要 20/20、精确依赖、渲染器合约及容器身份均通过，预检记录 `network_calls=0`。使用已核对的 API 底座 `sha256:8657a73a5633a7387d62e1af5ee8d68a64b70e3adcd6d91c175041fe6c133bca` 和 renderer `sha256:432dbf30dfc078f4a93d841e11d0b6bbefb12ace29428f0fa6cdf8600fe1d606`。 [发行预检](../../../script/.runtime/pa-skills-b02-1fa8d6fd/release-preflight.json)
- `skills-b02` 使用独立 PostgreSQL、RabbitMQ、执行锁卷、研究暂存卷、资产与账号。唯一发布端口绑定 `127.0.0.1:18482`，迁移为 `0094_sci_revision_chat`。API、Worker 和 Dispatcher 固定同一 Skills 清单 `41d9a409636e7e174e02a561f3f7628c3bebaeafb40b0fa3f086aa71917f4c51`。客户 A 持有 `B02-SCI`，客户 B 持有恢复所得的 Bulk 项目，分析员只获 Bulk 分配。 [离线灰度健康及隔离回执](../../../script/.runtime/pa-skills-b02-1fa8d6fd/release-source/receipts/offline-readiness.json)
- 默认发行进程保持外发关闭。真实任务在该 Worker 容器的短时专用进程执行，沿用产品的权限校验、任务租约、适配器和账本。独立 HTTPS 中继仅接收该 Worker 的连接，目的地为 `eutils.ncbi.nlm.nih.gov:443` 和 `api.openai.com:443`。未批准的主机、端口和非 CONNECT 方法均被拒绝，两个获准端点通过 TLS 证书校验。 [出口探针](../../../script/.runtime/pa-skills-b02-1fa8d6fd/egress-probe.json)

## 2. SCI 真实对照

使用确认的 NCBI 开发者联系配置执行一次 ESearch、一次 EFetch，间隔约 3.27 秒。实际返回 PMID `32971526` 和 `37438528`，题名、DOI 及两段 B00 固定摘录的 SHA-256 相符。所有者可下载原回执并核对摘要，另一客户得到 `404`。事实稿版本为 `b1b1d36d-68df-4980-8ba8-df1fa9a494d4`。 [NCBI 回执](../../../script/.runtime/pa-skills-b02-1fa8d6fd/sci-ncbi.json) · [来源白名单核对](../../../script/.runtime/pa-skills-b02-1fa8d6fd/sci-sources-approved.json)

Skills 关臂从 HTTPS API 冻结，开臂用同一发行镜像和隔离库，在专用进程调用同一个 FastAPI 路由并开启 `sci_narrative_review`。两份请求逐字段比对只差外层 Skills 指令。证据只有获准的两段摘要摘录和配套书目，原始文件、全文、图和其余历史文献未入包。同账号错误摘要得 `409`，跨账号授权得 `404`，幂等重放命中同一任务。两个授权各限一次新提交、零修正。 [冻结 SHA、授权及任务](../../../script/.runtime/pa-skills-b02-1fa8d6fd/sci-model-allowances.json)

| 项目 | Skills 关 | Skills 开 |
| --- | ---: | ---: |
| 冻结预留 | US$0.168295 | US$0.172705 |
| `POST /v1/responses` | 1 | 1 |
| 按已知响应 ID 续取 | 3 次 | 3 次 |
| 输入 / 输出 Token | 3,047 / 1,739 | 3,350 / 1,457 |
| 用量估算 | US$0.025006 | US$0.022944 |
| 本机专用进程执行和续取用时 | 41.52 秒 | 36.62 秒 |
| 任务及供应商状态 | `succeeded` / `completed` | `succeeded` / `completed` |

两臂合计预留 **US$0.341000**，按返回用量和安装价格估算 **US$0.047950**。两次新提交均在上限内。后续只对已持久化的原响应 ID 续取。按用户确认，本轮复用与现有开发配置相同的密钥。控制台补验已确认项目归属和用量，详见第 6 节。 [用量回执及隔离库任务计数](../../../script/.runtime/pa-skills-b02-1fa8d6fd/isolated-ledger-audit.json)

两份候选经当前结构校验。正文引文对应两条许可来源，所有者的 Word 重复下载字节相同，另一客户的正文和下载请求均返回 `404`。同一代表性 DOCX 在 Microsoft Word 的受保护视图和 WPS 只读模式均显示为两页，标题、段落、行内引文和参考文献可读。首轮 WPS 状态栏提示缺失字体，修订和复验见第 6 节。 [匿名稿 01](../../../script/.runtime/pa-skills-b02-1fa8d6fd/review-01.docx) · [匿名稿 02](../../../script/.runtime/pa-skills-b02-1fa8d6fd/review-02.docx) · [Office 检查](../../../script/.runtime/pa-skills-b02-1fa8d6fd/sci-office-review.json)

独立匿名初审核对了方法归属和 DOI，未发现错误数值、虚构引文、越界的具体生物结论或已验证声明。两稿均遗漏主题直接相关的 6 个与 8 个区域，两稿标题的 `Adult` 可能把第一条摘录的人群限定扩展到第二条。个别措辞对方法组合或发现目标表达偏强。候选科学审核状态仍为 `pending`。一组同题样本只支持记录逐次观察。 [匿名初审记录](../../../script/.runtime/pa-skills-b02-1fa8d6fd/sci-blind-review.json)

许可来源为 Litviňuková 等的 *Cells of the adult human heart* 和 Kanemaru 等的 *Spatially resolved multiomics of human cardiac niches*。两篇均采用 CC BY 4.0，实际使用范围为清单固定的两段摘要摘录。 [Litviňuková 等与许可](https://pmc.ncbi.nlm.nih.gov/articles/PMC7681775/) · [Kanemaru 等与许可](https://pmc.ncbi.nlm.nih.gov/articles/PMC10371870/) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

## 3. Bulk 固定结果与角色

- 恢复公开 `airway` 原件，采用原版本 `e39f31ac-9fba-5e6a-91c1-cecf4d326103` 和清单 SHA-256 `d02b9972241069a0b17e542edc90d3f23ae4e8e6ee3c8b69cd53ad80c2fce8ab`。定向迁入 19 张表的 245 条关联记录和 73 个原文件，复制及导入后校验通过。重跑迁入新增文件为 0。客户 B 拥有隔离库副本，历史显示名为 `Airway public B03 acceptance`。 [固定数值回读](../../../script/.runtime/pa-skills-b02-1fa8d6fd/airway-fixed-replay.json)
- 分析员获分配后，QC/PCA 三面板与归档逐项相同。8 个样本的 QC 缺失比例均为 0，PCA 得分为 `8×3`，前三个解释率为 `0.4699034572683748`、`0.21695926783515024`、`0.16696834196815674`。五项原成员的下载摘要和字节数匹配。预览前后均为 2 个历史任务、1 个结果版本和 66 项结果成员，新增任务、版本及模型调用均为 0。 [隔离 HTTP 回执](../../../script/.runtime/pa-skills-b02-1fa8d6fd/airway-isolated-http.json)
- 匿名访问 `401`，两个客户访问分析员入口 `403`，分析员未分配及撤回后访问 `404`。撤回后原会话仍有效，明细、三个面板及原文件读取均被拒绝。重新分配后同一会话恢复 `200`。客户 B 的研究设计、文件、交付历史及原始 counts 下载在撤回前后相同。 [分配撤回及恢复回执](../../../script/.runtime/pa-skills-b02-1fa8d6fd/airway-assignment-withdrawal.json)
- 同批 Edge 走查发现隔离库历史运行列表报 `409 bio_input_integrity_changed`。首次迁入缺少该运行的原检查点和候选文件，固定结果直达入口仍可读取。只读核对源归档后，在 B02 隔离库补齐 6 个原检查点和 5 份原候选文件及其存储记录，复跑新增文件为 0。实际分析员 HTTPS 请求的列表和运行详情恢复为 `200`，对应同一终态检查点、固定版本及 22 个候选成员。四个补齐的可下载候选成员与源 SHA-256、字节数一致，固定结果及历史下载继续可读。回执记录新增对象及条件回滚范围。 [恢复与条件回滚](../../../script/.runtime/pa-skills-b02-1fa8d6fd/airway-run-history/restore-receipt.json) · [重复执行](../../../script/.runtime/pa-skills-b02-1fa8d6fd/airway-run-history/replay-receipt.json) · [实际 HTTPS 回读](../../../script/.runtime/pa-skills-b02-1fa8d6fd/airway-run-history/https-receipt.json)

## 4. 外发停用与灰度回退

两个 SCI 授权已关闭，再发起请求均得到 `409`。隔离管理配置回退至外发关闭版本（修订 `3`），专用中继已停止。隔离库只记录两笔模型调用，原任务、回执及候选均保留。 [外发闭环回执](../../../script/.runtime/pa-skills-b02-1fa8d6fd/provider-closed.json)

| 候选 | Skills 开关 | 镜像 |
| --- | --- | --- |
| `d4bd459443e0429e998d32596018f531` | Bulk 开，SCI 默认关 | `sha256:f4f95f99af5b12d1a17d4a65c2a5969d991147617eea82ac3e3c6ef87d9852d6` |
| `216852d11536441b910808ef9ae4ed69` | 两条均关 | `sha256:18129395b02ad661147a807d4f415629a81d4e2a419e3a63245b90f25d3f67b0` |

两份候选包含同一 Skills 清单、前端和专用卷。 [配对镜像及开关校验](../../../script/.runtime/pa-skills-b02-1fa8d6fd/release-source/receipts/rollback-pair.json)

使用发行工具进入维护、切到双关、再切回原候选。双关时三个 Bulk 预览均返回 `404 runtime_skills_disabled`，原候选恢复后三个预览均返回 `200`。阶段比对中，五个 Bulk 历史下载及两份 SCI Word 的 SHA-256 和大小相同，两份冻结预览与账本仍精确绑定。恢复后的服务回到 `normal`，只在本机提供访问，外发保持关闭。 [实际切换与原件回读](../../../script/.runtime/pa-skills-b02-1fa8d6fd/release-source/receipts/rollback-execution.json)

定向离线回归覆盖 Skills 运行时、NCBI 传输替身和发行运维，99 项通过，用时 4.12 秒。通过替身覆盖 NCBI 429/5xx 路径。真实接入的重复写作请求命中原任务，后续模型调用均使用已保存的响应 ID。

```powershell
$env:PYTHONPATH = "$pwd\backend;$pwd"
& 'backend/.venv/Scripts/python.exe' -B -m pytest --noconftest -p no:cacheprovider -q backend/tests/domain/test_runtime_skills.py backend/tests/adapters/test_ncbi.py script/tests/test_release_operator.py
```

## 5. 验收状态与待验证项

| 项目 | 本轮状态 |
| --- | --- |
| Edge 两条业务入口和角色走查 | 已通过。四账号分别登录，覆盖 SCI Word、Bulk 原件和固定 QC/PCA、客户互访拒绝及管理员撤回复配。测试后确认 B02 临时 CA 在 Windows 当前用户及全机根证书库均不存在。 |
| WPS 字体兼容性 | 已在原稿诊断面板定位 `Courier` 和 `ＭＳ 明朝`。两份修订副本均实测 WPS 显示“当前文档没有缺失字体”。 |
| SCI 修订与证据范围 | 两份本机 Word 修订稿均在摘要和主题综合段补齐第一项的成人心脏 6 个解剖区域、第二项的人类心脏 8 个区域，已随 B02 交付验收。稿件的证据范围为两段固定摘要摘录。 |
| OpenAI 平台费用 | 两笔响应和 Token 已与 `Default project` 的日志和用量对齐，组织数据控制已核对。平台支出按 UTC 日汇总，当日 US$0.08 同时覆盖同一密钥的另一笔请求。B02 两笔合计 US$0.047950 为按回执用量和公示价格计算的估算值，逐笔实收金额尚未核验。 |
| 扩大灰度与性能 | 首轮已覆盖一个 Bulk 固定版本和一组 SCI A/B。扩大样本与 P95 待按确认清单另行验证。 |

## 6. 同批补验

- **Edge 角色走查。** 原生 Edge `158.0.4370.33` 在独立无头上下文用四个测试账号实际登录 `https://localhost:18482`，24 个检查步骤通过。客户 A 下载两份 SCI 历史 Word，客户 B 下载 Bulk 原始 counts，文件 SHA-256 与归档一致。两客户互访被拒绝，客户 B 直读分析员固定结果、预览和下载返回 `403`。分析员经「查看结果」的历史列表打开固定版本，QC 缺失比例、PCA 得分与方差和原成员下载通过。管理员在界面撤回后，分析员原会话刷新回到空列表，项目、固定结果、QC 和旧下载返回 `404`。管理员在界面复配后，原会话从正常入口重新打开固定结果，QC 恢复 `200`，分配保留给原分析员（修订 `5 → 6 → 7`）。Windows 临时 CA 仅导入当前用户库，测试后移除并复核两处证书库。前端分配、分析员工作区和结果入口的 4 个定向 Vitest 文件共 49 项通过。 [Edge 回执](../../../script/.runtime/pa-skills-b02-1fa8d6fd/supplement-20261125/edge-role-regression-20261125T053854Z-80a7cdc3.json) · [证书导入](../../../script/.runtime/pa-skills-b02-1fa8d6fd/supplement-20261125/edge-ca-install.json) · [证书移除](../../../script/.runtime/pa-skills-b02-1fa8d6fd/supplement-20261125/edge-ca-remove.json)
- **SCI 文字修订。** 复核两段 B00 摘录 SHA-256 后在两个本机 DOCX 副本定向修订。标题收窄到人类心脏图谱，第一项成人范围留在对应来源句，第二项按摘录表述研究目的。两份的引文编号、DOI 和参考文献保持一致。实际回读原始 A/B 历史 Word，所有者 `200`、其他客户 `404`，字节摘要与 B02 初次回执一致。本轮新增模型提交为 0。 [摘要来源与改动回执](../../../script/.runtime/pa-skills-b02-1fa8d6fd/supplement-20261125/sci-editorial-revision.json) · [历史 Word 回读](../../../script/.runtime/pa-skills-b02-1fa8d6fd/supplement-20261125/historical-docx-api.json)
- **字体复现和修订。** WPS 原稿检测到 `Courier` 和 `ＭＳ 明朝` 两项缺失。仅替换 `ＭＳ 明朝` 的对照副本剩 `Courier`；两份最终稿将这两个旧字体声明映射到本机 `Courier New` 和 `MS Gothic`，WPS 诊断面板均显示无缺失。正文、引用位置和页脚与文字修订稿一致，两份均为 2 页，离线渲染后逐页检查通过。字体替换限定于本机交付副本。 [WPS 与版面回执](../../../script/.runtime/pa-skills-b02-1fa8d6fd/supplement-20261125/sci-wps-supplement.json) · [修订稿 01](../../../script/.runtime/pa-skills-b02-1fa8d6fd/supplement-20261125/review-01-wps-corrected.docx) · [修订稿 02](../../../script/.runtime/pa-skills-b02-1fa8d6fd/supplement-20261125/review-02-wps-corrected.docx)
- **隔离账本。** 复核仍为 6 个任务、2 笔历史模型调用及 2 笔 NCBI 回执，外发开关保持关闭。 [本轮账本核对](../../../script/.runtime/pa-skills-b02-1fa8d6fd/supplement-20261125/ledger.json)
- **OpenAI 控制台。** 在 `Default project` 的 Logs 确认两条原响应 ID。用量页面分钟粒度的对应一小时显示 `gpt-6.1-sol` 两次，输入 `6,397`、输出 `3,196` Token，与应用回执逐项合计一致。11 月 25 日 UTC 日统计有 3 次请求，API 密钥分组只有一组。支出页面日明细显示 US$0.08，账面无法从该日同密钥支出单独拆出两笔。组织当前 API 调用日志为 `Enabled per call`，Playground 反馈、评估与微调数据、API 输入输出共享三项均关闭。两笔请求保留原 `background=true`、`store=true`。本次只读核对。 [控制台对账回执](../../../script/.runtime/pa-skills-b02-1fa8d6fd/supplement-20261125/openai-console-reconciliation.json) · [OpenAI 价格](https://developers.openai.com/api/docs/models/gpt-6.1-sol) · [Costs 日粒度](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs)

## 7. 验收交接

2026 年 11 月 25 日，用户确认 B02 验收通过，随后明确批准启动 B03。分支保持未暂存、未提交、未推送。 [B03 实施与验证记录](2026-11-25-PaperAssist-Skills-B03实施与验证记录.md)

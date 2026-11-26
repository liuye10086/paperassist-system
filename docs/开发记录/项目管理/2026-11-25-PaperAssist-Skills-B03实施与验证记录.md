# PaperAssist Skills B03 实施与验证记录

**2026-11-25 · B03 用户验收通过。** 本批在 B02 验收通过后获准启动，把同一套 Skills 运行时接入 SCI 研究论文首稿、毕业论文首稿、固定图件统计解释和单细胞组成结果。继续沿用原业务的权限、版本、授权及读稿和下载入口。最终复验和发行判定见收口记录。 [总领方案](2026-11-25-PaperAssist-Skills技能系统总领方案.md) · [B02 验收记录](2026-11-25-PaperAssist-Skills-B02实施与验证记录.md) · [B03 首次补验](2026-11-25-PaperAssist-Skills-B03待验证项补验记录.md) · [B03 用户验收](2026-11-25-PaperAssist-Skills-B03收口与验收记录.md#8-用户验收)

## 1. 基线与启用范围

本页保留 B03 当时的工作流和读数证据。B09 撤下组成试点入口，供者组、方向、组成比例、调整后 P 值和原表使用正式结果页。 [当前入口与试点退役记录](2026-11-26-PaperAssist-Skills-B09整理与验收记录.md#1-整理清单)

- 分支 `feat/runtime-skills`，主线基线 `5de3df8c219c4cd0db325b1a45a9c9dcedd9926b`，承接当前工作树 B00–B02 的未提交修改。B03 无数据库迁移。真实验证用 B02 的原件、账号、回执和灰度服务独立保留。 [B00 固定基线](2026-11-25-PaperAssist-Skills-B00实施与验证记录.md)
- `PAPERASSIST_SKILL_WORKFLOWS` 按流程逐个启用。新增的四个标识默认关闭。API 和 Worker 读取同一份技能包，可用 `PAPERASSIST_SKILLS_MANIFEST_SHA256` 固定发布清单。当前清单含八个技能、六条流程，SHA-256 为 `5136e50e3a8d083e19d612b46343d537cb7e776194bea376f061dd56efb3c524`。Windows CLI、隔离 Linux API 和开发 Worker 对当前只读源得到相同摘要。 [环境示例](../../../backend/.env.example) · [跨镜像校验回执](../../../script/.runtime/pa-skills-b03/skills-linux-verification.json)
- 开关只控制相应 Skills 路径。写作和图件解释继续受各自的外发、授权和模型账本控制。离线实施阶段数据库在独立本机测试容器中运行，模型用替身，真实 OpenAI 提交和外部文献 API 请求均为 0。随后在另一隔离环境按已确认额度做真实补验。 [B03 补验记录](2026-11-25-PaperAssist-Skills-B03待验证项补验记录.md)

## 2. 接入与验收路径

| 流程和角色 | 合同及固定材料 | 验收要点 |
| --- | --- | --- |
| SCI 研究论文，客户完整首稿 `sci_research_article` | 延用 schema 4，组合科学写作、研究论文及引用核验。使用合成的已上传研究事实、数值来源和固定 PNG。 | 新增内容体现在冻结请求的写作指令中。Methods 与 Results 的数值和证据别名、Discussion 的来源、PNG 字节沿用原合同。相同请求回读相同预览，按原响应 ID 续取。校验客户读稿、Word 和跨客户拒绝。 [业务用例](../../../backend/tests/integration/test_customer_sci_to_word.py) |
| 毕业论文，客户完整首稿 `thesis_initial_draft` | 延用 schema 3，组合科学写作、毕业论文及引用核验，使用已绑定的学校模板、当前章节配置和冻结的选材。 | 检查可写章节及其语言、引用和原图。姓名、签名、声明与模板原文件走本地处理。沿用学校格式复核、目录和 Word 路径，校验旧版本回读及导师修订。 [业务用例](../../../backend/tests/integration/test_customer_thesis_to_word.py) |
| 固定图件统计解释，获指派分析员 `statistical_explanation` | 延用 v5 固定图件解释，启用 Skills 时用 v8 授权合同绑定图件 ID、PNG 摘要、原事实、完整指令和确认记录。 | 六节解释沿用原证据校验。冻结外发摘要与实际发送指令一致，原图可继续下载。相同任务和已有解释优先复用，已有响应 ID 可续取。关闭 Skills 后新预览使用 v7。 [图件入口用例](../../../backend/tests/integration/test_b07_repair_versions.py) |
| 固定单细胞组成结果，获指派分析员 `single_cell_composition_preview` | 从单细胞结果页读取已发布 schema 5 `speckle_propeller` 的 `composition_results.tsv`，限定 `donor_unpaired`、`asin`、无批次调整和已确认的标签。 | 显示供体组、方向、原值、调整后 p 值和成员散列，沿用来源、成员和权限校验。支持分页、撤权及开关回退。只读请求新增任务和模型调用均为 0，原结果 API 和下载仍可使用。 [角色与下载用例](../../../backend/tests/api/test_single_cell_fixed_composition.py) |

SCI 与毕业论文从原客户工作台进入。首稿预览核对冻结材料、技能版本和指令后，再走原写作授权。退出确认后，同一份材料可以继续使用原冻结预览。修改材料须重新准备。局部修订、完整修订和建议沿用既有合同。保留仍服务于历史任务、候选、图件和 Word 的入口及恢复逻辑。 [写作入口](../../../frontend/src/features/customer/SciDraftGenerator.tsx) · [写作授权](../../../frontend/src/features/manuscripts/CustomerWritingConfirm.tsx) · [当前组成结果入口](../../../frontend/src/features/bio-insights/InsightResults.tsx)

统计解释回执保留实际确认人和分配修订，任务与计费保留项目归属。首次 POST 在提交账本事务中复验确认人的当前角色、分配及外发停用状态。已有响应 ID 按原账本续取，撤权的分析员无法访问任务和成果。待运行的 v8 同图解释与 v5 本地复用在写入时协调。已有合规解释、调用仅预留且尚未提交时，释放预留并读取原解释。 [授权与恢复](../../../backend/app/domain/figure_workbench/skill_approval.py) · [提交准入](../../../backend/app/domain/model_usage/service.py)

## 3. 固定单细胞 R 对照

沿用既有数值用例，八个合成独立供体，每组四个，每个供体 100 个细胞。固定比较 `stim` 相对 `ctrl`。镜像锁定为 `sha256:728b440e94d7708a5bbf983da746ccf6e5ca2d93f93acd19c2dc19cc937c5d57`，使用 R 4.4.3、`speckle 1.6.0`、`limma 3.62.1` 和 `statmod 1.5.2`。按运行前冻结协议，同引擎对照通过，两次新进程完整输出字节一致，SHA-256 为 `ab7e59f0404fc5521946545d195c0c0005df4fc30069f5adbfbced710ba118eb`。 [预先登记的验证协议](../../../script/.runtime/pa-skills-b03/r-numeric/PROTOCOL.md) · [数值与资源回执](../../../script/.runtime/pa-skills-b03/r-numeric/verification.json)

| 类别 | ctrl 均值 | stim 均值 | stim − ctrl | BH 调整后 p 值 |
| --- | ---: | ---: | ---: | ---: |
| T | 0.3300 | 0.5875 | +0.2575 | 0.00048353808306252034 |
| B | 0.4825 | 0.2650 | −0.2175 | 0.001906752541801201 |
| unknown | 0.1875 | 0.1475 | −0.0400 | 0.11249980986901548 |

独立算术核对逐供体组成、组均值、比例和差值，并从 R 提供的原始 p 值另算 BH 校正。原始 p 值和 moderated t 的验证范围是同引擎对照。使用供体为独立观测单位，表中方向和 p 值仅适用该合成夹具。 [Propeller 方法](https://academic.oup.com/bioinformatics/article/38/20/4720/6675456) · [复验说明和命令](../../../script/.runtime/pa-skills-b03/r-numeric/README.md)

另将同一批供体计数展开为固定细胞轴，走现有组成适配器和成果校验。用原始 TSV 字节验证 API 的只读展示逻辑，表 SHA-256 为 `a4b758e7ac82138b599977f682135f924b15450a5185e0bf7ece5901d6c3bd7f`。三类有变化的组成保留原始值，四类恒零项的差值为零、p 值留空。该对照覆盖原生计算到表读取，项目来源与权限另由隔离 API 用例验证。 [原始成果投影回执](../../../script/.runtime/pa-skills-b03/r-numeric/published-table-projection.json)

容器上限 1 CPU、4 GiB，禁用外部网络，未触发 OOM。两次复算进程含初始化分别耗时 8.14、8.09 秒，数值用例与两次复算合计宿主用时 27.93 秒。峰值进程 RSS 836936 KiB。该记录用于固定点复现，生产吞吐和 P95 另行测量。镜像内 `DESCRIPTION` 分别声明 `speckle` 为 GPL-3、`limma` 为 GPL (>=2)、`statmod` 为 GPL-2 | GPL-3，记录了 134 个加载的 R 命名空间及其版本和许可声明。目标发行物和分发义务待按部署方案复核。 [组件取证](../../../script/.runtime/pa-skills-b03/r-numeric/provenance.json) · [statmod 上游](https://cran.r-project.org/web/packages/statmod/index.html)

## 4. 隔离环境定向回归

| 验证组 | 结果与范围 |
| --- | --- |
| SCI 研究、综述和运行时 | 23 项通过，含实际 API 路由、隔离 PostgreSQL、模型替身回执和 Word 字节检查。SCI 流式写作与毕业论文客户角色另有 7 项 Windows 定向回归通过。 [SCI 对照](../../../script/.runtime/pa-skills-b03/sci-research-green.log) · [历史与角色回归](../../../script/.runtime/pa-skills-b03/writing-history-roles-final.log) |
| 毕业论文 | 两种开关下客户首稿生命周期及领域、运行时用例共 42 项通过。学校格式领域定向回归 21 项通过。目录缓存由渲染替身提供，DOCX 结构和格式规则由程序核对。 [首稿与恢复](../../../script/.runtime/pa-skills-b03/thesis-green-01.log) · [学校格式回归](../../../script/.runtime/pa-skills-b03/thesis-domain-02.log) |
| 固定图件统计解释 | 最终 Linux 串行验证 42 项通过。含 7 项业务集成，覆盖图件与精确指令绑定、分配撤回、自有项目确认人降权、停用外发、原 ID 恢复、并发复用、预留释放和原 PNG/Word。其余 35 项覆盖历史回执与账本来源准入。并发建测试 schema 触发隔离库锁容量限制后，已串行复验。 [最终集成与守卫回归](../../../script/.runtime/pa-skills-b03/stats-frozen-serial-20.log) |
| 共享网关与历史账本 | 定向回归 101 项通过。覆盖相同调用键的并发准入、未知提交禁止再提交、预留释放及旧版模型回读。 [网关和账本日志](../../../script/.runtime/pa-skills-b03/gateway-and-ledger-final.log) |
| 单细胞只读、来源与发布历史 | 3 项通过。覆盖真实鉴权和成员字节读取、既有发布生命周期、来源冻结。新读取用例使用注入的已发布结果与来源闭包。R 数值对照在固定镜像中过独立用例 1 项。 [角色与历史](../../../script/.runtime/pa-skills-b03/propeller-read-final.log) · [R 回执](../../../script/.runtime/pa-skills-b03/r-numeric/verification.json) |
| B01 Bulk 兼容 | Linux 工作容器使用已装的生信依赖，2 项通过。复验开关启停、成员原件校验和历史下载。Windows 基础测试解释器缺少 Matplotlib，采用已有 Linux 依赖复验。 [回归日志](../../../script/.runtime/pa-skills-b03/bulk-linux-final.log) |
| Skills 清单与发行脚本 | 72 项通过，范围为 Skills、发行操作和相关 Worker 定向用例。校验当前源的清单和封装规则，B03 新镜像部署另行验证。 [运行时和发行定向回归](../../../script/.runtime/pa-skills-b03/skills-release-final.log) |
| 前端及发行预检 | Vitest 9 个文件共 155 项通过，覆盖客户写作工作台、图件解释、单细胞及 Bulk 历史结果。TypeScript 检查和隔离目录构建通过。发行预检核对 20 个锁定字体，依赖及渲染器合同通过，网络调用为 0。 [前端回归](../../../script/.runtime/pa-skills-b03/frontend-verified.log) · [类型检查](../../../script/.runtime/pa-skills-b03/frontend-release-typecheck.log) · [构建](../../../script/.runtime/pa-skills-b03/frontend-release-build.log) · [发行预检](../../../script/.runtime/pa-skills-b03/release-preflight.json) |

从 B03 离线阶段的最终后端源和前端构建输出生成本地候选 `sha256:0c5cb6c4fdb568340ff600862adc691329a779317df290a473c561decb0fcab9`。源快照 SHA-256 为 `c9a86eb6de900640b9ae03be2e791dc88983e0abd984a632a24f33b07ab55626`，含 10 个受清单约束的 Skills 文件。清单中 2,023 个后端、脚本及前端构建文件与实际工作源逐文件核对。用候选自身的包在 `--network=none` 下核对 Skills 摘要。后续本机灰度和真实模型补验均绑定此镜像，Office 修复另有封装候选。 [候选及镜像回执](../../../script/.runtime/pa-skills-b03/release-image-final.json)

## 5. 停用与恢复

1. 停止接收受影响的新 Skills 请求。只从 `PAPERASSIST_SKILL_WORKFLOWS` 移除受影响的 B03 标识，需要暂停外发时同时关闭该业务的外发入口。记录当前开关、清单摘要、任务状态和调用回执。
2. API 与 Worker 继续使用可解析 B03 冻结合同的同一版本。已冻结首稿和 v8 统计解释可从原指令重建请求。已有响应 ID 的只续取，提交状态未知的先对账。资料变化或原确认失效时，由正常入口重新预览和授权。
3. 保留数据库、候选、Word、原图及分析成果。旧镜像切换前核对已存在的 B03 冻结写作和 v8 批准记录，先排空或保留能读取这些合同的服务。单细胞面板随开关关闭，旧结果和成员下载仍沿用原权限。
4. 回退后按固定样本复查 SCI 历史、论文 Word、统计图件原件、Bulk 和单细胞下载，以及角色撤权、原响应 ID 和账本。确认恢复组合后再决定是否打开对应流程。

## 6. 补验结果与交接

- 首次补验三次 OpenAI 提交有完整回执，SCI 研究首稿通过，毕业论文和统计解释的原任务被业务校验拦截。收口阶段修复两条流程的冻结材料，各补一次真实提交并成功。B03 共五次提交，官方分钟用量和日级费用核对后合计 US$0.0856725。外发已关闭。 [首次回执](2026-11-25-PaperAssist-Skills-B03待验证项补验记录.md#2-openai-真实提交与原回执复验) · [正式对账](2026-11-25-PaperAssist-Skills-B03收口与验收记录.md#3-openai-官方对账)
- 本机灰度、Edge 角色、停启回退、Word/WPS 代表样本、Microsoft Word 原生目录刷新及字体替换已复验。公开 Aorta 完成原生 R 复算、项目导入、结果发布、Edge 只读和原表下载。容量实测和 R 镜像对外分发审查见收口记录。 [首次补验](2026-11-25-PaperAssist-Skills-B03待验证项补验记录.md) · [收口证据](2026-11-25-PaperAssist-Skills-B03收口与验收记录.md)
- B02 已验收，逐笔实收金额和扩大灰度等未验证项继续见原记录。 [B02 验收记录](2026-11-25-PaperAssist-Skills-B02实施与验证记录.md)

当前交接为汇总 B00–B03 提交说明与文件范围，待用户确认。生产规模 P95 和 R 镜像发行条件仍按收口记录登记。 [B03 验收与发布边界](2026-11-25-PaperAssist-Skills-B03收口与验收记录.md#8-用户验收)

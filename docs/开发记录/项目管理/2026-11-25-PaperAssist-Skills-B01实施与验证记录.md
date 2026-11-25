# PaperAssist Skills B01 实施与验证记录

2026 年 11 月 25 日。B01 用户验收通过。工作分支为 `feat/runtime-skills`，沿用 B00 核对的 `main` 提交 `5de3df8c219c4cd0db325b1a45a9c9dcedd9926b` 和数据库迁移头 `0094_sci_revision_chat`。B01 使用 B00 的 SCI 摘要、初稿和 Word 夹具，以及 Bulk 固定 QC/PCA 归档。项目现有前后端和容器未切换。 [总领方案](2026-11-25-PaperAssist-Skills技能系统总领方案.md) · [B00 实施与验证](2026-11-25-PaperAssist-Skills-B00实施与验证记录.md)

## 实施

| 范围 | 本批落点 |
| --- | --- |
| Skills 运行时 | 从项目根 `SKILLS/` 或进程指定的绝对目录读取发布清单。四个首批技能各为 `1.0.0`。发布时检查 YAML、技能名、版本、资源范围、文件数量大小及 SHA-256，拒绝同版本改内容。文本按 LF 计算摘要，清单保留曾发布的版本身份。按后端白名单及依赖顺序去重，只展开该步骤使用的正文和引用资源。两个流程版本均为 `1.0.0`。 [目录](../../../SKILLS) · [注册与校验](../../../backend/app/domain/runtime_skills/registry.py) · [流程配置](../../../backend/app/domain/runtime_skills/runtime.py) |
| SCI 叙述性综述初稿 | 客户在原 SCI 入口生成 `narrative_review` 初稿时，冻结 `scientific-writing`、`narrative-review`、`citation-verification` 及引文阅读范围参考。原写作合同增加可选 `execution_contract.skills_snapshot`，其内层带版本、技能和资源摘要、指令及指令摘要。客户可在确认页查看已核对进外发包的综述写作规则。原授权核对实际外发字节，任务恢复读取已冻结包，候选保存 `writing_provenance.skills_trace`。历史合同、学校初稿、SCI 研究稿和流式改稿沿原入口和格式。 [预览与授权](../../../backend/app/domain/manuscript_writing/authorization.py) · [冻结请求](../../../backend/app/domain/manuscript_writing/frozen.py) · [客户预览](../../../frontend/src/features/manuscripts/WritingBundlePreview.tsx) |
| Bulk 只读 QC/PCA | 有当前项目分配的分析员可在既有固定结果的 QC 或 PCA 标签页打开预览。版本必须是成功的 `bulk_rna_counts` 处理结果。固定入口只接收 `qc_missing`、`pca_scores` 或 `pca_variance`。复用已发布对象解析、范围校验和 `bulk_plot_data`，按面板读取并核对所需成员。预览回传样本轴、值、来源与成员摘要、步骤、工具和技能版本，成功事件可用 `X-Request-ID` 在运行日志追踪。预览没有新增分析任务、模型外发或成果发布，原成员下载和报告继续走原入口。 [固定预览](../../../backend/app/domain/bio_insights/fixed_bulk_preview.py) · [接口](../../../backend/app/api/bio_analysis.py) · [分析员页面](../../../frontend/src/features/bioinformatics/BulkFixedPreview.tsx) |
| 开发与发行 | 开发 Worker 构建指纹包含技能清单。开发和发行 Dockerfile 都复制并检查同一目录，发行候选源清单绑定包文件。宿主发行工具在复制前检查路径、目录联接、文件范围和大小。API 与 Worker 在启用时校验清单和所需成员的摘要。未增加 Python 依赖、数据库迁移或调度方式。 [开发 Worker](../../../infra/worker/Dockerfile) · [发行 Dockerfile](../../../infra/api/Dockerfile) · [发行取源](../../../script/release/release.py) |

## 离线对照

- **SCI。** 复用 `CitationNcbi(3)` 的摘要及 `SciFixtureProvider`，使用真实后端入口、隔离 PostgreSQL 和候选任务执行入口。启用后只有外发请求中的系统指令改变。用旧预览摘要申请新包授权得到拒绝。关闭开关后，新预览恢复到原字节。缺包时，原授权仍能读取冻结包，模型替身收到一次 POST 与一次对原响应 ID 的 GET。导出的 DOCX 保留综述章节、摘要摘录和参考文献，证据建议仍由现有流程标记为待核对。 [对照用例](../../../backend/tests/integration/test_customer_sci_to_word.py)
- **Bulk。** B00 `baseline.json` 的 SHA-256 为 `fb648ee26e7a13cc01089d9a9e5a9ce5e068c811a90250fec52353c9b29a43dd`。逐字段对照三个面板，归档数值、坐标轴和来源摘要一致。隔离库重建的四个文件 `qc_missing_data`、`pca_scores`、`pca_variance_ratio` 和 `pca_data` 的 SHA-256 与 B00 一致。合成样本顺序为 `B0, B1, B2, A0, A1, A2`，缺失比例均为 0，PC1/PC2 方差比例为 `0.986929200789437` 和 `0.013070799210562981`。同时检查不可计算状态、合法样本名、分配撤回、跨项目拒绝、字节篡改与原下载。 [接口回归](../../../backend/tests/api/test_bio_bulk_fixed_preview.py) · [B00 固定材料](2026-11-25-PaperAssist-Skills-B00实施与验证记录.md#3-固定回归材料)
- **发布包。** Windows、本地发行 Dockerfile 验证镜像以及完整开发 Worker 镜像的清单 SHA-256 均为 `41d9a409636e7e174e02a561f3f7628c3bebaeafb40b0fa3f086aa71917f4c51`。发行 Dockerfile 使用本机已有的兼容底座，实装依赖精确匹配检查通过。首次以 `--network=none` 构建开发 Worker 时，既有依赖步骤未命中缓存，先用 B00 Worker 底座核对技能层。用户授权补验后，按开发 Worker Dockerfile 的正常构建配置复用锁定依赖层，完成完整镜像构建。两个镜像分别在断网容器中验证了两条流程的技能清单、SCI 冻结指令摘要一致，以及缺包、错误摘要、资源链接和越界路径均被拒绝。 [已锁定清单](../../../SKILLS/manifest.json)

| 本机复核项 | 验证产物与标识 |
| --- | --- |
| 发行打包 | `script/.runtime/pa-skills-b01-package-be9b5965/build.log`，镜像 `sha256:2089bd5d295d4dc4800554e1ec5089e0722780560b586473b3f01bf4f13d2e41`，源清单 SHA-256 `559c35afed13b460d04c0c156d50c306d662747649022e79c8ceeea9471df7f6`。包含本批隔离编译的前端。 |
| 完整开发 Worker · 补验通过 | `script/.runtime/pa-skills-b01-worker-full-93c7329d/` 下的 `build.log`、`skills-contract.json`、`bulk-numeric.log`。镜像 `sha256:a4b108511d8be08a7b09e8e6142a12ce4af56d7d2c73d69825a990012e32048b`。 |
| 首轮 Worker 验证 | 技能层镜像为 `sha256:8eb1d016347cabca3f0aed5338d51ea48fee8b954917c469bccd1e68f58c8e1e`。首次断网构建的失败记录为 `script/.runtime/pa-skills-b01-worker-7e027ec0/build.log`。 |
| 两条试点 | SCI 定向记录为 `script/.runtime/pa-skills-b01-sci-final-ce2293ef/pytest.log`。Bulk 归档在 B00 记录所列目录，B01 接口复跑留存目录为 `script/.runtime/pa-skills-b01-bulk-receipt-405112e0`。 |

## 定向回归结果

| 范围 | 通过数与口径 |
| --- | --- |
| PostgreSQL 写作 | **13 项**。使用隔离库和模型替身覆盖新旧综述、SCI 研究稿、流式改稿、毕业论文 Word、主题合章、拼版版本、历史金额授权、关闭授权后续取、未知提交和跨项目拒绝。 |
| PostgreSQL 生信 | **9 项**。新固定预览 2 项、原定量流程 2 项、Bulk 报告整表预算及原成员下载 2 项、原报告 DOCX 导出 3 项。新接口两项在加入追踪日志和样本标签兼容后复跑通过。 |
| 运行时与构建工具 | **57 项**。技能发现、版本历史、路径与联接、恶意或损坏的清单、按阶段加载、依赖、开关、固定摘要、API 错误与发行取源。另通过开发 PowerShell 启动器语法校验。 [运行时用例](../../../backend/tests/domain/test_runtime_skills.py) · [发行取源用例](../../../script/tests/test_release_operator.py) · [Worker 配置用例](../../../script/tests/test_worker_stack.py) |
| 写作合同与固定图件 | **150 项**写作领域和模型适配器用例、**9 项** Windows Bulk 显示合同、**18 项**断网 Linux 固定图件适配器用例通过。固定图件在补验构建的完整 Worker 内复跑 **18/18**。 [流式传输](../../../backend/tests/adapters/test_frozen_writing_stream.py) · [Bulk 显示合同](../../../backend/tests/domain/test_bio_b05_display_contracts.py) · [固定图件](../../../backend/tests/numeric/test_bio_b05_figures.py) |
| 前端 | **164 项**。写作、材料确认、授权、流式改稿和拼版 109 项，Bulk 固定结果、原工作流及读者报告 55 项。使用 jsdom 和接口替身。TypeScript 与隔离目录的 Vite 生产构建通过。 |

隔离运行使用 `paperassist_system_test` 的独立 schema 和合成资料。两条试点的真实模型、外部文献调用及付费提交均为 0。B00 归档、原有开发构建输出和现有服务保留。

## 开关和回退

默认两个流程关闭。隔离开发环境可通过 `PAPERASSIST_SKILL_WORKFLOWS` 选择 `sci_narrative_review` 或 `bulk_fixed_preview`，同时选择时以逗号分隔。API 和 Worker 可使用同一个 `PAPERASSIST_SKILLS_MANIFEST_SHA256` 固定发布包。Windows 开发运行时默认从仓库根取包，两个 Linux 镜像各从其打包目录取包。现有真实写作开关和授权准入仍控制模型外发。 [本地配置示例](../../../backend/.env.example)

在 `backend` 目录可运行 `./.venv/Scripts/python.exe -B -m app.domain.runtime_skills` 核对安装。修改技能内容或资源时先升技能版本，再用同一命令加 `--write` 生成候选清单，校验成功后才替换清单。

如需停止新试点，在同一版代码上清空对应流程开关，新 SCI 预览走原路径，Bulk 页面停止显示新入口。已冻结的 SCI 任务按原授权、来源和回执继续读取。切回 B00 二进制前应先排空或暂停含新写作合同的任务，并确认历史回读所需版本。完整的配对重启、恢复和切镜像演练留在 B02。

## B02 待验证

B01 的完整开发 Worker 构建和跨镜像离线验证已补齐。用户已验收 B01，并授权准备 B02 的确认清单。 [B02 真实验证与灰度确认清单](2026-11-25-PaperAssist-Skills-B02真实验证与灰度确认清单.md)

1. 用批准的公开文献和真实测试账户核对 PubMed、模型输出、科学论断、实际 Token、费用与等待时间。用同模型、同材料做有无 Skills 对照。
2. 用实际测试角色在浏览器走查，抽查 Word/WPS 原生打开和版面，复核授权真实 Bulk 版本及性能边界。
3. 在目标测试或灰度环境核对镜像和服务就绪，测量队列负载，演练暂停收新任务、原回执恢复、开关及镜像回退。

本批保留在本地工作树，未提交、推送或部署。B02 的真实调用和隔离灰度部署待用户确认范围。

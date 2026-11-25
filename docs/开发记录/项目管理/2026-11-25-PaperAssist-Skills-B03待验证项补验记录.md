# PaperAssist Skills B03 待验证项补验记录

本页保留首次补验及当时的待验证项。两条模型流程的真实复验、Word 原生检查、官方对账、容量测试、R 分发审查及用户验收见收口记录。 [B03 收口记录](2026-11-25-PaperAssist-Skills-B03收口与验收记录.md) · [用户验收](2026-11-25-PaperAssist-Skills-B03收口与验收记录.md#8-用户验收)

2026 年 11 月 25 日，B03 在离线实施完成后首次补验。SCI 研究首稿真实调用通过。毕业论文和统计解释的真实回执已取得，两条任务均被当时的业务校验拦截，已对原回执做独立离线复验。本机灰度、权限、停启回退、有限负载、代表性 Word/WPS、公开单细胞组成复算、项目发布与原生 Edge 回读均已验证。 [B03 实施记录](2026-11-25-PaperAssist-Skills-B03实施与验证记录.md) · [总领方案](2026-11-25-PaperAssist-Skills技能系统总领方案.md)

## 1. 本机隔离与版本

- `feat/runtime-skills` 基于 `main@5de3df8c219c4cd0db325b1a45a9c9dcedd9926b`。B03 灰度和真实模型使用候选 `sha256:0c5cb6c4fdb568340ff600862adc691329a779317df290a473c561decb0fcab9`，Skills SHA-256 为 `5136e50e3a8d083e19d612b46343d537cb7e776194bea376f061dd56efb3c524`。预检通过，灰度启动核对 2,028 个发行源条目和候选实际提供的前端文件。 [发行预检](../../../script/.runtime/pa-skills-b03/release-preflight.json) · [灰度启动回执](../../../script/.runtime/pa-skills-b03/supplement/gray/gray-start.json)
- `skills-b03` 在 `https://localhost:18483` 提供灰度，`skills-b03-model` 在 `https://localhost:18484` 保留隔离回执、原始合成材料和可下载制品。测试数据库、资产、队列均分开。Edge 只在独立测试进程使用已核对的本机服务公钥，安装或删除 Windows 证书均为 0。B02 容器及镜像 ID 与复验前相同。 [灰度操作记录](../../../script/.runtime/pa-skills-b03/supplement/gray/README.md) · [关闭外发回执](../../../script/.runtime/pa-skills-b03/supplement/model/records/external-closed.json)
- 本机验证证据留在 `script/.runtime/pa-skills-b03/`。工作区未暂存、未提交、未推送。生产和外部灰度未部署。

## 2. OpenAI 真实提交与原回执复验

用户确认继续使用同一 OpenAI `Default project`，上限 US$0.80、3 次新提交。使用 `gpt-6.1-sol` 对合成 SCI 研究首稿、合成毕业论文和合成固定图件各提交一次。发送前逐条核对冻结请求和实际 JSON。未外发用户科研材料、学校模板原文件或原 PNG，外部文献与 NCBI 请求为 0。三个 OpenAI `POST` 后按原响应 ID 完成 13 次常规续取及 2 次诊断读取。实际累计预留 US$0.445830，按返回用量及模型定价复算为 **US$0.050354**。逐响应实收金额无账单凭据。沿用既有 Responses 后台流程，按 `background=true` 与 `store=true` 留存，保留期限以服务端配置为准。三次限额已用完，外发开关、模型凭据挂载、临时外网转发均已撤下。 [用量与三条回执](../../../script/.runtime/pa-skills-b03/supplement/model/records/verified-b03-model.json) · [模型定价](https://developers.openai.com/api/docs/models/gpt-6.1-sol) · [数据留存说明](https://developers.openai.com/api/docs/guides/your-data)

| 流程 | 真实任务 | 用量复算 | 验证结果 |
| --- | --- | ---: | --- |
| SCI 研究首稿 | `succeeded` | US$0.015264 | 六节候选，待审核。逐段核对合成材料，保留 Methods 的计划 5 个观测与 Results 的实际 4 个及研究限制。Edge 实际下载 Word 共 39,875 bytes，SHA-256 `608e79e9c1f871343855b0a5ca37f64bef583265bf74bd5a030bcaccc06320e5`，嵌入原 PNG 与材料逐字节一致。 |
| 毕业论文首稿 | `failed`，`manuscript_writing_invalid` | US$0.022971 | 回执写入 7 个未请求的章节标题和 1 个未请求的图题，业务拒收，原任务无 Word。移除副本中这两组越界建议后，按原冻结包和原校验器重验，正文及已确认学校章标题保持一致，得到仅供审阅的本地候选。 |
| 固定图件统计解释 | `failed`，`explanation_invalid` | US$0.012119 | 首次拦截英文连接语，其余检查还涉及坐标、计数和独立性用语。独立回读确认六节 42 条事实引用全部到位。离线只改 6 句连接语，原校验器可渲染六节，42 条证据原值与顺序一致。未知引用、错用口径、未绑定数字、确认独立性、因果、显著性 6 个负控全部拒收。分析员仍可下载同一原 PNG，客户被拒。 |

两次离线复验使用原响应和冻结摘要，未发起新的模型请求、写入产品候选或发布稿件。研究首稿和统计解释均只使用合成业务材料，定向核对不覆盖真实论文写作质量、外部引用准确率和扩大样本后的通过率。 [Edge 真实回执回读](../../../script/.runtime/pa-skills-b03/supplement/gray/edge-model-readback.json) · [毕业论文校验原因](../../../script/.runtime/pa-skills-b03/supplement/model/records/thesis-receipt-diagnosis.json) · [毕业论文离线回执](../../../script/.runtime/pa-skills-b03/supplement/model/records/thesis-local-recheck.json) · [统计独立复验](../../../script/.runtime/pa-skills-b03/supplement/model/independent-stats-review/statistics-review.json)

## 3. 本机灰度、Edge 和负载

- **角色与历史成果。** Edge `158.0.4370.33` 实际登录客户所有者、其他客户、指派分析员、其他分析员、管理员共 5 个隔离账号。SCI 与学校客户可读取已冻结预览，其他客户返回 `404`。管理员实际分配并撤回，同一分析员访问原件依次返回 `404`、`200`、`404`，其他分析员全程 `404`。学校历史 Word 52,097 bytes，回读摘要 `5b06785ec1847e3fa5ef20a0722c4e3e35f9de6f3c9b729758340ae904484bf3`。 [Edge 角色走查](../../../script/.runtime/pa-skills-b03/supplement/gray/edge-primary.json)
- **停启和开关回退。** 维护窗口新写入返回 `503`，只读下载仍为 `200`。完成配对备份后停栈时端口不可达，共核对数据库 204 张表、106 项资产和关键数据指纹。按相同镜像关闭四个 B03 开关，新预览回到原合同，旧预览和下载字节一致。恢复开关后重新得到相同的 Skills 冻结内容，灰度模型调用账本为 0。 [停启、备份和回退](../../../script/.runtime/pa-skills-b03/supplement/gray/gray-rollback.json)
- **负载。** 192 次本机 HTTP 读取全为 `200`。每条路径每种并发 24 个样本，并发 4 时 SCI、学校预览 P95 为 443.92、467.94 ms。单 Worker 排队的 20 个合成 DOCX 解析任务全部完成，批次 158.13 秒。排队 P50/P95 为 60.40/116.32 秒，执行 P50/P95 为 1.54/3.84 秒，端到端 P50/P95 为 63.00/118.01 秒。时间来自同批实际 API 和数据库任务时间戳。 [负载回执及抽样方法](../../../script/.runtime/pa-skills-b03/supplement/gray/gray-load.json)
- **同路径开关对照。** 关闭和开启各 192 次回读，均成功。并发 4 下 SCI P95 从 498.34 到 443.22 ms，学校从 516.53 到 473.48 ms。对照在同一宿主和固定请求中完成，生产容量和 P95 仍待实际规模验证。 [对照样本和统计](../../../script/.runtime/pa-skills-b03/supplement/gray/gray-rollback.json)

## 4. Word/WPS 兼容修复与回归

实测原稿时，WPS 替换了空白 DOCX 模板遗留的 `Courier` 和 `ＭＳ 明朝`。学校首稿各章重置页码，刷新目录后正文条目均为 1。修复将新 SCI 读稿导出及学校连续分页路径的模板默认字体映射到 `Courier New` 与 `MS Gothic`，在应用学校样式前完成，保留用户明确选定的模板字体。新学校首稿进入已有的连续分页规则。学校生成缓存带渲染版本标识，可复用历史已冻结 DOCX。七项定向回归通过，包括开关两态、历史与已审核缓存、带引文 SCI。 [字体默认值](../../../backend/app/adapters/manuscript_docx.py) · [首稿导出](../../../backend/app/domain/sci_draft_reader.py) · [渲染缓存](../../../backend/app/domain/manuscript_writing/school_render_cache.py) · [定向回归](../../../script/.runtime/pa-skills-b03/supplement/office/product-regression-green/pytest.log)

Word `16.0.20625.20108` 与 WPS `12.1.0.29690` 实际打开修复件。带合成引用 SCI 各 2 页，讨论引文、参考文献和原图可见。学校首稿和复核稿在 WPS 各 10 页，刷新目录后 `1,1,2,3,4,5` 与原生章页码一致。WPS 明确提示修复件的字体均可用，样本学校正文为 Times New Roman/宋体 14 pt。原下载件与开版副本哈希相同，内嵌原 PNG 保持逐字节一致。 [Office 验证总回执](../../../script/.runtime/pa-skills-b03/supplement/office/office-verification.json) · [修复件 OOXML 与 SHA-256](../../../script/.runtime/pa-skills-b03/supplement/office/ooxml-fixed-evidence.json)

修复候选为 `sha256:fc5d0a7f144e2f7290d8858c912dc926a0c849bf1b460690027117259715e499`，源清单 `6ba9e69e64b9848aa900bd85621dad0d8873deb8b33f0bcad163eab75789f096`，同一前端构建和 Skills 摘要已核对。用修复候选只读访问 B03 模型隔离库和资产，以真实 LibreOffice 服务生成本地审阅文档。SCI 正文 XML、PNG 均和原下载一致。论文审阅件 46,834 bytes，带六条目录链接，原图字节一致，Word 与 WPS 都打开为 10 页，第 5 页显示 `1,1,2,3,4,5`，原图在第 8 页，WPS 内存刷新与缓存一致。受保护视图下的 Word 本机重算和字体替换仍未验证。灰度、模型和性能的原回执绑定第 1 节的原候选。 [兼容修复候选](../../../script/.runtime/pa-skills-b03/release-image-office-supplement.json) · [真实渲染回执](../../../script/.runtime/pa-skills-b03/supplement/model/records/office-supplement-render.json) · [Word 与 WPS 开版记录](../../../script/.runtime/pa-skills-b03/supplement/office/README.md)

## 5. 公开单细胞组成复算与 R 镜像许可

- **公开材料。** Tabula Muris Senis Aorta FACS `10.6084/m9.figshare.12654728.v1`，文件 `23872460`，发布方 MD5 匹配，本地 SHA-256 `0fbf73145f2b50f956b9946aa2fa17e5fce0e40ddfc5ba922a1d503d65ced3c3`。固定 3 月龄雄性 4 个供体 279 个细胞、24 月龄雄性 4 个供体 224 个细胞。以供体为单位做 `24m − 3m`，使用 `donor_unpaired`、`asin`，不作批次校正。 [作者发布的数据版本](https://doi.org/10.6084/m9.figshare.12654728.v1) · [冻结和复跑说明](../../../script/.runtime/pa-skills-b03/supplement/cell-r/README.md)
- **数值回执。** 固定 R 镜像 `sha256:728b440e94d7708a5bbf983da746ccf6e5ca2d93f93acd19c2dc19cc937c5d57`，关键执行模块与当前源码一致。两次断网复跑共 9 份输出字节一致。逐供体比例、差值和 BH 校正独立重算通过，原始 p 值与 moderated t 通过同引擎对照。6 个类别参与检验，最小 BH 调整 p 值为 `0.501952729131809`。该样本在 0.05 水平未观察到组间差异。B03 候选逐值投影已产生成员的 11 行，表 SHA-256 `8713a8dcba603bc8541c38266554690e197f9de38d9b4ac031cea9d24fef95d4`。两次独立复算直接使用发布标签及供体映射。生物学推断限本队列及其已声明的设计。 [独立数值复核](../../../script/.runtime/pa-skills-b03/supplement/cell-r/run/current-verification.json) · [原 TSV 投影](../../../script/.runtime/pa-skills-b03/supplement/cell-r/run/projection.json)
- **项目发布准备。** 从老版 H5AD 的 `raw.X` 取得整数计数，按已冻结的 503 个细胞提取同一基因轴的 22,966 个特征，重封装后逐值对照通过。Propeller 预检在本机可用内存低于 4 GiB 时两次拒绝。短暂停启本轮两套 B03 隔离环境后，预检通过，两个环境恢复。独立单细胞导入预检及 Worker 定向探针通过。 [原始计数转换](../../../script/.runtime/pa-skills-b03/supplement/cell-r/materials/aorta-fixed-cohort-counts.json) · [Propeller 预检](../../../script/.runtime/pa-skills-b03/supplement/cell-r/gray-propeller-runtime-paused.json) · [停启回执](../../../script/.runtime/pa-skills-b03/supplement/cell-r/gray-propeller-runtime-paused-recheck.json) · [导入预检](../../../script/.runtime/pa-skills-b03/supplement/cell-r/cell-import-runtime.log)
- **项目发布。** 在 `18483` 使用实际 API 建立测试项目及分析员指派。以临时只读依赖锁、已验证运行时和隔离 R Worker，完成公开计数上传、导入确认、供体映射、QC 确认、预处理和原始标签确认，再创建计划并通过正常任务执行器发布 Propeller。全部 503 个细胞保留，年龄、供体和作者标签与固定队列核对一致。发布结果版本 `08a8a468-c62d-51fd-a01d-dd6e2c996ae0`。实际 API 下载的 TSV 与独立复算逐字节一致，11 行，摘要见上。 [项目发布回执](../../../script/.runtime/pa-skills-b03/supplement/cell-r/gray-aorta-publication.json)
- **Edge 只读。** 恢复原本机灰度配置后，临时科学运行时已卸载。指派分析员仍可从实际产品结果页打开组成面板，页面、API 和下载 TSV 的 11 行逐值匹配，原表为 1,642 bytes。项目客户和另一客户预览及直接下载均为 `403`，未指派分析员两项均为 `404`。项目账本仅有 1 个导入、1 个预处理、1 个组成任务且均成功，灰度模型账本为 0。 [原生 Edge 回执](../../../script/.runtime/pa-skills-b03/supplement/cell-r/gray-aorta-edge.json) · [灰度恢复回执](../../../script/.runtime/pa-skills-b03/supplement/cell-r/gray-aorta-stack-restored.json)
- **发行许可。** 核查覆盖目标 7.84 GB 镜像中 339 个 R 包、437 个 Conda 包、235 条 Python 分发记录、105 个 Debian 包。已固定核心来源和构建配方。`dqrng`、`RhpcBLASctl` 标注 AGPL，在本次 Propeller 的 134 个运行时命名空间中均未加载。可用于当前内部计算。给第三方交付整镜像仍需补齐对应源码、第三方告知及 GPL/AGPL 组合范围审核，托管服务另按实际加载和远程交互组件核对。镜像外部分发为 0。 [组件、源码和许可核查](../../../script/.runtime/pa-skills-b03/supplement/cell-r/license/README.md) · [GPLv3](https://www.gnu.org/licenses/gpl-3.0.en.html) · [AGPLv3](https://www.gnu.org/licenses/agpl-3.0.en.html#section13)

## 6. 首次补验后的状态

- 毕业论文和统计解释的真实任务仍为失败，须用实际新回执检验后续模型输出才能更新真实通过结论。再次 `POST` 需另获预算和次数授权。逐响应实收未单独核销。
- 代表性 Office 开版限上述版本、测试机器和模板。Word 自身刷新与字体替换的独立检查受保护视图限制。公开 Aorta 复算、项目发布及 Edge 回读覆盖固定队列及作者发布标签。其他队列、生物学复核和重注释未纳入这次验证。
- 生产容量、规模 P95、扩大案例集和 R 镜像对外放行在首次补验后仍有验证条件。后续核验结果及放行边界见收口记录。 [后续实测和审核结论](2026-11-25-PaperAssist-Skills-B03收口与验收记录.md)

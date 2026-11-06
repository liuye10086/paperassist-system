# 第6批 R 工具独立审查（2026-11-06）

## 结论

Spec：通过本次限定审查。质量：未发现需要阻断交付的 R 工具层问题。该结论限于已审代码及已有小夹具证据，不等同真实研究数据、生物学验证或最大输入规模承载保证。

本次只读审查实现、直接原 API 测试、原始源码/论文留存及日志；没有重跑测试，没有修改功能代码、Git 或服务。仅新增本审查记录。

## Spec 核对

- `backend/app/adapters/single_cell_r/topics.py:135`：按方法加载固定版本并预热，要求 R 4.4.3 / slingshot 2.14.0 / GENIE3 1.28.0 / CellChat 2.2.0.9001；`infra/single-cell-r/Dockerfile.topics` 校验源归档 hash，最终层移除官方 CellChat data。
- `backend/app/adapters/single_cell_r/topics.R:9`：直接原 Slingshot，显式 start.clus；slingPseudotime(na=TRUE)、原 curve weights、lineage paths 和排序后的原曲线。Python 保留 NA，验证 cell/lineage 轴，未伪造时间或概率。
- `backend/app/adapters/single_cell_r/topics.R:17`：CSR cells×genes 的结构直接解释为 CSC genes×cells，GENIE3 按原 regulators×targets 返回，nCores=1。Python 明确按 tf_ids 与 genes 原顺序输出；上层标明 predictive importance 而非 P 值或因果。
- `backend/app/adapters/bio_insights_engine/single_cell_topics.py:107`：CellChat 用全原始 Gene Expression 计数作分母，合并重复精确 symbol 后 1e4 归一化/log1p，再按供者/条件调用；未输入缩放残差或整合表示。`topics.py:35` 拒绝负值/非有限值；`:114` 展开全部必需 receptor/ligand subunits。`topics.R:24` 构造完整 demo complex 表并直接调用原 computeCommunProb/filterCommunication，保留所有请求边的原概率/P。
- `topics_resource.json` 明确 3 条人工整理文献 LR、human、CC-BY-4.0、归属/改编/范围及 payload hash。留存论文 Fig7 主文确有 CCL19–CCR7、MIF–CD74/CD44、CXCL12–CXCR4，不是官方 CellChatDB 或全库。
- `backend/app/adapters/bio_insights_engine/worker.py:117` 在 isolation 前只预热可信固定夹具，`:130` enter 后才执行分析；沙箱入口检查单线程，GENIE3 nCores=1 / CellChat future::sequential。现有 sandbox_check.py 明确拒绝 fork/socket/未授权读取后再运行原方法。未将单 CPU 配额本身当作单线程证据。

## 质量及证据

- `backend/tests/numeric/test_single_cell_batch6_topics.py:15` 两个 root 的 Slingshot 原 API 对照，检查 NA、权重、lineages、root 方向；`:32` GENIE3 非排序 TF/基因轴、全权重精确相等、重复 seed、自边零、缺 TF 和非有限输入；`:49` 独立 literal DB 的 CellChat 原管线，逐 sender/receiver/LR 对照 12 条边概率/P、complex、group_sizes、缺必需基因及群大小边界。
- `script/.runtime/single-cell-batch6/numeric-final.log` 为 5 passed in 9.30s。准确拆分是 1 个文件存在断言 + 4 个实际 API 对照案例（Slingshot 两个 root、GENIE3、CellChat），不是 5 个独立数值方法案例。
- `combined-sandbox.log:33` 记录 propeller + 三方法原计算全通过，RSS 1081676 KiB，RLIMIT_AS 3 GiB。脚本确认所有原方法预热后再次在 enter 后计算。此为小夹具联合预算证据。
- 现有 CellChat 缺基因测试同时去掉两个受体 subunits；代码本身会拒绝缺任一 subunit。测试没有单独隔离“仅缺一个 subunit”情形，也未做负值专门测试；不构成当前实现缺陷，不能把这些分支描述成已独立数值实测。
- 测试没有逐坐标独立对照输出曲线，代码直接取原曲线并验证维度/有限值。没有最大 20k cells / 5k genes 的容量验证，没有真实数据适用性或通讯真实性结论。

## 发现与限制

没有确认的 P0/P1/P2 阻断或重要缺陷。无需为本审查追加泛化框架、审批或扩展回归。报告中“通过 5 个测试”准确；若汇总称“5 个原生数值对照”，建议使用上述 1+4 的准确口径。

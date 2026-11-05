# 成果来源核验修复与真实队列链路验证

## 授权与范围

用户要求解决第 5 步真实成果读取 `409`，必要时新建项目验证完整链路。本次允许在保留的本地验收环境创建合成项目、启动已有队列及执行本地计算；不提交、不推送、不调用付费模型。原项目、失败记录及固定成果均保留。

## 已确认根因与修复

1. **旧成果错误返回来源冲突。** 来源字节及 SHA 未变，但当前投影增加了旧冻结内容中不存在的 `bio_processed_dataset_version.content.layers`，以及生信图任务中两个值为 `null` 的结果字段。新增限定兼容投影，仅处理这些已知 v1 字段；原字段、来源身份、字节及哈希仍须完全一致，不改存量冻结数据。
2. **新批次上传在 worker 中找不到文件。** 公共文件记录隐藏 `object_key`，worker 误用旧的 `files/{id}.xlsx` 路径。现在在同一所有者及项目范围内解析私有存储位置，继续使用调用者固定的大小和 SHA 校验。
3. **大报告初始来源核验阻塞续租。** `research_report` / `delivery_package` 初始核验在 schema 写锁内，阻塞自身 heartbeat 和 API 会话更新。拆成短写入进度、只读来源核验、短写入推进；推进前重查 lease、owner、checkpoint。prepare/publish 的完整来源复验和失租保护继续保留。

## 原项目恢复证据

- 环境：`http://127.0.0.94:18094`，保留 schema `pa_test_8a5c8263d6fa44d28ff6486ad80d91a6`。
- 原项目 `e8ba52c6-0e85-42ac-8205-dd70f1851f03` 并非空项目：修复验证时 4 个研究图、11 个报告；列表均返回 200。
- 最新及最早研究图 PNG、最新及最早 Word 报告下载后 SHA 均与保存值一致。Edge 已显示原有组合图。
- 原成果未重新生成。证据：`script/.runtime/results-ui-20261105/existing-receipt.json`、`existing-figure-restored.png`。

## 新项目真实链路

- 项目：`43e40df7-002c-490c-b321-cc8588860880`（完整链路验收 2026-11-05）。
- 8 行合成 Excel 经公开批次上传 API、RabbitMQ、Linux worker 真实解析；检查有效行数为 8；需求已固定。
- 真实本地统计任务 `eb710c93-fd60-4aad-b6e2-369aa735b1e7` 成功：总体均值 4.5，Control / Treatment 均值 2.5 / 6.5。
- 研究图任务 `18671612-e7bb-5543-b1a3-93e717875d14` 成功，版本 `b0447e9c-79e8-55ad-a5cc-f37f37bfbaf4`。
- 研究报告任务 `77bd8aff-711e-540b-a68f-708a13fc326b` 成功；图、Word、表格、方法和成果包共 9 个成员下载校验通过，DOCX 结构检查通过。
- 首次研究图的文件定位失败记录保留，通过公开的下一版本操作继续，没有直接改任务状态、重传输入或重复统计。
- `chain-receipt.json` 状态为 `passed`，`chain-final.log` 保存过程，`chain-downloads/` 保存下载文件。以上均在 `script/.runtime/results-ui-20261105/`，不纳入提交。
- Edge 已核对统计表、研究图实际图像、报告内容预览和下载控件；点击 Word 下载后得到 `C:/Users/86182/Downloads/analysis.docx`，60461 bytes，SHA-256 `f8390515c4097a75fc0e9c154e98961025692847f50c99aca0f6b0adcbb2a0ad`，与保存成员一致。截图 `chain-figure.png`、`chain-report-download.png`；浏览器下载事件监听未回传事件，但实际落盘文件已单独验证。
- 报告版本 `1569f5eb-f6f0-5a16-9433-df839a35136b`：阶段记录显示初始来源核验 1.4 秒、文档与成果包渲染 23.0 秒；后续整理及发布仍有约 50 秒开销，未将其表述为性能验收通过。服务及 Edge 报告页保持运行供用户验收。

## 定向回归

- 来源兼容、发现、图与报告发布相关测试：29 passed（`backend-regression.log`）。
- 批次文件适配器、数据整理及两条历史来源集成测试：15 passed（`asset-regression.log`）；补充大小不符反例后适配器单测再次通过。
- 初始只读核验及图/报告发布：14 passed（`lease-regression.log`）。
- 续租、只读期间失租、checkpoint 漂移禁止 render、交付包同分支：4 passed（`source-lock-fence-regression.log`）。
- 各组包含重叠测试，不相加为唯一测试数。损坏来源字节、非空新增结果、哈希/大小/身份不符和跨所有者读取仍拒绝。
- 独立只读代码审查未发现此次改动的明确缺陷。

## 验收边界

这是合成表格统计分支的真实本地队列链路及原有生信成果读取验证，不等同于重新完成所有生信分析、付费写作或科学结论验收。大来源的 prepare/publish 仍有必要的写事务复验；本次没有宣称其耗时已消除，也没有重跑大型空间项目的全部计算。用户验收待确认。

# 第6批 R 原生工具层验收报告（2026-11-06）

## 结论与范围

Slingshot、GENIE3、CellChat 原包已接入独立 `TopicsBridge`。本报告确认原 API 数值对照及有界可信夹具在真实内核沙箱执行通过；不等同于真实研究数据、生物学结论或完整商业数据库授权验证。没有修改旧 bridge.py、Worker、合同、服务或前端；没有提交、推送、删除旧镜像/容器/卷。

文件：`backend/app/adapters/single_cell_r/topics.py`、`topics.R`、研究代理提供的 `topics_resource.json`；`infra/single-cell-r/Dockerfile.topics`、`topics-dependencies.md`、`topics-explicit-spec.txt`；`backend/tests/numeric/test_single_cell_batch6_topics.py`。

## 原生版本、资源与接口

- 镜像：`paperassist-single-cell-worker:b6-topics`，ID `sha256:4aac8cc9406f81db88f5b974f2f979dfc522713074d207f3b408f09df7957801`。
- 基础镜像：b5-propeller；R 4.4.3，Bioconductor 3.20。
- slingshot 2.14.0（Artistic-2.0），GENIE3 1.28.0（GPL >=2）。来源为 Bioconductor 3.20 source tarballs。
- CellChat 2.2.0.9001（GPL-3），官方仓库固定 SHA `75253cd0c9e68410e6e721a6d3a0419a1d7e358f`。
- 另固定 princurve 2.1.6、TrajectoryUtils 1.14.0、NMF 0.28、BiocManager 1.30.27；所有源码归档 SHA256 在 Dockerfile 校验。Conda精确URL/hash记录在 `topics-explicit-spec.txt`，源码覆盖后的实际R包版本清单为运行材料 `r-package-versions.tsv`（NMF conda元信息0.21.0被源码0.28覆盖，运行时以R packageVersion为准）。
- 多阶段最终镜像仅复制 R 前缀，已移除 CellChat/data 官方数据库；源码归档与编译器留在 builder，不进入最终镜像新增层。
- 默认 CellChat 资源是独立人工编制的 `human-demo-literature-v1`：CC-BY-4.0 Jin2021 Fig7正文的3条交互 CCL19→CCR7、MIF→CD74/CD44、CXCL12→CXCR4。保留复合受体subunit，明确归属、改编、适用物种、范围。不是官方CellChatDB，不是全库，不保证PBMC有显著交互。
- 资源规范payload SHA256 `9f7e7250fe0603615dfabb0c501c4ef6b5ea9f28734b3e874fb5df6723e31e19`，读取时验证；哈希编码见JSON metadata。官方DB含KEGG来源，其用途许可不能因软件GPL而默认放行，未在产品启用。

公开入口：`initialize_topics(scratch, method)`（每method独立可信小预热）、`get_topics_bridge()`、`get_cellchat_resource(species_taxon_id=9606)`（纯JSON且缓存）、`exercise_topics(method=None)`（隔离后真实原包小探针）。初始化兼容同进程先运行旧propeller。

Slingshot 返回 n_cells×n_lineages 原始 pseudotime（保留NA）、weights、lineage IDs/cluster paths、原embedding维度的曲线。GENIE3 输入CSR cells×genes，原生转换genes×cells，输出明确TF×target；`nCores=1`，稳定性多seed汇总留给Python工作流。CellChat接收外部已按全symbol计数分母归一化log1p的表达，不再二次归一化；`LR.use`显式选择、`raw.use=TRUE`、`type=triMean`、`population.size=FALSE`、`distance.use=FALSE`、`future::sequential`；返回全部选定sender×receiver×LR（包括零概率和非显著），不隐藏DE筛选。原 `filterCommunication` 对群大小 `<=min.cells` 过滤，因此桥接要求每群严格大于 min_cells。

## 实际验证

1. 新文件缺失断言先失败；Windows原生测试不承担R数值验证。最初无confcutdir触发无关数据库自动fixture/openpyxl缺失，改为限定numeric测试目录。
2. 最终真实数值测试 **5 passed in 9.30s**，日志 `numeric-final.log`。包括两个Slingshot root方向、NA和轴/lineage原API对照；GENIE3原矩阵方向、同seed完全一致、自调节零、缺TF/非有限值拒绝；CellChat12条边概率/p值、复合受体、群大小直接独立原API管线对照，并验证缺subunit/群大小边界拒绝。
3. 每个方法独立进程、真实Landlock/seccomp、网络隔离、2GiB容器内存、单CPU执行通过。隔离后确认fork/socket/未授权 `/etc/passwd` 读取均PermissionError，随后读取唯一声明fixture并调用原工具。
   - Slingshot peak RSS 746216 KiB；GENIE3 271532 KiB；CellChat 487712 KiB。
   - 全部 RLIMIT_AS = 3221225472 bytes（3GiB），未提高预算。
4. 联合gate：同进程先propeller再3topic预热，enter后再次运行propeller+`exercise_topics()`，全部真实计算通过。peak RSS **1081676 KiB**，AS仍3GiB。`combined-sandbox.log`。
5. 最终镜像R版本清单导出并断言官方CellChat data目录不存在。Python语法检查通过。

CellChat有原生提示：未提供samples列时默认同一sample1（本桥接每次单供者/条件调用）；保留在logs。原包reticulate兼容提示也保留，实际安装版本1.47.0，测试无崩溃。

## 可复现命令（PowerShell，仓库根目录）

```powershell
docker build -f infra/single-cell-r/Dockerfile.topics -t paperassist-single-cell-worker:b6-topics .

docker run --rm --network none --memory 2g --cpus 1 -e OPENBLAS_NUM_THREADS=1 -e OMP_NUM_THREADS=1 -e MKL_NUM_THREADS=1 -e NUMEXPR_NUM_THREADS=1 -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 -e PYTHONPATH=/repo/backend -v ${PWD}:/repo -w /repo --entrypoint /opt/paperassist-bio-insights/bin/python paperassist-single-cell-worker:b6-topics -c 'from app.adapters.single_cell_r.bootstrap import preload_runtime_libraries; preload_runtime_libraries(); import pytest; raise SystemExit(pytest.main(["backend/tests/numeric/test_single_cell_batch6_topics.py","--confcutdir=backend/tests/numeric","-q"]))'

foreach($method in @('slingshot','genie3','cellchat')) {
  docker run --rm --network none --memory 2g --cpus 1 -e OPENBLAS_NUM_THREADS=1 -e OMP_NUM_THREADS=1 -e MKL_NUM_THREADS=1 -e NUMEXPR_NUM_THREADS=1 -e PYTHONPATH=/repo/backend -v ${PWD}:/repo -w /repo --entrypoint /opt/paperassist-bio-insights/bin/python paperassist-single-cell-worker:b6-topics script/.runtime/single-cell-batch6/sandbox_check.py $method
}
docker run --rm --network none --memory 2g --cpus 1 -e OPENBLAS_NUM_THREADS=1 -e OMP_NUM_THREADS=1 -e MKL_NUM_THREADS=1 -e NUMEXPR_NUM_THREADS=1 -e PYTHONPATH=/repo/backend -v ${PWD}:/repo -w /repo --entrypoint /opt/paperassist-bio-insights/bin/python paperassist-single-cell-worker:b6-topics script/.runtime/single-cell-batch6/combined-sandbox.py
```

必须在pytest/数值插件前预加载既有 `bootstrap.preload_runtime_libraries()`；否则pytest插件可能先加载系统OpenSSL/libstdc++，造成ABI版本冲突。这是测试启动顺序，不修改系统库。运行材料均保留 `script/.runtime/single-cell-batch6/`，含失败构建/初次失败诊断日志、最终成功日志、探针脚本、镜像ID、包版本和研究来源。

## 保留限制

仅验证36–54细胞/小gene集合有界原生计算，未证明最大20k细胞/5k基因可在同预算完成。GENIE3内部原算法仍会致密化选定有界表达，范围选择由工作流控制。CellChat资源只有3条交互、仅human；不等同全DB分析或临床/因果验证。前后端整合、真实数据跑批及用户验收由主代理完成并单独记录。构建中的Conda解依赖使用freeze-installed，当前精确结果已存档；将来重建仍应对精确清单检查，不能只凭tag声称相同环境。

# 第2批后端实现任务

范围由用户在总领与七批计划批准，2026-11-05再次明确开始第2批。只实施本批，不提交/推送/合并、不新建分支，不调用云，不触碰既有数据。报告只生成Word，任何检查不得产生PDF。

## 架构与职责

- 沿用现有`SingleCellParameters`、正常API/Worker和`bio_engine`计算链。原counts保持整数，规范化/marker/pseudobulk仍用保留的原counts。
- 新建`adapters/single_cell_r/`：固定R代码、预加载桥接、稀疏输入与返回检查；通过rpy2在现有数值子进程嵌入R，不新增服务/逐步骤任务/审批。
- worker在sandbox.enter之前按需初始化R（固定`/opt/paperassist-single-cell-r/lib/R`，vanilla、不加载用户profile）、加载固定脚本与包、合成预热，之后才接触用户矩阵；stdout不能污染READY/JSON。sandbox仅增加固定R前缀只读权限和必要的特定scratch读写，不放开fork/exec/network或整个/tmp。实际单线程检查、原有RSS/超时边界保留。
- 直接将cells×genes CSR的data/indices/indptr作为genes×cells的dgCMatrix传给R，保持显式细胞/基因轴。不为交换额外制造大型密集矩阵。R double整数精度上限要检验。
- 改`single_cell_contracts.py`、`bio_engine/qc.py`/`pipeline.py`、worker、sandbox及必要的能力/API与Word接线。独立源文件参与既有code_digest，不建设新的版本系统。

## 参数和科学行为

- 加文库QC阈值覆盖（library_id明确，未指定字段继承全局）：counts/检测基因下限、counts上限和线粒体比例上限。未知文库/重复覆盖/继承后倒置阈值返回明确错误。按原始导入library_id匹配，不随可编辑供者/组别映射漂移；保留逐细胞原因和逐文库汇总。
- scDblFinder为可选，默认关闭以兼容既有请求；开启时按捕获文库单独计算，评分、预测、可选排除三者分开存储。可选expected doublet rate，不把预测称为已证实双细胞。固定seed、SerialParam与单线程；1.20.2的参数应查真实包，不传新版才有的参数。
- decontX为可选，默认关闭；对适用文库真实估计污染，保存浮点`decontx_counts`独立层、逐细胞污染率与模型适用/失败原因。不覆盖counts、不取整、不将校正层交给DE。缺条件的文库明确not_computable，不伪造成功。部分成功时必须明确覆盖轴/有效性，避免未经校正的值冒充校正结果（优先全部适用时才输出完整校正层）。
- 算法在初步QC保留的细胞/表达基因上运行，scDblFinder可选排除后重新对齐最终counts与所有结果；原始细胞的QC/双细胞状态仍可追溯。decontX只提供独立校正结果，本批不改已有下游表达语义。
- 输出：observations和逐文库QC/算法结果表、steps、summary、实际参数、包版本和工具日志、H5AD及Word。原counts和原始输入不变，浮点校正层与轴可下载。页面由后续任务实现，请提前回报参数/结果键。

## 验证

- [ ] 合同与分文库QC测试先红后绿，包含继承/阈值冲突/未知文库、单文库与多文库、原映射保留。
- [ ] 真实R小数据与直接原工具对照，证明评分/污染层来自工具，轴顺序一致、无跨文库混算、可选过滤与不变counts。
- [ ] 实际隔离Worker验证，不能只在未隔离函数下通过；运行时依赖、stderr/日志、超时和限制错误要如实呈现。
- [ ] 既有单细胞与空间分析相关定向回归；不默认全套回归，不并行运行DB测试。

本任务主agent负责R容器安装与最终公开数据/服务验收。后端实现者不要编辑`infra/single-cell-r/`或`script/dev/single_cell_runtime.py`，避免冲突。任何包安装/构建需求发给主agent。测试资料保存在`script/.runtime/single-cell-batch2/`。把结果报告写`docs/superpowers/plans/2026-11-05-batch2-backend-report.md`，标明真实运行与未验证部分。

## 真实矩阵测量后的有界调整

PBMC3k在父进程2GiB限制下实跑返回bio_resource_exceeded；独立受3GiB容器/3GiB地址空间约束的现有Worker测得RSS2275.25MiB，scDblFinder完成136个预测，decontX因无法分配103MiB向量失败，地址空间达到3072MiB。基于实测，将本批启用R工具的单细胞任务限定为RSS4GiB、AS5GiB，并使用5GiB测试/验收Worker容器；其余基础/空间任务保持原2GiB/3GiB。同步保存参数快照、估算、父进程及子进程实际限制，不新增用户配置/确认/版本页。每次工具结果复制后释放R临时对象，随后重新验证公开矩阵；这些测量不构成20,000细胞或云服务器容量承诺。

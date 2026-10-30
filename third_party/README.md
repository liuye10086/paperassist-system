# 本地第三方声明材料

本目录保存2026-10-27第二批从本机已安装依赖及既有离线镜像读取的原始许可、版权和NOTICE文件。文件原始字节未重排或转码；`index.json`按组件、版本和来源路径引用`texts/<SHA-256>.txt`。相同正文可共享一个文件，版权和来源仍逐条保留。`manifest.json`汇总索引哈希和未完成项，当前状态为`local_materials_partial`，S10-BE46继续未勾选。

## 范围与来源

| 目录 | 实测对象 | 用途和边界 |
|---|---|---|
| [python-linux](python-linux/index.json) | 既有固定应用基础镜像内91个Python发行包 | 79个requirements固定包全部版本一致；镜像内实际还含测试/构建工具，这些同样列出，不能仅因用途是测试就认定未分发。最终候选应再次核对本索引。 |
| [python-windows](python-windows/index.json) | 本机venv内102个Python发行包 | 本机开发/运行输入，不能替代Linux二进制证据；PDFium两平台原文分别保存。 |
| [frontend](frontend/index.json) | package-lock中219个包，127个本机已安装 | React、React DOM及scheduler属于运行依赖；其余锁定项为构建/测试工具。未安装的可选平台包只保留锁定元数据，不报告已取得其正文。 |
| [system-app](system-app/index.json) | 应用基础镜像 | 实有系统包版本数据库和版权文件。 |
| [system-renderer](system-renderer/index.json) | 固定LibreOffice渲染镜像 | 含实际系统/LibreOffice材料；Windows字体只读挂载，不进入本目录或候选镜像。 |
| [system-postgres](system-postgres/index.json) | 固定PostgreSQL镜像 | 实有系统/数据库版权文件。 |
| [system-broker](system-broker/index.json) | 固定RabbitMQ/Alpine镜像 | APK包元数据及实有RabbitMQ/Erlang等声明。元数据不是缺失正文的替代。 |

各索引`source.image_id`是本地实测完整不可变镜像ID，`source.retained_container`为只读、断网探针容器。应用镜像以`script/release/release.py`固定基础镜像构建；这些材料随候选复制至`/releaseapp/third_party`并纳入源码清单哈希。系统服务镜像仍按原固定ID使用，没有拉取或重新分发。

## 已补材料

- openpyxl 3.1.5：`LICENCE.rst`；et-xmlfile 2.0.0：`LICENCE.rst`、`LICENCE.python`和`AUTHORS.txt`，保留British拼写及Python历史许可链。
- pypdfium2 5.14.0 / PDFium 156.0.8076.0：外层三份许可正文及Windows/Linux各15份`BUILD_LICENSES`，包含实际嵌入库声明。
- ONNX Runtime：随包`ThirdPartyNotices.txt`与自身许可分别保存；不以顶层许可代替嵌入库材料。
- tqdm 4.70.1：保留随包`LICENCE`，其元数据原值为`MPL-2.0 AND MIT`，文件含MIT正文和MPL Exhibit A。完整MPL正文来源绑定仍待补。
- RapidOCR 3.10.0：代码LICENSE及`MODEL_LICENSES.md`分别保存；notice列出三模型及PaddleOCR来源说明。模型实测SHA与固定OCR合同一致，字典实测见下面的边界。

## 保留未完成项

1. flatbuffers 25.12.19两平台仅有Apache元数据/源码头，尚缺同版本完整许可正文及适用NOTICE依据。没有拿其他包Apache正文冒充该版本随包材料。
2. tqdm完整MPL正文及其来源绑定未补齐。
3. RapidOCR三模型已有随包来源声明，但识别ONNX内`character`字典没有独立明确归属/适用说明。该字段74946字节，SHA-256为`f7aa897ca828a4c7c9e2739c30f9161a33306d532f020bcdb91dcfb664a5507e`；嵌入模型可核实，适用条件保留未核实。
4. 已安装前端构建/测试包`@esbuild/win32-x64`、`@oxlint/binding-win32-x64-msvc`、`@rolldown/binding-win32-x64-msvc`、两种`@rollup/rollup-win32-x64-*`、`saxes`、`stackback`缺独立本地正文。锁定许可字段仍按原值保存，不能当作完整声明。其余未安装可选平台包不新增下载。
5. Windows字体、用户研究材料及本地素材不复制入本目录；字体/素材未来分发条件仍待确认。本批没有新增商用、公开或再分发授权。
6. 已收集系统及嵌入软件实有材料；各二进制适用条件、源码提供等义务尚未逐项完成核对。列出文件不等同整个分发物已经核定。

上述缺件仍需要同版本来源材料或额外授权，本批不联网补取，不据用户工程验收推定第三方权利。

## 复核与更新

```powershell
backend/.venv/Scripts/python.exe script/notices/verify_local.py
```

该命令核对每份原文字节/SHA、索引、79个Python固定版本及前端锁定哈希，不运行应用、模型或外部调用。重新采集使用`script/notices/collect_local.py --kind ... --output <新目录>`；镜像模式还需显式`--image <已有完整ID>`，始终`--pull=never --network=none --read-only`并保留探针容器。历史目录先另存运行材料，复核后替换本目录索引，不能覆盖历史收据。随后使用`verify_local.py --write-manifest`重新绑定聚合索引。

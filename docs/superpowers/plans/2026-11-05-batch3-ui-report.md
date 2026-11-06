# 第3批前端接线记录

要求：用户已确认第3批且要求启用整合与协变量处理。新建参数使用后端返回的默认值（Harmony开启、测序深度协变量、batch HVG）；允许关闭。既有参数缺字段仍显示关闭，不改历史结果。合同与边界见本目录`2026-11-05-batch3-backend-brief.md`。

已接`SingleCellIntegrationFields`至直接启动与既有单细胞配置页；不加入空间配置。参数：hvg_batch_key、technical_covariates、harmony。Harmony启用时选择4GiB资源提示。线粒体协变量需确认规则，直接启动变更规则时清理不再适用的线粒体协变量。结果PCA/UMAP页显示`single_cell_integration`实际状态与下游表示，纳入`integration_`图表/成员。

验证：新增`SingleCellIntegration.test.tsx`先因缺组件失败；接入后3通过1失败（未应用文案重复使断言范围过宽），调整断言到两项方法的状态段后4通过。原DirectStart4项、BioSpatialWorkflow9项同轮通过。初次构建发现unknown JSX条件类型错误，改为显式布尔后最终构建通过559 modules；既有大bundle warning仍在。日志`script/.runtime/single-cell-batch3/frontend-build.log`。

目前后端实现仍进行中，浏览器及真实结果/Word验证未完成，不将模拟组件测试称为完整验收。新结果理由映射与表格键需等后端实际产物再核对。

独立审查发现HVG回退字段需与后端对齐，以及既有配置中已选mt_fraction在撤销规则确认后不能关闭。后端已承诺输出fallback/reason；前端改为显示实际HVG策略并补齐实际reason中文映射，线粒体项在已选时始终允许取消。新增失效协变量取消用例、回退显示用例，定向 **18 passed**（Integration5、DirectStart4、BioSpatialWorkflow9）。表格键对齐为integration_diagnostics/design/coordinates/tool_versions。审查复核及真实产物验证待完成。

独立复核spec/quality均通过，无Critical/Important。按Minor建议同步成功fixture为batch_aware_seurat并断言实际批次HVG文案；5项再次通过。构建及浏览器端实际产物仍按最终冻结状态验证。


## 最终交叉模块复核

整合图详情曾误进入仅支持普通图类型的编辑器，实际触发 undefined.map。已将内部整合图详情保留为只读预览、下载及来源导航。两个新增详情回归先真实失败后通过；相关4文件共35项通过，日志见 `script/.runtime/single-cell-batch3/frontend-final.log`。最终静态复审 Important/Minor 均已关闭；浏览器真实结果及最终Word检查仍待主任务完成。

浏览器实页已核对新分析默认：HVG=batch、测序深度协变量开启、Harmony开启(theta2/lambda1/max_iter10)，未确认线粒体规则时该协变量禁用；当前资源提示4096MiB。整合参数区复选框和标签排版正常。仅查看参数，未通过页面额外提交计算。

最终浏览器核对实际单文库协变量已应用/Harmony未应用、双文库Harmony与协变量已应用及实际下游表示。两类内部整合图详情均可预览下载、无编辑器，最新metadata显示隐藏无效默认字段；详情17项回归与最终559 modules构建通过。英文Word实际浏览器下载成功，document.xml和嵌入图与API版一致。正式交付结构检查通过；英文17页全页视觉通过，中文20页新增整合内容通过但第6—7页既有marker标签密集，详见阶段04实施记录，不宣称全报告无排版问题。

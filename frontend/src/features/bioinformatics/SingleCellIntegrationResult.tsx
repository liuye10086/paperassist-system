type Result=Record<string,unknown>
const object=(value:unknown):Result=>value&&typeof value==='object'&&!Array.isArray(value)?value as Result:{}
const statuses:Record<string,string>={completed:'已完成',not_requested:'未请求',not_computable:'不可计算',failed:'失败',unknown:'未知',confounded:'完全混杂',not_confounded:'未发现完全混杂',unconfounded:'未发现完全混杂'}
const reasons:Record<string,string>={
 disabled:'未启用',batch_missing:'缺少完整批次信息',batch_metadata_missing:'缺少完整批次信息',single_batch:'只有一个有效批次',insufficient_batches:'只有一个有效批次',
 batch_group_confounded:'批次与研究组完全混杂，未应用整合',group_missing:'缺少完整研究组信息，无法排除混杂',
 covariate_constant:'所选协变量为常量，未应用处理',covariate_missing:'协变量有缺失值',covariates_collinear:'协变量存在共线性',mitochondrial_rule_unconfirmed:'线粒体规则未确认',tool_failed:'工具运行失败，详见日志',
 batch_values_missing:'缺少完整批次信息',batch_too_small:'部分批次细胞不足，使用全局 HVG',batch_group_completely_confounded:'批次与研究组完全混杂，未应用整合',group_missing_confounding_unassessed:'研究组信息不完整，无法排除混杂',
 covariate_missing_or_nonfinite:'协变量存在缺失或无效数值',covariate_design_rank_deficient:'协变量共线或剩余自由度不足',insufficient_residual_variation:'处理后有效变异不足',insufficient_cells_for_harmony_default_clusters:'细胞数量不足以使用当前 Harmony 默认聚类策略',
 regression_failed:'协变量回归失败，详见日志',harmony_failed:'Harmony 运行失败，详见日志',resource_insufficient:'计算资源不足，该项未完成',
}
const describe=(value:unknown)=>typeof value==='string'?(reasons[value]??'请核对批次信息和分析条件。'):''

export default function SingleCellIntegrationResult({summary}:{summary:Result}){
 const result=object(summary.single_cell_integration)
 if(!Object.keys(result).length)return null
 const hvg=object(result.hvg),technical=object(result.technical_covariates),harmony=object(result.harmony),design=object(result.design)
 const status=(value:Result)=>statuses[String(value.status)]??'未记录'
 const applied=(value:Result)=>value.applied===true?'已应用':'未应用'
 const columns=Array.isArray(technical.columns)?technical.columns.filter(v=>typeof v==='string').join('、'):'未选择'
 return <section className="analysis-detail">
  <h3>多样本整合与技术协变量结果</h3>
  <p>邻居、UMAP 与聚类实际使用：{result.downstream_representation==='X_pca_harmony'?'Harmony 整合表示':result.downstream_representation==='X_pca'?'PCA 表示':'未记录'}</p>
  <h4>HVG 批次策略</h4>
  <p>{status(hvg)}；{hvg.fallback===true?'已回退到全局 HVG':hvg.strategy==='batch_aware_seurat'?`批次感知 HVG；分组字段：${String(hvg.batch_key)}`:'全局 HVG'}</p>
  {!!hvg.reason&&<p>{describe(hvg.reason)}</p>}
  <h4>技术协变量处理</h4>
  <p>{status(technical)}；{applied(technical)}；协变量：{columns||'未选择'}</p>
  {!!technical.reason&&<p>{describe(technical.reason)}</p>}
  <h4>Harmony 批次整合</h4>
  <p>{status(harmony)}；{applied(harmony)}{harmony.batch_key?`；分组字段：${String(harmony.batch_key)}`:''}</p>
  {!!harmony.reason&&<p>{describe(harmony.reason)}</p>}
  <p>批次与研究组设计：{status(design)}{design.reason?`；${describe(design.reason)}`:''}</p>
  <p>原始 counts、normalized 和 log1p 保留；协变量处理仅用于降维，Harmony 仅调整低维表示。前后批次指标用于描述，不能证明生物学准确性。</p>
 </section>
}

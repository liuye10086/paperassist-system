type Result = Record<string, unknown>
const object = (value: unknown): Result => value && typeof value === 'object' ? value as Result : {}
const statuses: Record<string, string> = {completed: '已完成', partial: '部分完成', failed: '失败', not_computable: '不可计算', not_requested: '未请求'}
const reasons: Record<string, string> = {disabled: '未启用', resource_insufficient: '计算内存不足，当前文库未完成该模型；可缩小输入规模或在具备更多资源的运行环境中重新分析。', original_library_id_missing: '缺少原始文库标识', insufficient_cells_or_genes: '有效细胞或基因不足', insufficient_cell_populations: '缺少足够的细胞群体', insufficient_model_conditions: '不满足模型条件', tool_failed: '工具运行失败，详见运行日志', some_libraries_not_computable_or_failed: '部分文库不可计算或失败，详见逐文库结果表', no_library_completed: '没有文库完成计算'}

export default function SingleCellQcResult({summary}: {summary: Result}) {
 const algorithms = object(summary.single_cell_algorithms)
 if (!Object.keys(algorithms).length) return null
 const doublet = object(algorithms.doublet), decontx = object(algorithms.decontx), versions = object(algorithms.versions)
 const number = (value: unknown) => typeof value === 'number' ? value : '—'
 const status = (result: Result) => statuses[String(result.status)] ?? String(result.status ?? '未记录')
 const detail = (result: Result) => <><p>状态：{status(result)}；完成文库：{number(result.completed_libraries)} / {number(result.libraries)}；已计算细胞：{number(result.computed_cells)} / {number(result.input_cells)}</p>{typeof result.reason === 'string' && result.reason && <p>{reasons[result.reason] ?? result.reason}</p>}</>
 return <section className="analysis-detail">
  <h3>双细胞与环境 RNA 结果</h3>
  {algorithms.inherited_from_parent === true && <p className="warning-panel">以下质量模型结果继承父分析，不是在本亚群上重新运行。</p>}
  <h4>scDblFinder 双细胞预测</h4>{detail(doublet)}
  <p>预测双细胞：{number(doublet.predicted_doublets)}；实际排除：{number(doublet.excluded_cells)}</p>
  <p>预测属于模型判断；未启用排除时，预测双细胞仍保留在后续分析中。</p>
  <h4>decontX 环境 RNA 校正</h4>{detail(decontx)}
  <p>{decontx.layer_emitted === true ? '已保存独立 decontx_counts 层；原始 counts 及当前下游输入保持不变。' : '未生成可供后续使用的校正层；原始 counts 及当前下游输入保持不变。'}</p>
  <p>校正是基于细胞群体的模型估计，不能替代实验验证。逐文库状态、参数和原因见下方结果表与日志。</p>
  {Object.keys(versions).length > 0 && <p>实际工具版本：{Object.entries(versions).map(([key, value]) => `${key} ${String(value)}`).join('；')}</p>}
 </section>
}

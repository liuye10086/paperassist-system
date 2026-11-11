import {useI18n} from '../../shared/i18n'
import useResearchDraft from '../research-results/useResearchDraft'
import {bulkComparisonLabel} from './bulk'
import BulkSelectionFields,{BulkSelectionSummary,newBulkSelectionDraft,toBulkSelection,type BulkSelectionDraft} from './BulkSelectionFields'
import {Field,Paging} from './InsightShared'
import {bulkWorkflowBase,type BulkSensitivityRequest,type BulkSensitivityResult,type BulkWorkflowComparison} from './bulkWorkflow'
import {useBulkRequest} from './bulkWorkflowHooks'

type Draft = {mode:'threshold'|'run';baselineId:string;scenarioId:string;baseline:BulkSelectionDraft;scenario:BulkSelectionDraft}
const pageSize=50
const changeLabels:Record<string,string> = {
  stable_up:'稳定上调',stable_down:'稳定下调',changed_direction:'方向改变',gained:'新增入选',lost:'移出筛选',
  unchanged:'分类保持',ineligible:'无法纳入对照',up:'上调',down:'下调',not_significant:'未显著',excluded:'排除',
  not_computable:'不可计算',missing_metric:'缺少统计值',direction_not_selected:'筛选方向未选中',absent:'结果表无该特征',
}

export function bulkComparisonOption(item:BulkWorkflowComparison) {
  return [item.label,...item.contrasts.map(bulkComparisonLabel),item.refs.result_version_id].filter(Boolean).join(' · ')
}

export function sensitivityCompatible(left:BulkWorkflowComparison,right:BulkWorkflowComparison,
  contrast:BulkWorkflowComparison['contrasts'][number]) {
  const lineage=left.sensitivity_lineage??[], otherLineage=right.sensitivity_lineage??[]
  const keys=(values:string[][])=>values.map(value=>JSON.stringify(value)).sort()
  if(!lineage.length||JSON.stringify(keys(lineage))!==JSON.stringify(keys(otherLineage))) return false
  if(!left.sensitivity_identity||!right.sensitivity_identity||
     JSON.stringify(left.sensitivity_identity)!==JSON.stringify(right.sensitivity_identity)) return false
  const selected=(values:string[][])=>values.filter(([,condition])=>condition===contrast.numerator||condition===contrast.denominator)
    .map(([identity])=>identity)
  const samples=new Set(selected(left.sensitivity_samples??[]))
  return selected(right.sensitivity_samples??[]).some(key=>samples.has(key))
}

export default function BulkSensitivity({projectId,comparisons,initialId,onReviewed}:{
  projectId:string;comparisons:BulkWorkflowComparison[];initialId?:string;onReviewed:(value:BulkSensitivityRequest)=>void
}) {
  const {t}=useI18n()
  const [draft,update]=useResearchDraft<Draft>(projectId,`bulk-sensitivity:${initialId??''}`,()=>({
    mode:'threshold',baselineId:initialId??'',scenarioId:'',baseline:newBulkSelectionDraft(),scenario:newBulkSelectionDraft(),
  }))
  const read=useBulkRequest<BulkSensitivityResult>()
  const baseline=comparisons.find(item=>item.refs.result_version_id===draft.baselineId)
  const independent=draft.mode==='run'
  const comparison=baseline?.contrasts.find(item=>item.contrast_id===draft.baseline.contrast_id)
  const eligibleScenarios=comparisons.filter(item=>baseline&&comparison&&item!==baseline&&sensitivityCompatible(baseline,item,comparison)&&
    item.contrasts.some(c=>c.numerator===comparison?.numerator&&c.denominator===comparison?.denominator))
  const scenario=independent?eligibleScenarios.find(item=>item.refs.result_version_id===draft.scenarioId):baseline
  const scenarioContrasts=scenario?.contrasts.filter(item=>item.numerator===comparison?.numerator&&item.denominator===comparison?.denominator)??[]
  const baselineSelection=toBulkSelection(draft.baseline,baseline?.contrasts??[])
  const scenarioSelection=toBulkSelection(independent?draft.scenario:{...draft.scenario,contrast_id:draft.baseline.contrast_id},scenarioContrasts)
  const body:BulkSensitivityRequest|null=baseline&&scenario&&baselineSelection&&scenarioSelection?{
    baseline_version_id:draft.baselineId,scenario_version_id:scenario.refs.result_version_id!,
    baseline_selection:baselineSelection,scenario_selection:scenarioSelection,
  }:null
  const signature=body?JSON.stringify(body):''
  const response=read.data?.signature===signature?read.data.value:null
  const result=response?.baseline.version_id===body?.baseline_version_id&&response?.scenario.version_id===body?.scenario_version_id?response:null

  async function compare(page:number) {
    if(!body) return
    const checked=await read.submit(`${bulkWorkflowBase(projectId)}/sensitivity`,{...body,page,page_size:pageSize},signature)
    if(checked&&checked.baseline.version_id===body.baseline_version_id&&checked.scenario.version_id===body.scenario_version_id) onReviewed(body)
  }

  return <section className="analysis-detail" aria-label={t('稳健性与样本处理前后对照')}>
    <h3>{t('稳健性与样本处理前后对照')}</h3>
    <p>{t('选择已确认并发布的比较版本。筛选变体复用固定统计，模型或样本变化使用另一个已发布运行。')}</p>
    {!comparisons.length&&<p>{t('暂无可用的固定 Bulk 比较结果。')}</p>}
    {!!comparisons.length&&<form onSubmit={event=>{event.preventDefault();void compare(1)}}>
      <fieldset className="bulk-workflow-fields" disabled={read.busy||!read.valid}>
        <Field label="稳健性对照类型" value={draft.mode} onChange={mode=>update({...draft,mode:mode as Draft['mode']})}>
          <option value="threshold">{t('复用固定统计并调整筛选')}</option>
          <option value="run">{t('比较独立固定运行与样本处理前后')}</option>
        </Field>
        <Field label="基线固定比较版本" value={draft.baselineId} onChange={baselineId=>update({...draft,baselineId,
          scenarioId:'',baseline:newBulkSelectionDraft(),scenario:newBulkSelectionDraft()})}>
          <option value="">{t('请选择')}</option>
          {comparisons.map(item=><option key={item.refs.result_version_id!} value={item.refs.result_version_id!}>{bulkComparisonOption(item)}</option>)}
        </Field>
        {baseline&&<BulkSelectionFields title="基线筛选" value={draft.baseline} contrasts={baseline.contrasts}
          onChange={value=>update({...draft,baseline:value})}/>}
        {independent&&<Field label="另一个固定比较版本" value={draft.scenarioId} onChange={scenarioId=>update({...draft,scenarioId,scenario:newBulkSelectionDraft()})}>
          <option value="">{t('请选择')}</option>
          {eligibleScenarios.map(item=><option key={item.refs.result_version_id!} value={item.refs.result_version_id!}>{bulkComparisonOption(item)}</option>)}
        </Field>}
        {comparison&&independent&&!eligibleScenarios.length&&<p>{t('暂无同一原始数据版本、具有共同样本且方向兼容的其他已发布运行。')}</p>}
        {comparison&&scenario&&<BulkSelectionFields title="变体筛选" contrasts={scenarioContrasts} fixedContrast={!independent}
          value={independent?draft.scenario:{...draft.scenario,contrast_id:draft.baseline.contrast_id}}
          onChange={value=>update({...draft,scenario:value})}/>}
        <button type="submit" disabled={!body}>{t('核对并比较固定结果')}</button>
      </fieldset>
    </form>}
    {read.busy&&<p role="status">{t('正在核验固定来源，大文件可能需要数分钟。')} <button type="button" onClick={read.cancel}>{t('取消等待')}</button></p>}
    {read.error&&<p role="alert">{t(read.error)}</p>}
    {response&&!result&&<p role="alert">{t('固定来源身份不匹配，请重新打开。')}</p>}
    {result&&<>
      <BulkSensitivitySummary result={result}/>
      <div className="field-table-scroll"><table className="field-table" aria-label={t('基因稳健性对照结果')}>
        <thead><tr>{['稳定特征 ID','基因符号','基线分类','变体分类','变化','基线 q','变体 q','基线 log2FC','变体 log2FC'].map(label=><th key={label}>{t(label)}</th>)}</tr></thead>
        <tbody>{result.items.map(row=><tr key={row.feature_id}><th scope="row">{row.feature_id}</th>
          <td>{row.symbol??'—'}</td><td>{t(changeLabels[row.baseline_class]??row.baseline_class)}</td>
          <td>{t(changeLabels[row.scenario_class]??row.scenario_class)}</td><td>{t(changeLabels[row.change]??row.change)}</td>
          <td>{row.baseline_q??'—'}</td><td>{row.scenario_q??'—'}</td><td>{row.baseline_effect??'—'}</td><td>{row.scenario_effect??'—'}</td>
        </tr>)}</tbody>
      </table></div>
      <Paging page={result.page} size={result.page_size} total={result.total} onPage={page=>void compare(page)}/>
    </>}
  </section>
}

export function BulkSensitivitySummary({result}:{result:Pick<BulkSensitivityResult,'comparison_type'|'baseline'|'scenario'|'sample_changes'|'parameter_changes'|'counts'>}) {
  const {t}=useI18n()
  return <section>
    <h4>{t(result.comparison_type==='threshold_only'?'固定统计筛选对照':'独立固定运行对照')}</h4>
    {([['基线筛选',result.baseline],['变体筛选',result.scenario]] as const).map(([label,side])=><p key={label}>
      <strong>{t(label)}</strong> · {bulkComparisonLabel({contrast_id:side.selection.contrast_id,numerator:side.numerator,denominator:side.denominator})}
      {' · '}<BulkSelectionSummary value={side.selection}/><br/>
      <code>{side.version_id}</code> · <code>{side.run_id}</code> · <code>{side.plan_version_id}</code>
    </p>)}
    <dl className="bulk-workflow-metrics">
      {Object.entries(result.counts).map(([key,value])=><div key={key}><dt>{t(changeLabels[key]??key)}</dt><dd>{value}</dd></div>)}
    </dl>
    <h4>{t('样本处理前后')}</h4>
    <ul>
      <li>{t('共同样本数')} · {result.sample_changes.shared}</li>
      <li>{t('变体新增样本')} · {result.sample_changes.added.join(', ')||'—'}</li>
      <li>{t('变体移除样本')} · {result.sample_changes.removed.join(', ')||'—'}</li>
      <li>{t('样本分配变化')} · {result.sample_changes.reassigned.join(', ')||'—'}</li>
      {!!result.sample_changes.metadata_changed?.length&&<li>{t('样本元数据变化')} · {result.sample_changes.metadata_changed.join(', ')}</li>}
    </ul>
    <p>{t('科学参数差异')} · {result.parameter_changes.join(', ')||'—'}</p>
  </section>
}

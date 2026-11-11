import {useI18n} from '../../shared/i18n'
import {bulkComparisonLabel,bulkQColumns,validBulkSelection,type BulkSelection} from './bulk'
import type {BulkWorkflowComparison} from './bulkWorkflow'
import {Field} from './InsightShared'

export type BulkSelectionDraft = Omit<BulkSelection,'q_threshold'|'minimum_absolute_effect'> & {
  q_threshold:string
  minimum_absolute_effect:string
}

export const bulkDirections = {both:'双向 DEG',up:'上调 DEG',down:'下调 DEG'} as const

export function newBulkSelectionDraft(contrastId=''):BulkSelectionDraft {
  return {contrast_id:contrastId,q_column:'q_within_contrast',q_threshold:'0.05',minimum_absolute_effect:'1',direction:'both'}
}

export function toBulkSelection(draft:BulkSelectionDraft,contrasts:BulkWorkflowComparison['contrasts']) {
  if(!draft.q_threshold.trim()||!draft.minimum_absolute_effect.trim()||!contrasts.some(c=>c.contrast_id===draft.contrast_id)) return null
  const value={...draft,q_threshold:Number(draft.q_threshold),minimum_absolute_effect:Number(draft.minimum_absolute_effect)}
  return validBulkSelection(value)?value:null
}

export default function BulkSelectionFields({title,value,contrasts,onChange,fixedContrast=false}:{
  title:string;value:BulkSelectionDraft;contrasts:BulkWorkflowComparison['contrasts'];onChange:(value:BulkSelectionDraft)=>void;fixedContrast?:boolean
}) {
  const {t}=useI18n()
  const fixed=contrasts.find(item=>item.contrast_id===value.contrast_id)
  return <fieldset className="bulk-workflow-fields"><legend>{t(title)}</legend>
    {fixedContrast&&fixed?<p>{t('固定比较方向')} · {bulkComparisonLabel(fixed)}</p>:<Field label="固定比较方向" value={value.contrast_id} onChange={contrast_id=>onChange({...value,contrast_id})}>
      <option value="">{t('请选择')}</option>
      {contrasts.map(contrast=><option key={contrast.contrast_id} value={contrast.contrast_id}>{bulkComparisonLabel(contrast)}</option>)}
    </Field>}
    <Field label="q 值口径" value={value.q_column} onChange={q_column=>onChange({...value,q_column:q_column as BulkSelectionDraft['q_column']})}>
      {Object.entries(bulkQColumns).map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}
    </Field>
    <Field label="q 阈值" type="number" min={0} max={1} step="any" value={value.q_threshold}
      onChange={q_threshold=>onChange({...value,q_threshold})}/>
    <Field label="最小绝对效应" type="number" min={0} max={1000000} step="any" value={value.minimum_absolute_effect}
      onChange={minimum_absolute_effect=>onChange({...value,minimum_absolute_effect})}/>
    <Field label="DEG 方向" value={value.direction} onChange={direction=>onChange({...value,direction:direction as BulkSelectionDraft['direction']})}>
      {Object.entries(bulkDirections).map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}
    </Field>
  </fieldset>
}

export function BulkSelectionSummary({value}:{value:BulkSelection}) {
  const {t}=useI18n()
  return <>{t(bulkQColumns[value.q_column])} ({value.q_column}) · q ≤ {value.q_threshold} · |log2FC| ≥ {value.minimum_absolute_effect} · {t(bulkDirections[value.direction])}</>
}

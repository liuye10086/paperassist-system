import {researchOutputDefault} from './researchOutputDefault'
import type {AnalysisSelection} from '../analysis/analysisSelection'
import { useI18n } from '../../shared/i18n'
import './researchRequest.css'
import { observationLabels, researchFieldLabels, type ObservationStructure, type ResearchRequest } from './researchRequest'

export default function ResearchRequestForm({ value, onChange, disabled, selection }: { selection?:AnalysisSelection;value: ResearchRequest; onChange: (value: ResearchRequest) => void; disabled: boolean }) {
  const { t } = useI18n()
  return <div className="research-request-form">
    <div className="analysis-field-grid"><label>{t('研究问题')}<textarea value={value.question} rows={3} maxLength={4000} disabled={disabled} onChange={event => onChange({ ...value, question: event.target.value })} /></label>
      <label>{t('输出语言')}<select value={value.output_language} disabled={disabled} onChange={event => onChange({ ...value, output_language: event.target.value as ResearchRequest['output_language'] })}><option value="zh-CN">{t('中文')}</option><option value="en">{t('英文')}</option></select></label>
      {(['population', 'study_design', 'observation_unit'] as const).map(field => <label key={field}>{t(researchFieldLabels[field])}<textarea rows={2} value={value[field]} maxLength={2000} disabled={disabled} onChange={event => onChange({ ...value, [field]: event.target.value })} /></label>)}
      <label>{t('观察结构')}<select value={value.observation_structure} disabled={disabled} onChange={event => onChange({ ...value, observation_structure: event.target.value as ObservationStructure })}>{Object.entries(observationLabels).map(([key, label]) => <option key={key} value={key}>{t(label)}</option>)}</select></label>
      <label>{t('配对或重复测量关系')}<textarea rows={2} value={value.relationship_description} maxLength={2000} disabled={disabled} onChange={event => onChange({ ...value, relationship_description: event.target.value })} /></label>
      <label>{t('输出要求（可选）')}<textarea rows={2} value={value.output_requirements} maxLength={2000} disabled={disabled} onChange={event => onChange({ ...value, output_requirements: event.target.value })} /></label>
    </div>
    <p className="muted">{t('研究问题保留原文；未填写的输出要求默认：{requirements}。',{requirements:t(researchOutputDefault(selection))})}</p>
    <p className="muted">{t('研究声明保留在本地；模型建议、资料补交和预算同意均不能替代计划确认。')}</p>
    <p className="muted">{t('新成果沿用已确认的任务语言；已保存历史成果保留原语言。')}</p>
  </div>
}

import {researchOutputDefault} from './researchOutputDefault'
import type {AnalysisSelection} from '../analysis/analysisSelection'
import { useI18n } from '../../shared/i18n'
import './researchRequest.css'
import { observationLabels, researchFieldLabels, type ResearchRequest } from './researchRequest'

export default function ResearchRequestSummary({ value,selection }: { value: ResearchRequest;selection?:AnalysisSelection }) {
  const { t } = useI18n()
  return <div className="research-request-summary"><h5>{t('已保存的研究需求')}</h5>
    <dl><div><dt>{t('研究问题')}</dt><dd>{value.question}</dd></div>
      <div><dt>{t('输出语言')}</dt><dd>{t(value.output_language === 'en' ? '英文' : '中文')}</dd></div>
      {(['population', 'study_design', 'observation_unit'] as const).map(field => <div key={field}><dt>{t(researchFieldLabels[field])}</dt><dd>{value[field] || t('未填写')}</dd></div>)}
      <div><dt>{t('观察结构')}</dt><dd>{t(observationLabels[value.observation_structure])}</dd></div>
      <div><dt>{t('配对或重复测量关系')}</dt><dd>{value.relationship_description || t('未填写')}</dd></div>
      <div><dt>{t('输出要求（可选）')}</dt><dd>{value.output_requirements.trim()?value.output_requirements:t(researchOutputDefault(selection))}</dd></div>
    </dl><p className="muted">{t('研究声明保留在本地；模型建议、资料补交和预算同意均不能替代计划确认。')}</p>
    <p className="muted">{t('新成果沿用已确认的任务语言；已保存历史成果保留原语言。')}</p>
  </div>
}

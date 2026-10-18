export type ObservationStructure = 'unknown' | 'independent' | 'paired' | 'repeated'
export type ResearchRequest = { question: string; output_language: 'zh-CN' | 'en'; population: string; study_design: string; observation_unit: string; observation_structure: ObservationStructure; relationship_description: string; output_requirements: string }
export const researchFieldLabels = { population: '研究人群', study_design: '研究设计', observation_unit: '观察单位', observation_structure: '观察结构', relationship_description: '配对或重复测量关系', independent_observations:'每行独立观察声明', relationship_form:'关系形态', inference_assumptions_confirmed:'推断前提确认', independent_units:'观察单位独立声明',distribution:'分布前提',inference_confirmed:'方法推断前提确认',outcome_column:'结局列',covariates:'预先指定协变量',positive:'阳性编码',negative:'阴性编码',covariate_levels:'分类水平',covariate_reference:'分类参照水平',score_column:'冻结评分列',direction:'评分方向',score_kind:'评分类型',score_source:'评分来源',score_version:'评分版本',formation:'评分形成方式',evaluation_role:'评估数据角色',independence_confirmed:'评分与评估独立关系声明',outcome_time:'结局时间窗',id_column:'个体 ID 列',time_column:'随访时间列',status_column:'事件状态列',event:'事件编码',censored:'删失编码',time_unit:'时间单位',time_origin:'时间起点',noninformative_censoring:'非信息性删失声明',groups:'参与分组' }
export type ResearchMissing = keyof typeof researchFieldLabels
export const observationLabels: Record<ObservationStructure, string> = { unknown: '尚不确定', independent: '独立观察', paired: '配对观察', repeated: '重复测量' }
export function emptyResearchRequest(): ResearchRequest { return { question: '', output_language: 'zh-CN', population: '', study_design: '', observation_unit: '', observation_structure: 'unknown', relationship_description: '', output_requirements: '' } }
export function isResearchRequest(value: unknown): value is ResearchRequest {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const item = value as Record<string, unknown>
  return Object.keys(item).length === 8 && typeof item.question === 'string' && item.question.trim().length > 0 && item.question.length <= 4000
    && (item.output_language === 'zh-CN' || item.output_language === 'en')
    && typeof item.observation_structure === 'string' && Object.hasOwn(observationLabels, item.observation_structure)
    && ['population', 'study_design', 'observation_unit', 'relationship_description', 'output_requirements'].every(key => typeof item[key] === 'string' && item[key].length <= 2000)
}
export function isResearchMissing(value: unknown): value is ResearchMissing[] { return Array.isArray(value) && value.every(field => typeof field === 'string' && Object.hasOwn(researchFieldLabels, field)) && new Set(value).size === value.length }

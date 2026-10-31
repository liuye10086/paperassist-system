import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {projectBase} from './api'
import {useInsightRead} from './hooks'
import {DataDetails,ReadState} from './InsightShared'
export default function InsightImpact({projectId,id,resource=false}:{projectId:string;id:string;resource?:boolean}){const{t}=useI18n(),[enabled,setEnabled]=useState(false),impact=useInsightRead<{affected:unknown[];affected_truncated:boolean;newer_version_id?:string|null}>(`${projectBase(projectId)}/${resource?'bio-resources':'bio-insight-results'}/${encodeURIComponent(id)}/impact`,enabled,true);return <section><button type="button" onClick={()=>{setEnabled(true);if(enabled)impact.refresh()}}>{t('检查下游影响与新版提示')}</button><ReadState {...impact}/>{impact.data&&<><p>{t('固定来源保持不变；下游计划、图、发现、报告和稿件仅提示影响，不自动重算或替换。')}</p>{impact.data.newer_version_id&&<p>{t('存在资源新版')} · {impact.data.newer_version_id}</p>}{impact.data.affected_truncated&&<p>{t('影响链达到查询上限，显示结果不完整。')}</p>}<DataDetails title="下游依赖影响" value={impact.data.affected}/></>}</section>}

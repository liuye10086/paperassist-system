import {useInsightRead} from './hooks'
import {projectBase} from './api'
import type {Result,TablePage} from './contracts'
import {Field,ReadState} from './InsightShared'
import {strings} from './state'
import {useI18n} from '../../shared/i18n'
export default function ResultContrastChoice({projectId,sourceId,value,onChange}:{projectId:string;sourceId:string;value:string;onChange:(v:string)=>void}){const{t}=useI18n(),result=useInsightRead<Result>(`${projectBase(projectId)}/bio-insight-results/${encodeURIComponent(sourceId)}`,true,true),member=result.data?.members.find(m=>m.key===result.data?.summary.result_member_key),table=useInsightRead<TablePage>(member?`${projectBase(projectId)}/bio-insight-results/${sourceId}/tables/${encodeURIComponent(member.key)}?page=1&page_size=1`:'',!!member,true),ids=[...new Set([...strings(result.data?.methods.family_contrast_ids),...((result.data?.summary.actual_units??[]) as {contrast_id?:string}[]).flatMap(v=>v.contrast_id?[v.contrast_id]:[]),...(table.data?.items.flatMap(v=>typeof v.contrast_id==='string'?[v.contrast_id]:[])??[])])];return <div><Field label={`来源 ${sourceId.slice(0,8)} 的固定比较`} value={value} onChange={onChange}><option value="">{t('请选择实际比较')}</option>{ids.map(id=><option key={id}>{id}</option>)}</Field><ReadState {...result}/><ReadState {...table}/></div>}

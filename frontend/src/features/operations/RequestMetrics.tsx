import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {CoverageNote,Filters,ReadState} from './OperationsCommon'
import {timeFields,useOperationsRead,type Metrics} from './operationsApi'
import ToolUsageCounts from './ToolUsageCounts'
export default function RequestMetrics({onForbidden,active=true}:{onForbidden:()=>void;active?:boolean}){
 const{t}=useI18n(),[filters,setFilters]=useState<Record<string,string>>({})
 const read=useOperationsRead<Metrics>('/api/v1/admin/metrics?'+new URLSearchParams(filters),onForbidden,active)
 return <section hidden={!active} aria-label={t('运行指标')}><h3>{t('运行指标')}</h3><p>{t('全站请求指标使用独立时间筛选，不随模型用量筛选变化。')}</p><Filters applyLabel="应用请求指标筛选" fields={timeFields.map(field=>({...field,label:field.key==='from'?'请求指标起始时间':'请求指标结束时间'}))} onApply={setFilters}/><button disabled={read.loading} onClick={read.reload}>{t('刷新请求指标')}</button><ReadState {...read}/>{read.data&&<><CoverageNote coverage={read.data.coverage}/><dl className="operations-facts">{([['requests','请求数'],['errors','错误数'],['rate_limited','429 次数'],['retry_requests','重试请求'],['resume_requests','继续请求'],['recovery_operation_unknown_requests','恢复操作未知的请求'],['model_calls','模型调用'],['tool_calls','工具调用']] as const).map(([key,label])=><div key={key}><dt>{t(label)}</dt><dd>{key==='tool_calls'?t('已知执行 {known} 次；{count} 次调用的执行次数未知',{known:read.data!.tool_calls,count:read.data!.tool_calls_unknown_count??t('未知')}):read.data![key]??t('未知')}</dd></div>)}<ToolUsageCounts value={read.data}/>{Object.entries(read.data.model_calls_by_provenance??{}).map(([key,value])=><div key={key}><dt>{t(({openai_live:'已证实真实调用',synthetic_fixture:'合成验收样例',unknown:'来源未知'} as Record<string,string>)[key]??'来源未知')}</dt><dd>{value}</dd></div>)}</dl><p>{t('HTTP 请求包含被拒绝请求和幂等重放；重试、继续按已验证操作统计，不代表任务失败数或执行尝试数。')}</p><p>{t('历史未记录或未通过校验的恢复操作保留未知，缺失不按零。')}</p><p>{t('允许工具不代表实际执行；缺少证据不按零。')}</p></>}</section>
}

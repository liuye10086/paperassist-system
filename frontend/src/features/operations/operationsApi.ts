import type {ToolUsage} from './ToolUsageCounts'
import { useEffect, useRef, useState } from 'react'
import { apiFetch, onApiSessionChanged } from '../../shared/api/client'
import { useDocumentVisible } from '../tasks/useDocumentVisible'
import { apiError, safeError } from '../../shared/i18n'
export type Page<T> = {items:T[];total:number;page:number;page_size:number}
export type Account={id:string;email:string;role:'user'|'admin';active:boolean;admin_revision:number;updated_at:number;allowed_actions:string[]}
export type SafeTask={id:string;user_id:string;user_email:string;project_id:string;task_type:string;phase:string;status:string;revision:number;created_at:string;updated_at:string;current_attempt:number|null;attempt_count:number;started_at:string|null;finished_at:string|null;elapsed_ms:number|null;error_code:string|null;request_id:string|null;can_open_workspace:boolean;allowed_actions:string[];workspace_url?:string|null}
export type Summary=ToolUsage&{call_count:number;estimated_micro_usd:number|null;estimated_unknown_count:number;actual_micro_usd:number|null;actual_known_micro_usd:number;actual_unknown_count:number;reconciled_count:number;partial_count:number;pending_count:number;not_applicable_count:number;reserved_micro_usd:number;accounted_micro_usd:number;tool_call_count:number;tool_call_unknown_count:number;input_tokens:{known:number;unknown_count:number};output_tokens:{known:number;unknown_count:number};total_tokens:{known:number;unknown_count:number}}
export const provenanceNames={openai_live:'已证实真实调用',synthetic_fixture:'合成验收样例',unknown:'来源未知'} as const
export type Provenance=Record<keyof typeof provenanceNames,Summary>
export type Call=ToolUsage&{tool_call_count:number|null;tool_call_known_count:number;id:string;user_id:string;user_email?:string;project_id:string;task_id:string;task_type:string;model:string;status:string;provider_provenance:keyof typeof provenanceNames;created_at:string;input_tokens:number|null;output_tokens:number|null;total_tokens:number|null;estimated_cost_micro_usd:number|null;reconciliation:{status:string;actual_micro_usd:number|null};reserved_micro_usd:number;accounted_micro_usd:number}
export type Budget={user_id:string;scope_type:string;scope_key:string;limit_micro_usd:number|null;revision:number|null;estimated_micro_usd:number;accounted_micro_usd:number;reserved_micro_usd:number;available_micro_usd:number|null;exceeded:boolean;configured?:boolean}
export type Usage=Page<Call>&{currency:string;period:{kind:string;timezone:string;from:string|null;to:string|null};coverage:{historical_missing_is_zero:boolean};user_charge_enabled:boolean;quota:{configured:boolean};budget_scope:string;budgets:Budget[];summary:Summary;by_provenance:Provenance;groups:{key:string;summary:Summary;by_provenance:Provenance}[];group_by:string;group_total:number;group_page:number;group_page_size:number}
export type Coverage={started_at:string;historical_missing_is_zero:false;policy:string}
export type Log={request_id:string;route_template:string|null;method:string;status:number;elapsed_ms:number;user_id:string|null;task_id:string|null;error_code:string|null;created_at:string}
export type Audit={id:string;source:string;operator:string|null;actor_user_id:string|null;target_user_id:string;before_role:string|null;after_role:string;before_active:boolean|null;after_active:boolean;reason:string;effective_at:number;request_id:string|null}
export type Metrics=ToolUsage&{coverage:Coverage;requests:number;errors:number;rate_limited:number;retry_requests:number;resume_requests:number;model_calls:number;tool_calls:number;tool_calls_unknown_count:number;model_calls_by_provenance:Record<string,number>}
export class OperationsError extends Error {status:number;constructor(status:number,message:string){super(message);this.status=status}}
export async function operationsRequest<T>(url:string,signal:AbortSignal,init:RequestInit={}):Promise<T>{
 const response=await apiFetch(url,{...init,signal});const data=await response.json().catch(()=>null)
 if(!response.ok)throw new OperationsError(response.status,apiError(data,'运营信息读取失败，请重试。'))
 if(data===null||typeof data!=='object')throw new Error('运营信息读取失败，请重试。')
 return data as T
}
export function useOperationsRead<T>(url: string, onForbidden: () => void, active = true) {
 const visible = useDocumentVisible()
 const [sessionValid,setSessionValid] = useState(true)
 const [revision, setRevision] = useState(0)
 const [result, setResult] = useState<{key: string; data: T | null; error: string}>({key: '', data: null, error: ''})
 const request = useRef<AbortController | null>(null)
 const key = `${revision}:${url}`
 useEffect(()=>onApiSessionChanged(()=>{request.current?.abort();setSessionValid(false);setResult({key:'',data:null,error:''})}),[])
 useEffect(() => {
  if (!active || !visible || !sessionValid) return
  const controller = new AbortController()
  request.current = controller
  void operationsRequest<T>(url, controller.signal).then(value => {
   if (!controller.signal.aborted) setResult({key, data: value, error: ''})
  }).catch(cause => {
   if (controller.signal.aborted) return
   if (cause instanceof OperationsError && cause.status === 403) { onForbidden(); return }
   setResult({key, data: null, error: safeError(cause, '运营信息读取失败，请重试。')})
  })
  return () => controller.abort()
 }, [url, key, onForbidden, active, visible, sessionValid])
 return {
  data: result.key === key ? result.data : null,
  error: result.key === key ? result.error : '',
  loading: active && sessionValid && result.key !== key,
  reload: () => { request.current?.abort(); setRevision(n => n + 1) },
 }
}
export function queryUrl(path:string,filters:Record<string,string>,page:number,extra:Record<string,string>={}){const params=new URLSearchParams({...filters,page:String(page),page_size:'10',...extra});return `${path}?${params}`}
export function usd(value:number|null|undefined){return value==null?'未知':`USD ${(value/1_000_000).toFixed(6)}`}

export const timeFields = [{key: 'from', label: '起始时间', type: 'datetime-local'}, {key: 'to', label: '结束时间', type: 'datetime-local'}]

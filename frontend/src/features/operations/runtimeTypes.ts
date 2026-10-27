import {object} from './configurationTypes'

export type PublicRuntime = {status:'normal'|'maintenance'|'service_unavailable';reason:'runtime_control_not_configured'|'runtime_control_unknown'|'operator_maintenance'|'runtime_observation_unknown'|'observed_available'|'service_observation_unavailable';observed_at:string|null}
export type RuntimeHealth = {status:'healthy'|'unavailable'|'unknown';observed_at:string|null}
export type AdminRuntime = PublicRuntime & {
 coverage:{status:'observed'|'unknown';observed_at:string|null;sample_seconds:15;stale_after_seconds:45;historical_missing_is_zero:false}
 services:Record<'worker'|'dispatcher'|'broker',RuntimeHealth>;database:RuntimeHealth
 queue:{queued_count:number;oldest_pending_age_seconds:number|null}|null
 failures:{failed:number;denominator:number;ratio:number|null;window_seconds:3600;window_start:string;window_end:string;coverage:'terminal_tasks_updated_in_window'}|null
 budgets:{status:'known'|'unknown';registered_user_budgets:number;limit_micro_usd:number|null;reserved_micro_usd:number|null;accounted_micro_usd:number|null;coverage:'registered_user_budgets_only_not_global_balance'}|null
 disk:{free_bytes:number;total_bytes:number;coverage:'data_filesystem_only'}|null
 external_limits:{observed_at:string;window_seconds:number;observed_calls:number;observed_429:number;coverage:'recorded_provider_responses'}|null
 concurrency:{desired:1|2;effective:1|2|null;deployment_ceiling:1|2;pending_restart:boolean|null;desired_configuration_id:string|null;desired_configuration_sha256:string|null;effective_configuration_id:string|null;effective_configuration_sha256:string|null}
}
const choices=(value:unknown,values:readonly unknown[])=>values.includes(value)
const natural=(value:unknown):value is number=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0
const amount=(value:unknown)=>value===null||natural(value)
const nonnegative=(value:unknown)=>typeof value==='number'&&Number.isFinite(value)&&value>=0
const stamp=(value:unknown):value is string=>typeof value==='string'&&value.length<=64&&/(Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value))
const nullableStamp=(value:unknown)=>value===null||stamp(value)
const identity=(value:unknown)=>value===null||typeof value==='string'&&value.length>0&&value.length<=64&&/^[a-zA-Z0-9_-]+$/.test(value)
const sha=(value:unknown)=>value===null||typeof value==='string'&&/^[a-f0-9]{64}$/.test(value)
const health=(value:unknown)=>object(value)&&choices(value.status,['healthy','unavailable','unknown'])&&nullableStamp(value.observed_at)
export function isPublicRuntime(value:unknown):value is PublicRuntime {
 return object(value)&&choices(value.status,['normal','maintenance','service_unavailable'])&&choices(value.reason,['runtime_control_not_configured','runtime_control_unknown','operator_maintenance','runtime_observation_unknown','observed_available','service_observation_unavailable'])&&nullableStamp(value.observed_at)
}
export function isAdminRuntime(value:unknown):value is AdminRuntime {
 if(!isPublicRuntime(value))return false
 const v=value as unknown as Record<string,unknown>,c=v.coverage,s=v.services,q=v.queue,f=v.failures,b=v.budgets,d=v.disk,e=v.external_limits,n=v.concurrency
 return object(c)&&choices(c.status,['observed','unknown'])&&nullableStamp(c.observed_at)&&c.sample_seconds===15&&c.stale_after_seconds===45&&c.historical_missing_is_zero===false
  &&object(s)&&health(s.worker)&&health(s.dispatcher)&&health(s.broker)&&health(v.database)
  &&(q===null||object(q)&&natural(q.queued_count)&&(q.oldest_pending_age_seconds===null||nonnegative(q.oldest_pending_age_seconds)))
  &&(f===null||object(f)&&natural(f.failed)&&natural(f.denominator)&&f.failed<=f.denominator&&(f.ratio===null||nonnegative(f.ratio)&&(f.ratio as number)<=1)&&f.window_seconds===3600&&stamp(f.window_start)&&stamp(f.window_end)&&f.coverage==='terminal_tasks_updated_in_window')
  &&(b===null||object(b)&&choices(b.status,['known','unknown'])&&natural(b.registered_user_budgets)&&amount(b.limit_micro_usd)&&amount(b.reserved_micro_usd)&&amount(b.accounted_micro_usd)&&b.coverage==='registered_user_budgets_only_not_global_balance')
  &&(d===null||object(d)&&natural(d.free_bytes)&&natural(d.total_bytes)&&d.free_bytes<=d.total_bytes&&d.coverage==='data_filesystem_only')
  &&(e===null||object(e)&&stamp(e.observed_at)&&natural(e.window_seconds)&&e.window_seconds>=1&&e.window_seconds<=86400&&natural(e.observed_calls)&&natural(e.observed_429)&&e.observed_429<=e.observed_calls&&e.coverage==='recorded_provider_responses')
  &&object(n)&&choices(n.desired,[1,2])&&choices(n.effective,[null,1,2])&&choices(n.deployment_ceiling,[1,2])&&choices(n.pending_restart,[null,true,false])&&identity(n.desired_configuration_id)&&identity(n.effective_configuration_id)&&sha(n.desired_configuration_sha256)&&sha(n.effective_configuration_sha256)
}
export function freshRuntimeStamp(value:string|null,now=Date.now()){
 if(value===null)return false
 const age=now-Date.parse(value)
 return Number.isFinite(age)&&age>=-5_000&&age<=45_000
}

import {useI18n} from '../../shared/i18n'
import {effectName,type ConfigCatalog} from './configurationTypes'
export function ReadonlyField({label,value}:{label:string;value:string|number}){const{t}=useI18n();return <div className="configuration-readonly"><span>{t(label)}</span><strong>{typeof value==='string'?t(value):value}</strong><small>{t('只读')}</small></div>}
export function NumberField({label,value,onChange,min=0,max=1000000000000,step=1,path,catalog}:{label:string;value:number;onChange:(n:number)=>void;min?:number;max?:number;step?:number;path?:string;catalog?:ConfigCatalog}){
 const{t}=useI18n(),range=path?catalog?.effective_ranges[path]:undefined
 const minimum=Math.max(min,range?.minimum??min),maximum=Math.min(max,range?.maximum??max)
 const effect=path?catalog?.field_effects[path]??catalog?.effects[path.split('.')[0] as keyof ConfigCatalog['effects']]:undefined
 return <label>{t(label)}<input aria-label={t(label)} type="number" required min={minimum} max={maximum} step={step} value={value} onChange={e=>onChange(Number(e.target.value))}/><small>{t('有效范围：{min} 至 {max}',{min:minimum,max:maximum})}</small>{effect&&<small>{t(effectName(effect))}</small>}{path&&catalog?.restart_required[path]!==undefined&&<small>{t(catalog.restart_required[path]?'需要重启':'无需重启')}</small>}</label>
}

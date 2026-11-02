import { useI18n } from '../../shared/i18n'
import type { Declaration } from './contracts'
import { declared } from './state'
export default function DeclaredField({label,value,onChange,disabled=false,maxLength=4000,inputType}:{maxLength?:number;label:string;value?:Declaration;onChange:(v:Declaration)=>void;disabled?:boolean;inputType?:'datetime-local'}){
 const {t}=useI18n();const current=value??{state:'pending',value:null}
 const localTime=(text:string)=>{const date=new Date(text);return Number.isNaN(date.getTime())?'':new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16)}
 const change=(text:string)=>onChange(text.trim()?declared('known',inputType?new Date(text).toISOString():text):declared('pending',''))
 return <div className="intake-declared-field"><label>{t(label+'状态')}<select value={current.state} disabled={disabled} onChange={e=>onChange(declared(e.target.value as Declaration['state'],current.value??''))}><option value="pending">{t('待确认')}</option><option value="known">{t('已知')}</option><option value="not_applicable">{t('不适用')}</option></select></label><label>{t(label)}{inputType?<input type={inputType} value={current.value?localTime(current.value):''} disabled={disabled} onChange={e=>change(e.target.value)}/>:<textarea rows={2} value={current.value??''} disabled={disabled} maxLength={maxLength} onChange={e=>change(e.target.value)}/>}</label></div>
}

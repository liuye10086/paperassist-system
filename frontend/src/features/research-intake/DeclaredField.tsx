import { useI18n } from '../../shared/i18n'
import type { Declaration } from './contracts'
import { declared } from './state'
export default function DeclaredField({label,value,onChange,disabled=false,maxLength=4000}:{maxLength?:number;label:string;value?:Declaration;onChange:(v:Declaration)=>void;disabled?:boolean}){
 const {t}=useI18n();const current=value??{state:'pending',value:null}
 return <div className="intake-declared-field"><label>{t(label+'状态')}<select value={current.state} disabled={disabled} onChange={e=>onChange(declared(e.target.value as Declaration['state'],current.value??''))}><option value="pending">{t('待确认')}</option><option value="known">{t('已知')}</option><option value="not_applicable">{t('不适用')}</option></select></label><label>{t(label)}<textarea rows={2} value={current.value??''} disabled={disabled||current.state!=='known'} maxLength={maxLength} onChange={e=>onChange(declared('known',e.target.value))}/></label></div>
}

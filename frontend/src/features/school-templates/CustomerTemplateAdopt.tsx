import {useI18n} from '../../shared/i18n'
import type {Analysis} from './contracts'
import {conflictPrompt,customerSource,readableRuleValue} from './templateSourceLabel'

export type AdoptionState='bindFailed'|'bindUnknown'|'adopted'

/** Customer conflict cards: a plain question, each value with its source name and original text. */
export function ConflictCards({conflicts,decisions,onDecide,disabled}:{conflicts:Analysis['conflicts'];decisions:Record<string,string>;onDecide:(conflictId:string,optionId:string)=>void;disabled:boolean}){
 const {t}=useI18n()
 if(!conflicts.length)return null
 return <section className="template-conflicts" aria-label={t('需要选择的规则')}>
  {conflicts.map(conflict=><fieldset key={conflict.id} className="template-conflict" disabled={disabled}>
   <legend>{conflictPrompt(conflict)}</legend>
   {conflict.options.map(option=>{
    const {label,quote}=customerSource(option.source)
    return <label key={option.id} className="template-choice">
    <input type="radio" name={`template-conflict-${conflict.id}`} value={option.id} checked={decisions[conflict.id]===option.id} onChange={()=>onDecide(conflict.id,option.id)}/>
    <span><strong>{readableRuleValue(conflict.rule_id,option.value)}</strong> · {label}</span>
    {quote&&<span className="template-choice-quote">{t('原文')}：{quote}</span>}
   </label>})}
  </fieldset>)}
 </section>
}

type ActionProps={name:string;change:boolean;bound:boolean;state?:AdoptionState;busy:boolean;ready:boolean;returnPlace?:string;onAdopt:()=>void;onRetry:()=>void;onContinue?:()=>void}
/** One action for customers: confirm (when needed) and adopt; a failed adoption retries only the adoption. */
export function AdoptActions({name,change,bound,state,busy,ready,returnPlace,onAdopt,onRetry,onContinue}:ActionProps){
 const {t}=useI18n()
 if(state==='bindUnknown')return <div className="template-adopt">
  <p role="status">{t('规则已确认，暂未取得模板采用结果。')}</p>
  <button type="button" className="button-primary" disabled={busy} onClick={onRetry}>{t('查看采用结果')}</button>
 </div>
 if(state==='adopted'||bound)return <div className="template-adopt">
  <p role="status">{state==='adopted'?t('已采用 {name}。',{name}):t('这是当前采用的模板。')}</p>
  {onContinue&&<button type="button" className="button-primary" onClick={onContinue}>{t('继续 写作资料与引用')}</button>}
 </div>
 if(state==='bindFailed')return <div className="template-adopt">
  <p role="alert">{t(change?'规则已确认，但还没有改用。':'规则已确认，但模板还没有采用。')}</p>
  <button type="button" className="button-primary" disabled={busy} onClick={onRetry}>{t(change?'重试改用':'重试采用')}</button>
 </div>
 return <div className="template-adopt">
  <button type="button" className="button-primary" disabled={busy||!ready} onClick={onAdopt}>{t(change?'改用这份模板':'采用这份模板')}</button>
  {returnPlace&&<button type="button" disabled={busy||!ready} onClick={onAdopt}>{t('完成并返回 {place}',{place:returnPlace})}</button>}
 </div>
}

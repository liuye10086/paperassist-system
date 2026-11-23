import {useEffect,useId,useRef} from 'react'
import {useI18n} from '../../shared/i18n'
import type {AffectedManuscript,BindingPreview,ChapterChange,Fact,OutputChange} from './contracts'
import {lineRuleId,readableRuleValue,ruleLabel} from './templateSourceLabel'

type Translate=ReturnType<typeof useI18n>['t']
const profiles:Record<string,string>={'bsu-gs501-academic-masters-2026':'北体 GS501 学术型硕士排版'}
const whole=(value:unknown):value is number=>Number.isSafeInteger(value)

/** Customer wording for one chapter difference; never shows the detail key. */
function chapterChangeText(t:Translate,item:ChapterChange):string{
 const {from,to}=item.detail_params??{}
 switch(item.change){
  case 'added':return t('新增章节：{title}',{title:item.title})
  case 'removed':return t('删除章节：{title}',{title:item.title})
  case 'title_changed':return typeof from==='string'&&typeof to==='string'?t('章节改名：{from} → {to}',{from,to}):t('章节改名：{title}',{title:item.title})
  case 'level_changed':return whole(from)&&whole(to)?t('{title}：标题级别由 {from} 级改为 {to} 级',{title:item.title,from,to}):t('{title}：标题级别有变化',{title:item.title})
  case 'order_changed':return whole(from)&&whole(to)?t('{title}：位置由第 {from} 项调整为第 {to} 项',{title:item.title,from,to}):t('{title}：顺序有变化',{title:item.title})
 }
}

// Rule differences arrive with a stable rule id (or `format.{owner}.{property}`) and raw values, translated here.
function outputRuleId(item:OutputChange){
 if(item.rule_id)return item.rule_id
 const rest=item.detail_key.startsWith('format.')?item.detail_key.slice(7):item.detail_key.startsWith('rule.')?item.detail_key.slice(5):''
 return rest.includes('.')?rest:undefined
}
/** Customer wording for one Word format difference; unknown kinds fall back to a generic line. */
function outputChangeText(t:Translate,item:OutputChange,outputs:OutputChange[],targetRules:Fact[]):string{
 const {from,to}=item.detail_params??{}
 const ruleId=outputRuleId(item)
 if(ruleId){
  const companion=lineRuleId(ruleId)
  const difference=companion&&outputs.find(output=>outputRuleId(output)===companion)
  const unchanged=companion&&targetRules.find(rule=>rule.id===companion)?.value
  const value=(side:'from'|'to',v:unknown)=>v===undefined||v===null?t('未指定'):readableRuleValue(ruleId,v,difference?difference.detail_params[side]:unchanged)
  return t('{label}：{from} → {to}',{label:ruleLabel(ruleId),from:value('from',from),to:value('to',to)})
 }
 if(item.detail_key==='format.format_profile'){const value=(v:unknown)=>t(typeof v==='string'?profiles[v]??'其他排版方案':'按模板原样式');return t('排版方案：{from} → {to}',{from:value(from),to:value(to)})}
 if(item.detail_key==='format.front_matter')return typeof from==='boolean'&&typeof to==='boolean'?t('封面等前置规则：{from} → {to}',{from:t(from?'已设置':'未设置'),to:t(to?'已设置':'未设置')}):t('封面等前置规则有变化')
 if(item.detail_key==='format.headers_footers')return t('页眉页脚有变化')
 if(item.detail_key==='format.page_numbers')return t('页码设置有变化')
 return t('其他 Word 格式有变化')
}

type Props={preview:BindingPreview;targetRules?:Fact[];busy:boolean;bindFailed:boolean;bindUnknown?:boolean;onKeep:()=>void;onChange:()=>void;onRetry:()=>void;onMigrate?:(manuscript:AffectedManuscript)=>void}
/** What changing the adopted template affects (interface design section 4). Read-only until the customer changes. */
export default function TemplateChangePreview({preview,targetRules=[],busy,bindFailed,bindUnknown=false,onKeep,onChange,onRetry,onMigrate}:Props){
 const {t,locale}=useI18n();const heading=useRef<HTMLHeadingElement>(null);const id=useId()
 useEffect(()=>{heading.current?.focus()},[])
 const {current,next}=preview
 const date=(value:string|null|undefined)=>{const time=value?new Date(value):null;return time&&!Number.isNaN(time.getTime())?time.toLocaleDateString(locale,{year:'numeric',month:'2-digit',day:'2-digit'}):''}
 const adoptedAt=date(current?.confirmed_at)
 const subtitle=current?adoptedAt?t('当前：{current}（{date} 采用） → 新：{next}',{current:current.template_name,date:adoptedAt,next:next.template_name}):t('当前：{current} → 新：{next}',{current:current.template_name,next:next.template_name}):t('新：{next}',{next:next.template_name})
 return <section className="template-change-preview" aria-labelledby={`${id}-title`}>
  <h3 id={`${id}-title`} ref={heading} tabIndex={-1}>{t('改用后会影响这些章节和格式')}</h3>
  <p>{subtitle}</p>
  <div className="template-change-columns">
   <section aria-labelledby={`${id}-chapters`}><h4 id={`${id}-chapters`}>{t('章节')}</h4>{preview.chapters.length?<ul>{preview.chapters.map((item,index)=><li key={index}>{chapterChangeText(t,item)}</li>)}</ul>:<p className="muted">{t('章节没有变化。')}</p>}</section>
   <section aria-labelledby={`${id}-outputs`}><h4 id={`${id}-outputs`}>{t('Word 格式')}</h4>{preview.outputs.length?<ul>{preview.outputs.map((item,index)=><li key={index}>{outputChangeText(t,item,preview.outputs,targetRules)}</li>)}</ul>:<p className="muted">{t('Word 格式没有变化。')}</p>}</section>
  </div>
  {preview.manuscripts.length>0&&<section aria-labelledby={`${id}-manuscripts`}><h4 id={`${id}-manuscripts`}>{t('已有稿件')}</h4><ul>{preview.manuscripts.map((item,index)=><li key={item.manuscript_id}>
   <strong id={`${id}-m${index}`}>{item.title}</strong>
   <p>{t(onMigrate ? '已下载的 Word 保持原样；第 {N} 版要按新模板导出，需要先把稿件迁移到新模板。' : '第 {N} 版使用原模板。之后生成的初稿将使用新模板。',{N:item.revision})}</p>
   {onMigrate&&<button type="button" disabled={busy} aria-describedby={`${id}-m${index}`} onClick={()=>onMigrate(item)}>{t('迁移到新模板')}</button>}
  </li>)}</ul></section>}
  {bindFailed&&<p role="alert">{t('规则已确认，但还没有改用。')}</p>}
  {bindUnknown&&<p role="status">{t('规则已确认，暂未取得模板采用结果。')}</p>}
  <div className="template-adopt">
   <button type="button" disabled={busy} onClick={onKeep}>{t('保持当前模板')}</button>
   {bindFailed||bindUnknown?<button type="button" className="button-primary" disabled={busy} onClick={onRetry}>{t(bindUnknown?'查看采用结果':'重试改用')}</button>
    :<button type="button" className="button-primary" disabled={busy} onClick={onChange}>{t('改用这份模板')}</button>}
  </div>
 </section>
}

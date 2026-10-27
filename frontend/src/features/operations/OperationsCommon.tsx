import { useState, type FormEvent, type ReactNode } from 'react'
import { useI18n } from '../../shared/i18n'
import type { Coverage } from './operationsApi'
export type Field={key:string;label:string;type?:string;options?:{value:string;label:string}[]}
export function Filters({fields,onApply,initial={},disabled=false,applyLabel='应用筛选',collapsible=false}:{fields:Field[];onApply:(value:Record<string,string>)=>void;initial?:Record<string,string>;disabled?:boolean;applyLabel?:string;collapsible?:boolean}){
 const {t}=useI18n();const [draft,setDraft]=useState(initial),[error,setError]=useState('')
 function apply(event:FormEvent){event.preventDefault();if(disabled)return;const value:Record<string,string>={};for(const field of fields){const item=draft[field.key]?.trim();if(item)value[field.key]=field.type==='datetime-local'?new Date(item).toISOString():item}
  if(value.from&&value.to&&value.from>=value.to){setError('起始时间必须早于结束时间。');return}setError('');onApply(value)
 }
 const form=<form className="operations-filters" onSubmit={apply}>{fields.map(field=><label key={field.key}>{t(field.label)}{field.options?<select disabled={disabled} value={draft[field.key]??''} onChange={event=>setDraft({...draft,[field.key]:event.target.value})}>{field.options.map(option=><option key={option.value} value={option.value}>{t(option.label)}</option>)}</select>:<input disabled={disabled} type={field.type??'text'} value={draft[field.key]??''} onChange={event=>setDraft({...draft,[field.key]:event.target.value})}/>}</label>)}<button type="submit" disabled={disabled}>{t(applyLabel)}</button>{error&&<p role="alert">{t(error)}</p>}</form>
 return collapsible?<details className="operations-filter-disclosure"><summary>{t('筛选条件')}</summary>{form}</details>:form
}

export function ReadState({loading,error,empty}:{loading:boolean;error:string;empty?:boolean}){const{t}=useI18n();return <>{loading&&<p role="status">{t('正在读取运营信息……')}</p>}{error&&<p className="error-panel" role="alert">{t(error)}</p>}{!loading&&!error&&empty&&<p>{t('没有符合筛选条件的记录。')}</p>}</>}
export function Pagination({page,total,size=10,onChange,kind='',disabled=false}:{page:number;total:number;size?:number;onChange:(n:number)=>void;kind?:string;disabled?:boolean}){const{t}=useI18n();return <div className="operations-pagination"><button disabled={disabled||page<=1} onClick={()=>onChange(page-1)}>{t('上一页'+kind)}</button><span>{t('第 {page} 页，共 {total} 条',{page,total})}</span><button disabled={disabled||page*size>=total} onClick={()=>onChange(page+1)}>{t('下一页'+kind)}</button></div>}
export function Table({headers,children}:{headers:string[];children:ReactNode}){const{t}=useI18n();return <div className="operations-table-scroll" tabIndex={0} role="region" aria-label={headers.map(header=>t(header)).join(' / ')}><table><thead><tr>{headers.map(header=><th key={header}>{t(header)}</th>)}</tr></thead><tbody>{children}</tbody></table></div>}
export function CoverageNote({coverage}:{coverage:Coverage}){const{t,locale}=useI18n();return <aside className="operations-note"><p>{t('采集开始时间')}：<time dateTime={coverage.started_at}>{new Date(coverage.started_at).toLocaleString(locale)}</time></p><p>{t('历史缺失采集不代表零；本次请求可能在下次刷新后出现。')}</p><p>{t('有限采集可能遗漏或丢弃记录；没有遗漏计数时不能推断为零。')}</p><p>{t('记录持续保留，不自动删除。')}</p></aside>}
export function DateValue({value}:{value:string|number|null|undefined}){const{t,locale}=useI18n();return value==null?<>{t('未知')}</>:<time>{new Date(typeof value==='number'?value*1000:value).toLocaleString(locale)}</time>}

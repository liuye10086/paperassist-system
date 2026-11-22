import CommonExperiments from './CommonExperiments'
import DeclaredField from './DeclaredField'
import DesignRows from './DesignRows'
import SampleTableMapping from './SampleTableMapping'
import type { MaterialSource } from './MaterialReferences'
import { useLayoutEffect, useRef, useState } from 'react'
import { useI18n } from '../../shared/i18n'
import type { Content, Declaration } from './contracts'

type Row = Record<string, unknown>
type Mode = 'full' | 'customerSamples' | 'assignedDesign'
const modules = [
  ['experiments','通用实验'],['groups','样本分组'],['samples','样本信息'],['mapping','样本表映射'],
  ['observation','统计与比较'],['integration','多组学对应'],['declarations','设计声明'],
]
type Props = {
  sources?: MaterialSource[]; projectId?: string; value: Content; onChange: (v: Content) => void
  disabled?: boolean; mode?: Mode
}
export default function DesignForm({projectId='',sources=[],value,onChange,disabled=false,mode='full'}: Props) {
 const {t} = useI18n()
 const customer = mode === 'customerSamples'
 const assigned = mode === 'assignedDesign'
 const available = modules.filter(([key]) => customer ? ['groups','samples','mapping'].includes(key) : !(assigned && key === 'mapping'))
 const contentRef = useRef<HTMLDivElement>(null)
 const scrollPositions = useRef<Record<string,number>>({})
 const [module,setModule] = useState(available[0][0])
 const [rowPages,setRowPages] = useState<Record<string,number>>({})
 const update=(group:string,key:string,v:unknown)=>onChange({...value,[group]:{...(value[group] as object??{}),[key]:v}})
 const rows = (key: 'experiments'|'groups'|'samples'|'comparisons') => <DesignRows kind={key} {...{value,sources,disabled,onChange}}
   readOnly={assigned && (key === 'samples' || key === 'groups')} page={rowPages[key] ?? 1}
   setPage={page=>setRowPages(previous=>({...previous,[key]:page}))}/>
 const stringList=(group:string,key:string,label:string)=>{const list=group?(value[group] as Row??{})[key]:value[key];return <label>{t(label)}<textarea disabled={disabled} rows={3} value={(list as string[]??[]).join('\n')} onChange={e=>group?update(group,key,e.target.value.split('\n').filter(Boolean)):onChange({...value,[key]:e.target.value.split('\n').filter(Boolean)})}/></label>}
 useLayoutEffect(()=>{if(contentRef.current)contentRef.current.scrollTop=scrollPositions.current[module]??0},[module])
 return <div className="intake-form design-form"><div className="intake-module-layout">
   <nav className="intake-module-nav" aria-label={t(customer ? '样本资料模块' : '实验设计模块')}>
     {available.map(([key,label])=><button type="button" key={key} aria-current={module===key?'step':undefined} onClick={()=>{
       if(contentRef.current)scrollPositions.current[module]=contentRef.current.scrollTop
       setModule(key)
     }}>{t(label)}</button>)}
   </nav>
   <div className="intake-module-content" ref={contentRef}>
     {!customer && <div hidden={module!=='experiments'}><CommonExperiments value={value} onChange={onChange} disabled={disabled}
       onAdded={()=>setRowPages({...rowPages,experiments:Math.ceil((((value.experiments??[]) as Row[]).length+1)/5)})}/>{rows('experiments')}</div>}
     <div hidden={module!=='groups'}>{rows('groups')}</div>
     <div hidden={module!=='samples'}>{rows('samples')}</div>
     {!assigned && <div hidden={module!=='mapping'}><SampleTableMapping {...{projectId,sources,value,disabled,onChange}}/></div>}
     {!customer && <><div hidden={module!=='observation'}><section className="questionnaire-section"><h3>{t('统计单位与重复')}</h3>{[['statistical_unit','统计单位'],['biological_replicate','生物学重复定义'],['technical_replicate','技术重复定义']].map(([key,label])=><DeclaredField key={key} label={label} disabled={disabled} value={(value.observation as Record<string,Declaration>|undefined)?.[key]} onChange={v=>update('observation',key,v)}/>)}<label>{t('配对与重复结构')}<select disabled={disabled} value={(value.observation as {structure?:string})?.structure??'pending'} onChange={e=>update('observation','structure',e.target.value)}>{[['pending','待确认'],['independent','独立'],['paired','配对'],['repeated','重复测量'],['time','时间结构'],['dose','剂量结构']].map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}</select></label></section>{rows('comparisons')}{stringList('','exclusions','排除缺失与异常说明（每行一项）')}
 </div><div hidden={module!=='integration'}><section className="questionnaire-section"><h3>{t('多组学对应')}</h3>{((value.cross_dataset_links??[]) as Row[]).map((link,index)=>{const change=(key:string,v:unknown)=>onChange({...value,cross_dataset_links:(value.cross_dataset_links as Row[]).map((r,i)=>i===index?{...r,[key]:v}:r)});return <fieldset disabled={disabled} key={index}><label>{t('对应关系')}<select value={String(link.relationship??'pending')} onChange={e=>change('relationship',e.target.value)}>{[['pending','待确认'],['same_sample','同一样本'],['same_individual_different_tissue','同一个体不同组织'],['independent','独立实验'],['partial','部分对应']].map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}</select></label><label>{t('对应样本标识（每行一项）')}<textarea value={(link.sample_ids as string[]??[]).join('\n')} onChange={e=>change('sample_ids',e.target.value.split('\n').filter(Boolean))}/></label><label>{t('实际对应说明')}<textarea value={String(link.note??'')} onChange={e=>change('note',e.target.value)}/></label><button type="button" onClick={()=>onChange({...value,cross_dataset_links:(value.cross_dataset_links as Row[]).filter((_,i)=>i!==index)})}>{t('移除此行')}</button></fieldset>})}<button type="button" disabled={disabled} onClick={()=>onChange({...value,cross_dataset_links:[...(value.cross_dataset_links as Row[]??[]),{id:crypto.randomUUID(),relationship:'pending',sample_ids:[],note:''}]})}>{t('添加对应关系')}</button></section>
 </div><div hidden={module!=='declarations'}><section className="questionnaire-section"><h3>{t('设计声明')}</h3>{[['confirmed_by','设计确认人'],['version','设计版本说明'],['source','设计来源']].map(([key,label])=><DeclaredField key={key} label={label} disabled={disabled} value={(value.declarations as Record<string,Declaration>|undefined)?.[key]} onChange={v=>update('declarations',key,v)}/>)}{stringList('declarations','known_gaps','已知缺口（每行一项）')}</section></div></>}
   </div></div></div>
}

// Customer wording for journal records (B03 task 9): raw keys, section IDs, rule keys, article types and
// locations become business labels; internal IDs, hashes and version keys are left out.
import {translate} from '../../shared/i18n'
import {sectionLabels,type SectionId} from '../manuscripts/manuscriptTypes'
import {articleTypes} from '../customer/sciProjectSettings'
import {record} from './contracts'
import {ruleLabels} from './formatContracts'

const technical=/^[0-9a-f]{8}-[0-9a-f-]{27}$|^[0-9a-f]{12,}$|[a-z0-9]_[a-z0-9]|^[\w-]+:[\w:.-]+$/i
const hiddenKeys=new Set(['id','source_id','source_version','rules_version','requirements_version','preserved_ids','selected_id','count_method','origin','note','severity','category','status'])
const keyLabels:Record<string,string>={min:'最少',max:'最多',display_name:'显示名称',level:'标题级别',page:'页码',line:'行号',words:'词数',figures:'图',tables:'表',quote:'原文',location:'位置',value:'要求',section_id:'章节',actual:'实际',expected:'要求',text:'原文',key:'规则',article_type:'文章类型',position:'顺序',source_evidence:'来源依据'}

export function customerArticleType(value:string|null|undefined){
 if(!value)return translate('一般条款')
 if(Object.hasOwn(articleTypes,value))return translate(articleTypes[value as keyof typeof articleTypes])
 if(value==='review')return translate('综述')
 return value
}
export function customerSection(value:string){return Object.hasOwn(sectionLabels,value)?translate(sectionLabels[value as SectionId]):value}
export function customerRule(value:string){return Object.hasOwn(ruleLabels,value)?translate(ruleLabels[value as keyof typeof ruleLabels]):translate('其他要求')}
export function customerLocation(value:unknown):string{
 if(typeof value==='string'){const line=/^line:(\d+)$/.exec(value);if(line)return translate('原文第 {line} 行',{line:line[1]});return technical.test(value)?translate('来源材料中的对应条目'):value}
 return customerValue(value)
}
export function customerValue(value:unknown):string{
 if(value===null||value===undefined)return translate('未知')
 if(typeof value==='boolean')return translate(value?'是':'否')
 if(typeof value==='number')return String(value)
 if(Array.isArray(value))return value.map(customerValue).filter(Boolean).join(' / ')
 if(typeof value==='string'){
  if(Object.hasOwn(sectionLabels,value))return customerSection(value)
  if(Object.hasOwn(ruleLabels,value))return customerRule(value)
  if(/^line:\d+$/.test(value))return customerLocation(value)
  return technical.test(value)?'':value
 }
 if(record(value))return Object.entries(value).filter(([key])=>!hiddenKeys.has(key)).map(([key,item])=>{
  const shown=key==='location'?customerLocation(item):key==='article_type'?customerArticleType(typeof item==='string'?item:null):key==='key'&&typeof item==='string'?customerRule(item):customerValue(item)
  if(!shown)return ''
  if(Object.hasOwn(sectionLabels,key))return `${customerSection(key)}: ${shown}`
  return Object.hasOwn(keyLabels,key)?`${translate(keyLabels[key])}: ${shown}`:shown
 }).filter(Boolean).join('；')
 return ''
}

// Customer wording for school template sources, conflicts and rule values.
// Parser conflict categories: school_template_parser.py `_interpret_requirements` (font size, East Asian font,
// margins, abstract word count) and the heading-mapping conflict. Unknown categories fall back to a generic prompt.
import {translate as t} from '../../shared/i18n'
import {readable,type Source} from './contracts'

export type ConflictLike={id:string;rule_id?:string;kind?:string;options:{id:string;value:unknown;source?:Source}[]}

const roles:Record<string,string>={body:'正文',heading1:'一级标题',heading2:'二级标题',heading3:'三级标题',figure_caption:'图题注',table_caption:'表标题'}
const deeperHeadings:Record<string,string>={
 heading4:'四级标题',heading5:'五级标题',heading6:'六级标题',heading7:'七级标题',heading8:'八级标题',heading9:'九级标题',
}
const otherRoles:Record<string,string>={title_zh:'中文题目',title_en:'英文题目',abstract_heading_zh:'中文摘要标题',abstract_heading_en:'英文摘要标题',references_heading:'参考文献标题',toc_heading:'目录标题',acknowledgements_heading:'致谢标题',keywords_zh:'中文关键词',keywords_en:'英文关键词'}
const otherProperties:Record<string,string>={alignment:'对齐方式',first_line_chars:'首行缩进'}
const alignments:Record<string,string>={left:'左对齐',center:'居中',right:'右对齐',both:'两端对齐',justify:'两端对齐',distribute:'分散对齐'}
const properties:Record<string,{label:string;noun:string}>={
 font_size_pt:{label:'字号',noun:'字号'},font_east_asia:{label:'中文字体',noun:'字体'},font_latin:{label:'英文字体',noun:'字体'},
 line_spacing:{label:'行距',noun:'行距'},line_rule:{label:'行距方式',noun:'行距'},
}
const pageProperties:Record<string,string>={margin_top_cm:'上边距',margin_bottom_cm:'下边距',margin_left_cm:'左边距',margin_right_cm:'右边距',width_cm:'页面宽度',height_cm:'页面高度'}
const sizeNames:[number,string][]=[[26,'一号'],[24,'小一'],[22,'二号'],[18,'小二'],[16,'三号'],[15,'小三'],[14,'四号'],[12,'小四'],[10.5,'五号'],[9,'小五']]
const lineRules:Record<string,string>={auto:'倍数行距',exact:'固定行距',atLeast:'最小行距'}

const isTemplatePart=(part?:string)=>!part||part.startsWith('word/')
const isMapping=(id='',kind?:string)=>kind==='heading_mapping'||id.startsWith('heading-mapping')

/** 学校模板 / 补充规范《文件名》 / 补充说明文字 — never the storage part or path. */
export function sourceLabel(source?:Source):string{
 if(isTemplatePart(source?.part))return t('学校模板')
 if(source!.part==='supplement_text')return t('补充说明文字')
 return t('补充规范《{name}》',{name:source!.part!})
}

/** Parser provenance at formatting nodes describes a setting. Paragraph and supplementary sources are quotations. */
export function customerSource(source?:Source):{label:string;quote?:string}{
 const label=sourceLabel(source)
 const node=source?.path?.match(/\/(?:[\w.-]+:)?([\w.-]+)(?:\[\d+\])?$/)?.[1]
 if(source?.part==='word/styles.xml')return {label:`${label} · ${t(node==='docDefaults'?'文档默认格式':'模板样式')}`}
 if(source?.part==='word/document.xml'){
  if(node==='pgSz'||node==='pgMar'||node==='sectPr')return {label:`${label} · ${t('分节设置')}`}
  if(node==='rPr'||node==='pPr'){
   const marker='；示例：',start=source.text?.indexOf(marker)??-1
   return {label:`${label} · ${t('示例段落格式')}`,quote:start<0?undefined:source.text!.slice(start+marker.length)}
  }
 }
 return {label,quote:source?.text}
}

function described(ruleId:string):{label:string;noun:string}|null{
 if(ruleId==='abstract.word_count')return {label:'摘要字数',noun:'字数'}
 const dot=ruleId.lastIndexOf('.');if(dot<0)return null
 const owner=ruleId.slice(0,dot),property=ruleId.slice(dot+1)
 if(pageProperties[property])return {label:pageProperties[property],noun:property.startsWith('margin_')?'边距':'页面尺寸'}
 if(roles[owner]&&properties[property])return {label:roles[owner]+properties[property].label,noun:properties[property].noun}
 return null
}

/** Customer label for a stable rule id, e.g. body.font_latin → 正文英文字体. */
export function ruleLabel(ruleId:string,fallback='其他格式规则'):string{
 if(isMapping(ruleId))return t('标题级别')
 const found=described(ruleId);if(found)return t(found.label)
 const [owner,property]=ruleId.split('.')
 const role=roles[owner]??deeperHeadings[owner]??otherRoles[owner],label=properties[property]?.label??otherProperties[property]
 return role&&label?`${t(role)} · ${t(label)}`:t(fallback)
}

export function ruleDetailLabel(ruleId:string,fallback?:string):string{
 const label=ruleLabel(ruleId,fallback)
 const section=ruleId.match(/^section-(\d+)\.(\w+)$/)
 return section&&pageProperties[section[2]]?`${t('第 {index} 节',{index:section[1]})} · ${label}`:label
}

export function conflictPrompt(rule:ConflictLike):string{
 if(isMapping(rule.rule_id,rule.kind))return t('学校模板中这一段的原样式和标题标注不同。请选择这一段采用的级别。')
 const found=rule.rule_id?described(rule.rule_id):null
 if(!found)return t('这一项规则在两个来源中不同。请选择这篇论文采用的值。')
 const params={subject:t(found.label),noun:t(found.noun)}
 const fromTemplate=rule.options.some(option=>isTemplatePart(option.source?.part))
 return t(fromTemplate?'学校模板和补充说明的{subject}不同。请选择这篇论文采用的{noun}。':'补充说明中的{subject}要求不同。请选择这篇论文采用的{noun}。',params)
}

export function lineRuleId(ruleId:string|undefined):string|undefined{
 return ruleId?.endsWith('.line_spacing')?ruleId.replace(/\.line_spacing$/,'.line_rule'):undefined
}

export function readableRuleValue(ruleId:string|undefined,value:unknown,lineRule?:unknown):string{
 const id=ruleId??'',number=typeof value==='number'?value:typeof value==='string'&&value.trim()!==''?Number(value):NaN
 if(isMapping(id)&&typeof value==='string')return t(roles[value]??deeperHeadings[value]??'其他段落样式')
 if(id.endsWith('.font_size_pt')&&Number.isFinite(number)){
  const name=sizeNames.find(([size])=>Math.abs(size-number)<=.02)?.[1]
  return name?t(name):t('{size} 磅',{size:number})
 }
 if(id.endsWith('_cm')&&Number.isFinite(number))return t('{value} 厘米',{value:number})
 if(id.endsWith('.first_line_chars')&&Number.isFinite(number))return t('{value} 字符',{value:number/100})
 if(id.endsWith('.alignment')&&typeof value==='string')return t(alignments[value]??'其他对齐方式')
 if(id.endsWith('.line_rule')&&typeof value==='string')return t(lineRules[value]??'其他行距方式')
 if(id.endsWith('.line_spacing')&&Number.isFinite(number)){
  if(lineRule==='auto')return t('{value} 倍',{value:Math.round(number/240*100)/100})
  // The school Word renderer defaults an unspecified line rule to exact spacing.
  return t(lineRule==='atLeast'?'至少 {size} 磅':'固定 {size} 磅',{size:number/20})
 }
 return readable(value)
}

/** Original style attributes keyed by rule id, shown as "正文英文字体：宋体". */
export function readableAttributes(values:Record<string,unknown>):string{
 const entries=Object.entries(values)
 return entries.length?entries.map(([id,value])=>`${ruleLabel(id)}：${readableRuleValue(id,value,values[lineRuleId(id)??''])}`).join('；'):t('原模板未记录对应样式。')
}

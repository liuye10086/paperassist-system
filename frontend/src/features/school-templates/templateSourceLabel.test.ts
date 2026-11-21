import {afterEach,expect,it} from 'vitest'
import {setLocale} from '../../shared/i18n'
import {conflictPrompt,readableRuleValue,ruleLabel,sourceLabel} from './templateSourceLabel'

afterEach(()=>setLocale('zh-CN'))

it.each([4,5,6,7,8,9])('names the parser heading level %i in rules and mapping choices',level=>{
 setLocale('en')
 expect(ruleLabel(`heading${level}.alignment`)).toBe(`Level ${level} heading · Alignment`)
 expect(readableRuleValue('heading-mapping-3',`heading${level}`)).toBe(`Level ${level} heading`)
})
const template={part:'word/document.xml',path:'/w:document/w:body/w:p[4]',text:'正文小四号宋体'}
const file={part:'学校补充规范.docx',path:'document-version:0b8f5c1e-2f4a-4c7d-9a61-3d2e8f7b6a10:e1',text:'正文：五号字'}
const typed={part:'supplement_text',path:'supplement_text',text:'正文四号'}

it('names each conflict source without its storage location',()=>{
 expect(sourceLabel(template)).toBe('学校模板')
 expect(sourceLabel({part:'word/header1.xml'})).toBe('学校模板')
 expect(sourceLabel(file)).toBe('补充规范《学校补充规范.docx》')
 expect(sourceLabel(typed)).toBe('补充说明文字')
 expect(sourceLabel(undefined)).toBe('学校模板')
 setLocale('en')
 expect(sourceLabel(file)).toBe('Supplementary rules “学校补充规范.docx”')
 expect(sourceLabel(typed)).toBe('Supplementary note text')
})

it('asks each parser conflict category as a plain question',()=>{
 const options=[{id:'openxml',value:12,source:template},{id:'text-2',value:10.5,source:file}]
 expect(conflictPrompt({id:'c1',rule_id:'body.font_size_pt',options})).toBe('学校模板和补充说明的正文字号不同。请选择这篇论文采用的字号。')
 expect(conflictPrompt({id:'c2',rule_id:'heading1.font_east_asia',options})).toBe('学校模板和补充说明的一级标题中文字体不同。请选择这篇论文采用的字体。')
 expect(conflictPrompt({id:'c3',rule_id:'section-1.margin_top_cm',options})).toBe('学校模板和补充说明的上边距不同。请选择这篇论文采用的边距。')
 expect(conflictPrompt({id:'c4',rule_id:'abstract.word_count',options:[{id:'text-1',value:'300-500字',source:typed},{id:'text-2',value:'约400字',source:file}]})).toBe('补充说明中的摘要字数要求不同。请选择这篇论文采用的字数。')
 expect(conflictPrompt({id:'c5',kind:'heading_mapping',rule_id:'heading-mapping-3',options:[{id:'original',value:'body',source:template},{id:'alias',value:'heading1',source:template}]})).toBe('学校模板中这一段的原样式和标题标注不同。请选择这一段采用的级别。')
 expect(conflictPrompt({id:'c6',rule_id:'body.unknown_rule',options})).toBe('这一项规则在两个来源中不同。请选择这篇论文采用的值。')
 expect(conflictPrompt({id:'c7',options})).toBe('这一项规则在两个来源中不同。请选择这篇论文采用的值。')
})

it('shows rule values in customer terms and falls back to the raw number',()=>{
 expect(readableRuleValue('body.font_size_pt',12)).toBe('小四')
 expect(readableRuleValue('body.font_size_pt',10.5)).toBe('五号')
 expect(readableRuleValue('heading1.font_size_pt',13)).toBe('13 磅')
 expect(readableRuleValue('section-1.margin_left_cm',2.5)).toBe('2.5 厘米')
 expect(readableRuleValue('heading-mapping-3','heading2')).toBe('二级标题')
 expect(readableRuleValue('heading-mapping-3','body')).toBe('正文')
 expect(readableRuleValue('heading1.line_rule','auto')).toBe('倍数行距')
 expect(readableRuleValue('heading1.line_spacing','360','auto')).toBe('1.5 倍')
 expect(readableRuleValue('heading1.line_spacing','360')).toBe('固定 18 磅')
 expect(readableRuleValue('body.unknown_rule',7)).toBe('7')
 expect(readableRuleValue('abstract.word_count','300-500字')).toBe('300-500字')
 expect(ruleLabel('body.font_latin')).toBe('正文英文字体')
 expect(ruleLabel('table_caption.font_size_pt')).toBe('表标题字号')
 expect(ruleLabel('body.unknown_rule')).toBe('其他格式规则')
 setLocale('en')
 expect(readableRuleValue('body.font_size_pt',12)).toBe('Small four (12 pt)')
 expect(conflictPrompt({id:'c1',rule_id:'body.font_size_pt',options:[{id:'openxml',value:12,source:template},{id:'text-2',value:10.5,source:file}]})).toBe('The school template and the supplementary rules give different values for “Body text font size”. Choose the one to use in this thesis.')
})

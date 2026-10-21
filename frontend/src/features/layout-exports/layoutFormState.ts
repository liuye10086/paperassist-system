import {codePointLength} from './unicodeText'
import type {Anchor,Catalog,Layout} from './layoutApi'
export const paragraph=(a:Anchor)=>a.type==='paragraph'||a.type==='heading'
export function layoutFormError(layout:Layout,catalog:Catalog):string{
 if(layout.headings.length>100)return '最多设置 100 个标题级别。'
 const paragraphs=new Set(catalog.anchors.filter(paragraph).map(a=>a.id)),headings=catalog.anchors.filter(a=>a.heading_level!==null||layout.headings.some(h=>h.anchor_id===a.id))
 if(layout.toc&&!headings.some(a=>(layout.headings.find(h=>h.anchor_id===a.id)?.level??a.heading_level??9)<=layout.toc!.depth))return '目录需要深度范围内的标题，请先设置标题级别。'
 if(layout.pagination?.mode==='roman_front'&&!headings.some(a=>a.id===layout.pagination?.body_anchor_id))return '请选择正文起始标题。'
 if(layout.formulas.some(f=>!/^[A-Za-z][A-Za-z0-9_]{0,31}$/.test(f.id)||!f.expression.trim()||codePointLength(f.expression)>2000||!paragraphs.has(f.anchor_id))||new Set(layout.formulas.map(f=>f.id)).size!==layout.formulas.length)return '请填写有效且唯一的公式标识、表达式和位置。'
 const targets=new Set([...catalog.anchors.filter(a=>['heading','figure','table'].includes(a.type)).map(a=>a.id),...layout.headings.map(h=>h.anchor_id),...layout.formulas.filter(f=>f.placement==='after').map(f=>`formula:${f.id}`)])
 if(layout.references.some(r=>codePointLength(r.prefix)>100||!paragraphs.has(r.anchor_id)||!targets.has(r.target_id)||r.kind==='number'&&!r.target_id.startsWith('formula:')))return '请核对引用位置和目标；编号引用仅用于独立公式。'
 return ''
}

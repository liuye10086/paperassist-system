export const articleStructures={
 research:['title','abstract','introduction','results','discussion','materials_and_methods','references'],
 brief:['title','abstract','introduction','materials_and_methods','results','discussion','references'],
 narrative_review:['title','abstract','introduction','literature_scope','themes','discussion','conclusion','references'],
 methods:['title','abstract','introduction','materials_and_methods','validation','discussion','conclusion','references'],
} as const
export type ArticleType=keyof typeof articleStructures
export const maxSciSections = 300
export const headingLevels = [1, 2, 3, 4, 5, 6, 7, 8, 9]
export const isCustomSciSection = (id: string) => /^sci-section-[a-f0-9]{32}$/.test(id)
export type SciSection = {id:string;en:string;zh:string;level?:number}
export type SciTemplate={id:string;name:string;article_type:'research'|'narrative_review';source_url:string|null;
 sections:SciSection[]}

export function validSciTemplate(value:unknown):value is SciTemplate {
 if(!value||typeof value!=='object')return false
 const template=value as Partial<SciTemplate>
 const kind=template.article_type
 if(kind!=='research'&&kind!=='narrative_review')return false
 const sections=template.sections
 if(typeof template.id!=='string'||!template.id||typeof template.name!=='string'||!template.name||
  (template.source_url!==null&&(typeof template.source_url!=='string'||!template.source_url.startsWith('https://')))||
  !Array.isArray(sections))return false
 const expected = new Set<string>(articleStructures[kind])
 const ids = new Set(sections.map(section => section?.id))
 return sections.length <= maxSciSections && ids.size === sections.length &&
  sections[0]?.id === 'title' && sections.at(-1)?.id === 'references' &&
  [...expected].every(id => ids.has(id)) && sections.every(section =>
    section && typeof section.id === 'string' && (expected.has(section.id) || isCustomSciSection(section.id)) &&
    typeof section.en === 'string' && !!section.en.trim() && typeof section.zh === 'string' && !!section.zh.trim() &&
    (section.level === undefined || headingLevels.includes(section.level)))
}

export function narrativeSectionOrder(themeIds:readonly string[],order:readonly string[]=articleStructures.narrative_review){
 return order.flatMap(id=>id==='themes'?[id,...themeIds]:[id])
}

export function templateSectionHeading(template:SciTemplate|undefined,id:string,language:'en'|'zh-CN'){
 const section=template?.sections.find(section=>section.id===id)
 return section?.[language==='en'?'en':'zh']
}
const headings:Record<string,[string,string]>={title:['Title','标题'],abstract:['Abstract','摘要'],introduction:['Introduction','引言'],results:['Results','结果'],discussion:['Discussion','讨论'],materials_and_methods:['Materials and methods','材料与方法'],references:['References','参考文献'],conclusion:['Conclusion','结论'],literature_scope:['Literature sources and inclusion scope','文献来源与纳入说明'],themes:['Thematic synthesis','主题综合'],validation:['Actual validation','实际验证']}
const overrides:Partial<Record<ArticleType,Record<string,[string,string]>>>= {brief:{abstract:['Short abstract','短摘要'],introduction:['Brief background','简要背景']},narrative_review:{introduction:['Scope and background','范围与背景'],discussion:['Synthesis and limitations','综合讨论与局限']},methods:{introduction:['Problem and existing methods','问题与现有方法'],materials_and_methods:['Method and procedure','方法与步骤'],discussion:['Applicability and limitations','适用范围与限制']}}
export function articleHeading(type:ArticleType,id:string,language:'en'|'zh-CN'){return (overrides[type]?.[id]??headings[id])?.[language==='en'?0:1]??id}

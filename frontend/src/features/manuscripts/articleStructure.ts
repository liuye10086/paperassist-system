export const articleStructures={
 research:['title','abstract','introduction','results','discussion','materials_and_methods','references'],
 brief:['title','abstract','introduction','materials_and_methods','results','discussion','references'],
 narrative_review:['title','abstract','introduction','literature_scope','themes','discussion','conclusion','references'],
 methods:['title','abstract','introduction','materials_and_methods','validation','discussion','conclusion','references'],
} as const
export type ArticleType=keyof typeof articleStructures
const headings:Record<string,[string,string]>={title:['Title','标题'],abstract:['Abstract','摘要'],introduction:['Introduction','引言'],results:['Results','结果'],discussion:['Discussion','讨论'],materials_and_methods:['Materials and methods','材料与方法'],references:['References','参考文献'],conclusion:['Conclusion','结论'],literature_scope:['Literature sources and inclusion scope','文献来源与纳入说明'],themes:['Thematic synthesis','主题综合'],validation:['Actual validation','实际验证']}
const overrides:Partial<Record<ArticleType,Record<string,[string,string]>>>= {brief:{abstract:['Short abstract','短摘要'],introduction:['Brief background','简要背景']},narrative_review:{introduction:['Scope and background','范围与背景'],discussion:['Synthesis and limitations','综合讨论与局限']},methods:{introduction:['Problem and existing methods','问题与现有方法'],materials_and_methods:['Method and procedure','方法与步骤'],discussion:['Applicability and limitations','适用范围与限制']}}
export function articleHeading(type:ArticleType,id:string,language:'en'|'zh-CN'){return (overrides[type]?.[id]??headings[id])?.[language==='en'?0:1]??id}

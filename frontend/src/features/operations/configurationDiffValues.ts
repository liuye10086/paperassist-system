import {categoryNames,type ReviewCategory} from './configurationTypes'
type Translate=(key:string)=>string
const sourceNames:Record<string,string>={installed_code:'已安装代码',deployment_policy:'部署政策',synthetic_fixture:'合成验收样例'}
const roleNames:Record<string,string>={heading1:'一级标题',heading2:'二级标题',heading3:'三级标题',body:'正文'}
/** Enumerations are translated only at their installed field paths. Free text is never translated. */
export function configurationDiffValue(path:string,value:unknown,t:Translate):string {
 if(value===null)return t('未配置')
 if(typeof value==='boolean')return t(value?'参数开启':'参数关闭')
 let names:Record<string,string>|undefined
 if(/^models\.(explanation|recommendation|plot|writing|literature)\.price_source$/.test(path))names=sourceNames
 else if(/^models\.(explanation|recommendation|plot|writing|literature)\.price_status$/.test(path))names={unverified:'来源尚未核实',synthetic:'合成价格'}
 else if(path==='journals.update_result')names={not_started:'未开始',recorded:'已记录',failed:'更新失败'}
 else if(path==='journals.source_mode')names={local_only:'仅本地资料'}
 else if(path==='journals.update_mode')names={manual:'人工更新'}
 else if(path==='review.default_language')names={'zh-CN':'简体中文',en:'英语'}
 else if(path==='review.category_order'&&Array.isArray(value))return value.map(item=>typeof item==='string'&&Object.hasOwn(categoryNames,item)?t(categoryNames[item as ReviewCategory]):String(item)).join(' → ')
 else if(path==='schools.conflict_policy')names={require_confirmation:'必须人工确认冲突'}
 else if(path==='schools.heading_aliases'&&Array.isArray(value))return value.map(alias=>typeof alias==='object'&&alias!==null&&'text' in alias&&'role' in alias?String(alias.text)+' · '+(typeof alias.role==='string'&&Object.hasOwn(roleNames,alias.role)?t(roleNames[alias.role]):t('未知')):t('未知')).join('\n')
 else if(/^schools\.heading_aliases\.\d+\.role$/.test(path))names=roleNames
 if(typeof value==='string')return names&&Object.hasOwn(names,value)?t(names[value]):value
 return JSON.stringify(value)
}

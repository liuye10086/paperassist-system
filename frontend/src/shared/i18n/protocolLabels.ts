import {translate} from './index'
import {statusNames} from '../../features/tasks/taskTypes'

// These display maps do not change the protocol values held by inputs or requests.
export const writingModes={full_draft:'完整七部分初稿',rewrite_section:'指定章节重写'}
export const authorizationStates={active:'有效',closed:'已关闭',revoked:'已撤销'}
export const callStates={reserved:'已预留',submitting:'提交中',submitted:'已提交',submission_unknown:'提交结果未知',completed:'已完成',failed:'失败',released:'已释放'}
export const sourceKinds={original:'原始文件',document_version:'文档版本',ocr_review_version:'文字核对版本',external_evidence_version:'外部证据版本',analysis_run:'统计分析结果',figure:'图表',figure_language_version:'图语言版本'}
export const inventoryKinds={image:'图像',figure_text:'图中文字',export_text:'导出文字'}
export const inventoryScopes={label:'标签',narrative:'叙述文字',reference_metadata:'参考文献元数据'}
export const exceptionKinds={proper_name:'专名',unit:'单位',reference_metadata:'真实参考文献元数据'}
export const sheetStates={visible:'可见',hidden:'隐藏',veryHidden:'深度隐藏'}
export const severities={error:'错误',warning:'警告',human_review:'需人工核对',info:'信息'}
export const quotaScopes={user:'用户',project:'项目'}
export const unexecutedStates={pending:'待处理',waiting_material:'待补充资料',waiting_confirmation:'待用户确认',not_adopted:'未采用',completed:'已完成',executing:'执行中'}
export const guideSourceTypes={official_local:'官方本地材料',open_local:'开放本地材料',user_provided:'用户提供',synthetic:'合成材料'}
export const guideSourceStates={available:'可用',unavailable:'不可用',expired:'过期'}
export const permissionStates={allowed:'来源明确允许',unknown:'未知，待核实',disallowed:'不允许'}
export const requirementStates={known:'原文明示',unknown:'未知',unsupported:'暂不支持'}
export const requirementOrigins={journal:'期刊',unit:'单位要求'}
export const verificationLevels={synthetic_material_only:'仅合成材料',user_material_only:'仅用户提供',web_fetch_unverified:'已获取，官方身份未核实',unverified:'未核实',verified:'已核实',pending_verification:'待核实'}
export function protocolLabel(labels:Readonly<Record<string,string>>,value:unknown,fallback='未知状态'):string{
 return translate(typeof value==='string'&&Object.hasOwn(labels,value)?labels[value]:fallback)
}
export function taskStatusLabel(value:unknown){return protocolLabel(statusNames,value)}

/** origin is user-supplied text; only the two system defaults have local labels. */
export function requirementOriginLabel(value:string):string{
 return Object.hasOwn(requirementOrigins,value)?protocolLabel(requirementOrigins,value):value
}

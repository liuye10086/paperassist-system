import { message } from '../../shared/i18n'
import type { AnalysisSelection } from '../analysis/analysisSelection'
export function researchOutputDefault(selection?:AnalysisSelection) {
 if(selection?.task_type==='regression')return '回归效应、诊断与森林图'
 if(selection?.task_type==='roc')return '冻结评分 ROC 曲线与 AUC'
 if(selection?.task_type==='survival')return '右删失 Kaplan–Meier 曲线与风险人数'
 if(selection?.task_type==='group_comparison')return '比较统计、分组分布与固定主图'
 if(selection?.task_type!=='correlation')return '总体及分组描述统计'
 return message(selection.mode==='pair'?'{method} 单对相关与散点图':'{method} 探索相关矩阵与热力图（共同完整记录，仅系数）',{method:selection.method==='pearson'?'Pearson':'Spearman'})
}

import { useI18n } from '../../shared/i18n'
import type { QualityRecipe, QualitySummary as Summary } from './qualityApi'
import { columnLetter } from './preparationApi'

export const independentPlanMessage = '质量确认不替代分析计划确认。新版本须重新检查字段、类型、单位、有效记录和研究设计，并独立确认分析计划。'
export function QualityPolicyView({ recipe }: { recipe: QualityRecipe }) {
 const { t } = useI18n()
 return <div><h5>{t('已选择的质量策略')}</h5><p>{t('缺失值：不填补；分析仅按所选变量的完整记录或完整对规则处理。')}</p><p>{t('异常值：IQR 仅提示候选；默认保留，仅排除你明确选定且填写理由的源行。')}</p><p>{t(recipe.duplicate_policy === 'exact' ? '重复值：全部字段类型敏感整行精确去重，保留本轮手选排除后仍有效的最小源行。' : '重复值：保留全部记录。')}</p>
 <table><caption>{t('本轮字段处理')}</caption><thead><tr><th>{t('列')}</th><th>{t('去除首尾空白')}</th><th>{t('缺失标记')}</th></tr></thead><tbody>{recipe.fields.map(field => <tr key={field.column}><th>{columnLetter(field.column)}</th><td>{t(field.trim_text ? '开启' : '关闭')}</td><td>{field.missing_markers.length ? <pre>{JSON.stringify(field.missing_markers)}</pre> : t('关闭')}</td></tr>)}</tbody></table>
 {recipe.manual_exclusions.length > 0 && <ul>{recipe.manual_exclusions.map(item => <li key={item.row}>{t('源行 {row}（用户声明）', { row: item.row })}：{item.reason}</li>)}</ul>}</div>
}
const metrics = { record_count: '记录数', missing_cell_count: '缺失单元格数', missing_row_count: '含缺失的行数', blank_row_count: '全空行数', duplicate_group_count: '重复组数', duplicate_member_count: '重复组成员数', duplicate_extra_row_count: '重复额外行数', outlier_candidate_count: '异常候选数' } as const
export default function QualitySummary({ summary: s, baseVersion }: { summary: Summary; baseVersion?: number }) {
 const { t } = useI18n()
 return <div className="quality-summary"><p>{baseVersion===undefined?t('直接父版本处理前保留 {count} 行；精确版本见来源回执。',{count:s.base_record_count}):t('直接父版本：整理数据 v{version}；处理前保留 {count} 行。', { version: baseVersion, count: s.base_record_count })}</p><p>{t('原始区域 {root} 行 − 累计整理排除 {excluded} 行 = 当前整理保留 {retained} 行。', { root: s.root_record_count, excluded: s.cumulative_excluded_row_count, retained: s.retained_record_count })}</p>
 <p>{t('累计排除：继承 {inherited} 行、本轮手选 {manual} 行、本轮重复 {duplicate} 行；按执行顺序互斥计数。', { inherited: s.inherited_excluded_row_count, manual: s.manual_excluded_row_count, duplicate: s.duplicate_excluded_row_count })}</p>
 <p>{t('变化 {cells} 个单元格（最终保留行 {retained} 格、最终排除行 {excluded} 格）；完整回执 {impacts} 项。', { cells: s.changed_cell_count, retained: s.retained_changed_cell_count, excluded: s.excluded_changed_cell_count, impacts: s.impact_count })}</p>
 <div className="structure-table-scroll"><table><caption>{t('处理前后质量概况')}</caption><thead><tr><th>{t('指标')}</th><th>{t('直接父版本')}</th><th>{t('当前整理版本')}</th></tr></thead><tbody>{Object.entries(metrics).map(([key, label]) => <tr key={key}><th>{t(label)}</th><td>{s.before_quality[key as keyof typeof metrics]}</td><td>{s.after_quality[key as keyof typeof metrics]}</td></tr>)}</tbody></table></div>
 <p className="muted">{t('候选命中不等于实际排除。同一单元格先修剪再标记缺失只计一格；各分析仍按自己的变量与完整记录规则计算有效记录数。')}</p>
 {s.retained_record_count === 0 && <p role="alert" className="warning-panel">{t('当前整理保留记录为 0，无法发布。请修改规则后重新预览。')}</p>}</div>
}

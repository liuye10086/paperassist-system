import { useI18n } from '../../shared/i18n'
import { columnLetter, type PreparationRecipe, type PreparationField } from './preparationApi'
export default function PreparationEditor({ recipe, onChange, disabled = false }: { recipe: PreparationRecipe; onChange: (recipe: PreparationRecipe) => void; disabled?: boolean }) {
 const { t } = useI18n()
 function field(index: number, change: Partial<PreparationField>) { onChange({ ...recipe, fields: recipe.fields.map((f, i) => i === index ? { ...f, ...change } : f) }) }
 return <fieldset className="preparation-editor" disabled={disabled}><legend>{t('整理规则')}</legend>
 <p className="muted">{t('字段名称与单位由你确认。清理默认关闭；去除首尾空白后，精确匹配缺失标记。')}</p>
 {recipe.fields.map((f, i) => { const letter = columnLetter(f.column); return <div className="preparation-field" key={f.column}>
  <strong>{letter}</strong><label>{t('字段名称 {column}', { column: letter })}<input value={f.name} maxLength={160} onChange={e => field(i, { name: e.target.value })} /></label>
  <label>{t('单位 {column}', { column: letter })}<input value={f.unit.value ?? ''} maxLength={80} onChange={e => field(i, { unit: { ...f.unit, value: f.unit.status === 'confirmed' ? e.target.value : null } })} disabled={f.unit.status !== 'confirmed'} /></label>
  <label><input type="checkbox" checked={f.unit.status === 'confirmed'} onChange={e => field(i, { unit: { status: e.target.checked ? 'confirmed' : 'unconfirmed', value: e.target.checked ? '' : null } })} />{t('确认单位 {column}', { column: letter })}</label>
  <label><input type="checkbox" checked={f.trim_text} onChange={e => field(i, { trim_text: e.target.checked })} />{t('去除首尾空白 {column}', { column: letter })}</label>
  <div><label><input type="checkbox" checked={f.missing_markers.length > 0} onChange={e => field(i, { missing_markers: e.target.checked ? [''] : [] })} />{t('启用缺失标记 {column}', { column: letter })}</label>
  {f.missing_markers.length > 0 && <label>{t('缺失标记 {column}（每行一个）', { column: letter })}<textarea value={f.missing_markers.join('\n')} onChange={e => field(i, { missing_markers: e.target.value.split('\n') })} /></label>}</div>
 </div> })}</fieldset>
}

import { useEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { isDatasetSource, sameSource, type RawDatasetAnalysisSource } from '../analysis/datasetSource'
import SourceSummary from '../analysis/SourceSummary'
import { isTask, sameInputVersion, statusNames, type TaskView } from '../tasks/taskTypes'
import { TaskRequestError } from '../tasks/taskApi'
import { useDocumentVisible } from '../tasks/useDocumentVisible'
import PreparationEditor from './PreparationEditor'
import { columnLetter, fileBase, isRecipe, isReview, preparationRequest, type Review, type PreparationRecipe, type PreparationSummary } from './preparationApi'
import './preparation.css'
import { isQualityReview, type QualityReview } from './qualityApi'
import {isFilterReview,type FilterReview} from './populationFilterApi'
import {PopulationFilterReview} from './PopulationFilter'
import QualityPreparationReview from './QualityPreparationReview'
type Props = { projectId: string; taskId: string; blocked?: boolean; onChanged?: () => void; refreshKey?: number }
export default function PreparationReview(props: Props) { return <Panel key={`${props.projectId}:${props.taskId}`} {...props} /> }
function Panel({ projectId, taskId, blocked = false, onChanged, refreshKey = 0 }: Props) {
 const { t } = useI18n(); const visible = useDocumentVisible()
 const [review, setReview] = useState<Review | QualityReview | FilterReview | null>(null); const [draft, setDraft] = useState<PreparationRecipe | null>(null)
 const [editing, setEditing] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [refresh, setRefresh] = useState(0)
 const action = useRef<AbortController | null>(null); const mounted = useRef(true); const replay = useRef<{ signature: string; key: string } | null>(null)
 useEffect(() => { mounted.current = true; return () => { mounted.current = false; action.current?.abort() } }, [])
 useEffect(() => {
  if (!visible) return
  const controller = new AbortController(); let active = true; let timer = 0
  async function load() { try {
   const value = await preparationRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/dataset-preparation`, controller, (v): v is Review | QualityReview | FilterReview => isReview(v, projectId, taskId) || isQualityReview(v, projectId, taskId) || isFilterReview(v,projectId,taskId), '整理任务读取失败，请重试。')
   if (!active || controller.signal.aborted) return
   setReview(value)
   if (['queued', 'running'].includes(value.task.status)) timer = window.setTimeout(() => void load(), 5000)
  } catch (cause) { if (active) setError(safeError(cause, '整理任务读取失败，请重试。')) } }
  void load(); return () => { active = false; controller.abort(); window.clearTimeout(timer) }
 }, [projectId, taskId, refresh, refreshKey, visible])
 async function readFields() {
  if (!review || isQualityReview(review) || isFilterReview(review,projectId,taskId) || !draft || action.current) return
  const controller = new AbortController(); action.current = controller; setBusy(true); setError('')
  const params = new URLSearchParams({ header_row: String(draft.header_row), data_range: draft.data_range })
  try {
   const value = await preparationRequest(`${fileBase(projectId, review.source.file_id)}/dataset-versions/${encodeURIComponent(review.source.dataset_id)}/preparation-defaults?${params}`, controller, (v): v is { source: RawDatasetAnalysisSource; recipe: PreparationRecipe } => !!v && typeof v === 'object' && 'source' in v && isDatasetSource(v.source) && sameSource(v.source, review.source) && 'recipe' in v && isRecipe(v.recipe), '整理字段读取失败，请重试。')
   if (mounted.current && !controller.signal.aborted) setDraft(value.recipe)
  } catch (cause) { if (mounted.current) setError(safeError(cause, '整理字段读取失败，请重试。')) }
  finally { if (action.current === controller) action.current = null; if (mounted.current) setBusy(false) }
 }
 async function decide(operation: 'approve' | 'revise') {
  if (!review || isQualityReview(review) || isFilterReview(review,projectId,taskId) || action.current || blocked || review.wait?.status !== 'open') return
  const body = { operation, wait_id: review.wait.id, checkpoint_id: review.checkpoint_id, expected_task_revision: review.task.revision, input_version: review.task.input_version, recipe: operation === 'revise' ? draft : null }
  const signature = JSON.stringify(body); if (replay.current?.signature !== signature) replay.current = { signature, key: crypto.randomUUID() }
  const controller = new AbortController(); action.current = controller; setBusy(true); setError('')
  try {
   const result = await preparationRequest(`/api/v1/tasks/${encodeURIComponent(taskId)}/dataset-preparation/decision`, controller, (v): v is TaskView => isTask(v, projectId, taskId) && sameInputVersion(v.input_version, review.task.input_version), '整理决定尚未确认，请重新读取任务。', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': replay.current.key }, body: signature })
   if (!mounted.current || controller.signal.aborted) return
   setReview({ ...review, task: result, wait: null }); setEditing(false); setDraft(null); replay.current = null; setRefresh(n => n + 1); onChanged?.()
  } catch (cause) { if (mounted.current) { if (cause instanceof TaskRequestError && cause.status === 409) { replay.current = null; setEditing(false) } setError(cause instanceof TaskRequestError && cause.status === 409 ? '任务状态已更新，请核对重新读取的内容后再操作。' : safeError(cause, '整理决定尚未确认，请重新读取任务。')); setRefresh(n => n + 1); onChanged?.() } }
  finally { if (action.current === controller) action.current = null; if (mounted.current) setBusy(false) }
 }
 if (review && isFilterReview(review,projectId,taskId)) return <PopulationFilterReview key={`${review.checkpoint_id}:${review.task.revision}`} projectId={projectId} review={review} blocked={blocked||!!error} onReload={()=>{setError('');setReview(null);setRefresh(n=>n+1);onChanged?.()}}/>
 if (review && isQualityReview(review)) return <QualityPreparationReview key={`${review.checkpoint_id}:${review.task.revision}`} projectId={projectId} review={review} blocked={blocked || !!error} onReload={() => { setError(''); setReview(null); setRefresh(n => n + 1); onChanged?.() }} />
 return <section className="preparation-panel" aria-label={t('整理预览与确认')} aria-busy={busy}>
 <h4>{t('整理预览与确认')}</h4><button disabled={busy} onClick={() => { setError(''); setRefresh(n => n + 1) }}>{t('重新读取整理任务')}</button>
 {error && <p role="alert" className="error-panel">{t(error)}</p>}
 {!review && !error && <p role="status">{t('正在读取整理任务……')}</p>}
 {review && <><SourceSummary source={review.source} /><p role="status">{t(statusNames[review.task.status])}</p><p>{t('表头行 {row}；数据区域 {range}', { row: review.recipe.header_row, range: review.recipe.data_range })}</p>
 <PreparationRulesView recipe={review.recipe} />
 {review.preview && <PreparationSummaryView summary={review.preview} />}
 {review.changes.length > 0 && <table><caption>{t('前 20 项单元格变化（完整数据见 JSON）')}</caption><thead><tr><th>{t('原始位置')}</th><th>{t('整理前')}</th><th>{t('整理后')}</th></tr></thead><tbody>{review.changes.map(c => <tr key={c.coordinate}><th>{c.coordinate}</th><td><pre>{JSON.stringify(c.before.value)}</pre></td><td><pre>{JSON.stringify(c.after.value)}</pre></td></tr>)}</tbody></table>}
 {review.preview_download_url && <ProjectDownloadLink href={review.preview_download_url} filename="preparation-preview.json">{t('下载完整预览 JSON')}</ProjectDownloadLink>}
 {review.task.status === 'waiting_confirmation' && review.wait?.status === 'open' && review.preview && <>
  {editing && draft && <><RangeEditor recipe={draft} onChange={setDraft} disabled={busy || blocked} /><button disabled={busy || blocked} onClick={() => void readFields()}>{t('读取建议字段')}</button><PreparationEditor recipe={draft} onChange={setDraft} disabled={busy || blocked} /></>}
  <div className="structure-actions">{editing ? <button className="button-primary" disabled={busy || blocked || !draft?.fields.every(f => f.name.length > 0 && f.missing_markers.every(m => m.length > 0))} onClick={() => void decide('revise')}>{t('重新生成预览')}</button> : <><button className="button-primary" disabled={busy || blocked} onClick={() => void decide('approve')}>{t('确认并发布')}</button><button disabled={busy || blocked} onClick={() => { setDraft(review.recipe); setEditing(true) }}>{t('修改规则')}</button></>}</div>
  <p className="muted">{t('离开页面后任务仍等待确认，可在任务中心继续。')}</p>
 </>}
 {review.result && <p>{t('已发布：原始数据 v{raw} · 整理数据 v{prepared}', { raw: review.result.parent_dataset_version, prepared: review.result.version })}</p>}
 </>}
 </section>
}
export function RangeEditor({ recipe, onChange, disabled }: { recipe: PreparationRecipe; onChange: (recipe: PreparationRecipe) => void; disabled: boolean }) { const { t } = useI18n(); return <div className="analysis-field-grid"><label>{t('表头行')}<input type="number" min={1} max={100000} value={recipe.header_row} disabled={disabled} onChange={e => onChange({ ...recipe, header_row: Number(e.target.value) })} /></label><label>{t('数据区域')}<input value={recipe.data_range} disabled={disabled} placeholder="A2:D35" onChange={e => onChange({ ...recipe, data_range: e.target.value })} /></label></div> }
export function PreparationRulesView({ recipe }: { recipe: PreparationRecipe }) { const { t } = useI18n(); return <div className="structure-table-scroll"><table><caption>{t('当前整理规则')}</caption><thead><tr><th>{t('列')}</th><th>{t('字段名称')}</th><th>{t('单位')}</th><th>{t('去除首尾空白')}</th><th>{t('缺失标记')}</th></tr></thead><tbody>{recipe.fields.map(f => <tr key={f.column}><th>{columnLetter(f.column)}</th><td>{f.name}</td><td>{f.unit.status === 'confirmed' ? f.unit.value === '' ? t('无单位（已确认）') : f.unit.value : t('单位未确认')}</td><td>{t(f.trim_text ? '开启' : '关闭')}</td><td><pre>{f.missing_markers.length ? JSON.stringify(f.missing_markers) : t('关闭')}</pre></td></tr>)}</tbody></table></div> }
const issueLabels: Record<string, string> = { formula_unverified: '公式未核验', error_values: '错误值', mixed_types: '混合类型', unconfirmed_unit: '单位未确认', merged_cells: '合并单元格' }
export function PreparationSummaryView({ summary: s }: { summary: PreparationSummary }) { const { t } = useI18n(); return <><p>{t('记录 {records} 行；变化 {cells} 格、{rows} 行；去除空白 {trimmed} 格；缺失标记 {missing} 格。', { records: s.record_count, cells: s.changed_cell_count, rows: s.changed_row_count, trimmed: s.trimmed_cell_count, missing: s.missing_marker_cell_count })}</p>
 {s.columns.length > 0 && <table><caption>{t('整理后的字段概况')}</caption><thead><tr><th>{t('字段名称')}</th><th>{t('类型')}</th><th>{t('缺失')}</th><th>{t('非缺失')}</th></tr></thead><tbody>{s.columns.map(c => <tr key={c.column}><th>{c.name}</th><td>{c.observed_types.map(k => t(`读取类型：${k}`)).join(' / ')}</td><td>{c.missing_count}</td><td>{c.non_missing_count}</td></tr>)}</tbody></table>}
 {s.unresolved.length > 0 && <ul className="warning-panel">{s.unresolved.map((issue, i) => <li key={i}>{t(issueLabels[issue.code] ?? '需人工核对')} · {issue.column ?? t('数据区域')} · {issue.count}</li>)}</ul>}</> }

import { useEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import type { DatasetSummary } from '../datasets/datasetApi'
import { isDatasetSource, type RawDatasetAnalysisSource } from '../analysis/datasetSource'
import { isTask, type TaskView } from '../tasks/taskTypes'
import PreparationEditor from './PreparationEditor'
import PreparationReview from './PreparationReview'
import { fileBase, isRecipe, preparationRequest, type PreparationRecipe } from './preparationApi'
import './preparation.css'
type Props = { projectId: string; fileId: string; dataset: DatasetSummary; initialRecipe?: PreparationRecipe; onCreated?: () => void }
export default function PreparationPanel(props: Props) { return <Panel key={`${props.projectId}:${props.fileId}:${props.dataset.id}`} {...props} /> }
function Panel({ projectId, fileId, dataset, initialRecipe, onCreated }: Props) {
 const { t } = useI18n(); const base = fileBase(projectId, fileId)
 const [header, setHeader] = useState(initialRecipe?.header_row ?? 1); const [range, setRange] = useState(initialRecipe?.data_range ?? '')
 const [recipe, setRecipe] = useState<PreparationRecipe | null>(initialRecipe ?? null); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [taskId, setTaskId] = useState('')
 const request = useRef<AbortController | null>(null); const active = useRef(true); const replay = useRef<{ signature: string; key: string } | null>(null)
 useEffect(() => { active.current = true; return () => { active.current = false; request.current?.abort() } }, [])
 async function perform(create: boolean) {
  if (request.current || create && !recipe) return
  const controller = new AbortController(); request.current = controller; setBusy(true); setError('')
  try {
   if (create && recipe) {
    const signature = JSON.stringify({ dataset_id: dataset.id, recipe }); if (replay.current?.signature !== signature) replay.current = { signature, key: crypto.randomUUID() }
    const result = await preparationRequest(`${base}/dataset-preparations`, controller, (v): v is TaskView => isTask(v, projectId) && v.task_type === 'prepare_dataset' && v.input_version.kind === 'dataset_preparation' && v.input_version.source.dataset_id === dataset.id && v.input_version.source.file_id === fileId, '整理请求尚未确认，请使用同一请求重试。', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': replay.current.key }, body: signature })
    if (active.current && !controller.signal.aborted) { setTaskId(result.id); onCreated?.() }
   } else {
    const params = new URLSearchParams({ header_row: String(header) }); if (range) params.set('data_range', range)
    const result = await preparationRequest(`${base}/dataset-versions/${encodeURIComponent(dataset.id)}/preparation-defaults?${params}`, controller, (v): v is { source: RawDatasetAnalysisSource; recipe: PreparationRecipe } => !!v && typeof v === 'object' && 'source' in v && isDatasetSource(v.source) && v.source.kind === 'dataset_version' && v.source.dataset_id === dataset.id && v.source.file_id === fileId && 'recipe' in v && isRecipe(v.recipe), '整理字段读取失败，请重试。')
    if (active.current && !controller.signal.aborted) { setRecipe(result.recipe); setRange(result.recipe.data_range); setHeader(result.recipe.header_row) }
   }
  } catch (cause) { if (active.current) setError(safeError(cause, create ? '整理请求尚未确认，请使用同一请求重试。' : '整理字段读取失败，请重试。')) }
  finally { if (request.current === controller) request.current = null; if (active.current) setBusy(false) }
 }
 if (taskId) return <PreparationReview projectId={projectId} taskId={taskId} />
 return <section className="preparation-panel" aria-label={t('整理数据')} aria-busy={busy}><h4>{t('整理数据')}</h4><p>{dataset.sheet_name} · {t('原始数据版本 v{version}', { version: dataset.version })}</p>
 <div className="analysis-field-grid"><label>{t('表头行')}<input type="number" min={1} max={100000} value={header} disabled={busy} onChange={e => { setHeader(Number(e.target.value)); setRecipe(null) }} /></label><label>{t('数据区域')}<input value={range} placeholder="A2:D35" disabled={busy} onChange={e => { setRange(e.target.value); setRecipe(null) }} /></label></div>
 <button disabled={busy} onClick={() => void perform(false)}>{t('读取建议字段')}</button>
 {recipe && <><PreparationEditor recipe={recipe} onChange={setRecipe} disabled={busy} /><button className="button-primary" disabled={busy || !recipe.fields.length || recipe.fields.some(f => !f.name || f.missing_markers.some(m => !m))} onClick={() => void perform(true)}>{t('生成预览')}</button></>}
 {busy && <p role="status">{t('正在提交整理请求……')}</p>}{error && <p role="alert" className="error-panel">{t(error)}</p>}
 </section>
}

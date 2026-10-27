import useDraftLeaveGuard, {type RegisterLeaveGuard} from '../projects/useDraftLeaveGuard'
import { useEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import SourceSummary from '../analysis/SourceSummary'
import { sameSource, type PreparedDatasetAnalysisSource } from '../analysis/datasetSource'
import { isTask, type TaskView } from '../tasks/taskTypes'
import { fileBase, preparationRequest } from './preparationApi'
import { isQualityCounts, isQualityRecipe, isQualitySheet, qualityObject, type QualityCounts, type QualityRecipe, type QualitySheet } from './qualityApi'
import QualityEditor from './QualityEditor'
import PreparationReview from './PreparationReview'

type Defaults = { source: PreparedDatasetAnalysisSource; recipe: QualityRecipe; summary: QualityCounts; sheet: QualitySheet }
export default function QualityPreparationPanel(props: { projectId: string; source: PreparedDatasetAnalysisSource; onCreated?: () => void; viewActive?: boolean; registerLeaveGuard?: RegisterLeaveGuard }) { return <Panel key={JSON.stringify(props.source)} {...props} /> }
function Panel({ projectId, source, onCreated, viewActive = true, registerLeaveGuard }: { projectId: string; source: PreparedDatasetAnalysisSource; onCreated?: () => void; viewActive?: boolean; registerLeaveGuard?: RegisterLeaveGuard }) {
 const { t } = useI18n(); const [defaults, setDefaults] = useState<Defaults | null>(null); const [recipe, setRecipe] = useState<QualityRecipe | null>(null); const [taskId, setTaskId] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [retry, setRetry] = useState(0); const action = useRef<AbortController | null>(null); const replay = useRef<{ signature: string; key: string } | null>(null)
 useDraftLeaveGuard(registerLeaveGuard, !taskId && Boolean(defaults) && JSON.stringify(recipe) !== JSON.stringify(defaults?.recipe), busy)
 const base = fileBase(projectId, source.file_id)
 useEffect(() => () => action.current?.abort(), [])
 useEffect(() => { const controller = new AbortController(); let active = true
  preparationRequest(`${base}/prepared-dataset-versions/${encodeURIComponent(source.dataset_id)}/quality-defaults`, controller, (v): v is Defaults => qualityObject(v) && sameSource(v.source as PreparedDatasetAnalysisSource, source) && isQualityRecipe(v.recipe) && isQualityCounts(v.summary) && isQualitySheet(v.sheet), '质量策略读取失败，请重试。').then(v => { if (active) { setDefaults(v); setRecipe(v.recipe); setError('') } }).catch(cause => { if (active) setError(safeError(cause, '质量策略读取失败，请重试。')) }); return () => { active = false; controller.abort() }
 }, [base, source, retry])
 async function create() {
  if (!recipe || !isQualityRecipe(recipe) || action.current) return
  const signature = JSON.stringify({ base_dataset_id: source.dataset_id, recipe }); if (replay.current?.signature !== signature) replay.current = { signature, key: crypto.randomUUID() }
  const controller = new AbortController(); action.current = controller; setBusy(true); setError('')
  try { const result = await preparationRequest(`${base}/dataset-quality-preparations`, controller, (v): v is TaskView => isTask(v, projectId) && v.task_type === 'prepare_dataset' && v.input_version.kind === 'dataset_preparation' && v.input_version.workflow_version === (source.schema_version===3?'dataset_preparation_v3':'dataset_preparation_v2') && sameSource(v.input_version.source, source), '整理请求尚未确认，请使用同一请求重试。', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': replay.current.key }, body: signature }); if (!controller.signal.aborted) { setTaskId(result.id); onCreated?.() } }
  catch (cause) { if (!controller.signal.aborted) setError(safeError(cause, '整理请求尚未确认，请使用同一请求重试。')) }
  finally { if (action.current === controller) action.current = null; if (!controller.signal.aborted) setBusy(false) }
 }
 if (taskId) return <PreparationReview projectId={projectId} taskId={taskId} onRestart={() => { setTaskId(''); replay.current = null }} active={viewActive} registerLeaveGuard={registerLeaveGuard} />
 return <section className="preparation-panel" aria-label={t('处理质量问题')} aria-busy={busy}><h4>{t('处理质量问题')}</h4><SourceSummary source={source} />{error && <p role="alert">{t(error)} {!defaults && <button type="button" onClick={() => setRetry(n => n + 1)}>{t('重试')}</button>}</p>}{defaults && recipe && <><p>{t('父版本当前保留 {count} 行。', { count: defaults.summary.record_count })}</p><QualityEditor projectId={projectId} source={source} recipe={recipe} onChange={setRecipe} initialSheet={defaults.sheet} disabled={busy} /><button className="button-primary" disabled={busy || !isQualityRecipe(recipe)} onClick={() => void create()}>{t('生成质量预览')}</button></>}</section>
}

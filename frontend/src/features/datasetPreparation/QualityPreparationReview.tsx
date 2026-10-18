import { useEffect, useRef, useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import { onApiSessionChanged } from '../../shared/api/client'
import SourceSummary from '../analysis/SourceSummary'
import { isTask, sameInputVersion, statusNames, type TaskView } from '../tasks/taskTypes'
import { TaskRequestError } from '../tasks/taskApi'
import { preparationRequest } from './preparationApi'
import { isQualityRecipe, type QualityReview } from './qualityApi'
import QualityEditor from './QualityEditor'
import QualityImpacts from './QualityImpacts'
import QualitySummary, { independentPlanMessage, QualityPolicyView } from './QualitySummary'

export default function QualityPreparationReview({ projectId, review, blocked, onReload }: { projectId: string; review: QualityReview; blocked: boolean; onReload: () => void }) {
 const { t } = useI18n(); const [draft, setDraft] = useState(review.recipe); const [editing, setEditing] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [submitted, setSubmitted] = useState(false); const [sessionValid, setSessionValid] = useState(true); const action = useRef<AbortController | null>(null); const replay = useRef<{ signature: string; key: string } | null>(null)
 useEffect(() => () => action.current?.abort(), [])
 useEffect(() => onApiSessionChanged(() => { action.current?.abort(); setSessionValid(false) }), [])
 const waiting = !blocked && sessionValid && !submitted && review.task.status === 'waiting_confirmation' && review.wait?.status === 'open' && review.wait.task_revision === review.task.revision
 async function decide(operation: 'approve' | 'revise') {
  if (!waiting || action.current || !review.wait || operation === 'revise' && !isQualityRecipe(draft) || operation === 'approve' && (editing || !review.preview?.retained_record_count)) return
  const signature = JSON.stringify({ operation, wait_id: review.wait.id, checkpoint_id: review.checkpoint_id, expected_task_revision: review.task.revision, input_version: review.task.input_version, recipe: operation === 'revise' ? draft : null })
  if (replay.current?.signature !== signature) replay.current = { signature, key: crypto.randomUUID() }
  const controller = new AbortController(); action.current = controller; setBusy(true); setError('')
  try { await preparationRequest(`/api/v1/tasks/${encodeURIComponent(review.task.id)}/dataset-preparation/decision`, controller, (v): v is TaskView => isTask(v, projectId, review.task.id) && sameInputVersion(v.input_version, review.task.input_version), '整理决定尚未确认，请重新读取任务。', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': replay.current.key }, body: signature }); if (!controller.signal.aborted) { setSubmitted(true); replay.current = null; onReload() } }
  catch (cause) { if (!controller.signal.aborted) { if (cause instanceof TaskRequestError && cause.status === 409) { setSubmitted(true); replay.current = null; setError('任务状态已更新，请核对重新读取的内容后再操作。'); onReload() } else setError(safeError(cause, '整理决定尚未确认，请重新读取任务。')) } }
  finally { if (action.current === controller) action.current = null; if (!controller.signal.aborted) setBusy(false) }
 }
 return <section className="preparation-panel" aria-label={t('质量预览与确认')} aria-busy={busy}><h4>{t('质量预览与确认')}</h4><button type="button" disabled={busy || !sessionValid} onClick={onReload}>{t('重新读取整理任务')}</button>
 {!sessionValid ? <p role="alert">{t('会话已失效，请重新登录。')}</p> : <><SourceSummary source={review.source} /><p role="status">{t(statusNames[review.task.status])}</p><p>{t('锁定直接父版本 v{version}，不会自动切换最新版本。', { version: review.source.dataset_version })}</p>{error && <p role="alert" className="error-panel">{t(error)}</p>}
 {editing ? <><p className="warning-panel">{t('规则已进入编辑；原预览不可确认，重新生成完整预览后再确认。')}</p><QualityEditor projectId={projectId} source={review.source} recipe={draft} onChange={setDraft} disabled={busy || blocked || submitted} /></> : <><QualityPolicyView recipe={review.recipe} />{review.preview && <QualitySummary summary={review.preview} baseVersion={review.source.dataset_version} />}{review.impact_url && review.impact_download_url && <QualityImpacts projectId={projectId} source={review.source} url={review.impact_url} downloadUrl={review.impact_download_url} checkpointId={review.checkpoint_id} />}</>}
 {waiting && <div className="structure-actions">{editing ? <button type="button" className="button-primary" disabled={busy || !isQualityRecipe(draft)} onClick={() => void decide('revise')}>{t('重新生成预览')}</button> : <><button type="button" className="button-primary" disabled={busy || !review.preview?.retained_record_count || !review.impact_url || !review.impact_download_url} onClick={() => void decide('approve')}>{t('确认并发布')}</button><button type="button" disabled={busy} onClick={() => setEditing(true)}>{t('修改规则')}</button></>}</div>}
 {['waiting_confirmation', 'waiting_input'].includes(review.task.status) && <p className="muted">{t('离开页面后任务仍等待确认，可在任务中心继续。')}</p>}<p>{t(independentPlanMessage)}</p>{review.result && <p>{t('已发布：原始数据 v{raw} · 整理数据 v{prepared}', { raw: review.result.parent_dataset_version, prepared: review.result.version })}</p>}</>}
 </section>
}

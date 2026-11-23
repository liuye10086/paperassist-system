import { useState } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { intakeRequest } from '../research-intake/api'
import { paperMaterialsUrl, type PaperFile, type PaperMaterialNote, type PaperMaterialTarget } from './paperMaterials'

export default function SciFileNote({ projectId, file, note, figureTargets, prefill, registerLeaveGuard, onDone }: {
  projectId: string; file: PaperFile; note?: PaperMaterialNote; registerLeaveGuard: RegisterLeaveGuard
  figureTargets?: PaperMaterialTarget[]
  prefill?: string
  onDone: (saved: boolean) => void
}) {
  const { t } = useI18n()
  const [baseline] = useState(note)
  const [id] = useState(() => note?.id ?? crypto.randomUUID())
  const [value, setValue] = useState(note?.result ?? prefill ?? '')
  const [targetId, setTargetId] = useState(note?.target_available ? note.target_id : null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const dirty = value !== (baseline?.result ?? prefill ?? '') || targetId !== (baseline?.target_available ? baseline.target_id : null)
  useDraftLeaveGuard(registerLeaveGuard, dirty, busy)
  const canSave = !!figureTargets || !!value.trim()
  async function save() {
    if (busy || !canSave) return
    if (figureTargets && !baseline && !targetId && !value.trim()) { onDone(false); return }
    setBusy(true)
    setError('')
    try {
      await intakeRequest(paperMaterialsUrl(projectId) + '/' + encodeURIComponent(id), {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_id: file.id, expected_revision: baseline?.revision ?? 0,
          result: value.trim(), target_id: targetId }),
      })
      onDone(true)
    } catch (cause) {
      setError(safeError(cause, figureTargets ? '配图设置保存失败。' : '文件说明保存失败。'))
      setBusy(false)
    }
  }
  return <form className="sci-file-note" onSubmit={event => { event.preventDefault(); void save() }}>
    {figureTargets && <label>{t('入稿章节')}<select value={targetId ?? ''} disabled={busy} onChange={event => setTargetId(event.target.value || null)}>
      <option value="">{t('自动安排')}</option>
      {figureTargets.map(target => <option key={target.id} value={target.id}>{target.label}</option>)}
    </select></label>}
    <label>{t(figureTargets ? '图注与出处（选填）' : '文件说明（选填）')}<textarea rows={2} maxLength={20000} value={value} disabled={busy}
      onChange={event => setValue(event.target.value)} /></label>
    {error && <p role="alert" className="error-panel">{t(error)}</p>}
    <div className="sci-inline-controls">
      <button className="button-primary" disabled={busy || !canSave}>{t(busy ? '正在保存……' : figureTargets ? '保存配图设置' : '保存说明')}</button>
      <button type="button" disabled={busy} onClick={() => onDone(false)}>{t('取消')}</button>
    </div>
  </form>
}

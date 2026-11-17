import { useEffect, useRef, useState, type FormEvent } from 'react'
import { safeError, useI18n } from '../../shared/i18n'
import useDraftLeaveGuard, { type RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { IntakeError, intakeRequest, projectBase } from '../research-intake/api'
import { useResearchRead } from '../research-results/api'
import useResearchDraft from '../research-results/useResearchDraft'
import SciSettingsFields from './SciSettingsFields'
import { articleTypes, journalChoices, prepareSciSettings, sciSettingsDraft, type SciSettingsDraft, type SciSettingsState } from './sciProjectSettings'

type Props = { projectId: string; registerLeaveGuard: RegisterLeaveGuard }
type Edit = { revision: number; draft: SciSettingsDraft }

export default function CustomerSciSettings({ projectId, registerLeaveGuard }: Props) {
  const { t } = useI18n()
  const url = projectBase(projectId) + '/sci-settings'
  const read = useResearchRead<SciSettingsState>(url, true)
  return <section className="customer-sci-settings" aria-label={t('SCI 建项资料')}>
    <h2>{t('SCI 建项资料')}</h2>
    {read.error && <div className="error-panel" role="alert">{t(read.error)}{' '}
      <button type="button" onClick={read.refresh}>{t('重试')}</button>
    </div>}
    {read.data
      ? <SettingsEditor projectId={projectId} url={url} receipt={read.data} refresh={read.refresh} registerLeaveGuard={registerLeaveGuard} />
      : !read.error && <p role="status">{t('正在读取 SCI 建项资料……')}</p>}
  </section>
}

function SettingsEditor({ projectId, url, receipt, refresh, registerLeaveGuard }: Props & {
  url: string; receipt: SciSettingsState; refresh: () => void
}) {
  const { t } = useI18n()
  const [edit, setEdit] = useResearchDraft<Edit | null>(projectId, 'customer-sci-settings', () => null)
  const [saved, setSaved] = useState<SciSettingsState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  const current = saved && saved.revision >= receipt.revision ? saved : receipt
  const settings = current.settings
  const stale = edit !== null && edit.revision !== current.revision
  const dirty = edit !== null && JSON.stringify(edit.draft) !== JSON.stringify(sciSettingsDraft(settings))
  useDraftLeaveGuard(registerLeaveGuard, dirty, busy)

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!edit || stale || request.current) return
    const validated = prepareSciSettings(edit.draft)
    if ('error' in validated) { setError(validated.error); return }
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    setError('')
    try {
      const value = await intakeRequest<SciSettingsState>(url, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify({ expected_revision: edit.revision, settings: validated.settings }),
      })
      if (controller.signal.aborted) return
      if (!value?.settings || ![edit.revision, edit.revision + 1].includes(value.revision)) {
        throw new Error('SCI 建项资料保存结果待确认，请重试原请求。')
      }
      setSaved(value)
      setEdit(null)
    } catch (cause) {
      if (controller.signal.aborted) return
      setError(safeError(cause, 'SCI 建项资料保存失败，请重试。'))
      if (cause instanceof IntakeError && cause.status === 409) refresh()
    } finally {
      request.current = null
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  return <>
    {(!edit || stale) && (settings ? <dl className="sci-settings-summary">
      <dt>{t('论文类型')}</dt><dd>{t(articleTypes[settings.article_type])}</dd>
      <dt>{t('主要结果或结论')}</dt><dd>{settings.main_results}</dd>
      <dt>{t('目标期刊')}</dt><dd>{t(journalChoices[settings.target_journal.choice])}
        {settings.target_journal.name && ' · ' + settings.target_journal.name}</dd>
      <dt>{t('关键词')}</dt><dd>{settings.keywords.join(' · ')}</dd>
      <dt>{t('图表计划（Figure plan）')}</dt><dd><ol>{settings.figure_plan.map((item, index) =>
        <li key={index}><strong>{item.title}</strong><p>{item.description}</p></li>)}</ol></dd>
    </dl> : <p>{t('此项目尚未填写 SCI 建项资料。')}</p>)}
    {!edit ? <button type="button" onClick={() => setEdit({ revision: current.revision, draft: sciSettingsDraft(settings) })}>
      {t(settings ? '编辑 SCI 建项资料' : '补充 SCI 建项资料')}
    </button> : <form className="sci-settings-edit" noValidate aria-busy={busy} onSubmit={event => void save(event)}>
      {stale && <div className="warning-panel" role="status">{t('SCI 建项资料已更新，请核对最新版本。')}{' '}
        <button type="button" onClick={() => { setEdit({ ...edit, revision: current.revision }); setError('') }}>
          {t('保留草稿并继续编辑')}
        </button>
      </div>}
      <SciSettingsFields draft={edit.draft} disabled={busy || stale} onChange={draft => { setEdit({ ...edit, draft }); setError('') }} onError={setError} />
      {error && <p className="error-panel" role="alert">{t(error)}</p>}
      <div className="sci-inline-controls">
        <button type="submit" className="button-primary" disabled={busy || stale}>{t(busy ? '正在保存……' : '保存 SCI 建项资料')}</button>
        <button type="button" disabled={busy} onClick={() => { setEdit(null); setError('') }}>{t('取消')}</button>
      </div>
    </form>}
  </>
}

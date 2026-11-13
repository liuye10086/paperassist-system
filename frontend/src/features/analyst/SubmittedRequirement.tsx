import type { ReactNode } from 'react'
import { useI18n } from '../../shared/i18n'
import { projectBase } from '../research-intake/api'
import type { Intake, Version } from '../research-intake/contracts'
import { useResearchRead } from '../research-results/api'
import type { AnalystWorkspace, SubmittedVersion } from './useAnalystWorkspace'

function confirmedVersion(version: Version | null | undefined, projectId: string): version is Version {
  return !!version && typeof version.id === 'string' && Number.isSafeInteger(version.version) && version.operation === 'confirm'
    && !!version.content && (!version.project_id || version.project_id === projectId)
}

function matchesSubmitted(version: Version, submitted: SubmittedVersion) {
  return version.id === submitted.id && version.version === submitted.version
}

export default function SubmittedRequirement({ projectId, workspace, onDesign, headerAction }: {
  projectId: string; workspace: AnalystWorkspace; onDesign: () => void; headerAction: ReactNode
}) {
  const { t, locale } = useI18n()
  const base = projectBase(projectId)
  const submitted = workspace.value?.requirement
  const intake = useResearchRead<Intake>(`${base}/research-intake`, !!workspace.value)
  const latest = intake.data?.current_requirement
  const current = confirmedVersion(latest, projectId) && (!submitted || latest.version > submitted.version || matchesSubmitted(latest, submitted)) ? latest : null
  const needsExactVersion = !!intake.data && !!submitted && !current
  const historical = useResearchRead<Version>(submitted ? `${base}/requirements/${encodeURIComponent(submitted.id)}` : '', needsExactVersion)
  const version = current ?? (submitted && confirmedVersion(historical.data, projectId) && matchesSubmitted(historical.data, submitted) ? historical.data : null)
  const readError = workspace.error || intake.error || needsExactVersion && (historical.error || historical.data && !version && '无法核对已提交的需求版本。')
  const notes = version && typeof version.content.notes === 'string' ? version.content.notes : ''
  const scope = Array.isArray(version?.content.scope_items) ? version.content.scope_items.filter(item => item && typeof item.id === 'string'
    && typeof item.title === 'string' && item.delivery_kind === 'analysis' && item.status !== 'not_included') : []
  return <section className="project-details-card analyst-project-details" aria-label={t('已提交需求')} tabIndex={0}>
    <header className="analyst-project-details-heading">
      <h1>{t('已提交需求')}</h1>
      <div className="analyst-requirement-actions">
        <button type="button" onClick={onDesign}>{t('实验设计')}</button>
        {headerAction}
      </div>
    </header>
    {readError ? <><p role="alert">{t(readError)}</p><button type="button" onClick={() => { workspace.refresh(); intake.refresh(); historical.refresh() }}>{t('重新读取需求')}</button></>
      : !intake.data || submitted && !version ? <p role="status">{t('正在读取已提交需求……')}</p>
        : !version ? <p>{t('客户尚未提交需求。')}</p> : null}
    {version && <dl className="analyst-project-info analyst-requirement-rows">
      <div><dt>{t('提交时间')}</dt><dd><time dateTime={version.created_at}>{new Date(version.created_at).toLocaleString(locale)}</time></dd></div>
      <div>
        <dt>{t('研究范围')}</dt>
        <dd>{scope.length
          ? <ul className="analyst-scope-list">{scope.map(item => <li key={item.id}>{item.title}</li>)}</ul>
          : t('暂无已选研究范围。')}</dd>
      </div>
      {notes && <div><dt>{t('补充说明')}</dt><dd className="analyst-note">{notes}</dd></div>}
    </dl>}
  </section>
}

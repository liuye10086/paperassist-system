import { useI18n } from '../../shared/i18n'
import { WorkspaceIcon } from '../projects/WorkspaceShell'
import { projectBase } from '../research-intake/api'
import { confirmedSampleRegistration } from '../research-intake/assignedSampleRegistration'
import type { Intake, Version } from '../research-intake/contracts'
import { useResearchRead } from '../research-results/api'
import SubmittedScope from './SubmittedScope'
import type { AnalystWorkspace, SubmittedVersion } from './useAnalystWorkspace'

function confirmedVersion(version: Version | null | undefined, projectId: string): version is Version {
  return !!version && typeof version.id === 'string' && Number.isSafeInteger(version.version) && version.operation === 'confirm'
    && !!version.content && (!version.project_id || version.project_id === projectId)
}

function matchesSubmitted(version: Version, submitted: SubmittedVersion) {
  return version.id === submitted.id && version.version === submitted.version
}

export default function SubmittedRequirement({ projectId, workspace, onDesign }: {
  projectId: string; workspace: AnalystWorkspace; onDesign: () => void
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
  const sampleInfo = confirmedSampleRegistration(version)
  const scope = Array.isArray(version?.content.scope_items) ? version.content.scope_items.filter(item => item && typeof item.id === 'string'
    && typeof item.title === 'string' && item.delivery_kind === 'analysis' && item.status !== 'not_included') : []
  return <section className="project-details-card analyst-project-details submitted-requirement" aria-label={t('已提交需求')} tabIndex={0}>
    {readError ? <><p role="alert">{t(readError)}</p><button type="button" onClick={() => { workspace.refresh(); intake.refresh(); historical.refresh() }}>{t('重新读取需求')}</button></>
      : !intake.data || submitted && !version ? <p role="status">{t('正在读取已提交需求……')}</p>
        : !version ? <p>{t('客户尚未提交需求。')}</p> : null}
    {version && <div className="submitted-summary">
      <SubmittedScope scope={scope}/>
      <dl className="submitted-facts">
        {!!version.content.study_species?.length && <div><dt>{t('研究物种')}</dt>
          <dd>{version.content.study_species.map(name => t(name)).join(locale === 'en' ? ', ' : '、')}</dd></div>}
        {sampleInfo && <div><dt>{t('样本信息')}</dt><dd>{t('{groups} 个分组，{samples} 个样本',{groups:sampleInfo.groups.length,samples:sampleInfo.samples.length})}</dd></div>}
        <div><dt>{t('提交时间')}</dt><dd><time dateTime={version.created_at}>{new Date(version.created_at).toLocaleString(locale)}</time></dd></div>
      </dl>
      {notes && <section className="submitted-notes"><h2>{t('补充说明')}</h2><p className="analyst-note">{notes}</p></section>}
    </div>}
    <section className="analyst-design-entry" aria-label={t('实验设计')}>
      <div><h2>{t('实验设计')}</h2>
        <p>{t('核对客户提交的样本和分组，记录要比较哪些组、哪组作对照，以及哪些样本是独立重复。')}</p></div>
      <button type="button" className="button-primary" onClick={onDesign}>{t('打开实验设计')}<WorkspaceIcon name="arrow"/></button>
    </section>
  </section>
}

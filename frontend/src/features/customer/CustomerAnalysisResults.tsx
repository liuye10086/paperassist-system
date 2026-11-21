import { useCallback, useEffect, useRef, useState, type Ref } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { safeError, useI18n } from '../../shared/i18n'
import VersionLabel from '../../shared/VersionLabel'
import { versionMinute } from '../../shared/versionLabelText'
import { isProject, type Project } from '../projects/projectTypes'
import { researchRequest, useResearchRead } from '../research-results/api'
import { DeliveryMembers } from './CustomerDeliveries'
import { customerBase, type DeliveryDetail, type DeliveryMember, type DeliverySummary } from './customerWorkspaceApi'
import ReturnBar from './ReturnBar'
import type { ReturnTarget } from './returnToken'

export type AnalysisSelection = { projectId: string; snapshotId: string }
/** What the customer downloaded, kept for this browser tab only to prefill where it came from. */
export type AnalysisPick = { researchProjectName: string; deliveryTitle: string; memberNames: string[] }
/** Where the view was opened from: a review opinion takes Word files only, writing materials take any file. */
export type AnalysisPurpose = 'reviews' | 'materials'

type Props = {
  paperProjectId: string
  purpose: AnalysisPurpose
  returnTarget: ReturnTarget | null
  onReturn: (href: string) => void
  selected: AnalysisSelection | null
  onSelect: (selection: AnalysisSelection | null) => void
  onPick: (pick: AnalysisPick) => void
  /** With a ref the page title is the page heading (h1); otherwise it sits under the host page heading. */
  headingRef?: Ref<HTMLHeadingElement>
}
type Read = { items: DeliverySummary[] } | { error: string }

const projectPageSize = 100
const concurrentReads = 4
const isWord = (member: DeliveryMember) => member.format.toLowerCase() === 'docx'

async function eachLimited<T>(items: T[], work: (item: T) => Promise<void>) {
  let next = 0
  await Promise.all(Array.from({ length: Math.min(concurrentReads, items.length) }, async () => {
    while (next < items.length) await work(items[next++])
  }))
}

// Wireframes 17 and 18 (D3): only GET requests, and the paper project stays the workspace project. Analysis projects
// are never registered for project access, so one of them failing cannot mark the paper project unavailable.
export default function CustomerAnalysisResults({
  paperProjectId, purpose, returnTarget, onReturn, selected, onSelect, onPick, headingRef,
}: Props) {
  const { t, locale } = useI18n()
  const [attempt, setAttempt] = useState(0)
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [listError, setListError] = useState('')
  const [reads, setReads] = useState<Record<string, Read>>({})
  const lifetime = useRef<AbortController | null>(null)
  // Under a host page heading the workspace does not move focus for this view, so the view takes it on opening.
  const ownHeading = useRef<HTMLHeadingElement | null>(null)
  useEffect(() => { if (!headingRef) ownHeading.current?.focus({ preventScroll: true }) }, [headingRef])

  const readProject = useCallback(async (project: Project, signal: AbortSignal) => {
    let result: Read
    try {
      const value = await researchRequest<{ items?: unknown }>(customerBase(project.id) + '/deliveries', { signal })
      if (!Array.isArray(value?.items)) throw new Error('invalid')
      result = { items: (value.items as DeliverySummary[]).filter(item => item?.kind === 'analysis') }
    } catch (cause) {
      result = { error: safeError(cause, '') }
    }
    if (!signal.aborted) setReads(old => ({ ...old, [project.id]: result }))
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    lifetime.current = controller
    const stop = onApiSessionChanged(() => controller.abort())
    void (async () => {
      try {
        const found: Project[] = []
        for (let page = 1; ; page += 1) {
          const value = await researchRequest<{ items?: unknown; total?: unknown }>(
            `/api/v1/projects?type=research&page=${page}&page_size=${projectPageSize}`, { signal: controller.signal })
          if (!Array.isArray(value?.items) || !Number.isSafeInteger(value.total)) throw new Error('invalid')
          found.push(...value.items.filter(isProject).filter(item => item.project_type === 'research' && item.id !== paperProjectId))
          if (!value.items.length || page * projectPageSize >= Number(value.total)) break
        }
        if (controller.signal.aborted) return
        setProjects(found)
        await eachLimited(found, project => readProject(project, controller.signal))
      } catch {
        if (!controller.signal.aborted) setListError('暂时无法读取分析成果。')
      }
    })()
    return () => { controller.abort(); stop() }
  }, [attempt, paperProjectId, readProject])

  function retryList() {
    setProjects(null)
    setReads({})
    setListError('')
    setAttempt(value => value + 1)
  }
  function retryProject(project: Project) {
    const signal = lifetime.current?.signal
    if (!signal || signal.aborted) return
    setReads(old => Object.fromEntries(Object.entries(old).filter(([id]) => id !== project.id)))
    void readProject(project, signal)
  }

  const rows = (projects ?? []).flatMap(project => {
    const read = reads[project.id]
    return read && 'items' in read ? read.items.map(delivery => ({ project, delivery })) : []
  }).sort((a, b) => Date.parse(b.delivery.published_at) - Date.parse(a.delivery.published_at))
  const failed = (projects ?? []).filter(project => { const read = reads[project.id]; return read && 'error' in read })
  const loading = !listError && (!projects || projects.some(project => !reads[project.id]))
  const empty = !loading && !listError && rows.length === 0 && failed.length === 0
  const chosenProject = selected ? projects?.find(project => project.id === selected.projectId) : undefined
  const Heading = headingRef ? 'h1' : 'h2'

  return <section className="customer-section customer-analysis-results" aria-label={t('选择分析成果')}>
    <ReturnBar target={returnTarget} onReturn={onReturn}>
      {t(purpose === 'reviews' ? '正在为“{place}”取分析结果' : '正在为“{place}”取分析成果', { place: returnTarget?.label ?? '' })}
    </ReturnBar>
    <div className="customer-section-heading">
      <Heading ref={headingRef ?? ownHeading} tabIndex={-1}>{t('选择分析成果')}</Heading>
    </div>
    {listError && <div role="alert" className="error-panel">{t(listError)}{' '}
      <button type="button" onClick={retryList}>{t('重试')}</button>
    </div>}
    {failed.map(project => <div key={project.id} role="alert" className="error-panel">
      {t('暂时无法读取“{project}”的分析成果。', { project: project.name })}{' '}
      <button type="button" onClick={() => retryProject(project)}>{t('重试')}</button>
    </div>)}
    {loading && <p role="status">{t('正在读取分析成果……')}</p>}
    {empty && <div className="empty-preview">
      <p>{t('还没有已发布的分析成果。分析完成后会在这里出现。')}</p>
      {returnTarget && <button type="button" className="button-primary" onClick={() => onReturn(returnTarget.href)}>
        {t('返回 {place}', { place: returnTarget.label })}
      </button>}
    </div>}
    {rows.length > 0 && <ul className="customer-list" aria-label={t('已发布的分析成果')}>
      {rows.map(({ project, delivery }) => {
        const current = selected?.projectId === project.id && selected.snapshotId === delivery.id
        return <li key={project.id + ':' + delivery.id}>
          <button type="button" className="button-quiet" aria-current={current ? 'true' : undefined}
            onClick={() => { if (!current) onSelect({ projectId: project.id, snapshotId: delivery.id }) }}>
            {project.name} · {delivery.title} · {versionMinute(delivery.published_at, locale)}
          </button>
        </li>
      })}
    </ul>}
    {selected && projects && !chosenProject && <p role="alert">{t('这份分析成果不可用，请重新选择。')}</p>}
    {selected && chosenProject && <AnalysisResult key={selected.projectId + ':' + selected.snapshotId}
      project={chosenProject} snapshotId={selected.snapshotId} purpose={purpose} returnTarget={returnTarget} onPick={onPick} />}
  </section>
}

function AnalysisResult({ project, snapshotId, purpose, returnTarget, onPick }: {
  project: Project
  snapshotId: string
  purpose: AnalysisPurpose
  returnTarget: ReturnTarget | null
  onPick: (pick: AnalysisPick) => void
}) {
  const { t } = useI18n()
  const base = `${customerBase(project.id)}/deliveries/${encodeURIComponent(snapshotId)}`
  const read = useResearchRead<DeliveryDetail>(base, true)
  const [downloaded, setDownloaded] = useState(false)
  const detail = read.data
  const valid = !!detail && detail.id === snapshotId && detail.kind === 'analysis' && Array.isArray(detail.members)
  // A review opinion takes Word files only (user decision 2026-11-20): Word comes first, other files are marked.
  const members = valid ? purpose === 'reviews'
    ? [...detail.members.filter(isWord), ...detail.members.filter(member => !isWord(member))] : detail.members : []
  function picked(names: string[]) {
    if (!valid) return
    setDownloaded(true)
    onPick({ researchProjectName: project.name, deliveryTitle: detail.title, memberNames: names })
  }
  return <section className="manuscript-panel" aria-label={valid ? `${project.name} · ${detail.title}` : t('成果文件')}>
    {read.error && <div role="alert" className="error-panel">{t(read.error)}{' '}
      <button type="button" onClick={read.refresh}>{t('重试')}</button>
    </div>}
    {!detail && !read.error && <p role="status">{t('正在读取成果文件……')}</p>}
    {detail && !valid && <p role="alert">{t('这份分析成果不可用，请重新选择。')}</p>}
    {valid && <>
      <div className="customer-delivery-row customer-delivery-heading">
        <div className="customer-delivery-info"><h3>{project.name} · {detail.title}</h3><p className="muted">
          <VersionLabel revision={detail.revision} savedAt={detail.published_at} />
        </p></div>
        {detail.package_url === base + '/download' && <div className="customer-actions">
          <ProjectDownloadLink href={detail.package_url} filename={detail.title + '.zip'}
            onDownloaded={() => picked(detail.members.map(member => member.name))}>{t('下载全部文件')}</ProjectDownloadLink>
        </div>}
      </div>
      <DeliveryMembers base={base} members={members} label={t('成果文件')}
        note={purpose === 'reviews' ? member => isWord(member) ? null : t('需放进 Word 后再上传') : undefined}
        onDownloaded={member => picked([member.name])} />
      {downloaded && returnTarget && <p role="status">
        {t('下载所需文件后，可以返回 {place} 继续上传。', { place: returnTarget.label })}
      </p>}
    </>}
  </section>
}

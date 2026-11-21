import { useCallback, useLayoutEffect, useRef, useState, type RefObject } from 'react'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { useI18n } from '../../shared/i18n'
import VersionLabel from '../../shared/VersionLabel'
import type { LeaveGuard, RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { deliveryLabels } from '../research-intake/contracts'
import { useResearchRead } from '../research-results/api'
import CustomerFeedback from './CustomerFeedback'
import { customerBase, type DeliveryDetail, type DeliveryMember, type DeliverySummary } from './customerWorkspaceApi'

type Props = {
  projectId: string
  initialSnapshotId?: string
  initialDeliveryId?: string
  onSelectSnapshot: (id: string | null) => void
  headingRef: RefObject<HTMLHeadingElement | null>
  registerLeaveGuard: RegisterLeaveGuard
}

export default function CustomerDeliveries({ projectId, initialDeliveryId, initialSnapshotId, onSelectSnapshot, headingRef, registerLeaveGuard }: Props) {
  const { t } = useI18n()
  const selected = initialSnapshotId ?? null
  const returnDelivery = useRef<string | null>(null)
  const returnButton = useRef<HTMLButtonElement | null>(null)
  const read = useResearchRead<{ items: DeliverySummary[] }>(customerBase(projectId) + '/deliveries', selected === null)
  const deliveries = read.data?.items.filter(item => !initialDeliveryId || item.delivery_id === initialDeliveryId)
  useLayoutEffect(() => {
    if (!selected && returnDelivery.current) {
      (returnButton.current ?? headingRef.current)?.focus()
      returnDelivery.current = null
    }
  }, [selected, headingRef])
  if (selected) return <ReleasedDelivery key={selected} projectId={projectId} snapshotId={selected}
    expectedDeliveryId={initialDeliveryId} onBack={() => onSelectSnapshot(null)} registerLeaveGuard={registerLeaveGuard} />

  return <div className="customer-section customer-deliveries">
    <div className="customer-section-heading">
      <h1 ref={headingRef} tabIndex={-1}>{t('已发布交付')}</h1>
      <button type="button" className="button-quiet" disabled={read.loading} onClick={read.refresh}>{t('刷新交付')}</button>
    </div>
    {read.error && <p role="alert" className="error-panel">{t(read.error)}</p>}
    {!read.data && !read.error && <p role="status">{t('正在读取已发布交付……')}</p>}
    {deliveries && !read.error && (deliveries.length === 0
      ? <p>{t(initialDeliveryId ? '此交付暂无已发布版本。' : '此项目暂无已发布交付。')}</p>
      : groupByDelivery(deliveries).map(([current, ...older]) => {
        const version = (delivery: DeliverySummary, isCurrent: boolean) => <DeliveryVersion key={delivery.id}
          projectId={projectId} delivery={delivery} current={isCurrent} title={current.title}
          viewRef={button => { if (returnDelivery.current === delivery.id) returnButton.current = button }}
          onOpen={() => { returnDelivery.current = delivery.id; onSelectSnapshot(delivery.id) }} />
        const headingId = `customer-delivery-${current.id}`
        return <section key={current.id} className="customer-delivery-group" aria-labelledby={headingId}>
          <h2 id={headingId}>{current.title}</h2>
          <p className="muted">{t(deliveryLabels[current.kind])}</p>
          <ul className="customer-list">{version(current, true)}</ul>
          {older.length > 0 && <>
            <h3>{t('之前发布的版本')}</h3>
            <ul className="customer-list">{older.map(delivery => version(delivery, false))}</ul>
            <p className="muted">{t('只列出已发布的版本，版次可能不连续。')}</p>
          </>}
        </section>
      }))}
  </div>
}

// Published snapshots arrive newest first; keep that order, so each group starts with its current delivery.
function groupByDelivery(items: DeliverySummary[]) {
  const groups = new Map<string, DeliverySummary[]>()
  for (const item of items) groups.set(item.delivery_id, [...groups.get(item.delivery_id) ?? [], item])
  return [...groups.values()]
}

function DeliveryVersion({ projectId, delivery, current, title, viewRef, onOpen }: {
  projectId: string
  delivery: DeliverySummary
  current: boolean
  title: string
  viewRef: (button: HTMLButtonElement | null) => void
  onOpen: () => void
}) {
  const { t } = useI18n()
  const name = current ? title : `${title} ${t('第 {revision} 版', { revision: delivery.revision })}`
  return <li className="customer-delivery-row">
    <div className="customer-delivery-info"><p>
      <VersionLabel revision={delivery.revision} savedAt={delivery.published_at} />
      {current && <span className="version-label-current">{t('当前交付')}</span>}
      {' · '}{t('{count} 个文件', { count: delivery.member_count })}
    </p></div>
    <div className="customer-actions">
      <button type="button" className="button-quiet" aria-label={t('查看交付 {title}', { title: name })}
        ref={viewRef} onClick={onOpen}>{t('查看详情')}</button>
      <DeliveryDownload projectId={projectId} delivery={delivery} label={t('下载交付 {title}', { title: name })} onOpen={onOpen} />
    </div>
  </li>
}

// Downloads the package, or the only file, straight from the list. Otherwise “下载” opens the details,
// which is also the fallback while the details are loading or could not be read.
function DeliveryDownload({ projectId, delivery, label, onOpen }: {
  projectId: string
  delivery: DeliverySummary
  label: string
  onOpen: () => void
}) {
  const { t } = useI18n()
  const base = `${customerBase(projectId)}/deliveries/${encodeURIComponent(delivery.id)}`
  const detail = useResearchRead<DeliveryDetail>(base, true).data
  const members = detail?.id === delivery.id && Array.isArray(detail.members) ? detail.members : null
  const only = members?.length === 1 ? members[0] : null
  const target = !members ? null
    : detail?.package_url === base + '/download' ? { href: detail.package_url, filename: delivery.title + '.zip' }
      : only && only.download_url === `${base}/members/${encodeURIComponent(only.id)}/download`
        ? { href: only.download_url, filename: only.name } : null
  return target
    ? <ProjectDownloadLink href={target.href} filename={target.filename} ariaLabel={label}>{t('下载')}</ProjectDownloadLink>
    : <button type="button" className="button-quiet" aria-label={label} onClick={onOpen}>{t('下载')}</button>
}

function ReleasedDelivery({ projectId, snapshotId, expectedDeliveryId, onBack, registerLeaveGuard }: {
  projectId: string
  snapshotId: string
  expectedDeliveryId?: string
  onBack: () => void
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t } = useI18n()
  const base = `${customerBase(projectId)}/deliveries/${encodeURIComponent(snapshotId)}`
  const read = useResearchRead<DeliveryDetail>(base, true)
  const mismatch = !!read.data && (read.data.id !== snapshotId ||
    !!expectedDeliveryId && read.data.delivery_id !== expectedDeliveryId)
  const delivery = mismatch ? null : read.data
  const heading = useRef<HTMLHeadingElement | null>(null)
  const backButton = useRef<HTMLButtonElement | null>(null)
  useLayoutEffect(() => { backButton.current?.focus() }, [])
  useLayoutEffect(() => {
    if (document.activeElement === backButton.current) heading.current?.focus()
  }, [delivery?.id, read.error])
  const feedbackGuard = useRef<LeaveGuard | null>(null)
  const registerFeedback = useCallback<RegisterLeaveGuard>((guard, isDirty) => {
    feedbackGuard.current = guard
    const unregister = registerLeaveGuard(guard, isDirty)
    return () => { feedbackGuard.current = null; unregister() }
  }, [registerLeaveGuard])

  return <div className="customer-section customer-deliveries">
    <button ref={backButton} type="button" className="button-quiet" onClick={() => {
      if (feedbackGuard.current?.(true) !== false) onBack()
    }}>{t('返回交付列表')}</button>
    {read.error && <div role="alert" className="error-panel">{t(read.error)}{' '}
      <button type="button" onClick={read.refresh}>{t('刷新交付')}</button>
    </div>}
    {mismatch && <p role="alert">{t('该交付版本与链接不匹配。')}</p>}
    {!read.data && !read.error && <p role="status">{t('正在读取交付详情……')}</p>}
    {delivery && !read.error && <>
      <div className="customer-delivery-row customer-delivery-heading">
        <div className="customer-delivery-info"><h1 ref={heading} tabIndex={-1}>{delivery.title}</h1><p className="muted">
          <VersionLabel revision={delivery.revision} savedAt={delivery.published_at} />
        </p></div>
        {delivery.package_url === base + '/download' && <div className="customer-actions">
          <ProjectDownloadLink href={delivery.package_url} filename={delivery.title + '.zip'}>{t('下载交付包')}</ProjectDownloadLink>
        </div>}
      </div>
      <DeliveryMembers base={base} members={delivery.members} label={t('交付文件')} />
      <CustomerFeedback projectId={projectId} snapshotId={snapshotId} entries={delivery.feedback}
        onSaved={read.refresh} registerLeaveGuard={registerFeedback} />
    </>}
  </div>
}

const formatLabels: Record<string, string> = {
  docx: 'Word', xlsx: 'Excel', pdf: 'PDF',
  png: '图片', jpg: '图片', jpeg: '图片', tif: '图片', tiff: '图片', svg: '图片',
  zip: 'ZIP 压缩包', csv: 'CSV 数据表', tsv: 'TSV 数据表',
}

/**
 * The files of one published snapshot, without feedback. A file is only offered for download when its address is
 * exactly the member address under `base`; `note` adds a line under a file name.
 */
export function DeliveryMembers({ base, members, label, note, onDownloaded }: {
  base: string
  members: DeliveryMember[]
  label: string
  note?: (member: DeliveryMember) => string | null
  onDownloaded?: (member: DeliveryMember) => void
}) {
  const { t, locale } = useI18n()
  const [previewId, setPreviewId] = useState<string | null>(null)
  return <ul className="customer-list" aria-label={label}>
    {members.map(member => {
      const href = `${base}/members/${encodeURIComponent(member.id)}/download`
      const downloadable = href === member.download_url
      const format = member.format.toLowerCase()
      const image = downloadable && ['png', 'jpg', 'jpeg'].includes(format)
      const extra = note?.(member)
      return <li key={member.id} className="customer-delivery-member">
        <div className="customer-delivery-row">
          <div className="customer-delivery-info"><strong>{member.name}</strong><p className="muted">
            {t(Object.hasOwn(formatLabels, format) ? formatLabels[format] : '文件')} · {t('{count} 字节', { count: member.size_bytes.toLocaleString(locale) })}
            {extra && <> · {extra}</>}
          </p></div>
          {downloadable && <div className="customer-actions">
            {image && <button type="button" className="button-quiet" aria-pressed={previewId === member.id}
              onClick={() => setPreviewId(current => current === member.id ? null : member.id)}>{t('预览图件')}</button>}
            <ProjectDownloadLink href={href} filename={member.name} onDownloaded={onDownloaded && (() => onDownloaded(member))}
              ariaLabel={t('下载 {name}', { name: member.name })}>{t('下载文件')}</ProjectDownloadLink>
          </div>}
        </div>
        {image && previewId === member.id && <ReleasedImage key={href} href={href} name={member.name} />}
      </li>
    })}
  </ul>
}

function ReleasedImage({ href, name }: { href: string; name: string }) {
  const { t } = useI18n()
  const [failed, setFailed] = useState(false)
  return failed
    ? <p role="alert">{t('无法预览图件，请下载后查看。')}</p>
    : <img className="customer-delivery-image" src={href} alt={name} onError={() => setFailed(true)} />
}

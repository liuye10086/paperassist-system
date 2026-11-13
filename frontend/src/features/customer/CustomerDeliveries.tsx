import { useCallback, useLayoutEffect, useRef, useState, type RefObject } from 'react'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { useI18n } from '../../shared/i18n'
import type { LeaveGuard, RegisterLeaveGuard } from '../projects/useDraftLeaveGuard'
import { deliveryLabels } from '../research-intake/contracts'
import { useResearchRead } from '../research-results/api'
import CustomerFeedback from './CustomerFeedback'
import { customerBase, type DeliveryDetail, type DeliverySummary } from './customerWorkspaceApi'

export default function CustomerDeliveries({ projectId, headingRef, registerLeaveGuard }: {
  projectId: string
  headingRef: RefObject<HTMLHeadingElement | null>
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t, locale } = useI18n()
  const [selected, setSelected] = useState<string | null>(null)
  const returnDelivery = useRef<string | null>(null)
  const returnButton = useRef<HTMLButtonElement | null>(null)
  const read = useResearchRead<{ items: DeliverySummary[] }>(customerBase(projectId) + '/deliveries', selected === null)
  useLayoutEffect(() => {
    if (!selected && returnDelivery.current) {
      (returnButton.current ?? headingRef.current)?.focus()
      returnDelivery.current = null
    }
  }, [selected, headingRef])
  if (selected) return <ReleasedDelivery key={selected} projectId={projectId} snapshotId={selected}
    onBack={() => setSelected(null)} registerLeaveGuard={registerLeaveGuard} />

  return <div className="customer-section customer-deliveries">
    <div className="customer-section-heading">
      <h1 ref={headingRef} tabIndex={-1}>{t('已发布交付')}</h1>
      <button type="button" className="button-quiet" disabled={read.loading} onClick={read.refresh}>{t('刷新交付')}</button>
    </div>
    {read.error && <p role="alert" className="error-panel">{t(read.error)}</p>}
    {!read.data && !read.error && <p role="status">{t('正在读取已发布交付……')}</p>}
    {read.data && !read.error && (read.data.items.length === 0
      ? <p>{t('此项目暂无已发布交付。')}</p>
      : <ul className="customer-list">
        {read.data.items.map(delivery => <li key={delivery.id} className="customer-delivery-row">
          <div className="customer-delivery-info"><strong>{delivery.title}</strong><p className="muted">
            {t(deliveryLabels[delivery.kind])} · {t('{count} 个文件', { count: delivery.member_count })} ·{' '}
            <time dateTime={delivery.published_at}>{new Date(delivery.published_at).toLocaleString(locale)}</time>
          </p></div>
          <button type="button" className="button-quiet" aria-label={t('查看交付 {title}', { title: delivery.title })}
            ref={button => { if (returnDelivery.current === delivery.id) returnButton.current = button }}
            onClick={() => { returnDelivery.current = delivery.id; setSelected(delivery.id) }}>{t('查看详情')}</button>
        </li>)}
      </ul>)}
  </div>
}

function ReleasedDelivery({ projectId, snapshotId, onBack, registerLeaveGuard }: {
  projectId: string
  snapshotId: string
  onBack: () => void
  registerLeaveGuard: RegisterLeaveGuard
}) {
  const { t, locale } = useI18n()
  const base = `${customerBase(projectId)}/deliveries/${encodeURIComponent(snapshotId)}`
  const read = useResearchRead<DeliveryDetail>(base, true)
  const delivery = read.data
  const [previewId, setPreviewId] = useState<string | null>(null)
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
    {!delivery && !read.error && <p role="status">{t('正在读取交付详情……')}</p>}
    {delivery && !read.error && <>
      <div className="customer-delivery-row customer-delivery-heading">
        <div className="customer-delivery-info"><h1 ref={heading} tabIndex={-1}>{delivery.title}</h1><p className="muted">
          {t('版本 {version} · 发布于 {date}', { version: delivery.revision, date: new Date(delivery.published_at).toLocaleString(locale) })}
        </p></div>
        {delivery.package_url === base + '/download' && <div className="customer-actions">
          <ProjectDownloadLink href={delivery.package_url} filename={delivery.title + '.zip'}>{t('下载交付包')}</ProjectDownloadLink>
        </div>}
      </div>
      <ul className="customer-list" aria-label={t('交付文件')}>
        {delivery.members.map(member => {
          const href = `${base}/members/${encodeURIComponent(member.id)}/download`
          const downloadable = href === member.download_url
          const image = downloadable && ['png', 'jpg', 'jpeg'].includes(member.format.toLowerCase())
          return <li key={member.id} className="customer-delivery-member">
            <div className="customer-delivery-row">
              <div className="customer-delivery-info"><strong>{member.name}</strong><p className="muted">
                {member.format.toUpperCase()} · {t('{bytes} 字节', { bytes: member.size_bytes.toLocaleString(locale) })}
              </p></div>
              {downloadable && <div className="customer-actions">
                {image && <button type="button" className="button-quiet" aria-pressed={previewId === member.id}
                  onClick={() => setPreviewId(current => current === member.id ? null : member.id)}>{t('预览图件')}</button>}
                <ProjectDownloadLink href={href} filename={member.name}
                  ariaLabel={t('下载 {name}', { name: member.name })}>{t('下载文件')}</ProjectDownloadLink>
              </div>}
            </div>
            {image && previewId === member.id && <ReleasedImage key={href} href={href} name={member.name} />}
          </li>
        })}
      </ul>
      <CustomerFeedback projectId={projectId} snapshotId={snapshotId} entries={delivery.feedback}
        onSaved={read.refresh} registerLeaveGuard={registerFeedback} />
    </>}
  </div>
}

function ReleasedImage({ href, name }: { href: string; name: string }) {
  const { t } = useI18n()
  const [failed, setFailed] = useState(false)
  return failed
    ? <p role="alert">{t('无法预览图件，请下载后查看。')}</p>
    : <img className="customer-delivery-image" src={href} alt={name} onError={() => setFailed(true)} />
}

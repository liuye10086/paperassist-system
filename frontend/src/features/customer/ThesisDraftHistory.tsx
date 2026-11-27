import { useI18n } from '../../shared/i18n'
import ManuscriptExports from '../manuscripts/ManuscriptExports'
import ManuscriptPreview from '../manuscripts/ManuscriptPreview'
import { isAdoptedSnapshot, manuscriptBase, manuscriptVersionPath, validManuscript, type Manuscript, type ManuscriptVersion } from '../manuscripts/manuscriptTypes'
import type { Round } from '../reviews/reviewTypes'
import { projectBase, useResearchRead } from '../research-results/api'
import CustomerDownloadLink from './CustomerDownloadLink'
import type { UpdatePaperRoute } from './customerPaperNavigation'

type PastDraft = { manuscript_id: string; revision: number; request_id: string; title: string; created_at: string; previous_request_id: string | null }
type Props = { projectId: string; update: UpdatePaperRoute }

function Exports({ version }: { version: ManuscriptVersion }) {
  return <>{version.exports.filter(file => file.status === 'succeeded' && file.download_url && file.filename).map(file =>
    <CustomerDownloadLink key={file.id} href={file.download_url!} filename={file.filename!}>{file.filename}</CustomerDownloadLink>)}</>
}

export function ThesisHistory({ projectId, update }: Props) {
  const { t, locale } = useI18n()
  const requests = useResearchRead<{items: PastDraft[]}>(projectBase(projectId) + '/draft-history', true)
  const manuscripts = useResearchRead<{items: Manuscript[]}>(manuscriptBase(projectId), true)
  const saved = (manuscripts.data?.items ?? []).filter(m => validManuscript(m, projectId)).flatMap(m => m.versions
    .filter(v => isAdoptedSnapshot(v.snapshot, v.parent_version_id) || v.exports.some(e => e.status === 'succeeded'))
    .map(v => ({m, v})))
  return <section className="sci-draft-history" aria-label={t('历史版本')}>
    <h2>{t('历史版本')}</h2>
    {requests.data?.items?.map(draft => <article key={draft.request_id}>
      <div><strong>{draft.title}</strong><p>{t(draft.previous_request_id ? '修改稿' : '初稿')} · {new Date(draft.created_at).toLocaleString(locale)}</p></div>
      <button type="button" className="button-accent" onClick={() => update({manuscript:draft.manuscript_id, revision:draft.revision, writingRequest:draft.request_id, view:'writing'}, true)}>{t('查看这版正文')}</button>
    </article>)}
    {saved.map(({m,v}) => <article key={v.id}><div><strong>{v.snapshot.title}</strong>
      <p>{t('已保存稿件')} · {t('第 {number} 版',{number:v.revision})}</p></div>
      <div className="customer-actions">
        <Exports version={v}/>
        <button type="button" className="button-accent" onClick={() => update({manuscript:m.id, revision:v.revision, writingRequest:undefined, view:'saved'}, true)}>{t('查看这版正文')}</button>
      </div>
    </article>)}
    {[requests, manuscripts].map((read, i) => read.error && <p role="alert" key={i}>{t(read.error)} <button onClick={read.refresh}>{t('重试')}</button></p>)}
    {(requests.loading || manuscripts.loading) && <p className="visually-hidden" role="status">{t('正在读取稿件……')}</p>}
    {requests.data?.items?.length === 0 && manuscripts.data && !saved.length && <p>{t('还没有历史稿件。')}</p>}
  </section>
}

export function SavedThesisVersion({ projectId, manuscript, revision, update }: Props & {manuscript: string; revision: number}) {
  const { t } = useI18n()
  const read = useResearchRead<ManuscriptVersion>(manuscriptVersionPath(projectId, manuscript, revision), true)
  const version = read.data?.revision === revision && read.data.snapshot?.project_id === projectId ? read.data : null
  if (read.error || (read.data && !version)) return <p role="alert">{t(read.error || '指定固定稿件版本不可用。')} <button onClick={read.refresh}>{t('重试')}</button></p>
  if (!version) return <p role="status">{t('正在读取稿件……')}</p>
  const adopted = isAdoptedSnapshot(version.snapshot, version.parent_version_id)
  const hasWord = version.exports.some(e => e.status === 'succeeded' && e.download_url)
  return <section>{adopted && !hasWord
      ? <ManuscriptExports projectId={projectId} manuscriptId={manuscript} version={version} customerThesis active/>
      : <Exports version={version}/>}
    {adopted
      ? <ManuscriptPreview snapshot={version.snapshot} customerView presentation="body" label="已保存稿件"/>
      : <><p>{t('这版保存的是写作材料。')}</p><button onClick={() => update({view:'select', manuscript:undefined, revision:undefined, writingRequest:undefined},true)}>{t('前往文献与初稿')}</button></>}
  </section>
}

export function PastThesisOpinions({ projectId, roundId, update }: Props & {roundId: string}) {
  const {t} = useI18n()
  const saved = useResearchRead<Round>(projectBase(projectId) + '/reviews/rounds/' + encodeURIComponent(roundId), true)
  if (saved.error || (saved.data && saved.data.id !== roundId)) return <p role="alert">{t(saved.error || '意见轮次不可用。')} <button onClick={saved.refresh}>{t('重试')}</button></p>
  if (!saved.data) return <p role="status">{t('正在读取意见……')}</p>
  const round = saved.data
  return <section><h2>{round.title}</h2>
    {round.sources.map(source => <div key={source.id}><h3>{source.label}</h3><p className="template-text">{source.original_text}</p></div>)}
    <button onClick={() => update({view:'saved', round:undefined, item:undefined, manuscript:round.manuscript.id, revision:round.manuscript.revision, writingRequest:undefined},true)}>{t('查看这版正文')}</button>
  </section>
}

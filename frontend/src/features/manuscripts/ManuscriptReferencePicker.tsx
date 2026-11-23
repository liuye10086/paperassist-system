import { useId, useState } from 'react'
import { useI18n } from '../../shared/i18n'
import { useEvidenceResource } from '../literature/evidenceHooks'
import { basePath, validPage, validReference, type Page, type Reference } from '../literature/literatureApi'
import { EvidencePagination } from '../literature/LiteratureMaterials'
import './manuscriptReferencePicker.css'

export type SelectedReference = { project_reference_id: string; search_id: string; quote: string }
type Props = {
  projectId: string
  active: boolean
  disabled: boolean
  selected: SelectedReference[]
  onChange: (next: SelectedReference[]) => void
  onFindLiterature?: () => void
}
const maxReferences = 20
const maxQuoteLength = 6000
const characterCount = (value: string) => Array.from(value).length

function LongAbstractExcerpt({ text, selectedQuote, disabled, onChoose }: {
  text: string; selectedQuote?: string; disabled: boolean; onChoose: (quote: string) => void
}) {
  const { t } = useI18n()
  const hint = useId()
  const [draft, setDraft] = useState(selectedQuote && text.includes(selectedQuote) ? selectedQuote : '')
  const valid = !!draft.trim() && characterCount(draft) <= maxQuoteLength && text.includes(draft)
  return <div className="manuscript-reference-excerpt">
    <p className="manuscript-reference-text">{text}</p>
    <p className="muted" id={hint}>{t('此段超过 {limit} 字，请从中复制一段连续原文（最多 {limit} 字）。', { limit: maxQuoteLength })}</p>
    <label>{t('摘录此段连续原文')}
      <textarea value={draft} disabled={disabled} aria-describedby={hint} aria-invalid={!!draft && !valid}
        onChange={event => setDraft(event.target.value)} />
    </label>
    {draft && !valid && <p className="muted">{t('请保留原文措辞和顺序，并核对摘录字数。')}</p>}
    <label className="manuscript-reference-choice">
      <input type="checkbox" checked={!!draft && selectedQuote === draft} disabled={disabled || !valid}
        onChange={() => onChoose(draft)} />
      {t('选用此摘录')}
    </label>
  </div>
}

function ReferenceOption({ item, selected, disabled, onChoose, onRemove }: {
  item: Reference; selected?: SelectedReference; disabled: boolean; onChoose: (quote: string) => void; onRemove: () => void
}) {
  const { t } = useI18n()
  const { record, source } = item
  // Saved selections identify the verbatim text, so duplicate paragraphs share one choice.
  const paragraphs = new Map<string, Reference['record']['abstract'][number]>()
  if (record.abstract_status === 'available') {
    for (const part of record.abstract) {
      if (part.text.trim() && !paragraphs.has(part.text)) paragraphs.set(part.text, part)
    }
  }
  const excluded = item.selection.status === 'excluded'
  const selectedQuote = selected?.search_id === source.search_id ? selected.quote : undefined
  const listedSelection = !excluded && !!selectedQuote && paragraphs.has(selectedQuote)
  const publication = [source.source_kind === 'synthetic_fixture' ? t('合成测试资料') : 'PubMed',
    `PMID ${item.pmid}`, record.journal, record.year].filter(Boolean).join(' · ')

  return <fieldset className="manuscript-reference-option">
    <legend>{record.title || t('题名未提供')}</legend>
    <p className="muted">{publication}</p>
    {item.selection.status === 'shortlisted' && <p>{t('已入选')}</p>}
    {excluded && <p>{t('人工排除')}</p>}
    {selected && !listedSelection && <div className="manuscript-reference-saved">
      <strong>{t('已选原文摘录')}</strong>
      <p className="manuscript-reference-text">{selected.quote}</p>
      <button type="button" disabled={disabled} onClick={onRemove}>{t('移除此摘录')}</button>
    </div>}
    {paragraphs.size === 0 && <p>{t(record.abstract_status === 'not_returned' ? '摘要未返回' : '摘要为空')}</p>}
    {Array.from(paragraphs.values(), ({ label, text }) => <div key={text}>
      {characterCount(text) > maxQuoteLength && !excluded ? <>
        {label && <strong>{label}</strong>}
        <LongAbstractExcerpt text={text} selectedQuote={selectedQuote} disabled={disabled} onChoose={onChoose} />
      </> : <label className="manuscript-reference-choice">
        <input type="checkbox" checked={!excluded && selectedQuote === text} disabled={disabled || excluded}
          onChange={() => onChoose(text)} />
        <span className="manuscript-reference-text">{label && <strong>{label} · </strong>}{text}</span>
      </label>}
    </div>)}
  </fieldset>
}

function ReferencePage({ projectId, active, disabled, selected, onChange, onFindLiterature }: Props) {
  const { t } = useI18n()
  const heading = useId()
  const [page, setPage] = useState(1)
  const [shortlisted, setShortlisted] = useState(false)
  const [retry, setRetry] = useState(0)
  const params = new URLSearchParams({ page: String(page) })
  if (shortlisted) params.set('selection', 'shortlisted')
  const url = active ? `${basePath(projectId)}/references?${params}` : null
  const records = useEvidenceResource<Page<Reference>>(url,
    value => validPage(value, projectId, page, row => validReference(row, projectId)), retry, () => undefined)

  function remove(id: string) {
    onChange(selected.filter(entry => entry.project_reference_id !== id))
  }
  function choose(item: Reference, quote: string) {
    const current = selected.find(entry => entry.project_reference_id === item.id)
    if (current?.search_id === item.source.search_id && current.quote === quote) {
      remove(item.id)
      return
    }
    const next = { project_reference_id: item.id, search_id: item.source.search_id, quote }
    onChange(current ? selected.map(entry => entry === current ? next : entry) : [...selected, next])
  }
  if (!active) return null
  return <section className="manuscript-reference-picker" aria-labelledby={heading}>
    <div className="manuscript-reference-heading">
      <h4 id={heading}>{t('选用文献摘要')}</h4>
      <span aria-live="polite">{t('已选 {count} / {limit} 篇', { count: selected.length, limit: maxReferences })}</span>
      {onFindLiterature && <button type="button" className="button-quiet" disabled={disabled} onClick={onFindLiterature}>{t('查找文献')}</button>}
    </div>
    <label className="manuscript-reference-filter">{t('筛选候选状态')}
      <select value={shortlisted ? 'shortlisted' : ''} onChange={event => { setPage(1); setShortlisted(event.target.value === 'shortlisted') }}>
        <option value="">{t('全部候选')}</option><option value="shortlisted">{t('已入选')}</option>
      </select>
    </label>
    {records.loading && <p role="status">{t('正在读取候选文献……')}</p>}
    {records.error && <div>
      <p role="alert">{t(records.error)}</p>
      <button type="button" onClick={() => setRetry(version => version + 1)}>{t('重试')}</button>
    </div>}
    {records.data && <>
      {records.data.total === 0 ? <p>{t(shortlisted ? '此项目暂无已入选的文献。' : '此项目还没有保存的候选文献。')}</p> : <>
        <p>{t('核对摘要后勾选要用于写作的原文，每篇可选一段。')}</p>
        <div className="manuscript-reference-list" role="region" tabIndex={0} aria-label={t('项目候选文献')}>
          {records.data.items.map(item => {
            const current = selected.find(entry => entry.project_reference_id === item.id)
            return <ReferenceOption key={item.id + ':' + item.source.search_id} item={item} selected={current}
              disabled={disabled || (!current && selected.length >= maxReferences)}
              onChoose={quote => choose(item, quote)} onRemove={() => remove(item.id)} />
          })}
        </div>
      </>}
      {(records.data.total > records.data.page_size || page > 1) && <EvidencePagination page={page}
        total={records.data.total} size={records.data.page_size} onPage={setPage} label="候选文献分页" />}
    </>}
  </section>
}

export function ManuscriptReferencePicker(props: Props) {
  return <ReferencePage key={props.projectId} {...props} />
}
export default ManuscriptReferencePicker

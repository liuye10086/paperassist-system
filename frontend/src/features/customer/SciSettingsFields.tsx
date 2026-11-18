import { useId } from 'react'
import { useI18n } from '../../shared/i18n'
import PaperKeywordFields from './PaperKeywordFields'
import { LegacySciHistory } from './SciSettingsSummary'
import { articleTypes, journalChoices, type SciSettingsDraft } from './sciProjectSettings'

type Props = {
  draft: SciSettingsDraft
  disabled: boolean
  onChange: (draft: SciSettingsDraft) => void
  onError: (message: string) => void
}

function moveRow<T>(rows: T[], index: number, offset: number) {
  const reordered = [...rows]
  const [row] = reordered.splice(index, 1)
  reordered.splice(index + offset, 0, row)
  return reordered
}

function RowActions({ index, count, onMove, onRemove }: {
  index: number; count: number; onMove: (offset: number) => void; onRemove: () => void
}) {
  const { t } = useI18n()
  return <div className="sci-inline-controls">
    {index > 0 && <button type="button" className="button-quiet" onClick={() => onMove(-1)}>{t('上移')}</button>}
    {index + 1 < count && <button type="button" className="button-quiet" onClick={() => onMove(1)}>{t('下移')}</button>}
    <button type="button" className="button-quiet" onClick={onRemove}>{t('移除')}</button>
  </div>
}

export default function SciSettingsFields({ draft, disabled, onChange, onError }: Props) {
  const { t } = useI18n()
  const journalName = useId()
  const choice = draft.target_journal.choice
  const { figure_findings, review_sections } = draft

  return <fieldset className="sci-settings-fields" disabled={disabled}>
    <label>{t('论文类型')}<select required value={draft.article_type}
      onChange={event => onChange({ ...draft, article_type: event.target.value as SciSettingsDraft['article_type'] })}>
      <option value="">{t('请选择论文类型')}</option>
      {Object.entries(articleTypes).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
    </select></label>
    <label>{t('拟定论文题目')}<input required maxLength={200} value={draft.proposed_title}
      onChange={event => onChange({ ...draft, proposed_title: event.target.value })} /></label>
    <fieldset className="sci-journal-field">
      <legend>{t('目标期刊')}</legend>
      <div className="sci-inline-controls">
        {Object.entries(journalChoices).map(([value, label]) => <label key={value}>
          <input type="radio" name={journalName} required checked={choice === value} value={value}
            onChange={() => onChange({ ...draft, target_journal: { choice: value as keyof typeof journalChoices, name: '' } })} />
          {t(label)}
        </label>)}
      </div>
      {(choice === 'other' || choice === 'nature_subjournal') && <label>{t('期刊名称')}
        <input required value={draft.target_journal.name} maxLength={200}
          onChange={event => onChange({ ...draft, target_journal: { ...draft.target_journal, name: event.target.value } })} />
      </label>}
    </fieldset>
    <PaperKeywordFields draft={draft} onChange={value => onChange({ ...draft, ...value })} onError={onError} />
    {draft.article_type === 'research' && <fieldset className="sci-content-list">
      <legend>{t('填写主要发现')}</legend>
      <p className="muted">{t('上传后将图表关联到对应发现。稿件按实际入稿图件编号。')}</p>
      {figure_findings.map((item, index) => <fieldset key={item.id} className="sci-content-item">
        <legend>{t('发现 {number}', { number: index + 1 })}</legend>
        <label>{t('主要发现')}<textarea required value={item.finding} rows={2} maxLength={20000}
          onChange={event => onChange({ ...draft, figure_findings: figure_findings.map(row =>
            row.id === item.id ? { ...row, finding: event.target.value } : row) })} /></label>
        <RowActions index={index} count={figure_findings.length}
          onMove={offset => onChange({ ...draft, figure_findings: moveRow(figure_findings, index, offset) })}
          onRemove={() => onChange({ ...draft, figure_findings: figure_findings.filter(row => row.id !== item.id) })} />
      </fieldset>)}
      <button type="button" onClick={() => onChange({ ...draft, figure_findings: [...figure_findings, { id: crypto.randomUUID(), finding: '' }] })}>
        {t('添加发现')}
      </button>
    </fieldset>}
    {draft.article_type === 'narrative_review' && <fieldset className="sci-content-list">
      <legend>{t('按小标题填写综述内容')}</legend>
      <p className="muted">{t('小标题会用于成稿，请使用拟写作的语种。')}</p>
      {review_sections.map((item, index) => <fieldset key={item.id} className="sci-content-item">
        <legend>{t('小标题 {number}', { number: index + 1 })}</legend>
        <label>{t('小标题')}<input required value={item.heading} maxLength={200}
          onChange={event => onChange({ ...draft, review_sections: review_sections.map(row =>
            row.id === item.id ? { ...row, heading: event.target.value } : row) })} /></label>
        <label>{t('需要涵盖的内容')}<textarea required value={item.content} rows={2} maxLength={20000}
          onChange={event => onChange({ ...draft, review_sections: review_sections.map(row =>
            row.id === item.id ? { ...row, content: event.target.value } : row) })} /></label>
        <RowActions index={index} count={review_sections.length}
          onMove={offset => onChange({ ...draft, review_sections: moveRow(review_sections, index, offset) })}
          onRemove={() => onChange({ ...draft, review_sections: review_sections.filter(row => row.id !== item.id) })} />
      </fieldset>)}
      <button type="button" onClick={() => onChange({ ...draft, review_sections: [...review_sections, { id: crypto.randomUUID(), heading: '', content: '' }] })}>
        {t('添加小标题')}
      </button>
    </fieldset>}
    {draft.legacy_draft && <LegacySciHistory settings={draft.legacy_draft} heading="原建项草稿" />}
  </fieldset>
}

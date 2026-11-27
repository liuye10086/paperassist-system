import { useId } from 'react'
import { useI18n } from '../../shared/i18n'
import PaperKeywordFields from './PaperKeywordFields'
import { LegacySciHistory } from './SciSettingsSummary'
import { articleTypes, journalPresetRows, type SciSettingsDraft } from './sciProjectSettings'

const journalRows = [...journalPresetRows, ['other']] as const

type Props = {
  draft: SciSettingsDraft
  disabled: boolean
  onChange: (draft: SciSettingsDraft) => void
  onError: (message: string) => void
}

export default function SciSettingsFields({ draft, disabled, onChange, onError }: Props) {
  const { t } = useI18n()
  const journalLabel = useId()
  const journal = draft.target_journal
  const customJournal = journal.selection === 'other'
  const findings = draft.figure_findings
  return <fieldset className="sci-settings-fields" disabled={disabled}>
    <label>{t('论文类型')}<select required value={draft.article_type}
      onChange={event => onChange({ ...draft, article_type: event.target.value as SciSettingsDraft['article_type'] })}>
      <option value="" disabled hidden>{t('请选择论文类型')}</option>
      {Object.entries(articleTypes).map(([value, name]) => <option key={value} value={value}>{t(name)}</option>)}
    </select></label>
    <label className="sci-settings-title">{t('拟定论文题目')}<input required maxLength={200} value={draft.proposed_title}
      onChange={event => onChange({ ...draft, proposed_title: event.target.value })} /></label>
    <PaperKeywordFields draft={draft} onChange={value => onChange({ ...draft, ...value })} onError={onError} />
    <div className="sci-journal-field">
      <span id={journalLabel}>{t('目标期刊')}</span>
      <div className="sci-journal-options" role="group" aria-labelledby={journalLabel}>
        {journalRows.map(row => <div className="sci-inline-controls" key={row[0]}>
          {row.map(option => <div className="sci-journal-option" key={option}>
            <label>
              <input type="radio" name={journalLabel} value={option} checked={journal.selection === option} required
                onChange={() => onChange({ ...draft, target_journal: { ...journal, selection: option } })} />
              {option === 'other' ? t('其他期刊') : option}
            </label>
            {option === 'other' && <input className="sci-journal-name" aria-label={t('期刊名称')} placeholder={t('期刊名称')} maxLength={200}
              required={customJournal} disabled={!customJournal} value={customJournal ? journal.customName : ''}
              onChange={event => onChange({ ...draft, target_journal: { ...journal, customName: event.target.value } })} />}
          </div>)}
        </div>)}
      </div>
    </div>
    {draft.article_type === 'research' && (findings.length ? findings : [null]).map((finding, index) =>
      <label key={index}>{t(findings.length > 1 ? '发现 {number}' : '主要结果（可稍后补充）', { number: index + 1 })}
        <textarea rows={3} maxLength={20000} value={finding?.finding ?? ''} onChange={event => {
          const text = event.target.value
          const rows = finding ? findings.map((row, i) => i === index ? { ...row, finding: text } : row)
            : [{ id: crypto.randomUUID(), finding: text }]
          onChange({ ...draft, figure_findings: rows })
        }} />
      </label>)}
    {draft.legacy_draft && <LegacySciHistory settings={draft.legacy_draft} heading="原建项草稿" />}
  </fieldset>
}

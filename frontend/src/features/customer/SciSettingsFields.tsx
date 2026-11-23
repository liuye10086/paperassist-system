import { useI18n } from '../../shared/i18n'
import PaperKeywordFields from './PaperKeywordFields'
import { LegacySciHistory } from './SciSettingsSummary'
import { articleTypes, type SciSettingsDraft } from './sciProjectSettings'

type Props = {
  draft: SciSettingsDraft
  disabled: boolean
  onChange: (draft: SciSettingsDraft) => void
  onError: (message: string) => void
}

export default function SciSettingsFields({ draft, disabled, onChange, onError }: Props) {
  const { t } = useI18n()
  const journal = draft.target_journal
  const findings = draft.figure_findings
  return <fieldset className="sci-settings-fields" disabled={disabled}>
    <label>{t('论文类型')}<select required value={draft.article_type}
      onChange={event => onChange({ ...draft, article_type: event.target.value as SciSettingsDraft['article_type'] })}>
      <option value="">{t('请选择论文类型')}</option>
      {Object.entries(articleTypes).map(([value, name]) => <option key={value} value={value}>{t(name)}</option>)}
    </select></label>
    <label>{t('拟定论文题目')}<input required maxLength={200} value={draft.proposed_title}
      onChange={event => onChange({ ...draft, proposed_title: event.target.value })} /></label>
    <PaperKeywordFields draft={draft} onChange={value => onChange({ ...draft, ...value })} onError={onError} />
    <label>{t('目标期刊（选填）')}<input maxLength={200} value={journal.choice === 'science' ? 'Science' : journal.name}
      onChange={event => {
        const name = event.target.value
        onChange({ ...draft, target_journal: { choice: name ? 'other' : '', name } })
      }} /></label>
    {draft.article_type === 'research' && (findings.length ? findings : [null]).map((finding, index) =>
      <label key={index}>{t(findings.length > 1 ? '发现 {number}' : '主要结果（可稍后补充）', { number: index + 1 })}
        <textarea rows={3} maxLength={20000} value={finding?.finding ?? ''} onChange={event => {
          const text = event.target.value
          const rows = finding ? findings.map((row, i) => i === index ? { ...row, finding: text } : row)
            : [{ id: crypto.randomUUID(), finding: text }]
          onChange({ ...draft, figure_findings: rows })
        }} />
      </label>)}
    {draft.article_type === 'narrative_review' && draft.review_sections.map((section, index) =>
      <label key={section.id}>{section.heading}<textarea maxLength={20000} rows={2} value={section.content}
        onChange={event => onChange({ ...draft, review_sections: draft.review_sections.map((row, i) =>
          i === index ? { ...row, content: event.target.value } : row) })} /></label>)}
    {draft.legacy_draft && <LegacySciHistory settings={draft.legacy_draft} heading="原建项草稿" />}
  </fieldset>
}

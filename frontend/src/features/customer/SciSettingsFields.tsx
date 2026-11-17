import { useId } from 'react'
import { useI18n } from '../../shared/i18n'
import { articleTypes, hasKeyword, journalChoices, MAX_FIGURE_PLANS, MAX_KEYWORDS, type SciSettingsDraft } from './sciProjectSettings'

type Props = {
  draft: SciSettingsDraft
  disabled: boolean
  onChange: (draft: SciSettingsDraft) => void
  onError: (message: string) => void
}

export default function SciSettingsFields({ draft, disabled, onChange, onError }: Props) {
  const { t } = useI18n()
  const journalName = useId()
  const choice = draft.target_journal.choice

  function addKeyword() {
    const keyword = draft.keywordInput.trim()
    if (!keyword || draft.keywords.length >= MAX_KEYWORDS) return
    if (hasKeyword(draft.keywords, keyword)) { onError('关键词已添加。'); return }
    onChange({ ...draft, keywords: [...draft.keywords, keyword], keywordInput: '' })
  }

  function changeFigure(index: number, field: 'title' | 'description', value: string) {
    onChange({ ...draft, figure_plan: draft.figure_plan.map((item, position) => position === index ? { ...item, [field]: value } : item) })
  }

  function moveFigure(index: number, offset: number) {
    const items = [...draft.figure_plan]
    const [item] = items.splice(index, 1)
    items.splice(index + offset, 0, item)
    onChange({ ...draft, figure_plan: items })
  }

  return <fieldset className="sci-settings-fields" disabled={disabled}>
    <label>{t('论文类型')}<select required value={draft.article_type}
      onChange={event => onChange({ ...draft, article_type: event.target.value as SciSettingsDraft['article_type'] })}>
      <option value="">{t('请选择论文类型')}</option>
      {Object.entries(articleTypes).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
    </select></label>
    <label>{t('主要结果或结论')}<textarea required rows={3} maxLength={20000} value={draft.main_results}
      onChange={event => onChange({ ...draft, main_results: event.target.value })} /></label>
    <fieldset className="sci-journal-field">
      <legend>{t('目标期刊')}</legend>
      <div className="sci-inline-controls">
        {Object.entries(journalChoices).map(([value, label]) => <label key={value}>
          <input type="radio" name={journalName} required checked={choice === value} value={value}
            onChange={() => onChange({ ...draft, target_journal: { choice: value as keyof typeof journalChoices, name: '' } })} />
          {t(label)}
        </label>)}
      </div>
      {(choice === 'other' || choice === 'nature_subjournal') && <label>{t(choice === 'other' ? '期刊名称' : '具体子刊名称（选填）')}
        <input required={choice === 'other'} value={draft.target_journal.name} maxLength={200}
          onChange={event => onChange({ ...draft, target_journal: { ...draft.target_journal, name: event.target.value } })} />
      </label>}
    </fieldset>
    <div className="sci-keywords">
      <div className="sci-inline-controls">
        <label>{t('关键词')}<input value={draft.keywordInput} maxLength={200} disabled={draft.keywords.length >= MAX_KEYWORDS}
          onChange={event => onChange({ ...draft, keywordInput: event.target.value })}
          onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); addKeyword() } }} /></label>
        <button type="button" onClick={addKeyword} disabled={!draft.keywordInput.trim() || draft.keywords.length >= MAX_KEYWORDS}>
          {t('添加关键词')}
        </button>
      </div>
      {draft.keywords.length > 0 && <ul className="sci-keyword-list">
        {draft.keywords.map((keyword, index) => <li key={keyword}>
          {keyword}<button type="button" className="button-quiet" aria-label={t('移除关键词 {keyword}', { keyword })}
            onClick={() => onChange({ ...draft, keywords: draft.keywords.filter((_, position) => position !== index) })}>×</button>
        </li>)}
      </ul>}
    </div>
    <fieldset className="sci-figure-plans">
      <legend>{t('图表计划（Figure plan）')}</legend>
      {draft.figure_plan.map((item, index) => <fieldset key={index} className="sci-figure-plan">
        <legend>{t('图表计划 {number}', { number: index + 1 })}</legend>
        <label>{t('图表标题')}<input required value={item.title} maxLength={200}
          onChange={event => changeFigure(index, 'title', event.target.value)} /></label>
        <label>{t('拟表达内容')}<textarea required value={item.description} rows={2} maxLength={2000}
          onChange={event => changeFigure(index, 'description', event.target.value)} /></label>
        <div className="sci-inline-controls">
          {index > 0 && <button type="button" className="button-quiet" onClick={() => moveFigure(index, -1)}>{t('上移')}</button>}
          {index + 1 < draft.figure_plan.length && <button type="button" className="button-quiet" onClick={() => moveFigure(index, 1)}>{t('下移')}</button>}
          <button type="button" className="button-quiet" onClick={() =>
            onChange({ ...draft, figure_plan: draft.figure_plan.filter((_, position) => position !== index) })}>{t('移除')}</button>
        </div>
      </fieldset>)}
      <button type="button" onClick={() => onChange({ ...draft, figure_plan: [...draft.figure_plan, { title: '', description: '' }] })}
        disabled={draft.figure_plan.length >= MAX_FIGURE_PLANS}>{t('添加图表计划')}</button>
    </fieldset>
  </fieldset>
}

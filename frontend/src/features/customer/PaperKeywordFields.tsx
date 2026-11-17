import { useId } from 'react'
import { useI18n } from '../../shared/i18n'
import { hasKeyword, MAX_KEYWORDS, type PaperKeywordDraft } from './paperKeywords'

export default function PaperKeywordFields({ draft, onChange, onError }: {
  draft: PaperKeywordDraft; onChange: (value: PaperKeywordDraft) => void; onError: (message: string) => void
}) {
  const { t } = useI18n()
  const keywordCount = useId()
  const { keywords, keywordInput } = draft
  const full = keywords.length >= MAX_KEYWORDS

  function addKeyword() {
    const keyword = keywordInput.trim()
    if (!keyword || full) return
    if (hasKeyword(keywords, keyword)) { onError('关键词已添加。'); return }
    onChange({ keywords: [...keywords, keyword], keywordInput: '' })
  }

  return <div className="paper-keywords">
    <div className="sci-inline-controls">
      <label>{t('关键词')}<input value={keywordInput} maxLength={200} disabled={full} aria-describedby={keywordCount}
        onChange={event => onChange({ keywords, keywordInput: event.target.value })}
        onKeyDown={event => {
          if (event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); addKeyword() }
        }} /></label>
      <button type="button" onClick={addKeyword} disabled={!keywordInput.trim() || full}>{t('添加关键词')}</button>
    </div>
    <p className="muted paper-keyword-count" id={keywordCount}>{t('已添加 {count} 个关键词，需填写 4 至 6 个。', { count: keywords.length })}</p>
    {keywords.length > 0 && <ul className="paper-keyword-list">
      {keywords.map((keyword, index) => <li key={keyword}>
        {keyword}<button type="button" className="button-quiet" aria-label={t('移除关键词 {keyword}', { keyword })}
          onClick={() => onChange({ keywordInput, keywords: keywords.filter((_, position) => position !== index) })}>×</button>
      </li>)}
    </ul>}
  </div>
}

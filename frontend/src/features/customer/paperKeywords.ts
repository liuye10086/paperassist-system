export const MAX_KEYWORDS = 6
const MIN_KEYWORDS = 4

export type PaperKeywordDraft = { keywords: string[]; keywordInput: string }

export function hasKeyword(keywords: string[], value: string) {
  return keywords.some(keyword => keyword.toLowerCase() === value.toLowerCase())
}

export function preparePaperKeywords({ keywords, keywordInput }: PaperKeywordDraft): { keywords: string[] } | { error: string } {
  const pending = keywordInput.trim()
  if (pending && hasKeyword(keywords, pending)) return { error: '关键词已添加。' }
  const values = pending ? [...keywords, pending] : keywords
  if (values.length < MIN_KEYWORDS || values.length > MAX_KEYWORDS) return { error: '请填写 4 至 6 个关键词。' }
  return { keywords: values }
}

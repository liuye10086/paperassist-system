import { useI18n } from '../../shared/i18n'
import type { Evidence } from '../literature/evidenceApi'
import type { LocalManifest } from './writingLiveTypes'

export const readingScopeLabels: Record<Evidence['reading_scope'], string> = {
  abstract: '摘要', pmc_fulltext: 'PMC 正文片段', user_material: '用户材料摘录',
}

type Props = {
  aliases?: string[]
  manifest: LocalManifest
  onUse?: (alias: string, quote: string) => void
  disabled?: boolean
}

export default function ParagraphReferenceExcerpts({ aliases, manifest, onUse, disabled }: Props) {
  const { t } = useI18n()
  const excerpts = (aliases ?? []).flatMap(alias => {
    const item = manifest.evidence[alias]
    const excerpt = item?.binding.evidence.find(e => e.id === item.evidence_id)
    return excerpt ? [{ alias, title: item.binding.metadata.title, excerpt }] : []
  })
  if (!excerpts.length) return null
  const heading = t('初稿为本段标出的文献')
  return <section aria-label={heading}>
    <h5>{heading}</h5>
    {excerpts.map(({ alias, title, excerpt }) => <div key={alias}>
      <p>{title} · {t(readingScopeLabels[excerpt.reading_scope])}</p>
      <blockquote>{excerpt.quote}</blockquote>
      {onUse && <button type="button" disabled={disabled} onClick={() => onUse(alias, excerpt.quote)}>{t('用这段原文核对')}</button>}
    </div>)}
  </section>
}

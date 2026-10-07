import type { Locale } from '../i18n'

/** Replace only names generated from this artifact's internal metadata. */
export function artifactFilename(filename: string, kind: 'figure' | 'report', id: string, revision: number, locale: Locale): string {
  if (kind === 'figure' && filename === `boxplot-${id}.png`) return 'boxplot.png'
  if (kind === 'report' && filename === `分析报告-v${revision}-${id.slice(0, 8)}.docx`) return locale === 'en' ? 'analysis-report.docx' : '分析报告.docx'
  return filename
}

import type { Locale } from '../i18n'

/** Replace only names generated from this artifact's internal metadata. */
export function artifactFilename(filename: string, kind: 'figure' | 'report', id: string, revision: number|null, locale: Locale): string {
  if (kind === 'figure')for(const type of ['boxplot','group_boxplot','paired_connected','scatter','correlation_heatmap','line','bar','violin','forest','roc_curve','kaplan_meier'])if(filename===`${type}-${id}.png`)return `${type}.png`
  if (kind === 'report' && filename === `分析报告-v${revision}-${id.slice(0, 8)}.docx`) return locale === 'en' ? 'analysis-report.docx' : '分析报告.docx'
  return filename
}

export const readerEngine = 'statistics_reader_report_v1'
export const readerPolicy = 'statistics_reader_export_v1'
export const wordSha = 'a'.repeat(64)

export function readerProjection(taskType: 'word_report' | 'collection_word_report', taskId: string, version = 'formal-report', titles = ['Fixed result panel']) {
  const reader_export = {
    policy: readerPolicy, context_id: 'fixed-context', report_version_id: version, task_id: taskId,
    task_type: taskType, origin: 'saved_explanation_reuse', adapter_version: 'statistics_saved_explanation_v1',
  } as const
  const members = (['docx', 'xlsx', 'zip'] as const).map((role, index) => ({
    id: role + '-member', key: ['analysis', 'results', 'analysis_package'][index],
    role, format: role, sha256: index === 0 ? wordSha : String(index).repeat(64), size_bytes: 200,
    download_url: `/api/v1/projects/p1/research-reports/${version}/members/${role}-member/download`,
  }))
  const reader_report = {
    origin: 'saved_explanation_reuse',
    narrative: {
      abstract: 'Fixed results for this report.', design_and_data: 'Saved observations.',
      quality_control: 'Three eligible records.', methods_summary: 'Matched methods.',
      key_findings: 'Median of one.', limitations: 'Limited to selected records.', reader_cautions: 'Review the complete table.',
    },
    figures: titles.map((title, index) => ({
      number: index + 1, title, reading: 'Read the axes.', observations: 'Three observations.',
      interpretation: 'Descriptive evidence.', limitations: 'Review image details.', caption: 'Saved figure caption.',
    })),
  }
  return { reader_export, members, reader_report }
}

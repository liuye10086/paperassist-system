import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import { useI18n } from '../../shared/i18n'
import { RESEARCH_TIMEOUT_MS } from '../research-results/api'
import type { ReaderExportFiles } from './statisticsReaderExport'

const labels = {
  docx: '下载 Word 报告',
  xlsx: '下载 XLSX 结果表',
  zip: '下载复现资料（ZIP）',
} as const

export default function StatisticsReportDownloads({ files, filename, includeWord = true }: { files: ReaderExportFiles; filename: string; includeWord?: boolean }) {
  const { t } = useI18n()
  const title = filename.replace(/\.docx$/i, '')
  return <ul className="research-member-list">
    {(['docx', 'xlsx', 'zip'] as const).filter(role => includeWord || role !== 'docx').map(role => {
      const member = files.members.find(member => member.role === role)!
      return <li key={member.id}>
        <ProjectDownloadLink href={member.download_url} filename={`${title}.${role}`} timeoutMs={RESEARCH_TIMEOUT_MS}>
          {t(labels[role])}
        </ProjectDownloadLink>
      </li>
    })}
  </ul>
}

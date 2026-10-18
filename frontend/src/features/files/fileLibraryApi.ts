import { apiFetch } from '../../shared/api/client'
import { apiError } from '../../shared/i18n'

export const purposeLabels = {
  raw_data: '原始数据', figure: '图表资料', methods: '方法资料', school_template: '学校模板',
  paper: '论文', revision_material: '修订材料',
} as const
export type FilePurpose = keyof typeof purposeLabels
export type ProjectFile = {
  id: string; filename: string; file_type: string; size_bytes: number; uploaded_at: string
  parse_status: 'queued' | 'parsing' | 'parsed' | 'failed'; parse_revision?: number; error: { code: string; message: string } | null
}
export type UploadBatchSummary = { created_at: string; item_count: number; item_position: number }
export type LibraryFile = ProjectFile & { purposes: FilePurpose[]; metadata_revision: number; uploader_recorded: boolean; upload_batch?: UploadBatchSummary | null }
export type FilePage = { items: LibraryFile[]; total: number; page: number; page_size: number }
const originalReferenceLabels = {
  analysis_setups: '分析配置引用', analysis_runs: '统计分析引用', figures: '图表引用', explanations: '结果解释引用', reports: 'Word 报告引用',
  structure_versions: '结构版本记录', dataset_versions: '原始数据版本记录', prepared_dataset_versions: '整理数据版本记录', tasks: '任务引用', legacy_jobs: '历史作业', active_tasks: '在途任务', recovery_candidates: '恢复候选',
} as const
export const referenceLabels = { ...originalReferenceLabels, prepared_dataset_derivations: '质量派生与回执' } as const
export type FileDetail = LibraryFile & {
  source: { kind: 'legacy_excel' | 'excel_parse' | 'docx_parse' | 'pdf_parse' | 'ocr_parse'; preview_available: boolean; preview_row_limit: 20 | null; parser_version: string | null }
  references: Record<keyof typeof originalReferenceLabels, number> & { prepared_dataset_derivations?: number }
  retention: { policy: 'internal_testing_keep'; automatic_deletion: false; deletion_available: false }
}

// Purposes and their revision belong to one snapshot. A late read may still refresh
// other fields, but must never replace a newer confirmed metadata snapshot.
export function mergeFileMetadata<T extends LibraryFile>(incoming: T, current?: LibraryFile | null): T {
  if (!current || current.id !== incoming.id) return incoming
  let merged = incoming
  if (current.metadata_revision > incoming.metadata_revision) merged = { ...merged, purposes: current.purposes, metadata_revision: current.metadata_revision }
  if ((current.parse_revision ?? 0) > (incoming.parse_revision ?? 0)) {
    merged = { ...merged, parse_status: current.parse_status, parse_revision: current.parse_revision, error: current.error }
    if ('source' in incoming && 'source' in current) merged = { ...merged, source: current.source }
  }
  return merged
}

export async function fileRequest<T>(url: string, signal: AbortSignal, onUnavailable: () => void, init?: RequestInit): Promise<T> {
  async function read(): Promise<T> {
    const response = await apiFetch(url, { ...init, signal })
    const result = await response.json().catch(() => null)
    if (signal.aborted) throw new DOMException('Request aborted', 'AbortError')
    if (response.status === 401 || response.status === 403 ||
      (response.status === 404 && result?.detail?.code === 'project_not_found')) {
      onUnavailable()
      throw new DOMException('Project unavailable', 'AbortError')
    }
    if (!response.ok) throw Object.assign(new Error(response.status === 409 && result?.detail?.code === 'file_metadata_conflict'
      ? '文件用途已被更新，请重新读取后核对草稿再保存。' : apiError(result, '文件请求失败，请重试。')), { status: response.status, code: result?.detail?.code })
    return result
  }
  let abort!: () => void
  const cancelled = new Promise<never>((_resolve, reject) => {
    abort = () => reject(new DOMException('Request aborted', 'AbortError'))
    if (signal.aborted) abort()
    else signal.addEventListener('abort', abort, { once: true })
  })
  try { return await Promise.race([read(), cancelled]) }
  finally { signal.removeEventListener('abort', abort) }
}

export const parseStatusLabels = { queued: '已保存，等待解析', parsing: '文件解析中', parsed: '可预览', failed: '解析失败' }

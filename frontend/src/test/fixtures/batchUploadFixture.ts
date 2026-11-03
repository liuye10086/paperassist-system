import type { UploadBatch } from '../../features/files/batchUploadApi'

// Exercise the batch API while reusing each integration test's file-store fixture.
export function batchUploadFixture(projectId: string, save: () => { id: string; parse_status?: string; error?: { code: string; message: string } | null }) {
  const base = `/api/v1/projects/${projectId}/file-batches`
  let batch: UploadBatch | null = null
  return (url: string, init?: RequestInit): Response | undefined => {
    if (url === base && init?.method === 'POST') {
      const body = JSON.parse(String(init.body)) as { items: { client_id: string; filename: string; size_bytes: number }[] }
      batch = { id: 'b1', project_id: projectId, created_at: '2026-11-03T00:00:00Z', revision: 1,
        items: body.items.map((item, ordinal) => ({ id: item.client_id, ordinal, filename: item.filename,
          size_bytes: item.size_bytes, status: 'pending', file_id: null, task: null, error: null })) }
      return Response.json(batch)
    }
    if (url.startsWith(`${base}/b1/items/`) && init?.method === 'POST' && batch) {
      const file = save()
      const item = batch.items.find(item => url.endsWith(`/${item.id}`))!
      Object.assign(item, { file_id: file.id, status: file.parse_status === 'failed' ? 'failed' : 'parsed', error: file.error ?? null })
      batch.revision++
      return Response.json(item)
    }
    if (url === `${base}/b1`) return Response.json(batch)
    if (url.startsWith(`${base}?`)) return Response.json({ items: batch ? [batch] : [], total: batch ? 1 : 0, page: 1, page_size: 5 })
  }
}

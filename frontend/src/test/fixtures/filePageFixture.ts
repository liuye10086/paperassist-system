export function filePageFixture<T extends object>(url: string, files: T[]) {
  const query = new URL(url, 'http://localhost').searchParams
  const page = Number(query.get('page'))
  const pageSize = Number(query.get('page_size'))
  return { items: files.slice((page - 1) * pageSize, page * pageSize).map(file => ({
    ...file, purposes: [], metadata_revision: 1, uploader_recorded: false,
  })), total: files.length, page, page_size: pageSize }
}

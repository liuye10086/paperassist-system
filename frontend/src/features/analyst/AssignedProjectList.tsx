import { useState } from 'react'
import ProjectList, { type ProjectListQuery } from '../projects/ProjectList'
import { PROJECT_PAGE_SIZE, isProjectPage, type ProjectPage } from '../projects/projectTypes'
import { useResearchRead } from '../research-results/api'

export default function AssignedProjectList({ onOpen }: { onOpen: (id: string) => void }) {
  const [query, setQuery] = useState<ProjectListQuery>({ page: 1, q: '', type: '' })
  const [searchDraft, setSearchDraft] = useState('')
  const params = new URLSearchParams({ page: String(query.page), page_size: String(PROJECT_PAGE_SIZE) })
  if (query.q) params.set('q', query.q)
  if (query.type) params.set('type', query.type)
  const read = useResearchRead<ProjectPage>(`/api/v1/assigned-projects?${params}`, true)
  const page = isProjectPage(read.data, query.page) ? read.data : null
  const last = Math.max(1, Math.ceil((page?.total ?? 0) / PROJECT_PAGE_SIZE))
  if (page && query.page > last) setQuery({ ...query, page: last })
  const error = read.error || (read.data && !page ? '项目列表格式不正确。' : '')
  return <ProjectList items={error ? [] : page?.items ?? []} total={page?.total ?? 0} query={query} searchDraft={searchDraft}
    loading={read.loading || !read.data && !error} error={error} onSearchDraftChange={setSearchDraft} onQueryChange={setQuery}
    onOpen={onOpen} onRetry={read.refresh} emptyMessage="目前没有分配给你的项目。"/>
}

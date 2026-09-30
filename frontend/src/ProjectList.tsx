import { typeNames, type Project } from './projectTypes'

export type ProjectListQuery = {
  page: number
  pageSize: 10 | 20 | 50
  q: string
  type: '' | Project['project_type']
}

type ProjectListProps = {
  items: Project[]
  total: number
  query: ProjectListQuery
  searchDraft: string
  loading: boolean
  error: string
  onSearchDraftChange: (value: string) => void
  onQueryChange: (query: ProjectListQuery) => void
  onOpen: (projectId: string) => void
  onRetry: () => void
  onCreate: () => void
}

export default function ProjectList({ items, total, query, searchDraft, loading, error,
  onSearchDraftChange, onQueryChange, onOpen, onRetry, onCreate }: ProjectListProps) {
  const pages = Math.max(1, Math.ceil(total / query.pageSize))
  const filtered = Boolean(query.q || query.type)

  function clearFilters() {
    onSearchDraftChange('')
    onQueryChange({ ...query, page: 1, q: '', type: '' })
  }

  return <section className="project-list" aria-label="项目列表区域" aria-busy={loading}>
    <form className="project-list-filters" onSubmit={event => {
      event.preventDefault()
      onQueryChange({ ...query, page: 1, q: searchDraft.trim() })
    }}>
      <label>搜索项目名称<input value={searchDraft} onChange={event => onSearchDraftChange(event.target.value)} maxLength={120} /></label>
      <button type="submit">搜索项目</button>
      <label>筛选项目类型<select value={query.type} onChange={event => onQueryChange({
        ...query, page: 1, type: event.target.value as ProjectListQuery['type'],
      })}>
        <option value="">全部类型</option><option value="sci">SCI 科研论文</option><option value="thesis">毕业论文</option>
      </select></label>
      <button type="button" onClick={clearFilters}>清除筛选</button>
    </form>
    {loading && <p role="status">正在读取项目列表……</p>}
    {error && <div className="error-panel" role="alert">{error}{' '}
      <button type="button" onClick={onRetry} disabled={loading}>重试项目列表</button>
    </div>}
    <div className="project-table-scroll">
      <table className="project-table">
        <caption>项目列表</caption>
        <thead><tr><th scope="col">项目名称</th><th scope="col">项目类型</th><th scope="col">创建时间</th>
          <th scope="col">最近更新时间</th><th scope="col">文件数</th><th scope="col">操作</th></tr></thead>
        <tbody>{items.map(project => <tr key={project.id}>
          <td>{project.name}</td><td>{typeNames[project.project_type]}</td>
          <td><time dateTime={project.created_at}>{new Date(project.created_at).toLocaleString('zh-CN')}</time></td>
          <td><time dateTime={project.updated_at}>{new Date(project.updated_at).toLocaleString('zh-CN')}</time></td>
          <td>{project.file_count}</td>
          <td><button type="button" aria-label={`打开项目 ${project.name}`} onClick={() => onOpen(project.id)}>打开项目</button></td>
        </tr>)}</tbody>
      </table>
    </div>
    {!loading && !error && total === 0 && <div className="empty-preview">
      {filtered ? <p>没有匹配的项目。</p> : <><p>还没有项目，请先创建一个项目。</p>
        <button type="button" onClick={onCreate}>新建项目</button></>}
    </div>}
    <div className="project-pagination">
      <label>每页项目数<select value={query.pageSize} onChange={event => onQueryChange({
        ...query, page: 1, pageSize: Number(event.target.value) as ProjectListQuery['pageSize'],
      })}>{[10, 20, 50].map(size => <option key={size} value={size}>{size}</option>)}</select></label>
      <span>共 {total} 个项目 · 第 {query.page} / {pages} 页</span>
      <button type="button" onClick={() => onQueryChange({ ...query, page: query.page - 1 })} disabled={loading || query.page <= 1}>上一页</button>
      <button type="button" onClick={() => onQueryChange({ ...query, page: query.page + 1 })} disabled={loading || query.page >= pages}>下一页</button>
    </div>
  </section>
}

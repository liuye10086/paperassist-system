import { typeNames, type Project } from './projectTypes'
import { useI18n } from './i18n'

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
  const { t, locale } = useI18n()
  const pages = Math.max(1, Math.ceil(total / query.pageSize))
  const filtered = Boolean(query.q || query.type)

  function clearFilters() {
    onSearchDraftChange('')
    onQueryChange({ ...query, page: 1, q: '', type: '' })
  }

  return <section className="project-list" aria-label={t("项目列表区域")} aria-busy={loading}>
    <form className="project-list-filters" onSubmit={event => {
      event.preventDefault()
      onQueryChange({ ...query, page: 1, q: searchDraft.trim() })
    }}>
      <label>{t("搜索项目名称")}<input value={searchDraft} onChange={event => onSearchDraftChange(event.target.value)} maxLength={120} /></label>
      <button type="submit">{t("搜索项目")}</button>
      <label>{t("筛选项目类型")}<select value={query.type} onChange={event => onQueryChange({
        ...query, page: 1, type: event.target.value as ProjectListQuery['type'],
      })}>
        <option value="">{t("全部类型")}</option><option value="sci">{t("SCI 科研论文")}</option><option value="thesis">{t("毕业论文")}</option>
      </select></label>
      <button type="button" onClick={clearFilters}>{t("清除筛选")}</button>
    </form>
    {loading && <p role="status">{t("正在读取项目列表……")}</p>}
    {error && <div className="error-panel" role="alert">{t(error)}{' '}
      <button type="button" onClick={onRetry} disabled={loading}>{t("重试项目列表")}</button>
    </div>}
    <div className="project-table-scroll">
      <table className="project-table">
        <caption>{t("项目列表")}</caption>
        <thead><tr><th scope="col">{t("项目名称")}</th><th scope="col">{t("项目类型")}</th><th scope="col">{t("创建时间")}</th>
          <th scope="col">{t("最近更新时间")}</th><th scope="col">{t("文件数")}</th><th scope="col">{t("操作")}</th></tr></thead>
        <tbody>{items.map(project => <tr key={project.id}>
          <td>{project.name}</td><td>{t(typeNames[project.project_type])}</td>
          <td><time dateTime={project.created_at}>{new Date(project.created_at).toLocaleString(locale)}</time></td>
          <td><time dateTime={project.updated_at}>{new Date(project.updated_at).toLocaleString(locale)}</time></td>
          <td>{project.file_count}</td>
          <td><button type="button" aria-label={t('打开项目 {name}', { name: project.name })} onClick={() => onOpen(project.id)}>{t("打开项目")}</button></td>
        </tr>)}</tbody>
      </table>
    </div>
    {!loading && !error && total === 0 && <div className="empty-preview">
      {filtered ? <p>{t("没有匹配的项目。")}</p> : <><p>{t("还没有项目，请先创建一个项目。")}</p>
        <button type="button" onClick={onCreate}>{t("新建项目")}</button></>}
    </div>}
    <div className="project-pagination">
      <label>{t("每页项目数")}<select value={query.pageSize} onChange={event => onQueryChange({
        ...query, page: 1, pageSize: Number(event.target.value) as ProjectListQuery['pageSize'],
      })}>{[10, 20, 50].map(size => <option key={size} value={size}>{size}</option>)}</select></label>
      <span>{t('共 {total} 个项目 · 第 {page} / {pages} 页', { total, page: query.page, pages })}</span>
      <button type="button" onClick={() => onQueryChange({ ...query, page: query.page - 1 })} disabled={loading || query.page <= 1}>{t("上一页")}</button>
      <button type="button" onClick={() => onQueryChange({ ...query, page: query.page + 1 })} disabled={loading || query.page >= pages}>{t("下一页")}</button>
    </div>
  </section>
}

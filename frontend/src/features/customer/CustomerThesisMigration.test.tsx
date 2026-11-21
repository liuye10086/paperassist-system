// B04 task 9 (D6): “迁移到新模板” on the template change preview changes the template first, then opens the migration
// page of that manuscript version with the new template preselected.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { manuscriptFixture, snapshotFixture } from '../manuscripts/manuscriptFixtures'
import CustomerWorkspace from './CustomerWorkspace'
import { customerManuscriptNavigation } from './customerPaperNavigation'

type Stub = { onAdopted?: (id: string) => void; onOpenMigration?: (manuscriptId: string, revision: number, confirmationId: string) => void }
vi.mock('../school-templates/SchoolTemplates', () => ({
  // Same order as SchoolTemplates: the adoption is reported first, then the migration opens.
  default: ({ onAdopted, onOpenMigration }: Stub) => <div>
    <p>{onOpenMigration ? 'migration-wired' : 'migration-missing'}</p>
    <button type="button" onClick={() => { onAdopted?.('confirm2'); onOpenMigration?.('m1', 3, 'confirm2') }}>迁移到新模板</button>
  </div>,
}))

const project = {
  id: 'customer-thesis-9', name: '毕业论文样例', research_topic: '运动干预',
  project_type: 'thesis', file_count: 0, created_at: '2026-11-11T00:00:00Z', updated_at: '2026-11-11T00:00:00Z',
}
const base = '/api/v1/projects/' + project.id
const chapters = [{ id: 'c1', title: '第二章 研究方法', level: 1, purpose: 'materials_and_methods', output_language: 'zh-CN', result_group_ids: [] }]
const profile = { revision: 2, school: '测试学校', department: '', major: '', degree_type: '硕士', education_level: '研究生', applicable_version: '2026', bound_confirmation_id: 'confirm2' }
const thesisContext = { schema_version: 1, profile: { ...profile, bound_confirmation_id: 'confirm1' }, template_version_id: 'template1', confirmation_id: 'confirm1',
  confirmation_sha256: 'a'.repeat(64), confirmation: { id: 'confirm1', chapters: chapters.map(({ id, title, level }) => ({ id, title, level })) }, source_files: [], chapters }
const snapshot = { ...snapshotFixture, project_id: project.id, output_language: 'zh-CN', thesis_context: thesisContext,
  sections: chapters.map(c => ({ ...c, paragraphs: [{ id: 'c1:1', text: '学校方法正文', origin: 'user_provided', source_ids: [], citations: [] }] })),
  school_content_report: { rules_version: 'school_v1', issues: [], can_publish: true, scientifically_verified: false } }
const purposes = ['abstract', 'introduction', 'materials_and_methods', 'results', 'discussion', 'conclusion', 'references', 'acknowledgements', 'manual', 'other']
const readiness = { ready: true, blocking_reasons: [], profile, confirmation_id: 'confirm2', chapters: chapters.map(({ id, title, level }) => ({ id, title, level })),
  purposes, template_source_file_ids: [] }
const versions = [3, 2, 1].map(revision => ({ ...manuscriptFixture.versions[0], id: 'v' + revision, revision, parent_version_id: revision > 1 ? 'v' + (revision - 1) : null,
  created_at: `2026-11-1${revision}T08:00:00Z`, snapshot, exports: [] }))
const manuscript = { ...manuscriptFixture, project_id: project.id, title: '毕业论文初稿', current_revision: 3, versions }
function serve() {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === base) return Response.json(project)
    if (url === base + '/thesis-profile') return Response.json(profile)
    if (url === base + '/manuscripts/m1/versions/3/exports' && init?.method === 'POST')
      return Response.json({ detail: { code: 'task_source_conflict' } }, { status: 409 })
    if (url === base + '/manuscripts') return Response.json({ items: [manuscript] })
    if (url === base + '/manuscripts/candidates') return Response.json({ items: [], citation_drafts: [], methods_fields: [], project_type: 'thesis', thesis: readiness })
    if (url === base + '/manuscripts/m1/school-changes') return Response.json({ items: [] })
    if (url === base + '/school-templates') return Response.json({ items: [
      { id: 't1', name: '旧模板', version_label: '2025', confirmation: { id: 'confirm1' } },
      { id: 't2', name: '学校 2026 模板', version_label: '2026', confirmation: { id: 'confirm2' } },
      { id: 't3', name: '学院模板', version_label: '2026', confirmation: { id: 'confirm3' } }] })
    if (/\/manuscripts\/m1\/versions\/\d+\/exports$/.test(url)) return Response.json({ items: [] })
    return new Response(null, { status: 404 })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}
const migration = '#' + new URLSearchParams({ 'customer-project': project.id, step: 'manuscripts', manuscript: 'm1', revision: '3', view: 'school', target: 'confirm2' }).toString()

beforeEach(() => {
  setApiSession('csrf', 'customer-test')
  sessionStorage.clear()
})
afterEach(() => {
  cleanup()
  clearApiSession()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', window.location.pathname)
})

it('opens the migration of the affected version with the new template preselected', async () => {
  serve()
  window.history.replaceState(null, '', `#customer-project=${project.id}&step=school`)
  render(<CustomerWorkspace />)
  expect(await screen.findByText('migration-wired')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '迁移到新模板' }))
  await waitFor(() => expect(window.location.hash).toBe(migration))
  const select = await screen.findByLabelText('选择新模板') as HTMLSelectElement
  await waitFor(() => expect(select.value).toBe('confirm2'))
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: '开始迁移' })))
  expect(screen.getByText('已下载的 Word 保持原样；第 3 版要按新模板导出，需要先把稿件迁移到新模板。')).toBeTruthy()
  const page = screen.getByRole('region', { name: '模板迁移' })
  expect(page.textContent).not.toMatch(/历史稿继续使用原模板|父版本|固定版本|登记|版本输入|匹配并另存|对应章节/)
  expect(page.querySelectorAll('details')).toHaveLength(0)
  // Preselecting is not an edit: a step click leaves without asking to discard anything.
  const confirm = vi.spyOn(window, 'confirm')
  fireEvent.click(screen.getAllByRole('button', { name: /学校模板/ })[0])
  await waitFor(() => expect(new URLSearchParams(window.location.hash.slice(1)).get('step')).toBe('school'))
  expect(confirm).not.toHaveBeenCalled()
})

it('lets the migration win over a chapter return token', async () => {
  serve()
  const origin = new URLSearchParams({ 'customer-project': project.id, step: 'manuscripts', view: 'materials', focus: 'chapters' }).toString()
  window.history.replaceState(null, '', '#' + new URLSearchParams({ 'customer-project': project.id, step: 'school', return: origin,
    returnLabel: 'chapter', returnChapter: '章节与复核' }).toString())
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '迁移到新模板' }))
  await waitFor(() => expect(window.location.hash).toBe(migration))
  await screen.findByLabelText('选择新模板')
  expect(window.location.hash).toBe(migration)
  // Back leads to the template page, not to a chapter return that was never followed.
  window.history.back()
  await waitFor(() => expect(new URLSearchParams(window.location.hash.slice(1)).get('step')).toBe('school'))
})

// Word page (B04 task 11): a version made under the previous template is refused; its migration button opens the same
// migration page as the template change preview, with the project's current template preselected.
it('opens the migration from the Word page when an old-template version is refused', async () => {
  serve()
  window.history.replaceState(null, '', '#' + new URLSearchParams({ 'customer-project': project.id, step: 'word', manuscript: 'm1', revision: '3', view: 'exports' }).toString())
  render(<CustomerWorkspace />)
  fireEvent.click(await screen.findByRole('button', { name: '生成 Word' }))
  expect(await screen.findByText('这一版用的是之前的学校模板。已下载的 Word 保持原样；要按新模板导出，需要先把稿件迁移到新模板。')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '迁移到新模板' }))
  await waitFor(() => expect(window.location.hash).toBe(migration))
  const select = await screen.findByLabelText('选择新模板') as HTMLSelectElement
  await waitFor(() => expect(select.value).toBe('confirm2'))
})

it('reads the migration target only on the template migration view', () => {
  const read = (query: string) => customerManuscriptNavigation(new URLSearchParams(query), false, true).target
  expect(read('manuscript=m1&revision=3&view=school&target=confirm2')).toBe('confirm2')
  expect(read('manuscript=m1&revision=3&view=body&target=confirm2')).toBeUndefined()
  expect(read('manuscript=m1&revision=3&view=school&target=not%20an%20id')).toBeUndefined()
  expect(read('view=school&target=confirm2')).toBeUndefined()
  expect(customerManuscriptNavigation(new URLSearchParams('manuscript=m1&revision=3&view=school&target=confirm2'), true, true).target).toBeUndefined()
})

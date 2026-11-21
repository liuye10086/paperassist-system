// B04 task 7: the B03 overwrite rule (D2) on a customer thesis: saving the writing materials again over a version
// that already has a written body asks first and names the next version.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ProjectManuscripts from './ProjectManuscripts'
import { candidatesFixture, inputFixture, manuscriptFixture, snapshotFixture } from './manuscriptFixtures'
import { rawSnapshot } from './writingLiveFixtures'
import type { ManuscriptInput } from './manuscriptTypes'

const base = '/api/v1/projects/p1/manuscripts'
const profile = { revision: 2, school: '测试学校', department: '', major: '', degree_type: '硕士', education_level: '研究生', applicable_version: '2026', bound_confirmation_id: 'confirm1' }
const chapters = [{ id: 'chapter-method', title: '第二章 方法', level: 1, purpose: 'materials_and_methods', output_language: 'zh-CN', result_group_ids: [] }]
const school = { schema_version: 1, profile, template_version_id: 'template1', confirmation_id: 'confirm1', confirmation_sha256: 'a'.repeat(64),
  confirmation: { id: 'confirm1', chapters: chapters.map(({ id, title, level }) => ({ id, title, level })) }, source_files: [], chapters }
const snapshot = { ...snapshotFixture, output_language: 'zh-CN', thesis_context: school,
  sections: chapters.map(c => ({ ...c, paragraphs: [{ id: 'chapter-method:1', text: '方法正文', origin: 'user_provided', source_ids: [], citations: [] }] })),
  school_content_report: { rules_version: 'school_v1', issues: [], can_publish: true, scientifically_verified: false } }
const readiness = { ready: true, blocking_reasons: [], profile, confirmation_id: 'confirm1', chapters: chapters.map(({ id, title, level }) => ({ id, title, level })),
  purposes: ['abstract', 'introduction', 'materials_and_methods', 'results', 'discussion', 'conclusion', 'references', 'acknowledgements', 'manual', 'other'], template_source_file_ids: [] }
const input = { ...inputFixture, title: '毕业论文初稿', output_language: 'zh-CN',
  thesis: { confirmation_id: 'confirm1', profile_revision: 2, chapter_mappings: chapters.map(c => ({ chapter_id: c.id, purpose: c.purpose, output_language: c.output_language, result_group_ids: [] })) } }
const first = { ...manuscriptFixture.versions[0], input, snapshot, exports: [], created_at: '2026-11-19T07:40:00Z' }
const second = { ...first, id: 'v2', revision: 2, parent_version_id: 'v1', task_id: 'draft-2', created_at: '2026-11-19T09:10:00Z',
  snapshot: { ...snapshot, writing_provenance: { ...rawSnapshot.writing_provenance!, base_version_id: 'v1' } } }
const stored = { ...manuscriptFixture, title: '毕业论文初稿', current_revision: 2, versions: [first, second] }

beforeEach(() => {
  sessionStorage.clear()
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: { configurable: true, value(this: HTMLDialogElement) { this.open = true } },
    close: { configurable: true, value(this: HTMLDialogElement) { this.open = false } },
  })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear() })

it('asks before overwriting an adopted thesis version and names the next version', async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === `${base}/candidates`) return Response.json({ ...candidatesFixture, project_type: 'thesis', thesis: readiness })
    if (url === base && !init?.method) return Response.json({ items: [stored] })
    return Response.json({ items: [] })
  })
  vi.stubGlobal('fetch', fetcher)
  render(<ProjectManuscripts projectId="p1" researchTopic="学校研究" outputLanguage="zh-CN" active projectType="thesis"
    customerThesis={{ wordOnly: false }} view="materials" onViewChange={() => {}} onSelectVersion={() => {}} />)
  const save = await screen.findByRole('button', { name: '覆盖之前的写作材料' })
  await waitFor(() => expect(save.closest('fieldset')?.disabled).toBe(false))
  fireEvent.click(save)
  const dialog = await screen.findByRole('dialog', { name: '覆盖之前的写作材料？' })
  expect(dialog.textContent).toContain('保存后，这份稿件会按新材料更新为第 3 版。')
  fireEvent.click(within(dialog).getByRole('button', { name: '取消' }))
  expect(fetcher.mock.calls.filter(([url, init]) => init?.method === 'POST' && String(url).endsWith('/versions'))).toHaveLength(0)
  expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/writing-requests'))).toBe(false)
})

const savedPurposes = [
  ['声明', 'manual'], ['中文摘要', 'abstract'], ['英文摘要', 'abstract'], ['引言', 'introduction'],
  ['研究方法', 'other'], ['条件比较', 'results'], ['讨论', 'discussion'], ['结论', 'conclusion'],
  ['参考文献', 'references'], ['致谢', 'acknowledgements'], ['附录', 'manual'],
] as const
const currentChapters = savedPurposes.map(([title], index) => ({ id: 'c' + index, title, level: 1 }))
const savedMappings = savedPurposes.map(([, purpose], index) => ({
  chapter_id: currentChapters[index].id, purpose, output_language: index === 2 ? 'en' : 'project',
  result_group_ids: purpose === 'results' ? ['extra-results'] : [],
}))
const currentPlan = { kind: 'thesis', title: '新版毕业论文需求', keywords: [], materials: [], omitted_count: 0, token: 'b'.repeat(64),
  sections: [
    { id: 'plan-methods', chapter_id: 'c4', label: '研究方法', purpose: 'materials_and_methods', text: '说明方法' },
    { id: 'plan-results', chapter_id: 'c5', label: '条件比较', purpose: 'results', text: '报告结果' },
  ] }
function openSavedMaterials({ confirmation = 'confirm1', chapters: current = currentChapters, protectedPurposes = {} }: {
  confirmation?: string; chapters?: typeof currentChapters; protectedPurposes?: Record<string, string>
} = {}) {
  const currentSchool = { ...readiness, confirmation_id: confirmation,
    profile: { ...profile, revision: 3, bound_confirmation_id: confirmation }, chapters: current,
    protected_chapter_purposes: protectedPurposes }
  const savedInput = { ...input, thesis: { ...input.thesis, chapter_mappings: savedMappings },
    results_groups: [{ id: 'extra-results', title: '补充结果组', analysis_run_ids: [], figure_ids: [] }] }
  const savedChapters = currentChapters.map((chapter, index) => ({
    ...chapter, purpose: savedMappings[index].purpose,
    output_language: savedMappings[index].output_language === 'en' ? 'en' : 'zh-CN',
    result_group_ids: savedMappings[index].result_group_ids,
  }))
  const savedVersion = { ...second, id: 'v5', revision: 5, input: savedInput,
    snapshot: { ...second.snapshot,
      thesis_context: { ...school, confirmation: { ...school.confirmation, chapters: currentChapters }, chapters: savedChapters },
      sections: savedChapters.map(chapter => ({ ...chapter, paragraphs: [] })),
    } }
  const manuscript = { ...stored, current_revision: 5, versions: [savedVersion] }
  const writes: ManuscriptInput[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url === base + '/candidates') return Response.json({ ...candidatesFixture, project_type: 'thesis', thesis: currentSchool, paper_plan: currentPlan })
    if (url === base) return Response.json({ items: [manuscript] })
    if (url === base + '/m1/versions' && init?.method === 'POST') {
      const payload = JSON.parse(String(init.body))
      writes.push(payload)
      return Response.json({ ...manuscript, current_revision: 6, versions: [...manuscript.versions, { ...savedVersion, id: 'v6', revision: 6, input: payload }] })
    }
    return Response.json({ items: [] })
  }))
  const open = () => render(<ProjectManuscripts projectId="p1" researchTopic="学校研究" outputLanguage="zh-CN" active projectType="thesis"
    customerThesis={{ wordOnly: false }} view="materials" onViewChange={() => {}} />)
  return { page: open(), open, writes }
}
async function showChapterFields() {
  fireEvent.click(await screen.findByRole('button', { name: /章节配置/ }))
  await screen.findByRole('group', { name: '英文摘要' })
}
function chapterField(title: string, label: string) {
  return within(screen.getByRole('group', { name: title })).getByRole<HTMLSelectElement>('combobox', { name: label })
}

it('retains nine chapter choices when the requirements advance under the same school confirmation and saves with its current revision', async () => {
  const { page, open, writes } = openSavedMaterials()
  await showChapterFields()
  const editable = savedPurposes.filter(([title]) => !['研究方法', '条件比较'].includes(title))
  expect(editable.map(([title]) => chapterField(title, '内容用途').value)).toEqual(editable.map(([, purpose]) => purpose))
  expect(chapterField('英文摘要', '章节语言').value).toBe('en')
  expect(within(screen.getByRole('group', { name: '研究方法' })).getByText(/沿用已保存的写作要求/)).toBeTruthy()
  expect(within(screen.getByRole('group', { name: '条件比较' })).getByRole('checkbox', { name: '补充结果组' })).toHaveProperty('checked', true)
  fireEvent.change(chapterField('附录', '内容用途'), { target: { value: 'other' } })
  page.unmount()
  open()
  await showChapterFields()
  expect(chapterField('附录', '内容用途').value).toBe('other')
  expect(writes).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: '覆盖之前的写作材料' }))
  const dialog = await screen.findByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: '覆盖并保存' }))
  await waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0]).toMatchObject({ expected_revision: 5, paper_plan_token: currentPlan.token,
    thesis: { confirmation_id: 'confirm1', profile_revision: 3,
      chapter_mappings: savedMappings.map(mapping => {
        if (mapping.chapter_id === 'c4') return { ...mapping, purpose: 'materials_and_methods' }
        if (mapping.chapter_id === 'c5') return { ...mapping, result_group_ids: ['plan-results', 'extra-results'] }
        if (mapping.chapter_id === 'c10') return { ...mapping, purpose: 'other' }
        return mapping
      }) } })
})

it('enforces the current protected purpose and leaves a new chapter ID unselected even if its title matches a saved chapter', async () => {
  const reordered = [...currentChapters].reverse().map(chapter => chapter.id === 'c8' ? { ...chapter, id: 'new-reference-id' } : chapter)
  const { writes } = openSavedMaterials({ chapters: reordered, protectedPurposes: { c7: 'manual' } })
  await showChapterFields()
  const protectedChapter = within(screen.getByRole('group', { name: '结论' }))
  expect(protectedChapter.queryByRole('combobox', { name: '内容用途' })).toBeNull()
  expect(protectedChapter.getByText(/人工填写.*沿用学校模板确认的用途/)).toBeTruthy()
  expect(chapterField('参考文献', '内容用途').value).toBe('')
  expect(chapterField('英文摘要', '内容用途').value).toBe('abstract')
  fireEvent.click(screen.getByRole('button', { name: '覆盖之前的写作材料' }))
  expect(await screen.findByText('请逐章明确内容用途并核对当前学校确认版本。')).toBeTruthy()
  expect(writes).toHaveLength(0)
  fireEvent.change(chapterField('参考文献', '内容用途'), { target: { value: 'references' } })
  fireEvent.click(screen.getByRole('button', { name: '覆盖之前的写作材料' }))
  fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '覆盖并保存' }))
  await waitFor(() => expect(writes).toHaveLength(1))
  const submitted = writes[0].thesis!.chapter_mappings
  expect(submitted.map(mapping => mapping.chapter_id)).toEqual(reordered.map(chapter => chapter.id))
  expect(submitted.find(mapping => mapping.chapter_id === 'c7')).toMatchObject({ purpose: 'manual', result_group_ids: [] })
})

it('does not infer saved purposes or languages from reused chapter IDs after changing the school confirmation', async () => {
  const { writes } = openSavedMaterials({ confirmation: 'different-confirmation' })
  await showChapterFields()
  expect(chapterField('英文摘要', '内容用途').value).toBe('')
  expect(chapterField('英文摘要', '章节语言').value).toBe('project')
  expect(writes).toHaveLength(0)
})

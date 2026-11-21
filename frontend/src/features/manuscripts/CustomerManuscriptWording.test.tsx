// B05 task 10: the customer writing and confirmation pages speak to the customer — no internal eyebrow, review
// gates, paragraph identity, fixed versions or “protected” chapters. Staff pages keep their wording.
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { setLocale } from '../../shared/i18n'
import ProjectManuscripts from './ProjectManuscripts'
import CustomerWritingConfirm from './CustomerWritingConfirm'
import WritingBundlePreview from './WritingBundlePreview'
import WritingLive from './WritingLive'
import { candidatesFixture, manuscriptFixture, snapshotFixture } from './manuscriptFixtures'
import { bundleFixture } from './writingLiveFixtures'
import type { ManuscriptVersion, Snapshot } from './manuscriptTypes'

const base = '/api/v1/projects/p1/manuscripts'
const banned = /THESIS|显式发布|Results 分组|门禁|段落身份|固定版本|受保护/
const profile = { revision: 2, school: '测试学校', department: '', major: '', degree_type: '硕士', education_level: '研究生', applicable_version: '2026', bound_confirmation_id: 'confirm1' }
const chapters = [{ id: 'chapter-method', title: '第二章 方法', level: 1, purpose: 'materials_and_methods', output_language: 'zh-CN', result_group_ids: [] },
  { id: 'chapter-thanks', title: '致谢', level: 1, purpose: 'acknowledgements', output_language: 'zh-CN', result_group_ids: [] }]
const readiness = { ready: true, blocking_reasons: [], profile, confirmation_id: 'confirm1', chapters: chapters.map(({ id, title, level }) => ({ id, title, level })),
  purposes: ['abstract', 'introduction', 'materials_and_methods', 'results', 'discussion', 'conclusion', 'references', 'acknowledgements', 'manual', 'other'], template_source_file_ids: [] }
const savedAt = '2026-11-19T07:40:00Z'

afterEach(() => { cleanup(); setLocale('zh-CN'); vi.unstubAllGlobals(); sessionStorage.clear() })

function serve(thesis = false) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === `${base}/candidates`) return Response.json(thesis ? { ...candidatesFixture, project_type: 'thesis', thesis: readiness } : candidatesFixture)
    return Response.json({ items: [] })
  }))
}
const sci = { projectId: 'p1', researchTopic: '血清指标', outputLanguage: 'zh-CN' as const, active: true, projectType: 'sci' as const,
  customerSci: { settings: null, wordOnly: false }, view: 'materials' as const, onViewChange: () => {}, onSelectVersion: () => {} }
const thesis = { projectId: 'p1', researchTopic: '学校研究', outputLanguage: 'zh-CN' as const, active: true, projectType: 'thesis' as const,
  customerThesis: { wordOnly: false }, view: 'materials' as const, onViewChange: () => {}, onSelectVersion: () => {} }

it('shows the SCI customer materials pages in customer wording', async () => {
  serve()
  render(<ProjectManuscripts {...sci} />)
  await screen.findByRole('checkbox', { name: '固定统计结果' })
  expect(document.querySelector('.workspace-eyebrow')?.textContent).toBe('SCI')
  fireEvent.click(screen.getByRole('button', { name: /结果$/ }))
  expect(screen.getByRole('heading', { name: '结果分组' })).toBeTruthy()
  expect(screen.getByText('按你打算讨论的顺序排列结果和图表；调整顺序不会丢失已关联的资料。')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '添加结果分组' }))
  const group = screen.getByRole('group', { name: '结果分组 1' })
  expect(within(group).getByText('结果分组 1')).toBeTruthy()
  expect(screen.getByText('引用沿用已核验的文献；新写的内容需要另外选择支持的文献。')).toBeTruthy()
  expect(screen.getByText('不同说法会并列保留；你核实之前，不会写成确定的内容。')).toBeTruthy()
  expect(document.body.textContent).not.toMatch(banned)
})

it('names the thesis customer page in customer wording, in Chinese and English', async () => {
  serve(true)
  const view = render(<ProjectManuscripts {...thesis} />)
  await screen.findByRole('checkbox', { name: '固定统计结果' })
  expect(document.querySelector('.workspace-eyebrow')?.textContent).toBe('毕业论文')
  expect(screen.getByText('按学校模板的章节整理写作材料，生成正文初稿，核对后采用为新的一版。')).toBeTruthy()
  expect(document.body.textContent).not.toMatch(banned)
  view.unmount()
  setLocale('en')
  render(<ProjectManuscripts {...thesis} />)
  await screen.findByRole('checkbox', { name: '固定统计结果' })
  expect(document.querySelector('.workspace-eyebrow')?.textContent).toBe('Thesis')
  expect(screen.getByText('Organize the writing materials by the chapters of the school template, generate a first draft, check it and adopt it as a new version.')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /^Results$/ }))
  expect(screen.getByRole('heading', { name: 'Result groups' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Add result group' }))
  expect(screen.getByRole('group', { name: 'Result group 1' })).toBeTruthy()
  expect(screen.getByText('Arrange the results and figures in the order you plan to discuss them. Reordering keeps the linked materials.')).toBeTruthy()
  expect(screen.getByText('Citations keep the literature already checked. New text needs its own supporting literature.')).toBeTruthy()
  expect(screen.getByText('Different statements are kept side by side and are not written as settled until you check them.')).toBeTruthy()
  expect(document.body.textContent).not.toMatch(/Results group|review gates|paragraph identity|Fixed version|explicitly publish/i)
})

it('keeps the staff wording on the staff materials pages', async () => {
  serve()
  render(<ProjectManuscripts projectId="p1" researchTopic="Test" outputLanguage="en" active />)
  await screen.findByRole('checkbox', { name: '固定统计结果' })
  expect(screen.getByRole('heading', { name: 'Results 分组' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '添加 Results 分组' })).toBeTruthy()
  expect(screen.getByText('按论述顺序组织结果与图表；移动分组保留来源和段落身份。')).toBeTruthy()
  expect(screen.getByText('引用沿用原核验门禁；新论述不自动继承旧支持性决定。')).toBeTruthy()
  expect(screen.getByText('并列保留不同说法；冲突字段不写成已确认事实。')).toBeTruthy()
})

it('names the writing materials on the confirmation page by version and save time', async () => {
  const version = { ...manuscriptFixture.versions[0], created_at: savedAt } as unknown as ManuscriptVersion
  render(<CustomerWritingConfirm bundle={bundleFixture()} version={version} capabilities={null} customerThesis={false} generated={false}
    edited={false} unknown={false} previewUnknown={false} busy={false} onPreview={() => {}} onSubmit={async () => {}} onCheckResult={() => {}} />)
  const region = screen.getByRole('region', { name: '本次写作材料' })
  expect(region.textContent).toMatch(/第 1 版 · \d{4}/)
  expect(region.querySelector('time')?.getAttribute('dateTime')).toBe(savedAt)
  expect(document.body.textContent).not.toMatch(banned)
  expect(screen.queryByRole('region', { name: '完整外发材料' })).toBeNull()
})

it('keeps the staff readable bundle title when no save time is given', () => {
  render(<WritingBundlePreview bundle={bundleFixture()} readableSnapshot={snapshotFixture as unknown as Snapshot} />)
  const region = screen.getByRole('region', { name: '完整外发材料' })
  expect(region.textContent).toContain('固定版本 1')
})

const school = { schema_version: 1, profile, template_version_id: 'template1', confirmation_id: 'confirm1', confirmation_sha256: 'a'.repeat(64),
  confirmation: { id: 'confirm1', chapters: chapters.map(({ id, title, level }) => ({ id, title, level })) }, source_files: [], chapters }
const thesisVersion = { ...manuscriptFixture.versions[0], snapshot: { ...snapshotFixture, output_language: 'zh-CN', thesis_context: school,
  sections: chapters.map(c => ({ ...c, paragraphs: [{ id: `${c.id}:1`, text: c.title, origin: 'user_provided', source_ids: [], citations: [] }] })) } } as unknown as ManuscriptVersion

it('says a thesis chapter that is not written keeps its text, in Chinese and English', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ items: [], capabilities: { real_calls_enabled: false } })))
  const view = render(<WritingLive projectId="p1" manuscriptId="m1" version={thesisVersion} onPublished={() => {}} customerThesis />)
  const region = await screen.findByRole('region', { name: '本次可生成的章节' })
  expect(within(region).getByText(/^致谢 · /).textContent).toContain('保持原文')
  expect(document.body.textContent).not.toMatch(banned)
  view.unmount()
  setLocale('en')
  render(<WritingLive projectId="p1" manuscriptId="m1" version={thesisVersion} onPublished={() => {}} customerThesis />)
  const english = await screen.findByRole('region', { name: 'Chapters that can be generated this time' })
  expect(within(english).getByText(/^致谢 · /).textContent).toContain('Kept as written')
})

it('keeps “受保护” for the thesis chapters on the staff writing page', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ items: [], capabilities: { real_calls_enabled: false } })))
  render(<WritingLive projectId="p1" manuscriptId="m1" version={thesisVersion} onPublished={() => {}} />)
  const region = await screen.findByRole('region', { name: '冻结学校章节' })
  expect(within(region).getByText(/致谢 · /).textContent).toContain('受保护')
})

// B05 task 11: English review of the B04 Word page wording, in American spelling.
it('words the earlier blind copy and the customer Word options in reviewed American English', async () => {
  const { translate } = await import('../../shared/i18n')
  setLocale('en')
  expect(translate('历史盲审稿')).toBe('Earlier anonymized copy (read-only)')
  expect(translate('盲评版请按学校要求交第三方处理。')).toBe('Ask a third party to prepare the anonymized copy for blind review, as your school requires.')
  expect(translate('封面与目录')).toBe('Cover and table of contents')
  expect(translate('按第 {revision} 版导出；封面等填写内容只用于这次 Word。', { revision: 3 })).toBe('Exports version 3. What you fill in for the cover and other pages is used only for this Word file.')
})

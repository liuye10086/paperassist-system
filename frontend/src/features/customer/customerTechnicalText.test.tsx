// B01 regression baseline: customer pages must not show system IDs, hashes, paths or raw codes.
// Every stub UUID and hash is registered as a system ID, so full values and 8/12-character cuts are caught.
// Known leaks are asserted exactly as they appear today; the batch that fixes one changes it to toEqual([]).
// Cases run in Chinese; one English case covers the progress page, because raw codes come from the same data
// mapping in both languages. In English only snake_case values are listed as rawValues: single words such as
// draft or failed are normal English wording there.
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
import { findTechnicalText } from '../../test/technicalText'
import { manuscriptFixture as b05ManuscriptFixture } from '../manuscripts/manuscriptFixtures'
import { taskFixture as b05TaskFixture, workspaceFixture as b05WorkspaceFixture } from '../tasks/taskFixtures'
import WritingClaimReview from '../manuscripts/WritingClaimReview'
import type { LocalManifest } from '../manuscripts/writingLiveTypes'
import CustomerWorkspace from './CustomerWorkspace'
import { customerBase } from './customerWorkspaceApi'

const projectId = '7c1f3a52-6b0e-4d8f-9a21-3e4b5c6d7f80'
const deliveryId = '0a9b8c7d-6e5f-4a3b-8c2d-1e0f9a8b7c6d'
const snapshotId = '5e4d3c2b-1a09-4f8e-9d7c-6b5a4f3e2d1c'
const memberId = '9f8e7d6c-5b4a-4392-8170-6f5e4d3c2b1a'
const fileId = '2b3c4d5e-6f70-4a81-92b3-c4d5e6f7a8b9'
const feedbackId = '4c5d6e7f-8091-4a2b-bc3d-4e5f60718293'
const submissionId = '6d7e8f90-a1b2-4c3d-8e4f-5a6b7c8d9e0f'
const sha256 = '18533238bb1daaa4a8600f1c533cd8ce7c66996ba7ee120b8ee6cc766e3670e2'
const time = '2026-11-18T06:20:00Z'
const base = '/api/v1/projects/' + projectId
const customer = customerBase(projectId)
const snapshotBase = `${customer}/deliveries/${snapshotId}`
const progressStatuses = ['draft', 'pending_assignment', 'assigned', 'analyzing', 'needs_materials', 'materials_submitted', 'delivered']
const systemIds = [projectId, deliveryId, snapshotId, memberId, fileId, feedbackId, submissionId, sha256]
const scan = (rawValues?: readonly string[]) => findTechnicalText(document.body, { systemIds, rawValues })

const project = {
  id: projectId, name: '病例对照分析', research_topic: '比较病例与对照的血清指标', project_type: 'research',
  file_count: 1, created_at: time, updated_at: time, has_analysis_history: true,
}
const summary = {
  id: snapshotId, delivery_id: deliveryId, title: '血清指标比较报告', kind: 'analysis', revision: 2,
  published_at: time, member_count: 1,
}

const submission = {
  id: submissionId, requirement_version: 2, file_ids: [fileId], files: [{ id: fileId, name: 'group_table.xlsx' }],
  note: '第 4 例样本编号已更正。', created_at: time,
}

function serve(status = 'needs_materials') {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === base) return Response.json(project)
    if (url === customer + '/progress') return Response.json({
      status, requirement_version: 2, submitted_at: time, updated_at: time,
      note: '请补充 group_table.xlsx 中的分组信息。', feedback: [{ id: feedbackId, message: '已补交分组表。', created_at: time }],
      submissions: status === 'materials_submitted' ? [submission] : [],
    })
    if (url === customer + '/deliveries') return Response.json({ items: [summary] })
    if (url === snapshotBase) return Response.json({
      ...summary, package_url: snapshotBase + '/download', feedback: [],
      members: [{ id: memberId, name: 'serum_boxplot.png', format: 'png', size_bytes: 172111,
        download_url: `${snapshotBase}/members/${memberId}/download` }],
    })
    if (url.startsWith(base + '/files?')) return Response.json({
      items: [{ id: fileId, filename: 'sample_data_v2.xlsx', file_type: 'xlsx', parse_status: 'parsed', sha256 }],
      total: 1, page: 1, page_size: 5,
    })
    return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
  }))
}

function open(step: string, extra = '', status?: string) {
  window.history.replaceState(null, '', `#customer-project=${projectId}&step=${step}${extra}`)
  serve(status)
  render(<CustomerWorkspace />)
}

beforeEach(() => { setApiSession('csrf', 'customer-test'); sessionStorage.clear() })
afterEach(() => {
  cleanup()
  setLocale('zh-CN')
  clearApiSession()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', window.location.pathname)
})

it('shows analysis progress and supplement notes in business wording', async () => {
  open('progress')
  await screen.findByText('请补充 group_table.xlsx 中的分组信息。')
  await screen.findByText('已补交分组表。')
  expect(scan(progressStatuses)).toEqual([])
})

it('shows analysis progress in English without raw codes', async () => {
  setLocale('en')
  open('progress')
  await screen.findByText('请补充 group_table.xlsx 中的分组信息。')
  await screen.findByText('已补交分组表。')
  expect(scan(progressStatuses.filter(status => status.includes('_')))).toEqual([])
})

it('shows submitted materials and their files in business wording', async () => {
  open('progress', '', 'materials_submitted')
  await screen.findByText('已补交，等待核对')
  await screen.findByText('第 4 例样本编号已更正。')
  expect(scan(progressStatuses)).toEqual([])
})

it('shows the supplement page with the analyst request and file names only', async () => {
  const token = new URLSearchParams({ return: `customer-project=${projectId}&step=progress`, returnLabel: 'progress' })
  open('upload', '&mode=supplement&' + token.toString())
  await screen.findByRole('heading', { name: '补交资料', level: 1 })
  await screen.findByText('请补充 group_table.xlsx 中的分组信息。')
  await screen.findByRole('link', { name: '返回 任务进度' })
  await screen.findAllByText('sample_data_v2.xlsx')
  expect(scan(['parsed', 'stored', 'failed', 'supplement', 'needs_materials'])).toEqual([])
})

it('lists published deliveries without internal identifiers', async () => {
  open('deliveries')
  await screen.findByText('血清指标比较报告')
  expect(scan()).toEqual([])
})

it('opens a released delivery and its files without internal identifiers', async () => {
  open('deliveries', `&snapshot=${snapshotId}&delivery=${deliveryId}`)
  await screen.findByRole('heading', { name: '血清指标比较报告', level: 1 })
  await screen.findByText('serum_boxplot.png')
  expect(scan()).toEqual([])
})

it('lists uploaded analysis files by file name', async () => {
  open('upload')
  await screen.findByText('sample_data_v2.xlsx')
  expect(scan(['parsed', 'stored', 'failed'])).toEqual([])
})

// B03 task 8 (总案第十节 B03-6): the customer's literature check shows no context hash, claim, bibliography-version
// or review IDs and no raw decision, relevance or reading-scope values — before and after every interaction.
const reviewValues = ['supported', 'partial', 'unsupported', 'needs_review', 'related', 'unrelated', 'uncertain', 'user_material', 'pmc_fulltext']
it('shows the customer literature claim check without identifiers or raw values, before and after deciding', async () => {
  const { fireEvent, waitFor } = await import('@testing-library/react')
  const claimId = '0c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f', referenceId = '1d2e3f4a-5b6c-4d7e-9f80-a1b2c3d4e5f6'
  const metadataId = '2e3f4a5b-6c7d-4e8f-8a91-b2c3d4e5f6a7', frozenId = '3f4a5b6c-7d8e-4f90-9ba2-c3d4e5f6a7b8'
  const oldClaimId = '4a5b6c7d-8e9f-4a01-8cb3-d4e5f6a7b8c9', evidenceId = '5b6c7d8e-9f0a-4b12-9dc4-e5f6a7b8c9d0'
  const reviewId = '6c7d8e9f-0a1b-4c23-8ed5-f6a7b8c9d0e1', searchId = '7d8e9f0a-1b2c-4d34-9fe6-a7b8c9d0e1f2'
  const receiptId = '8e9f0a1b-2c3d-4e45-8af7-b8c9d0e1f2a3'
  const text = '血清指标在病例组更高。', context = 'writing-v2:' + sha256, quote = '病例组血清指标显著升高'
  const source = { kind: 'abstract', search_id: searchId, receipt_id: receiptId, sha256 }
  const frozen = { id: frozenId, claim_id: oldClaimId, claim_revision: 1, project_reference_id: referenceId,
    quote: '与对照相比，病例组血清指标显著升高。', reading_scope: 'pmc_fulltext', source, location: { abstract_index: 0, start: 0, end: 18 }, created_at: time }
  const manifest = { sources: {}, evidence: { e1: { evidence_id: frozenId, binding: { project_reference_id: referenceId,
    metadata_version_id: metadataId, metadata: { title: '血清标志物队列研究' }, evidence: [frozen] } } } } as unknown as LocalManifest
  const claim = { id: claimId, project_id: projectId, revision: 1, content: text, context, output_language: 'zh-CN', created_at: time, updated_at: time }
  const saved = { ...frozen, id: evidenceId, claim_id: claimId, quote, reading_scope: 'abstract', location: { abstract_index: 0, start: 6, end: 17 } }
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/evidence/claims')) return Response.json(claim, { status: 201 })
    if (url.endsWith(`/claims/${claimId}/evidence`)) return Response.json(saved, { status: 201 })
    if (url.endsWith(`/claims/${claimId}/reviews`)) return Response.json({ ...JSON.parse(String(init?.body)), id: reviewId, claim_id: claimId,
      decided_by: memberId, created_at: time }, { status: 201 })
    return Response.json({ items: [] })
  }))
  const ids = { systemIds: [...systemIds, claimId, referenceId, metadataId, frozenId, oldClaimId, evidenceId, reviewId, searchId, receiptId], rawValues: reviewValues }
  render(<WritingClaimReview projectId={projectId} text={text} context={context} language="zh-CN" manifest={manifest}
    onBinding={() => {}} customerView />)
  await screen.findByText(text)
  expect(screen.getByRole('region', { name: '核对这段的文献依据' })).toBeTruthy()
  expect(findTechnicalText(document.body, ids)).toEqual([])
  expect(document.body.textContent).not.toContain('writing-v2:')
  fireEvent.click(screen.getByRole('button', { name: '为此精确文本创建新主张' }))
  await screen.findByText('已为这段文字建立核对记录（第 1 版）')
  const select = screen.getByLabelText('选择实际公开证据与书目') as HTMLSelectElement
  expect([...select.options].map(option => option.textContent)).toContain('文献 1 · 血清标志物队列研究 · PMC 正文片段')
  fireEvent.change(select, { target: { value: 'e1' } })
  expect(findTechnicalText(document.body, ids)).toEqual([])
  fireEvent.change(screen.getByLabelText('新主张精确摘录'), { target: { value: quote } })
  fireEvent.click(screen.getByRole('button', { name: '保存新主张证据' }))
  fireEvent.click(await screen.findByRole('checkbox', { name: quote }))
  fireEvent.change(screen.getByLabelText('本次支持决定'), { target: { value: 'supported' } })
  fireEvent.change(screen.getByLabelText('本次文献相关性'), { target: { value: 'related' } })
  fireEvent.change(screen.getByLabelText('新主张人工理由'), { target: { value: '摘要原文直接说明病例组升高。' } })
  fireEvent.click(screen.getByRole('button', { name: '保存此主张的人工决定' }))
  const decision = await screen.findByRole('checkbox', { name: '决定 1 · 支持 · 相关' })
  expect(findTechnicalText(document.body, ids)).toEqual([])
  fireEvent.click(decision)
  await waitFor(() => expect((decision as HTMLInputElement).checked).toBe(true))
  expect(findTechnicalText(document.body, ids)).toEqual([])
})

// B03 task 5 (D5): the one-step writing confirmation shows materials, fee and consent, but no preview ID or SHA.
it('shows the customer writing confirmation without preview identifiers or hashes', async () => {
  const { webcrypto, createHash } = await import('node:crypto')
  const { default: WritingLive } = await import('../manuscripts/WritingLive')
  const { bundleFixture } = await import('../manuscripts/writingLiveFixtures')
  const { manuscriptFixture } = await import('../manuscripts/manuscriptFixtures')
  vi.stubGlobal('crypto', webcrypto)
  const manuscriptId = '3e2d1c0b-9a8f-4e7d-8c6b-5a4f3e2d1c0b', bundleId = '7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d'
  const wire = JSON.stringify({ model: 'gpt-5.4-2026-03-05', input: JSON.stringify({ instructions: '比较病例与对照的血清指标', sources: [], evidence: [] }) })
  const digest = createHash('sha256').update(wire).digest('hex')
  const writing = `${base}/manuscripts/${manuscriptId}`
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST' && url === writing + '/writing-previews') return Response.json({
      ...bundleFixture(bundleId, manuscriptId), project_id: projectId, request_json: JSON.parse(String(init.body)),
      wire_json: wire, bundle_sha256: digest, wire_sha256: digest, wire_bytes: new TextEncoder().encode(wire).length,
    })
    if (url === writing + '/writing-previews') return Response.json({ items: [], capabilities: { real_calls_enabled: true } })
    return Response.json({ items: [] })
  }))
  const version = { ...manuscriptFixture.versions[0], snapshot: { ...manuscriptFixture.versions[0].snapshot, project_id: projectId } }
  render(<WritingLive projectId={projectId} manuscriptId={manuscriptId} version={version as never} onPublished={() => {}}
    customerSci={{ article_type: 'research', keywords: [], main_results: '', figure_plan: [], target_journal: { choice: 'undecided', name: null } } as never} />)
  await screen.findByText('本次将使用以下材料生成正文')
  expect(findTechnicalText(document.body, { systemIds: [...systemIds, manuscriptId, bundleId, digest] })).toEqual([])
})

// B03 task 4 (D2): the customer manuscript list, writing materials and version history show titles and
// “第 N 版 · 时间” only — no manuscript, version, task or source IDs and no requirement token.
it('shows the customer manuscript list, materials and versions without identifiers', async () => {
  const { default: ProjectManuscripts } = await import('../manuscripts/ProjectManuscripts')
  const { candidatesFixture, manuscriptFixture } = await import('../manuscripts/manuscriptFixtures')
  const manuscriptId = '8b7a6c5d-4e3f-4a2b-9c1d-0e9f8a7b6c5d', firstId = '1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d'
  const secondId = '6f5e4d3c-2b1a-4098-8f7e-6d5c4b3a2f1e', taskId = 'b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5e'
  const runId = 'c4d5e6f7-a8b9-4c0d-9e1f-2a3b4c5d6e7f', token = '9d4c2b7a1e8f3065c7b2a9d4e1f8c3b6a5d0e7f2c9b4a1d8e3f6c0b5a2d7e4f1'
  const snapshot = { ...manuscriptFixture.versions[0].snapshot, project_id: projectId }
  const versions = [firstId, secondId].map((id, index) => ({ ...manuscriptFixture.versions[0], id, revision: index + 1,
    parent_version_id: index ? firstId : null, task_id: taskId, created_at: time, snapshot, exports: [] }))
  const stored = { ...manuscriptFixture, id: manuscriptId, project_id: projectId, title: '血清指标比较', current_revision: 2, versions }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/manuscripts/candidates')) return Response.json({ ...candidatesFixture,
      items: [{ ...candidatesFixture.items[0], id: runId, file_id: fileId, download_url: null }], citation_drafts: [],
      paper_plan: { kind: 'research', title: '血清指标比较', keywords: ['血清'], sections: [], materials: [], token, omitted_count: 0 } })
    if (url === base + '/manuscripts') return Response.json({ items: [stored] })
    return Response.json({ items: [] })
  }))
  const props = { projectId, researchTopic: project.research_topic, outputLanguage: 'zh-CN' as const, active: true, projectType: 'sci' as const,
    customerSci: { settings: null, wordOnly: false }, initialManuscript: manuscriptId, initialRevision: 2 }
  const ids = { systemIds: [...systemIds, manuscriptId, firstId, secondId, taskId, runId, token] }
  const view = render(<ProjectManuscripts {...props} view="list" />)
  await screen.findByText('当前稿件')
  expect(findTechnicalText(document.body, ids)).toEqual([])
  view.rerender(<ProjectManuscripts {...props} view="materials" />)
  await screen.findByRole('region', { name: '已保存的写作要求' })
  expect(findTechnicalText(document.body, ids)).toEqual([])
  view.rerender(<ProjectManuscripts {...props} view="versions" />)
  await screen.findAllByRole('button', { name: '查看这一版' })
  expect(findTechnicalText(document.body, ids)).toEqual([])
})

// B03 task 6: the customer's “完成稿件复核” summary and the Word page show titles, counts and “第 N 版 · 时间” only.
it('shows the customer adoption summary and Word page without identifiers or hashes', async () => {
  const { createHash } = await import('node:crypto')
  const { default: WritingLanguageReview } = await import('../manuscripts/WritingLanguageReview')
  const { default: ManuscriptExports } = await import('../manuscripts/ManuscriptExports')
  const { scienceReview, languageArtifact } = await import('../manuscripts/writingLiveFixtures')
  const { exportFixture, manuscriptFixture } = await import('../manuscripts/manuscriptFixtures')
  const digest = (value: string) => createHash('sha256').update(value).digest('hex')
  const manuscriptId = 'd1e2f3a4-b5c6-4d7e-8f90-a1b2c3d4e5f6', requestId = 'e2f3a4b5-c6d7-4e8f-9a01-b2c3d4e5f6a7'
  const reviewId = 'f3a4b5c6-d7e8-4f90-8a12-c3d4e5f6a7b8', artifactId = 'a4b5c6d7-e8f9-4a01-9b23-d4e5f6a7b8c9'
  const versionId = 'b5c6d7e8-f9a0-4b12-8c34-e5f6a7b8c9d0', exportId = 'c6d7e8f9-a0b1-4c23-9d45-f6a7b8c9d0e1'
  const failedId = 'd7e8f9a0-b1c2-4d34-8e56-a7b8c9d0e1f2', taskId = 'e8f9a0b1-c2d3-4e45-9f67-b8c9d0e1f2a3'
  const hashes = ['review', 'artifact', 'inventory', 'candidate', 'docx'].map(digest)
  // The fixture paragraphs read “Original {section id}”; give them ordinary text so only the page itself is scanned.
  const candidate = { ...scienceReview.candidate, project_id: projectId, sections: scienceReview.candidate.sections?.map(section =>
    ({ ...section, paragraphs: section.paragraphs.map(paragraph => ({ ...paragraph, text: '血清指标在病例组更高。' })) })) }
  const review = { ...scienceReview, id: reviewId, request_id: requestId, review_sha256: hashes[0], candidate }
  const artifact = { ...languageArtifact, id: artifactId, request_id: requestId, review_id: reviewId, review_sha256: hashes[0],
    candidate, artifact_sha256: hashes[1], inventory_sha256: hashes[2], candidate_sha256: hashes[3] }
  const ids = { systemIds: [...systemIds, manuscriptId, requestId, reviewId, artifactId, versionId, exportId, failedId, taskId, ...hashes] }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith(`/language-reviews/${artifactId}`)) return Response.json(artifact)
    if (url.endsWith('/language-reviews')) return Response.json({ items: [{ id: artifactId, created_at: time }] })
    if (url.endsWith('/exports')) return Response.json({ items: [
      { ...exportFixture, id: exportId, version_id: versionId, task_id: taskId, sha256: hashes[4], created_at: time,
        download_url: `${base}/manuscripts/${manuscriptId}/exports/${exportId}/download` },
      { ...exportFixture, id: failedId, version_id: versionId, task_id: taskId, status: 'failed', error_code: 'task_failed',
        download_url: null, filename: null, size_bytes: null, sha256: null, created_at: time },
    ] })
    return Response.json({ items: [] })
  }))
  render(<WritingLanguageReview projectId={projectId} manuscriptId={manuscriptId} baseRevision={1} baseSavedAt={time}
    scienceParagraphs={7} review={review} onPublished={() => {}} customerSci />)
  await screen.findByRole('button', { name: '采用这份稿件' })
  expect(findTechnicalText(document.body, ids)).toEqual([])
  cleanup()
  const version = { ...manuscriptFixture.versions[0], id: versionId, task_id: taskId, created_at: time,
    snapshot: { ...manuscriptFixture.versions[0].snapshot, project_id: projectId }, exports: [] }
  render(<ManuscriptExports projectId={projectId} manuscriptId={manuscriptId} version={version as never} customerSci />)
  await screen.findByText('这一版 Word 没有生成成功。')
  expect(screen.queryByRole('button', { name: '查看任务结果' })).toBeNull()
  expect(findTechnicalText(document.body, ids)).toEqual([])
  expect(document.body.textContent).not.toMatch(/DOCX/)
})

// B03 task 8: the customer science check — with writing requirements and on an older manuscript without them — shows
// section names, source names and “第 N 个数字”, never IDs, hashes, fact paths, `occurrence` or provider wording.
// The submitted numeric binding still counts occurrences from 0.
it.each([['with writing requirements', true], ['without writing requirements', false]] as const)(
  'shows the customer science check %s without identifiers, hashes or occurrence', async (_name, planned) => {
    const { createHash } = await import('node:crypto')
    const { fireEvent, waitFor, within } = await import('@testing-library/react')
    const { default: WritingScienceReview } = await import('../manuscripts/WritingScienceReview')
    const { bundleFixture, liveRequest, rawSnapshot, reviewContext } = await import('../manuscripts/writingLiveFixtures')
    const digest = (value: string) => createHash('sha256').update(value).digest('hex')
    const manuscriptId = 'f1a2b3c4-d5e6-4f70-8192-a3b4c5d6e7f8', requestId = 'a2b3c4d5-e6f7-4081-92a3-b4c5d6e7f8a9'
    const bundleId = 'b3c4d5e6-f7a8-4192-a3b4-c5d6e7f8a9b0', sourceId = 'c4d5e6f7-a8b9-42a3-b4c5-d6e7f8a9b0c1'
    const callId = 'd5e6f7a8-b9c0-43b4-85d6-e7f8a9b0c1d2', authorizationId = 'e6f7a8b9-c0d1-44c5-96e7-f8a9b0c1d2e3'
    const logicalId = 'f7a8b9c0-d1e2-45d6-a7f8-a9b0c1d2e3f4', claimId = 'a8b9c0d1-e2f3-46e7-b8a9-b0c1d2e3f4a5'
    const hashes = ['candidate', 'body', 'raw'].map(digest)
    const sections = rawSnapshot.sections!.map((section, index) => ({ ...section,
      paragraphs: section.paragraphs.map(paragraph => ({ ...paragraph, text: `第 ${index + 1} 部分正文。` })) }))
    const candidate = { ...rawSnapshot, project_id: projectId, sections,
      sources: [{ kind: 'analysis_run', id: sourceId, file_id: fileId, role: 'computed_results', label: '血清指标分组比较', sha256, download_url: null, content: { version: 2 } }],
      writing_provenance: { ...rawSnapshot.writing_provenance!, provider_provenance: 'openai_live', bundle_id: bundleId, raw_output_sha256: hashes[2] },
      ...(planned ? { paper_plan: { kind: 'research', title: rawSnapshot.title, keywords: [], sections: [], materials: [] } } : {}) }
    const manifest = { sources: { s1: sourceId }, evidence: {} }
    const context = { ...reviewContext, request_id: requestId, candidate, candidate_sha256: hashes[0], body_sha256: hashes[1], reviews: [], local_manifest: manifest,
      claim_contexts: Object.fromEntries(Object.keys(reviewContext.claim_contexts).map(id => [id, `writing-v2:${hashes[0]}:${id}`])) }
    const wire = JSON.stringify({ model: 'gpt-5.4-2026-03-05', input: JSON.stringify({ sources: [{ alias: 's1', facts: [{ fact_path: '/groups/0/mean', value: '12.5' }] }], evidence: [] }) })
    const bundle = { ...bundleFixture(bundleId, manuscriptId), project_id: projectId, wire_json: wire, bundle_sha256: digest(wire), wire_sha256: digest(wire),
      wire_bytes: new TextEncoder().encode(wire).length, local_manifest: manifest }
    const request = { ...liveRequest, id: requestId, project_id: projectId, manuscript_id: manuscriptId, task: { ...liveRequest.task, id: requestId }, candidate,
      model_calls: [{ id: callId, model: 'gpt-5.4-2026-03-05', status: 'completed', provider_provenance: 'openai_live', bundle_id: bundleId,
        authorization_id: authorizationId, logical_task_id: logicalId, estimated_cost_micro_usd: 12345 }] }
    const claim = { id: claimId, project_id: projectId, revision: 1, content: '第 5 部分正文。', context: context.claim_contexts['discussion:1'],
      output_language: 'en', created_at: time, updated_at: time }
    const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/review-context')) return Response.json(context)
      if (url.endsWith(`/writing-previews/${bundleId}`)) return Response.json(bundle)
      if (init?.method === 'POST' && url.endsWith('/evidence/claims')) return Response.json(claim, { status: 201 })
      return Response.json({ items: [] })
    })
    vi.stubGlobal('fetch', fetcher)
    const ids = { systemIds: [...systemIds, manuscriptId, requestId, bundleId, sourceId, callId, authorizationId, logicalId, claimId, ...hashes, bundle.bundle_sha256] }
    render(<WritingScienceReview projectId={projectId} manuscriptId={manuscriptId} request={request as never} onPublished={() => {}} customerSci autoLoad baseSavedAt={time} />)
    const discussion = await screen.findByLabelText('段落主张分类 讨论 · 段落 1')
    await waitFor(() => expect(discussion.matches(':disabled')).toBe(false))
    expect(screen.getByText(/本次写作回执/)).toBeTruthy()
    expect(screen.getByText(/费用为预估，以用量记录为准/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '开始逐段核对' })).toBeTruthy()
    fireEvent.change(discussion, { target: { value: 'literature_claim' } })
    fireEvent.click(screen.getByRole('button', { name: '为此精确文本创建新主张' }))
    await screen.findByText('已为这段文字建立核对记录（第 1 版）')
    fireEvent.change(screen.getByLabelText('段落主张分类 结果 · 段落 1'), { target: { value: 'study_claim' } })
    const results = document.getElementById('writing-paragraph-results:1')!
    fireEvent.click(within(results).getByRole('button', { name: '添加数字来源' }))
    const number = within(results).getByRole('group', { name: '第 1 个数字' })
    expect(within(number).getByLabelText('这是本段的第几个数字')).toHaveProperty('value', '1')
    const fact = within(number).getByLabelText('来源中的数值') as HTMLSelectElement
    expect([...fact.options].map(option => option.textContent)).toContain('血清指标分组比较 · 数值 1 = 12.5')
    fireEvent.change(fact, { target: { value: 's1|/groups/0/mean' } })
    expect(findTechnicalText(document.body, { ...ids, rawValues: reviewValues })).toEqual([])
    expect(document.body.textContent).not.toMatch(/occurrence|provider|writing-v2:/)
    expect(within(results).getByText('请为这段中的每个数字选择来源。图表编号不算研究数值。')).toBeTruthy()
    // Finish the check: the submitted binding still counts from 0.
    fireEvent.change(discussion, { target: { value: 'non_claim' } })
    for (const select of screen.getAllByLabelText(/^段落主张分类/)) if (!(select as HTMLSelectElement).value) fireEvent.change(select, { target: { value: 'non_claim' } })
    for (const basis of screen.getAllByLabelText(/^科学核对理由/)) fireEvent.change(basis, { target: { value: '已逐段核对。' } })
    for (const name of ['标题研究对象一致', '标题方向一致', '标题强度一致', '摘要目的一致', '摘要方法一致', '摘要关键结果一致', '摘要结论一致']) fireEvent.click(screen.getByLabelText(name))
    fireEvent.change(screen.getByLabelText('标题一致性依据'), { target: { value: '标题已核对' } })
    fireEvent.change(screen.getByLabelText('摘要一致性依据'), { target: { value: '摘要已核对' } })
    fireEvent.click(screen.getByRole('button', { name: '完成科学核对' }))
    await waitFor(() => expect(fetcher.mock.calls.some(([url, init]) => url.endsWith('/reviews') && init?.method === 'POST')).toBe(true))
    const body = JSON.parse(String(fetcher.mock.calls.find(([url, init]) => url.endsWith('/reviews') && init?.method === 'POST')![1]?.body))
    const result = body.paragraphs.find((paragraph: { paragraph_id: string }) => paragraph.paragraph_id === 'results:1')
    expect(result.numeric_bindings).toEqual([{ occurrence: 0, kind: 'study', source_alias: 's1', fact_path: '/groups/0/mean', value: '12.5' }])
  })

// B03 task 8: the customer writing materials show source names and readable reading scopes, with nothing folded.
it('shows the customer writing materials without identifiers, fact paths or folded sections', async () => {
  const { createHash, webcrypto } = await import('node:crypto')
  const { default: WritingBundlePreview } = await import('../manuscripts/WritingBundlePreview')
  const { bundleFixture, rawSnapshot } = await import('../manuscripts/writingLiveFixtures')
  vi.stubGlobal('crypto', webcrypto)
  const manuscriptId = 'b9c0d1e2-f3a4-47f8-89b0-c1d2e3f4a5b6', bundleId = 'c0d1e2f3-a4b5-48a9-9ac1-d2e3f4a5b6c7'
  const sourceId = 'd1e2f3a4-b5c6-49ba-abd2-e3f4a5b6c7d8'
  const wire = JSON.stringify({ model: 'gpt-5.4-2026-03-05', input: JSON.stringify({
    sources: [{ alias: 's1', facts: [{ fact_path: '/groups/0/mean', value: '12.5' }] }],
    evidence: [{ quote: '病例组血清指标显著升高', reading_scope: 'pmc_fulltext', bibliography: { title: '血清标志物队列研究', authors: ['王明'], journal: 'Clin Chem', year: 2024 } }] }) })
  const digest = createHash('sha256').update(wire).digest('hex')
  const bundle = { ...bundleFixture(bundleId, manuscriptId), project_id: projectId, wire_json: wire, bundle_sha256: digest, wire_sha256: digest,
    wire_bytes: new TextEncoder().encode(wire).length, local_manifest: { sources: { s1: sourceId }, evidence: {} } }
  const snapshot = { ...rawSnapshot, project_id: projectId, sources: [{ kind: 'analysis_run', id: sourceId, file_id: fileId, role: 'computed_results',
    label: '血清指标分组比较', sha256, download_url: null, content: { version: 2 } }] }
  render(<WritingBundlePreview bundle={bundle as never} readableSnapshot={snapshot as never} materialsOnly />)
  await screen.findByText('病例组血清指标显著升高')
  expect(screen.getByText('血清指标分组比较')).toBeTruthy()
  expect(findTechnicalText(document.body, { systemIds: [...systemIds, manuscriptId, bundleId, sourceId, digest], rawValues: reviewValues })).toEqual([])
  expect(document.querySelector('details, [aria-expanded]')).toBeNull()
})

// B03 task 8: the customer language check starts and finishes with plain buttons; no advanced read-back, nothing folded.
it('shows the customer language check without the advanced read-back or folded sections', async () => {
  const { fireEvent } = await import('@testing-library/react')
  const { default: WritingLanguageReview } = await import('../manuscripts/WritingLanguageReview')
  const { scienceReview, languageContext } = await import('../manuscripts/writingLiveFixtures')
  const manuscriptId = 'e2f3a4b5-c6d7-4acb-bce3-f4a5b6c7d8e9'
  const candidate = { ...scienceReview.candidate, project_id: projectId, sections: scienceReview.candidate.sections?.map(section =>
    ({ ...section, paragraphs: section.paragraphs.map(paragraph => ({ ...paragraph, text: '血清指标在病例组更高。' })) })) }
  const review = { ...scienceReview, candidate }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json(url.endsWith('/language-context') ? { ...languageContext, candidate } : { items: [] })))
  render(<WritingLanguageReview projectId={projectId} manuscriptId={manuscriptId} baseRevision={1} baseSavedAt={time} review={review} onPublished={() => {}} customerSci />)
  expect(screen.queryByRole('button', { name: '读取真实 DOCX 全语言清单' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '开始语言核对' }))
  await screen.findByText('本版稿件的语言核对清单')
  expect(screen.getByRole('button', { name: '完成语言核对' })).toBeTruthy()
  expect(screen.queryByText('高级设置：按编号回读历史语言产物')).toBeNull()
  expect(document.querySelector('details, [aria-expanded]')).toBeNull()
  expect(findTechnicalText(document.body, { systemIds: [...systemIds, manuscriptId] })).toEqual([])
  expect(document.body.textContent).not.toMatch(/DOCX/)
})

it('shows the SCI draft, Word download and revision form without internal identifiers or retired review actions', async () => {
  const { fireEvent } = await import('@testing-library/react')
  const draft = { manuscript_id: submissionId, revision: 1, request_id: feedbackId }
  const reader = base + '/manuscripts/' + draft.manuscript_id + '/writing-requests/' + draft.request_id + '/draft-reader'
  const fetch = vi.fn(async (url: string) => {
    if (url === base) return Response.json({ ...project, project_type: 'sci' })
    if (url === base + '/sci-current-draft') return Response.json({draft})
    if (url === reader + '?revision=1') return Response.json({project_id: projectId, ...draft, status: 'succeeded',
      error_code: null, can_revise: true, previous_request_id: null, changes: [], draft: {title: '血清指标综述', output_language: 'zh-CN',
        sections: [{id: 'title', heading: '标题', level: 1, groups: [],
          paragraphs: [{id: memberId, parts: [{text: '血清指标综述', citations: []}]}]}], keywords: [], references: [], acknowledgements: ''}})
    return new Response(null, {status: 404})
  })
  vi.stubGlobal('fetch', fetch)
  window.history.replaceState(null, '', '#customer-project=' + projectId + '&step=word')
  render(<CustomerWorkspace />)
  await screen.findByRole('heading', {name: '血清指标综述'})
  const check = () => {
    expect(screen.queryByRole('alert')).toBeNull()
    expect(scan()).toEqual([])
    expect(document.body.textContent).not.toMatch(/事实稿|受控模型写作|逐条回复|DOCX|occurrence/)
    expect(screen.queryByRole('button', {name: '以此版本处理意见'})).toBeNull()
  }
  check()
  const word = screen.getByRole('link', {name: /下载.*Word/})
  expect(word.getAttribute('href')).toBe(reader + '/word?revision=1')
  fireEvent.click(screen.getByRole('button', {name: '修改初稿'}))
  expect(await screen.findByLabelText('审稿意见')).toBeTruthy()
  check()
  expect(fetch.mock.calls.map(([url]) => url).some(url => /\/reviews|\/exports|\/writing-authorizations/.test(url))).toBe(false)
})

// B04 task 14: end to end through CustomerWorkspace on a thesis project — the template list, upload page, single adoption
// view and change preview; writing materials and literature; chapters, writing and template migration; the Word page
// with only the identified Word and with a historical blind export; and the supervisor's returned Word. Every page
// scans clean, keeps the customer wording and folds nothing. A probe puts a fixture ID and an XML part back on the
// page and expects the scan to turn red, so a page that renders nothing cannot pass.
it('shows thesis details, template rules and uploads without internal identifiers', async () => {
  const { fireEvent } = await import('@testing-library/react')
  const { createHash, webcrypto } = await import('node:crypto')
  const { manuscriptFixture, snapshotFixture, exportFixture } = await import('../manuscripts/manuscriptFixtures')
  const { bundleFixture } = await import('../manuscripts/writingLiveFixtures')
  const { taskFixture } = await import('../tasks/taskFixtures')
  vi.stubGlobal('crypto', webcrypto)
  const digest = (value: string) => createHash('sha256').update(value).digest('hex')
  const id = {
    templateA: '0b1c2d3e-4f5a-4b6c-8d7e-9f0a1b2c3d4e', templateB: '1c2d3e4f-5a6b-4c7d-9e8f-0a1b2c3d4e5f',
    confirmA: '2d3e4f5a-6b7c-4d8e-8f90-1a2b3c4d5e6f', confirmB: '3e4f5a6b-7c8d-4e9f-9a01-2b3c4d5e6f70',
    templateFile: '4f5a6b7c-8d9e-4fa0-8b12-3c4d5e6f7081', manuscript: '5a6b7c8d-9eaf-40b1-9c23-4d5e6f708192',
    v1: '6b7c8d9e-afb0-41c2-8d34-5e6f708192a3', v2: '7c8d9eaf-b0c1-42d3-9e45-6f708192a3b4',
    task: '8d9eafb0-c1d2-43e4-8f56-708192a3b4c5', exportSigned: '9eafb0c1-d2e3-44f5-9067-8192a3b4c5d6',
    exportBlind: 'afb0c1d2-e3f4-4506-8178-92a3b4c5d6e7', exportTask: 'b0c1d2e3-f405-4617-9289-a3b4c5d6e7f8',
    bundle: 'c1d2e3f4-0516-4728-83a9-b4c5d6e7f809', round: 'd2e3f405-1627-4839-94ba-c5d6e7f8091a',
    roundTask: 'e3f40516-2738-494a-85cb-d6e7f8091a2b', document: 'f4051627-3849-4a5b-96dc-e7f8091a2b3c',
    documentVersion: '05162738-495a-4b6c-87ed-f8091a2b3c4d', presentation: '16273849-5a6b-4c7d-98fe-091a2b3c4d5e',
  }
  const hashes = ['analysis-a', 'analysis-b', 'confirmation', 'word', 'blind-word'].map(digest)
  const thesisProject = { id: projectId, name: '运动干预毕业论文', research_topic: '运动干预与血压', project_type: 'thesis',
    file_count: 1, created_at: time, updated_at: time, default_output_language: 'zh-CN' }
  const profile = { revision: 3, school: '示例体育大学', department: '运动人体科学学院', major: '运动人体科学', degree_type: '硕士',
    education_level: '研究生', applicable_version: '2026', bound_confirmation_id: id.confirmA }
  const chapters = [{ id: 'chapter-methods', title: '第 3 章 研究设计', level: 1 }, { id: 'chapter-results', title: '第 4 章 研究结果', level: 1 }]
  const source = (text: string) => ({ part: 'word/document.xml', path: '/w:document/w:body/w:p[4]', text })
  const analysis = (fontSize: number) => ({
    rules: [{ id: 'body.font_size_pt', label: 'body.font_size_pt', value: fontSize, source: source('正文小四宋体') }],
    chapters, sections: [], notes: [], missing: [], unsupported: [], identity_fields: [],
    conflicts: fontSize === 14 ? [{ id: 'conflict-1', rule_id: 'body.font_size_pt', label: 'body.font_size_pt', options: [
      { id: 'openxml', value: 14, source: source('正文四号宋体') },
      { id: 'text-1', value: 12, source: { part: 'supplement_text', path: 'supplement_text', text: '正文小四' } }] }] : [],
  })
  const templateSource = { id: 's1', role: 'template', file_id: id.templateFile, filename: '学校论文模板.docx', download_url: '' }
  const templates = [
    { id: id.templateA, name: '学校 2025 模板', school: profile.school, version_label: '2025', task: { id: id.task, status: 'succeeded' },
      analysis: analysis(12), analysis_sha256: hashes[0], confirmation: { id: id.confirmA, chapters }, sources: [templateSource] },
    { id: id.templateB, name: '学校 2026 模板', school: profile.school, version_label: '2026', task: { id: id.task, status: 'succeeded' },
      analysis: analysis(14), analysis_sha256: hashes[1], confirmation: null, sources: [templateSource] },
  ]
  const preview = {
    current: { confirmation_id: id.confirmA, template_name: '学校 2025 模板', confirmed_at: time },
    next: { confirmation_id: null, template_name: '学校 2026 模板', confirmed_at: null },
    chapters: [{ title: '第 3 章 研究设计', change: 'title_changed', detail_key: 'chapter.title_changed', detail_params: { from: '第 3 章 研究方法', to: '第 3 章 研究设计' } },
      { title: '附录', change: 'added', detail_key: 'chapter.added', detail_params: {} }],
    outputs: [{ kind: 'word_format', rule_id: 'body.font_size_pt', detail_key: 'format.rule', detail_params: { from: 12, to: 14 } }],
    manuscripts: [{ manuscript_id: id.manuscript, title: '运动干预与血压', revision: 2, keeps_template: true, next_action: 'migrate' }],
  }
  const thesisChapters = chapters.map((chapter, index) => ({ ...chapter, purpose: index ? 'results' : 'materials_and_methods', output_language: 'zh-CN', result_group_ids: [] }))
  const thesisContext = { schema_version: 1, profile, template_version_id: id.templateA, confirmation_id: id.confirmA, confirmation_sha256: hashes[2],
    confirmation: { id: id.confirmA, chapters }, source_files: [], chapters: thesisChapters }
  const snapshot = { ...snapshotFixture, project_id: projectId, title: '运动干预与血压', output_language: 'zh-CN', notice: '本地整理的写作材料', issues: [],
    methods: [], thesis_context: thesisContext,
    sections: thesisChapters.map(chapter => ({ ...chapter, paragraphs: [{ id: chapter.id + ':1', text: '运动干预后收缩压下降。', origin: 'user_provided', source_ids: [], citations: [] }] })),
    school_content_report: { rules_version: 'school_v1', issues: [], can_publish: true, scientifically_verified: false } }
  const version = (versionId: string, revision: number) => ({ ...manuscriptFixture.versions[0], id: versionId, revision, parent_version_id: revision > 1 ? id.v1 : null,
    task_id: id.task, created_at: time, snapshot, exports: [] })
  const manuscript = { ...manuscriptFixture, id: id.manuscript, project_id: projectId, title: '运动干预与血压', current_revision: 2,
    created_at: time, updated_at: time, versions: [version(id.v2, 2), version(id.v1, 1)] }
  const purposes = ['abstract', 'introduction', 'materials_and_methods', 'results', 'discussion', 'conclusion', 'references', 'acknowledgements', 'manual', 'other']
  const readiness = { ready: true, blocking_reasons: [], profile, confirmation_id: id.confirmA, chapters, purposes, template_source_file_ids: [] }
  const requirements = { revision: 2, education_level: '硕士', language: 'zh-CN', school: profile.school, title: '运动干预与血压', keywords: ['运动', '血压'],
    sections: [{ chapter_id: 'chapter-methods', purpose: 'materials_and_methods', content: '随机分组，干预 12 周。' }],
    template: { name: '学校 2025 模板', confirmation_id: id.confirmA, chapters } }
  const manuscriptBase = `${base}/manuscripts/${id.manuscript}`
  const word = (exportId: string, extra: object) => ({ ...exportFixture, id: exportId, version_id: id.v2, task_id: id.exportTask, created_at: time,
    download_url: `${manuscriptBase}/exports/${exportId}/download`, ...extra })
  const blindPresentation = { binding: { presentation_version_id: id.presentation, language_view: 'zh-CN', review_mode: 'blind' },
    checks: [{ code: 'blind:images', status: 'pending', message: 'Images require blind review' }],
    quality: { scientific_semantic: 'pending', word_wps: 'pending', real_compliance: 'pending' },
    blind: { known_identity_check: 'passed', remaining: [], images: 'pending_manual_review', exceptions: [], anonymity_verified: false } }
  const wire = JSON.stringify({ model: 'gpt-5.4-2026-03-05', input: JSON.stringify({ instructions: '写作学校章节', sources: [], evidence: [] }) })
  const bundleSha = digest(wire)
  const round = { id: id.round, project_id: projectId, title: '导师第一轮意见', project_type: 'thesis', round_number: 1, revision: 1, synthetic: false,
    manuscript: { id: id.manuscript, revision: 1, version_id: id.v1, title: '运动干预与血压' }, sources: [], items: [], materials: [],
    constraints: { school_confirmation_id: id.confirmA, journal_target_id: null }, versions: [], decisions: [],
    task: { ...taskFixture, id: id.roundTask, project_id: projectId, task_type: 'review_round_plan', phase: 'verify', status: 'succeeded', display_status: 'succeeded', reason_code: null, error_code: null,
      input_version: { kind: 'review_round_plan', round_id: id.round, base_version_id: id.v1, workflow_version: 'review_round_plan_v1' } },
    wait: null, created_at: time, real_model_calls: false, real_network_calls: false, continuation: null, next_round_ids: [] }
  const continuation = { previous_round_id: id.round, manuscript_id: id.manuscript, expected_current_revision: 2,
    eligible_inputs: [{ id: id.manuscript, revision: 1, version_id: id.v1, title: '运动干预与血压', saved_at: time,
      exports: [{ id: id.exportBlind, status: 'succeeded', review_mode: 'blind', created_at: time }, { id: id.exportSigned, status: 'succeeded', review_mode: 'identified', created_at: time }] }],
    successful_revisions: [], returns: [] }
  const reviewInputs = { project_type: 'thesis', manuscripts: [{ id: id.manuscript, title: '运动干预与血压', current_revision: 2, versions: [
    { id: id.v1, revision: 1, status: 'published', title: '运动干预与血压', created_at: time }, { id: id.v2, revision: 2, status: 'published', title: '运动干预与血压', created_at: time }] }],
    documents: [{ file_id: id.document, filename: '导师返回.docx', document_version_id: id.documentVersion, version: 1, kind: 'docx_document' }],
    journal_targets: [], school_confirmations: [{ id: id.confirmA, label: '学校 2025 模板' }] }
  const state = { adopted: true }
  const exportsWith = { blind: false }
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (url === base) return Response.json(thesisProject)
    if (url === base + '/thesis-profile') return Response.json(profile)
    if (url === base + '/thesis-requirements') return Response.json(state.adopted ? requirements : { ...requirements, template: null })
    if (url === base + '/school-templates') return Response.json({ items: templates })
    if (url === base + '/thesis-template-binding/preview') return Response.json(preview)
    if (url.startsWith(base + '/files?')) return Response.json({ items: [{ id: id.templateFile, filename: '学校论文模板.docx', file_type: 'docx', parse_status: 'parsed', sha256 }],
      total: 1, page: 1, page_size: 5 })
    if (url.startsWith(base + '/file-batches?')) return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
    if (url === base + '/literature/config') return Response.json({ available: false, reason: 'ncbi_not_configured', candidate_limits: [20], default_limit: 20, page_size: 10,
      publication_types: [], full_text_acquisition: false, claim_verification: false })
    if (url.startsWith(base + '/literature/')) return Response.json({ project_id: projectId, items: [], total: 0, page: 1, page_size: 10 })
    if (url === base + '/manuscripts') return Response.json({ items: [manuscript] })
    if (url === base + '/manuscripts/candidates') return Response.json({ items: [], citation_drafts: [], methods_fields: [], project_type: 'thesis', thesis: readiness })
    if (method === 'POST' && url === manuscriptBase + '/writing-previews') {
      const school = { schema_version: 1, chapters: { chapter1: { chapter_id: 'chapter-results', title: '第 4 章 研究结果', level: 1, purpose: 'results', output_language: 'zh-CN', result_group_ids: [] } }, writable_aliases: ['chapter1'] }
      const fixture = bundleFixture(id.bundle, id.manuscript)
      return Response.json({ ...fixture, project_id: projectId, base_version_id: id.v2, request_json: JSON.parse(String(init?.body)), wire_json: wire,
        bundle_sha256: bundleSha, wire_sha256: bundleSha, wire_bytes: new TextEncoder().encode(wire).length,
        local_manifest: { ...fixture.local_manifest, school, protected_identity: { sha256: digest('identity') } } })
    }
    if (url === manuscriptBase + '/writing-previews') return Response.json({ items: [], capabilities: { real_calls_enabled: true } })
    if (url === manuscriptBase + '/versions/1') return Response.json(version(id.v1, 1))
    if (url === manuscriptBase + '/school-changes') return Response.json({ items: [] })
    if (url === manuscriptBase + '/versions/2/exports') return Response.json({ items: [
      ...(exportsWith.blind ? [word(id.exportBlind, { sha256: hashes[4], filename: '毕业论文盲审稿.docx', presentation: blindPresentation })] : []),
      word(id.exportSigned, { sha256: hashes[3], filename: '毕业论文.docx' })] })
    if (url === base + '/reviews/inputs') return Response.json(reviewInputs)
    if (url === base + '/reviews/rounds') return Response.json({ items: [round] })
    if (url === `${base}/reviews/rounds/${id.round}`) return Response.json(round)
    if (url === `${base}/reviews/rounds/${id.round}/continuation-context`) return Response.json(continuation)
    if (url.endsWith('/progress')) return Response.json({ items: [], current: null, journal_current_by_target: {} })
    return Response.json({ items: [] })
  }))
  const ids = { systemIds: [...systemIds, ...Object.values(id), ...hashes, bundleSha] }
  // Wording the plan bans on every thesis customer page. “盲审” alone stays allowed: the historical label contains it.
  const banned = /DOCX|独立盲审派生稿|普通署名稿|盲审稿 Word|生成盲审稿|预览盲审稿|审阅输出模式|公共稿件|清洁|冻结|绑定此确认版本|word\/|supplement_text/
  const check = () => {
    expect(screen.queryByRole('alert')).toBeNull()
    expect(findTechnicalText(document.body, ids)).toEqual([])
    expect(document.body.textContent).not.toMatch(banned)
    if (!document.querySelector('.thesis-organizer-panels')) {
      expect(document.querySelectorAll('details')).toHaveLength(0)
      expect(document.querySelector('.customer-step-content [aria-expanded]')).toBeNull()
    }
  }
  const visit = (hash: string) => {
    cleanup()
    window.history.replaceState(null, '', `#customer-project=${projectId}&${hash}`)
    render(<CustomerWorkspace />)
  }
  // The organizer uses customer-facing language whether or not a template is adopted.
  visit('step=school')
  await screen.findByText('已采用学校模板 · 学校 2025 模板')
  check()
  expect(document.body.textContent).not.toMatch(/绑定/)
  state.adopted = false
  visit('step=school')
  await screen.findByRole('button', { name: '上传学校模板' })
  check()
  expect(document.body.textContent).not.toMatch(/绑定/)
  state.adopted = true
  // Template list, the upload page and the single adoption view (B04 tasks 5, 6).
  visit('step=school&view=list')
  await screen.findByRole('heading', { name: '学校模板', level: 1 })
  await screen.findAllByText('学校 2026 模板')
  check()
  visit('step=school&view=upload')
  await screen.findByRole('region', { name: '上传学校论文模板' })
  await screen.findAllByRole('option', { name: '学校论文模板.docx' })
  check()
  visit(`step=school&view=detail&template=${id.templateB}`)
  await screen.findByText('还有 1 处需要选择')
  check()
  fireEvent.click(screen.getByRole('radio', { name: /四号/ }))
  fireEvent.click(screen.getByRole('button', { name: '改用这份模板' }))
  await screen.findByRole('heading', { name: '改用后会影响这些章节和格式' })
  expect(screen.getByText('第 2 版使用原模板。之后生成的初稿将使用新模板。')).toBeTruthy()
  check()
  // Probe against a false green: a fixture ID or an XML part put back on the page turns the scan red.
  const probe = document.createElement('p')
  for (const leak of [id.templateB, 'word/document.xml']) {
    probe.textContent = '来源 ' + leak
    document.querySelector('.customer-step-content')!.append(probe)
    expect(check).toThrow()
    probe.remove()
  }
  check()
  // Writing materials and literature (B04 task 7).
  visit('step=materials')
  await screen.findByRole('heading', { name: '上传资料', level: 1 })
  await screen.findAllByText('学校论文模板.docx')
  check()
}, 30000)

// B05 task 17: the cross-module pages through CustomerWorkspace — the analysis results opened from a review opinion
// (with results, empty and with one chosen) and from the writing materials, the opinion and files pages after the
// trip back, the manuscripts step reached with a round token, the old task page and the project list. Every page scans
// clean, folds nothing and keeps none of the retired or internal wording. A probe puts a fixture ID back on the page
// and expects the scan to turn red, so a page that renders nothing cannot pass.
const b05 = {
  research: '1f2e3d4c-5b6a-4978-8a9b-0c1d2e3f4a5b', snapshot: '2a3b4c5d-6e7f-4a8b-9c0d-1e2f3a4b5c6e',
  delivery: '3b4c5d6e-7f8a-4b9c-8d0e-2f3a4b5c6d7e', word: '4c5d6e7f-8a9b-4c0d-9e1f-3a4b5c6d7e8f',
  table: '5d6e7f8a-9b0c-4d1e-8f2a-4b5c6d7e8f9a', round: '6e7f8a9b-0c1d-4e2f-9a3b-5c6d7e8f9a0b',
  roundTask: '7f8a9b0c-1d2e-4f3a-8b4c-6d7e8f9a0b1c', source: '8a9b0c1d-2e3f-4a4b-9c5d-7e8f9a0b1c2d',
  manuscript: '9b0c1d2e-3f4a-4b5c-8d6e-8f9a0b1c2d3e', version: '0c1d2e3f-4a5b-4c6d-9e7f-9a0b1c2d3e4f',
  task: 'ac1d2e3f-4a5b-4c6d-9e7f-9a0b1c2d3e40', uploaded: 'bd2e3f4a-5b6c-4d7e-8f90-ab1c2d3e4f51',
  structure: 'ce3f4a5b-6c7d-4e8f-9a01-bc2d3e4f5a62', confirmation: 'df4a5b6c-7d8e-4f90-8b12-cd3e4f5a6b73',
}
const b05Ids = { systemIds: [...systemIds, ...Object.values(b05)], rawValues: ['research', 'sci', 'thesis', 'succeeded', 'failed', 'analysis'] }
// Retired entries and wording that B02–B05 replaced; none may come back on a customer page.
const b05Banned = /固定文档|回传续轮|补料继续|THESIS|Results 分组|登记模板迁移|版本输入|人工文本|署名稿导出|NCBI|Worker|下载完整 JSON|前往已发布分析交付/
type B05State = { results: boolean; projects: boolean; uploaded: boolean }

function serveB05(projectType: 'sci' | 'thesis' | 'research', state: B05State) {
  const research = { id: b05.research, name: '血清分析项目', research_topic: '血清指标', project_type: 'research', file_count: 1,
    created_at: time, updated_at: time }
  const paper = { id: projectId, name: '血清指标论文', research_topic: '比较病例与对照的血清指标', project_type: projectType,
    file_count: 1, created_at: time, updated_at: time, default_output_language: 'zh-CN' }
  const researchBase = customerBase(b05.research) + '/deliveries'
  const delivery = { id: b05.snapshot, delivery_id: b05.delivery, title: '血清指标比较', kind: 'analysis', revision: 2, published_at: time, member_count: 2 }
  const member = (memberId: string, name: string, format: string) => ({ id: memberId, name, format, size_bytes: 20480,
    download_url: `${researchBase}/${b05.snapshot}/members/${memberId}/download` })
  const roundTask = { ...b05TaskFixture, id: b05.roundTask, project_id: projectId, task_type: 'review_round_plan', phase: 'verify', status: 'succeeded',
    display_status: 'succeeded', reason_code: null, error_code: null,
    input_version: { kind: 'review_round_plan', round_id: b05.round, base_version_id: b05.version, workflow_version: 'review_round_plan_v1' } }
  const item = { id: `${b05.source}:1`, source_id: b05.source, number: 1, original_number: '1', original_text: '请补充两组血清指标的生存分析。',
    source_location: null, revision: 1, status: 'waiting_material', uncompleted_reason: '', decision: null, category: 'method', locations: [],
    translation: null, plan: '', evidence_ids: [], needs: [{ kind: 'analysis', description: '补充生存分析' }], flags: [], conflicting_item_ids: [],
    proposed_action: 'modify', not_adopt_reason: '' }
  const round = { id: b05.round, project_id: projectId, title: '一审意见', project_type: projectType, round_number: 1, revision: 1, synthetic: false,
    manuscript: { id: b05.manuscript, revision: 1, version_id: b05.version, title: '血清指标论文' },
    sources: [{ id: b05.source, role: 'reviewer', label: '审稿人 1', format: 'text', original_text: '请补充两组血清指标的生存分析。', segments: [], warnings: [] }],
    items: [item], materials: [], constraints: { school_confirmation_id: null, journal_target_id: null }, versions: [], decisions: [], task: roundTask,
    wait: null, created_at: time, real_model_calls: false, real_network_calls: false, continuation: null, next_round_ids: [] }
  const fixtureVersion = b05ManuscriptFixture.versions[0]
  const version = { ...fixtureVersion, id: b05.version, revision: 1, task_id: b05.roundTask, created_at: time, exports: [],
    snapshot: { ...fixtureVersion.snapshot, project_id: projectId, title: '血清指标论文' } }
  const manuscript = { ...b05ManuscriptFixture, id: b05.manuscript, project_id: projectId, title: '血清指标论文', current_revision: 1,
    created_at: time, updated_at: time, versions: [version] }
  const legacyTask = projectType === 'research'
    ? { ...b05TaskFixture, id: b05.task, project_id: projectId, task_type: 'extract_dataset', phase: 'parse', status: 'failed', display_status: 'failed',
      reason_code: null, error_code: null, input_version: { kind: 'excel_structure', structure_id: b05.structure, source_sha256: sha256, parser_version: 'openpyxl-3.1.5-structure-v1' } }
    : { ...roundTask, id: b05.task }
  const workspace = { ...b05WorkspaceFixture, task: legacyTask, wait: null, allowed_actions: projectType === 'research' ? ['retry'] : [],
    source: projectType === 'research' ? { ...b05WorkspaceFixture.source, file_id: fileId, filename: 'serum_data.xlsx', analysis_run_id: null }
      : { file_id: null, filename: '一审意见', analysis_run_id: null, is_current: true },
    artifacts: { figure: null, explanation: null, report: null,
      ...(projectType === 'research' ? { dataset: { filename: 'structure.json', download_url: `${base}/datasets/${b05.structure}/download` } } : {}) } }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.startsWith('/api/v1/projects?type=research')) {
      const items = state.results ? [research] : []
      return Response.json({ items, total: items.length, page: 1, page_size: 100 })
    }
    if (url.startsWith('/api/v1/projects?')) {
      const items = state.projects ? [paper, research] : []
      return Response.json({ items, total: items.length, page: 1, page_size: 12 })
    }
    if (url === base) return Response.json(paper)
    if (url === researchBase) return Response.json({ items: [delivery] })
    if (url === `${researchBase}/${b05.snapshot}`) return Response.json({ ...delivery, feedback: [], package_url: `${researchBase}/${b05.snapshot}/download`,
      members: [member(b05.table, 'survival_table.xlsx', 'xlsx'), member(b05.word, '生存分析.docx', 'docx')] })
    if (url.includes('/members/') && url.endsWith('/download')) return new Response('bytes')
    if (url === base + '/sci-settings') return Response.json({ settings: { article_type: 'research', proposed_title: '血清指标论文',
      target_journal: { choice: 'undecided', name: null }, keywords: ['血清'], findings: [] }, revision: 1 })
    if (url === base + '/thesis-requirements') return Response.json({ revision: 1, keywords: [], sections: [], template: null })
    if (url.startsWith(base + '/files?')) {
      const items = state.uploaded ? [{ id: b05.uploaded, filename: '生存分析.docx', file_type: 'docx', size_bytes: 20480, uploaded_at: time,
        parse_status: 'parsed', error: null, purposes: [], metadata_revision: 1, uploader_recorded: true, sha256 }] : []
      return Response.json({ items, total: items.length, page: 1, page_size: 5 })
    }
    if (url.startsWith(base + '/paper-materials?')) return Response.json({ items: [], targets: [] })
    if (url === base + '/literature/config') return Response.json({ available: false, reason: 'ncbi_not_configured', candidate_limits: [20], default_limit: 20,
      page_size: 10, publication_types: [], full_text_acquisition: false, claim_verification: false })
    if (url.startsWith(base + '/literature/')) return Response.json({ project_id: projectId, items: [], total: 0, page: 1, page_size: 10 })
    if (url === base + '/reviews/inputs') return Response.json({ project_type: projectType, manuscripts: [{ id: b05.manuscript, title: '血清指标论文', current_revision: 1,
      versions: [{ id: b05.version, revision: 1, status: 'published', title: '血清指标论文', created_at: time }] }],
      documents: [], journal_targets: [], school_confirmations: [] })
    if (url === base + '/reviews/rounds') return Response.json({ items: [round] })
    if (url === `${base}/reviews/rounds/${b05.round}`) return Response.json(round)
    if (url === base + '/manuscripts') return Response.json({ items: [manuscript] })
    if (url === base + '/manuscripts/candidates') return Response.json(projectType === 'thesis'
      ? { items: [], citation_drafts: [], methods_fields: [], project_type: 'thesis', thesis: { ready: true, blocking_reasons: [],
        profile: { revision: 1, school: '示例大学', department: '医学院', major: '临床医学', degree_type: '硕士', education_level: '研究生',
          applicable_version: '2026', bound_confirmation_id: b05.confirmation },
        confirmation_id: b05.confirmation, chapters: [{ id: 'chapter-results', title: '第 4 章 研究结果', level: 1 }],
        purposes: ['results', 'discussion', 'other'], template_source_file_ids: [] } }
      : { items: [], citation_drafts: [], methods_fields: [], project_type: 'sci' })
    if (url === `${base}/manuscripts/${b05.manuscript}/versions/1`) return Response.json(manuscript.versions[0])
    if (url === `/api/v1/tasks/${b05.task}/workspace`) return Response.json(workspace)
    if (url === `/api/v1/tasks/${b05.roundTask}/workspace`) return Response.json({ ...workspace, task: roundTask, allowed_actions: [],
      source: { file_id: null, filename: '一审意见', analysis_run_id: null, is_current: true }, artifacts: { figure: null, explanation: null, report: null } })
    if (url.includes('/events')) return Response.json({ task_id: url.split('/')[4], items: [], next_cursor: 0 })
    return Response.json({ items: [], total: 0, page: 1, page_size: 5 })
  }))
}

function checkB05() {
  expect(screen.queryByRole('alert')).toBeNull()
  expect(findTechnicalText(document.body, b05Ids)).toEqual([])
  expect(document.body.textContent).not.toMatch(b05Banned)
  expect(document.querySelectorAll('details')).toHaveLength(0)
}

function visitB05(hash: string) {
  cleanup()
  window.history.replaceState(null, '', hash ? `#${hash}` : window.location.pathname)
  render(<CustomerWorkspace />)
}

describe('thesis cross-module customer pages', () => {
  const projectType = 'thesis'
  beforeEach(() => {
    vi.stubGlobal('URL', class extends URL { static createObjectURL = vi.fn(() => 'blob:x'); static revokeObjectURL = vi.fn() })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  })

  it('walks the writing materials trip to the analysis results and back without identifiers, old wording or folds', async () => {
    const { fireEvent, within } = await import('@testing-library/react')
    const state = { results: true, projects: true, uploaded: false }
    serveB05(projectType, state)
    visitB05(`customer-project=${projectId}&step=materials&view=files`)
    fireEvent.click(await screen.findByRole('button', { name: '从我的分析项目取用成果' }))
    await screen.findByText('正在为“写作资料”取分析成果')
    fireEvent.click(await screen.findByRole('button', { name: /血清分析项目 · 血清指标比较/ }))
    await screen.findByRole('list', { name: '成果文件' })
    expect(screen.queryByText('需放进 Word 后再上传')).toBeNull()
    checkB05()
    fireEvent.click(screen.getByRole('link', { name: '下载 生存分析.docx' }))
    await screen.findByText('下载所需文件后，可以返回 写作资料 继续上传。')
    checkB05()
    state.uploaded = true
    fireEvent.click(screen.getByRole('link', { name: '返回 写作资料' }))
    fireEvent.click(await screen.findByRole('button', { name: '刷新资料' }))
    const list = await screen.findByRole('list', { name: '已上传资料' })
    await within(list).findByText(/来自 血清分析项目 · 血清指标比较/)
    checkB05()
  }, 30000)


})

describe.each(['research', 'thesis'] as const)('B05 old task page (%s)', projectType => {
  it('shows the customer task page without identifiers, internal wording or folds', async () => {
    const { fireEvent } = await import('@testing-library/react')
    serveB05(projectType, { results: true, projects: true, uploaded: false })
    visitB05(`customer-project=${projectId}&step=tasks&task=${b05.task}`)
    await screen.findByRole('heading', { name: '任务详情', level: 1 })
    await screen.findByText(projectType === 'research' ? 'Excel 结构提取' : '意见处理计划', undefined, { timeout: 4000 })
    checkB05()
    // What the task worked on reads as the customer's own material, not frozen or local inputs.
    const facts = document.querySelector('.task-facts')!
    expect(facts.textContent).toContain(projectType === 'research' ? '上传的文件' : '本轮意见和送审稿')
    expect(facts.textContent).not.toMatch(/冻结|本地|固定/)
    for (const view of ['待处理', '成果']) {
      fireEvent.click(screen.getByRole('button', { name: view }))
      checkB05()
    }
  })
})

it.each([['empty', false], ['with projects', true]] as const)('shows the project list %s without identifiers or old wording', async (_name, projects) => {
  serveB05('sci', { results: true, projects, uploaded: false })
  visitB05('')
  await screen.findByRole('heading', { name: '我的项目', level: 1 })
  if (projects) await screen.findByText('血清指标论文')
  else await screen.findByText('还没有项目。新建一个项目，开始数据分析或论文写作。')
  checkB05()
})

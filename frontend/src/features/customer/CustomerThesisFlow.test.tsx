import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { exportFixture, manuscriptFixture, snapshotFixture } from '../manuscripts/manuscriptFixtures'
import CustomerWorkspace from './CustomerWorkspace'

const project = {
  id: 'customer-project-1', name: '客户项目样例', research_topic: '比较病例与对照',
  project_type: 'thesis', file_count: 0, created_at: '2026-11-11T00:00:00Z', updated_at: '2026-11-11T00:00:00Z',
}
const base = '/api/v1/projects/' + project.id
const chapter = { id: 'discussion', title: '讨论', level: 1, purpose: 'discussion', output_language: 'en', result_group_ids: [] }
const profile = { revision: 1, school: '合成大学', department: '', major: '', degree_type: '硕士', education_level: '研究生',
  applicable_version: '2026', bound_confirmation_id: 'confirm1' }
const snapshot = { ...snapshotFixture, project_id: project.id,
  thesis_context: { schema_version: 1, profile, template_version_id: 'template1', confirmation_id: 'confirm1',
    confirmation_sha256: 'a'.repeat(64), confirmation: { chapters: [chapter] }, source_files: [], chapters: [chapter] },
  sections: [{ ...chapter, paragraphs: snapshotFixture.methods }],
  school_content_report: { rules_version: 'school_v1', issues: [], can_publish: true, scientifically_verified: false } }
const first = { ...manuscriptFixture.versions[0], snapshot, exports: [], created_at: '2026-11-19T07:40:00Z' }
const second = { ...first, id: 'v2', revision: 2, parent_version_id: 'v1', task_id: 'draft-2', created_at: '2026-11-19T09:10:00Z',
  snapshot: { ...snapshot, writing_provenance: { provider_provenance: 'synthetic_fixture', verification_status: 'not_verified',
    base_version_id: 'v1', language_review_id: 'school-review', school_export_options: { manual_fields: { author: '合成作者', student_id: '', department: '', major: '', class_name: '', supervisor: '', submission_date: '' }, manual_chapters: [],
      english_title: '', keywords: [], include_toc: true, toc_depth: 3 } } } }

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', window.location.pathname)
})

function open(params: Record<string,string>, extra: (url:string) => unknown) {
  const fetch = vi.fn(async (url: string, init?:RequestInit) => {
    if (init?.method && init.method !== 'GET') throw Error('Reading an archive must not write')
    if (url === base) return Response.json(project)
    const value = extra(url)
    if (value !== undefined) return Response.json(value)
    return new Response(null,{status:404})
  })
  vi.stubGlobal('fetch', fetch)
  window.history.replaceState(null, '', '#' + new URLSearchParams({'customer-project':project.id, ...params}))
  render(<CustomerWorkspace/>)
  return fetch
}

it('downloads the original Word from a bookmarked saved school version, even after a newer draft', async () => {
  const download = base + '/manuscripts/m1/exports/export1/download'
  const fetch = open({step:'word', manuscript:'m1', revision:'2'}, url =>
    url === base + '/manuscripts/m1/versions/2' ? {...second, exports:[{...exportFixture, filename:'归档学位论文.docx',download_url:download}]} : undefined)
  expect((await screen.findByRole('link',{name:'归档学位论文.docx'})).getAttribute('href')).toBe(download)
  expect(screen.getByRole('heading',{name:'文献与初稿'})).toBeTruthy()
  expect(fetch.mock.calls.some(([url])=> url.includes('current-draft'))).toBe(false)
})

it('opens the chosen historical request when the original draft and the revision share the same version number', async () => {
  const versions = ['latest','original'].map(id=>({manuscript_id:'m1', revision:2, request_id:id, title:id,
    created_at:'2026-11-22T10:00:00Z', previous_request_id:id==='latest'?'original':null}))
  const fetch = open({step:'manuscripts',view:'draft-history'}, url =>
    url.endsWith('/draft-history') ? {items:versions} : url.endsWith('/manuscripts') ? {items:[]} : undefined)
  const old = (await screen.findByText('original')).closest('article')!
  fireEvent.click(within(old).getByRole('button',{name:'查看这版正文'}))
  expect(new URLSearchParams(location.hash.slice(1)).get('writingRequest')).toBe('original')
  expect(fetch.mock.calls.some(([url])=> url.includes('/writing-requests/latest'))).toBe(false)
})

it('keeps a missing archived version pinned instead of displaying a newer draft', async () => {
  const fetch = open({step:'word',manuscript:'m1',revision:'99'},()=>undefined)
  await screen.findByRole('alert')
  expect(fetch.mock.calls.some(([url])=>url.includes('/versions/99'))).toBe(true)
  expect(fetch.mock.calls.some(([url])=>url.includes('current-draft'))).toBe(false)
})

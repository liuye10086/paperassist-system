import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
import CustomerProgress from './CustomerProgress'
import { customerBase, type Progress } from './customerWorkspaceApi'

const projectId = 'customer-project-1'
const customer = customerBase(projectId)
const time = '2026-11-18T06:20:00Z'
const later = '2026-11-18T07:02:00Z'

function progress(patch: Partial<Progress>): Progress {
  return { status: 'draft', requirement_version: null, submitted_at: null, updated_at: null, note: null, feedback: [], submissions: [], ...patch }
}

function show(value: Progress, handlers: Partial<Record<'onRequirements' | 'onUpload' | 'onDeliveries', () => void>> = {}) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url === customer + '/progress'
    ? Response.json(value) : Response.json({ detail: { code: 'project_not_found' } }, { status: 404 })))
  render(<CustomerProgress projectId={projectId} headingRef={() => {}} onRequirements={handlers.onRequirements ?? vi.fn()}
    onUpload={handlers.onUpload ?? vi.fn()} onDeliveries={handlers.onDeliveries ?? vi.fn()} registerLeaveGuard={() => () => {}} />)
}

beforeEach(() => setApiSession('csrf', 'customer-test'))
afterEach(() => {
  cleanup()
  setLocale('zh-CN')
  clearApiSession()
  vi.unstubAllGlobals()
})

it('explains an empty project and offers the requirement step', async () => {
  const onRequirements = vi.fn()
  show(progress({}), { onRequirements })
  expect(await screen.findByText('待提交需求')).toBeTruthy()
  expect(screen.getByText('还没有提交需求。选择需要的分析并提交后，管理员会为你分配分析员。')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '去选择需求' }))
  expect(onRequirements).toHaveBeenCalledOnce()
})

it('tells the customer who is working while waiting, without a main action', async () => {
  show(progress({ status: 'pending_assignment', requirement_version: 2, submitted_at: time, updated_at: time }))
  expect(await screen.findByText('待分配')).toBeTruthy()
  expect(screen.getByText('需求已提交，等待分配分析员。你可以离开此页，稍后回到项目查看。')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '补交资料' })).toBeNull()
  expect(screen.queryByRole('button', { name: '去选择需求' })).toBeNull()
})

it('quotes the analyst request when materials are needed', async () => {
  const onUpload = vi.fn()
  show(progress({ status: 'needs_materials', requirement_version: 2, submitted_at: time, updated_at: time, note: '请补充 6 例对照组的分组表。' }), { onUpload })
  expect(await screen.findByText('待补资料')).toBeTruthy()
  expect(screen.getByText('分析员需要你补充：')).toBeTruthy()
  expect(screen.getByText('请补充 6 例对照组的分组表。')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '补交资料' }))
  expect(onUpload).toHaveBeenCalledOnce()
})

it('shows the submitted materials and waits for the analyst to check them', async () => {
  show(progress({
    status: 'materials_submitted', requirement_version: 2, submitted_at: time, updated_at: later, note: '请补充分组表。',
    submissions: [
      { id: 'submission-1', requirement_version: 2, file_ids: ['file-0'], files: [{ id: 'file-0', name: '旧分组表.xlsx' }], note: null, created_at: time },
      { id: 'submission-2', requirement_version: 2, file_ids: ['file-1', 'file-2'], note: '第 4 例样本编号已更正。', created_at: later,
        files: [{ id: 'file-1', name: '对照组分组表.xlsx' }, { id: 'file-2', name: '补充说明.docx' }] },
    ],
  }))
  expect(await screen.findByText('已补交，等待核对')).toBeTruthy()
  const date = new Date(later).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  expect(screen.getByText(`已补交 2 个文件 · ${date}，等待分析员核对`)).toBeTruthy()
  expect(screen.queryByRole('button', { name: '补交资料' })).toBeNull()
  const records = screen.getByRole('list', { name: '补交记录' })
  expect(within(records).getAllByRole('listitem')).toHaveLength(2)
  expect(within(records).getByText('第 4 例样本编号已更正。')).toBeTruthy()
  expect(within(records).getByRole('link', { name: '下载 对照组分组表.xlsx' }).getAttribute('href'))
    .toBe(`/api/v1/projects/${projectId}/files/file-1/download`)
  expect(within(records).getByRole('link', { name: '下载 旧分组表.xlsx' })).toBeTruthy()
})

it('keeps earlier submissions visible after the work returns to an analyst', async () => {
  show(progress({
    status: 'assigned', requirement_version: 2, submitted_at: time, updated_at: later,
    submissions: [{ id: 'submission-1', requirement_version: 2, file_ids: ['file-1'], files: [{ id: 'file-1', name: '分组表.xlsx' }], note: null, created_at: time }],
  }))
  expect(await screen.findByText('已分配')).toBeTruthy()
  expect(within(screen.getByRole('list', { name: '补交记录' })).getByText('分组表.xlsx')).toBeTruthy()
})

it.each([1, 2])('names the submitted state and file count in English (count = %i)', async count => {
  setLocale('en')
  const files = Array.from({ length: count }, (_, index) => ({ id: 'file-' + index, name: 'groups-' + index + '.xlsx' }))
  show(progress({
    status: 'materials_submitted', requirement_version: 2, submitted_at: time, updated_at: later,
    submissions: [{ id: 'submission-1', requirement_version: 2, file_ids: files.map(file => file.id), files, note: null, created_at: later }],
  }))
  expect(await screen.findByText('Materials resubmitted, awaiting review')).toBeTruthy()
  const countLabel = count === 1 ? '1 file' : '2 files'
  const date = new Date(later).toLocaleString('en', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  expect(screen.getByText(`${countLabel} submitted · ${date}, awaiting analyst review`)).toBeTruthy()
  expect(screen.getByText(`${date} · ${countLabel}`)).toBeTruthy()
})

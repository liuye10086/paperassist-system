import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ProjectTasks from './ProjectTasks'
import { legacyTaskFixture, legacyWorkspaceFixture, pageFixture, preparationSourceFixture, preparationTaskFixture, sourceFixture, taskFixture } from './taskFixtures'
import { clearApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); setLocale('zh-CN') })
const props = { projectId: 'p1', active: true, selectedTaskId: '', onSelectTask: vi.fn() }
it('reads only unified project tasks and exposes readable source without internal identifiers', async () => {
  const fetch = vi.fn(async (_url: string) => Response.json(pageFixture)); vi.stubGlobal('fetch', fetch)
  render(<ProjectTasks {...props} />)
  await screen.findByText('实验.xlsx')
  expect(screen.getByText('分析配置 v1')).toBeTruthy()
  expect(fetch.mock.calls[0][0]).toBe('/api/v1/projects/p1/tasks?page=1&page_size=10')
  expect(screen.queryByText('t1')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '查看图表生成任务' }))
  expect(props.onSelectTask).toHaveBeenCalledWith('t1')
})
it('pauses hidden-tab reads, aborts an in-flight poll, and resumes with only one timer', async () => {
  vi.useFakeTimers()
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  const fetch = vi.fn((url: string, init?: RequestInit) => fetch.mock.calls.length === 2
    ? new Promise<Response>(() => { void url; void init }) : Promise.resolve(Response.json(pageFixture)))
  vi.stubGlobal('fetch', fetch); render(<ProjectTasks {...props} />)
  await act(async () => {})
  await act(async () => { vi.advanceTimersByTime(5000) })
  expect(fetch).toHaveBeenCalledTimes(2)
  const signal = fetch.mock.calls[1][1]?.signal
  act(() => { visibility.mockReturnValue('hidden'); document.dispatchEvent(new Event('visibilitychange')) })
  expect(signal?.aborted).toBe(true)
  await act(async () => { vi.advanceTimersByTime(30_000) })
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(screen.getByText('实验.xlsx')).toBeTruthy()
  await act(async () => { visibility.mockReturnValue('visible'); document.dispatchEvent(new Event('visibilitychange')) })
  expect(fetch).toHaveBeenCalledTimes(3)
  await act(async () => { document.dispatchEvent(new Event('visibilitychange')); vi.advanceTimersByTime(5000) })
  expect(fetch).toHaveBeenCalledTimes(4)
})
it('filters on the server and resets pagination without creating tasks', async () => {
  const fetch = vi.fn(async (url: string, _init?: RequestInit) => {
    const q = new URL(url, 'http://local').searchParams
    return Response.json({ ...pageFixture, items: [], total: 0, page: Number(q.get('page')) })
  }); vi.stubGlobal('fetch', fetch); render(<ProjectTasks {...props} />)
  await screen.findByText('此筛选下没有任务。')
  fireEvent.change(screen.getByLabelText('任务状态'), { target: { value: 'failed' } })
  fireEvent.change(screen.getByLabelText('任务类型'), { target: { value: 'explanation' } })
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.includes('status=failed&task_type=explanation'))).toBe(true))
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})
it('does not fetch hidden tasks and clears private content on session change', async () => {
  const fetch = vi.fn(async () => Response.json(pageFixture)); vi.stubGlobal('fetch', fetch)
  const view = render(<ProjectTasks {...props} active={false} />)
  expect(fetch).not.toHaveBeenCalled()
  view.rerender(<ProjectTasks {...props} />); await screen.findByText('实验.xlsx')
  act(() => clearApiSession())
  expect(screen.queryByText('实验.xlsx')).toBeNull()
})
it.each(['zh-CN', 'en'] as const)('displays mixed historical tasks with unknown updated time in %s', async locale => {
  setLocale(locale)
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...pageFixture, total: 2,
    items: [...pageFixture.items, { task: legacyTaskFixture, source: { ...legacyWorkspaceFixture.source, filename: '历史来源.xlsx' } }] })))
  render(<ProjectTasks {...props} />)
  await screen.findByText('历史来源.xlsx')
  expect(screen.getByText(locale === 'en' ? 'Historical task' : '历史任务')).toBeTruthy()
  expect(screen.getByText(locale === 'en' ? 'Not recorded' : '未记录')).toBeTruthy()
  expect(screen.queryByText(legacyTaskFixture.id)).toBeNull()
  expect(document.body.textContent).not.toContain('1970')
  fireEvent.click(screen.getAllByRole('button', { name: locale === 'en' ? 'View Chart generation task' : '查看图表生成任务' })[1])
  expect(props.onSelectTask).toHaveBeenCalledWith(legacyTaskFixture.id)
})
it.each(['zh-CN', 'en'] as const)('identifies local preparation in the task list without inventing an analysis setup in %s', async locale => {
 setLocale(locale)
 vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...pageFixture, items: [{ task: preparationTaskFixture, source: { ...sourceFixture, analysis_run_id: null, dataset_source: preparationSourceFixture } }] })))
 render(<ProjectTasks {...props} />)
 await screen.findByText('实验.xlsx')
 expect(screen.getByText(locale === 'en' ? 'Local dataset preparation' : '本地数据整理')).toBeTruthy()
 expect(screen.getByText(locale === 'en' ? 'Preparation preview' : '整理预览')).toBeTruthy()
 expect(screen.queryByText(/分析配置 v|Analysis setup v/)).toBeNull()
 expect(screen.queryByText(locale === 'en' ? 'Current analysis setup' : '当前分析配置')).toBeNull()
})

it.each([['zh-CN',true],['zh-CN',false],['en',true],['en',false]] as const)('shows frozen literature assistance source instead of statistical setup in %s (current=%s)',async(locale,current)=>{
 setLocale(locale)
 const task={...taskFixture,id:'assistance-list1',task_type:'literature_assistance',phase:current?'plan':'verify',input_version:{kind:'literature_assistance',workflow_version:'literature_assistance_v1',assistance_kind:current?'search_plan':'evidence_review',input_digest:'a'.repeat(64),output_language:'en'}}
 const source={file_id:null,filename:'Synthetic bound research context',analysis_run_id:null,is_current:current}
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({...pageFixture,total:1,items:[{task,source}]})))
 render(<ProjectTasks {...props}/>)
 await screen.findByText('Synthetic bound research context')
 expect(screen.getByText(locale==='en'?'Frozen literature assistance input':'冻结的文献建议输入')).toBeTruthy()
 expect(screen.getByText(locale==='en'?(current?'Bound to the input version at submission':'Bound to a historical claim revision'):(current?'绑定提交时的输入版本':'绑定历史论述版本'))).toBeTruthy()
 expect(screen.queryByText(/分析配置 v|Analysis configuration v|Analysis setup v/)).toBeNull()
 expect(screen.queryByText(/当前分析配置|历史分析配置|Current analysis setup|Historical analysis setup|Current analysis configuration|Historical analysis configuration/)).toBeNull()
 expect(screen.queryByText('assistance-list1')).toBeNull()
})

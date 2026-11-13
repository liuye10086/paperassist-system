import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import App from '../../app/App'
import { summaryFixture } from '../fixtures/summaryFixture'
import { workflowStateFixture } from '../fixtures/workflowStateFixture'

const project = { id: 'chrome-project', name: '导航精简研究', research_topic: '合成资料', project_type: 'research' as const, file_count: 1, created_at: '2026-11-02T00:00:00Z', updated_at: '2026-11-02T00:00:00Z' }
function mount() {
  window.history.replaceState(null, '', '/#project=chrome-project&section=artifacts')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/auth/me')) return Response.json({user:{id:'chrome-user',email:'analyst@example.test',role:'analyst'},csrf_token:'fixture-token'})
    if (url === '/api/v1/projects/chrome-project') return Response.json(project)
    if (url.endsWith('/workflow-state')) return Response.json(workflowStateFixture(project))
    if (url.includes('/summary?')) return Response.json(summaryFixture(project.id))
    if (url.endsWith('/config')) return Response.json({max_upload_bytes:10485760,preview_row_limit:20})
    if (url.endsWith('/files')) return Response.json([])
    if (url.startsWith('/api/v1/assigned-projects?')) return Response.json({items:[],total:0,page:1,page_size:5})
    return Response.json({items:[],total:0,page:1,page_size:10})
  }))
  render(<App />)
}
afterEach(() => {cleanup();vi.unstubAllGlobals();window.history.replaceState(null,'','/')})

it('keeps one project step navigation in the header and hides it when leaving the project',async()=>{
  mount();await screen.findByRole('navigation',{name:'项目操作步骤'})
  const header=screen.getByRole('button',{name:'账号'}).closest('header')!
  expect(within(header).getByText(project.name)).toBeTruthy()
  expect(within(header).getByRole('navigation',{name:'项目操作步骤'})).toBeTruthy()
  expect(screen.getAllByRole('navigation',{name:'项目操作步骤'})).toHaveLength(1)
  fireEvent.click(within(header).getByRole('button',{name:'第 2 步：已提交需求'}))
  expect(window.location.hash).toContain('view=requirements')
  fireEvent.click(screen.getByRole('button',{name:'分配给我的项目'}))
  expect(within(header).queryByRole('navigation',{name:'项目操作步骤'})).toBeNull()
  expect(within(header).queryByText(project.name)).toBeNull()
  expect(within(header).getByText('分配给我的项目')).toBeTruthy()
})

it('keeps analyst workspace actions in the account menu and retains the project',async()=>{
  mount();await screen.findByRole('navigation',{name:'项目操作步骤'})
  const account=screen.getByRole('button',{name:'账号'})
  const header=account.closest('header')!
  expect(account.textContent).toBe('A')
  expect(screen.queryByRole('button',{name:'本人用量'})).toBeNull()
  expect(screen.queryByRole('navigation',{name:'面包屑导航'})).toBeNull()
  expect(screen.queryByLabelText('服务运行提示')).toBeNull()
  expect(screen.queryByText('从一份数据开始')).toBeNull()
  expect(screen.queryByText('界面语言',{exact:true})).toBeNull()
  expect(screen.getByRole('combobox',{name:'界面语言'})).toBeTruthy()
  fireEvent.click(account)
  expect(screen.queryByRole('button',{name:'管理员'})).toBeNull()
  fireEvent.click(screen.getByRole('button',{name:'本人用量'}))
  expect(account.getAttribute('aria-expanded')).toBe('false')
  expect(screen.getByRole('heading',{name:'本人用量'})).toBeTruthy()
  expect(screen.queryByRole('navigation',{name:'项目操作步骤'})).toBeNull()
  expect(within(header).queryByText(project.name)).toBeNull()
  fireEvent.click(account)
  fireEvent.click(screen.getByRole('button',{name:'项目工作区'}))
  expect(screen.getByRole('button',{name:project.name})).toBeTruthy()
  expect(within(header).getByText(project.name)).toBeTruthy()
  expect(screen.getByRole('button',{name:'第 4 步：查看结果'}).getAttribute('aria-current')).toBe('step')
  expect(vi.mocked(fetch).mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)
})

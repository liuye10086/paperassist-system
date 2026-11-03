import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, expect, test, vi } from 'vitest'
import ProjectDetails from './ProjectDetails'
import type { Project } from './projectTypes'

const initial: Project = { id: 'p1', name: '原项目名称', research_topic: '原研究主题', project_type: 'research', file_count: 0, created_at: '2026-11-03T00:00:00Z', updated_at: '2026-11-03T00:00:00Z', default_output_language: 'zh-CN' }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
function Harness() {
  const [project, setProject] = useState(initial)
  return <ProjectDetails project={project} onUpdated={setProject}/>
}

test('saves each visible field independently and preserves the other draft', async () => {
  let saved = initial
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => {
    saved = { ...saved, ...JSON.parse(String(init?.body)) }
    return Response.json(saved)
  })
  vi.stubGlobal('fetch', fetcher)
  const user = userEvent.setup()
  render(<Harness />)
  expect(screen.queryByRole('button', { name: '编辑项目信息' })).toBeNull()
  await user.clear(screen.getByLabelText('修改项目名称'))
  await user.type(screen.getByLabelText('修改项目名称'), '新名称')
  await user.clear(screen.getByLabelText('修改研究主题'))
  await user.type(screen.getByLabelText('修改研究主题'), '另一项未保存主题')
  await user.click(screen.getByRole('button', { name: '保存修改：项目名称' }))
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({ name: '新名称' })
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe('新名称')
  expect((screen.getByLabelText('修改研究主题') as HTMLTextAreaElement).value).toBe('另一项未保存主题')
  await user.click(screen.getByRole('button', { name: '保存修改：研究主题' }))
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
  expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({ research_topic: '另一项未保存主题' })
  expect(screen.getByLabelText('修改项目名称')).toBeTruthy()
  expect(screen.getByLabelText('修改研究主题')).toBeTruthy()
})

test('cancels only the selected field and restores its latest saved value', async () => {
  const fetcher = vi.fn()
  vi.stubGlobal('fetch', fetcher)
  const user = userEvent.setup()
  render(<Harness />)
  await user.type(screen.getByLabelText('修改项目名称'), '草稿')
  await user.type(screen.getByLabelText('修改研究主题'), '草稿')
  await user.click(screen.getByRole('button', { name: '取消修改：研究主题' }))
  expect((screen.getByLabelText('修改研究主题') as HTMLTextAreaElement).value).toBe(initial.research_topic)
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe(initial.name + '草稿')
  await user.click(screen.getByRole('button', { name: '取消修改：项目名称' }))
  expect((screen.getByLabelText('修改项目名称') as HTMLInputElement).value).toBe(initial.name)
  expect(fetcher).not.toHaveBeenCalled()
})

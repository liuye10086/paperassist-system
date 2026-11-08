import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import ProjectWorkspace from './ProjectWorkspace'

vi.mock('./ProjectResources', () => ({
  default: ({ onSaved }: { onSaved: () => void }) => <button type="button" onClick={onSaved}>模拟资料已保存</button>,
}))

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })

test('refreshes workflow state after resources report a saved change', async () => {
  const project = { id: 'p1', name: '连续性测试项目', research_topic: '主链路', project_type: 'research', file_count: 0,
    created_at: '2026-11-08T00:00:00Z', updated_at: '2026-11-08T00:00:00Z' }
  let workflowReads = 0
  const fetcher = vi.fn(async (url: string) => {
    if (url.includes('/workflow-state')) {
      workflowReads += 1
      return Response.json(workflowReads === 1
        ? { project_id: project.id, project_type: project.project_type, files: { total: 0, ready: 0 }, requirements: { saved: false, version: null, services: ['analysis'] }, results: { available: false }, next_step: 'upload' }
        : { project_id: project.id, project_type: project.project_type, files: { total: 1, ready: 1 }, requirements: { saved: false, version: null, services: ['analysis'] }, results: { available: false }, next_step: 'requirements' })
    }
    if (url.endsWith(`/api/v1/projects/${project.id}`)) return Response.json(project)
    return Response.json({ items: [project], total: 1, page: 1, page_size: 5 })
  })
  vi.stubGlobal('fetch', fetcher)
  const user = userEvent.setup()
  render(<ProjectWorkspace />)
  await user.click(await screen.findByRole('button', { name: '打开项目 连续性测试项目' }))
  expect(await screen.findByText('上传并继续')).toBeTruthy()
  await user.click(screen.getByRole('button', { name: '模拟资料已保存' }))
  expect(await screen.findByText('保存需求并继续')).toBeTruthy()
  expect(fetcher.mock.calls.filter(([url]) => String(url).includes('/workflow-state'))).toHaveLength(2)
})

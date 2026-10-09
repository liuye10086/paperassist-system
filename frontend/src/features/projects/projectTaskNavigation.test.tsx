import { act, cleanup, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import WorkspaceShell from './WorkspaceShell'
import useProjectSelection from './useProjectSelection'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })
const project = { id: 'p1', name: '研究', research_topic: '主题', project_type: 'sci', file_count: 0,
  created_at: '2026-10-08T00:00:00Z', updated_at: '2026-10-08T00:00:00Z', default_output_language: 'zh-CN' }
it('adds project tasks to the existing sidebar', () => {
  render(<WorkspaceShell view="project" section="overview" projectName="研究" onNavigate={vi.fn()} onCreate={vi.fn()} onCurrentProject={vi.fn()}><div /></WorkspaceShell>)
  expect(screen.getByRole('button', { name: '项目任务' })).toBeTruthy()
})
it('restores the task deep link and clears it when a different project opens', async () => {
  window.history.replaceState(null, '', '/#project=p1&section=tasks&task=t1')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json({ ...project, id: url.endsWith('p2') ? 'p2' : 'p1' })))
  const { result } = renderHook(() => useProjectSelection(vi.fn(), vi.fn()))
  await waitFor(() => expect(result.current.project?.id).toBe('p1'))
  expect(result.current.section).toBe('tasks'); expect(result.current.taskId).toBe('t1')
  expect(window.location.hash).toBe('#project=p1&section=tasks&task=t1')
  act(() => result.current.open('p2'))
  await waitFor(() => expect(result.current.project?.id).toBe('p2'))
  expect(result.current.taskId).toBe(''); expect(window.location.hash).toBe('#project=p2')
})
it.each(['legacy-plot:', 'legacy-plot:abc/def', 'legacy-plot:b2xk=', 'legacy-other:b2xk', 'legacy-plot:A', 'legacy-plot:YR', 'legacy-plot:_w'])('rejects malformed historical deep link %s', async taskId => {
  window.history.replaceState(null, '', `/#project=p1&section=tasks&task=${encodeURIComponent(taskId)}`)
  vi.stubGlobal('fetch', vi.fn(async () => Response.json(project)))
  const { result } = renderHook(() => useProjectSelection(vi.fn(), vi.fn()))
  await waitFor(() => expect(result.current.project?.id).toBe('p1'))
  expect(result.current.taskId).toBe('')
  expect(window.location.hash).toBe('#project=p1&section=tasks')
})
it.each(['legacy-plot', 'legacy-explanation'])('restores a long canonical %s deep link and clears it on project change', async prefix => {
  const taskId = `${prefix}:${btoa('old-task/'.repeat(100)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')}`
  window.history.replaceState(null, '', `/#project=p1&section=tasks&task=${encodeURIComponent(taskId)}`)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => Response.json({ ...project, id: url.endsWith('p2') ? 'p2' : 'p1' })))
  const { result } = renderHook(() => useProjectSelection(vi.fn(), vi.fn()))
  await waitFor(() => expect(result.current.project?.id).toBe('p1'))
  expect(result.current.taskId).toBe(taskId)
  expect(window.location.hash).toContain(`task=${encodeURIComponent(taskId)}`)
  act(() => result.current.open('p2'))
  await waitFor(() => expect(result.current.project?.id).toBe('p2'))
  expect(result.current.taskId).toBe('')
})
it('preserves current selection when a malformed legacy ID is selected', async () => {
  window.history.replaceState(null, '', '/#project=p1&section=tasks&task=t1')
  vi.stubGlobal('fetch', vi.fn(async () => Response.json(project)))
  const { result } = renderHook(() => useProjectSelection(vi.fn(), vi.fn()))
  await waitFor(() => expect(result.current.project?.id).toBe('p1'))
  act(() => result.current.selectTask('legacy-plot:abc/def'))
  expect(result.current.taskId).toBe('t1')
  expect(window.location.hash).toBe('#project=p1&section=tasks&task=t1')
})

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { homeRoute, parseNavigation, serializeNavigation } from './projectNavigation'
import useProjectSelection from './useProjectSelection'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })
it.each([
  '#project=p1&section=files&view=upload',
  '#project=p1&section=files&view=detail&file=f1',
  '#project=p1&section=files&view=preview&file=f2',
  '#project=p1&section=literature&view=search',
  '#project=p1&section=literature&view=history&search=s1',
  '#project=p1&section=literature&view=detail&reference=r1&search=s1',
  '#project=p1&section=literature&view=evidence',
  '#project=p1&section=literature&view=citations',
])('restores a material or literature destination %s', hash => {
  const route = parseNavigation(hash)
  expect(route).not.toBeNull()
  expect(parseNavigation(serializeNavigation(route!))).toEqual(route)
})
it.each([
  'files&view=detail', 'files&view=list&file=f1', 'files&view=upload&file=f1',
  'files&view=preview&file=../f1', 'files&view=detail&file=f1&file=f2',
  'literature&view=detail', 'literature&view=search&reference=r1',
  'literature&view=unknown', 'literature&view=detail&reference=bad/id',
])('rejects malformed or mismatched entity parameters %s', suffix => {
  expect(parseNavigation('#project=p1&section=' + suffix)).toBeNull()
})
it('preserves old literature search links and defaults list views', () => {
  expect(parseNavigation('#project=p1&section=literature&search=s1')?.literatureNavigation).toEqual({ view: 'list', referenceId: '' })
  expect(parseNavigation('#project=p1&section=files')?.resourceNavigation).toEqual({ view: 'list', fileId: '' })
  expect(serializeNavigation(homeRoute())).toBe('#workspace=home')
})

function Harness() {
  const s = useProjectSelection(() => {}, () => {})
  return <><output>{JSON.stringify({ resources:s.resourceNavigation, literature:s.literatureNavigation, search:s.literatureSearchId })}</output>
    <button onClick={() => s.selectResource({view:'detail',fileId:'f1'})}>file</button>
    <button onClick={() => s.selectLiteratureView({view:'citations',referenceId:''})}>citations</button>
    <button onClick={() => s.selectTask('task1')}>task</button>
    <button onClick={() => s.selectLiterature('search2')}>search results</button>
    <button onClick={() => s.open('p2')}>other project</button></>
}
it('navigates with browser history and clears entity routes across projects', async () => {
  window.history.replaceState(null, '', '/#project=p1&section=files')
  vi.stubGlobal('fetch', vi.fn(async (url:string) => Response.json({id:url.split('/').at(-1),name:'Research',research_topic:'Topic',project_type:'sci',file_count:0,created_at:'2026-10-26T00:00:00Z',updated_at:'2026-10-26T00:00:00Z'})))
  render(<Harness />)
  fireEvent.click(screen.getByText('file'))
  expect(window.location.hash).toContain('view=detail&file=f1')
  fireEvent.click(screen.getByText('citations'))
  expect(window.location.hash).toContain('view=citations')
  await act(async () => { window.history.back() })
  await waitFor(() => expect(window.location.hash).toContain('view=detail&file=f1'))
  expect(screen.getByRole('status').textContent).toContain('"fileId":"f1"')
  fireEvent.click(screen.getByText('other project'))
  expect(window.location.hash).toBe('#project=p2')
  expect(screen.getByRole('status').textContent).toContain('"resources":{"view":"list","fileId":""}')
})
it.each(['citations','evidence','detail&reference=r1'])('opens a task search result in the candidate list after %s', async view => {
  window.history.replaceState(null, '', '/#project=p1&section=literature&view='+view)
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({id:'p1',name:'Research',research_topic:'Topic',project_type:'sci',file_count:0,created_at:'2026-10-26T00:00:00Z',updated_at:'2026-10-26T00:00:00Z'})))
  render(<Harness />)
  fireEvent.click(screen.getByText('task'))
  fireEvent.click(screen.getByText('search results'))
  expect(window.location.hash).toBe('#project=p1&section=literature&search=search2')
  expect(screen.getByRole('status').textContent).toContain('"literature":{"view":"list","referenceId":""}')
})

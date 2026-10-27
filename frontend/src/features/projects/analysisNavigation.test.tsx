import { afterEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { parseNavigation, serializeNavigation } from './projectNavigation'
import useProjectSelection from './useProjectSelection'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })
it.each(['overview','setup','profile','plan','statistics','figure','explanation','report'])('restores analysis view %s with fixed file', view => {
  const route = parseNavigation(`#project=p1&section=analysis&view=${view}&file=f1`)
  expect(route).not.toBeNull()
  expect(route?.analysisNavigation).toEqual({ view, fileId:'f1' })
  expect(parseNavigation(serializeNavigation(route!))).toEqual(route)
})
it.each(['analysis&view=nope','analysis&file=../a','analysis&view=setup&run=latest','analysis&view=plan&view=setup','artifacts&view=detail','artifacts&view=detail&artifact=a&kind=unknown','artifacts&view=list&artifact=a','artifacts&page=0','artifacts&page=1.2'])('rejects malformed analysis/artifact routes %s', suffix => {
  expect(parseNavigation('#project=p1&section='+suffix)).toBeNull()
})
it('round trips fixed artifact identity and originating page', () => {
  const route=parseNavigation('#project=p1&section=artifacts&view=detail&artifact=figure1&kind=figure&page=2')
  expect(route?.artifactNavigation).toEqual({view:'detail',artifactId:'figure1',kind:'figure',page:2})
  expect(parseNavigation(serializeNavigation(route!))).toEqual(route)
})
function Harness() {
  const s=useProjectSelection(()=>{},()=>{})
  return <><output>{JSON.stringify(s.analysisNavigation)}</output>
    <button onClick={()=>s.selectAnalysis({view:'plan',fileId:'f1'})}>plan</button>
    <button onClick={()=>s.selectAnalysis({view:'statistics',fileId:'f1'})}>results</button>
    <button onClick={()=>s.selectArtifact({view:'list',artifactId:'',kind:'',page:1})}>artifacts</button>
    <button onClick={()=>s.selectArtifact({view:'detail',artifactId:'a1',kind:'figure',page:1})}>artifact detail</button>
    <button onClick={()=>s.changeSection('analysis')}>analysis</button>
    <button onClick={()=>s.open('p2')}>other</button></>
}
it('restores the analysis view on back and clears selected file for another project', async()=>{
  window.history.replaceState(null,'','/#project=p1&section=analysis')
  vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json({id:url.split('/').at(-1),name:'Research',research_topic:'Topic',project_type:'sci',file_count:0,created_at:'2026-10-26T00:00:00Z',updated_at:'2026-10-26T00:00:00Z'})))
  render(<Harness/>);fireEvent.click(screen.getByText('plan'));fireEvent.click(screen.getByText('results'))
  await act(async()=>window.history.back())
  await waitFor(()=>expect(screen.getByRole('status').textContent).toContain('"view":"plan"'))
  expect(window.location.hash).toContain('file=f1')
  fireEvent.click(screen.getByText('other'))
  expect(screen.getByRole('status').textContent).toContain('"fileId":""')
})

it('retains the analysis file when browser history traverses another section',async()=>{
  window.history.replaceState(null,'','/#project=p1&section=analysis&view=plan&file=f1')
  vi.stubGlobal('fetch',vi.fn(async()=>Response.json({id:'p1',name:'Research',research_topic:'Topic',project_type:'sci',file_count:0,created_at:'2026-10-26T00:00:00Z',updated_at:'2026-10-26T00:00:00Z'})))
  render(<Harness/>);fireEvent.click(screen.getByText('artifacts'));fireEvent.click(screen.getByText('artifact detail'))
  await act(async()=>window.history.back())
  await waitFor(()=>expect(window.location.hash).toBe('#project=p1&section=artifacts'))
  fireEvent.click(screen.getByText('analysis'))
  expect(window.location.hash).toBe('#project=p1&section=analysis&view=plan&file=f1')
})

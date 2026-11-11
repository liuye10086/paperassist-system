import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {parseNavigation,serializeNavigation} from './projectNavigation'
import useDraftLeaveGuard from './useDraftLeaveGuard'
import useProjectSelection from './useProjectSelection'
afterEach(()=>{cleanup();vi.unstubAllGlobals();window.history.replaceState(null,'','/')})
it.each(['bio-analysis-setup&setup=s1','bio-analysis&run=r1','bio-result&processed=p1&tab=qc','bio-result&processed=p1&tab=spatial','bio-annotation&annotationSet=a1&annotationVersion=v1','bio-figure&figure=f1'])('round trips fixed bio analysis identity %s',suffix=>{
 const hash='#project=project1&section=analysis&view='+suffix
 const route=parseNavigation(hash);expect(route).not.toBeNull();expect(serializeNavigation(route!)).toBe(hash)
})
it.each(['bio-result&processed=p1','bio-result&processed=p1&tab=arbitrary','bio-result&processed=p1&tab=qc&file=f1','bio-analysis&run=r1&setup=s1','bio-analysis-setup','bio-annotation&annotationSet=a1','bio-figure&figure=f1&run=r1','bio-datasets&processed=p1','setup&processed=p1','bio-analysis&run=../private'])('rejects mixed, incomplete or unsafe bio identities %s',suffix=>expect(parseNavigation('#project=p1&section=analysis&view='+suffix)).toBeNull())
function Harness(){const s=useProjectSelection(()=>{},()=>{});return <><output>{JSON.stringify(s.analysisNavigation)}</output><a href="#project=p1&section=analysis&view=bio-result&processed=result1&tab=spatial">same result</a><button onClick={()=>s.open('p2')}>other project</button></>}
function GuardHarness(){const s=useProjectSelection(()=>{},()=>{});return <><output>{JSON.stringify(s.analysisNavigation)}</output><button onClick={()=>s.registerLeaveGuard(()=>false,()=>true)}>register</button><a href="#project=p1&section=analysis&view=bio-analysis-setup&setup=s1">same setup</a><a href="#project=p1&section=analysis&view=bio-datasets">leave setup</a></>}
it('guards a bio draft when a real link leaves the setup and permits same-link navigation',()=>{window.history.replaceState(null,'','/#project=p1&section=analysis&view=bio-analysis-setup&setup=s1');vi.stubGlobal('fetch',vi.fn(async()=>Response.json({})));render(<GuardHarness/>);fireEvent.click(screen.getByText('register'));fireEvent.click(screen.getByText('leave setup'));expect(window.location.hash).toContain('setup=s1');fireEvent.click(screen.getByText('same setup'));expect(screen.getByRole('status').textContent).toContain('"setupId":"s1"')})
it('handles an actual same-link click and clears the private result on project switch',()=>{
 window.history.replaceState(null,'','/#project=p1&section=analysis&view=bio-result&processed=result1&tab=spatial')
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json({id:url.split('/').at(-1),name:'Research',research_topic:'T',project_type:'research',file_count:0,created_at:'x',updated_at:'x'})))
 render(<Harness/>);fireEvent.click(screen.getByRole('link'));expect(screen.getByRole('status').textContent).toContain('"processedId":"result1"');fireEvent.click(screen.getByText('other project'));expect(screen.getByRole('status').textContent).not.toContain('result1')
})

function BulkQcDraftHarness(){
 const selection=useProjectSelection(()=>{},()=>{})
 useDraftLeaveGuard(selection.registerLeaveGuard,true,false)
 return <>
  <a href="#project=p1&section=analysis&view=bulk-workflow&bulkView=data">Data overview</a>
  <a href="#project=p1&section=analysis&view=bio-datasets&bulkView=data">Data import</a>
  <a href="#project=p1&section=analysis&view=bio-analysis-setup&setup=s2&bulkView=qc">Another QC recipe</a>
 </>
}

it('guards a Bulk QC draft when a workflow link would replace its mounted setup',()=>{
 window.history.replaceState(null,'','/#project=p1&section=analysis&view=bio-analysis-setup&setup=s1&bulkView=qc')
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({})))
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
 try{
  render(<BulkQcDraftHarness/>)
  fireEvent.click(screen.getByText('Data overview'))
  expect(window.location.hash).toContain('view=bulk-workflow&bulkView=data')
  expect(confirm).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('Data import'))
  expect(confirm).toHaveBeenCalledTimes(1)
  expect(window.location.hash).toContain('view=bulk-workflow&bulkView=data')
  fireEvent.click(screen.getByText('Another QC recipe'))
  expect(confirm).toHaveBeenCalledTimes(2)
  expect(window.location.hash).toContain('view=bulk-workflow&bulkView=data')
 }finally{confirm.mockRestore()}
})

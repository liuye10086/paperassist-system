import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import useProjectSelection from './useProjectSelection'

afterEach(()=>{cleanup();vi.unstubAllGlobals();window.history.replaceState(null,'','/')})
function Harness(){
 const s=useProjectSelection(()=>{},()=>{})
 return <><button onClick={()=>s.registerLeaveGuard(()=>false,()=>true)}>dirty</button>
 <button onClick={()=>s.selectResource({view:'upload',fileId:''})}>upload</button>
 <button onClick={()=>s.selectResource({view:'quality',fileId:'',bio:{view:'bio-analysis-setup',fileId:'',setupId:'s1'}})}>same setup</button>
 <button onClick={()=>s.selectResource({view:'quality',fileId:'',bio:{view:'bio-datasets',fileId:''}})}>other QC view</button>
 <button onClick={()=>s.selectAnalysis({view:'bio-datasets',fileId:''})}>analysis import</button></>
}
it('retains a hidden quality draft and guards replacement when returning from another module',()=>{
 window.history.replaceState(null,'','/#project=p1&section=files&view=quality&quality=bio-analysis-setup&setup=s1')
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({})))
 render(<Harness/>);fireEvent.click(screen.getByText('dirty'))
 fireEvent.click(screen.getByText('upload'));expect(window.location.hash).toContain('view=upload')
 fireEvent.click(screen.getByText('other QC view'));expect(window.location.hash).toContain('view=upload')
 fireEvent.click(screen.getByText('analysis import'));expect(window.location.hash).toContain('view=upload')
 fireEvent.click(screen.getByText('same setup'));expect(window.location.hash).toContain('setup=s1')
})

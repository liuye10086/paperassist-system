import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import useProjectSelection from './useProjectSelection'
afterEach(()=>{cleanup();vi.unstubAllGlobals();window.history.replaceState(null,'','/')})
function Harness(){
 const s=useProjectSelection(()=>{},()=>{})
 return <><output>{JSON.stringify({manuscript:s.manuscriptLink,view:s.manuscriptView,journal:s.journalView,adaptation:s.adaptationId,school:s.schoolTemplateNavigation})}</output>
 <button onClick={()=>s.selectManuscriptVersion('m2',2)}>version</button>
 <button onClick={()=>s.selectManuscriptView('writing')}>write</button>
 <button onClick={()=>s.selectJournalView('guidelines')}>guidelines</button>
 <button onClick={()=>s.selectJournalView('sources')}>sources</button>
 <button onClick={()=>s.selectJournalAdaptation('a2')}>adaptation2</button>
 <button onClick={()=>s.changeSection('manuscripts')}>manuscripts</button>
 <button onClick={()=>s.selectSchoolTemplate({view:'confirm',templateId:'t1'})}>confirm</button>
 <button onClick={()=>s.open('p2')}>other</button></>
}
function start(){vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json({id:url.split('/').at(-1),name:'Research',research_topic:'Topic',project_type:'thesis',file_count:0,created_at:'2026-10-26T00:00:00Z',updated_at:'2026-10-26T00:00:00Z'})));render(<Harness/>)}
it('preserves an inactive fixed manuscript and task when using history in journals',async()=>{
 window.history.replaceState(null,'','/#project=p1&section=manuscripts&manuscript=m1&revision=1');start()
 fireEvent.click(screen.getByText('version'));fireEvent.click(screen.getByText('write'))
 fireEvent.click(screen.getByText('guidelines'));fireEvent.click(screen.getByText('sources'))
 await act(async()=>window.history.back());await waitFor(()=>expect(window.location.hash).toContain('view=guidelines'))
 fireEvent.click(screen.getByText('manuscripts'))
 expect(window.location.hash).toBe('#project=p1&section=manuscripts&view=writing&manuscript=m2&revision=2')
})
it('clears template and manuscript destinations across projects',()=>{
 window.history.replaceState(null,'','/#project=p1&section=manuscripts&manuscript=m1&revision=1');start()
 fireEvent.click(screen.getByText('confirm'));fireEvent.click(screen.getByText('other'))
 const state=JSON.parse(screen.getByRole('status').textContent!)
 expect(state.manuscript).toEqual({id:'',revision:0});expect(state.school).toEqual({view:'list',templateId:''})
})
it('synchronizes selected adaptation identity and restores an older deep link',async()=>{
 window.history.replaceState(null,'','/#project=p1&section=journals&adaptation=a1');start()
 fireEvent.click(screen.getByText('adaptation2'))
 expect(window.location.hash).toBe('#project=p1&section=journals&adaptation=a2')
 fireEvent.click(screen.getByText('manuscripts'))
 act(()=>{window.history.replaceState(null,'','/#project=p1&section=journals&adaptation=a1');window.dispatchEvent(new HashChangeEvent('hashchange'))})
 await waitFor(()=>expect(JSON.parse(screen.getByRole('status').textContent!).adaptation).toBe('a1'))
})

import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ProjectManuscripts from './ProjectManuscripts'
import {candidatesFixture,manuscriptFixture,snapshotFixture} from './manuscriptFixtures'
import {validSnapshot} from './manuscriptTypes'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('opens a research materials workbench for the selected saved revision',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/candidates')?candidatesFixture:url.endsWith('/context?revision=1')?{}:url.endsWith('/manuscripts')?{items:[manuscriptFixture]}:{items:[]})))
 render(<ProjectManuscripts projectId="p1" researchTopic="Study" outputLanguage="en" active/>);fireEvent.click(await screen.findByRole('button',{name:'查看版本 1'}))
 expect(await screen.findByRole('region',{name:'研究资料与检查'})).toBeTruthy()
})
it('accepts strict fact-ID bindings on displayed legacy paragraphs and rejects mixed or extra binding fields',()=>{
 const snapshot={...snapshotFixture,methods:[{...snapshotFixture.methods[0],numeric_bindings:[{fact_id:'analysis_run:run1:/overall/mean',value:'27.56'}]}]}
 expect(validSnapshot(snapshot,'p1')).toBe(true)
 expect(validSnapshot({...snapshot,methods:[{...snapshot.methods[0],numeric_bindings:[{fact_id:'fact',source_id:'run1',value:'27.56'}]}]},'p1')).toBe(false)
 expect(validSnapshot({...snapshot,methods:[{...snapshot.methods[0],numeric_bindings:[{source_id:'run1',value:'27.56',extra:true}]}]},'p1')).toBe(false)
})

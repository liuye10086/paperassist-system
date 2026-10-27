import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ProjectManuscripts from './ProjectManuscripts'
import {candidatesFixture,manuscriptFixture} from './manuscriptFixtures'

afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const props={projectId:'p1',researchTopic:'Topic',outputLanguage:'en' as const,active:true}
function server(){const fetcher=vi.fn(async(url:string)=>Response.json(url.endsWith('/candidates')?candidatesFixture:url==='/api/v1/projects/p1/manuscripts'?{items:[manuscriptFixture]}:{items:[],pdf_status:'not_requested'}));vi.stubGlobal('fetch',fetcher);return fetcher}
it('starts with a manuscript list and opens a fixed version in the body view',async()=>{
 server();const change=vi.fn(),select=vi.fn();render(<ProjectManuscripts {...props} view="list" onViewChange={change} onSelectVersion={select}/>)
 fireEvent.click(await screen.findByRole('button',{name:'打开稿件'}))
 expect(select).toHaveBeenCalledWith('m1',1);expect(change).toHaveBeenCalledWith('body')
 expect(screen.queryByRole('form',{name:'事实稿资料'})).toBeNull()
 expect(screen.queryByRole('region',{name:'DOCX 导出'})).toBeNull()
})
it('keeps material pages and draft while changing task view and fixed version props',async()=>{
 server();const view=render(<ProjectManuscripts {...props} view="materials"/>)
 await screen.findByRole('checkbox',{name:'固定统计结果'})
 expect(screen.queryByRole('textbox',{name:'研究问题'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'方法'}));fireEvent.change(screen.getByLabelText('研究问题'),{target:{value:'Keep draft'}})
 view.rerender(<ProjectManuscripts {...props} view="body" initialManuscript="m1" initialRevision={1}/>)
 await screen.findByText('Frozen methods')
 expect(screen.queryByRole('textbox',{name:'研究问题'})).toBeNull()
 view.rerender(<ProjectManuscripts {...props} view="materials" initialManuscript="m1" initialRevision={1}/>)
 expect(screen.getByLabelText('研究问题')).toHaveProperty('value','Keep draft')
})
it('keeps writing drafts tied to their version when navigating away and back',async()=>{
 server();const view=render(<ProjectManuscripts {...props} view="writing" initialManuscript="m1" initialRevision={1}/>)
 fireEvent.change(await screen.findByLabelText('自由写作要求'),{target:{value:'Keep writing'}})
 view.rerender(<ProjectManuscripts {...props} view="versions" initialManuscript="m1" initialRevision={1}/>)
 expect(screen.queryByRole('textbox',{name:'自由写作要求'})).toBeNull()
 view.rerender(<ProjectManuscripts {...props} view="writing" initialManuscript="m1" initialRevision={1}/>)
 expect(screen.getByLabelText('自由写作要求')).toHaveProperty('value','Keep writing')
})
it('registers unsaved material drafts without treating an unused idempotency key as pending',async()=>{
 server();let dirty=()=>false;const register=vi.fn((_guard:()=>boolean,isDirty?:()=>boolean)=>{dirty=isDirty??(()=>false);return ()=>{}})
 render(<ProjectManuscripts {...props} view="materials" registerLeaveGuard={register}/>)
 await screen.findByRole('checkbox',{name:'固定统计结果'});expect(dirty()).toBe(false)
 fireEvent.change(screen.getByLabelText('稿件标题'),{target:{value:'Changed'}})
 await waitFor(()=>expect(dirty()).toBe(true))
})
it('keeps separate writing requirements for each fixed version',async()=>{
 const second={...manuscriptFixture.versions[0],id:'v2',revision:2,parent_version_id:'v1',exports:[]}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/candidates')?candidatesFixture:url==='/api/v1/projects/p1/manuscripts'?{items:[{...manuscriptFixture,current_revision:2,versions:[...manuscriptFixture.versions,second]}]}:{items:[]})))
 const view=render(<ProjectManuscripts {...props} view="writing" initialManuscript="m1" initialRevision={1}/>)
 fireEvent.change(await screen.findByRole('textbox',{name:'自由写作要求'}),{target:{value:'Version one'}})
 view.rerender(<ProjectManuscripts {...props} view="writing" initialManuscript="m1" initialRevision={2}/>)
 expect(screen.getByRole('textbox',{name:'自由写作要求'})).toHaveProperty('value','')
 fireEvent.change(screen.getByRole('textbox',{name:'自由写作要求'}),{target:{value:'Version two'}})
 view.rerender(<ProjectManuscripts {...props} view="writing" initialManuscript="m1" initialRevision={1}/>)
 expect(screen.getByRole('textbox',{name:'自由写作要求'})).toHaveProperty('value','Version one')
})
it('does not replace material edits when loading a frozen version is cancelled',async()=>{
 server();vi.stubGlobal('confirm',vi.fn(()=>false))
 const change=vi.fn();const view=render(<ProjectManuscripts {...props} view="materials" initialManuscript="m1" initialRevision={1} onViewChange={change}/>)
 await screen.findByRole('checkbox',{name:'固定统计结果'})
 fireEvent.change(screen.getByLabelText('稿件标题'),{target:{value:'Unsaved material'}})
 view.rerender(<ProjectManuscripts {...props} view="versions" initialManuscript="m1" initialRevision={1} onViewChange={change}/>)
 fireEvent.click(screen.getByRole('button',{name:'以此版本编辑新稿'}))
 expect(window.confirm).toHaveBeenCalled();expect(change).not.toHaveBeenCalled()
 view.rerender(<ProjectManuscripts {...props} view="materials" initialManuscript="m1" initialRevision={1}/>)
 expect(screen.getByLabelText('稿件标题')).toHaveProperty('value','Unsaved material')
})
it('does not change the viewed fixed version or task after a background fact-draft save',async()=>{
 let finish!:(response:Response)=>void
 const result={...manuscriptFixture,current_revision:2,versions:[...manuscriptFixture.versions,{...manuscriptFixture.versions[0],id:'v2',revision:2,parent_version_id:'v1'}]}
 vi.stubGlobal('fetch',vi.fn((url:string,init?:RequestInit)=>init?.method==='POST'?new Promise<Response>(resolve=>{finish=resolve}):Promise.resolve(Response.json(url.endsWith('/candidates')?candidatesFixture:{items:[manuscriptFixture]}))))
 const change=vi.fn();const view=render(<ProjectManuscripts {...props} view="materials" initialManuscript="m1" initialRevision={1} onViewChange={change}/>)
 await screen.findByRole('checkbox',{name:'固定统计结果'})
 fireEvent.click(screen.getByRole('button',{name:'保存并创建事实稿'}))
 view.rerender(<ProjectManuscripts {...props} view="body" initialManuscript="m1" initialRevision={1} onViewChange={change}/>)
 await act(async()=>finish(Response.json(result)))
 expect(screen.getByText('固定版本 1')).toBeTruthy();expect(change).not.toHaveBeenCalled()
 expect(screen.queryByRole('form',{name:'事实稿资料'})).toBeNull()
})

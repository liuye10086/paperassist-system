import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ManuscriptTaskLinks from './ManuscriptTaskLinks'
import {workspaceFixture} from './taskFixtures'
import {manuscriptFixture} from '../manuscripts/manuscriptFixtures'
import type {TaskWorkspace} from './taskTypes'

const second={...manuscriptFixture.versions[0],id:'v2',revision:2,parent_version_id:'v1',exports:[]}
const history={items:[{...manuscriptFixture,current_revision:2,versions:[...manuscriptFixture.versions,second]}]}
function workspace(kind:'manuscript_writing'|'manuscript_draft'|'manuscript_docx',artifact:unknown=null){return {...workspaceFixture,task:{...workspaceFixture.task,task_type:kind,input_version:kind==='manuscript_writing'?{kind:'manuscript_writing',base_version_id:'v1',base_revision:1,output_language:'en',workflow_version:'manuscript_writing_v1'}:{kind:'manuscript',manuscript_version_id:'v1',output_language:'en',workflow_version:'manuscript_fact_draft_v1'}},artifacts:{...workspaceFixture.artifacts,manuscript:artifact}} as unknown as TaskWorkspace}
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it.each([['manuscript_writing','返回稿件写作','writing'],['manuscript_draft','查看此版本稿件','body'],['manuscript_docx','查看此版本的 Word','exports']] as const)('resolves %s to its frozen version rather than current v2',async(kind,label,view)=>{
 const fetcher=vi.fn(async(_url:string,_init?:RequestInit)=>Response.json(history));vi.stubGlobal('fetch',fetcher)
 render(<ManuscriptTaskLinks workspace={workspace(kind)} active/>);expect((await screen.findByRole('link',{name:label})).getAttribute('href')).toBe(`#project=p1&section=manuscripts&view=${view}&manuscript=m1&revision=1`);expect(fetcher.mock.calls.every(([,init])=>!init||!init.method||init.method==='GET')).toBe(true)
})
it('does not substitute the current version when the association is missing',async()=>{vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[]})));render(<ManuscriptTaskLinks workspace={workspace('manuscript_writing')} active/>);expect(await screen.findByText(/无法唯一定位/)).toBeTruthy();expect(screen.queryByRole('link')).toBeNull()})
it('stays on the task when history cannot be read',async()=>{vi.stubGlobal('fetch',vi.fn(async()=>{throw new Error('offline')}));render(<ManuscriptTaskLinks workspace={workspace('manuscript_writing')} active/>);expect(await screen.findByText(/稿件历史读取失败/)).toBeTruthy();expect(screen.queryByRole('link')).toBeNull()})
it('uses the task artifact for a fixed Word version without fetching or generating',async()=>{const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);render(<ManuscriptTaskLinks workspace={workspace('manuscript_docx',{id:'m1',version_id:'v1',revision:1,download_url:null})} active/>);expect((await screen.findByRole('link',{name:'查看此版本的 Word'})).getAttribute('href')).toBe('#project=p1&section=manuscripts&view=exports&manuscript=m1&revision=1');expect(fetcher).not.toHaveBeenCalled()})
it('rejects ambiguous associations rather than picking the first manuscript',async()=>{vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:[history.items[0],history.items[0]]})));render(<ManuscriptTaskLinks workspace={workspace('manuscript_writing')} active/>);expect(await screen.findByText(/无法唯一定位/)).toBeTruthy();expect(screen.queryByRole('link')).toBeNull()})

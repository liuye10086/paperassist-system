import {StrictMode} from 'react'
import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import ResearchIntake from './ResearchIntake'
import {apiFetch} from '../../shared/api/client'
import {emptyRequirement} from './state'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
it('preserves local draft on conflict and reads a specific immutable historical version',async()=>{
 const root={project_id:'p1',revision:1,current_requirement:null,current_design:null,deliveries:[],capabilities:{},gaps:[]};const version={id:'v1',version:1,operation:'save',content:{...emptyRequirement(),notes:'History'},sha256:'a'.repeat(64),created_at:'2026-10-29T00:00:00Z'}
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{const path=String(url);if(init?.method==='POST')return Response.json({detail:{code:'research_intake_revision_conflict'}},{status:409});if(path.endsWith('/research-intake'))return Response.json(root);if(path.endsWith('/files'))return Response.json([]);if(path.endsWith('/requirements/v1'))return Response.json(version);return Response.json({items:[version],total:1})})
 render(<StrictMode><ResearchIntake projectId="p1" active view="requirements"/></StrictMode>);await screen.findByText('尚未保存版本');fireEvent.change(screen.getByLabelText('补充说明'),{target:{value:'My draft'}});fireEvent.click(screen.getByText('保存新版本'));await screen.findByText('服务器已有新版本，草稿已保留。重新读取后核对并合并，再保存。');expect((screen.getByLabelText('补充说明') as HTMLTextAreaElement).value).toBe('My draft');fireEvent.click(screen.getByText(/版本 1 ·/));await waitFor(()=>expect((screen.getByLabelText('补充说明') as HTMLTextAreaElement).value).toBe('History'));expect((screen.getByLabelText('补充说明') as HTMLTextAreaElement).disabled).toBe(true);fireEvent.click(screen.getByText('返回当前草稿'));expect((screen.getByLabelText('补充说明') as HTMLTextAreaElement).value).toBe('My draft')
})

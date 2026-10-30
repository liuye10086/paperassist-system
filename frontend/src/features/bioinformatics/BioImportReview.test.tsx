import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import BioImportReview from './BioImportReview'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
it('keeps confirmation unavailable until candidate exists then sends exact wait and revision',async()=>{
 let ready=false;const fetch=vi.mocked(apiFetch).mockImplementation(async(_url,init)=>{if(init?.method==='POST')return Response.json({});return Response.json({id:'i1',dataset_id:'d1',task:{id:'t1',status:'waiting_confirmation',revision:4},candidate:ready?{sha256:'a'.repeat(64),summary:{},members:[],checks:[]}:null,checkpoint_id:'c1',wait_id:'w1',expected_dataset_revision:2})});render(<BioImportReview projectId="p1" importId="i1" onNavigate={vi.fn()}/>);await screen.findByText('候选尚未就绪，请查看任务状态。');expect(screen.queryByText('确认并发布数据集版本')).toBeNull();ready=true;fireEvent.click(screen.getByText('重新读取导入'));await screen.findByText('确认并发布数据集版本');fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByText('确认并发布数据集版本'));await waitFor(()=>expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(true));const call=fetch.mock.calls.find(([,init])=>init?.method==='POST')!;expect(JSON.parse(String(call[1]!.body))).toEqual({task_revision:4,checkpoint_id:'c1',wait_id:'w1',candidate_sha256:'a'.repeat(64),expected_dataset_revision:2})
})

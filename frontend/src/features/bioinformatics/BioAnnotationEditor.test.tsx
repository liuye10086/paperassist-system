import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import BioAnnotationEditor from './BioAnnotationEditor'
import {processedFixture} from './spatialFixtures'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
it('preserves proposed cluster labels and evidence without claiming a confirmed cell identity',async()=>{vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'annv1',set_id:'ann1',labels:[],regions:[],checks:[],assignments:[],evidence:[]}));render(<BioAnnotationEditor projectId="p1" result={processedFixture} onNavigate={()=>{}}/>);fireEvent.click(screen.getByText('添加人工标签'));fireEvent.change(screen.getByLabelText('标签名称 1'),{target:{value:'SPN-like region'}});fireEvent.change(screen.getByLabelText('cluster ID 列表 1'),{target:{value:'0,1'}});fireEvent.click(screen.getByText('保存人工注释新版本'));await waitFor(()=>expect(apiFetch).toHaveBeenCalled());const body=JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')?.[1]?.body));expect(body.labels[0]).toMatchObject({status:'proposed',name:'SPN-like region',cluster_ids:['0','1']});expect(body.expected_revision).toBe(0);expect(body.processed_dataset_version_id).toBe('processed1')})

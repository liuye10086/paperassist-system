import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import BioUpload from './BioUpload'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
it('reads uncertain upload before retry and retains original registration key',async()=>{
 let registrations=0,uploads=0,saved=false;const keys:string[]=[];const batch=()=>({id:'b1',project_id:'p1',items:[{id:'i1',filename:'raw.tar',size_bytes:1,status:saved?'stored':'pending',file_id:saved?'f1':null}]})
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{if(String(url).endsWith('bio-upload-batches')&&init?.method==='POST'){registrations++;keys.push(new Headers(init.headers).get('Idempotency-Key')!);if(registrations===1)throw Error('lost');return Response.json(batch())}if(String(url).includes('/items/')){uploads++;saved=true;throw Error('lost upload')}if(String(url).endsWith('/b1'))return Response.json(batch());return Response.json({items:[],total:0})})
 render(<BioUpload projectId="p1" onChanged={vi.fn()}/>);fireEvent.change(screen.getByLabelText('选择生信文件'),{target:{files:[new File(['x'],'raw.tar')]}});fireEvent.click(screen.getByText('登记并上传'));await screen.findByText('上传结果尚未核实，先读取原批次；保持原文件和请求身份。');fireEvent.click(screen.getByText('登记并上传'));await waitFor(()=>expect(uploads).toBe(1));fireEvent.click(screen.getByText('重新读取上传批次'));await screen.findByText(/已保存，待生信导入/);expect(keys[0]).toBe(keys[1]);expect(uploads).toBe(1)
})

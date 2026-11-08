import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import BioUpload from './BioUpload'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks();sessionStorage.clear()})
it('reads uncertain upload before retry and retains original registration key',async()=>{
 let registrations=0,uploads=0,saved=false;const keys:string[]=[];const batch=()=>({id:'b1',project_id:'p1',items:[{id:'i1',filename:'raw.tar',size_bytes:1,status:saved?'stored':'pending',file_id:saved?'f1':null}]})
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{if(String(url).endsWith('bio-upload-batches')&&init?.method==='POST'){registrations++;keys.push(new Headers(init.headers).get('Idempotency-Key')!);if(registrations===1)throw Error('lost');return Response.json(batch())}if(String(url).includes('/items/')){uploads++;saved=true;throw Error('lost upload')}if(String(url).endsWith('/b1'))return Response.json(batch());return Response.json({items:[],total:0})})
 render(<BioUpload projectId="p1" onChanged={vi.fn()}/>);fireEvent.change(screen.getByLabelText('选择生信文件'),{target:{files:[new File(['x'],'raw.tar')]}});fireEvent.click(screen.getByText('登记并上传'));await screen.findByText('上传结果尚未核实，先读取原批次；保持原文件和请求身份。');fireEvent.click(screen.getByText('登记并上传'));await waitFor(()=>expect(uploads).toBe(1));fireEvent.click(screen.getByText('重新读取上传批次'));await screen.findByText(/已保存，待生信导入/);expect(keys[0]).toBe(keys[1]);expect(uploads).toBe(1)
})
it('restores an uncertain registration identity across reload without serializing File bytes',async()=>{
 const keys:string[]=[];let attempts=0
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(String(url).endsWith('bio-upload-batches')&&init?.method==='POST'){keys.push(new Headers(init.headers).get('Idempotency-Key')!);attempts++;if(attempts===1)throw Error('lost');return Response.json({id:'b1',project_id:'p1',items:[{id:'i1',filename:'raw.tar',size_bytes:1,status:'pending',file_id:null}]})}
  if(String(url).endsWith('/b1'))return Response.json({id:'b1',project_id:'p1',items:[{id:'i1',filename:'raw.tar',size_bytes:1,status:'pending',file_id:null}]})
  return Response.json({items:[],total:0})
 })
 const view=render(<BioUpload projectId="p1" onChanged={vi.fn()}/>);
 fireEvent.change(screen.getByLabelText('选择生信文件'),{target:{files:[new File(['x'],'raw.tar')]}});fireEvent.click(screen.getByText('登记并上传'))
 await screen.findByText('上传结果尚未核实，先读取原批次；保持原文件和请求身份。');view.unmount()
 render(<BioUpload projectId="p1" onChanged={vi.fn()}/>);
 expect(screen.getByText('上传结果尚未核实，先读取原批次；保持原文件和请求身份。')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'核对登记结果'}));await screen.findByText(/请重新选择名称和大小一致的原文件/)
 expect(keys).toHaveLength(2);expect(keys[0]).toBe(keys[1]);expect(JSON.stringify(Object.values(sessionStorage))).not.toContain('"files":[{}]')
 expect(vi.mocked(apiFetch).mock.calls.some(([url])=>String(url).includes('/items/'))).toBe(false)
})
it('restores a registered partial batch and uploads only a reselected matching pending original',async()=>{
 let stored=false,interrupted=true;const snapshot=()=>({id:'b1',project_id:'p1',items:[{id:'done',filename:'done.h5',size_bytes:1,status:'stored',file_id:'f1'},{id:'todo',filename:'todo.h5',size_bytes:2,status:stored?'stored':'pending',file_id:stored?'f2':null}]})
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(init?.method==='POST'&&String(url).endsWith('bio-upload-batches'))return Response.json(snapshot())
  if(String(url).includes('/items/todo')){if(interrupted){interrupted=false;throw Error('lost')}stored=true;return Response.json(snapshot().items[1])}
  if(String(url).endsWith('/b1'))return Response.json(snapshot())
  return Response.json({items:[],total:0})
 })
 const view=render(<BioUpload projectId="p1" onChanged={vi.fn()}/>);
 fireEvent.change(screen.getByLabelText('选择生信文件'),{target:{files:[new File(['x'],'done.h5'),new File(['xx'],'todo.h5')]}});fireEvent.click(screen.getByText('登记并上传'))
 await screen.findByText('上传结果尚未核实，先读取原批次；保持原文件和请求身份。');view.unmount()
 vi.mocked(apiFetch).mockClear();render(<BioUpload projectId="p1" onChanged={vi.fn()}/>);
 expect(screen.getAllByText(/请重新选择名称和大小一致的原文件/).length).toBeGreaterThan(0)
 fireEvent.click(screen.getByRole('button',{name:'重新读取上传批次'}));await waitFor(()=>expect(screen.queryByText('上传结果尚未核实，先读取原批次；保持原文件和请求身份。')).toBeNull()); fireEvent.change(screen.getByLabelText('重新选择同一文件'),{target:{files:[new File(['xx'],'todo.h5')]}})
 fireEvent.click(screen.getByRole('button',{name:'核对并继续上传'}));await waitFor(()=>expect(stored).toBe(true))
 expect(vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST').map(([url])=>url)).toEqual([expect.stringContaining('/items/todo')])
})

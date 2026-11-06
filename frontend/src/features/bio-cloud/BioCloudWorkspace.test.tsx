import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import BioCloudWorkspace from './BioCloudWorkspace'
import {setApiSession} from '../../shared/api/client'
import {PART_SIZE,cloudStorageKey} from './cloud'
import type {Capabilities} from './cloud'
const profile={id:'profile',name:'STARsolo',species:'human',chemistries:['v3'],engine:'STARsolo',reference_id:'ref',account_verified:true}
const capabilities={enabled:true,provider:'aws',profiles:[profile],blockers:[],part_size:PART_SIZE,evidence:{documentation_supported:true,code_integrated:true,real_data_verified:false}}
const outputs=[{role:'matrix',file_id:'m',filename:'matrix.mtx.gz'},{role:'features',file_id:'f',filename:'features.tsv.gz'},{role:'barcodes',file_id:'b',filename:'barcodes.tsv.gz'}]
function network(cap:Capabilities=capabilities,runs:unknown[]=[]){const mock=vi.fn().mockImplementation(async(url:string,init?:RequestInit)=>Response.json(url.endsWith('/capabilities')?cap:url.endsWith('/uploads')?{items:[{id:'u1',filename:'r1.fastq.gz',status:'completed'},{id:'u2',filename:'r2.fastq.gz',status:'completed'}]}:url.endsWith('/runs')&&init?.method==='POST'?{id:'run1',status:'queued',outputs:[]}:url.endsWith('/runs')?{items:runs}:{}));vi.stubGlobal('fetch',mock);return mock}
beforeEach(()=>{sessionStorage.clear();setApiSession('csrf','alice')})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('blocks unconfigured uploads and submissions while stating evidence limits',async()=>{
 const mock=network({...capabilities,enabled:false,profiles:[],blockers:['account_not_configured']})
 render(<BioCloudWorkspace projectId="p" active onSelectMatrix={()=>{}}/>)
 await screen.findByText(/未开通\/未核验/)
 expect((screen.getByRole('button',{name:'创建上传并续传'}) as HTMLButtonElement).disabled).toBe(true)
 expect((screen.getByRole('button',{name:'提交云分析'}) as HTMLButtonElement).disabled).toBe(true)
 expect(screen.getByText(/真实云验证未执行/)).toBeTruthy()
 expect(mock.mock.calls.every(c=>c[1]?.method!=='POST')).toBe(true)
})
it('submits selected parameters and authorization with one explicit click',async()=>{
 const mock=network();render(<BioCloudWorkspace projectId="p" active onSelectMatrix={()=>{}}/>)
 await screen.findByText('STARsolo · human · ref')
 for(const [label,value] of [['云流程','profile'],['建库 chemistry','v3'],['样本 ID','S'],['文库 ID','L'],['R1 FASTQ','u1'],['R2 FASTQ','u2'],['预算上限（USD）','10.00']])fireEvent.change(screen.getByLabelText(label),{target:{value}})
 expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
 expect(screen.getByText(/点击提交即确认所选材料可交给该境外服务分析/)).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'提交云分析'}))
 await waitFor(()=>expect(mock.mock.calls.filter(c=>c[1]?.method==='POST')).toHaveLength(1))
 expect(JSON.parse(String(mock.mock.calls.find(c=>c[1]?.method==='POST')?.[1]?.body))).toMatchObject({sample_id:'S',library_id:'L',species:'human',chemistry:'v3',budget_approved:true,external_processing_confirmed:true})
})
it('returns matrix output identities without automatically starting import',async()=>{
 const mock=network(capabilities,[{id:'run',status:'completed',sample_id:'S',library_id:'L',engine:'STARsolo',outputs}]);const select=vi.fn()
 render(<BioCloudWorkspace projectId="p" active onSelectMatrix={select}/>)
 fireEvent.click(await screen.findByRole('button',{name:'选择产物进入矩阵导入审核'}))
 expect(select).toHaveBeenCalledWith({matrix:'m',features:'f',barcodes:'b'})
 expect(mock.mock.calls.every(c=>c[1]?.method!=='POST')).toBe(true)
})
it('restores unknown identity and disables new submission, session change stops requests',async()=>{
 sessionStorage.setItem(cloudStorageKey('alice','p'),JSON.stringify({key:'12345678-1234-1234-1234-123456789abc',kind:'run'}))
 const mock=network();render(<BioCloudWorkspace projectId="p" active onSelectMatrix={()=>{}}/>)
 expect(await screen.findByRole('button',{name:'查回原请求'})).toBeTruthy()
 expect((screen.getByRole('button',{name:'提交云分析'}) as HTMLButtonElement).disabled).toBe(true)
 setApiSession('new','bob')
 await waitFor(()=>expect(screen.getByText('会话已改变，请重新进入项目。')).toBeTruthy())
 const count=mock.mock.calls.length;fireEvent.click(screen.getByRole('button',{name:'刷新云状态'}));expect(mock.mock.calls.length).toBe(count)
})
import BioImports from '../bioinformatics/BioImports'
it('BioImports keeps matrix drafts until explicit replacement and selects v4 mtx outputs',async()=>{
 const mock=vi.fn().mockImplementation(async(url:string)=>Response.json(url.endsWith('/capabilities')?capabilities:url.includes('/bio-cloud/uploads')?{items:[]}:url.includes('/bio-cloud/runs')?{items:[{id:'run',status:'completed',sample_id:'S',library_id:'L',engine:'STARsolo',outputs}]}:url.endsWith('/files')?outputs.map(o=>({id:o.file_id,filename:o.filename,file_type:'bio_component'})):{items:[],total:0}))
 vi.stubGlobal('fetch',mock);const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
 render(<BioImports projectId="p" active navigation={{view:'bio-datasets',fileId:''}} onNavigate={()=>{}}/>)
 await screen.findByText('matrix.mtx.gz');fireEvent.change(screen.getByLabelText('数据集名称'),{target:{value:'my draft'}})
 fireEvent.click(screen.getByRole('button',{name:'打开 FASTQ 云端工作区'}));fireEvent.click(await screen.findByRole('button',{name:'选择产物进入矩阵导入审核'}))
 expect((screen.getByLabelText('数据集名称') as HTMLInputElement).value).toBe('my draft')
 confirm.mockReturnValue(true);fireEvent.click(screen.getByRole('button',{name:'选择产物进入矩阵导入审核'}))
 expect((screen.getByLabelText('导入核对流程') as HTMLSelectElement).value).toBe('v4')
 expect((screen.getByLabelText('单细胞矩阵格式') as HTMLSelectElement).value).toBe('mtx')
 expect((screen.getByRole('checkbox',{name:/matrix.mtx.gz/}) as HTMLInputElement).checked).toBe(true)
 expect((screen.getByLabelText('生信文件用途 matrix.mtx.gz') as HTMLSelectElement).value).toBe('matrix')
 expect(mock.mock.calls.every(c=>!String(c[0]).endsWith('/import'))).toBe(true);confirm.mockRestore()
})
it('polls sequentially only while active and never cancels background runs on hide',async()=>{
 const {act}=await import('@testing-library/react');vi.useFakeTimers()
 try{
  const mock=network(capabilities,[{id:'r',status:'running',sample_id:'S',library_id:'L',engine:'STARsolo',outputs:[]}])
  const view=render(<BioCloudWorkspace projectId="p" active onSelectMatrix={()=>{}}/>)
  await act(async()=>{await vi.advanceTimersByTimeAsync(0)})
  const before=mock.mock.calls.length
  await act(async()=>{await vi.advanceTimersByTimeAsync(5000)})
  expect(mock.mock.calls.length).toBe(before+3)
  view.rerender(<BioCloudWorkspace projectId="p" active={false} onSelectMatrix={()=>{}}/>)
  const hidden=mock.mock.calls.length
  await act(async()=>{await vi.advanceTimersByTimeAsync(20000)})
  expect(mock.mock.calls.length).toBe(hidden)
  expect(mock.mock.calls.every(c=>c[1]?.method!=='POST')).toBe(true)
 }finally{vi.useRealTimers()}
})
it('offers provider receipt reconciliation only for an unknown submission without creating another run',async()=>{
 const mock=network(capabilities,[{id:'unknown1',status:'submission_unknown',sample_id:'S',library_id:'L',engine:'STARsolo',outputs:[]}])
 render(<BioCloudWorkspace projectId="p" active onSelectMatrix={()=>{}}/>)
 await screen.findByText(/请先在云控制台核对/)
 fireEvent.change(screen.getByLabelText('云运行 ID'),{target:{value:'provider123'}})
 fireEvent.click(screen.getByRole('button',{name:'按云运行 ID 核对原提交'}))
 await waitFor(()=>expect(mock.mock.calls.some(c=>String(c[0]).endsWith('/runs/unknown1/reconcile'))).toBe(true))
 const call=mock.mock.calls.find(c=>String(c[0]).endsWith('/runs/unknown1/reconcile'))
 expect(JSON.parse(String(call?.[1]?.body))).toEqual({provider_run_id:'provider123'})
 expect(mock.mock.calls.some(c=>String(c[0]).endsWith('/runs')&&c[1]?.method==='POST')).toBe(false)
})
it.each(['failed','blocked'])('can request cancellation of known active remote run when local status is %s',async status=>{
 const mock=network(capabilities,[{id:'local-failed',status,provider_run_id:'remote1',provider_state:'RUNNING',sample_id:'S',library_id:'L',engine:'STARsolo',outputs:[]}])
 render(<BioCloudWorkspace projectId="p" active onSelectMatrix={()=>{}}/>)
 fireEvent.click(await screen.findByRole('button',{name:'请求取消云运行'}))
 await waitFor(()=>expect(mock.mock.calls.some(c=>String(c[0]).endsWith('/runs/local-failed/cancel')&&c[1]?.method==='POST')).toBe(true))
})
it.each(['FAILED','CANCELLED'])('does not offer cancellation after provider terminal state %s',async provider_state=>{
 network(capabilities,[{id:'terminal',status:'blocked',provider_run_id:'remote1',provider_state,sample_id:'S',library_id:'L',engine:'STARsolo',outputs:[]}])
 render(<BioCloudWorkspace projectId="p" active onSelectMatrix={()=>{}}/>)
 await screen.findByText('S / L · STARsolo')
 expect(screen.queryByRole('button',{name:'请求取消云运行'})).toBeNull()
})
it('shows only administrator-verified estimated run fee and separates additional charges',async()=>{
 network({...capabilities,profiles:[{...profile,estimated_run_cost_usd:12.5}]})
 render(<BioCloudWorkspace projectId="p" active onSelectMatrix={()=>{}}/>)
 await screen.findByText('STARsolo · human · ref')
 fireEvent.change(screen.getByLabelText('云流程'),{target:{value:'profile'}})
 expect(screen.getByText('预计单次分析费：USD 12.50（管理员已核实报价）')).toBeTruthy()
 expect(screen.getByText(/只校验已核实的预计单次分析费；S3、网络和日志费用另计/)).toBeTruthy()
})
it('does not invent estimated fee when profile quote is absent',async()=>{
 network();render(<BioCloudWorkspace projectId="p" active onSelectMatrix={()=>{}}/>)
 await screen.findByText('STARsolo · human · ref')
 fireEvent.change(screen.getByLabelText('云流程'),{target:{value:'profile'}})
 expect(screen.getByText('预计单次分析费：待核实；缺少已核实报价时服务端将阻塞提交。')).toBeTruthy()
})

import {afterEach,expect,it,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import BioImports from './BioImports'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks();sessionStorage.clear()})
function responses(url:string,init?:RequestInit){return Promise.resolve(Response.json(init?.method==='POST'?{id:'import1'}:url.endsWith('/files')?[{id:'file1',filename:'matrix.h5',file_type:'bio_component'}]:url.includes('/bio-analysis-runs')?{items:[],total:0}:{items:[{id:'dataset1',name:'Existing Visium',revision:2}],total:1}))}
it('opens the import form from an original and restores its configuration and sample after reload',async()=>{
 vi.mocked(apiFetch).mockImplementation(responses)
 const props={projectId:'p1',active:true,sectioned:true,qualityMode:false,navigation:{view:'bio-datasets' as const,fileId:'file1'},initialFileIds:['file1'],entryKey:'req1:qc',onNavigate:vi.fn()}
 const view=render(<BioImports {...props}/>);
 await screen.findByRole('checkbox',{name:/matrix.h5/})
 expect(screen.getByRole('button',{name:'导入与检查'}).getAttribute('aria-pressed')).toBe('true')
 fireEvent.change(screen.getByLabelText('导入核对流程'),{target:{value:'v4'}})
 fireEvent.change(screen.getByLabelText('单细胞矩阵格式'),{target:{value:'h5ad'}})
 fireEvent.change(screen.getByLabelText('H5AD counts 数据层'),{target:{value:'layers/counts'}})
 fireEvent.change(screen.getByLabelText('数据集名称'),{target:{value:'恢复矩阵'}})
 fireEvent.click(screen.getByRole('button',{name:'填写样本信息'}));fireEvent.change(screen.getByLabelText('样本编号 1'),{target:{value:'S1'}})
 view.unmount();render(<BioImports {...props}/>);
 expect(await screen.findByLabelText('样本编号 1')).toHaveProperty('value','S1')
 expect(screen.getByLabelText('数据集名称')).toHaveProperty('value','恢复矩阵')
 expect(screen.getByLabelText('H5AD counts 数据层')).toHaveProperty('value','layers/counts')
 expect(vi.mocked(apiFetch).mock.calls.some(([,init])=>init?.method==='POST')).toBe(false)
})
it('requires a fresh material read before submitting a restored draft and keeps it blocked on read failure',async()=>{
 vi.mocked(apiFetch).mockImplementation(responses)
 const props={projectId:'p1',active:true,navigation:{view:'bio-datasets' as const,fileId:''},onNavigate:vi.fn()}
 const view=render(<BioImports {...props}/>);await screen.findByText('matrix.h5')
 fireEvent.change(screen.getByLabelText('数据集名称'),{target:{value:'恢复时不得提前提交'}});fireEvent.click(screen.getByRole('checkbox',{name:/matrix.h5/}));view.unmount()
 let rejectRead!:(reason:Error)=>void
 vi.mocked(apiFetch).mockImplementation((url,init)=>String(url).endsWith('/files')?new Promise((_resolve,reject)=>{rejectRead=reject}):responses(url,init))
 render(<BioImports {...props}/>);
 expect(screen.getByRole('button',{name:'开始结构导入'})).toHaveProperty('disabled',true)
 await act(async()=>rejectRead(Error('offline')))
 expect(screen.getByRole('button',{name:'开始结构导入'})).toHaveProperty('disabled',true)
 expect(screen.getByLabelText('数据集名称')).toHaveProperty('value','恢复时不得提前提交')
 expect(screen.getByRole('button',{name:'重新读取导入材料'})).toHaveProperty('disabled',false)
 expect(vi.mocked(apiFetch).mock.calls.some(([,init])=>init?.method==='POST')).toBe(false)
})
it('removes deselected files from sample assignments and keeps the sample editable',async()=>{
 vi.mocked(apiFetch).mockImplementation((url,init)=>url.endsWith('/files')?Promise.resolve(Response.json([
  {id:'file1',filename:'matrix.h5',file_type:'bio_component'},{id:'file2',filename:'other.h5',file_type:'bio_component'},
 ])):responses(url,init))
 render(<BioImports projectId="p1" active navigation={{view:'bio-datasets',fileId:''}} onNavigate={()=>{}}/>)
 await screen.findByText('matrix.h5')
 fireEvent.change(screen.getByLabelText('导入核对流程'),{target:{value:'v4'}})
 fireEvent.change(screen.getByLabelText('单细胞矩阵格式'),{target:{value:'10x_h5'}})
 fireEvent.change(screen.getByLabelText('数据集名称'),{target:{value:'Cells'}})
 fireEvent.click(screen.getByRole('checkbox',{name:/matrix.h5/}))
 const second=screen.getByRole('checkbox',{name:/other.h5/})
 fireEvent.click(second)
 fireEvent.click(screen.getByRole('button',{name:'填写样本信息'}))
 fireEvent.change(screen.getByLabelText('样本编号 1'),{target:{value:'S1'}})
 fireEvent.change(screen.getByLabelText('物种 Taxon ID（正整数） 1'),{target:{value:'9606'}})
 fireEvent.change(screen.getByLabelText('参考标识 1'),{target:{value:'GRCh38'}})
 fireEvent.change(screen.getByLabelText('参考版本 1'),{target:{value:'2024-A'}})
 fireEvent.change(screen.getByLabelText('建库方案 1'),{target:{value:'3prime-v3'}})
 fireEvent.change(screen.getByLabelText('配对编号 1'),{target:{value:'P1'}})
 fireEvent.click(second)
 const start=screen.getByRole('button',{name:'开始结构导入'}) as HTMLButtonElement
 expect(start.disabled).toBe(false)
 fireEvent.click(start)
 await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(call=>call[1]?.method==='POST')).toBe(true))
 const body=JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(call=>call[1]?.method==='POST')?.[1]?.body))
 expect(body.file_ids).toEqual(['file1'])
 expect(body.samples).toEqual([{sample_id:'S1',library_id:'library1',donor:null,batch:null,group:null,species_taxon_id:9606,reference_id:'GRCh38',reference_version:'2024-A',library_chemistry:'3prime-v3',pair_id:'P1',file_ids:['file1']}])
})
it('keeps the exact v1 request body without v2 default fields',async()=>{vi.mocked(apiFetch).mockImplementation(responses);render(<BioImports projectId="p1" active navigation={{view:'bio-datasets',fileId:''}} onNavigate={()=>{}}/>);await screen.findByText('matrix.h5');fireEvent.change(screen.getByLabelText('数据集名称'),{target:{value:'Import'}});fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByText('开始结构导入'));await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(c=>c[1]?.method==='POST')).toBe(true));expect(JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')?.[1]?.body))).toEqual({file_ids:['file1'],assay:'visium',name:'Import',dataset_id:null,expected_dataset_revision:0,roles:{}})})
it('explicitly requests H5 v2 in the existing dataset root without adding a sample',async()=>{vi.mocked(apiFetch).mockImplementation(responses);render(<BioImports projectId="p1" active navigation={{view:'bio-datasets',fileId:''}} onNavigate={()=>{}}/>);await screen.findByText('matrix.h5');fireEvent.change(screen.getByLabelText('导入核对流程'),{target:{value:'v2'}});fireEvent.change(screen.getByLabelText('分析矩阵表示'),{target:{value:'10x_h5'}});fireEvent.click(screen.getByLabelText('实际比较另一矩阵表示'));fireEvent.change(screen.getByLabelText('导入目标'),{target:{value:'dataset1'}});fireEvent.click(screen.getByRole('checkbox',{name:/matrix.h5/}));fireEvent.click(screen.getByText('开始实际矩阵核对'));await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(c=>c[1]?.method==='POST')).toBe(true));expect(JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')?.[1]?.body))).toMatchObject({matrix_representation:'10x_h5',compare_alternate:false,dataset_id:'dataset1',expected_dataset_revision:2});expect(screen.getByText('MTX 与 H5 是同一样本的表示，比较不会增加样本或供体。')).toBeTruthy()})

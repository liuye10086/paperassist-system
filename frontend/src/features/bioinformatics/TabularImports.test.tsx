import {afterEach, expect, it, vi} from 'vitest'
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import BioImports from './BioImports'

vi.mock('../../shared/api/client', () => ({apiFetch:vi.fn(), getApiUserId:()=>'owner1', onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks();sessionStorage.clear()})
const files = [
 {id:'matrix',filename:'measured.xlsx',file_type:'bio_component'},
 {id:'samples',filename:'samples.tsv',file_type:'bio_component'},
 {id:'features',filename:'features.csv',file_type:'bio_component'},
]
function mockRequests(failPost=false) {
 vi.mocked(apiFetch).mockImplementation(async(url, init)=>{
  if(init?.method==='POST') {if(failPost)throw Error('connection lost');return Response.json({id:'import-new'})}
  if(String(url).includes('/bio-requests/'))return Response.json({kind:'import',id:'import-new',root_id:'dataset-new',request_digest:'a'.repeat(64)})
  return Response.json(String(url).endsWith('/files')?files:{items:[],total:0})
 })
}
async function fill() {
 await screen.findByText('measured.xlsx')
 fireEvent.change(screen.getByLabelText('导入核对流程'),{target:{value:'v3'}})
 fireEvent.change(screen.getByLabelText('数据类型'),{target:{value:'metabolomics'}})
 fireEvent.change(screen.getByLabelText('数据集名称'),{target:{value:'Measured metabolites'}})
 fireEvent.change(screen.getByLabelText('定量矩阵原件'),{target:{value:'matrix'}})
 fireEvent.change(screen.getByLabelText('定量矩阵工作表名称'),{target:{value:'Quantification'}})
 fireEvent.change(screen.getByLabelText('样本信息原件'),{target:{value:'samples'}})
 fireEvent.change(screen.getByLabelText('特征注释原件（可选）'),{target:{value:'features'}})
 fireEvent.change(screen.getByLabelText('样本列名（每行一个，保留原始顺序）'),{target:{value:'S1\nS2\nS3\nS4'}})
 fireEvent.change(screen.getByLabelText('输入数值尺度'),{target:{value:'log10'}})
 fireEvent.change(screen.getByLabelText('数值单位'),{target:{value:'log10 normalized intensity'}})
 fireEvent.change(screen.getByLabelText('上游定量与处理方法'),{target:{value:'LC-HRMS, drift and osmolarity normalization, log10'}})
}
it('submits a frozen nonspatial request with explicit sheet, scale and sample axis',async()=>{
 mockRequests();const navigate=vi.fn()
 render(<BioImports projectId="p1" active navigation={{view:'bio-datasets',fileId:''}} onNavigate={navigate}/>)
 await fill();fireEvent.click(screen.getByText('开始定量矩阵核对'))
 await waitFor(()=>expect(navigate).toHaveBeenCalledWith({view:'bio-import',fileId:'',importId:'import-new'}))
 const request=JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')?.[1]?.body))
 expect(request).toMatchObject({workflow_version:'bio_import_v3',assay:'metabolomics',file_ids:['matrix','samples','features'],sample_columns:['S1','S2','S3','S4'],feature_id_column:'feature_id',scale:{kind:'log10',unit:'log10 normalized intensity'},tables:[{file_id:'matrix',role:'quantitative_matrix',format:'xlsx',sheet:'Quantification'},{file_id:'samples',role:'sample_metadata',format:'tsv'},{file_id:'features',role:'feature_metadata',format:'csv'}]})
 expect(request).not.toHaveProperty('roles');expect(request).not.toHaveProperty('matrix_representation')
})
it('requires a declared worksheet and distinct originals before submitting',async()=>{
 mockRequests();render(<BioImports projectId="p1" active navigation={{view:'bio-datasets',fileId:''}} onNavigate={()=>{}}/>)
 await fill();fireEvent.change(screen.getByLabelText('定量矩阵工作表名称'),{target:{value:''}})
 expect((screen.getByText('开始定量矩阵核对') as HTMLButtonElement).disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('定量矩阵工作表名称'),{target:{value:'Quantification'}})
 fireEvent.change(screen.getByLabelText('样本信息原件'),{target:{value:'matrix'}})
 expect((screen.getByText('开始定量矩阵核对') as HTMLButtonElement).disabled).toBe(true)
 expect(vi.mocked(apiFetch).mock.calls.filter(c=>c[1]?.method==='POST')).toHaveLength(0)
})
it('preserves the unknown request identity and resolves it without a second POST',async()=>{
 mockRequests(true);const navigate=vi.fn()
 render(<BioImports projectId="p1" active navigation={{view:'bio-datasets',fileId:''}} onNavigate={navigate}/>)
 await fill();fireEvent.click(screen.getByText('开始定量矩阵核对'))
 const lookup=await screen.findByText('按原请求身份核对')
 expect((screen.getByText('开始定量矩阵核对') as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(lookup)
 await waitFor(()=>expect(navigate).toHaveBeenCalledWith({view:'bio-import',fileId:'',importId:'import-new'}))
 expect(vi.mocked(apiFetch).mock.calls.filter(c=>c[1]?.method==='POST')).toHaveLength(1)
})
it('protects sample-axis-only and scale-only drafts before any original or name is selected',async()=>{
 mockRequests();let dirty=()=>false
 render(<BioImports projectId="p1" active navigation={{view:'bio-datasets',fileId:''}} onNavigate={()=>{}} registerLeaveGuard={(_guard,isDirty)=>{dirty=isDirty??(()=>false);return()=>{}}}/>)
 await screen.findByText('measured.xlsx');fireEvent.change(screen.getByLabelText('导入核对流程'),{target:{value:'v3'}})
 expect(dirty()).toBe(false)
 fireEvent.change(screen.getByLabelText('样本列名（每行一个，保留原始顺序）'),{target:{value:'S1\nS2'}})
 expect(dirty()).toBe(true)
 fireEvent.change(screen.getByLabelText('样本列名（每行一个，保留原始顺序）'),{target:{value:''}})
 expect(dirty()).toBe(false)
 fireEvent.change(screen.getByLabelText('上游定量与处理方法'),{target:{value:'Measured original counts'}})
 expect(dirty()).toBe(true)
 fireEvent.change(screen.getByLabelText('导入核对流程'),{target:{value:'v1'}})
 expect(dirty()).toBe(true)
})

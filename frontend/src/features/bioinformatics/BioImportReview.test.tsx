import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import BioImportReview from './BioImportReview'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
it.each(['single_cell','visium'])('describes spatial-only checks according to the frozen %s import',async assay=>{
 const single=assay==='single_cell'
 const spatial=[['positions_count','坐标数量',single?0:12],['in_tissue_count','组织内观测数',single?null:9],['matrix_barcodes_in_positions','矩阵条码具备位置',single?null:true],['matrix_matches_in_tissue','矩阵与组织内条码一致性',single?null:true]] as const
 const input_version=single?{kind:'bio_import',workflow_version:'bio_import_v4',parser_version:'single_cell_import_v1',assay}:{kind:'bio_import',workflow_version:'bio_import_v1',parser_version:'geo_visium_import_v1'}
 const checks=[...spatial.map(([code,,value])=>({code,value,status:'passed'})),{code:'duplicate_symbol_groups',value:0,status:'passed'},{code:'structure',value:'checked',status:'passed'}]
 vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'i1',dataset_id:'d1',task:{id:'t1',status:'waiting_confirmation',revision:1,input_version},candidate:{sha256:'a'.repeat(64),summary:{},members:[],checks}}))
 render(<BioImportReview projectId="p1" importId="i1" onNavigate={()=>{}}/>)
 const table=within(await screen.findByRole('table',{name:'核对结果'}))
 for(const [,label] of spatial){
  const row=table.getByRole('row',{name:new RegExp(label)})
  expect(within(row).getByText(single?'不适用':'已通过')).toBeTruthy()
 }
 const zero=within(table.getByRole('row',{name:/重复基因符号组数/}))
 expect(zero.getByText('已通过')).toBeTruthy()
 expect(zero.getByText('0')).toBeTruthy()
 expect(within(table.getByRole('row',{name:/文件结构/})).getByText('已通过')).toBeTruthy()
})
it('keeps confirmation unavailable until candidate exists then sends exact wait and revision',async()=>{
 let ready=false;const fetch=vi.mocked(apiFetch).mockImplementation(async(_url,init)=>{if(init?.method==='POST')return Response.json({});return Response.json({id:'i1',dataset_id:'d1',task:{id:'t1',status:'waiting_confirmation',revision:4},candidate:ready?{sha256:'a'.repeat(64),summary:{},members:[],checks:[]}:null,checkpoint_id:'c1',wait_id:'w1',expected_dataset_revision:2})});render(<BioImportReview projectId="p1" importId="i1" onNavigate={vi.fn()}/>);await screen.findByText('候选尚未就绪，请查看任务状态。');expect(screen.queryByText('确认并发布数据集版本')).toBeNull();ready=true;fireEvent.click(screen.getByText('重新读取导入'));await screen.findByText('确认并发布数据集版本');fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByText('确认并发布数据集版本'));await waitFor(()=>expect(fetch.mock.calls.some(([,init])=>init?.method==='POST')).toBe(true));const call=fetch.mock.calls.find(([,init])=>init?.method==='POST')!;expect(JSON.parse(String(call[1]!.body))).toEqual({task_revision:4,checkpoint_id:'c1',wait_id:'w1',candidate_sha256:'a'.repeat(64),expected_dataset_revision:2})
})

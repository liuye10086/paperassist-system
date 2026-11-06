import {afterEach, expect, it, vi} from 'vitest'
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import SingleCellDirectStart from './SingleCellDirectStart'
import SingleCellIntegrationResult from './SingleCellIntegrationResult'
import SingleCellIntegrationFields from './SingleCellIntegrationFields'
import {capabilitiesFixture, rawFixture} from './spatialFixtures'

vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks();sessionStorage.clear()})

const newDefaults={...capabilitiesFixture.default_params,hvg_batch_key:'batch',technical_covariates:['log1p_total_counts'],harmony:{enabled:true,batch_key:'batch',theta:2,lambda:1,max_iter:10}}

it('shows enabled new defaults and submits edited integration settings in one analysis',async()=>{
 const navigate=vi.fn()
 vi.mocked(apiFetch).mockImplementation(async(_url,init)=>Response.json(init?.method==='POST'?{id:'run3',task:{id:'task3'}}:{...capabilitiesFixture,default_params:newDefaults}))
 render(<SingleCellDirectStart projectId="p1" source={rawFixture} onNavigate={navigate}/>)
 expect((await screen.findByLabelText('运行 Harmony 批次整合') as HTMLInputElement).checked).toBe(true)
 expect((screen.getByLabelText('处理测序深度（log1p total counts）') as HTMLInputElement).checked).toBe(true)
 expect((screen.getByLabelText('处理线粒体比例') as HTMLInputElement).disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('HVG 批次分组'),{target:{value:'library_id'}})
 fireEvent.change(screen.getByLabelText('Harmony 批次分组'),{target:{value:'library_id'}})
 fireEvent.change(screen.getByLabelText('Harmony theta'),{target:{value:'3'}})
 fireEvent.click(screen.getByRole('button',{name:'开始单细胞分析'}))
 await waitFor(()=>expect(navigate).toHaveBeenCalledWith({view:'bio-analysis',fileId:'',runId:'run3'}))
 const posts=vi.mocked(apiFetch).mock.calls.filter(c=>c[1]?.method==='POST')
 expect(posts).toHaveLength(1)
 const params=JSON.parse(String(posts[0][1]?.body)).params
 expect(params.hvg_batch_key).toBe('library_id')
 expect(params.technical_covariates).toEqual(['log1p_total_counts'])
 expect(params.harmony).toEqual({enabled:true,batch_key:'library_id',theta:3,lambda:1,max_iter:10})
})

it('allows users to disable both methods without silently restoring defaults',async()=>{
 vi.mocked(apiFetch).mockImplementation(async(_url,init)=>Response.json(init?.method==='POST'?{id:'run4',task:{id:'task4'}}:{...capabilitiesFixture,default_params:newDefaults}))
 render(<SingleCellDirectStart projectId="p1" source={rawFixture} onNavigate={()=>{}}/>)
 fireEvent.click(await screen.findByLabelText('运行 Harmony 批次整合'))
 fireEvent.click(screen.getByLabelText('处理测序深度（log1p total counts）'))
 fireEvent.change(screen.getByLabelText('HVG 批次分组'),{target:{value:''}})
 fireEvent.click(screen.getByRole('button',{name:'开始单细胞分析'}))
 await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(c=>c[1]?.method==='POST')).toBe(true))
 const params=JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST')![1]!.body)).params
 expect(params.harmony.enabled).toBe(false)
 expect(params.technical_covariates).toEqual([])
 expect(params.hvg_batch_key).toBeNull()
})

it('reports applied methods and the actual downstream representation',()=>{
 render(<SingleCellIntegrationResult summary={{single_cell_integration:{hvg:{status:'completed',strategy:'batch_aware_seurat',batch_key:'batch'},technical_covariates:{status:'completed',applied:true,columns:['log1p_total_counts']},harmony:{status:'completed',applied:true},design:{status:'unknown',reason:'group_missing'},downstream_representation:'X_pca_harmony',versions:{harmony:'1.2.3'}}}}/>)
 expect(screen.getByText(/邻居、UMAP 与聚类实际使用：Harmony 整合表示/)).toBeTruthy()
 expect(screen.getByText(/原始 counts、normalized 和 log1p 保留/)).toBeTruthy()
 expect(screen.getByText(/log1p_total_counts/)).toBeTruthy()
 expect(screen.getByText(/批次感知 HVG；分组字段：batch/)).toBeTruthy()
})

it('shows blocked integration as unapplied and PCA fallback without claiming success',()=>{
 render(<SingleCellIntegrationResult summary={{single_cell_integration:{hvg:{status:'completed',strategy:'global_seurat',batch_key:'batch',fallback:true,reason:'batch_values_missing'},technical_covariates:{status:'not_computable',applied:false,reason:'covariate_constant'},harmony:{status:'not_computable',applied:false,reason:'batch_group_completely_confounded'},design:{status:'confounded'},downstream_representation:'X_pca'}}}/>)
 expect(screen.getByText(/邻居、UMAP 与聚类实际使用：PCA 表示/)).toBeTruthy()
 expect(screen.getAllByText(/不可计算；未应用/)).toHaveLength(2)
 expect(screen.getByText(/批次与研究组完全混杂/)).toBeTruthy()
 expect(screen.getByText(/已回退到全局 HVG/)).toBeTruthy()
 expect(screen.getByText('缺少完整批次信息')).toBeTruthy()
})

it('allows removal of an already selected mitochondrial covariate after rule invalidation',()=>{
 const change=vi.fn()
 render(<SingleCellIntegrationFields params={{...capabilitiesFixture.default_params,technical_covariates:['log1p_total_counts','mt_fraction']}} onChange={change}/>)
 const option=screen.getByLabelText('处理线粒体比例') as HTMLInputElement
 expect(option.checked).toBe(true)
 expect(option.disabled).toBe(false)
 fireEvent.click(option)
 expect(change.mock.calls[0][0].technical_covariates).toEqual(['log1p_total_counts'])
})

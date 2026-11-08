import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import BioDatasetDetail from './BioDatasetDetail'
import BioImportReview from './BioImportReview'
import BioAnalysisReview from './BioAnalysisReview'
import BioAnalysisSetup from './BioAnalysisSetup'
import {capabilitiesFixture,runFixture,setupFixture} from './spatialFixtures'

vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
vi.mock('../../shared/components/ProjectDownloadLink',()=>({default:({children}:{children:import('react').ReactNode})=><span>{children}</span>}))
afterEach(()=>{cleanup();vi.clearAllMocks();sessionStorage.clear()})

it('switches dataset modules and retains the loaded bounded matrix preview',async()=>{
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('/matrix-preview')?{features:['gene1'],observations:['AA-1'],values:[[3]]}:{id:'v1',dataset_id:'d1',version:1,shape:{features:1,observations:1},checks:[],members:[],summary:{}}))
 render(<BioDatasetDetail projectId="p1" datasetId="d1" versionId="v1"/>)
 await screen.findByRole('region',{name:'数据概况'})
 expect(screen.queryByRole('region',{name:'矩阵预览'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'矩阵预览'}))
 fireEvent.click(screen.getByRole('button',{name:'读取有界矩阵预览'}))
 await screen.findByText('gene1')
 fireEvent.click(screen.getByRole('button',{name:'数据概况'}))
 fireEvent.click(screen.getByRole('button',{name:'矩阵预览'}))
 expect(screen.getByRole('columnheader',{name:'gene1'})).toBeTruthy()
 expect(vi.mocked(apiFetch).mock.calls.filter(([url])=>String(url).includes('/matrix-preview'))).toHaveLength(1)
})

it('keeps import acceptance and confirmation outside the switchable review modules',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'i1',dataset_id:'d1',task:{id:'t1',status:'waiting_confirmation',revision:4},candidate:{sha256:'a'.repeat(64),summary:{},members:[],checks:[]},checkpoint_id:'c1',wait_id:'w1',expected_dataset_revision:2}))
 render(<BioImportReview projectId="p1" importId="i1" onNavigate={()=>{}}/>)
 await screen.findByRole('region',{name:'文件结构'})
 fireEvent.click(screen.getByRole('checkbox'))
 fireEvent.click(screen.getByRole('button',{name:'研究设计'}))
 expect(screen.queryByRole('region',{name:'文件结构'})).toBeNull()
 expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(true)
 expect((screen.getByRole('button',{name:'确认并发布数据集版本'}) as HTMLButtonElement).disabled).toBe(false)
})

it('keeps QC acceptance available while reviewing effective parameters',async()=>{
 vi.mocked(apiFetch).mockResolvedValue(Response.json(runFixture))
 render(<BioAnalysisReview projectId="p1" runId="run1" onNavigate={()=>{}}/>)
 await screen.findByRole('region',{name:'QC 概况'})
 fireEvent.click(screen.getByRole('checkbox'))
 fireEvent.click(screen.getByRole('button',{name:'有效参数'}))
 expect(screen.queryByRole('region',{name:'QC 概况'})).toBeNull()
 expect(screen.getByRole('region',{name:'有效参数'})).toBeTruthy()
 expect((screen.getByRole('button',{name:'确认此 QC 候选并继续计算'}) as HTMLButtonElement).disabled).toBe(false)
})

it('preserves unsaved recipe values when switching configuration modules',async()=>{
 vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('capabilities')?capabilitiesFixture:setupFixture))
 render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>)
 const input=await screen.findByLabelText('最低 counts')
 fireEvent.change(input,{target:{value:'12'}})
 fireEvent.click(screen.getByRole('button',{name:'能力与来源'}))
 await waitFor(()=>expect(screen.getByText('donor_unknown')).toBeTruthy())
 expect(screen.queryByRole('region',{name:'分析参数'})).toBeNull()
 expect((screen.getByRole('button',{name:'保存新配方版本'}) as HTMLButtonElement).disabled).toBe(false)
 expect((screen.getByRole('button',{name:'开始分析'}) as HTMLButtonElement).disabled).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'分析参数'}))
 expect((screen.getByLabelText('最低 counts') as HTMLInputElement).value).toBe('12')
 expect(document.querySelector('details,summary')).toBeNull()
})

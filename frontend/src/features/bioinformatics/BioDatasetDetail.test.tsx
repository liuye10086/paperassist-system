import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react'
import BioDatasetDetail from './BioDatasetDetail'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),onApiSessionChanged:()=>()=>{}}))
vi.mock('../../shared/components/ProjectDownloadLink',()=>({default:({children}:{children:import('react').ReactNode})=><span>{children}</span>}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
it('shows feature IDs and symbols while preserving separate columns for duplicate symbols',async()=>{
 vi.mocked(apiFetch).mockImplementation(async url=>String(url).includes('/matrix-preview')?Response.json({features:[{id:'ENSG001',symbol:'DUP',feature_type:'Gene Expression'},{id:'ENSG002',symbol:'DUP',feature_type:'Gene Expression'}],observations:['AA-1'],values:[[3,8]]}):Response.json({id:'v1',dataset_id:'d1',version:1,shape:{features:2,observations:1,stored_entries:2},checks:[],members:[],summary:{}}))
 render(<BioDatasetDetail projectId="p1" datasetId="d1" versionId="v1"/>);fireEvent.click(await screen.findByText('读取有界矩阵预览'))
 const table=await screen.findByRole('table',{name:'少量原始矩阵值；保留稳定标识，未标准化或筛选。'});expect(within(table).getByRole('columnheader',{name:/ENSG001.*DUP/})).toBeTruthy();expect(within(table).getByRole('columnheader',{name:/ENSG002.*DUP/})).toBeTruthy();expect(within(table).getAllByText('DUP')).toHaveLength(2);expect(within(table).getAllByRole('cell').map(cell=>cell.textContent)).toEqual(['3','8'])
})

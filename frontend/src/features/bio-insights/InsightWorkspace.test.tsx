import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import BioInsightsWorkspace from './BioInsightsWorkspace'
import {apiFetch} from '../../shared/api/client'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner',onApiSessionChanged:()=>()=>{}}))
vi.mock('./InsightPlanEditor',()=>({default:()=> <p>plan editor</p>,InsightRun:()=> <p>run reader</p>}))
afterEach(cleanup)
it('opens unrelated runs and results without carrying the previously viewed plan identity',async()=>{const navigate=vi.fn();vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).includes('/bio-insight-runs?')?{items:[{id:'runB',kind:'comparison',plan_version_id:'versionB',task:{status:'succeeded'},result_version_id:'resultB'}],total:1,page:1,page_size:20}:String(url).includes('/bio-insight-plans/planA/')?{id:'versionA',plan_id:'planA',kind:'comparison',config:{},sources:[]}:{items:[],total:0}));render(<BioInsightsWorkspace projectId="p1" navigation={{view:'bio-insight-plan',fileId:'',planId:'planA',planVersionId:'versionA'}} active onNavigate={navigate}/>);fireEvent.click(await screen.findByText(/固定设计差异比较 · succeeded · runB/));expect(navigate).toHaveBeenLastCalledWith({view:'bio-insight-plan',fileId:'',runId:'runB'});fireEvent.click(screen.getByRole('button',{name:'查看固定结果',hidden:true}));expect(navigate).toHaveBeenLastCalledWith({view:'bio-insight-result',fileId:'',resultVersionId:'resultB'})})

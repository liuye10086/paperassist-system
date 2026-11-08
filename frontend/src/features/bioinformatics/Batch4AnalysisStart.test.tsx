import {afterEach,expect,it,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import BioSpatialWorkspace from './BioSpatialWorkspace'
import {capabilitiesFixture,rawFixture,recipeFixture,setupFixture} from './spatialFixtures'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks();sessionStorage.clear()})
function open(allowNewAnalysis=true){return render(<BioSpatialWorkspace projectId="p1" navigation={{view:'bio-analysis-setup',fileId:'',setupId:'setup1'}} onNavigate={()=>{}} allowNewAnalysis={allowNewAnalysis}/>)}
function response(url:unknown){return Response.json(String(url).includes('capabilities')?capabilitiesFixture:setupFixture)}
it('starts an unchanged recipe directly without an extra recipe POST',async()=>{
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>init?.method==='POST'?Response.json({id:'run1'}):response(url))
 open();const start=await screen.findByRole('button',{name:'开始分析'});await waitFor(()=>expect((start as HTMLButtonElement).disabled).toBe(false));fireEvent.click(start);await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1))
 expect(JSON.parse(String(vi.mocked(apiFetch).mock.calls.find(([,init])=>init?.method==='POST')?.[1]?.body))).toMatchObject({recipe_version_id:'recipe1',expected_setup_revision:1})
})
it('saves mapping then recipe then run from one final click and uses returned exact identities',async()=>{
 let finish!:(value:Response)=>void
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(init?.method!=='POST')return response(url)
  if(String(url).endsWith('/bio-observation-maps'))return new Promise<Response>(resolve=>{finish=resolve})
  return Response.json(String(url).endsWith('/recipes')?{...recipeFixture,id:'recipe2',revision:2,observation_map_version_id:'mapv2'}:{id:'run1'})
 })
 open();await screen.findByLabelText('最低 counts');fireEvent.click(screen.getByRole('button',{name:'观测映射'}));fireEvent.click(screen.getByText('添加条码对应'));fireEvent.change(screen.getByLabelText('条码 1'),{target:{value:'AA-1'}})
 const start=screen.getByRole('button',{name:'开始分析'});await waitFor(()=>expect((start as HTMLButtonElement).disabled).toBe(false));fireEvent.click(start);fireEvent.click(start);await waitFor(()=>expect(finish).toBeTypeOf('function'))
 expect(vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1)
 await act(async()=>finish(Response.json({id:'mapv2',set_id:'mapset',version:1,revision:1,raw_source:rawFixture,rows:[],total:1,counts:{mapped:1,total:1,unmapped:0}})))
 await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(3))
 const calls=vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')
 expect(calls.map(([url])=>String(url).split('/').pop())).toEqual(['bio-observation-maps','recipes','bio-analysis-runs'])
 expect(JSON.parse(String(calls[1][1]?.body))).toMatchObject({observation_map_version_id:'mapv2',expected_revision:1})
 expect(JSON.parse(String(calls[2][1]?.body))).toMatchObject({recipe_version_id:'recipe2',expected_setup_revision:2})
})
it.each([409,500])('does not run an old recipe after save status %s',async(status)=>{
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>init?.method==='POST'?Response.json({detail:{code:'failed'}},{status}):response(url))
 open();fireEvent.change(await screen.findByLabelText('最低 counts'),{target:{value:'4'}});await waitFor(()=>expect((screen.getByRole('button',{name:'开始分析'}) as HTMLButtonElement).disabled).toBe(false));fireEvent.click(screen.getByRole('button',{name:'开始分析'}))
 await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(([,init])=>init?.method==='POST')).toBe(true));await act(async()=>{})
 expect(vi.mocked(apiFetch).mock.calls.filter(([url,init])=>init?.method==='POST'&&String(url).endsWith('bio-analysis-runs'))).toHaveLength(0)
})
it('gates final new compute while retaining readable setup',async()=>{
 vi.mocked(apiFetch).mockImplementation(async(url)=>response(url));open(false);expect((await screen.findByRole('button',{name:'开始分析'}) as HTMLButtonElement).disabled).toBe(true);expect(screen.getByLabelText('最低 counts')).toBeTruthy();expect(vi.mocked(apiFetch).mock.calls.every(([,init])=>init?.method!=='POST')).toBe(true)
})

it('waits for the recovered recipe head and never starts an old recipe during explicit lookup',async()=>{
 sessionStorage.setItem('paperassist.bio-request.v1:owner1:p1:recipe','1a234567-1234-1234-1234-123456789abc')
 let recovered=false,finishRoot!:(response:Response)=>void
 vi.mocked(apiFetch).mockImplementation(async(url)=>{
  if(String(url).includes('/bio-requests/')){recovered=true;return Response.json({kind:'recipe',id:'recipe2',root_id:'setup1'})}
  if(recovered&&String(url).endsWith('/bio-analysis-setups/setup1'))return new Promise<Response>(resolve=>{finishRoot=resolve})
  return response(url)
 })
 open();await screen.findByRole('button',{name:'开始分析'});fireEvent.click(screen.getByRole('button',{name:'按原请求身份核对'}));await waitFor(()=>expect(finishRoot).toBeTypeOf('function'))
 expect((screen.getByRole('button',{name:'开始分析'}) as HTMLButtonElement).disabled).toBe(true)
 await act(async()=>finishRoot(Response.json({...setupFixture,revision:2,current_recipe_version_id:'recipe2',current_recipe:{...recipeFixture,id:'recipe2',revision:2}})))
 await waitFor(()=>expect((screen.getByRole('button',{name:'开始分析'}) as HTMLButtonElement).disabled).toBe(false))
 expect(vi.mocked(apiFetch).mock.calls.every(([,init])=>init?.method!=='POST')).toBe(true)
})

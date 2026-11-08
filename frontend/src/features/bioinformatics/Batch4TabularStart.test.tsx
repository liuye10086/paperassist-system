import {afterEach,expect,it,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import BioAnalysisSetup from './BioAnalysisSetup'
import {rawFixture} from './spatialFixtures'
const params={normalization:'already_normalized',transform:'none',scaling:'none',exclude_samples:[],exclude_features:[],pca_components:3,seed:0,output_language:'en'}
const raw={...rawFixture,parser_version:'tabular_assay_import_v1'}
const recipe={id:'recipe1',setup_id:'setup1',version:1,revision:1,raw_source:raw,observation_map_version_id:null,design_version_id:null,recipe_code:'tabular_quantitative_v1',params}
const setup={id:'setup1',name:'Measured',revision:1,raw_source:raw,current_recipe_version_id:'recipe1',current_recipe:recipe}
const capability={raw_source:raw,available:true,blockers:[],limits:{},recipes:['tabular_quantitative_v1'],design_gaps:[],assay:'metabolomics',scale:{kind:'log10',unit:'intensity'},default_params:params}
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks();sessionStorage.clear()})
it('saves a dirty tabular recipe and reconciles its exact identity before the one final run',async()=>{
 let head=setup,finish!:(response:Response)=>void
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(init?.method==='POST'){
   if(String(url).endsWith('/recipes'))return new Promise<Response>(resolve=>{finish=resolve})
   return Response.json({id:'run2'})
  }
  return Response.json(String(url).includes('capabilities')?capability:head)
 })
 render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>);fireEvent.change(await screen.findByLabelText('PCA 成分数'),{target:{value:'5'}})
 const start=screen.getByRole('button',{name:'开始分析'});await waitFor(()=>expect((start as HTMLButtonElement).disabled).toBe(false));fireEvent.click(start);fireEvent.click(start);await waitFor(()=>expect(finish).toBeTypeOf('function'))
 expect(vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1)
 const updated={...recipe,id:'recipe2',version:2,revision:2,params:{...params,pca_components:5}};head={...setup,revision:2,current_recipe_version_id:'recipe2',current_recipe:updated}
 await act(async()=>finish(Response.json(updated)));await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(2))
 const run=vi.mocked(apiFetch).mock.calls.find(([url,init])=>init?.method==='POST'&&String(url).endsWith('/bio-analysis-runs'))!
 expect(JSON.parse(String(run[1]?.body))).toMatchObject({recipe_version_id:'recipe2',expected_setup_revision:2})
})
it('does not automatically run when the head advanced past the recipe just saved',async()=>{
 let saved=false
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(init?.method==='POST'){saved=true;return Response.json({...recipe,id:'recipe2',version:2,revision:2})}
  return Response.json(String(url).includes('capabilities')?capability:saved?{...setup,revision:3,current_recipe_version_id:'recipe3',current_recipe:{...recipe,id:'recipe3',revision:3}}:setup)
 })
 render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>);fireEvent.change(await screen.findByLabelText('PCA 成分数'),{target:{value:'5'}});await waitFor(()=>expect((screen.getByRole('button',{name:'开始分析'}) as HTMLButtonElement).disabled).toBe(false));fireEvent.click(screen.getByRole('button',{name:'开始分析'}));await screen.findByText('核对并采用当前配方版本')
 expect(vi.mocked(apiFetch).mock.calls.filter(([url,init])=>init?.method==='POST'&&String(url).endsWith('/bio-analysis-runs'))).toHaveLength(0)
})

it('does not send a run POST when unmounted while reconciling the saved tabular recipe',async()=>{
 let saved=false;const finishes:((response:Response)=>void)[]=[],updated={...recipe,id:'recipe2',version:2,revision:2}
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>{
  if(init?.method==='POST'){saved=true;return Response.json(updated)}
  if(saved&&String(url).endsWith('/bio-analysis-setups/setup1'))return new Promise<Response>(resolve=>{finishes.push(resolve)})
  return Response.json(String(url).includes('capabilities')?capability:setup)
 })
 const view=render(<BioAnalysisSetup projectId="p1" setupId="setup1" onNavigate={()=>{}}/>);fireEvent.change(await screen.findByLabelText('PCA 成分数'),{target:{value:'5'}});await waitFor(()=>expect((screen.getByRole('button',{name:'开始分析'}) as HTMLButtonElement).disabled).toBe(false));fireEvent.click(screen.getByRole('button',{name:'开始分析'}));await waitFor(()=>expect(finishes.length).toBeGreaterThan(0));view.unmount()
 await act(async()=>{for(const finish of finishes)finish(Response.json({...setup,revision:2,current_recipe_version_id:'recipe2',current_recipe:updated}))})
 expect(vi.mocked(apiFetch).mock.calls.filter(([url,init])=>init?.method==='POST'&&String(url).endsWith('/bio-analysis-runs'))).toHaveLength(0)
})

import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ProjectManuscripts from './ProjectManuscripts'
import {candidatesFixture,inputFixture,manuscriptFixture,snapshotFixture} from './manuscriptFixtures'
const base='/api/v1/projects/p1/manuscripts'
const document={kind:'document_version',id:'doc1',file_id:'file1',label:'已解析文档',version:1,allowed_roles:['methods','image_observation'],download_url:null}
const original={kind:'original',id:'photo1',file_id:'photo1',label:'独立图片',version:null,allowed_roles:['image_observation','methods'],download_url:null}
const source={kind:'document_version',id:'doc1',file_id:'file1',role:'image_observation',label:'已解析文档',sha256:'a'.repeat(64),download_url:null,content:{}}
const photo={kind:'original',id:'photo1',file_id:'photo1',role:'image_observation',label:'独立图片',sha256:'b'.repeat(64),download_url:null,content:{}}
// The second child deliberately has no source-ID prefix: relationships come from source_ids.
const pictures=[{id:'doc1:image1',number:1,title:'文档第一图',caption:'First saved caption',sha256:'a'.repeat(64),source_ids:['doc1']},{id:'unrelated-opaque-child',number:2,title:'文档第二图',caption:'Second saved caption',sha256:'b'.repeat(64),source_ids:['doc1']}]
const snapshot={...snapshotFixture,sources:[source,photo],results_groups:[{id:'group1',title:'Observations',paragraphs:[],tables:[],figures:[...pictures,{id:'photo1',number:3,title:'独立图片',caption:'Keep original caption',sha256:'c'.repeat(64),source_ids:['photo1']}]}]}
const frozenInput={...inputFixture,sources:[{kind:'document_version',id:'doc1',file_id:'file1',role:'image_observation'},{kind:'original',id:'photo1',file_id:'photo1',role:'image_observation'}],results_groups:[{id:'group1',title:'Observations',analysis_run_ids:[],figure_ids:pictures.map(f=>f.id).concat('photo1')}],figure_notes:pictures.map(f=>({figure_id:f.id,caption:f.caption,panels:[]})).concat({figure_id:'photo1',caption:'Keep original caption',panels:[]})}
const history={...manuscriptFixture,versions:[{...manuscriptFixture.versions[0],input:frozenInput,snapshot,exports:[]}]}
const props={projectId:'p1',researchTopic:'研究',outputLanguage:'en' as const,active:true}
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
function serve(saved=false){
 const fetcher=vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/candidates'))return Response.json({...candidatesFixture,items:[document,original]})
  if(url===base&&!init?.method)return Response.json({items:saved?[history]:[]})
  if(url.endsWith('/preview'))return Response.json(snapshot)
  return Response.json(history)
 });vi.stubGlobal('fetch',fetcher);return fetcher
}
it.each(['remove','methods'])('removes document child captions after source %s before the next preview',async(action)=>{
 const fetcher=serve();render(<ProjectManuscripts {...props}/>)
 fireEvent.click(await screen.findByRole('checkbox',{name:'已解析文档'}))
 const sourceControls=screen.getByRole('group',{name:'已解析文档'})
 fireEvent.change(within(sourceControls).getByLabelText('资料用途'),{target:{value:'image_observation'}})
 fireEvent.click(screen.getByRole('button',{name:'预览事实稿'}))
 const caption=await screen.findByRole('group',{name:'文档第一图'})
 fireEvent.change(within(caption).getByLabelText('用户提供图注'),{target:{value:'Edited caption'}})
 const second=screen.getByRole('group',{name:'文档第二图'})
 fireEvent.change(within(second).getByLabelText('用户提供图注'),{target:{value:'Second edited caption'}})
 if(action==='remove')fireEvent.click(within(sourceControls).getByRole('checkbox',{name:'已解析文档'}))
 else fireEvent.change(within(sourceControls).getByLabelText('资料用途'),{target:{value:'methods'}})
 fireEvent.click(screen.getByRole('button',{name:'预览事实稿'}))
 await waitFor(()=>expect(fetcher.mock.calls.filter(([url])=>url.endsWith('/preview'))).toHaveLength(2))
 const body=JSON.parse(String(fetcher.mock.calls.filter(([url])=>url.endsWith('/preview'))[1][1]?.body))
 expect(body.figure_notes).toEqual([])
 if(action==='methods')expect(body.sources[0].role).toBe('methods')
 expect(screen.queryByRole('group',{name:'文档第一图'})).toBeNull()
 expect(screen.queryByRole('group',{name:'文档第二图'})).toBeNull()
})
it.each(['remove','methods'])('restores child caption editors on clone and clears only that source figure links and notes on %s',async(action)=>{
 const fetcher=serve(true);render(<ProjectManuscripts {...props}/>)
 fireEvent.click(await screen.findByRole('button',{name:'以此版本编辑新稿'}))
 const caption=screen.getByRole('group',{name:'文档第一图'})
 expect(within(caption).getByLabelText('用户提供图注')).toHaveProperty('value','First saved caption')
 fireEvent.change(within(caption).getByLabelText('用户提供图注'),{target:{value:'Edited cloned caption'}})
 const documentControls=screen.getByRole('group',{name:'已解析文档'})
 if(action==='remove')fireEvent.click(within(documentControls).getByRole('checkbox',{name:'已解析文档'}))
 else fireEvent.change(within(documentControls).getByLabelText('资料用途'),{target:{value:'methods'}})
 fireEvent.click(screen.getByRole('button',{name:'保存为新版本'}))
 await waitFor(()=>expect(fetcher.mock.calls.some(([url,init])=>url===`${base}/m1/versions`&&init?.method==='POST')).toBe(true))
 const body=JSON.parse(String(fetcher.mock.calls.find(([url,init])=>url===`${base}/m1/versions`&&init?.method==='POST')![1]?.body))
 expect(body.figure_notes).toEqual([{figure_id:'photo1',caption:'Keep original caption',panels:[]}])
 expect(body.results_groups[0].figure_ids).toEqual(['photo1'])
 expect(frozenInput.figure_notes[0].caption).toBe('First saved caption')
})

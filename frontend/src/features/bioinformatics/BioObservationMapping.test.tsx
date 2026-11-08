import {createRef} from 'react'
import {afterEach,expect,it,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import BioObservationMapping,{type MappingPreparation} from './BioObservationMapping'
import {rawFixture} from './spatialFixtures'
vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks();sessionStorage.clear()})
it('saves explicit pending donor fields rather than inferring independent donors',async()=>{vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'mapv1',set_id:'map1',version:1,revision:1,rows:[],counts:{mapped:1,unmapped:9,total:10}}));render(<BioObservationMapping projectId="p1" source={rawFixture} designVersionId={null} currentVersionId={null} onSaved={()=>{}}/>);fireEvent.click(screen.getByText('添加条码对应'));fireEvent.change(screen.getByLabelText('条码 1'),{target:{value:'AA-1'}});fireEvent.click(screen.getByText('保存映射'));await waitFor(()=>expect(apiFetch).toHaveBeenCalled());const call=vi.mocked(apiFetch).mock.calls.find(c=>c[1]?.method==='POST');expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({rows:[{barcode:'AA-1',donor:{status:'pending',value:null},section:{status:'pending',value:null}}]})})
it('applies the complete frozen table identity instead of saving the 20-row preview as a full map',async()=>{const table_source={file_id:'mappingfile',sha256:'f'.repeat(64),sheet:0,mapping:{barcode:'barcode'}};vi.mocked(apiFetch).mockImplementation(async(url)=>String(url).endsWith('/files')?Response.json([{id:'mappingfile',filename:'mapping.xlsx'}]):String(url).endsWith('table-previews')?Response.json({source:{file_id:'mappingfile',sha256:'f'.repeat(64)},table_source,headers:['barcode'],preview_rows:[{barcode:'AA-1'}],total:1000,valid:true,errors:[],counts:{mapped:1000,unmapped:0,total:1000}}):Response.json({id:'mapv1',set_id:'map1',version:1,revision:1,rows:[],total:1000,counts:{mapped:1000,unmapped:0,total:1000}}));render(<BioObservationMapping projectId="p1" source={rawFixture} designVersionId={null} currentVersionId={null} onSaved={()=>{}}/>);fireEvent.click(screen.getByRole('button',{name:'读取映射来源文件'}));await screen.findByText('mapping.xlsx');fireEvent.change(screen.getByLabelText('映射来源文件'),{target:{value:'mappingfile'}});fireEvent.click(screen.getByText('只读验证表格映射'));fireEvent.click(await screen.findByText('明确应用已验证映射到草稿'));fireEvent.click(screen.getByText('保存映射'));await waitFor(()=>expect(vi.mocked(apiFetch).mock.calls.some(c=>String(c[0]).endsWith('/bio-observation-maps'))).toBe(true));const call=vi.mocked(apiFetch).mock.calls.find(c=>String(c[0]).endsWith('/bio-observation-maps'));expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({table_source,rows:[]})})

const row={barcode:'AA-1',sample_id:{status:'pending',value:null},section:{status:'pending',value:null},donor:{status:'pending',value:null},batch:{status:'pending',value:null},group:{status:'pending',value:null}}
it('reuses the complete saved mapping after an edit is reverted without posting a new mapping',async()=>{
 const ref=createRef<MappingPreparation>(),all=Array.from({length:51},(_,i)=>({...row,barcode:`AA-${i+1}`}))
 vi.mocked(apiFetch).mockImplementation(async(url,init)=>Response.json({id:init?.method==='POST'?'map-duplicate':'mapv1',set_id:'mapset',version:1,revision:1,design_version_id:null,raw_source:rawFixture,rows:String(url).includes('page=2')?all.slice(50):all.slice(0,50),total:51,counts:{mapped:51,total:51,unmapped:0}}))
 render(<BioObservationMapping ref={ref} projectId="p1" source={rawFixture} designVersionId={null} currentVersionId="mapv1" currentSetId="mapset" onSaved={vi.fn()}/>);fireEvent.click(screen.getByRole('button',{name:'读取已保存映射用于编辑'}));await screen.findByLabelText('条码 1')
 fireEvent.change(screen.getByLabelText('条码 1'),{target:{value:'changed'}});fireEvent.change(screen.getByLabelText('条码 1'),{target:{value:'AA-1'}})
 let result:string|null|undefined;await act(async()=>{result=await ref.current!.ensureSaved()})
 expect(result).toBe('mapv1');expect(vi.mocked(apiFetch).mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0)
})
it('follows the newly adopted parent map identity instead of returning a previously loaded map',async()=>{
 const ref=createRef<MappingPreparation>(),props={projectId:'p1',source:rawFixture,designVersionId:null,currentSetId:'mapset',onSaved:vi.fn()}
 vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'mapv1',set_id:'mapset',version:1,revision:1,raw_source:rawFixture,rows:[row],total:1,counts:{mapped:1,total:1,unmapped:0}}))
 const view=render(<BioObservationMapping ref={ref} {...props} currentVersionId="mapv1"/>);fireEvent.click(screen.getByRole('button',{name:'读取已保存映射用于编辑'}));await screen.findByLabelText('条码 1');view.rerender(<BioObservationMapping ref={ref} {...props} currentVersionId="mapv2"/>)
 let result:string|null|undefined;await act(async()=>{result=await ref.current!.ensureSaved()});expect(result).toBe('mapv2');expect(vi.mocked(apiFetch).mock.calls.every(([,init])=>init?.method!=='POST')).toBe(true)
})
it('keeps a dirty old-map draft and requires an explicit decision when the parent adopts a new map',async()=>{
 const ref=createRef<MappingPreparation>(),props={projectId:'p1',source:rawFixture,designVersionId:null,currentSetId:'mapset',onSaved:vi.fn()}
 vi.mocked(apiFetch).mockResolvedValue(Response.json({id:'mapv1',set_id:'mapset',version:1,revision:1,raw_source:rawFixture,rows:[row],total:1,counts:{mapped:1,total:1,unmapped:0}}))
 const view=render(<BioObservationMapping ref={ref} {...props} currentVersionId="mapv1"/>);fireEvent.click(screen.getByRole('button',{name:'读取已保存映射用于编辑'}));fireEvent.change(await screen.findByLabelText('条码 1'),{target:{value:'local-draft'}});view.rerender(<BioObservationMapping ref={ref} {...props} currentVersionId="mapv2"/>)
 let result:string|null|undefined;await act(async()=>{result=await ref.current!.ensureSaved()});expect(result).toBeUndefined();expect((screen.getByLabelText('条码 1') as HTMLInputElement).value).toBe('local-draft');expect(vi.mocked(apiFetch).mock.calls.every(([,init])=>init?.method!=='POST')).toBe(true)
 expect(screen.getByText('样本对应关系已更新，本地修改已保留，请选择要使用的内容。')).toBeTruthy()
})

it('blocks old-map reuse while recovered mapping details are pending or failed and offers a GET-only retry',async()=>{
 sessionStorage.setItem('paperassist.bio-request.v1:owner1:p1:map','1a234567-1234-1234-1234-123456789abc')
 let finish!:(response:Response)=>void,details=0;const ref=createRef<MappingPreparation>(),onSaved=vi.fn()
 const recovered={id:'mapv2',set_id:'mapset2',version:1,revision:1,raw_source:rawFixture,rows:[row],total:1,counts:{mapped:1,total:1,unmapped:0}}
 vi.mocked(apiFetch).mockImplementation(async(url)=>String(url).includes('/bio-requests/')?Response.json({kind:'map',id:'mapv2',root_id:'mapset2'}):++details===1?new Promise<Response>(resolve=>{finish=resolve}):Response.json(recovered))
 render(<BioObservationMapping ref={ref} projectId="p1" source={rawFixture} designVersionId={null} currentVersionId="mapv1" currentSetId="mapset1" onSaved={onSaved}/>);fireEvent.click(screen.getByRole('button',{name:'按原请求身份核对'}));await waitFor(()=>expect(finish).toBeTypeOf('function'))
 let result:string|null|undefined;await act(async()=>{result=await ref.current!.ensureSaved()});expect(result).toBeUndefined();await act(async()=>finish(Response.json({}, {status:503})))
 const retry=await screen.findByRole('button',{name:'重新核对样本对应关系'});await act(async()=>{result=await ref.current!.ensureSaved()});expect(result).toBeUndefined();fireEvent.click(retry);await waitFor(()=>expect(onSaved).toHaveBeenCalledWith(recovered))
 expect(vi.mocked(apiFetch).mock.calls.every(([,init])=>init?.method!=='POST')).toBe(true)
})

it('keeps a local mapping draft as a new mapping when the parent removes its saved mapping',async()=>{
 const ref=createRef<MappingPreparation>(),props={projectId:'p1',source:rawFixture,designVersionId:null,onSaved:vi.fn()}
 const existing={id:'mapv1',set_id:'mapset',version:1,revision:1,raw_source:rawFixture,rows:[row],total:1,counts:{mapped:1,total:1,unmapped:0}}
 vi.mocked(apiFetch).mockImplementation(async(_url,init)=>Response.json(init?.method==='POST'?{...existing,id:'map-new',set_id:'map-new-set'}:existing))
 const view=render(<BioObservationMapping ref={ref} {...props} currentVersionId="mapv1" currentSetId="mapset"/>);fireEvent.click(screen.getByRole('button',{name:'读取已保存映射用于编辑'}));fireEvent.change(await screen.findByLabelText('条码 1'),{target:{value:'local-draft'}});view.rerender(<BioObservationMapping ref={ref} {...props} currentVersionId={null} currentSetId={null}/>)
 const keep=screen.getByRole('button',{name:'保留本地修改'});expect((keep as HTMLButtonElement).disabled).toBe(false);fireEvent.click(keep);await act(async()=>{await ref.current!.ensureSaved()})
 const call=vi.mocked(apiFetch).mock.calls.find(([,init])=>init?.method==='POST')!;expect(String(call[0])).toBe('/api/v1/projects/p1/bio-observation-maps');expect(JSON.parse(String(call[1]?.body))).toMatchObject({expected_revision:0,rows:[{barcode:'local-draft'}]})
})
it('restores only the recovered mapping identity after a pending-details refresh and retries by GET',async()=>{
 sessionStorage.setItem('paperassist.bio-request.v1:owner1:p1:map','1a234567-1234-1234-1234-123456789abc')
 let finish!:(response:Response)=>void,details=0;const recovered={id:'mapv2',set_id:'mapset2',version:1,revision:1,raw_source:rawFixture,rows:[row],total:1,counts:{mapped:1,total:1,unmapped:0}},onSaved=vi.fn(),props={projectId:'p1',source:rawFixture,designVersionId:null,currentVersionId:'mapv1',currentSetId:'mapset1',onSaved}
 vi.mocked(apiFetch).mockImplementation(async(url)=>String(url).includes('/bio-requests/')?Response.json({kind:'map',id:'mapv2',root_id:'mapset2'}):++details===1?new Promise<Response>(resolve=>{finish=resolve}):Response.json(recovered))
 const first=render(<BioObservationMapping {...props}/>);fireEvent.click(screen.getByRole('button',{name:'按原请求身份核对'}));await waitFor(()=>expect(finish).toBeTypeOf('function'));first.unmount()
 const ref=createRef<MappingPreparation>();render(<BioObservationMapping {...props} ref={ref}/>);let result:string|null|undefined;await act(async()=>{result=await ref.current!.ensureSaved()});expect(result).toBeUndefined();fireEvent.click(screen.getByRole('button',{name:'重新核对样本对应关系'}));await waitFor(()=>expect(onSaved).toHaveBeenCalledWith(recovered));await act(async()=>finish(Response.json(recovered)))
 expect(onSaved).toHaveBeenCalledTimes(1);expect(vi.mocked(apiFetch).mock.calls.filter(([url])=>String(url).includes('/bio-requests/'))).toHaveLength(1);expect(vi.mocked(apiFetch).mock.calls.every(([,init])=>init?.method!=='POST')).toBe(true)
})

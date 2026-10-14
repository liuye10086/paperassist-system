import {afterEach,expect,test,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import FileLifecyclePanel from './FileLifecyclePanel'
import FileDetails from './FileDetails'
import {assessmentFixture,lifecycleResponse} from './lifecycleFixtures'
import FileImpactReview from './FileImpactReview'
import StructureVersions from '../datasets/StructureVersions'
import {rowPage,version} from '../datasets/datasetFixtures'

afterEach(()=>{cleanup();vi.unstubAllGlobals()})

test('distinct historical Text scope tuples clear the previous deletion reason',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>lifecycleResponse(url,url.includes('/files/b%3Ac/')?'b:c':'c')!))
 const view=render(<FileLifecyclePanel projectId="a:b" fileId="c" active onUnavailable={()=>{}}/> )
 fireEvent.change(screen.getByRole('textbox',{name:'删除申请理由'}),{target:{value:'private reason for first scope'}})
 view.rerender(<FileLifecyclePanel projectId="a" fileId="b:c" active onUnavailable={()=>{}}/> )
 await waitFor(()=>expect(screen.getByText('删除申请共 0 条')).toBeTruthy())
 expect((screen.getByRole('textbox',{name:'删除申请理由'}) as HTMLTextAreaElement).value).toBe('')
})
test('impact pagination starts at page one after a distinct historical Text scope tuple replaces page two',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
  const file=url.includes('/files/b%3Ac/')?'b:c':'c'
  if(url.includes('/tasks'))return Response.json({items:[],total:11,page:Number(new URL(url,'http://local').searchParams.get('page')),page_size:10,counts:assessmentFixture(file).counts})
  return lifecycleResponse(url,file)!
 }))
 const props={action:'reparse' as const,operation:'Word',onUnavailable:()=>{},onCancel:()=>{},onConfirm:()=>{}}
 const view=render(<FileImpactReview {...props} projectId="a:b" fileId="c"/>);await screen.findByText('第 1 页');fireEvent.click(screen.getByRole('button',{name:'下一页受影响任务'}));await screen.findByText('第 2 页')
 view.rerender(<FileImpactReview {...props} projectId="a" fileId="b:c"/>);await screen.findByText('第 1 页');expect(screen.queryByText('第 2 页')).toBeNull()
})

test('structure scope replacement immediately clears the old selected rows and cell evidence',async()=>{
 const scoped={...version,file_id:'c',task:{...version.task,project_id:'a:b'},datasets:version.datasets.map(d=>({...d,file_id:'c'}))}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
  if(url.includes('/files/b%3Ac/'))return new Promise<Response>(()=>{})
  if(url.includes('/rows?'))return Response.json({...rowPage(),dataset:scoped.datasets[0]})
  return Response.json({items:[scoped],total:1,page:1,page_size:5,latest_version:1})
 }))
 const props={filename:'historical.xlsx',active:true,onUnavailable:()=>{}}
 const view=render(<StructureVersions {...props} projectId="a:b" fileId="c"/>);fireEvent.click(await screen.findByRole('button',{name:'查看单元格 A1 来源'}));expect(screen.getByRole('region',{name:'单元格来源'})).toBeTruthy()
 view.rerender(<StructureVersions {...props} projectId="a" fileId="b:c"/>);expect(screen.queryByRole('region',{name:'单元格来源'})).toBeNull();expect(screen.queryByRole('button',{name:'查看单元格 A1 来源'})).toBeNull();expect(screen.queryByRole('link',{name:'下载完整 JSON'})).toBeNull()
})

test('same historical Text scope keeps its reason and pending acknowledgement across rerenders',async()=>{
 let resolve!:(value:Response)=>void
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>init?.method==='POST'?new Promise<Response>(done=>{resolve=done}):lifecycleResponse(url,'c')!))
 const props={projectId:'a:b',fileId:'c',active:true,onUnavailable:()=>{}}
 const view=render(<FileLifecyclePanel {...props}/>);fireEvent.change(screen.getByRole('textbox',{name:'删除申请理由'}),{target:{value:'same historical scope reason'}})
 view.rerender(<FileLifecyclePanel {...props}/>);expect((screen.getByRole('textbox',{name:'删除申请理由'}) as HTMLTextAreaElement).value).toBe('same historical scope reason')
 fireEvent.click(screen.getByRole('button',{name:'提交删除申请'}));await waitFor(()=>expect(screen.getByRole('button',{name:'确认提交删除申请'}).hasAttribute('disabled')).toBe(false));fireEvent.click(screen.getByRole('button',{name:'确认提交删除申请'}));view.rerender(<FileLifecyclePanel {...props}/>)
 const assessment=assessmentFixture('c');await act(async()=>resolve(Response.json({id:'same-request',file_id:'c',reason:'same historical scope reason',status:'retained',requested_at:'2026-10-13T00:00:00Z',resolved_at:'2026-10-13T00:00:00Z',policy_version:assessment.policy_version,assessment_revision:assessment.assessment_revision,assessment})))
 expect(screen.getByText('已记录申请，文件按规则保留')).toBeTruthy()
})

test('colliding historical Text scopes hide old file details while the new read is pending',async()=>{
 const detail={id:'c',filename:'first scope private file',file_type:'docx',size_bytes:1,parse_status:'parsed',purposes:[],metadata_revision:1,uploader_recorded:true,references:{},source:{kind:'docx_parse',preview_available:true}}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.includes('/files/b%3Ac/')?new Promise<Response>(()=>{}):lifecycleResponse(url,'c')??Response.json(url.endsWith('/details')?detail:{items:[],total:0,page:1,page_size:5,latest_version:0})))
 const props={active:true,onUnavailable:()=>{},onUpdated:()=>{}}
 const view=render(<FileDetails {...props} projectId="a:b" fileId="c"/> )
 await screen.findByRole('heading',{name:'文件详情 · first scope private file'})
 view.rerender(<FileDetails {...props} projectId="a" fileId="b:c"/> )
 expect(screen.queryByRole('heading',{name:'文件详情 · first scope private file'})).toBeNull()
})

test('late deletion receipt from a historical Text scope cannot populate a distinct scope tuple',async()=>{
 let resolve!:(value:Response)=>void
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>init?.method==='POST'?new Promise<Response>(done=>{resolve=done}):lifecycleResponse(url,url.includes('/files/b%3Ac/')?'b:c':'c')!))
 const view=render(<FileLifecyclePanel projectId="a:b" fileId="c" active onUnavailable={()=>{}}/> )
 fireEvent.change(screen.getByRole('textbox',{name:'删除申请理由'}),{target:{value:'private reason for first scope'}})
 fireEvent.click(screen.getByRole('button',{name:'提交删除申请'}))
 await waitFor(()=>expect(screen.getByRole('button',{name:'确认提交删除申请'}).hasAttribute('disabled')).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'确认提交删除申请'}))
 view.rerender(<FileLifecyclePanel projectId="a" fileId="b:c" active onUnavailable={()=>{}}/> )
 const assessment=assessmentFixture('c')
 await act(async()=>resolve(Response.json({id:'old-request',file_id:'c',reason:'private reason for first scope',status:'retained',requested_at:'2026-10-13T00:00:00Z',resolved_at:'2026-10-13T00:00:00Z',policy_version:assessment.policy_version,assessment_revision:assessment.assessment_revision,assessment})))
 expect(screen.queryByText('已记录申请，文件按规则保留')).toBeNull()
 expect(screen.queryByText('申请理由：private reason for first scope')).toBeNull()
})

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import BatchUpload from './BatchUpload'
import type { BatchItem } from './batchUploadApi'
import { clearApiSession, setApiSession } from '../../shared/api/client'
import { setLocale } from '../../shared/i18n'
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers();setLocale('zh-CN')})
const props={projectId:'p1',active:true,onUnavailable:vi.fn(),onChanged:vi.fn()}
const item=(id='i1',status:BatchItem['status']='pending'):BatchItem=>({id,ordinal:0,filename:'same.xlsx',size_bytes:1,status,file_id:null,task:null,error:null})
const batch=(items=[item()],revision=1)=>({id:'b1',project_id:'p1',created_at:'2026-10-10T00:00:00Z',revision,items})
const page=(items:unknown[]=[])=>Response.json({items,total:items.length,page:1,page_size:5})
function select(files:File[]){fireEvent.change(screen.getByLabelText('批量选择 Excel / Word / PDF / 图片 文件'),{target:{files}})}
it('keeps the original registration key after an unknown response and uses session CSRF',async()=>{
 setApiSession('real-token');let keys:string[]=[];let calls=0
 vi.stubGlobal('fetch',vi.fn(async(url:string,init:RequestInit)=>{if(init.method==='POST'&&url.endsWith('file-batches')){keys.push(new Headers(init.headers).get('Idempotency-Key')!);expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('real-token');calls++;if(calls===1)throw new Error('lost');return Response.json(batch([item('i1','rejected')]))}return page()}))
 render(<BatchUpload {...props}/>);select([new File(['a'],'same.xlsx')]);fireEvent.click(screen.getByText('开始上传'));await screen.findByText('登记结果待确认，请使用原选择重试。');fireEvent.click(screen.getByText('开始上传'));await screen.findByText(/上传被拒绝/);expect(keys[0]).toBe(keys[1])
})
it('queries uncertain upload before offering a retry and never duplicates a saved item',async()=>{
 let posts=0, reads=0;let saved=false
 vi.stubGlobal('fetch',vi.fn(async(url:string,init:RequestInit)=>{if(url.includes('/items/')){posts++;saved=true;throw new Error('lost')}if(init.method==='POST'){const body=JSON.parse(String(init.body));return Response.json(batch([item(body.items[0].client_id)]))}if(url.endsWith('/b1')){reads++;const ids=JSON.parse(String((fetch as ReturnType<typeof vi.fn>).mock.calls.find(([,i])=>i.method==='POST')![1].body));return Response.json(batch([{...item(ids.items[0].client_id,'queued'),file_id:'f1'}],2))}return page(saved?[batch([{...item('i1','queued'),file_id:'f1'}],2)]:[])}))
 render(<BatchUpload {...props}/>);select([new File(['a'],'same.xlsx')]);fireEvent.click(screen.getByText('开始上传'));await screen.findByText(/已保存，等待解析/);expect(posts).toBe(1);expect(reads).toBe(1);expect(screen.queryByText('核对后上传')).toBeNull()
})
it('restores missing local bytes and requires choosing the same name and size',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>page([batch()])));render(<BatchUpload {...props}/>);await screen.findByText('重新选择同一文件');const button=screen.getByText('核对后上传') as HTMLButtonElement;expect(button.disabled).toBe(true);fireEvent.change(screen.getByLabelText('重新选择同一文件'),{target:{files:[new File(['xx'],'same.xlsx')]}});expect(button.disabled).toBe(true);await screen.findByText('请选择名称和大小一致的原文件。');fireEvent.change(screen.getByLabelText('重新选择同一文件'),{target:{files:[new File(['a'],'same.xlsx')]}});expect(button.disabled).toBe(false)
})
it('clears batch contents on session invalidation and discards a late read',async()=>{
 let resolve!:(value:Response)=>void;vi.stubGlobal('fetch',vi.fn(()=>new Promise(r=>{resolve=r})));render(<BatchUpload {...props}/>);await act(async()=>{clearApiSession();resolve(page([batch()]))});expect(screen.queryByText('same.xlsx')).toBeNull()
})
it('pauses hidden page requests, refreshes on return and stops terminal polling',async()=>{
 vi.useFakeTimers();let visible='hidden';vi.spyOn(document,'visibilityState','get').mockImplementation(()=>visible as DocumentVisibilityState);const fetch=vi.fn(async()=>page([batch([item('i1','parsed')],4)]));vi.stubGlobal('fetch',fetch);render(<BatchUpload {...props}/>);await act(async()=>{await vi.advanceTimersByTimeAsync(5000)});expect(fetch).not.toHaveBeenCalled();visible='visible';await act(async()=>{document.dispatchEvent(new Event('visibilitychange'))});expect(fetch).toHaveBeenCalledTimes(1);await act(async()=>{await vi.advanceTimersByTimeAsync(15000)});expect(fetch).toHaveBeenCalledTimes(1)
})
it('does not overlap polling requests',async()=>{
 vi.useFakeTimers();let resolve!:(value:Response)=>void;const fetch=vi.fn(()=>new Promise(r=>{resolve=r}));vi.stubGlobal('fetch',fetch);render(<BatchUpload {...props}/>);await act(async()=>{await vi.advanceTimersByTimeAsync(10000)});expect(fetch).toHaveBeenCalledTimes(1);await act(async()=>{resolve(page([batch([item('i1','queued')],2)]))});await act(async()=>{await vi.advanceTimersByTimeAsync(5000)});expect(fetch).toHaveBeenCalledTimes(2)
})
it('rejects eleven selections and exposes mixed file validation without treating duplicate names as one',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>page()));render(<BatchUpload {...props}/>);select(Array.from({length:11},()=>new File(['a'],'same.xlsx')));expect((screen.getByText('开始上传') as HTMLButtonElement).disabled).toBe(true);select([new File(['a'],'same.xlsx'),new File(['b'],'same.xlsx'),new File([],'empty.xlsx'),new File(['x'],'bad.txt')]);expect(screen.getAllByText(/same.xlsx/)).toHaveLength(2);expect(screen.getByText('文件为空。')).toBeTruthy();expect(screen.getByText('仅支持 .xlsx、.docx、.pdf、.png、.jpg 或 .jpeg 文件。')).toBeTruthy();await waitFor(()=>expect(screen.queryByRole('alert')).toBeNull())
})

it('replaces an uncertain local receipt when a later batch query confirms saved parsing',async()=>{
 let snapshot=batch();let confirmed=false
 vi.stubGlobal('fetch',vi.fn(async(url:string,init:RequestInit)=>{
  if(init.method==='POST'&&url.endsWith('file-batches')){const body=JSON.parse(String(init.body));snapshot=batch([item(body.items[0].client_id)]);return Response.json(snapshot)}
  if(url.includes('/items/')||url.endsWith('/b1'))throw new Error('offline')
  return page(confirmed?[{...snapshot,revision:4,items:snapshot.items.map(i=>({...i,status:'parsed',file_id:'f1'}))}]:[])
 }));render(<BatchUpload {...props}/>);select([new File(['a'],'same.xlsx')]);fireEvent.click(screen.getByText('开始上传'));await screen.findByText(/接收结果待确认/);confirmed=true;fireEvent.click(screen.getByText('重新读取批次'));await screen.findByText(/解析完成/);expect(screen.queryByText(/接收结果待确认/)).toBeNull()
})

it('keeps newer polled parsed state when a late queued upload receipt arrives and rereads fail',async()=>{
 vi.useFakeTimers();const started=Date.now();let receiptReturned=false;let snapshot=batch();let finishUpload!:(response:Response)=>void
 const fetch=vi.fn(async(url:string,init:RequestInit)=>{
  if(init.method==='POST'&&url.endsWith('file-batches')){const body=JSON.parse(String(init.body));snapshot=batch([item(body.items[0].client_id)]);return Response.json(snapshot)}
  if(url.includes('/items/'))return new Promise<Response>(resolve=>{finishUpload=resolve})
  if(url.endsWith('/b1'))throw new Error('reread unavailable')
  if(receiptReturned)throw new Error('later read unavailable');if(Date.now()-started<5000)return page([snapshot]);return page([{...snapshot,revision:4,items:snapshot.items.map(i=>({...i,status:'parsed',file_id:'f1'}))}])
 });vi.stubGlobal('fetch',fetch);render(<BatchUpload {...props}/>);await act(async()=>{});select([new File(['a'],'same.xlsx')]);await act(async()=>{fireEvent.click(screen.getByText('开始上传'))});await act(async()=>{await vi.advanceTimersByTimeAsync(5000)});expect(screen.getByText(/解析完成/)).toBeTruthy();await act(async()=>{receiptReturned=true;finishUpload(Response.json({...snapshot.items[0],status:'queued',file_id:'f1'}))});expect(screen.getByText(/解析完成/)).toBeTruthy();expect(screen.queryByText(/接收结果待确认/)).toBeNull();expect(screen.queryByText(/已保存，等待解析/)).toBeNull()
})
it('replaces the five-batch page when an external new batch displaces an in-flight batch',async()=>{
 const make=(name:string,status:BatchItem['status']='parsed')=>({...batch([{...item(`i-${name}`,status),filename:`${name}.xlsx`}]),id:name})
 let rows=[make('old-flight','queued'),make('b2'),make('b3'),make('b4'),make('b5')]
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({items:rows,total:6,page:1,page_size:5})));const view=render(<BatchUpload {...props}/>);await screen.findByText('old-flight.xlsx');rows=[make('new'),...rows.slice(1)];fireEvent.click(screen.getByText('重新读取批次'));await screen.findByText('new.xlsx');expect(view.container.querySelectorAll('article')).toHaveLength(5);expect(screen.queryByText('old-flight.xlsx')).toBeNull()
})
it('returns to the first authoritative page when starting a batch from page two',async()=>{
 let created=false;let snapshot=batch();const requested:number[]=[]
 const make=(name:string)=>({...batch([{...item(`i-${name}`,'parsed'),filename:`${name}.xlsx`}]),id:name})
 const fetch=vi.fn(async(url:string,init:RequestInit)=>{
  if(init.method==='POST'&&url.endsWith('file-batches')){const body=JSON.parse(String(init.body));snapshot={...batch([item(body.items[0].client_id)]),id:'new-batch'};created=true;return Response.json(snapshot)}
  if(url.includes('/items/')){snapshot={...snapshot,revision:2,items:snapshot.items.map(i=>({...i,status:'queued',file_id:'f-new'}))};return Response.json(snapshot.items[0])}
  if(url.endsWith('/new-batch'))return Response.json(snapshot)
  const number=Number(new URL(url,'http://localhost').searchParams.get('page'));requested.push(number);return Response.json({items:number===1?(created?[snapshot,make('b1'),make('b2'),make('b3'),make('b4')]:[make('b1'),make('b2'),make('b3'),make('b4'),make('b5')]):[make('page-two')],total:created?7:6,page:number,page_size:5})
 });vi.stubGlobal('fetch',fetch);const view=render(<BatchUpload {...props}/>);await screen.findByText('b1.xlsx');fireEvent.click(screen.getByText('下一页'));await screen.findByText('page-two.xlsx');select([new File(['a'],'same.xlsx')]);fireEvent.click(screen.getByText('开始上传'));await waitFor(()=>expect(screen.getByText('上一页').getAttribute('disabled')).not.toBeNull());await screen.findByText('same.xlsx');expect(screen.queryByText('page-two.xlsx')).toBeNull();expect(view.container.querySelectorAll('article')).toHaveLength(5);expect(requested.at(-1)).toBe(1)
})

import {beforeEach,describe,expect,it,vi} from 'vitest'
import {webcrypto} from 'node:crypto'
import {CloudClient,PART_SIZE,cloudStorageKey,resumeUpload,runBody,matrixOutputs} from './cloud'
import {setApiSession} from '../../shared/api/client'

beforeEach(()=>{sessionStorage.clear();setApiSession('csrf','alice');vi.stubGlobal('crypto',webcrypto)})
const upload={id:'u1',filename:'a.fastq.gz',size_bytes:PART_SIZE+2,part_size:PART_SIZE,status:'uploading'}
describe('cloud safety and multipart',()=>{
 it('isolates persisted requests by account and project',()=>{
  expect(cloudStorageKey('alice','p')).not.toBe(cloudStorageKey('bob','p'))
  expect(cloudStorageKey('alice','p')).not.toBe(cloudStorageKey('alice','q'))
 })
 it('retains unknown POST identity across reload and only looks up the same key',async()=>{
  const fetcher=vi.fn().mockRejectedValueOnce(new Error('lost')).mockResolvedValueOnce(new Response('{}',{status:404})).mockResolvedValueOnce(Response.json(upload))
  vi.stubGlobal('fetch',fetcher)
  const client=new CloudClient('p')
  await expect(client.create('upload',{filename:'a.fastq.gz',size_bytes:3})).rejects.toThrow()
  const key=client.pending!.key
  const restored=new CloudClient('p')
  await expect(restored.create('upload',{})).rejects.toThrow()
  await expect(restored.lookup()).rejects.toThrow()
  expect(restored.pending?.key).toBe(key)
  expect(await restored.lookup()).toEqual(upload)
  expect(fetcher.mock.calls.filter(c=>c[1]?.method==='POST')).toHaveLength(1)
  expect(fetcher.mock.calls[1][0]).toContain(`/requests/${key}?kind=upload`)
 })
 it('reads one part at a time, compares resumed checksum and omits credentials on PUT',async()=>{
  const slices:number[][]=[]
  const file={name:'a.fastq.gz',size:PART_SIZE+2,slice:(start:number,end:number)=>{slices.push([start,end]);return {arrayBuffer:async()=>Buffer.alloc(end-start)}}} as unknown as File
  const checksum=Buffer.from(await webcrypto.subtle.digest('SHA-256',Buffer.alloc(PART_SIZE))).toString('base64')
  const request=vi.fn().mockImplementation(async(path:string)=>path.endsWith('/parts')?{items:[{part_number:1,checksum_sha256:checksum,size_bytes:PART_SIZE}]}:path.endsWith('/sign')?{url:'https://signed.invalid/part',headers:{'x-amz-checksum-sha256':'test'}}:{...upload,status:'completed'})
  const put=vi.fn().mockResolvedValue({ok:true})
  await resumeUpload(file,upload,request,new AbortController().signal,put)
  expect(slices).toEqual([[0,PART_SIZE],[PART_SIZE,PART_SIZE+2]])
  expect(put).toHaveBeenCalledTimes(1)
  expect(put.mock.calls[0][1]).toMatchObject({method:'PUT',credentials:'omit',headers:{'x-amz-checksum-sha256':'test'}})
 })
 it('rejects checksum conflict without uploading or completing',async()=>{
  const file={name:upload.filename,size:upload.size_bytes,slice:()=>({arrayBuffer:async()=>Buffer.alloc(1)})} as unknown as File
  const request=vi.fn().mockResolvedValue({items:[{part_number:1,checksum_sha256:'different',size_bytes:PART_SIZE}]})
  const put=vi.fn()
  await expect(resumeUpload(file,upload,request,new AbortController().signal,put)).rejects.toThrow('校验不一致')
  expect(put).not.toHaveBeenCalled();expect(request).toHaveBeenCalledTimes(1)
 })
 it('builds one-library submission payload with authorization from the submit action',()=>{
  const draft={profile_id:'profile',sample_id:'S',library_id:'L',donor_id:'D',group:'G',chemistry:'v3',r1:'u1',r2:'u2',budget_limit_usd:'10.00'}
  const profile={id:'profile',species:'human',chemistries:['v3'],account_verified:true}
  expect(runBody(draft,profile)).toMatchObject({species:'human',fastqs:[{upload_id:'u1',read:'R1',lane:'L001',chunk:1},{upload_id:'u2',read:'R2',lane:'L001',chunk:1}],budget_limit_usd:'10.00',external_processing_confirmed:true,budget_approved:true})
  expect(()=>runBody({...draft,budget_limit_usd:''},profile)).toThrow()
  expect(()=>runBody({...draft,r2:'u1'},profile)).toThrow()
 })
 it('selects only complete matrix/features/barcodes outputs',()=>{
  expect(matrixOutputs([{role:'matrix',file_id:'m'},{role:'features',file_id:'f'},{role:'barcodes',file_id:'b'},{role:'log',file_id:'l'}])).toEqual({matrix:'m',features:'f',barcodes:'b'})
  expect(matrixOutputs([{role:'matrix',file_id:'m'}])).toBeNull()
 })
})

import {taskNames,statusNames,displayNames} from '../tasks/taskTypes'
it('labels cloud tasks and cancellation in existing task surfaces',()=>{
 expect(taskNames).toHaveProperty('bio_cloud_run','FASTQ 云端计算')
 expect(statusNames).toHaveProperty('cancelled','已取消')
 expect(displayNames).toHaveProperty('cancelled','已取消')
})
it('keeps unknown identity on malformed success payload instead of permitting another paid POST',async()=>{
 const fetcher=vi.fn().mockResolvedValue(Response.json(null));vi.stubGlobal('fetch',fetcher)
 const client=new CloudClient('p')
 await expect(client.create('run',{})).rejects.toThrow()
 expect(client.pending?.kind).toBe('run')
 await expect(client.lookup()).rejects.toThrow()
 expect(client.pending?.kind).toBe('run')
})
it('allows correction only after definite client rejection and blocks writes if identity storage fails',async()=>{
 const fetcher=vi.fn().mockResolvedValue(Response.json({detail:{code:'invalid'}},{status:422}));vi.stubGlobal('fetch',fetcher)
 const client=new CloudClient('p');await expect(client.create('run',{})).rejects.toThrow();expect(client.pending).toBeNull()
 const persist=vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('storage unavailable')})
 await expect(client.create('run',{})).rejects.toThrow('storage unavailable');expect(fetcher).toHaveBeenCalledTimes(1);persist.mockRestore()
})
it('retains successful parts and resumes only remaining part after interrupted PUT',async()=>{
 const file={name:upload.filename,size:upload.size_bytes,slice:(start:number,end:number)=>({arrayBuffer:async()=>Buffer.alloc(end-start)})} as unknown as File
 let saved=false;const request=vi.fn().mockImplementation(async(path:string)=>path.endsWith('/parts')?{items:saved?[{part_number:1,size_bytes:PART_SIZE,checksum_sha256:Buffer.from(await webcrypto.subtle.digest('SHA-256',Buffer.alloc(PART_SIZE))).toString('base64')}]:[]}:path.endsWith('/sign')?{url:'https://signed.invalid/part',headers:{}}:{...upload,status:'completed'})
 const put=vi.fn().mockImplementation(async()=>{if(!saved){saved=true;return {ok:true}}throw Error('interrupted')})
 await expect(resumeUpload(file,upload,request,new AbortController().signal,put)).rejects.toThrow('interrupted')
 const resumedPut=vi.fn().mockResolvedValue({ok:true})
 await resumeUpload(file,upload,request,new AbortController().signal,resumedPut)
 expect(resumedPut).toHaveBeenCalledTimes(1)
 expect(request.mock.calls.filter(c=>c[0].endsWith('/parts/1/sign'))).toHaveLength(1)
})
it('checks later resumed parts before sending any missing part from a potentially different file',async()=>{
 const file={name:upload.filename,size:upload.size_bytes,slice:(start:number,end:number)=>({arrayBuffer:async()=>Buffer.alloc(end-start)})} as unknown as File
 const request=vi.fn().mockImplementation(async(path:string)=>path.endsWith('/parts')?{items:[{part_number:2,size_bytes:2,checksum_sha256:'wrong'}]}:{url:'https://signed.invalid',headers:{}})
 const put=vi.fn().mockResolvedValue({ok:true})
 await expect(resumeUpload(file,upload,request,new AbortController().signal,put)).rejects.toThrow('校验不一致')
 expect(put).not.toHaveBeenCalled()
})
it('recovers completing upload through final-object confirmation without listing or reading parts',async()=>{
 const slice=vi.fn();const file={name:upload.filename,size:upload.size_bytes,slice} as unknown as File
 const request=vi.fn().mockImplementation(async(path:string)=>{if(path.endsWith('/parts'))throw Error('NoSuchUpload');return {...upload,status:'completed'}}),put=vi.fn()
 expect(await resumeUpload(file,{...upload,status:'completing'},request,new AbortController().signal,put)).toMatchObject({status:'completed'})
 expect(request).toHaveBeenCalledTimes(1)
 expect(request.mock.calls[0][0]).toBe('/uploads/u1/complete')
 expect(request.mock.calls[0][1]).toMatchObject({method:'POST',body:'{}'})
 expect(slice).not.toHaveBeenCalled();expect(put).not.toHaveBeenCalled()
})

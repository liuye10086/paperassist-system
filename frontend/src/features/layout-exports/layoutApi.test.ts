import {beforeEach,afterEach,expect,it,vi} from 'vitest'
import {emptyLayout,pendingLayout,submitLayout,validLayout,validLayoutExport,validCatalog} from './layoutApi'
import {setApiSession} from '../../shared/api/client'
import {isProjectSummary} from '../projects/projectSummaryTypes'
import {summaryFixture} from '../../test/fixtures/summaryFixture'
const hash='a'.repeat(64),scope={projectId:'p1',sourceKind:'report' as const,sourceId:'r1',sourceSha256:hash}
const layout=emptyLayout(hash)
const row={id:'l1',project_id:'p1',source_kind:'report',source_id:'r1',source_sha256:hash,status:'queued',task_id:'lt1',created_at:'2026-10-20T00:00:00Z',layout,layout_version:'document_layout_v1',output_language:'en',request_key:'key',can_retry:false,parent_export_id:null,filename:null,error_code:null,renderer_manifest:null,sha256:null,size_bytes:null,download_url:null}

it('recovers the original layout/task with a recovery key while retaining the original creation key',async()=>{const original={...row,status:'failed',can_retry:true,error_code:'storage_quota_exceeded',recovery_mode:'local_candidate'} as import('./layoutApi').LayoutExport;vi.stubGlobal('fetch',vi.fn(async(_url,init)=>Response.json({...original,status:'queued',can_retry:false,recovery_request_key:JSON.parse(init.body).request_key})));const result=await submitLayout(scope,undefined,new AbortController(),original.id,original);expect(result.id).toBe('l1');expect(result.task_id).toBe('lt1');expect(result.request_key).toBe('key')})
it('does not accept a substituted task in original layout recovery',async()=>{const original={...row,status:'failed',can_retry:true,error_code:'storage_quota_exceeded',recovery_mode:'local_candidate'} as import('./layoutApi').LayoutExport;vi.stubGlobal('fetch',vi.fn(async(_url,init)=>Response.json({...original,task_id:'other',status:'queued',can_retry:false,recovery_request_key:JSON.parse(init.body).request_key})));await expect(submitLayout(scope,undefined,new AbortController(),original.id,original)).rejects.toThrow()})
afterEach(()=>vi.unstubAllGlobals())
beforeEach(()=>{sessionStorage.clear();setApiSession('session','owner1');vi.unstubAllGlobals()})
it('strictly validates normalized fields and forbids source or artifact substitution',()=>{
 expect(validLayoutExport(row,scope)).toBe(true)
 for(const delta of [{source_kind:'layout_export'},{source_sha256:'b'.repeat(64)},{source_id:'other'},{project_id:'p2'},{can_retry:'yes'},{download_url:'https://evil.test/f'},{status:'succeeded'},{request_key:undefined},{layout:{...layout,extra:true}},{layout:{...layout,toc:{depth:1,extra:true}}},{layout:{...layout,pagination:{mode:'continuous',body_anchor_id:hash+':0'}}},{layout:{...layout,formulas:[{id:'eq',anchor_id:hash+':0',expression:'x',placement:'after',extra:true}]}}])expect(validLayoutExport({...row,...delta},scope)).toBe(false)
 expect(validLayout({...layout,pagination:{mode:'continuous',body_anchor_id:null}},hash)).toBe(true)
})
it('checks bounded summary layout exports against their own exact project and source',()=>{
 const summary={...summaryFixture(),layout_exports:[row]};expect(isProjectSummary(summary,'p1','sci',1,1)).toBe(true)
 expect(isProjectSummary({...summary,layout_exports:[{...row,project_id:'p2'}]},'p1','sci',1,1)).toBe(false)
 expect(isProjectSummary({...summary,layout_exports:Array.from({length:21},(_,n)=>({...row,id:`l${n}`}))},'p1','sci',1,1)).toBe(false)
})
it('isolates exact unconfirmed bodies by owner, restores for the same owner, and never stores CSRF credentials',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>{throw new TypeError('lost')}));await expect(submitLayout(scope,{...layout,formulas:[{id:'eq1',anchor_id:hash+':0',expression:'private_input',placement:'after'}]},new AbortController())).rejects.toThrow()
 const before=pendingLayout(scope);expect(before?.body).toContain('private_input');expect(JSON.stringify(sessionStorage)).not.toContain('session')
 setApiSession('another-token','owner2');expect(pendingLayout(scope)).toBeNull();setApiSession('restored-token','owner1');expect(pendingLayout(scope)?.body).toBe(before?.body)
})
it('requires exact returned request key, retains unknown request, and clears a definitive 422 rejection',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json(row)));await expect(submitLayout(scope,layout,new AbortController())).rejects.toThrow();expect(pendingLayout(scope)).toBeTruthy()
 vi.stubGlobal('fetch',vi.fn(async()=>Response.json({detail:{code:'layout_formula_invalid',params:{formula_id:'eq1',position:4,reason:'/private/path'}}},{status:422})));await expect(submitLayout(scope,layout,new AbortController())).rejects.toThrow();expect(pendingLayout(scope)).toBeNull()
})

it('validates the frozen source version and exact SHA-derived anchor identities',()=>{
 const catalog={source_kind:'report',source_id:'r1',filename:'source.docx',source_sha256:hash,source_size:100,version:{id:'a1',revision:1,renderer_version:'v1'},output_language:'en',limits:{},anchors:[{id:hash+':0',position:0,type:'heading',text:'Results',heading_level:1,bookmark:null,is_caption:false}]}
 expect(validCatalog(catalog,scope)).toBe(true);expect(validCatalog({...catalog,version:{revision:'1'}},scope)).toBe(false);expect(validCatalog({...catalog,anchors:[{...catalog.anchors[0],id:'b'.repeat(64)+':0'}]},scope)).toBe(false)
})

// Equivalent to catalog_docx's Python text[:160]: one non-BMP mathematical
// character plus159 ASCII characters is160 code points but161 UTF-16 units.
it.each([160,161])('counts catalog excerpt boundary %i in Unicode code points',count=>{
 const catalog={source_kind:'report',source_id:'r1',filename:'unicode.docx',source_sha256:hash,source_size:100,version:{id:'a1',revision:1,renderer_version:'v1'},output_language:'en',limits:{},anchors:[{id:hash+':0',position:0,type:'heading',text:'𝑥'+'a'.repeat(count-1),heading_level:1,bookmark:null,is_caption:false}]}
 expect(Array.from(catalog.anchors[0].text)).toHaveLength(count);expect(catalog.anchors[0].text.length).toBe(count+1);expect(validCatalog(catalog,scope)).toBe(count<=160)
})
it.each([2000,2001])('reads normalized formula expression boundary %i by Python-compatible code points',count=>{
 const value={...layout,formulas:[{id:'eq1',anchor_id:hash+':0',expression:'𝑥'+'x'.repeat(count-1),placement:'after'}]}
 expect(validLayout(value,hash)).toBe(count<=2000);expect(validLayoutExport({...row,layout:value},scope)).toBe(count<=2000)
})
it.each([100,101])('reads normalized reference prefix boundary %i by Python-compatible code points',count=>{
 const value={...layout,references:[{anchor_id:hash+':0',target_id:hash+':0',kind:'text',prefix:'𝑥'+'p'.repeat(count-1)}]}
 expect(validLayout(value,hash)).toBe(count<=100);expect(validLayoutExport({...row,layout:value},scope)).toBe(count<=100)
})

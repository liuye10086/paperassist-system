import {expect,it} from 'vitest'
import type {ProjectFile} from '../files/fileLibraryApi'
import type {Version} from '../research-intake/contracts'
import {analysisScopes,entryMethods,entrySources,filePreparation,sourceNavigation} from './analysisEntryState'

const file=(id:string,status:ProjectFile['parse_status'],type='xlsx'):ProjectFile=>({id,filename:id+'.'+type,file_type:type,parse_status:status,size_bytes:10,uploaded_at:'',error:null})
const requirement:Version={id:'req-old',version:1,operation:'save',content:{schema_version:1,scope_items:[{id:'questionnaire.analysis.qc',title:'质控',delivery_kind:'analysis',status:'planned'},{id:'custom',title:'客户定制',delivery_kind:'analysis',status:'completed'},{id:'omit',title:'不纳入',delivery_kind:'analysis',status:'not_included'}]},sha256:'hash',created_at:'',material_refs:[]}
it('separates saved originals, pending parses, numerical tables and evidence',()=>{
 expect(filePreparation(file('a','queued')).ready).toBe(false)
 expect(filePreparation(file('a','parsing')).label).toBe('解析中')
 expect(filePreparation(file('a','failed')).label).toBe('解析失败')
 expect(filePreparation(file('a','stored','h5ad'))).toMatchObject({kind:'bio-original',ready:false})
 expect(filePreparation(file('a','parsed'))).toMatchObject({kind:'table',ready:true})
 expect(filePreparation(file('a','parsed','pdf'))).toMatchObject({kind:'evidence',ready:false})
 expect(filePreparation(file('a','parsed','png')).ready).toBe(false)
})
it('uses declared purpose without allowing unrelated failed files to block a table',()=>{
 const v={...requirement,material_refs:[{file_id:'table',purpose:'raw_data',availability:'provided' as const},{file_id:'bad',purpose:'figures',availability:'provided' as const}]}
 expect(entrySources(v,'qc',[file('table','parsed'),file('bad','failed')])).toMatchObject([{fileId:'table',ready:true}])
 expect(entrySources(v,'visualization',[file('table','parsed'),file('bad','failed')])).toMatchObject([{fileId:'bad',ready:false}])
})
it('keeps exact published versions and never substitutes the latest or missing source',()=>{
 const v={...requirement,material_refs:[{bio_dataset_version_id:'old',purpose:'raw_data',availability:'provided' as const}],material_sources:[{bio_dataset_version_id:'old',dataset_id:'dataset',dataset_name:'保留数据',version:2}]}
 const [source]=entrySources(v,'qc',[])
 expect(source).toMatchObject({datasetId:'dataset',versionId:'old',kind:'bio-version'})
 expect(sourceNavigation(source)).toMatchObject({view:'bio-dataset',datasetId:'dataset',versionId:'old'})
 expect(entrySources({...v,material_sources:[]},'qc',[])[0]).toMatchObject({kind:'missing',ready:false})
})
it('keeps custom scope text and ambiguous methods explicit',()=>{
 expect(analysisScopes(requirement).map(s=>s.title)).toEqual(['质控','客户定制'])
 expect(entryMethods('enrichment').map(m=>m.id)).toEqual(['ora','gsea_prerank'])
 expect(entryMethods('validation').map(m=>m.id)).toEqual(['qpcr','table'])
 expect(entryMethods('multiomics')[0].navigation).toMatchObject({view:'bio-insights',intent:'integration'})
 expect(entryMethods('custom').length).toBeGreaterThan(1)
})
it('reuses the existing import candidate and fixed published result of a stored original',()=>{
 const v={...requirement,material_refs:[{file_id:'raw',purpose:'raw_data',availability:'provided' as const}]}
 const original=file('raw','stored','bio_bundle')
 const waiting={id:'import-one',status:'waiting_confirmation',fileIds:['raw'],datasetId:'dataset',createdAt:'2026-11-03T00:00:00Z'}
 const [candidate]=entrySources(v,'qc',[original],[waiting])
 expect(candidate.status).toBe('等待核对确认')
 expect(sourceNavigation(candidate)).toEqual({view:'bio-import',fileId:'',importId:'import-one'})
 const [published]=entrySources(v,'qc',[original],[{...waiting,status:'succeeded',versionId:'fixed-old'}])
 expect(sourceNavigation(published)).toMatchObject({view:'bio-dataset',datasetId:'dataset',versionId:'fixed-old'})
 expect(entrySources(v,'qc',[original],[waiting,{...waiting,id:'import-two'}])).toHaveLength(2)
})

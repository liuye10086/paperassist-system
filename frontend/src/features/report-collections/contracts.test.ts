import {expect,test} from 'vitest'
import {sameCollectionScope,reorderItems,publicEntries,isExport} from './contracts'
import {correlationResult} from '../analysis/correlationFixtures'
test('collection scope ignores setup revision but requires the exact prepared source and language',()=>{
 const a={source:correlationResult.source,language:'zh-CN'}
 expect(sameCollectionScope(a,{...a,setup_revision:999})).toBe(true)
 expect(sameCollectionScope(a,{...a,language:'en'})).toBe(false)
 expect(sameCollectionScope(a,{...a,source:{...a.source,dataset_id:'other'}})).toBe(false)
})
test('reordering moves a single entry and preserves frozen identities',()=>{
 const entries=[{figure_id:'a'},{figure_id:'b'},{figure_id:'c'}]
 expect(reorderItems(entries,2,-1)).toEqual([entries[0],entries[2],entries[1]])
 expect(reorderItems(entries,0,-1)).toEqual(entries)
 expect(entries.map(e=>e.figure_id)).toEqual(['a','b','c'])
})
test('report preview strips internal identifiers and hashes recursively',()=>{
 expect(publicEntries({analysis_run_id:'secret',sha256:'a'.repeat(64),n:8,source:{dataset_id:'secret2',sheet_name:'Sheet1'}})).toEqual([['n',8],['source',{sheet_name:'Sheet1'}]])
})
test('saved export metadata cannot cross the immutable version or request',()=>{
 const report={id:'report1',schema_version:1,collection_id:'collection1',collection_version_id:'version1',build_request_id:'request1',export_revision:1,language:'zh-CN',filename:'report.docx',engine:{id:'collection_word_v1'},sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),size_bytes:100}
 const request={id:'request1',version_id:'version1',export_revision:1,status:'succeeded',missing:[],report}
 expect(isExport(request)).toBe(true)
 expect(isExport({...request,report:{...report,collection_version_id:'version2'}})).toBe(false)
 expect(isExport({...request,report:{...report,build_request_id:'request2'}})).toBe(false)
})

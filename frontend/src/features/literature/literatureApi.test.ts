import {it,expect} from 'vitest'
import {validSearchInput,validSource} from './literatureApi'
const input={research_topic:'Synthetic topic',source_context:{kind:'feedback',label:'Synthetic review',text:'Synthetic feedback'},query:'synthetic',year_from:null,year_to:null,publication_types:[],sort:'relevance',limit:20,output_language:'en'}
it('validates numeric limits strictly and rejects whitespace, null bytes, unsupported or repeated types',()=>{
 expect(validSearchInput(input)).toBe(true)
 for(const value of [{...input,limit:'20'},{...input,query:'  '},{...input,research_topic:'a\0b'},{...input,year_from:2026,year_to:2020},{...input,publication_types:['Review','Review']},{...input,publication_types:['Other']},{...input,source_context:{...input.source_context,text:'x'.repeat(6001)}}])expect(validSearchInput(value)).toBe(false)
})
it('rejects raw-source download links belonging to other projects or remote domains',()=>{
 const source={search_id:'s1',receipt_id:'r1',query:'synthetic',effective_query:'(synthetic)',retrieved_at:'2026-10-08T01:00:00Z',source_kind:'synthetic_fixture',cached:false,ordinal:1,source_download_url:'/api/v1/projects/p1/literature/receipts/r1/source'}
 expect(validSource(source,'p1')).toBe(true)
 expect(validSource(source,'p2')).toBe(false)
 expect(validSource({...source,source_download_url:'https://evil.test/source'},'p1')).toBe(false)
})
it('accepts legacy sources and validates supplied saved search context strictly',()=>{
 const source={search_id:'s1',receipt_id:'r1',query:'synthetic',effective_query:'(synthetic)',retrieved_at:'2026-10-08T01:00:00Z',source_kind:'synthetic_fixture',cached:false,ordinal:1,source_download_url:'/api/v1/projects/p1/literature/receipts/r1/source'}
 expect(validSource(source,'p1')).toBe(true)
 expect(validSource({...source,source_context:input.source_context},'p1')).toBe(true)
 expect(validSource({...source,source_context:null},'p1')).toBe(true)
 for(const context of [{kind:'unknown',label:'x',text:'x'},{kind:['feedback'],label:'x',text:'x'},{kind:'section',label:1,text:'x'},{kind:'section',label:'x',text:null},{kind:'section',label:'x'},{kind:'section',label:'x'.repeat(201),text:'x'},{kind:'section',label:'x',text:'x'.repeat(6001)}])expect(validSource({...source,source_context:context},'p1')).toBe(false)
})

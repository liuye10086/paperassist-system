import { expect, it } from 'vitest'
import { mergeFileMetadata, type LibraryFile } from './fileLibraryApi'
it('merges parse and metadata revisions independently',()=>{
 const old={id:'f',parse_revision:2,parse_status:'queued',purposes:['raw_data'],metadata_revision:4} as LibraryFile
 const latest={...old,parse_revision:5,parse_status:'parsed',purposes:['paper'],metadata_revision:1} as LibraryFile
 const result=mergeFileMetadata(old,latest)
 expect(result.parse_status).toBe('parsed');expect(result.parse_revision).toBe(5);expect(result.metadata_revision).toBe(4)
})

it('keeps confirmed preview availability with its newer parse revision',()=>{
 const latest={id:'f',parse_revision:5,parse_status:'parsed',purposes:[],metadata_revision:1,source:{kind:'excel_parse',preview_available:true,parser_version:'v1',preview_row_limit:20}} as unknown as import('./fileLibraryApi').FileDetail
 const incoming={...latest,parse_revision:2,parse_status:'queued',source:{...latest.source,preview_available:false}} as typeof latest
 expect(mergeFileMetadata(incoming,latest).source.preview_available).toBe(true)
})

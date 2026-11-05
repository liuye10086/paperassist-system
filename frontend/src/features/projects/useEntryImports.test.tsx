import {act,cleanup,renderHook,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {researchRequest} from '../research-results/api'
import useEntryImports from './useEntryImports'
vi.mock('../research-results/api',()=>({projectBase:(p:string)=>'/api/v1/projects/'+p,researchRequest:vi.fn()}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
const task=(id:string,project='p1')=>({task:{project_id:project,status:'waiting_confirmation',input_version:{kind:'bio_import',import_id:id,dataset_id:'dataset',source_file_ids:['raw']},created_at:''}})
it('reads all existing import pages without treating unrelated project tasks as sources',async()=>{
 vi.mocked(researchRequest).mockImplementation(async url=>url.includes('page=1&')?{items:[task('first'),task('foreign','p2')],total:51}:{items:[task('second')],total:51})
 const {result}=renderHook(()=>useEntryImports('p1',true))
 await waitFor(()=>expect(result.current.unknown).toBe(false))
 expect(result.current.data?.map(i=>i.id)).toEqual(['first','second']);expect(researchRequest).toHaveBeenCalledTimes(2)
})
it('keeps a failed read unverified and allows a manual retry',async()=>{
 vi.mocked(researchRequest).mockRejectedValueOnce(Error('offline')).mockResolvedValue({items:[],total:0})
 const {result}=renderHook(()=>useEntryImports('p1',true));await waitFor(()=>expect(result.current.error).not.toBe(''))
 expect(result.current.unknown).toBe(true);act(()=>result.current.refresh());await waitFor(()=>expect(result.current.unknown).toBe(false));expect(result.current.data).toEqual([])
})
it('does not read import history for ordinary tables',()=>{
 renderHook(()=>useEntryImports('p1',false));expect(researchRequest).not.toHaveBeenCalled()
})
it('rereads import status after returning from the review workspace',async()=>{
 vi.mocked(researchRequest).mockResolvedValue({items:[],total:0})
 const {result,rerender}=renderHook(({location})=>useEntryImports('p1',true,location),{initialProps:{location:'overview'}})
 await waitFor(()=>expect(result.current.unknown).toBe(false))
 rerender({location:'bio-import'});await waitFor(()=>expect(researchRequest).toHaveBeenCalledTimes(2))
 vi.mocked(researchRequest).mockResolvedValue({items:[task('newly-imported')],total:1})
 rerender({location:'overview'});await waitFor(()=>expect(result.current.data?.[0]?.id).toBe('newly-imported'))
})

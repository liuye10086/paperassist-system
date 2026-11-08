import {afterEach,expect,it,vi} from 'vitest'
import {act,cleanup,render,screen} from '@testing-library/react'
import {apiFetch} from '../../shared/api/client'
import {setLocale} from '../../shared/i18n'
import BioAnalysisReview from './BioAnalysisReview'
import {SingleCellCandidateTask} from './SingleCellCandidates'
import {processedFixture,runFixture} from './spatialFixtures'

vi.mock('../../shared/api/client',()=>({apiFetch:vi.fn(),getApiUserId:()=> 'owner1',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();vi.clearAllMocks();setLocale('zh-CN')})

const quotaMessages={
 'zh-CN':'存储配额不足；已有成果仍可查看下载。请查看“本人存储”，联系管理员申请扩容后显式重试原操作。',
 en:'Storage quota exceeded; existing results remain available to view and download. Check My storage and contact an administrator to request more capacity before explicitly retrying the original operation.',
} as const

for(const view of ['analysis','candidate'] as const){
 for(const locale of ['zh-CN','en'] as const){
  it(`localizes the ${view} quota failure and capacity recovery guidance in ${locale}`,async()=>{
   setLocale(locale)
   const task={...runFixture.task,status:'failed' as const,error_code:'storage_quota_exceeded'}
   const run={id:'candidate1',name:'SingleR',parent_processed_source:processedFixture.source,reference_id:'reference1',task,result:null}
   vi.mocked(apiFetch).mockImplementation(async url=>Response.json(String(url).endsWith('/bio-single-cell-references')?{items:[]}:String(url).endsWith('/annotation-runs')?{items:[run]}:String(url).includes('/bio-single-cell-annotation-runs/')?run:{...runFixture,candidate:null,task}))
   if(view==='analysis')render(<BioAnalysisReview projectId="p1" runId="run1" onNavigate={vi.fn()}/> )
   else render(<SingleCellCandidateTask projectId="p1" result={processedFixture} onPublished={vi.fn()}/> )
   expect(await screen.findByText(quotaMessages[locale])).toBeTruthy()
   expect(screen.queryByText('storage_quota_exceeded')).toBeNull()
   act(()=>setLocale(locale==='en'?'zh-CN':'en'))
   expect(screen.getByText(quotaMessages[locale==='en'?'zh-CN':'en'])).toBeTruthy()
   expect(vi.mocked(apiFetch).mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)
  })
 }
}

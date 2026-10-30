import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import WritingLive from './WritingLive'
import WritingScienceReview from './WritingScienceReview'
import {liveRequest,unsubmittedRequest} from './writingLiveFixtures'
import {manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
import {validLiveRequest} from './writingLiveTypes'
import {setLocale} from '../../shared/i18n'

const unknownRequest={...unsubmittedRequest('reserved'),model_calls:[{...unsubmittedRequest('reserved').model_calls[0],provider_provenance:'not_recorded' as const}]}
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})

it('accepts explicitly unrecorded call provenance and retains not_submitted historical reads',()=>{
 expect(validLiveRequest(unknownRequest,'p1','m1')).toBe(true)
 expect(validLiveRequest(unsubmittedRequest('reserved'),'p1','m1')).toBe(true)
 expect(validLiveRequest({...unknownRequest,model_calls:[{...unknownRequest.model_calls[0],provider_provenance:'verified_live'}]},'p1','m1')).toBe(false)
})

it.each(['zh-CN','en'] as const)('shows unrecorded provenance in %s without inferring an executed live or simulated call',locale=>{
 setLocale(locale)
 render(<WritingScienceReview projectId="p1" manuscriptId="m1" request={unknownRequest} onPublished={vi.fn()}/>)
 expect(screen.getByText(locale==='en'?/Provenance was not separately recorded; the model name does not establish a live call\./:/来源未单独记录；不能据模型名确认真实调用。/)).toBeTruthy()
 expect(screen.queryByText(/真实 provider 回执|离线模拟回执 \/ 演示用量|尚未提交；没有供应商回执。|Live provider receipt|Offline simulated receipt \/ demo usage/)).toBeNull()
})

it('opens a retained writing request whose call provenance is unrecorded using reads only',async()=>{
 const retained={...unknownRequest,id:liveRequest.id,task:{...unknownRequest.task,id:liveRequest.id}}
 const fetcher=vi.fn(async(url:string,_init?:RequestInit)=>Response.json(url.endsWith('/writing-previews')?{items:[],capabilities:{real_calls_enabled:false}}:{items:[retained]}))
 vi.stubGlobal('fetch',fetcher)
 render(<WritingLive projectId="p1" manuscriptId="m1" version={manuscriptFixture.versions[0] as unknown as ManuscriptVersion} onPublished={vi.fn()}/>)
 fireEvent.click(await screen.findByRole('button',{name:'审核此原始候选'}))
 expect(screen.getByText(/来源未单独记录；不能据模型名确认真实调用。/)).toBeTruthy()
 expect(screen.queryByRole('alert')).toBeNull();expect(fetcher.mock.calls.every(([,init])=>!init?.method||init.method==='GET')).toBe(true)
})

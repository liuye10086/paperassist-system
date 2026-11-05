import {StrictMode} from 'react'
import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import AuthBoundary from '../auth/AuthBoundary'
import useResearchDraft from './useResearchDraft'

afterEach(()=>{cleanup();sessionStorage.clear();vi.unstubAllGlobals()})
it('restores the same owner draft through the initial StrictMode auth cleanup, and clears it on authenticated unmount',async()=>{
 const key='paperassist.research-draft.v1:owner:p1:writing:d1'
 sessionStorage.setItem(key,JSON.stringify({notes:'刷新前的写作材料'}))
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/me')?{user:{id:'owner',email:'owner@example.test',role:'user'},csrf_token:'fixture-csrf'}:{})))
 function Draft(){const [value]=useResearchDraft('p1','writing:d1',()=>({notes:'空白草稿'}));return <p>{value.notes}</p>}
 const view=render(<StrictMode><AuthBoundary><Draft/></AuthBoundary></StrictMode>)
 expect(await screen.findByText('刷新前的写作材料')).toBeTruthy()
 view.unmount()
 expect(sessionStorage.getItem(key)).toBeNull()
})

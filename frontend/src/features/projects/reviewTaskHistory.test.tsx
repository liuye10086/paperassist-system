import {act,cleanup,renderHook,waitFor} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import useProjectSelection from './useProjectSelection'

afterEach(()=>{cleanup();vi.unstubAllGlobals();window.history.replaceState(null,'','/')})
function start(hash='#project=p1&section=reviews&round=r1') {
 window.history.replaceState(null,'','/'+hash)
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json({id:url.split('/').at(-1),name:'Research',research_topic:'Topic',project_type:'sci',file_count:0,created_at:'2026-10-26T00:00:00Z',updated_at:'2026-10-26T00:00:00Z'})))
 return renderHook(()=>useProjectSelection(()=>{},()=>{})).result
}
it('retains inactive review identity and task detail through same-project history',async()=>{
 const s=start();await waitFor(()=>expect(s.current.project?.id).toBe('p1'))
 act(()=>s.current.selectReviewItem('i1'));act(()=>s.current.selectReviewView('plan'))
 act(()=>s.current.selectTask('t1'));act(()=>s.current.selectTaskDetailView('actions'))
 act(()=>s.current.selectTaskDetailView('events'))
 await act(async()=>window.history.back());await waitFor(()=>expect(s.current.taskDetailView).toBe('actions'))
 act(()=>s.current.changeSection('reviews'))
 expect(window.location.hash).toBe('#project=p1&section=reviews&view=plan&item=i1&round=r1')
 act(()=>s.current.changeSection('tasks'))
 expect(window.location.hash).toBe('#project=p1&section=tasks&view=actions&task=t1')
})
it('updates run and document identities without reusing a document from another run',()=>{
 const s=start()
 act(()=>s.current.selectReviewView('revision'));act(()=>s.current.selectReviewRun('run1'))
 act(()=>s.current.selectReviewView('response'));act(()=>s.current.selectReviewDocument('doc1'))
 expect(window.location.hash).toBe('#project=p1&section=reviews&view=response&round=r1&reviewRun=run1&reviewDocument=doc1')
 act(()=>s.current.selectReviewRun('run2'))
 expect(s.current.reviewLink.document).toBe('');expect(s.current.reviewLink.run).toBe('run2')
 act(()=>s.current.selectRound('r2'))
 expect(s.current.reviewView).toBe('items');expect(s.current.reviewLink.run).toBe('');expect(s.current.reviewItemId).toBe('')
})
it('returns from task details to list and clears all task destinations across projects',()=>{
 const s=start()
 act(()=>s.current.selectReviewItem('i1'));act(()=>s.current.selectTask('t1'));act(()=>s.current.selectTaskDetailView('events'))
 act(()=>s.current.selectTask(''))
 expect(window.location.hash).toBe('#project=p1&section=tasks');expect(s.current.taskDetailView).toBe('overview')
 act(()=>s.current.selectTask('t2'));act(()=>s.current.open('p2'))
 expect(s.current.taskId).toBe('');expect(s.current.reviewView).toBe('list');expect(s.current.reviewItemId).toBe('');expect(s.current.reviewLink.round).toBe('')
})
it('restores a fixed review document deep link after an inactive section',()=>{
 const s=start()
 act(()=>s.current.selectRound('r2'));act(()=>s.current.changeSection('manuscripts'))
 act(()=>{window.history.replaceState(null,'','/#project=p1&section=reviews&round=r1&reviewRun=run1&reviewDocument=doc1');window.dispatchEvent(new HashChangeEvent('hashchange'))})
 expect(s.current.reviewView).toBe('documents');expect(s.current.reviewLink).toMatchObject({round:'r1',run:'run1',document:'doc1'})
})

import {act,cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import ManuscriptPreview from './ManuscriptPreview'
import {snapshotFixture} from './manuscriptFixtures'
import type {Snapshot} from './manuscriptTypes'
import {setLocale} from '../../shared/i18n'

afterEach(()=>{cleanup();setLocale('zh-CN')})
const frozenNotice='科学审核已完成；逐章语言与学校导出仍待核对。'
function schoolSnapshot(status='scientific_and_language_reviewed'):Snapshot{
 return {...snapshotFixture,notice:frozenNotice,thesis_context:{profile:{school:'Synthetic school',applicable_version:'2026'},confirmation_id:'frozen-confirmation'},sections:[],writing_provenance:{schema_version:2,school_content_version:'school-live-v1',provider_provenance:'synthetic_fixture',verification_status:status}} as unknown as Snapshot
}

it('folds the completed school candidate-stage notice by default, preserves its exact text and translates its summary',()=>{
 const snapshot=schoolSnapshot(),original=JSON.stringify(snapshot)
 render(<ManuscriptPreview snapshot={snapshot}/> )
 const summary=screen.getByText('查看候选阶段的冻结提示'),details=summary.closest('details')!
 expect(details.open).toBe(false)
 expect(screen.getByText(frozenNotice).closest('details')).toBe(details)
 expect(screen.getByText('已记录人工科学与语言审核；不等同科学有效性证明。').closest('details')).toBeNull()
 fireEvent.click(summary);expect(details.open).toBe(true)
 expect(screen.getByText(frozenNotice).textContent).toBe(frozenNotice)
 act(()=>setLocale('en'))
 expect(screen.getByText('View the frozen candidate-stage notice')).toBeTruthy()
 expect(screen.getByText(frozenNotice).textContent).toBe(frozenNotice)
 expect(JSON.stringify(snapshot)).toBe(original)
})

it('keeps the original notice visible for pending school reviews and fully reviewed SCI or legacy school drafts',()=>{
 const snapshot=schoolSnapshot('scientific_reviewed_language_pending')
 const {rerender}=render(<ManuscriptPreview snapshot={snapshot}/> )
 expect(screen.getByText(frozenNotice).closest('details')).toBeNull()
 expect(screen.queryByText('查看候选阶段的冻结提示')).toBeNull()
 const sci={...snapshot,thesis_context:undefined,writing_provenance:{...snapshot.writing_provenance!,school_content_version:undefined,verification_status:'scientific_and_language_reviewed'}}
 rerender(<ManuscriptPreview snapshot={sci}/> )
 expect(screen.getByText(frozenNotice).closest('details')).toBeNull()
 rerender(<ManuscriptPreview snapshot={{...schoolSnapshot(),writing_provenance:{...schoolSnapshot().writing_provenance!,school_content_version:undefined}}}/> )
 expect(screen.getByText(frozenNotice).closest('details')).toBeNull()
})

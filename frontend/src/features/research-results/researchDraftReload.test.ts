import {expect,it} from 'vitest'
import './useResearchDraft'
import {setApiSession,clearApiSession} from '../../shared/api/client'

it('retains only the restored owner draft and pending requests on page load, then clears them on session transitions',()=>{
 sessionStorage.clear()
 const retained=['draft','request','publish'].map(kind=>`paperassist.research-${kind}.v1:owner:p1:writing:d1`)
 retained.forEach(key=>sessionStorage.setItem(key,'saved'))
 const foreign='paperassist.research-draft.v1:other:p1:writing:d1'
 sessionStorage.setItem(foreign,'other data')
 setApiSession('restored-csrf','owner')
 retained.forEach(key=>expect(sessionStorage.getItem(key)).toBe('saved'))
 expect(sessionStorage.getItem(foreign)).toBeNull()
 setApiSession('switched-csrf','other')
 retained.forEach(key=>expect(sessionStorage.getItem(key)).toBeNull())
 sessionStorage.setItem(foreign,'new draft')
 clearApiSession()
 expect(sessionStorage.getItem(foreign)).toBeNull()
})

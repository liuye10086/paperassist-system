import {act,cleanup,renderHook} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {useInsightDraft} from './hooks'
vi.mock('../../shared/api/client',()=>({getApiUserId:()=> 'owner',onApiSessionChanged:()=>()=>{}}))
afterEach(()=>{cleanup();sessionStorage.clear()})
it('restores each project and version draft separately when switching context',()=>{const {result,rerender}=renderHook(({p,v})=>useInsightDraft(p,v,()=>({notes:''})),{initialProps:{p:'p1',v:'v1'}});act(()=>result.current[1]({notes:'A notes'}));rerender({p:'p2',v:'v1'});expect(result.current[0].notes).toBe('');act(()=>result.current[1]({notes:'B notes'}));rerender({p:'p1',v:'v2'});expect(result.current[0].notes).toBe('');rerender({p:'p1',v:'v1'});expect(result.current[0].notes).toBe('A notes');rerender({p:'p2',v:'v1'});expect(result.current[0].notes).toBe('B notes')})

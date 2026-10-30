import { fireEvent,render,screen,cleanup } from '@testing-library/react'
import { afterEach,describe,expect,it,vi } from 'vitest'
import RequirementForm from './RequirementForm'
import { emptyRequirement } from './state'
afterEach(cleanup)
describe('requirement form',()=>{
 it('retains hidden SCI request when services change and records pending contact',()=>{
  const content={...emptyRequirement(),services:['sci_draft'],sci_request:{journal:{state:'known',value:'Preserved'}}};const changed=vi.fn()
  render(<RequirementForm value={content} onChange={changed}/>);
  fireEvent.click(screen.getByLabelText('SCI 稿件'));expect(changed.mock.lastCall?.[0].sci_request).toEqual(content.sci_request)
  fireEvent.change(screen.getByLabelText('联系人状态'),{target:{value:'pending'}});expect(changed.mock.lastCall?.[0].contact.alias).toEqual({state:'pending',value:null})
 })
})
import {setLocale} from '../../shared/i18n'
it('shows explicit pending states in English',()=>{setLocale('en');try{render(<RequirementForm value={emptyRequirement()} onChange={vi.fn()}/>);expect((screen.getByLabelText('Contact name status') as HTMLSelectElement).value).toBe('pending');expect(screen.getAllByText(/(?:Waiting for|Pending) confirmation/).length).toBeGreaterThan(0)}finally{setLocale('zh-CN')}})

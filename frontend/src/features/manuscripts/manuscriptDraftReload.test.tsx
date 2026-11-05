import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import ManuscriptWriting from './ManuscriptWriting'
import WritingLive from './WritingLive'
import ManuscriptExports from './ManuscriptExports'
import {manuscriptFixture} from './manuscriptFixtures'
import type {ManuscriptVersion} from './manuscriptTypes'
const version=manuscriptFixture.versions[0] as unknown as ManuscriptVersion
const props={projectId:'p1',manuscriptId:'m1',version,onPublished:vi.fn()}
beforeEach(()=>{sessionStorage.clear();vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/writing-previews')?{items:[],capabilities:{real_calls_enabled:false}}:{items:[]})))})
afterEach(()=>{cleanup();vi.unstubAllGlobals();sessionStorage.clear()})
it('restores full and chapter writing drafts only for the same fixed version and project',()=>{
 const view=render(<ManuscriptWriting {...props}/>);fireEvent.change(screen.getByLabelText('自由写作要求'),{target:{value:'full'}});fireEvent.change(screen.getByLabelText('写作方式'),{target:{value:'rewrite_section'}});fireEvent.change(screen.getByLabelText('自由写作要求'),{target:{value:'chapter'}});view.unmount()
 const restored=render(<ManuscriptWriting {...props}/>);expect(screen.getByLabelText('自由写作要求')).toHaveProperty('value','chapter');fireEvent.change(screen.getByLabelText('写作方式'),{target:{value:'full_draft'}});expect(screen.getByLabelText('自由写作要求')).toHaveProperty('value','full');restored.rerender(<ManuscriptWriting {...props} version={{...version,id:'v2'}}/>);expect(screen.getByLabelText('自由写作要求')).toHaveProperty('value','');restored.rerender(<ManuscriptWriting {...props} projectId="p2"/>);expect(screen.getByLabelText('自由写作要求')).toHaveProperty('value','')
})
it('restores controlled writing input after remount',()=>{
 const view=render(<WritingLive {...props}/>);fireEvent.change(screen.getByLabelText('受控写作关键词（每行一项）'),{target:{value:'draft keyword'}});view.unmount();render(<WritingLive {...props}/>);expect(screen.getByLabelText('受控写作关键词（每行一项）')).toHaveProperty('value','draft keyword');expect(screen.getByRole('button',{name:'提交已授权写作'}).matches(':disabled')).toBe(true)
})
it('restores school manual fields after remount',()=>{
 const v={...version,snapshot:{...version.snapshot,thesis_context:{confirmation_id:'c',chapters:[]}}} as unknown as ManuscriptVersion
 const view=render(<ManuscriptExports {...props} version={v}/>);fireEvent.change(screen.getByLabelText('作者'),{target:{value:'作者甲'}});view.unmount();render(<ManuscriptExports {...props} version={v}/>);expect(screen.getByLabelText('作者')).toHaveProperty('value','作者甲')
})

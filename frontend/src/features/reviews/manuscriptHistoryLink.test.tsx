import {act,cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import ProjectManuscripts from '../manuscripts/ProjectManuscripts'
import {candidatesFixture,manuscriptFixture} from '../manuscripts/manuscriptFixtures'
import {validSnapshot} from '../manuscripts/manuscriptTypes'
import {setLocale} from '../../shared/i18n'
afterEach(()=>{cleanup();vi.unstubAllGlobals();setLocale('zh-CN')})
it('opens the exact public manuscript revision rather than an implicit latest draft',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/candidates')?candidatesFixture:url.endsWith('/manuscripts')?{items:[manuscriptFixture]}:{items:[]})))
 const props={projectId:'p1',researchTopic:'Synthetic history',outputLanguage:'en' as const,active:true,initialManuscript:'m1',initialRevision:1}
 render(<ProjectManuscripts {...props}/>);expect(await screen.findByText('正在查看版本 1')).toBeTruthy()
})
it('accepts preserved v2 numeric bindings only with validated public return or revision provenance',()=>{
 const original=manuscriptFixture.versions[0].snapshot,snapshot={...original,methods:[{...original.methods[0],numeric_bindings:[{occurrence:0,value:'12',kind:'study',source_alias:'S1',fact_path:'n'}]}]}
 const returned={schema_version:1,return_id:'return1',previous_round_id:'round1',revision_id:null,base_version_id:'v1',input_sha256:'a'.repeat(64),source:{file_id:'fdoc',document_version_id:'parse1'},mappings:[{input_section_id:'input1',chapter_id:'methods'}],preview_sha256:'b'.repeat(64)}
 expect(validSnapshot({...snapshot,user_return_provenance:returned},'p1')).toBe(true)
 expect(validSnapshot({...snapshot,review_revision_provenance:{revision_id:'revision1',round_id:'round1',base_version_id:'v1',input_sha256:'a'.repeat(64),synthetic:true}},'p1')).toBe(true)
 expect(validSnapshot({...snapshot,user_return_provenance:{...returned,input_sha256:'invalid'}},'p1')).toBe(false)
 expect(validSnapshot({...snapshot,user_return_provenance:returned,methods:[{...snapshot.methods[0],numeric_bindings:[{occurrence:-1,value:'12',kind:'study',source_alias:'S1',fact_path:'n'}]}]},'p1')).toBe(false)
})
it('labels verified public user returns in SCI and school history while keeping adjacent system versions distinct',async()=>{
 const base={...manuscriptFixture.versions[0],id:'base4',revision:4,exports:[]},returned={...base,id:'return5',revision:5,parent_version_id:'base4',snapshot:{...base.snapshot,user_return_provenance:{schema_version:1,return_id:'return1',previous_round_id:'round1',revision_id:null,base_version_id:'base4',input_sha256:'a'.repeat(64),source:{file_id:'fdoc',document_version_id:'parse1'},mappings:[{input_section_id:'input1',chapter_id:'methods'}],preview_sha256:'b'.repeat(64)}}},next={...base,id:'system6',revision:6,parent_version_id:'return5'},manuscript={...manuscriptFixture,current_revision:6,versions:[base,returned,next]}
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>Response.json(url.endsWith('/candidates')?candidatesFixture:url.endsWith('/manuscripts')?{items:[manuscript]}:{items:[]})))
 for(const projectType of ['sci','thesis'] as const){
  render(<ProjectManuscripts projectId="p1" projectType={projectType} researchTopic="Synthetic return history" outputLanguage="en" active/>);const returnedRow=(await screen.findByText('版本 5')).closest('.manuscript-version');expect(returnedRow?.textContent).toContain('用户回传');expect(returnedRow?.textContent).toContain('父版本 4');for(const revision of [4,6]){const systemRow=screen.getByText(`版本 ${revision}`).closest('.manuscript-version');expect(systemRow?.textContent).toContain('系统生成');expect(systemRow?.textContent).not.toContain('用户回传')}
  if(projectType==='thesis'){act(()=>setLocale('en'));expect(screen.getByText('Version 5').closest('.manuscript-version')?.textContent).toContain('User returned manuscript');expect(screen.getByText('Version 6').closest('.manuscript-version')?.textContent).toContain('System generated')}
  cleanup()
 }
})

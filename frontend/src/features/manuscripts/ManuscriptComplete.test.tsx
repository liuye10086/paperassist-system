import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import ManuscriptPreview from './ManuscriptPreview'
import {setLocale} from '../../shared/i18n'
import {snapshotFixture} from './manuscriptFixtures'
import {validSnapshot,type Snapshot} from './manuscriptTypes'
afterEach(()=>{cleanup();setLocale('zh-CN')})
export const completeSnapshot={...snapshotFixture,sections:['title','abstract','introduction','results','discussion','materials_and_methods','references'].map(id=>({id,paragraphs:[{id:`writing:${id}:1`,text:`Saved ${id}`,origin:'model_generated',source_ids:[],citations:[],numeric_bindings:[]}]})),keywords:['User keyword'],acknowledgements:'User thanks',writing_provenance:{provider_provenance:'synthetic_fixture',verification_status:'not_verified'}}
it('accepts seven frozen sections and shows them in manuscript language with explicit synthetic label',()=>{
 expect(validSnapshot(completeSnapshot,'p1')).toBe(true)
 render(<ManuscriptPreview snapshot={completeSnapshot as unknown as Snapshot}/> )
 expect(screen.getByText('Saved abstract')).toBeTruthy()
 expect(screen.getByRole('heading',{name:'Discussion'})).toBeTruthy()
 expect(screen.getByText(/合成模拟/)).toBeTruthy()
 expect(screen.getByText('User keyword')).toBeTruthy()
 expect(screen.getByText('User thanks')).toBeTruthy()
})
it('rejects malformed, reordered or cross-project complete snapshots',()=>{
 expect(validSnapshot({...completeSnapshot,sections:[...completeSnapshot.sections].reverse()},'p1')).toBe(false)
 expect(validSnapshot({...completeSnapshot,sections:completeSnapshot.sections.map(s=>({...s,paragraphs:[{text:'unbound'}]}))},'p1')).toBe(false)
 expect(validSnapshot(completeSnapshot,'p2')).toBe(false)
})

it('keeps Chinese manuscript section order when the workspace is English and hides superseded fact paragraphs',()=>{
 setLocale('en');const snapshot={...completeSnapshot,output_language:'zh-CN'} as unknown as Snapshot;render(<ManuscriptPreview snapshot={snapshot}/>);const titles=screen.getAllByRole('heading',{level:4}).map(n=>n.textContent).filter(n=>['标题','摘要','引言','结果','讨论','材料与方法','参考文献'].includes(n??''));expect(titles).toEqual(['标题','摘要','引言','结果','讨论','材料与方法','参考文献']);expect(screen.queryByText('Frozen methods')).toBeNull();expect(screen.getByText('Saved materials_and_methods')).toBeTruthy()
})
it('renders frozen citation bindings using saved reference numbering without exposing review identifiers',()=>{
 const snapshot={...completeSnapshot,references:[{number:1,text:'Frozen reference',project_reference_id:'ref1'}],sections:completeSnapshot.sections.map(s=>s.id==='introduction'?{...s,paragraphs:[{...s.paragraphs[0],text:'Frozen reviewed claim (1)',origin:'literature',citations:[{project_reference_id:'ref1',reference_id:'canonical1',review_id:'private-review',metadata_version_id:'metadata1'}]}]}:s)}
 expect(validSnapshot(snapshot,'p1')).toBe(true);render(<ManuscriptPreview snapshot={snapshot as unknown as Snapshot}/>);expect(screen.getByRole('link',{name:'Citation source 1'})).toBeTruthy();expect(screen.queryByText('private-review')).toBeNull()
})

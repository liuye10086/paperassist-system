import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import {articleStructures,articleHeading,type ArticleType} from './articleStructure'
import {snapshotFixture} from './manuscriptFixtures'
import {validSnapshot,type Snapshot} from './manuscriptTypes'
import {validPreviewInput} from './writingLiveTypes'
import ManuscriptPreview from './ManuscriptPreview'
afterEach(cleanup)
it.each(Object.keys(articleStructures) as ArticleType[])('admits and renders the exact %s article structure',kind=>{
 const snapshot={...snapshotFixture,article_type:kind,article_structure_version:'article-scope-v1',sections:articleStructures[kind].map(id=>({id,paragraphs:[{id:`p-${id}`,text:`Saved ${id}`,origin:'user_provided',source_ids:[],citations:[]}]}))} as Snapshot
 expect(validSnapshot(snapshot,'p1')).toBe(true)
 expect(validSnapshot({...snapshot,sections:snapshot.sections!.slice(1)},'p1')).toBe(false)
 render(<ManuscriptPreview snapshot={snapshot}/>)
 for(const id of articleStructures[kind])expect(screen.getByRole('heading',{name:articleHeading(kind,id,'en')})).toBeTruthy()
})
it('accepts scoped edits of a published methods article and keeps school request restrictions',()=>{
 const input={schema_version:4,base_revision:1,document_kind:'sci',article_type:'methods',mode:'polish',target_section:null,target_sections:['discussion'],target_paragraph_ids:[],paragraph_plan:[],brief_limits:null,output_language:'en',instructions:'',keywords:[],acknowledgements:'',selected_source_ids:[],selected_evidence_ids:[]}
 expect(validPreviewInput(input)).toBe(true)
 expect(validPreviewInput({...input,document_kind:'thesis'})).toBe(false)
 expect(validPreviewInput({...input,document_kind:'thesis',article_type:'research'})).toBe(true)
 expect(validPreviewInput({...input,validation_source_ids:['source'],selected_source_ids:['source']})).toBe(true)
 expect(validPreviewInput({...input,validation_source_ids:['unselected']})).toBe(false)
 expect(validPreviewInput({...input,article_type:'brief',validation_source_ids:['source'],selected_source_ids:['source']})).toBe(false)
})

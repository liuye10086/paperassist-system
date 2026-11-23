import { expect,it } from 'vitest'
import { validSnapshot, validManuscript, validCandidates } from './manuscriptTypes'
import { snapshotFixture,manuscriptFixture,candidatesFixture } from './manuscriptFixtures'

it('accepts only original review figures in native review sections outside the theme list', () => {
 const source = {kind: 'original', id: 'illustration', file_id: 'illustration', role: 'image_observation'}
 const material = {section_id: 'discussion', filename: 'overview.png', kind: 'figure', result: '', selection: source}
 const plan = {kind: 'narrative_review', title: 'Review', keywords: [], sections: [], materials: [material]}
 const candidates = (paperPlan: object) => ({...candidatesFixture, paper_plan: {...paperPlan, token:'a'.repeat(64), omitted_count:0}})
 expect(validCandidates(candidates(plan), 'p1')).toBe(true)
 expect(validSnapshot({...snapshotFixture, paper_plan: plan}, 'p1')).toBe(true)
 for (const invalid of [
   {...plan, kind: 'research'},
   {...plan, materials: [{...material, kind: 'table'}]},
   {...plan, materials: [{...material, section_id: 'abstract'}]},
   {...plan, materials: [{...material, selection: {...source, kind: 'document_version'}}]},
 ]) expect(validCandidates(candidates(invalid), 'p1')).toBe(false)
})
it('accepts frozen stable paragraph and table identities without exposing or rewriting them',()=>{
 expect(validSnapshot({...snapshotFixture,methods:[{...snapshotFixture.methods[0],id:'methods:research_question'}],results_groups:[{id:'group1',title:'Result',paragraphs:[{...snapshotFixture.methods[0],id:'results:run1',origin:'computed_result'}],tables:[{id:'table:run1',title:'Table',columns:['Value'],rows:[['1']],source_ids:['run1']}],figures:[]}]},'p1')).toBe(true)
})
it('rejects cross-project snapshots and download URLs',()=>{
 expect(validSnapshot(snapshotFixture,'p2')).toBe(false)
 expect(validCandidates({...candidatesFixture,items:[{...candidatesFixture.items[0],download_url:'/api/v1/projects/p2/files/f/download'}]},'p1')).toBe(false)
 expect(validManuscript({...manuscriptFixture,versions:[{...manuscriptFixture.versions[0],exports:[{...manuscriptFixture.versions[0].exports[0],download_url:'https://example.com/private'}]}]},'p1')).toBe(false)
 expect(validManuscript({...manuscriptFixture,versions:[{...manuscriptFixture.versions[0],exports:[{...manuscriptFixture.versions[0].exports[0],version_id:'another-version'}]}]},'p1')).toBe(false)
})
it('accepts optional illustration fields and image observations while preserving historical drafts',()=>{
 const observation={...snapshotFixture.methods[0],origin:'image_observation',cross_references:[{kind:'figure',target_id:'image1',number:1,panel_label:'A'}]}
 const snapshot={...snapshotFixture,illustration_check_version:1,methods:[observation],results_groups:[{id:'g1',title:'Observations',paragraphs:[observation],tables:[{id:'table:run1',number:1,title:'Table',columns:['Value'],rows:[['1']],source_ids:['run1']}],figures:[{id:'image1',number:1,title:'Figure',caption:'Candidate',caption_status:'candidate',sha256:'a'.repeat(64),source_ids:[]}]}]}
 expect(validSnapshot(snapshotFixture,'p1')).toBe(true)
 expect(validSnapshot(snapshot,'p1')).toBe(true)
 expect(validSnapshot({...snapshot,illustration_check_version:2},'p1')).toBe(false)
 expect(validSnapshot({...snapshot,methods:[{...observation,cross_references:[{kind:'figure',target_id:'image1',number:1,panel_label:'a'}]}]},'p1')).toBe(false)
 expect(validSnapshot({...snapshot,methods:[{...observation,cross_references:[{kind:'table',target_id:'table:run1',number:1,panel_label:'A'}]}]},'p1')).toBe(false)
})

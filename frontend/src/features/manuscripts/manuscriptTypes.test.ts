import { expect,it } from 'vitest'
import { validSnapshot, validManuscript, validCandidates } from './manuscriptTypes'
import { snapshotFixture,manuscriptFixture,candidatesFixture } from './manuscriptFixtures'
it('accepts frozen stable paragraph and table identities without exposing or rewriting them',()=>{
 expect(validSnapshot({...snapshotFixture,methods:[{...snapshotFixture.methods[0],id:'methods:research_question'}],results_groups:[{id:'group1',title:'Result',paragraphs:[{...snapshotFixture.methods[0],id:'results:run1',origin:'computed_result'}],tables:[{id:'table:run1',title:'Table',columns:['Value'],rows:[['1']],source_ids:['run1']}],figures:[]}]},'p1')).toBe(true)
})
it('rejects cross-project snapshots and download URLs',()=>{
 expect(validSnapshot(snapshotFixture,'p2')).toBe(false)
 expect(validCandidates({...candidatesFixture,items:[{...candidatesFixture.items[0],download_url:'/api/v1/projects/p2/files/f/download'}]},'p1')).toBe(false)
 expect(validManuscript({...manuscriptFixture,versions:[{...manuscriptFixture.versions[0],exports:[{...manuscriptFixture.versions[0].exports[0],download_url:'https://example.com/private'}]}]},'p1')).toBe(false)
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

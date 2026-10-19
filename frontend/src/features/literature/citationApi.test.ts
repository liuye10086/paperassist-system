import {expect,it} from 'vitest'
import {usableClaim,validDraft,draftInput,referenceCopy,type Candidate,type DraftView} from './citationApi'
it('never makes an explicitly unverified metadata source selectable even if a summary is inconsistent',()=>{
 const candidate={metadata:{usable:true,source_verified:false,source_current:true}} as Candidate
 const claim={id:'c1',revision:1,content:'Synthetic',review_source_current:true,citation_eligible:true,supplement_rounds_used:0,latest_review:{id:'r1',status:'supported',relevance:'related',claim_revision:1,evidence_ids:['e1']}} as Candidate['claims'][number]
 expect(usableClaim(candidate,claim)).toBe(false)
})
it('strips resolved claim text and evidence when reopening a saved immutable snapshot for editing',()=>{
 const view={snapshot:{title:'Synthetic',output_language:'en',paragraphs:[{id:'stable-1',fragments:[{kind:'claim',claim_id:'claim1',claim_revision:2,text:'Server only',bindings:[{review_id:'review1',metadata_version_id:'meta1',evidence:[{id:'ev1'}]}]}]}]}} as unknown as DraftView
 expect(draftInput(view).paragraphs).toEqual([{id:'stable-1',fragments:[{kind:'claim',claim_id:'claim1',claim_revision:2,bindings:[{review_id:'review1',metadata_version_id:'meta1'}]}]}])
})
it('copies server bibliography verbatim and rejects a foreign project draft',()=>{
 expect(referenceCopy({text:'Server',paragraphs:[],references:[{number:3,project_reference_id:'r1',text:'Original date and title.'}]})).toBe('3. Original date and title.')
 expect(validDraft({project_id:'other'},'p1')).toBe(false)
})

import {articleHeading} from './articleStructure'
import type {ManuscriptInput,PaperPlan,Snapshot} from './manuscriptTypes'
import type {SchoolPurpose,ThesisInput,ThesisReadiness} from './thesisTypes'

export function plannedThesisInput(plan:PaperPlan,readiness:ThesisReadiness,previous?:ThesisInput):ThesisInput|undefined{
  if(plan.kind!=='thesis'||!readiness.ready||!readiness.confirmation_id)return previous
  // Saving writing requirements can advance the profile revision without changing the confirmed chapters.
  const sameConfirmation=previous?.confirmation_id===readiness.confirmation_id
  const sectionsByChapter=new Map(plan.sections.map(section=>[section.chapter_id,section]))
  const plannedGroupIds=new Set(plan.sections.map(section=>section.id))
  return {
    confirmation_id:readiness.confirmation_id,profile_revision:readiness.profile.revision,
    chapter_mappings:readiness.chapters.map(chapter=>{
      const saved=sameConfirmation?previous?.chapter_mappings.find(mapping=>mapping.chapter_id===chapter.id):undefined
      const planned=sectionsByChapter.get(chapter.id)
      const purpose=readiness.protected_chapter_purposes?.[chapter.id]??planned?.purpose??saved?.purpose??('' as SchoolPurpose)
      return {
        chapter_id:chapter.id,purpose,output_language:saved?.output_language??'project',
        result_group_ids:purpose==='results'?[...(planned?[planned.id]:[]),...(saved?.result_group_ids??[]).filter(id=>!plannedGroupIds.has(id))]:[],
      }
    }),
  }
}

export function supplementaryInput(input:ManuscriptInput,fileIds:ReadonlySet<string>,relatedFigureIds:(id:string)=>ReadonlySet<string>):ManuscriptInput{
  const duplicates=input.sources.filter(source=>fileIds.has(source.file_id))
  if(!duplicates.length)return input
  const removedIds=new Set(duplicates.map(source=>source.id))
  const removedFigures=new Set(duplicates.flatMap(source=>[...relatedFigureIds(source.id)]))
  const groups=input.results_groups.flatMap(group=>{
    const analysis_run_ids=group.analysis_run_ids.filter(id=>!removedIds.has(id))
    const figure_ids=group.figure_ids.filter(id=>!removedFigures.has(id))
    if((group.analysis_run_ids.length||group.figure_ids.length)&&!analysis_run_ids.length&&!figure_ids.length)return []
    return [{...group,analysis_run_ids,figure_ids}]
  })
  return {
    ...input,sources:input.sources.filter(source=>!removedIds.has(source.id)),results_groups:groups,
    method_source_ids:Object.fromEntries(Object.entries(input.method_source_ids).map(([field,ids])=>[field,ids?.filter(id=>!removedIds.has(id))])),
    figure_notes:input.figure_notes.filter(note=>fileIds.has(note.figure_id)||!removedFigures.has(note.figure_id)),
    analysis_handoff_run_ids:input.analysis_handoff_run_ids?.filter(id=>!removedIds.has(id)),
  }
}

export function plannedWritingSources(snapshot:Snapshot):string[]{
  if(!snapshot.paper_plan)return []
  const linked=new Set(snapshot.paper_plan.materials.map(material=>material.selection.id))
  for(const group of snapshot.paper_plan.kind==='narrative_review'?[]:snapshot.results_groups){
    for(const item of [...group.figures,...group.tables])for(const id of item.source_ids)linked.add(id)
    for(const paragraph of group.paragraphs)if(paragraph.origin==='user_provided')for(const id of paragraph.source_ids)linked.add(id)
  }
  return [...new Set(snapshot.sources.filter(source=>linked.has(source.id)).map(source=>source.id))]
}

export function plannedSectionTitle(snapshot:Snapshot,id:string):string|undefined{
  return snapshot.journal_display_context?.names[id]??snapshot.sections?.find(section=>section.id===id)?.title??
    snapshot.paper_plan?.sections.find(section=>section.id===id)?.label??
    (snapshot.article_type?articleHeading(snapshot.article_type,id,snapshot.output_language):undefined)
}

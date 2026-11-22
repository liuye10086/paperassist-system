import type {Content, SampleRegistration, Version} from './contracts'

export function confirmedSampleRegistration(requirement?: Version | null): SampleRegistration | null {
 if(requirement?.operation!=='confirm')return null
 const value=requirement.content.sample_information as Partial<SampleRegistration> | undefined
 return value && Array.isArray(value.groups) && Array.isArray(value.samples)
  ? {groups:value.groups,samples:value.samples} : null
}

export function assignedDesignContent(draft:Content,requirement:Version|null,saved:Version|null):Content {
 const registration=confirmedSampleRegistration(requirement)??{
  groups:(saved?.content.groups??[]) as SampleRegistration['groups'],
  samples:(saved?.content.samples??[]) as SampleRegistration['samples'],
 }
 const experiments=[...(draft.experiments??[]) as Record<string,unknown>[]]
 const experimentIds=new Set(experiments.map(row=>row.id))
 for(const group of registration.groups){
  if(typeof group.experiment_id==='string'&&!experimentIds.has(group.experiment_id)){
   experiments.push({id:group.experiment_id,data_type:''})
   experimentIds.add(group.experiment_id)
  }
 }
 return {...draft,...registration,experiments}
}

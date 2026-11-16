import type {BioReportContext,BioReportRequest} from './contracts'

export const fixedSha='a'.repeat(64)
export function fixedContext(body:BioReportRequest,id='context1'):BioReportContext {
 return {id,...body,
  report:{schema_version:1,title:body.title,language:body.language,finding_version_id:'finding1',
   figure_version_ids:[],reader_narrative_id:null,root_id:null,expected_revision:0},
  source:{source_kind:'bio_report_context',source_id:id,sha256:fixedSha,selection:body.selection}}
}

export function fixedExports(project='p1',context='context1',report='formal1') {
 return {items:[{id:report,task_id:'export1',
  task:{id:'export1',project_id:project,task_type:'research_report',status:'succeeded'},
  members:['docx','xlsx','zip'].map(role=>({id:'member-'+role,key:'report',role,format:role,sha256:fixedSha,size_bytes:12,
   download_url:`/api/v1/projects/${project}/bio-reader-reports/${context}/reports/${report}/members/${role}/download`}))}],
  total:1,page:1,page_size:20,export_state:'completed'}
}

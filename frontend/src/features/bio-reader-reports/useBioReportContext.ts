import {RESEARCH_LOADING_MESSAGE,useResearchRead} from '../research-results/api'
import {bioReportsBase,reportIdentityError,validContext,type BioReportContext} from './contracts'

export function useBioReportContext(projectId:string,id:string|undefined,active:boolean,
 matches?:(context:BioReportContext)=>boolean){
 const read=useResearchRead<BioReportContext>(id?`${bioReportsBase(projectId)}/${encodeURIComponent(id)}`:'',active)
 const data=id&&validContext(read.data,id)&&(!matches||matches(read.data))?read.data:null
 const error=id?(read.error||(read.data&&!data?reportIdentityError:'')):''
 return {data,error,valid:read.valid,loading:!!id&&!data&&!error&&read.valid,
  loadingMessage:RESEARCH_LOADING_MESSAGE,refresh:read.refresh}
}

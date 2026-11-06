import {jsonRequest} from '../bioinformatics/api'
import type {CloudClient,CloudRun} from './cloud'
// Reconciles a known provider receipt; never creates another paid cloud run.
export function reconcileRun(client:CloudClient,runId:string,providerRunId:string,signal:AbortSignal){
 if(!providerRunId.trim())throw Error('请先核对云运行 ID。')
 return client.request<CloudRun>(`/runs/${encodeURIComponent(runId)}/reconcile`,{...jsonRequest({provider_run_id:providerRunId.trim()}),signal})
}

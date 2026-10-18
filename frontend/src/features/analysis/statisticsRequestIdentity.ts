import {onApiSessionChanged} from '../../shared/api/client'

const prefix='paperassist.statistics.request:'
// Only opaque request keys are kept; no data, results or credentials are stored.
onApiSessionChanged(()=>{
 try{for(const key of Object.keys(sessionStorage))if(key.startsWith(prefix))sessionStorage.removeItem(key)}catch{/* Storage may be disabled. */}
})
export function pendingStatisticsKey(context:string):string|null{
 try{const value=sessionStorage.getItem(prefix+context);return value&&/^[a-zA-Z0-9-]{1,64}$/.test(value)?value:null}catch{return null}
}
export function saveStatisticsKey(context:string,key:string|null){
 try{if(key===null)sessionStorage.removeItem(prefix+context);else sessionStorage.setItem(prefix+context,key)}catch{/* In-memory retries still retain the exact key. */}
}

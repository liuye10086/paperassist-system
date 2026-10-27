import {operationsRequest} from './operationsApi'
import {isCatalog,isVersion,object,type ConfigCatalog,type ConfigurationCurrent,type ConfigurationVersion} from './configurationTypes'
export const configurationBase='/api/v1/admin/configurations'
export async function configurationRequest<T>(path:string,signal:AbortSignal,body?:unknown):Promise<T>{
 const value=await operationsRequest<unknown>(configurationBase+path,signal,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
 if(path==='/catalog'&&!isCatalog(value)||path==='/current'&&(!object(value)||!Number.isSafeInteger(value.revision)||(value.revision as number)<0||!(value.version===null||isVersion(value.version))))throw new Error('配置响应无效，请重新读取。')
 if((path.endsWith('/save')||path.endsWith('/copy')||path==='/baseline')&&!isVersion(value))throw new Error('配置响应无效，请重新读取。')
 return value as T
}
export async function readConfigurationHeader(signal:AbortSignal){const[current,catalog]=await Promise.all([configurationRequest<ConfigurationCurrent>('/current',signal),configurationRequest<ConfigCatalog>('/catalog',signal)]);return{current,catalog}}
export async function readConfigurationVersion(id:string,signal:AbortSignal){const value=await configurationRequest<ConfigurationVersion>('/'+encodeURIComponent(id),signal);if(!isVersion(value))throw new Error('配置响应无效，请重新读取。');return value}

import {intakeRequest,jsonRequest,projectBase,IntakeError} from '../research-intake/api'
import {STANDARD_REQUEST_TIMEOUT_MS,RESEARCH_REQUEST_TIMEOUT_MS} from '../../shared/api/requestTimeouts'
export {jsonRequest,projectBase,IntakeError}
export const insightBase=(project:string)=>`${projectBase(project)}/bio-insights`
export function insightRequest<T>(url:string,init?:RequestInit,fullSource=false){return intakeRequest<T>(url,init,fullSource?RESEARCH_REQUEST_TIMEOUT_MS:STANDARD_REQUEST_TIMEOUT_MS)}

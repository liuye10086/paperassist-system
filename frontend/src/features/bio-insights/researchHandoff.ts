import {getApiUserId,onApiSessionChanged} from '../../shared/api/client'
import type {Source} from '../research-results/contracts'
const prefix='paperassist.research-handoff.v1:'
onApiSessionChanged(()=>{try{for(const k of Object.keys(sessionStorage))if(k.startsWith(prefix))sessionStorage.removeItem(k)}catch{}})
const key=(project:string)=>`${prefix}${getApiUserId()??'anonymous'}:${project}`
export type ResearchHandoff={id:string;source:Source}
export function queueResearchSource(project:string,source:Source){const value={id:crypto.randomUUID(),source};sessionStorage.setItem(key(project),JSON.stringify(value));return value}
export function takeResearchSource(project:string):ResearchHandoff|null{try{const raw=sessionStorage.getItem(key(project));if(!raw)return null;const value=JSON.parse(raw) as ResearchHandoff;if(value.id&&['bio_insight_result_version','bio_insight_result_member','analysis_run'].includes(value.source.source_kind)&&value.source.source_id&&value.source.locator){sessionStorage.removeItem(key(project));return value}}catch{}return null}

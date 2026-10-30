import {useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {projectBase} from './api'
import type {RawBioSource,SpatialMember} from './spatialContracts'
import {useBioImage} from './spatialHooks'
export function BioSource({source}:{source:RawBioSource}){const {t}=useI18n();return <dl className="bio-source"><dt>{t('固定原始版本')}</dt><dd>{source.dataset_version_id} · v{source.version}</dd><dt>SHA-256</dt><dd><code>{source.manifest_sha256}</code></dd><dt>{t('解析器版本')}</dt><dd>{source.parser_version}</dd></dl>}
export function BioWriteStatus({writer}:{writer:{error:string;unknown:boolean;busy:boolean;lookup:()=>Promise<void>}}){const {t}=useI18n();return <>{writer.error&&<p role="alert" className="error-panel">{t(writer.error)}</p>}{writer.busy&&<p role="status">{t('正在保存或核对原请求……')}</p>}{writer.unknown&&<button type="button" disabled={writer.busy} onClick={()=>void writer.lookup()}>{t('按原请求身份核对')}</button>}</>}
export function BioSpatialMembers({projectId,members}:{projectId:string;members:SpatialMember[]}){const {t}=useI18n();return <ul className="bio-member-list">{members.map(m=>m.download_url?.startsWith(projectBase(projectId)+'/')&&<li key={m.id}><ProjectDownloadLink href={m.download_url} filename={m.filename??`${m.key}.${m.format}`}>{m.filename??m.key} · {m.format}</ProjectDownloadLink><small>{m.size_bytes} bytes · SHA-256 {m.sha256}</small></li>)}{!members.length&&<li>{t('暂无已发布成员')}</li>}</ul>}
export function BioJson({value}:{value:unknown}){return <pre className="bio-json">{JSON.stringify(value,null,2)}</pre>}
export function BioMemberImage({projectId,member}:{projectId:string;member:SpatialMember}){const url=member.download_url?.startsWith(projectBase(projectId)+'/')&&member.format==='png'?member.download_url:'';const image=useBioImage(url);return image?<img className="bio-coordinate-preview" src={image} alt={member.key}/>:null}

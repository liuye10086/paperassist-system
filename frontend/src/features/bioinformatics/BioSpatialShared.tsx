import ReadableDetails from '../../shared/components/ReadableDetails'
import {useI18n} from '../../shared/i18n'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import {projectBase} from './api'
import type {RawBioSource,SpatialMember} from './spatialContracts'
import {useBioImage} from './spatialHooks'
import {figureName,isTechnicalResultFile,resultFileName} from './bioPresentation'
export function BioSource({source}:{source:RawBioSource}){
 const {t}=useI18n()
 const analysis=source.parser_version.startsWith('single_cell')?'单细胞表达数据':source.parser_version.startsWith('tabular_assay')?'样本定量数据':'空间表达数据'
 return <dl className="bio-source"><dt>{t('分析输入')}</dt><dd>{t(analysis)} · {t('{count} 个来源文件',{count:source.source_file_ids.length})}</dd></dl>
}
export function BioWriteStatus({writer}:{writer:{error:string;unknown:boolean;busy:boolean;lookup:()=>Promise<void>}}){const {t}=useI18n();return <>{writer.error&&<p role="alert" className="error-panel">{t(writer.error)}</p>}{writer.busy&&<p role="status">{t('正在保存或核对原请求……')}</p>}{writer.unknown&&<button type="button" disabled={writer.busy} onClick={()=>void writer.lookup()}>{t('按原请求身份核对')}</button>}</>}
export function BioSpatialMembers({projectId,members}:{projectId:string;members:SpatialMember[]}){
 const {t}=useI18n()
 const files=members.filter(m=>!isTechnicalResultFile(m.key,m.format)&&m.format.toLowerCase()!=='pdf'&&
  (!members.some(member=>member.format.toLowerCase()==='pdf')||m.format.toLowerCase()!=='zip')&&m.download_url?.startsWith(projectBase(projectId)+'/'))
 return <ul className="bio-member-list">{files.map(m=>{
  const name=resultFileName(m,t)
  return <li key={m.id}><ProjectDownloadLink href={m.download_url} filename={name}>{name}</ProjectDownloadLink></li>
 })}{!files.length&&<li>{t('暂无已发布成员')}</li>}</ul>
}
export function BioJson({value}:{value:unknown}){return <ReadableDetails value={value} readerView/>}
export function BioMemberImage({projectId,member,label}:{projectId:string;member:SpatialMember;label?:string}){const {t}=useI18n(),url=member.download_url?.startsWith(projectBase(projectId)+'/')&&member.format==='png'?member.download_url:'';const image=useBioImage(url);return image?<img className="bio-coordinate-preview" src={image} alt={label??figureName(member.key,t)}/>:null}

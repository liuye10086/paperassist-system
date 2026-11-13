const equivalenceLabels:Record<string,string>={identical:'全矩阵数值和轴顺序一致',order_reindexed_equal:'重排轴后全矩阵数值一致',mismatch:'矩阵不一致，不能确认等价',not_comparable:'条件不足，尚未完成等价核对'}
import {checkLabels,roleLabels} from './contracts'
import {useI18n} from '../../shared/i18n'
import type {BioCheck,BioMember} from './contracts'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
const spatialChecks = ['positions_count','in_tissue_count','matrix_matches_in_tissue','matrix_barcodes_in_positions']
const checkNotes:Record<string,string> = {
 duplicate_feature_symbols_preserved: '重复基因符号已保留',
 matrix_barcodes_differ_from_in_tissue: '矩阵条码与组织内条码范围不同',
}

function describeCheck(check:BioCheck,singleCell:boolean,t:ReturnType<typeof useI18n>['t'],locale:string){
 const code=check.code??'', value=check.value
 const spatialOnly=singleCell&&spatialChecks.includes(code)
 let label='待核对', tone='neutral'
 if(spatialOnly||singleCell&&(check.status==='not_applicable'||value==='not_applicable'))label='不适用'
 else if(code==='representation_equivalence'&&value&&typeof value==='object'&&'status' in value){
  const state=String(value.status)
  label=equivalenceLabels[state]??label
  tone=state==='mismatch'?'error':['identical','order_reindexed_equal'].includes(state)?'success':'warning'
 } else if(check.status==='passed'){label='已通过';tone='success'}
 else if(check.status==='internal_not_checked'||value==='internal_not_checked'){label='H5 内部未核对';tone='warning'}
 else if(['failed','error','blocked'].includes(check.status??'')){label='未通过';tone='error'}
 else if(check.status==='warning'){label='需留意';tone='warning'}
 else if(check.status==='not_requested')label='未请求'

 let detail=''
 if(value&&typeof value==='object'&&!Array.isArray(value)){
  const fields=value as Record<string,unknown>
  if(code==='source_accessions')detail=Object.values(fields).filter(v=>typeof v==='string').join(' · ')
  if(code==='sample_mapping'&&typeof fields.sample_count==='number')detail=t('{count} 个已对应样本',{count:fields.sample_count})
 } else if(typeof value==='number'&&!spatialOnly)detail=value.toLocaleString(locale)
 else if(Array.isArray(value))detail=value.map(item=>code==='quality_reports'&&item&&typeof item==='object'
  ?[item.source,item.report_type].filter(Boolean).join(' ')
  :t(checkNotes[String(item)]??String(item))).join(' · ')
 return {name:t(check.name??checkLabels[code]??'结构核对'),status:t(label),tone,detail}
}

export function BioChecks({checks,singleCell=false,layout='list'}:{checks:BioCheck[];singleCell?:boolean;layout?:'list'|'table'}){
 const {t,locale}=useI18n()
 if(!checks.length)return null
 const rows=checks.map(check=>describeCheck(check,singleCell,t,locale))
 if(layout==='table')return <div className="bio-table-scroll bio-check-table"><table aria-label={t('核对结果')}>
  <thead><tr>{['核对项目','核对状态','说明'].map(label=><th key={label} scope="col">{t(label)}</th>)}</tr></thead>
  <tbody>{rows.map(({name,status,tone,detail},index)=><tr key={index}><th scope="row">{name}</th>
   <td><span className="status-badge" data-tone={tone}>{status}</span></td><td>{detail||'—'}</td></tr>)}</tbody>
 </table></div>
 return <ul className="bio-checks">{rows.map(({name,status,detail},index)=><li key={index}>{name} · {status}{detail&&<> · {detail}</>}</li>)}</ul>
}
export function BioMembers({members,projectId}:{members:BioMember[];projectId:string}){const {t}=useI18n();return <div className="bio-table-scroll"><table><thead><tr>{['成员文件','用途','核对状态','操作'].map(label=><th key={label}>{t(label)}</th>)}</tr></thead><tbody>{members.map((member,index)=><tr key={member.id??index}><td>{member.filename}</td><td>{t(roleLabels[member.role]??'配套成员')}</td><td>{t(member.verification_state==='internal_not_checked'?'H5 内部未核对':member.verification_state==='verified'?'已核对':member.verification_state==='not_checked'?'未核对':member.verification_state)}</td><td>{member.download_url?.startsWith(`/api/v1/projects/${encodeURIComponent(projectId)}/`)?<ProjectDownloadLink href={member.download_url} filename={member.filename}>{t('下载')}</ProjectDownloadLink>:t('发布后可下载')}</td></tr>)}</tbody></table></div>}
export function BioCounts({summary}:{summary:Record<string,unknown>}){const {t}=useI18n();const shape=(summary.shape??summary) as Record<string,unknown>;return <dl className="bio-counts">{[['features','特征数'],['observations','观测数'],['stored_entries','存储矩阵项数']].map(([key,label])=><div key={key}><dt>{t(label)}</dt><dd>{typeof shape[key]==='number'?shape[key].toLocaleString():t('待核对')}</dd></div>)}</dl>}

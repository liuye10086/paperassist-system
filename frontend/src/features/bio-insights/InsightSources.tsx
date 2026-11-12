import {useState} from 'react'
import {useI18n} from '../../shared/i18n'
import {sourceLabels,type Source,type SourceKind,type SourceItem,type Page} from './contracts'
import {insightBase} from './api'
import {useInsightRead} from './hooks'
import {Field,Paging,ReadState} from './InsightShared'
const roles={external_evidence:'类型化外部证据',support_design:'独立验证设计原件',overlap_audit:'供体重叠核查原件',sample_mapping:'样本对应资源',object_mapping:'对象对应资源',feature_input:'实际提取输入（FASTA／结构）',processed:'处理数据',observation_map:'观测对应表',annotation:'区域／细胞人工注释',design:'研究设计',result:'分析结果',gene_sets:'基因集合',id_mapping:'ID 映射',feature_annotation:'序列／结构注释',source:'外部表文件',background:'显式背景'}
const resourceRoles = {gene_sets:'基因集合',id_mapping:'ID 映射'}

export default function InsightSources({projectId,value,onChange,active=true,bulkResources=false,processedAssay}:{
 projectId:string;value:Source[];onChange:(s:Source[])=>void;active?:boolean;bulkResources?:boolean;processedAssay?:string
}) {
 const {t} = useI18n()
 const [kind,setKind] = useState<SourceKind>(bulkResources?'bio_resource_version':'bio_processed_dataset_version')
 const [role,setRole] = useState(bulkResources?'gene_sets':'processed')
 const [page,setPage] = useState(1)
 const [id,setId] = useState('')
 const list = useInsightRead<Page<SourceItem>>(`${insightBase(projectId)}/sources?source_kind=${kind}&page=${page}&page_size=20`,active)
 const items = list.data?.items??[]
 const eligible = bulkResources?items.filter(item=>item.kind===role&&!!item.sha256):
  processedAssay&&kind==='bio_processed_dataset_version'?items.filter(item=>item.assay===processedAssay):items
 const picked = eligible.find(item=>item.source_id===id)
 const title = (item:SourceItem) => bulkResources
  ?[item.title,item.release,item.version===undefined?undefined:`v${item.version}`].filter(Boolean).join(' · ')
  :item.title
 function changeKind(next:SourceKind) {
  setKind(next);setPage(1);setId('')
  setRole(({external_evidence_version:'external_evidence',bio_processed_dataset_version:'processed',bio_observation_map_version:'observation_map',bio_annotation_version:'annotation',research_design_version:'design',bio_resource_version:'gene_sets',bio_insight_result_version:'result',original_file:'source'})[next])
 }
 function add() {
  if (!picked?.sha256||value.some(s=>s.source_id===id&&s.source_kind===kind&&(bulkResources||s.role===role))) return
  onChange([...value,{source_kind:kind,source_id:id,sha256:picked.sha256,role,
   locator:{kind:'object',...(picked.parse_version_id?{parse_version_id:picked.parse_version_id}:{})},
   title:title(picked),assay:picked.assay,...(bulkResources&&picked.species_taxon_id!=null?{species_taxon_id:picked.species_taxon_id}:{})}])
 }
 return <section>
  <h3>{t(bulkResources?'选择本地固定富集资源':'固定输入版本与角色')}</h3>
  <div className="insight-grid">
   {!bulkResources&&<Field label="来源类型" value={kind} onChange={v=>changeKind(v as SourceKind)}>
    {Object.entries(sourceLabels).map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}
   </Field>}
   <Field label="来源使用角色" value={role} onChange={next=>{setRole(next);if(bulkResources){setId('');setPage(1)}}}>
    {Object.entries(bulkResources?resourceRoles:roles).map(([key,label])=><option key={key} value={key}>{t(label)}</option>)}
   </Field>
   <Field label="选择固定来源版本" value={id} onChange={setId}>
    <option value="">{t('请选择')}</option>
    {eligible.map(item=><option value={item.source_id} key={item.source_id} disabled={!item.sha256}>{title(item)}</option>)}
   </Field>
  </div>
  <ReadState {...list}/>
  {list.data&&<Paging page={page} size={20} total={list.data.total} onPage={next=>{setPage(next);if(bulkResources)setId('')}}/>}
  {bulkResources&&list.data&&!eligible.length&&<p>{t('当前页没有已发布的此类资源，可在资源管理中导入。')}</p>}
  <div className="intake-actions">
   <button type="button" disabled={bulkResources?!picked:!id} onClick={add}>{t('加入固定来源')}</button>
   {bulkResources&&<button type="button" disabled={list.loading} onClick={list.refresh}>{t('刷新固定资源')}</button>}
  </div>
  <ul>{value.map((s,i)=>{
   const item = items.find(row=>row.source_id===s.source_id)
   return <li key={`${s.source_kind}:${s.source_id}:${s.role}`}>
    <strong>{t(sourceLabels[s.source_kind])} · {t(roles[s.role as keyof typeof roles]??s.role)}</strong> {s.title??(bulkResources?(item?title(item):s.source_id):t('已选固定来源'))} <button type="button" onClick={()=>onChange(value.filter((_,j)=>i!==j))}>{t('移除')}</button>
   </li>
  })}</ul>
 </section>
}

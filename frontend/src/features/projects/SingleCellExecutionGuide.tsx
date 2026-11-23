import {useI18n} from '../../shared/i18n'
import type {ProjectFile} from '../files/fileLibraryApi'
import {singleCellMtxFiles} from '../bioinformatics/singleCellMtxFiles'
import type {AnalysisScope, EntryImport, rnaRequestGroups} from './analysisEntryState'
import type {AnalysisNavigation} from './analysisViews'

type Group = ReturnType<typeof rnaRequestGroups>[number]
type Props = {group:Group; files:ProjectFile[]; imports:EntryImport[]; checking:boolean; open:(scope:AnalysisScope, next:AnalysisNavigation)=>void}

export default function SingleCellExecutionGuide({group,files,imports,checking,open}:Props) {
  const {t}=useI18n()
  const matrix=singleCellMtxFiles(files)
  const previous=imports.filter(item=>item.parser==='single_cell_import_v1' && matrix.length===3 &&
    item.fileIds.length===3 && matrix.every(file=>item.fileIds.includes(file.id)))
  const candidates=previous.filter(item=>item.status==='succeeded'&&item.versionId || ['waiting_confirmation','running','queued'].includes(item.status))
  const reusable=candidates.length===1?candidates[0]:undefined
  const resume=reusable?.versionId
    ? {view:'bio-dataset' as const,datasetId:reusable.datasetId,versionId:reusable.versionId}
    : reusable ? {view:'bio-import' as const,importId:reusable.id} : null
  const methods=group.choices.filter(choice=>choice.scope.id.startsWith('customer.analysis.'))
  return <article className="single-cell-execution" aria-label={t(group.title)}>
    <h3>{t('单细胞分析流程')}</h3>
    <ol>
      <li><div><h4>{t('导入计数矩阵')}</h4>
        <p>{matrix.length?matrix.map(f=>f.filename).join(' + '):t('选择已上传的单细胞原始计数文件，核对细胞数和基因数后发布数据集。')}</p></div></li>
      <li><div><h4>{t('关联细胞分组表')}</h4>
        <p>{t('用条码把细胞对应到样本、供者和分组。只做初步聚类时可跳过。')}</p></div></li>
      <li><div><h4>{t('运行质控与聚类')}</h4>
        <p>{t('首次体验可沿用标准参数。核对质控结果后继续计算，完成后查看 UMAP、Marker 热图和 Word 报告。')}</p></div></li>
    </ol>
    <div className="single-cell-actions"><button type="button" className="button-primary" disabled={checking} onClick={()=>open(group.parent,
      {...group.primary[0].navigation,...resume})}>{t(!resume?'导入并核对单细胞矩阵':resume.view==='bio-import'?'继续核对本次导入':'继续使用已发布矩阵')}</button>
      <button type="button" className="button-quiet" onClick={()=>open(group.parent,group.primary[1].navigation)}>{t('查看单细胞处理结果')}</button></div>
    {methods.length>0&&<div className="single-cell-followup"><h4>{t('完成聚类后')}</h4>
      {methods.map(choice=><button key={choice.scope.id} type="button" onClick={()=>open(choice.scope,choice.navigation)}>{t(choice.label)}</button>)}</div>}
  </article>
}

import { useI18n } from '../../shared/i18n'
import { artifactFilename } from '../../shared/components/artifactFilename'
import ProjectDownloadLink from '../../shared/components/ProjectDownloadLink'
import type { ArtifactNavigation } from './analysisViews'
import type { ProjectSummaryData, SummaryArtifact } from './projectSummaryTypes'

type Props = { projectId:string; data:ProjectSummaryData; navigation:ArtifactNavigation; onNavigate:(next:ArtifactNavigation)=>void }
export default function ArtifactLibrary({projectId,data,navigation,onNavigate}:Props) {
  const {t,locale}=useI18n()
  const filename=(item:SummaryArtifact)=>item.collection_id?t('集合报告-v{version}-导出{export}.docx',{version:item.collection_revision!,export:item.export_revision!}):artifactFilename(item.download_filename,item.kind,item.id,item.setup_revision,locale)
  const selected=data.artifacts.items.find(item=>item.id===navigation.artifactId&&item.kind===navigation.kind)
  const pages=Math.max(1,Math.ceil(data.artifacts.total/10))
  const list=()=>onNavigate({...navigation,view:'list',artifactId:'',kind:''})
  return <div className="artifact-library">
    <nav className="artifact-view-nav" aria-label={t('成果视图')}>
      <button type="button" aria-current={navigation.view==='list'?'page':undefined} onClick={list}>{t('成果列表')}</button>
      <button type="button" aria-current={navigation.view==='layout'?'page':undefined} onClick={()=>onNavigate({...navigation,view:'layout',artifactId:'',kind:''})}>{t('排版导出记录')}</button>
      {navigation.view==='detail'&&<span aria-current="page">{t('成果详情')}</span>}
    </nav>
    {navigation.view==='list'&&<>
      <div className="artifact-list-heading"><div><h4>{t('已生成文件')}</h4><p>{t('先选择成果，再查看对应来源、固定版本与下载。')}</p></div><span>{t('共 {total} 项',{total:data.artifacts.total})}</span></div>
      {data.artifacts.total===0?<p className="summary-empty">{t('还没有已生成的 PNG 或 Word 文件。')}</p>:<ul className="summary-artifact-list">{data.artifacts.items.map(item=><li key={`${item.kind}:${item.id}`}>
        <span className={`summary-artifact-symbol summary-artifact-${item.kind}`} aria-hidden="true">{item.kind==='figure'?'PNG':'DOCX'}</span>
        <div className="summary-artifact-content"><strong>{filename(item)}</strong><p>{item.collection_title??item.filename}</p>{item.collection_id&&<p className="summary-artifact-meta">{t('集合版本 {version} · 导出版本 {export} · {count} 个分析结果',{version:item.collection_revision!,export:item.export_revision!,count:item.result_count!})}</p>}<p className="summary-artifact-meta">{new Date(item.recorded_at).toLocaleString(locale)} · {item.size_bytes.toLocaleString(locale)} {t('字节')}</p></div>
        <button type="button" aria-label={t('查看成果 {name}',{name:filename(item)})} onClick={()=>onNavigate({view:'detail',artifactId:item.id,kind:item.kind,page:data.artifacts.page})}>{t('查看详情')}</button><ProjectDownloadLink href={item.download_url} filename={filename(item)} ariaLabel={t('下载成果 {name}',{name:filename(item)})}>{t('下载文件')}</ProjectDownloadLink>
      </li>)}</ul>}
      <nav className="summary-pagination" aria-label={t('成果分页')}><span>{t('共 {total} 项 · 第 {page} / {pages} 页',{total:data.artifacts.total,page:data.artifacts.page,pages})}</span>
        <button type="button" aria-label={t('成果上一页')} disabled={data.artifacts.page<=1} onClick={()=>onNavigate({...navigation,page:data.artifacts.page-1})}>{t('上一页')}</button>
        <button type="button" aria-label={t('成果下一页')} disabled={data.artifacts.page>=pages} onClick={()=>onNavigate({...navigation,page:data.artifacts.page+1})}>{t('下一页')}</button></nav>
    </>}
    {navigation.view==='detail'&&(selected?<section className="artifact-detail" aria-label={t('成果详情')}>
      <div className="artifact-detail-heading"><div><span className="workspace-eyebrow">{t(selected.kind==='figure'?'PNG 图表':'Word 分析报告')}</span><h4>{filename(selected)}</h4><p>{selected.collection_title??selected.filename}</p></div>
        <ProjectDownloadLink href={selected.download_url} filename={filename(selected)} ariaLabel={t('下载成果 {name}',{name:filename(selected)})}>{t('下载文件')}</ProjectDownloadLink></div>
      <dl className="artifact-detail-grid"><div><dt>{t('来源文件')}</dt><dd>{selected.filename}</dd></div>
        <div><dt>{t('记录时间')}</dt><dd>{new Date(selected.recorded_at).toLocaleString(locale)}</dd></div>
        <div><dt>{t('成果类型')}</dt><dd>{t(selected.collection_id?'同源多结果集合':selected.kind==='figure'?'PNG 图表':'Word 分析报告')}</dd></div>
        <div><dt>{t('版本状态')}</dt><dd>{t(selected.collection_id?'冻结集合版本':selected.current_revision===null?'当前设置未记录':selected.setup_revision===selected.current_revision?'当前结果':'历史结果')}</dd></div>
        {selected.setup_revision!==null&&<div><dt>{t('字段配置版本')}</dt><dd>{selected.setup_revision}</dd></div>}
        {selected.collection_revision!=null&&<div><dt>{t('集合版本')}</dt><dd>{selected.collection_revision} · {t('导出版本')} {selected.export_revision}</dd></div>}
        <div><dt>{t('文件大小')}</dt><dd>{selected.size_bytes.toLocaleString(locale)} {t('字节')}</dd></div>
        <div><dt>{t('分析引擎')}</dt><dd>{selected.engine_version}</dd></div></dl>
      <details className="artifact-source-identifiers"><summary>{t('查看固定来源与校验标识')}</summary><dl>
        <dt>{t('成果标识')}</dt><dd>{selected.id}</dd>
        {selected.analysis_run_id&&<><dt>{t('分析运行标识')}</dt><dd>{selected.analysis_run_id}</dd></>}
        {selected.figure_config_version_id&&<><dt>{t('图表配置版本')}</dt><dd>{selected.figure_config_version_id}</dd></>}
        {selected.collection_version_id&&<><dt>{t('集合版本标识')}</dt><dd>{selected.collection_version_id}</dd></>}
        <dt>SHA-256</dt><dd>{selected.sha256}</dd></dl></details>
    </section>:<div role="alert" className="error-panel"><p>{t('该成果不在当前记录页中，请返回列表重新选择；不会替换为其他版本。')}</p><button type="button" onClick={list}>{t('返回成果列表')}</button></div>)}
    {navigation.view==='layout'&&<section aria-label={t('近期排版导出')}><h4>{t('近期排版导出')}</h4><p className="muted">{t('仅显示最近 20 条排版记录；完整历史请打开原稿的排版与公式。')}</p>
      {!data.layout_exports?.length?<p className="summary-empty">{t('尚无排版导出记录。')}</p>:<ul className="summary-artifact-list">{data.layout_exports.map(item=><li key={item.id}><div className="summary-artifact-content"><strong>{item.filename??t('排版 DOCX 导出')}</strong><p>{t({queued:'待执行',running:'运行中',succeeded:'已完成',failed:'执行失败'}[item.status])} · {new Date(item.created_at).toLocaleString(locale)}</p>
        <a href={`#project=${encodeURIComponent(projectId)}&section=tasks&task=${encodeURIComponent(item.task_id)}`}>{t('查看排版任务')}</a></div>{item.status==='succeeded'&&item.download_url&&<ProjectDownloadLink href={item.download_url} filename={item.filename??'layout.docx'}>{t('下载排版 DOCX')}</ProjectDownloadLink>}</li>)}</ul>}
    </section>}
  </div>
}

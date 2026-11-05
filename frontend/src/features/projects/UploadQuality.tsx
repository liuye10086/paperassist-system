import { useI18n } from '../../shared/i18n'
import { parseStatusLabels, type ProjectFile } from '../files/fileLibraryApi'
import type { ResourceNavigation } from './resourceViews'

export default function UploadQuality({ files, loading, error, onReload, onNavigate }: {
  files: ProjectFile[]; loading: boolean; error: string; onReload: () => void
  onNavigate: (next: ResourceNavigation) => void
}) {
  const { t } = useI18n()
  const tables = files.filter(file => file.file_type === 'xlsx')
  const bioFiles = files.filter(file => ['bio_bundle','bio_component'].includes(file.file_type))
  return <section className="upload-quality" aria-label={t('质量控制')}>
    <header className="upload-quality-heading"><div><h2>{t('质量控制')}</h2>
      <p>{t('选择已上传材料，检查数据并查看已有结果，再进入第 3 步选择分析需求。')}</p></div>
      <button type="button" disabled={loading} onClick={onReload}>{t('重新读取材料')}</button></header>
    {loading ? <p role="status">{t('正在核对材料状态……')}</p> : error ? <p role="alert">{t(error)}</p> : <>
      {bioFiles.length > 0 && <article className="upload-quality-card"><div><h3>{t('组学与生信数据')}</h3>
        <p>{t('核对导入数据、确认质控设置，或查看已有质控结果。')}</p></div>
        <button type="button" onClick={() => onNavigate({view:'quality',fileId:'',bio:{view:'bio-datasets',fileId:''}})}>{t('进入生信质量控制')}</button></article>}
      {tables.map(file => <article className="upload-quality-card" key={file.id}><div><h3>{file.filename}</h3>
        <p>{t(parseStatusLabels[file.parse_status])} · {t('结构核对、数据整理与质量处理')}</p></div>
        <button type="button" disabled={file.parse_status !== 'parsed'} onClick={() => onNavigate({view:'quality',fileId:file.id})}
          aria-label={t('检查表格 {name}',{name:file.filename})}>{t(file.parse_status === 'parsed' ? '检查表格数据' : '等待解析完成')}</button></article>)}
      {!tables.length && !bioFiles.length && <div className="upload-quality-empty"><p>{t(files.length ? '当前材料没有可进行数据质控的表格或组学数据。报告和图片可在文件详情核对解析内容。' : '先上传表格或组学数据，再进行质量控制。')}</p>
        <button type="button" onClick={() => onNavigate({view:files.length?'list':'upload',fileId:''})}>{t(files.length?'已上传文件':'上传文件')}</button></div>}
    </>}
  </section>
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { onApiSessionChanged } from '../../shared/api/client'
import { useI18n } from '../../shared/i18n'
import BatchUpload from '../files/BatchUpload'
import ExcelPreview from '../files/ExcelPreview'
import type { SavedPreviewState } from '../files/ExcelPreview'
import ProjectFileLibrary from '../files/ProjectFileLibrary'
import { fileRequest } from '../files/fileLibraryApi'
import type { ProjectFile } from '../files/fileLibraryApi'
import AnalysisSetup from '../analysis/AnalysisSetup'
import type { ProjectSection } from './WorkspaceShell'

type Props = { projectId: string; onSaved: () => void; section: ProjectSection; onSectionChange: (section: ProjectSection) => void; active?: boolean }

function ResourceScope({ projectId, onSaved, section, onSectionChange, active = true }: Props) {
  const { t } = useI18n()
  const [unavailable, setUnavailable] = useState(false)
  const denied = useCallback(() => setUnavailable(true), [])
  useEffect(() => onApiSessionChanged(denied), [denied])
  if (unavailable) return <p role="alert" className="error-panel">{t('项目不存在或无权访问。')}</p>
  return <ResourceContent projectId={projectId} onSaved={onSaved} section={section} onSectionChange={onSectionChange} active={active} onUnavailable={denied} />
}

function ResourceContent({ projectId, onSaved, section, onSectionChange, onUnavailable, active }: Props & { onUnavailable: () => void }) {
  const [files, setFiles] = useState<ProjectFile[]>([])
  const [attempt, setAttempt] = useState(0)
  const [uploadVersion, setUploadVersion] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [opened, setOpened] = useState<{ id: string; request: number } | null>(null)
  const [previewState, setPreviewState] = useState<SavedPreviewState | null>(null)
  const openSequence = useRef(0)

  function refresh() { setLoading(true); setError(''); setAttempt(value => value + 1) }
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const timeout = window.setTimeout(() => controller.abort(), 15_000)
    void fileRequest<ProjectFile[]>(`/api/v1/projects/${projectId}/files`, controller.signal, onUnavailable)
      .then(result => {
        if (!Array.isArray(result)) throw new Error('format')
        if (active && !controller.signal.aborted) setFiles(result)
      })
      .catch(() => { if (active) setError('文件列表读取失败，请确认后端服务正常后重试。') })
      .finally(() => { window.clearTimeout(timeout); if (active) setLoading(false) })
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [projectId, attempt, onUnavailable])

  function batchChanged() { setUploadVersion(value => value + 1); refresh(); onSaved() }
  function uploaded() {
    setOpened(null); setPreviewState(null); setUploadVersion(value => value + 1)
    refresh(); onSaved()
  }
  return <>
    <div hidden={section !== 'files'} className="project-files-page">
      <BatchUpload projectId={projectId} active={Boolean(active) && section === 'files'} onUnavailable={onUnavailable} onChanged={batchChanged} />
      <ProjectFileLibrary projectId={projectId} active={Boolean(active) && section === 'files'} uploadVersion={uploadVersion} busy={busy}
        previewState={previewState} onUnavailable={onUnavailable} onPreview={id => {
          setPreviewState({ id, status: 'loading' }); setOpened({ id, request: ++openSequence.current })
        }} />
      <ExcelPreview projectId={projectId} savedFile={opened} onSaved={uploaded} onBusyChange={setBusy} onSavedPreviewChange={setPreviewState} />
    </div>
    <div hidden={section !== 'analysis'} className="project-analysis-page">
      <AnalysisSetup projectId={projectId} files={files} filesLoading={loading} filesError={error} onReloadFiles={refresh}
        onOpenFiles={() => onSectionChange('files')} />
    </div>
  </>
}

export default function ProjectResources(props: Props) { return <ResourceScope key={props.projectId} {...props} /> }

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { apiFetch } from '../../shared/api/client'
import { watchProjectAccess } from '../../shared/api/projectAccess'
import { isProject, type Project } from './projectTypes'
import { apiError, safeError } from '../../shared/i18n'
import type { ProjectSection } from './WorkspaceShell'
import { isTaskId } from '../tasks/taskTypes'

type Instance = { id: string; key: number }
type Request = { controller: AbortController; timeout: number }

export default function useProjectSelection(onUnavailable: (id: string) => void, onAvailable: (id: string) => void) {
  const [section, setSection] = useState<ProjectSection>(() => new URLSearchParams(window.location.hash.slice(1)).get('section') === 'reviews' ? 'reviews' : new URLSearchParams(window.location.hash.slice(1)).get('section') === 'tasks' ? 'tasks' : new URLSearchParams(window.location.hash.slice(1)).get('section')==='literature'?'literature':new URLSearchParams(window.location.hash.slice(1)).get('section')==='manuscripts'?'manuscripts':new URLSearchParams(window.location.hash.slice(1)).get('section')==='school-templates'?'school-templates':new URLSearchParams(window.location.hash.slice(1)).get('section')==='journals'?'journals':'overview')
  const [taskId, setTaskId] = useState(() => {
    const params = new URLSearchParams(window.location.hash.slice(1))
    const id = params.get('task') ?? ''
    return params.has('project') && params.get('section') === 'tasks' && isTaskId(id) ? id : ''
  })
  const [literatureSearchId,setLiteratureSearchId]=useState(()=>{const params=new URLSearchParams(window.location.hash.slice(1));const id=params.get('search')??'';return params.get('section')==='literature'&&/^[A-Za-z0-9_-]{1,64}$/.test(id)?id:''})
  const [adaptationId,setAdaptationId]=useState(()=>{const p=new URLSearchParams(window.location.hash.slice(1)),id=p.get('adaptation')??'';return p.get('section')==='journals'&&/^[A-Za-z0-9_-]{1,64}$/.test(id)?id:''})
  const [reviewLink,setReviewLink]=useState(()=>readReviewLink())
  const [manuscriptLink,setManuscriptLink]=useState(()=>readManuscriptLink())
  const nextKey = useRef(1)
  const [instance, setInstance] = useState<Instance | null>(() => {
    const id = new URLSearchParams(window.location.hash.slice(1)).get('project')
    return id ? { id, key: 1 } : null
  })
  const [detail, setDetail] = useState<{ instance: Instance; project: Project } | null>(null)
  const [failure, setFailure] = useState<{ instance: Instance; message: string } | null>(null)
  const [unavailableId, setUnavailableId] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(Boolean(instance))
  const current = useRef<Instance | null>(null)
  const callbacks = useRef({ onUnavailable, onAvailable })
  const request = useRef<Request | null>(null)
  const sequence = useRef(0)

  function cancel() {
    sequence.current++
    if (request.current) {
      request.current.controller.abort()
      window.clearTimeout(request.current.timeout)
      request.current = null
    }
  }

  useLayoutEffect(() => { callbacks.current = { onUnavailable, onAvailable } })
  // The parent registers this instance before detail or child passive effects issue requests.
  useLayoutEffect(() => {
    current.current = instance
    if (!instance) return
    const stop = watchProjectAccess(instance.id, () => {
      if (current.current !== instance) return
      cancel()
      current.current = null
      setInstance(null)
      setDetail(null)
      setFailure(null)
      setLoading(false)
      setUnavailableId(instance.id)
      setTaskId('');setLiteratureSearchId('');setAdaptationId('');setManuscriptLink({id:'',revision:0});setReviewLink({round:'',manuscript:'',revision:0,run:'',document:''})
      setSection('overview')
      callbacks.current.onUnavailable(instance.id)
    })
    return () => { stop(); cancel(); if (current.current === instance) current.current = null }
  }, [instance])

  useLayoutEffect(() => {
    window.history.replaceState(null, '', window.location.pathname + window.location.search
      + (instance ? `#project=${encodeURIComponent(instance.id)}${section==='reviews'?`&section=reviews${reviewLink.round?`&round=${encodeURIComponent(reviewLink.round)}${reviewLink.run?`&reviewRun=${encodeURIComponent(reviewLink.run)}`:''}${reviewLink.document?`&reviewDocument=${encodeURIComponent(reviewLink.document)}`:''}`:reviewLink.manuscript?`&reviewManuscript=${encodeURIComponent(reviewLink.manuscript)}&reviewRevision=${reviewLink.revision}`:''}`:section === 'tasks' ? `&section=tasks${taskId ? `&task=${encodeURIComponent(taskId)}` : ''}` : section==='literature'?`&section=literature${literatureSearchId?`&search=${encodeURIComponent(literatureSearchId)}`:''}`:section==='manuscripts'?`&section=manuscripts${manuscriptLink.id?`&manuscript=${encodeURIComponent(manuscriptLink.id)}&revision=${manuscriptLink.revision}`:''}`:section==='school-templates'?'&section=school-templates':section==='journals'?`&section=journals${adaptationId?`&adaptation=${encodeURIComponent(adaptationId)}`:''}`:''}` : ''))
  }, [instance, section, taskId, literatureSearchId, adaptationId, reviewLink, manuscriptLink])

  useEffect(() => {
    const openTaskLink = () => {
      const params = new URLSearchParams(window.location.hash.slice(1))
      if(instance&&current.current===instance&&params.get('project')===instance.id&&params.get('section')==='journals'&&params.getAll('project').length===1&&params.getAll('section').length===1&&params.getAll('adaptation').length<=1&&[...params.keys()].every(k=>['project','section','adaptation'].includes(k))&&(!params.has('adaptation')||/^[A-Za-z0-9_-]{1,64}$/.test(params.get('adaptation')??''))){setSection('journals');setAdaptationId(params.get('adaptation')??'');return}
      if(instance&&current.current===instance&&params.get('project')===instance.id&&params.get('section')==='reviews'&&validReviewLink(params)){setSection('reviews');setReviewLink(readReviewLink());return}
      if(instance&&current.current===instance&&params.get('project')===instance.id&&params.get('section')==='manuscripts'&&validManuscriptLink(params)){setSection('manuscripts');setManuscriptLink(readManuscriptLink());return}
      const id = params.get('task')
      if (!instance || current.current !== instance || params.get('project') !== instance.id
        || params.get('section') !== 'tasks' || !isTaskId(id) || !id.startsWith('legacy-') && !/^[A-Za-z0-9_-]{1,64}$/.test(id)
        || [...params.keys()].some(key => !['project', 'section', 'task'].includes(key))
        || ['project', 'section', 'task'].some(key => params.getAll(key).length !== 1)) return
      setSection('tasks'); setTaskId(id)
    }
    window.addEventListener('hashchange', openTaskLink)
    return () => window.removeEventListener('hashchange', openTaskLink)
  }, [instance])

  useEffect(() => {
    if (!instance) return
    const controller = new AbortController()
    const id = ++sequence.current
    const isCurrent = () => current.current === instance && sequence.current === id && !controller.signal.aborted
    const timeout = window.setTimeout(() => {
      if (!isCurrent()) return
      controller.abort()
      setFailure({ instance, message: '项目详情读取超时，请稍后重试。' })
      setLoading(false)
    }, 15_000)
    request.current = { controller, timeout }
    async function load() {
      try {
        const response = await apiFetch(`/api/v1/projects/${encodeURIComponent(instance!.id)}`, { signal: controller.signal })
        const result: unknown = await response.json()
        if (!isCurrent()) return
        if (!response.ok) throw new Error(apiError(result, '项目详情读取失败，请稍后重试。'))
        if (!isProject(result) || result.id !== instance!.id) throw new Error('项目详情格式不正确，请重试。')
        setDetail({ instance: instance!, project: result })
        if(result.project_type==='sci')setSection(previous=>previous==='school-templates'?'overview':previous)
        if(result.project_type==='thesis')setSection(previous=>previous==='journals'?'overview':previous)
        callbacks.current.onAvailable(instance!.id)
      } catch (cause) {
        if (isCurrent()) setFailure({ instance: instance!, message: cause instanceof TypeError
          ? '无法连接后端，请稍后重试项目详情。' : safeError(cause, '项目详情读取失败。') })
      } finally {
        window.clearTimeout(timeout)
        if (isCurrent()) setLoading(false)
        if (request.current?.controller === controller) request.current = null
      }
    }
    void load()
    return () => { controller.abort(); window.clearTimeout(timeout) }
  }, [instance, attempt])

  function refresh() {
    cancel()
    setFailure(null)
    setLoading(true)
    setAttempt(value => value + 1)
  }

  function open(id: string, seed?: Project) {
    setUnavailableId('')
    if (instance?.id === id && current.current === instance) { refresh(); return }
    setTaskId('');setLiteratureSearchId('');setAdaptationId('');setManuscriptLink({id:'',revision:0});setReviewLink({round:'',manuscript:'',revision:0,run:'',document:''})
    setSection('overview')
    cancel()
    const next = { id, key: ++nextKey.current }
    setInstance(next)
    setDetail(seed ? { instance: next, project: seed } : null)
    setFailure(null)
    setLoading(true)
  }

  function update(project: Project) {
    if (!instance || current.current !== instance || project.id !== instance.id) return
    cancel()
    setDetail({ instance, project })
    setFailure(null)
    setLoading(false)
  }

  function close() {
    cancel()
    setInstance(null)
    setDetail(null)
    setFailure(null)
    setUnavailableId('')
    setLoading(false)
    setTaskId('');setLiteratureSearchId('');setAdaptationId('');setManuscriptLink({id:'',revision:0});setReviewLink({round:'',manuscript:'',revision:0,run:'',document:''})
    setSection('overview')
  }

  function changeSection(next: ProjectSection) {
    setSection(next)
  }

  function selectTask(id: string) {
    if (!isTaskId(id)) return
    setSection('tasks')
    setTaskId(id)
  }

  return { instance, project: detail?.instance === instance ? detail.project : null,
    error: failure?.instance === instance ? failure.message : '', loading, unavailableId, open, refresh, update, close,
    section, taskId, literatureSearchId, reviewLink, manuscriptLink, selectRound:(id:string)=>{if(id&&!/^[A-Za-z0-9_-]{1,64}$/.test(id))return;setSection('reviews');setReviewLink({round:id,manuscript:'',revision:0,run:'',document:''})}, selectLiterature:(id:string)=>{if(id&&!/^[A-Za-z0-9_-]{1,64}$/.test(id))return;setSection('literature');setLiteratureSearchId(id)}, changeSection, selectTask }
}

function validReviewLink(p:URLSearchParams){const ids=['round','reviewManuscript','reviewRun','reviewDocument'];return p.getAll('project').length===1&&p.getAll('section').length===1&&[...p.keys()].every(k=>['project','section',...ids,'reviewRevision'].includes(k))&&[...ids,'reviewRevision'].every(k=>p.getAll(k).length<=1)&&ids.every(k=>!p.has(k)||/^[A-Za-z0-9_-]{1,64}$/.test(p.get(k)??''))&&(!p.has('round')||!p.has('reviewManuscript')&&!p.has('reviewRevision'))&&(!p.has('reviewRun')||p.has('round'))&&(!p.has('reviewDocument')||p.has('reviewRun'))&&(!p.has('reviewManuscript')&&!p.has('reviewRevision')||p.has('reviewManuscript')&&/^[1-9][0-9]*$/.test(p.get('reviewRevision')??''))}
function readReviewLink(){const p=new URLSearchParams(window.location.hash.slice(1));return p.get('section')==='reviews'&&validReviewLink(p)?{round:p.get('round')??'',manuscript:p.get('reviewManuscript')??'',revision:Number(p.get('reviewRevision')??0),run:p.get('reviewRun')??'',document:p.get('reviewDocument')??''}:{round:'',manuscript:'',revision:0,run:'',document:''}}

function validManuscriptLink(p:URLSearchParams){return p.getAll('project').length===1&&p.getAll('section').length===1&&p.getAll('manuscript').length===1&&p.getAll('revision').length===1&&[...p.keys()].every(k=>['project','section','manuscript','revision'].includes(k))&&/^[A-Za-z0-9_-]{1,64}$/.test(p.get('manuscript')??'')&&/^[1-9][0-9]*$/.test(p.get('revision')??'')&&Number.isSafeInteger(Number(p.get('revision')))}
function readManuscriptLink(){const p=new URLSearchParams(window.location.hash.slice(1));return p.get('section')==='manuscripts'&&validManuscriptLink(p)?{id:p.get('manuscript')!,revision:Number(p.get('revision'))}:{id:'',revision:0}}

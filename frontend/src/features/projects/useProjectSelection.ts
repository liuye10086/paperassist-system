import type { ReviewView, TaskDetailView } from './reviewViews';
import type { AnalysisNavigation, ArtifactNavigation } from './analysisViews';
import type { ManuscriptView, JournalView, SchoolTemplateNavigation } from './manuscriptViews';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { apiFetch } from '../../shared/api/client';
import { watchProjectAccess } from '../../shared/api/projectAccess';
import { isProject, type Project } from './projectTypes';
import { apiError, safeError } from '../../shared/i18n';
import type { ProjectSection, WorkspaceView } from './WorkspaceShell';
import { isTaskId } from '../tasks/taskTypes';
import { homeRoute, parseNavigation, serializeNavigation, validId, type NavigationRoute, type OverviewView } from './projectNavigation';
import type { ResourceNavigation } from './resourceViews';
import type { LiteratureNavigation } from './literatureViews';
function initialRoute() {
    const hash = window.location.hash, valid = parseNavigation(hash);
    if (valid)
        return valid;
    const p = new URLSearchParams(hash.slice(1));
    if (p.get('section') === 'tasks' && p.getAll('project').length === 1 && p.getAll('section').length === 1 && p.getAll('task').length === 1 && [...p.keys()].every(k => ['project', 'section', 'task'].includes(k))) {
        p.delete('task');
        const fallback = parseNavigation('#' + p.toString());
        if (fallback) {
            window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search + serializeNavigation(fallback));
            return fallback;
        }
    }
    return homeRoute();
}
type Instance = {
    id: string;
    key: number;
};
type Request = {
    controller: AbortController;
    timeout: number;
};
export default function useProjectSelection(onUnavailable: (id: string) => void, onAvailable: (id: string) => void, onNavigate?: () => void) {
    const [route, setRoute] = useState(() => initialRoute());
    const routeRef = useRef(route);
    const retainedProjectRoute = useRef(route);
    const { section, taskId, literatureSearchId, adaptationId, reviewLink, manuscriptLink } = route;
    const [instance, setInstance] = useState<Instance | null>(() => route.projectId ? { id: route.projectId, key: 1 } : null);
    const nextKey = useRef(1), current = useRef<Instance | null>(instance), callbacks = useRef({ onUnavailable, onAvailable, onNavigate }), request = useRef<Request | null>(null), sequence = useRef(0);
    const [detail, setDetail] = useState<{
        instance: Instance;
        project: Project;
    } | null>(null);
    const [failure, setFailure] = useState<{
        instance: Instance;
        message: string;
    } | null>(null);
    const [unavailableId, setUnavailableId] = useState(''), [attempt, setAttempt] = useState(0), [loading, setLoading] = useState(Boolean(instance));
    const dirtyChecks = useRef(new Set<() => boolean>());
    const guards = useRef(new Set<() => boolean>()), index = useRef(0), restore = useRef<{
        delta: number;
        route: NavigationRoute;
    } | null>(null), replay = useRef(false);
    function allowed(next: NavigationRoute) {
        const previous=routeRef.current;
        if(previous.section==='analysis'&&previous.analysisNavigation.view.startsWith('bio-')&&serializeNavigation(previous)!==serializeNavigation(next))return [...guards.current].every(g=>g());
        return !current.current || !next.projectId || next.projectId === current.current.id || [...guards.current].every(g => g());
    }
    function apply(next: NavigationRoute, seed?: Project) {
        // A same-project deep link describes only its visible section. Keep
        // inactive task destinations so Back/Forward does not hide a retained draft.
        if (next.projectId && next.projectId === current.current?.id) {
            if (next.section !== 'reviews') next = {...next,reviewLink:routeRef.current.reviewLink,reviewView:routeRef.current.reviewView,reviewItemId:routeRef.current.reviewItemId};
            if (next.section !== 'tasks') next = {...next,taskId:routeRef.current.taskId,taskDetailView:routeRef.current.taskDetailView};
            if (next.section !== 'analysis') next = { ...next, analysisNavigation: routeRef.current.analysisNavigation };
            if (next.section !== 'artifacts') next = { ...next, artifactNavigation: routeRef.current.artifactNavigation };
            if (next.section !== 'manuscripts') next = { ...next, manuscriptView: routeRef.current.manuscriptView, manuscriptLink: routeRef.current.manuscriptLink };
            if (next.section !== 'journals') next = { ...next, journalView: routeRef.current.journalView, adaptationId: routeRef.current.adaptationId };
            if (next.section !== 'school-templates') next = { ...next, schoolTemplateNavigation: routeRef.current.schoolTemplateNavigation };
        }
        if (next.workspaceView === 'project')
            retainedProjectRoute.current = next;
        else
            next = { ...retainedProjectRoute.current, workspaceView: next.workspaceView, projectId: '' };
        routeRef.current = next;
        setRoute(next);
        if (next.projectId && next.projectId !== current.current?.id) {
            cancel();
            const fresh = { id: next.projectId, key: ++nextKey.current };
            current.current = fresh;
            setInstance(fresh);
            setDetail(seed ? { instance: fresh, project: seed } : null);
            setFailure(null);
            setLoading(true);
            setUnavailableId('');
        }
        callbacks.current.onNavigate?.();
    }
    function write(next: NavigationRoute, replace = false) {
        if (!replace)
            index.current++;
        window.history[replace ? 'replaceState' : 'pushState']({ ...window.history.state, paperassistNavigationIndex: index.current }, '', window.location.pathname + window.location.search + serializeNavigation(next));
    }
    function navigate(next: NavigationRoute, seed?: Project) {
        if (!allowed(next))
            return;
        if (serializeNavigation(next) !== serializeNavigation(routeRef.current))
            write(next);
        apply(next, seed);
    }
    function setSection(value: ProjectSection | ((s: ProjectSection) => ProjectSection)) {
        const section = typeof value === 'function' ? value(routeRef.current.section) : value;
        if (section === routeRef.current.section)
            return;
        const next = { ...routeRef.current, section };
        write(next, true);
        apply(next);
    }
    function cancel() {
        sequence.current++;
        if (request.current) {
            request.current.controller.abort();
            window.clearTimeout(request.current.timeout);
            request.current = null;
        }
    }
    useLayoutEffect(() => {
        callbacks.current = { onUnavailable, onAvailable, onNavigate };
    });
    // The parent registers this instance before detail or child passive effects issue requests.
    useLayoutEffect(() => {
        current.current = instance;
        if (!instance)
            return;
        const stop = watchProjectAccess(instance.id, () => {
            if (current.current !== instance)
                return;
            cancel();
            current.current = null;
            setInstance(null);
            setDetail(null);
            setFailure(null);
            setLoading(false);
            setUnavailableId(instance.id);
            retainedProjectRoute.current = homeRoute();
            apply(homeRoute());
            write(homeRoute(), true);
            callbacks.current.onUnavailable(instance.id);
        });
        return () => {
            stop();
            cancel();
            if (current.current === instance)
                current.current = null;
        };
    }, [instance]);
    useEffect(() => {
        index.current = Number.isInteger(window.history.state?.paperassistNavigationIndex) ? window.history.state.paperassistNavigationIndex : 0;
        window.history.replaceState({ ...window.history.state, paperassistNavigationIndex: index.current }, '');
        function unload(event: BeforeUnloadEvent) {
            if ([...dirtyChecks.current].some(check => check())) {
                event.preventDefault();
                event.returnValue = '';
            }
        }
        window.addEventListener('beforeunload', unload);
        function follow(event: Event) {
            if (event.type === 'hashchange' && (restore.current || replay.current))
                return;
            const next = parseNavigation(window.location.hash);
            if (!next)
                return;
            let nextIndex = window.history.state?.paperassistNavigationIndex;
            if (restore.current) {
                const pending = restore.current;
                restore.current = null;
                if (allowed(pending.route)) {
                    replay.current = true;
                    window.history.go(pending.delta);
                }
                return;
            }
            if (serializeNavigation(next) === serializeNavigation(routeRef.current) && nextIndex === index.current)
                return;
            // A native location.hash assignment creates a new entry, but browsers may
            // clear state or inherit our current index. Stamp only metadata before the
            // ordinary pointer-restoration path; never replace either entry's URL.
            if (!Number.isInteger(nextIndex) || nextIndex === index.current) {
                nextIndex = index.current + 1;
                window.history.replaceState({ ...window.history.state, paperassistNavigationIndex: nextIndex }, '');
            }
            const delta = nextIndex - index.current;
            if (!replay.current && next.projectId && current.current && next.projectId !== current.current.id && guards.current.size) {
                restore.current = { delta, route: next };
                window.history.go(-delta);
                return;
            }
            replay.current = false;
            index.current = nextIndex;
            apply(next);
        }
        function click(event: MouseEvent) {
            if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || !(event.target instanceof Element))
                return;
            const a = event.target.closest('a');
            if (!a || a.hasAttribute('download') || a.target && a.target !== '_self' || !a.hasAttribute('href'))
                return;
            const url = new URL(a.href);
            if (url.origin !== window.location.origin || url.pathname !== window.location.pathname || url.search !== window.location.search)
                return;
            const next = parseNavigation(url.hash);
            if (next) {
                event.preventDefault();
                navigate(next);
            }
        }
        window.addEventListener('popstate', follow);
        window.addEventListener('hashchange', follow);
        document.addEventListener('click', click);
        return () => {
            window.removeEventListener('beforeunload', unload);
            window.removeEventListener('popstate', follow);
            window.removeEventListener('hashchange', follow);
            document.removeEventListener('click', click);
        };
    }, []);
    useEffect(() => {
        if (!instance)
            return;
        const controller = new AbortController();
        const id = ++sequence.current;
        const isCurrent = () => current.current === instance && sequence.current === id && !controller.signal.aborted;
        const timeout = window.setTimeout(() => {
            if (!isCurrent())
                return;
            controller.abort();
            setFailure({ instance, message: '项目详情读取超时，请稍后重试。' });
            setLoading(false);
        }, 15000);
        request.current = { controller, timeout };
        async function load() {
            try {
                const response = await apiFetch(`/api/v1/projects/${encodeURIComponent(instance!.id)}`, { signal: controller.signal });
                const result: unknown = await response.json();
                if (!isCurrent())
                    return;
                if (!response.ok)
                    throw new Error(apiError(result, '项目详情读取失败，请稍后重试。'));
                if (!isProject(result) || result.id !== instance!.id)
                    throw new Error('项目详情格式不正确，请重试。');
                setDetail({ instance: instance!, project: result });
                if (result.project_type === 'sci')
                    setSection(previous => previous === 'school-templates' ? 'overview' : previous);
                if (result.project_type === 'thesis')
                    setSection(previous => previous === 'journals' ? 'overview' : previous);
                callbacks.current.onAvailable(instance!.id);
            }
            catch (cause) {
                if (isCurrent())
                    setFailure({ instance: instance!, message: cause instanceof TypeError
                            ? '无法连接后端，请稍后重试项目详情。' : safeError(cause, '项目详情读取失败。') });
            }
            finally {
                window.clearTimeout(timeout);
                if (isCurrent())
                    setLoading(false);
                if (request.current?.controller === controller)
                    request.current = null;
            }
        }
        void load();
        return () => {
            controller.abort();
            window.clearTimeout(timeout);
        };
    }, [instance, attempt]);
    function refresh() {
        cancel();
        setFailure(null);
        setLoading(true);
        setAttempt(value => value + 1);
    }
    function open(id: string, seed?: Project) {
        if (current.current?.id === id && routeRef.current.workspaceView === 'project') {
            refresh();
            return;
        }
        if (validId(id))
            navigate({ ...homeRoute(), workspaceView: 'project', projectId: id }, seed);
    }
    function update(project: Project) {
        if (!instance || current.current !== instance || project.id !== instance.id)
            return;
        cancel();
        setDetail({ instance, project });
        setFailure(null);
        setLoading(false);
    }
    function close() {
        if (![...guards.current].every(g => g()))
            return;
        cancel();
        current.current = null;
        setInstance(null);
        setDetail(null);
        setFailure(null);
        setUnavailableId('');
        setLoading(false);
        retainedProjectRoute.current = homeRoute();
        navigate(homeRoute());
    }
    function changeSection(next: ProjectSection) {
        navigate({ ...routeRef.current, projectId: current.current?.id ?? '', workspaceView: 'project', section: next });
    }
    function selectTask(id: string) {
        if (!id || isTaskId(id))
            navigate({ ...routeRef.current, projectId: current.current?.id ?? '', workspaceView: 'project', section: 'tasks', taskId: id, taskDetailView:'overview' });
    }
    function selectTaskDetailView(taskDetailView:TaskDetailView) {
        if (routeRef.current.taskId) navigate({...routeRef.current,projectId:current.current?.id ?? '',workspaceView:'project',section:'tasks',taskDetailView});
    }
    function selectReviewView(reviewView:ReviewView) {
        const reviewLink = {...routeRef.current.reviewLink};
        if (reviewView === 'comparison' || reviewView === 'response') reviewLink.document = '';
        navigate({...routeRef.current,projectId:current.current?.id ?? '',workspaceView:'project',section:'reviews',reviewView,reviewLink});
    }
    function selectReviewItem(reviewItemId:string) {
        if (validId(reviewItemId) && routeRef.current.reviewLink.round)
            navigate({...routeRef.current,projectId:current.current?.id ?? '',workspaceView:'project',section:'reviews',reviewItemId});
    }
    function selectReviewRun(run:string) {
        if ((!run || validId(run)) && routeRef.current.reviewLink.round)
            navigate({...routeRef.current,projectId:current.current?.id ?? '',workspaceView:'project',section:'reviews',reviewLink:{...routeRef.current.reviewLink,run,document:''}});
    }
    function selectReviewDocument(document:string) {
        if ((!document || validId(document)) && routeRef.current.reviewLink.run)
            navigate({...routeRef.current,projectId:current.current?.id ?? '',workspaceView:'project',section:'reviews',reviewLink:{...routeRef.current.reviewLink,document}});
    }
    function navigateWorkspace(view: WorkspaceView) {
        navigate({ ...routeRef.current, workspaceView: view === 'project' && !current.current ? 'projects' : view, projectId: view === 'project' ? current.current?.id ?? '' : '' });
    }
    function changeOverviewView(view: OverviewView) {
        navigate({ ...routeRef.current, projectId: current.current?.id ?? '', workspaceView: 'project', section: 'overview', overviewView: view });
    }
    function registerLeaveGuard(guard: () => boolean, isDirty?: () => boolean) {
        guards.current.add(guard);
        if (isDirty)
            dirtyChecks.current.add(isDirty);
        return () => {
            guards.current.delete(guard);
            if (isDirty)
                dirtyChecks.current.delete(isDirty);
        };
    }
    function selectResource(resourceNavigation: ResourceNavigation) {
        const next = {...routeRef.current, projectId:current.current?.id ?? '', workspaceView:'project' as const, section:'files' as const, resourceNavigation};
        if (parseNavigation(serializeNavigation(next))) navigate(next);
    }
    function selectLiteratureView(literatureNavigation: LiteratureNavigation) {
        const next = {...routeRef.current, projectId:current.current?.id ?? '', workspaceView:'project' as const, section:'literature' as const, literatureNavigation};
        if (parseNavigation(serializeNavigation(next))) navigate(next);
    }
    function selectAnalysis(analysisNavigation: AnalysisNavigation) {
        const next = {...routeRef.current, projectId:current.current?.id ?? '', workspaceView:'project' as const, section:'analysis' as const, analysisNavigation};
        if (parseNavigation(serializeNavigation(next))) navigate(next);
    }
    function selectArtifact(artifactNavigation: ArtifactNavigation) {
        const next = {...routeRef.current, projectId:current.current?.id ?? '', workspaceView:'project' as const, section:'artifacts' as const, artifactNavigation};
        if (parseNavigation(serializeNavigation(next))) navigate(next);
    }
    function selectManuscriptView(manuscriptView: ManuscriptView) {
        navigate({...routeRef.current, projectId:current.current?.id ?? '',workspaceView:'project',section:'manuscripts',manuscriptView});
    }
    function selectManuscriptVersion(id:string, revision:number) {
        if (validId(id) && Number.isSafeInteger(revision) && revision > 0)
            navigate({...routeRef.current, projectId:current.current?.id ?? '',workspaceView:'project',section:'manuscripts',manuscriptLink:{id,revision}});
    }
    function selectJournalView(journalView:JournalView) {
        navigate({...routeRef.current,projectId:current.current?.id ?? '',workspaceView:'project',section:'journals',journalView});
    }
    function selectJournalAdaptation(adaptationId:string) {
        if (!adaptationId || validId(adaptationId))
            navigate({...routeRef.current,projectId:current.current?.id ?? '',workspaceView:'project',section:'journals',journalView:'adaptation',adaptationId});
    }
    function selectSchoolTemplate(schoolTemplateNavigation:SchoolTemplateNavigation) {
        const next = {...routeRef.current,projectId:current.current?.id ?? '',workspaceView:'project' as const,section:'school-templates' as const,schoolTemplateNavigation};
        if (parseNavigation(serializeNavigation(next))) navigate(next);
    }
    return { instance, project: detail?.instance === instance ? detail?.project ?? null : null, error: failure?.instance === instance ? failure?.message ?? '' : '', loading, unavailableId, open, refresh, update, close,
        reviewView:route.reviewView,reviewItemId:route.reviewItemId,taskDetailView:route.taskDetailView,
        selectReviewView,selectReviewItem,selectReviewRun,selectReviewDocument,selectTaskDetailView,
        manuscriptView:route.manuscriptView,journalView:route.journalView,schoolTemplateNavigation:route.schoolTemplateNavigation,
        selectManuscriptView,selectManuscriptVersion,selectJournalView,selectJournalAdaptation,selectSchoolTemplate,
        workspaceView: route.workspaceView, navigateWorkspace, overviewView: route.overviewView, changeOverviewView, registerLeaveGuard,
        section, taskId, literatureSearchId, adaptationId, reviewLink, manuscriptLink, selectTask, changeSection,
        analysisNavigation:route.analysisNavigation, artifactNavigation:route.artifactNavigation, selectAnalysis, selectArtifact,
        resourceNavigation:route.resourceNavigation, literatureNavigation:route.literatureNavigation, selectResource, selectLiteratureView,
        selectRound: (id: string) => {
            if (!id || validId(id))
                navigate({ ...routeRef.current, projectId: current.current?.id ?? '', workspaceView: 'project', section: 'reviews', reviewView:id?'items':'list',reviewItemId:'', reviewLink: { round: id, manuscript: '', revision: 0, run: '', document: '' } });
        },
        selectLiterature: (id: string) => {
            if (!id || validId(id))
                navigate({ ...routeRef.current, projectId: current.current?.id ?? '', workspaceView: 'project', section: 'literature', literatureSearchId: id, literatureNavigation:{view:'list',referenceId:''} });
        } };
}

import type { ProjectSection, WorkspaceView } from './WorkspaceShell';
import { isTaskId } from '../tasks/taskTypes';
import type { ResourceNavigation } from './resourceViews';
import { reviewViews, taskDetailViews, type ReviewView, type TaskDetailView } from './reviewViews';
import type { LiteratureNavigation } from './literatureViews';
import { analysisViews, bioResultTabs, type AnalysisNavigation, type ArtifactNavigation } from './analysisViews';
import { manuscriptViews, journalViews, schoolTemplateViews, type ManuscriptView, type JournalView, type SchoolTemplateNavigation } from './manuscriptViews';
export type OverviewView = 'tasks' | 'settings' | 'activity' | 'usage' | 'requirements' | 'deliveries' | 'design';
export type NavigationRoute = {
    workspaceView: WorkspaceView;
    projectId: string;
    section: ProjectSection;
    overviewView: OverviewView;
    taskId: string;
    taskDetailView: TaskDetailView;
    reviewView: ReviewView;
    reviewItemId: string;
    literatureSearchId: string;
    resourceNavigation: ResourceNavigation;
    literatureNavigation: LiteratureNavigation;
    analysisNavigation: AnalysisNavigation;
    artifactNavigation: ArtifactNavigation;
    adaptationId: string;
    manuscriptView: ManuscriptView;
    journalView: JournalView;
    schoolTemplateNavigation: SchoolTemplateNavigation;
    manuscriptLink: {
        id: string;
        revision: number;
    };
    reviewLink: {
        round: string;
        manuscript: string;
        revision: number;
        run: string;
        document: string;
    };
};
export const validId = (id: string) => /^[A-Za-z0-9_-]{1,64}$/.test(id);
export const homeRoute = (): NavigationRoute => ({ workspaceView: 'home', projectId: '', section: 'overview', overviewView: 'tasks', taskId: '', taskDetailView:'overview', reviewView:'list', reviewItemId:'', literatureSearchId: '', resourceNavigation: {view:'list',fileId:''}, literatureNavigation: {view:'list',referenceId:''}, analysisNavigation: {view:'overview',fileId:''}, artifactNavigation: {view:'list',artifactId:'',kind:'',page:1}, adaptationId: '', manuscriptView: 'list', journalView: 'overview', schoolTemplateNavigation: {view:'list',templateId:''}, manuscriptLink: { id: '', revision: 0 }, reviewLink: { round: '', manuscript: '', revision: 0, run: '', document: '' } });
export function parseNavigation(hash: string): NavigationRoute | null {
    const p = new URLSearchParams(hash.replace(/^#/, '')), r = homeRoute();
    if (!p.size)
        return r;
    if ([...p.keys()].some(k => p.getAll(k).length !== 1))
        return null;
    if (p.has('workspace'))
        return p.size === 1 && ['home', 'projects'].includes(p.get('workspace')!) ? { ...r, workspaceView: p.get('workspace') as WorkspaceView } : null;
    if (!validId(p.get('project') ?? ''))
        return null;
    r.workspaceView = 'project';
    r.projectId = p.get('project')!;
    const section = p.get('section') ?? 'overview';
    if (!['overview', 'files', 'analysis', 'artifacts', 'tasks', 'literature', 'manuscripts', 'reviews', 'school-templates', 'journals'].includes(section))
        return null;
    r.section = section as ProjectSection;
    const keys: Record<string, string[]> = { overview: ['view'], analysis:['view','file','import','dataset','version','setup','run','processed','tab','annotationSet','annotationVersion','figure'], artifacts:['view','artifact','kind','page'], files: ['view','file'], tasks: ['view','task'], literature: ['search','view','reference'], manuscripts: ['view','manuscript', 'revision'], reviews: ['view','item','round', 'reviewManuscript', 'reviewRevision', 'reviewRun', 'reviewDocument'], journals: ['view','adaptation'], 'school-templates':['view','template'] };
    if ([...p.keys()].some(k => !['project', 'section', ...(keys[section] ?? [])].includes(k)))
        return null;
    const id = (key: string) => !p.has(key) || validId(p.get(key)!);
    const revision = (key: string) => /^[1-9][0-9]*$/.test(p.get(key) ?? '') && Number.isSafeInteger(Number(p.get(key)));
    if (section === 'overview') {
        if (p.has('view') && !['tasks', 'settings', 'activity', 'usage','requirements','deliveries','design'].includes(p.get('view')!))
            return null;
        r.overviewView = (p.get('view') ?? 'tasks') as OverviewView;
    }
    if (section === 'tasks') {
        r.taskId = p.get('task') ?? '';
        const view = p.get('view') ?? 'overview';
        if (!(taskDetailViews as readonly string[]).includes(view) || view !== 'overview' && !r.taskId) return null;
        r.taskDetailView = view as TaskDetailView;
        if (p.has('task') && (!isTaskId(r.taskId) || !r.taskId.startsWith('legacy-') && !validId(r.taskId)))
            return null;
    }
    if (section === 'literature') {
        const view = p.get('view') ?? 'list';
        if (!id('search') || !['list','search','history','detail','evidence','citations'].includes(view) || !id('reference') || (view === 'detail') !== p.has('reference'))
            return null;
        r.literatureSearchId = p.get('search') ?? '';
        r.literatureNavigation = {view:view as LiteratureNavigation['view'],referenceId:p.get('reference') ?? ''};
    }
    if (section === 'files') {
        const view = p.get('view') ?? 'list';
        if (!['list','upload','detail','preview'].includes(view) || !id('file') || ['detail','preview'].includes(view) !== p.has('file'))
            return null;
        r.resourceNavigation = {view:view as ResourceNavigation['view'],fileId:p.get('file') ?? ''};
    }
    if (section === 'analysis') {
        const view = p.get('view') ?? 'overview';
        if (!(analysisViews as readonly string[]).includes(view) || !id('file')) return null;
        if (view.startsWith('bio-')) {
            const identities:Record<string,string[]>={'bio-datasets':[],'bio-import':['import'],'bio-dataset':['dataset','version'],'bio-analysis-setup':['setup'],'bio-analysis':['run'],'bio-result':['processed','tab'],'bio-annotation':['annotationSet','annotationVersion'],'bio-figure':['figure']};
            const required=identities[view];
            if (!required || [...p.keys()].some(k=>!['project','section','view',...required].includes(k)) || required.some(k=>!p.has(k)||!id(k))) return null;
            if(view==='bio-result'&&!(bioResultTabs as readonly string[]).includes(p.get('tab')!))return null;
        } else if (['import','dataset','version','setup','run','processed','tab','annotationSet','annotationVersion','figure'].some(k => p.has(k))) return null;
        r.analysisNavigation = {view:view as AnalysisNavigation['view'],fileId:p.get('file') ?? ''};
        const fields={import:'importId',dataset:'datasetId',version:'versionId',setup:'setupId',run:'runId',processed:'processedId',tab:'tab',annotationSet:'annotationSetId',annotationVersion:'annotationVersionId',figure:'figureId'} as const;
        for(const [key,field] of Object.entries(fields))if(p.has(key))Object.assign(r.analysisNavigation,{[field]:p.get(key)!});
    }
    if (section === 'artifacts') {
        const view = p.get('view') ?? 'list';
        if (!['list','detail','layout'].includes(view) || !id('artifact') || (view === 'detail') !== p.has('artifact') || (view === 'detail') !== p.has('kind') || p.has('kind') && !['figure','report'].includes(p.get('kind')!) || p.has('page') && !revision('page')) return null;
        r.artifactNavigation = {view:view as ArtifactNavigation['view'],artifactId:p.get('artifact') ?? '',kind:(p.get('kind') ?? '') as ArtifactNavigation['kind'],page:Number(p.get('page') ?? 1)};
    }
    if (section === 'journals') {
        const view = p.get('view') ?? (p.has('adaptation') ? 'adaptation' : 'overview');
        if (!id('adaptation') || !(journalViews as readonly string[]).includes(view))
            return null;
        r.journalView = view as JournalView;
        r.adaptationId = p.get('adaptation') ?? '';
    }
    if (section === 'school-templates') {
        const view = p.get('view') ?? 'list';
        if (!(schoolTemplateViews as readonly string[]).includes(view) || !id('template') || ['detail','rules','confirm','binding'].includes(view) !== p.has('template')) return null;
        r.schoolTemplateNavigation = {view:view as SchoolTemplateNavigation['view'],templateId:p.get('template') ?? ''};
    }
    if (section === 'manuscripts') {
        const view = p.get('view') ?? (p.has('manuscript') ? 'body' : 'list');
        if (!(manuscriptViews as readonly string[]).includes(view)) return null;
        r.manuscriptView = view as ManuscriptView;
        if (p.has('manuscript') !== p.has('revision') || p.has('manuscript') && (!id('manuscript') || !revision('revision')))
            return null;
        r.manuscriptLink = { id: p.get('manuscript') ?? '', revision: Number(p.get('revision') ?? 0) };
    }
    if (section === 'reviews') {
        const view = p.get('view') ?? (p.has('reviewDocument') ? 'documents' : p.has('reviewRun') ? 'revision' : p.has('round') ? 'items' : p.has('reviewManuscript') ? 'create' : 'list');
        if (!(reviewViews as readonly string[]).includes(view) || !id('item') || p.has('item') && !p.has('round')) return null;
        if (!p.has('round') && !['list','create','progress'].includes(view) || p.has('round') && view === 'create') return null;
        r.reviewView = view as ReviewView;
        r.reviewItemId = p.get('item') ?? '';
        if (!['round', 'reviewManuscript', 'reviewRun', 'reviewDocument'].every(id) || p.has('round') && (p.has('reviewManuscript') || p.has('reviewRevision')) || p.has('reviewRun') && !p.has('round') || p.has('reviewDocument') && !p.has('reviewRun') || p.has('reviewManuscript') !== p.has('reviewRevision') || p.has('reviewRevision') && !revision('reviewRevision'))
            return null;
        r.reviewLink = { round: p.get('round') ?? '', manuscript: p.get('reviewManuscript') ?? '', revision: Number(p.get('reviewRevision') ?? 0), run: p.get('reviewRun') ?? '', document: p.get('reviewDocument') ?? '' };
    }
    return r;
}
export function serializeNavigation(r: NavigationRoute): string {
    if (r.workspaceView !== 'project')
        return '#workspace=' + r.workspaceView;
    const p = new URLSearchParams({ project: r.projectId });
    if (r.section !== 'overview' || r.overviewView !== 'tasks')
        p.set('section', r.section);
    if (r.section === 'overview' && r.overviewView !== 'tasks')
        p.set('view', r.overviewView);
    if (r.section === 'tasks') {
        if (r.taskId && r.taskDetailView !== 'overview') p.set('view',r.taskDetailView);
        if (r.taskId) p.set('task', r.taskId);
    }
    if (r.section === 'files') {
        if (r.resourceNavigation.view !== 'list') p.set('view', r.resourceNavigation.view);
        if (['detail','preview'].includes(r.resourceNavigation.view)) p.set('file', r.resourceNavigation.fileId);
    }
    if (r.section === 'literature') {
        if (r.literatureNavigation.view !== 'list') p.set('view', r.literatureNavigation.view);
        if (r.literatureNavigation.view === 'detail') p.set('reference', r.literatureNavigation.referenceId);
    }
    if (r.section === 'literature' && r.literatureSearchId)
        p.set('search', r.literatureSearchId);
    if (r.section === 'analysis') {
        if (r.analysisNavigation.view !== 'overview') p.set('view', r.analysisNavigation.view);
        if (!r.analysisNavigation.view.startsWith('bio-') && r.analysisNavigation.fileId) p.set('file', r.analysisNavigation.fileId);
        if (r.analysisNavigation.view === 'bio-import' && r.analysisNavigation.importId) p.set('import',r.analysisNavigation.importId);
        if (r.analysisNavigation.view === 'bio-dataset' && r.analysisNavigation.datasetId && r.analysisNavigation.versionId) { p.set('dataset',r.analysisNavigation.datasetId); p.set('version',r.analysisNavigation.versionId); }
        const a=r.analysisNavigation;
        if(a.view==='bio-analysis-setup'&&a.setupId)p.set('setup',a.setupId);
        if(a.view==='bio-analysis'&&a.runId)p.set('run',a.runId);
        if(a.view==='bio-result'&&a.processedId&&a.tab){p.set('processed',a.processedId);p.set('tab',a.tab);}
        if(a.view==='bio-annotation'&&a.annotationSetId&&a.annotationVersionId){p.set('annotationSet',a.annotationSetId);p.set('annotationVersion',a.annotationVersionId);}
        if(a.view==='bio-figure'&&a.figureId)p.set('figure',a.figureId);
    }
    if (r.section === 'artifacts') {
        const a = r.artifactNavigation;
        if (a.view !== 'list') p.set('view',a.view);
        if (a.view === 'detail') { p.set('artifact',a.artifactId); p.set('kind',a.kind); }
        if (a.page !== 1) p.set('page',String(a.page));
    }
    if (r.section === 'journals' && r.journalView !== (r.adaptationId ? 'adaptation' : 'overview')) p.set('view',r.journalView);
    if (r.section === 'school-templates') {
        if (r.schoolTemplateNavigation.view !== 'list') p.set('view',r.schoolTemplateNavigation.view);
        if (r.schoolTemplateNavigation.templateId) p.set('template',r.schoolTemplateNavigation.templateId);
    }
    if (r.section === 'manuscripts' && r.manuscriptView !== (r.manuscriptLink.id ? 'body' : 'list')) p.set('view',r.manuscriptView);
    if (r.section === 'journals' && r.adaptationId)
        p.set('adaptation', r.adaptationId);
    if (r.section === 'manuscripts' && r.manuscriptLink.id) {
        p.set('manuscript', r.manuscriptLink.id);
        p.set('revision', String(r.manuscriptLink.revision));
    }
    if (r.section === 'reviews') {
        const l = r.reviewLink;
        const defaultView = l.document ? 'documents' : l.run ? 'revision' : l.round ? 'items' : l.manuscript ? 'create' : 'list';
        if (r.reviewView !== defaultView) p.set('view',r.reviewView);
        if (r.reviewItemId && l.round) p.set('item',r.reviewItemId);
        if (l.round) {
            p.set('round', l.round);
            if (l.run)
                p.set('reviewRun', l.run);
            if (l.document)
                p.set('reviewDocument', l.document);
        }
        else if (l.manuscript) {
            p.set('reviewManuscript', l.manuscript);
            p.set('reviewRevision', String(l.revision));
        }
    }
    return '#' + p.toString();
}

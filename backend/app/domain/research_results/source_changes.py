"""Read-only newer-version notices over explicitly selected, fixed sources."""
from app.auth.project_access import assignment_for_owner
from .sources import ResearchSourceReader

LINEAGES={'research_finding_version':('research_finding_versions','set_id'),
    'research_figure_version':('research_figure_versions','root_id'),
    'research_report_version':('research_report_versions','root_id'),
    'bio_figure_version':('bio_figure_versions','root_id')}


def check_changes(assets,project,selections):
    reader=ResearchSourceReader(assets);items=[]
    with reader.store.connection() as db:
        reader.store.require_project(db,project)
        for selection in selections:
            fixed=reader.read_source(project,selection,db=db)
            latest=None;lineage=LINEAGES.get(fixed.source_kind)
            if lineage:
                table,root=lineage;revision='version' if fixed.source_kind=='bio_figure_version' else 'revision'
                latest=db.execute('SELECT n.id,n.'+revision+' AS revision FROM '+table+' old JOIN '+table+' n ON n.'+root+'=old.'+root+
                    ' AND n.project_id=old.project_id WHERE old.id=%s AND old.project_id=%s AND n.'+revision+'>old.'+revision+' ORDER BY n.'+revision+' DESC LIMIT 1',
                    (fixed.source_id,project)).fetchone()
            elif fixed.source_kind=='analysis_run':
                latest=db.execute("SELECT n.id,n.setup_revision AS revision FROM analysis_runs old JOIN analysis_runs n ON n.file_id=old.file_id JOIN files f ON f.id=n.file_id WHERE old.id=%s AND f.project_id=%s AND n.setup_revision>old.setup_revision AND nullif(n.completed_at,'') IS NOT NULL AND n.result_json::jsonb->>'completed_at'=n.completed_at ORDER BY n.setup_revision DESC,n.completed_at DESC LIMIT 1",(fixed.source_id,project)).fetchone()
            elif fixed.source_kind in ('bio_insight_result_version','bio_insight_result_member'):
                identifier=fixed.content['result_version_id']
                member=fixed.content.get('member')
                select='m.id' if member else 'n.id'
                join=' JOIN bio_insight_result_members m ON m.result_version_id=n.id AND m.project_id=n.project_id AND m.key=%s' if member else ''
                params=([member['key']] if member else [])+[identifier,project]
                latest=db.execute('SELECT '+select+' AS id,nv.version AS revision FROM bio_insight_result_versions old '
                    'JOIN bio_insight_plan_versions ov ON ov.id=old.plan_version_id AND ov.project_id=old.project_id '
                    'JOIN bio_insight_plan_versions nv ON nv.plan_id=ov.plan_id AND nv.project_id=ov.project_id AND nv.version>ov.version '
                    'JOIN bio_insight_result_versions n ON n.plan_version_id=nv.id AND n.project_id=old.project_id '
                    'JOIN tasks t ON t.id=n.task_id AND t.status=\'succeeded\''+join+
                    ' WHERE old.id=%s AND old.project_id=%s ORDER BY nv.version DESC,n.created_at DESC LIMIT 1',tuple(params)).fetchone()
            impact=dependency_impact(db,project,reader.store.user_id,fixed.source_kind,fixed.source_id)
            affected=impact['affected'];truncated=impact['affected_truncated']
            items.append(dict(source_kind=fixed.source_kind,source_id=fixed.source_id,sha256=fixed.sha256,fixed_source_unchanged=True,
                newer_version_id=latest['id'] if latest else None,newer_revision=latest['revision'] if latest else None,
                affected=affected,affected_truncated=truncated,automatic_replacement=False))
    return dict(items=items)


def dependency_impact(db,project,user,kind,identifier,limit=500):
    """Bounded read-only graph; member/version aliases share downstream reachability."""
    include_manuscripts = assignment_for_owner(user) is None
    visited={(kind,identifier)};pending=[(kind,identifier)];affected=[];truncated=False
    def add(child,**extra):
        nonlocal truncated
        if child in visited:return
        if len(visited)>=limit:
            truncated=True;return
        visited.add(child);pending.append(child)
        affected.append(dict(source_kind=child[0],source_id=child[1],**extra))
    while pending and not truncated:
        kind,identifier=pending.pop(0)
        if kind=='bio_insight_result_version':
            for row in db.execute('SELECT id FROM bio_insight_result_members WHERE result_version_id=%s AND project_id=%s AND user_id=%s ORDER BY id LIMIT 501',(identifier,project,user)).fetchall():
                add(('bio_insight_result_member',row['id']))
        elif kind=='bio_insight_result_member':
            row=db.execute('SELECT result_version_id FROM bio_insight_result_members WHERE id=%s AND project_id=%s AND user_id=%s',(identifier,project,user)).fetchone()
            if row:add(('bio_insight_result_version',row['result_version_id']))
        for row in db.execute('SELECT DISTINCT v.id FROM bio_insight_plan_sources s JOIN bio_insight_plan_versions v ON v.id=s.plan_version_id AND v.project_id=s.project_id AND v.user_id=s.user_id WHERE s.project_id=%s AND s.user_id=%s AND s.source_kind=%s AND s.source_id=%s ORDER BY v.id LIMIT 501',(project,user,kind,identifier)).fetchall():
            add(('bio_insight_plan_version',row['id']))
        if kind=='bio_insight_plan_version':
            for row in db.execute('SELECT id FROM bio_insight_runs WHERE plan_version_id=%s AND project_id=%s AND user_id=%s ORDER BY id LIMIT 501',(identifier,project,user)).fetchall():
                add(('bio_insight_run',row['id']))
        if kind=='bio_insight_run':
            for row in db.execute('SELECT id FROM bio_insight_result_versions WHERE run_id=%s AND project_id=%s AND user_id=%s ORDER BY id LIMIT 501',(identifier,project,user)).fetchall():
                add(('bio_insight_result_version',row['id']))
        for row in db.execute('SELECT DISTINCT parent_kind,finding_version_id,figure_version_id,report_version_id FROM research_source_bindings WHERE project_id=%s AND user_id=%s AND source_kind=%s AND source_id=%s ORDER BY parent_kind,finding_version_id,figure_version_id,report_version_id LIMIT 501',(project,user,kind,identifier)).fetchall():
            add(('research_'+row['parent_kind']+'_version',row[row['parent_kind']+'_version_id']))
        if not include_manuscripts:
            continue
        for row in db.execute('SELECT s.version_id,v.manuscript_id,v.revision FROM manuscript_research_sources s JOIN manuscript_versions v ON v.id=s.version_id AND v.project_id=s.project_id WHERE s.project_id=%s AND s.user_id=%s AND s.source_kind=%s AND s.source_id=%s ORDER BY s.version_id LIMIT 501',(project,user,kind,identifier)).fetchall():
            add(('manuscript_version',row['version_id']),manuscript_id=row['manuscript_id'],revision=row['revision'])
    return dict(affected=affected,affected_truncated=truncated,automatic_replacement=False)

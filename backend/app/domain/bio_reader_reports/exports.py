"""Read completed R1 artifacts bound to one exact native report context."""
from typing import Literal

from app.adapters.bio_analysis_store import scoped_object
from app.adapters.research_objects import ResearchObjects
from app.adapters.research_results_store import ResearchResultsStore, invalid
from app.domain.research_results.reports import ResearchReportService
from app.domain.research_results.sources import ResearchSourceReader

from .service import BioReaderReportService


MemberRole = Literal['docx', 'xlsx', 'zip']
MEMBER_ROLES = ('docx', 'xlsx', 'zip')
PAGE_SIZE = 20


class BioReaderReportExports(ResearchResultsStore):
    def __init__(self, assets):
        super().__init__(assets)
        self.reports = ResearchReportService(assets)
        self.objects = ResearchObjects(assets.directory)

    def _bound_report(self, db, project, report, context=None):
        content = self.verify_content(report)
        fixed = content['finding']
        finding = self.require(db, 'research_finding_versions', project, report['finding_version_id'])
        finding_content = self.verify_content(finding)
        sources = finding_content['sources']
        if len(sources) != 1 or sources[0]['source_kind'] != 'bio_report_context':
            raise invalid()
        source = sources[0]
        if context is None:
            context = self.require(db, 'bio_report_context_versions', project, source['source_id'])
        context_content = self.verify_content(context)
        if (source['source_id'] != context['id'] or source['sha256'] != context['content_sha256']
                or fixed['id'] != finding['id'] or fixed['sha256'] != finding['content_sha256']
                or fixed['content'] != finding_content
                or context_content['language'] != content['language'] or report['language'] != content['language']
                or content['figures'] != BioReaderReportService.fixed_figures(context_content)
                or content['tables'] != context_content['tables']):
            raise invalid()
        task = self.store.require_task(db, report['task_id'])
        snapshot = task['input_snapshot']
        bindings = db.execute("""SELECT source_kind,source_id,source_sha256 FROM research_source_bindings
            WHERE report_version_id=%s AND project_id=%s AND user_id=%s""",
            (report['id'], project, self.store.user_id)).fetchall()
        if (task['task_type'] != 'research_report' or task['project_id'] != project
                or snapshot.get('report_version_id') != report['id']
                or snapshot.get('content_sha256') != report['content_sha256']
                or snapshot.get('output_language') != content['language']
                or [dict(x) for x in bindings] != [dict(source_kind='research_finding_version',
                    source_id=finding['id'], source_sha256=finding['content_sha256'])]):
            raise invalid()
        return context, context_content, finding, task

    def list(self, project, context_id, page):
        with self.store.connection() as db:
            context = self.require(db, 'bio_report_context_versions', project, context_id)
            # The direct finding binding filters before pagination, irrespective
            # of how many reports exist elsewhere in the project.
            scope = """FROM research_report_versions r WHERE r.project_id=%s AND r.user_id=%s
                AND EXISTS (SELECT 1 FROM research_source_bindings b
                    WHERE b.finding_version_id=r.finding_version_id AND b.project_id=r.project_id
                    AND b.user_id=r.user_id AND b.source_kind='bio_report_context' AND b.source_id=%s
                    AND NOT EXISTS (SELECT 1 FROM research_source_bindings other
                        WHERE other.finding_version_id=b.finding_version_id AND other.project_id=b.project_id
                        AND other.user_id=b.user_id AND other.id<>b.id))"""
            parameters = (project, self.store.user_id, context_id)
            total = db.execute('SELECT count(*) AS n ' + scope, parameters).fetchone()['n']
            rows = db.execute('SELECT r.* ' + scope + ' ORDER BY r.created_at DESC,r.id LIMIT %s OFFSET %s',
                              (*parameters, PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
            items = []
            for report in rows:
                _, _, _, task = self._bound_report(db, project, report, context)
                members = []
                if task['status'] == 'succeeded':
                    _, available = self._published(db, project, report, task)
                    members = [member for member in available if member['role'] in MEMBER_ROLES
                               and member['format'] == member['role']]
                items.append(dict(id=report['id'], task_id=task['id'], task=self.store.public_task(task), members=members))
            return dict(items=items, total=total, page=page, page_size=PAGE_SIZE)

    def _published(self, db, project, report, task):
        if task['status'] != 'succeeded' or not report['manifest_object_id']:
            raise invalid('research_source_incomplete', 422)
        if task['result_research_report_version_id'] != report['id']:
            raise invalid()
        return self.reports.checked_members(db, project, report, read_member_bytes=False)

    def resolve(self, project, report_id, roles, *, context_id=None, selection=None, language=None):
        with self.store.connection() as db:
            context = self.require(db, 'bio_report_context_versions', project, context_id) if context_id else None
            report = self.require(db, 'research_report_versions', project, report_id)
            context, content, finding, task = self._bound_report(db, project, report, context)
            if selection is not None and (selection != content['selection'] or language != content['language']):
                raise invalid()
            _, available = self._published(db, project, report, task)
            ResearchSourceReader(self.assets, allow_stale_labels=True).read_source(
                project, dict(source_kind='research_finding_version', source_id=finding['id'],
                              sha256=finding['content_sha256']), db=db)
            members = {}
            for role in roles:
                matching = [m for m in available if m['role'] == role and m['format'] == role]
                if len(matching) != 1:
                    raise invalid('research_source_not_found', 404)
                member = matching[0]
                original = self.require(db, 'research_report_members', project, member['id'])
                obj = scoped_object(db, project, self.store.user_id, original['storage_object_id'])
                members[role] = dict(metadata=member, object=obj)
            return context, content, members

"""Progress and explicit publication within the current analyst assignment."""

from collections import defaultdict

from app.adapters.research_intake_store import latest_confirmed_requirement
from app.adapters.research_results_store import invalid
from app.core.exceptions import StorageError
from app.domain.customer_workspace import confirmed_progress, read_published_deliveries
from app.domain.delivery_packages.service import DeliveryService, analysis_member_supported
from app.domain.storage_governance.guards import require_scope_open


class AnalystWorkspace:
    def __init__(self, projects):
        self.projects = projects
        self.delivery = DeliveryService(projects)

    def _assignment(self, project_id):
        assignment = self.projects.assignment
        if assignment is None or assignment.project_id != project_id:
            raise StorageError('project_not_found', '项目不存在。', 404)
        return assignment

    @staticmethod
    def _lock_requirement(db, assignment, revision):
        if revision != assignment.revision:
            raise StorageError('project_assignment_stale', '项目分配已变更，请重新读取。', 409)
        # Confirmation writes also lock this row before adding a version.
        db.execute('SELECT project_id FROM research_intakes WHERE project_id=%s FOR UPDATE',
                   (assignment.project_id,)).fetchone()
        requirement = latest_confirmed_requirement(db, assignment.project_id)
        if requirement is None:
            raise StorageError('research_revision_conflict', '项目尚无正式提交的需求。', 409)
        return requirement

    @staticmethod
    def _view(db, assignment, requirement):
        project_id, owner_id = assignment.project_id, assignment.owner_id
        progress = confirmed_progress(db, project_id, owner_id, requirement, assignment)
        feedback = defaultdict(list)
        for row in db.execute('''SELECT snapshot_id, id, message, created_at FROM customer_feedback
            WHERE project_id=%s AND user_id=%s ORDER BY created_at DESC, id''', (project_id, owner_id)):
            feedback[row['snapshot_id']].append({key: row[key] for key in ('id', 'message', 'created_at')})
        publications = [
            dict(id=row['id'], title=row['title'], published_at=row['published_at'], feedback=feedback[row['id']])
            for row in read_published_deliveries(db, project_id, owner_id, kind='analysis')
        ]
        return dict(assignment_revision=assignment.revision,
                    requirement=dict(id=requirement['id'], version=requirement['version']) if requirement else None,
                    status=progress['status'], note=progress['note'], feedback=feedback[None],
                    publications=publications)

    def read(self, project_id):
        assignment = self._assignment(project_id)
        with self.projects.connection() as db:
            return self._view(db, assignment, latest_confirmed_requirement(db, project_id))

    def update_progress(self, project_id, request):
        assignment = self._assignment(project_id)
        with self.projects.connection(write=True) as db:
            requirement = self._lock_requirement(db, assignment, request.assignment_revision)
            if request.requirement_version_id != requirement['id']:
                raise StorageError('research_revision_conflict', '客户已提交新需求，请重新读取。', 409)
            progress = confirmed_progress(db, project_id, assignment.owner_id, requirement, assignment)
            if progress['status'] == 'delivered':
                raise StorageError('research_request_conflict', '该需求已交付。', 409)
            require_scope_open(db, project_id)
            db.execute('''INSERT INTO customer_requirement_progress
                (requirement_version_id, project_id, status, note, assignment_revision)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (requirement_version_id) DO UPDATE SET status=excluded.status, note=excluded.note,
                    assignment_revision=excluded.assignment_revision, updated_at=clock_timestamp()''',
                (requirement['id'], project_id, request.status, request.note or None, assignment.revision))
            return self._view(db, assignment, requirement)

    def publish(self, project_id, request):
        assignment = self._assignment(project_id)
        with self.projects.connection(write=True) as db:
            requirement = self._lock_requirement(db, assignment, request.assignment_revision)
            frozen = db.execute('''SELECT s.delivery_id FROM delivery_snapshots s
                JOIN research_deliveries d ON d.id=s.delivery_id AND d.project_id=s.project_id
                WHERE s.id=%s AND s.project_id=%s AND s.user_id=%s AND d.kind='analysis' ''',
                (request.snapshot_id, project_id, assignment.owner_id)).fetchone()
            if frozen is None:
                raise invalid('research_source_not_found', 404)
            row = self.delivery.row(db, project_id, frozen['delivery_id'], request.snapshot_id)
            if row['requirement_version_id'] != requirement['id']:
                raise StorageError('research_revision_conflict', '交付需关联客户最新正式需求。', 409)
            snapshot = row['snapshot_json']
            if snapshot['requirement_sha256'] != requirement['sha256']:
                raise invalid()
            if any(not analysis_member_supported(member['selection']['kind'], member['format'])
                   for member in snapshot['members']):
                raise StorageError('research_source_unsupported', '请仅选择分析报告、图件或可交付的附件。', 422)

            existing = db.execute('''SELECT snapshot_id AS id, title, published_at FROM customer_delivery_publications
                WHERE snapshot_id=%s AND project_id=%s''', (row['id'], project_id)).fetchone()
            if existing:
                if existing['title'] != request.title:
                    raise StorageError('research_request_conflict', '该快照已使用其他标题发布。', 409)
                return dict(existing), 200
            require_scope_open(db, project_id, file_ids=snapshot['source_file_ids'])
            self.delivery.require_snapshot_sources(db, row)
            publication = db.execute('''INSERT INTO customer_delivery_publications (snapshot_id, project_id, delivery_id, title)
                VALUES (%s,%s,%s,%s) RETURNING snapshot_id AS id, title, published_at''',
                (row['id'], project_id, row['delivery_id'], request.title)).fetchone()
            return dict(publication), 201

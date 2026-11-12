"""Read and download the deliveries explicitly released to a project's customer."""

from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import quote
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from app.adapters.research_intake_store import latest_confirmed_requirement
from app.adapters.research_results_store import invalid
from app.auth.project_access import read_current_assignment
from app.core.exceptions import StorageError
from app.domain.delivery_packages.service import DeliveryService
from app.domain.research_results.report_package import make_package
from app.domain.storage_governance.guards import require_scope_open


_DELIVERIES = '''SELECT s.id, p.title, d.kind, s.revision, p.published_at, p.delivery_id,
        jsonb_array_length(s.snapshot_json->'members') AS member_count
    FROM customer_delivery_publications p
    JOIN delivery_snapshots s ON s.id=p.snapshot_id AND s.project_id=p.project_id AND s.delivery_id=p.delivery_id
    JOIN research_deliveries d ON d.id=p.delivery_id AND d.project_id=p.project_id
    WHERE p.project_id=%s AND s.user_id=%s'''


def read_published_deliveries(db, project_id, owner_id, *, kind=None):
    return db.execute(_DELIVERIES + ' AND (%s::text IS NULL OR d.kind=%s) ORDER BY p.published_at DESC, s.id',
                      (project_id, owner_id, kind, kind))


def confirmed_progress(db, project_id, owner_id, requirement, assignment):
    if requirement is None:
        return dict(status='draft', requirement_version=None, submitted_at=None, updated_at=None, note=None)

    published_at = db.execute('''SELECT max(p.published_at) AS published_at
        FROM customer_delivery_publications p
        JOIN delivery_snapshots s ON s.id=p.snapshot_id AND s.project_id=p.project_id
        WHERE p.project_id=%s AND s.user_id=%s AND s.requirement_version_id=%s''',
        (project_id, owner_id, requirement['id'])).fetchone()['published_at']
    submitted_at = requirement['created_at']
    result = dict(requirement_version=requirement['version'], submitted_at=submitted_at)
    if published_at:
        return dict(result, status='delivered', note=None, updated_at=published_at)

    # Revision-free rows from the customer workspace rollout apply only to
    # projects that have never had an assignment.
    progress = db.execute('''SELECT p.status, p.note, p.updated_at FROM customer_requirement_progress p
        WHERE p.project_id=%s AND p.requirement_version_id=%s AND (
            p.assignment_revision=%s::bigint OR (p.assignment_revision IS NULL AND NOT EXISTS (
                SELECT 1 FROM project_assignments a WHERE a.project_id=p.project_id
            ))
        )''', (project_id, requirement['id'], assignment.revision if assignment else None)).fetchone()
    if progress:
        return dict(result, **progress)

    assignment_time = assignment.updated_at if assignment else None
    return dict(result, status='assigned' if assignment else 'pending_assignment', note=None,
                updated_at=max(submitted_at, assignment_time or submitted_at))


class CustomerWorkspace:
    def __init__(self, projects):
        self.delivery = DeliveryService(projects)
        self.store = self.delivery.store

    def _feedback(self, db, project_id, snapshot_id):
        return [dict(row) for row in db.execute('''SELECT id, message, created_at FROM customer_feedback
            WHERE project_id=%s AND user_id=%s AND snapshot_id IS NOT DISTINCT FROM %s::text
            ORDER BY created_at DESC, id''', (project_id, self.store.user_id, snapshot_id))]

    def progress(self, project_id):
        with self.store.connection() as db:
            self.store.require_project(db, project_id, role='customer')
            requirement = latest_confirmed_requirement(db, project_id)
            assignment = read_current_assignment(db, project_id)
            progress = confirmed_progress(db, project_id, self.store.user_id, requirement, assignment)
            return dict(progress, feedback=self._feedback(db, project_id, None))

    @staticmethod
    def _summary(row):
        return {key: row[key] for key in ('id', 'title', 'kind', 'revision', 'published_at', 'member_count')}

    def deliveries(self, project_id):
        with self.store.connection() as db:
            self.store.require_project(db, project_id, role='customer')
            rows = read_published_deliveries(db, project_id, self.store.user_id)
            return {'items': [self._summary(row) for row in rows]}

    def _publication(self, db, project_id, snapshot_id):
        row = db.execute(_DELIVERIES + ' AND s.id=%s', (project_id, self.store.user_id, snapshot_id)).fetchone()
        if row is None:
            raise invalid('research_source_not_found', 404)
        return row

    def detail(self, project_id, snapshot_id):
        with self.store.connection() as db:
            self.store.require_project(db, project_id, role='customer')
            publication = self._publication(db, project_id, snapshot_id)
            row = self.delivery.row(db, project_id, publication['delivery_id'], snapshot_id)
            base = f'/api/v1/projects/{quote(project_id, safe="")}/customer-workspace/deliveries/{snapshot_id}'
            members = [dict(id=m['id'], name=PurePosixPath(m['name']).name, format=m['format'],
                            size_bytes=m['size_bytes'], download_url=f'{base}/members/{m["id"]}/download')
                       for m in row['snapshot_json']['members']]
            return dict(self._summary(publication), members=members,
                        package_url=f'{base}/download' if self.delivery.ready_package(db, row) else None,
                        feedback=self._feedback(db, project_id, snapshot_id))

    def member(self, project_id, snapshot_id, member_id):
        with self.store.connection() as db:
            self.store.require_project(db, project_id, role='customer')
            publication = self._publication(db, project_id, snapshot_id)
            row = self.delivery.row(db, project_id, publication['delivery_id'], snapshot_id)
            member, raw = self.delivery.member_bytes(db, row, member_id)
            return dict(filename=PurePosixPath(member['name']).name, sha256=member['sha256']), raw

    def package(self, project_id, snapshot_id):
        with self.store.connection() as db:
            self.store.require_project(db, project_id, role='customer')
            publication = self._publication(db, project_id, snapshot_id)
            row = self.delivery.row(db, project_id, publication['delivery_id'], snapshot_id)
            metadata, stored = self.delivery.package_bytes(db, row)

        # The existing archive includes internal source and change metadata.
        # Export just the explicitly released member bytes and their hashes.
        files = {}
        try:
            with ZipFile(BytesIO(stored)) as archive:
                for member in row['snapshot_json']['members']:
                    name = PurePosixPath(member['name']).name
                    raw = archive.read(member['name'])
                    if name in files or len(raw) != member['size_bytes'] or sha256(raw).hexdigest() != member['sha256']:
                        raise invalid()
                    files[name] = raw
            del stored
            public, _ = make_package(files, {'kind': 'delivery', 'snapshot_id': snapshot_id})
        except (BadZipFile, KeyError, ValueError) as exc:
            raise invalid('research_output_invalid') from exc
        return dict(filename=metadata['filename'], sha256=sha256(public).hexdigest()), public

    def submit_feedback(self, project_id, request, key):
        with self.store.connection(write=True) as db:
            self.store.require_project(db, project_id, role='customer')
            if request.snapshot_id is not None:
                self._publication(db, project_id, request.snapshot_id)
            existing = db.execute('''SELECT id, message, created_at, snapshot_id FROM customer_feedback
                WHERE project_id=%s AND user_id=%s AND request_key=%s''',
                (project_id, self.store.user_id, key)).fetchone()
            if existing:
                if existing['message'] != request.message or existing['snapshot_id'] != request.snapshot_id:
                    raise StorageError('research_request_conflict', '相同请求键已用于不同内容。', 409)
                return {field: existing[field] for field in ('id', 'message', 'created_at')}, 200
            require_scope_open(db, project_id)
            row = db.execute('''INSERT INTO customer_feedback (id, project_id, user_id, snapshot_id, message, request_key)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, message, created_at''',
                (str(uuid4()), project_id, self.store.user_id, request.snapshot_id, request.message, key)).fetchone()
            return dict(row), 201

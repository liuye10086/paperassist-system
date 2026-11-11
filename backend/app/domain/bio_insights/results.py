"""Read complete published tables and formal members without numeric imports."""
import csv
import io
import json

from app.adapters.bio_insights_store import BioInsightsStore,invalid
from app.adapters.bio_analysis_store import scoped_object


def checked_members(service,db,project,row,*,resource=False,progress=None):
    if service.store.require_task(db,row['task_id'])['status']!='succeeded' or not row['manifest_object_id']:
        raise invalid('bio_insight_source_incomplete',422)
    obj=scoped_object(db,project,service.store.user_id,row['manifest_object_id'])
    if obj['sha256']!=row['manifest_sha256']:raise invalid()
    content=service.objects.read(obj)
    if len(content)>4194304:raise invalid('bio_insight_limit_exceeded',422)
    manifest=json.loads(content)
    table='bio_resource_members' if resource else 'bio_insight_result_members'
    column='resource_version_id' if resource else 'result_version_id'
    rows=db.execute('SELECT * FROM '+table+' WHERE '+column+'=%s AND project_id=%s AND user_id=%s ORDER BY key',
                    (row['id'],project,service.store.user_id)).fetchall()
    formal=list(rows)
    expected={m['key']:m for m in manifest['members']}
    if set(expected)!={m['key'] for m in formal}:raise invalid()
    members=[]
    for member in rows:
        if progress:progress()
        stored=scoped_object(db,project,service.store.user_id,member['storage_object_id'])
        if any(member[key]!=stored[key] for key in ('size_bytes','sha256')):raise invalid()
        if any(member[key]!=expected[member['key']][key] for key in ('key','role','format','sha256','size_bytes')):raise invalid()
        from pathlib import Path
        from .sources import InsightSourceReader
        from app.domain.storage_governance.service import _key
        path=Path(service.assets.directory)/stored['object_key']
        _key(service.assets.directory,path)
        InsightSourceReader._verify(path,stored,progress)
        members.append({**dict(member),'object_key':stored['object_key']})
    if resource:
        initial=next((m for m in members if m['role']=='input_snapshot'),None)
        if not initial or manifest.get('input_snapshot_sha256')!=initial['sha256']:raise invalid()
    return manifest,members


class BioInsightResultService(BioInsightsStore):
    def get(self,project,identifier):
        with self.store.connection() as db:
            row=self.require(db,'bio_insight_result_versions',project,identifier)
            manifest,members=checked_members(self,db,project,row)
            task=self.store.require_task(db,row['task_id'])
            from .service import BioInsightsService
            BioInsightsService(self.assets).require_sources(db,task,runtime=False)
            return dict(id=row['id'],run_id=row['run_id'],plan_version_id=row['plan_version_id'],kind=row['kind'],
                provenance=row['provenance'],inference_scope=row['inference_scope'],summary=row['summary_json'],methods=row['methods_json'],
                manifest_sha256=row['manifest_sha256'],manifest=manifest,task_id=row['task_id'],task=self.store.public_task(task),
                members=[self.public_member(project,identifier,m) for m in members])

    @staticmethod
    def public_member(project,identifier,member,resource=False):
        prefix='bio-resources' if resource else 'bio-insight-results'
        return {key:member[key] for key in ('id','key','role','format','sha256','size_bytes')}|dict(shape=member['shape_json'],
            download_url=f'/api/v1/projects/{project}/{prefix}/{identifier}/members/{member["id"]}/download')

    def member(self,project,identifier,member_id,*,resource=False):
        with self.store.connection() as db:
            table='bio_resource_versions' if resource else 'bio_insight_result_versions'
            row=self.require(db,table,project,identifier)
            from .service import BioInsightsService
            BioInsightsService(self.assets).require_sources(db,self.store.require_task(db,row['task_id']),runtime=False)
            _,members=checked_members(self,db,project,row,resource=resource)
            member=next((m for m in members if m['id']==member_id and m['role']!='input_snapshot'),None)
            if not member:raise invalid('bio_insight_not_found',404)
            if member['role']=='original_resource':
                file=db.execute('SELECT * FROM files WHERE id=%s AND project_id=%s AND uploader_id=%s',
                    (member['original_file_id'],project,self.store.user_id)).fetchone()
                if not file or file['sha256']!=member['sha256'] or file['size_bytes']!=member['size_bytes']:raise invalid()
                return member,self.assets.original(dict(file))
            return member,self.objects.read(member)

    def table(self,project,identifier,key,page=1,page_size=50,search=None):
        from .sources import InsightSourceReader
        with self.store.connection() as db:
            row=self.require(db,'bio_insight_result_versions',project,identifier)
            from .service import BioInsightsService
            BioInsightsService(self.assets).require_sources(db,self.store.require_task(db,row['task_id']),runtime=False)
            _,members=checked_members(self,db,project,row)
            member=next((m for m in members if m['key']==key and m['format'] in ('csv','tsv')),None)
            if not member:raise invalid('bio_insight_not_found',404)
            path=self.objects.path(member['object_key'])
            InsightSourceReader._verify(path,member)
            selected=[];total=matched=0;columns=[]
            with path.open('r',encoding='utf-8-sig',newline='') as stream:
                reader=csv.DictReader(stream,delimiter='\t' if member['format']=='tsv' else ',',strict=True)
                columns=reader.fieldnames or []
                for item in reader:
                    total+=1
                    if None in item:raise invalid()
                    if search and not any(search.casefold() in value.casefold() for value in item.values() if value is not None):continue
                    if (page-1)*page_size<=matched<page*page_size:selected.append(item)
                    matched+=1
            return dict(key=key,columns=columns,items=selected,total=total,matched_total=matched,page=page,page_size=page_size,
                sha256=member['sha256'],raw_text_values=True,provenance=row['provenance'],inference_scope=row['inference_scope'])

    def bulk_comparisons(self, project, identifier, *, contrast_id, subset, q_column, q_threshold,
                         minimum_absolute_effect, page, page_size, search):
        from .bulk_results import bulk_comparison_page, bulk_contrast_labels, is_reviewed_bulk
        from .contracts import BulkSelection
        from .service import BioInsightsService

        with self.store.connection() as db:
            row = self.require(db, 'bio_insight_result_versions', project, identifier)
            plan = self.require(db, 'bio_insight_plan_versions', project, row['plan_version_id'])
            metadata = {'kind': row['kind'], 'plan_config': plan['config_json']}
            if not is_reviewed_bulk(metadata):
                raise invalid('bio_insight_source_unsupported', 422)
            try:
                contrasts = bulk_contrast_labels(metadata)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise invalid() from exc
            selected = next(iter(contrasts)) if contrast_id is None else contrast_id
            if selected not in contrasts:
                raise invalid('bio_insight_not_found', 404)

            task = self.store.require_task(db, row['task_id'])
            BioInsightsService(self.assets).require_sources(db, task, runtime=False)
            _, members = checked_members(self, db, project, row)
            member = next((item for item in members if item['key'] == 'comparison_results'
                           and item['role'] == 'table' and item['format'] == 'tsv'), None)
            if member is None:
                raise invalid('bio_insight_source_incomplete', 422)
            selection = BulkSelection(contrast_id=selected, q_column=q_column, q_threshold=q_threshold,
                                      minimum_absolute_effect=minimum_absolute_effect)
            path = self.objects.path(member['object_key'])
            try:
                result = bulk_comparison_page(path, contrasts, selection, subset=subset, page=page,
                                              page_size=page_size, search=search)
            except (csv.Error, OSError, ValueError) as exc:
                raise invalid() from exc
            return dict(result, sha256=member['sha256'], raw_text_values=True, subset=subset,
                        q_column=q_column, q_threshold=q_threshold, minimum_absolute_effect=minimum_absolute_effect,
                        provenance=row['provenance'], inference_scope=row['inference_scope'])

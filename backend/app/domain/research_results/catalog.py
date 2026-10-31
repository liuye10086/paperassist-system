"""Bounded identity browsing and request recovery; never scans matrices."""
from app.adapters.research_results_store import ResearchResultsStore,invalid
from app.db.research_results_schema import SOURCE_TARGETS


class ResearchCatalog(ResearchResultsStore):
    def list(self,project,kind,page=1):
        if kind not in SOURCE_TARGETS:raise invalid('research_source_unsupported',422)
        table=SOURCE_TARGETS[kind][1]
        title={'original_file':'s.filename','bio_analysis_artifact':'s.key',
            'bio_insight_result_member':'s.key','bio_insight_result_version':"s.kind||' / '||s.id",
            'bio_figure_version':"COALESCE(NULLIF(s.config_json->>'title',''),s.config_json->>'kind',s.id)",
            'research_figure_version':"COALESCE(NULLIF(s.config_json->>'title',''),s.id)",
            'research_finding_version':"COALESCE(NULLIF(s.content_json->>'title',''),s.id)",
            'research_report_version':"COALESCE(NULLIF(s.content_json->>'title',''),s.id)"}.get(kind,'s.id')
        moment='uploaded_at' if kind=='original_file' else 'created_at'
        sha='sha256' if kind in ('original_file','bio_analysis_artifact','external_evidence_version','bio_insight_result_member') else 'content_sha256' if kind in ('research_finding_version','research_report_version') else 'manifest_sha256'
        # Objects without complete formal output remain visible as unavailable.
        join='';extra='';status="'available'"
        if kind=='bio_insight_result_member':
            join=' JOIN bio_insight_result_versions result ON result.id=s.result_version_id AND result.project_id=s.project_id JOIN tasks t ON t.id=result.task_id AND t.project_id=s.project_id'
            status='t.status';extra+=',s.result_version_id,s.key,s.role,s.format'
        elif kind in ('bio_processed_dataset_version','bio_figure_version','research_figure_version','research_report_version','bio_insight_result_version'):
            join=' JOIN tasks t ON t.id=s.task_id AND t.project_id=s.project_id'
            status='t.status'
        elif kind=='original_file':status='s.parse_status'
        if kind in ('bio_processed_dataset_version','bio_figure_version'):
            processed='s'
            if kind=='bio_figure_version':
                join+=' JOIN bio_processed_dataset_versions p ON p.id=s.processed_dataset_version_id AND p.project_id=s.project_id'
                processed='p'
                extra+=",s.config_json->>'kind' AS kind,s.config_json->>'panel' AS panel,s.version,s.processed_dataset_version_id"
            join+=' JOIN bio_dataset_versions raw ON raw.id='+processed+'.raw_dataset_version_id AND raw.project_id=s.project_id'
            join+=' JOIN bio_datasets d ON d.id=raw.dataset_id AND d.project_id=s.project_id'
            join+=' JOIN bio_analysis_recipe_versions recipe ON recipe.id='+processed+'.recipe_version_id AND recipe.project_id=s.project_id'
            extra+=',d.name AS dataset_name,raw.version AS raw_version,recipe.version AS recipe_version'
            if kind=='bio_processed_dataset_version':title='d.name'
        elif kind in ('research_figure_version','research_finding_version','research_report_version'):
            extra+=',s.revision'
        with self.store.connection() as db:
            self.store.require_project(db,project)
            total=db.execute('SELECT count(*) AS n FROM '+table+' WHERE project_id=%s',(project,)).fetchone()['n']
            rows=db.execute('SELECT s.id AS source_id,'+title+' AS title,s.'+moment+' AS created_at,s.'+sha+' AS sha256,'+status+' AS status'+extra+' FROM '+table+' s'+join+' WHERE s.project_id=%s ORDER BY s.'+moment+' DESC,s.id LIMIT 25 OFFSET %s',(project,(page-1)*25)).fetchall()
            return dict(items=[dict(source_kind=kind,**dict(r)) for r in rows],total=total,page=page,page_size=25)

    def request(self,project,kind,key):
        table={'finding':'research_finding_versions','figure':'research_figure_versions',
               'report':'research_report_versions','candidate':'research_manuscript_candidates'}.get(kind)
        if not table:raise invalid('research_source_unsupported',422)
        with self.store.connection() as db:
            self.store.require_project(db,project)
            row=db.execute('SELECT * FROM '+table+' WHERE project_id=%s AND user_id=%s AND request_key=%s',
                (project,self.store.user_id,key)).fetchone()
            if not row:raise invalid('research_source_not_found',404)
            result={k:row[k] for k in ('id','set_id','root_id','revision','task_id') if k in row}
            result.update(kind=kind,request_digest=row['request_digest'])
            if row.get('task_id'):result['task']=self.store.public_task(self.store.require_task(db,row['task_id']))
            return result

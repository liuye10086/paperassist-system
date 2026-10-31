"""CR-B03 owner scoped, typed and versioned research result foundations."""
import hashlib
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

TABLE_NAMES = ('research_finding_sets','research_finding_versions','research_figure_versions',
               'research_figure_members','research_report_versions','research_report_members',
               'research_source_bindings','manuscript_research_sources','research_manuscript_candidates')
IMMUTABLE = ('research_finding_versions','research_figure_members','research_report_members',
             'research_source_bindings','manuscript_research_sources')
SOURCE_TARGETS = {
    'bio_processed_dataset_version': ('processed_version_id','bio_processed_dataset_versions'),
    'bio_analysis_artifact': ('analysis_artifact_id','bio_analysis_artifacts'),
    'bio_figure_version': ('bio_figure_version_id','bio_figure_versions'),
    'original_file': ('file_id','files'),
    'external_evidence_version': ('external_evidence_version_id','external_evidence_versions'),
    'research_finding_version': ('source_finding_version_id','research_finding_versions'),
    'research_figure_version': ('research_figure_version_id','research_figure_versions'),
    'research_report_version': ('source_report_version_id','research_report_versions'),
    'bio_insight_result_version': ('bio_insight_result_version_id','bio_insight_result_versions'),
    'bio_insight_result_member': ('bio_insight_result_member_id','bio_insight_result_members'),
}


def define_research_results_tables(metadata):
    tables=[]
    serial=[0]
    def text(name,nullable=False):
        return sa.Column(name,sa.Text,nullable=nullable)
    def integer(name,default=None,nullable=False):
        return sa.Column(name,sa.Integer,nullable=nullable,server_default=str(default) if default is not None else None)
    def check(expression):
        return sa.CheckConstraint(expression,name='b03_ck_'+hashlib.sha256(expression.encode()).hexdigest()[:16])
    def fk(cols,target,targets=None,**kw):
        serial[0]+=1
        return sa.ForeignKeyConstraint(cols,[target+'.'+c for c in (targets or ['id','project_id'])],
                                       name='b03_scope_fk_'+str(serial[0]),**kw)
    def ref(col,target,**kw):
        return fk([col,'project_id'],target,**kw)
    def obj(col):
        return fk([col,'project_id'],'storage_references',['object_id','project_id'])
    def bounded_json(name,nullable=False):
        return [sa.Column(name,JSONB(none_as_null=True),nullable=nullable),
                check(f"{name} IS NULL OR (jsonb_typeof({name})='object' AND octet_length({name}::text)<=4194304)" if nullable
                      else f"jsonb_typeof({name})='object' AND octet_length({name}::text)<=4194304")]
    def request():
        return [text('request_key'),text('request_digest'),
                sa.UniqueConstraint('project_id','user_id','request_key'),
                check("request_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$'")]
    def make(name,*extra):
        table=sa.Table(name,metadata,sa.Column('id',sa.Text,primary_key=True),text('project_id'),text('user_id'),
            sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),integer('schema_version',1),
            sa.UniqueConstraint('id','project_id'),sa.UniqueConstraint('id','project_id','user_id'),
            fk(['project_id','user_id'],'projects',['id','owner_id']),check('schema_version=1'),*extra)
        sa.Index(name+'_project_created',table.c.project_id,table.c.created_at.desc(),table.c.id)
        tables.append(table)
        return table
    def version_lineage(root_col,name):
        return [text(root_col),integer('revision'),text('parent_id',True),
                sa.UniqueConstraint(root_col,'revision'),sa.UniqueConstraint('id',root_col,'project_id'),
                fk(['parent_id',root_col,'project_id'],name,['id',root_col,'project_id']),
                check("revision>=1 AND ((revision=1 AND parent_id IS NULL) OR (revision>1 AND parent_id IS NOT NULL))")]
    def task_result(name):
        return [text('task_id'),fk(['task_id','project_id','user_id'],'tasks',['id','project_id','user_id']),sa.UniqueConstraint('task_id'),
                sa.UniqueConstraint('id','task_id','project_id')]
    def source_fields():
        items=[text('source_kind'),text('source_id')]
        for col,target in SOURCE_TARGETS.values():
            constraint = (sa.ForeignKeyConstraint([col,'project_id'],[target+'.id',target+'.project_id'],
                          name='b04_research_'+col+'_fk') if col.startswith('bio_insight_') else ref(col,target))
            items.extend([text(col,True),constraint])
        cols=','.join(col for col,_ in SOURCE_TARGETS.values())
        choices=' OR '.join(f"(source_kind='{kind}' AND {col} IS NOT NULL AND source_id={col})"
                            for kind,(col,_) in SOURCE_TARGETS.items())
        items.append(check(f'num_nonnulls({cols})=1 AND ({choices})'))
        return items

    # This existing table lacked a project-scoped unique target; add no data.
    sa.UniqueConstraint(metadata.tables['external_evidence_versions'].c.id,
                        metadata.tables['external_evidence_versions'].c.project_id,name='b03_evidence_project_key')

    roots=make('research_finding_sets',text('title'),integer('revision',1),text('current_version_id',True),
               sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
               fk(['current_version_id','id','project_id'],'research_finding_versions',['id','set_id','project_id'],use_alter=True),
               check('revision>=1 AND length(title) BETWEEN 1 AND 200 AND updated_at>=created_at'))
    make('research_finding_versions',*version_lineage('set_id','research_finding_versions'),
         ref('set_id','research_finding_sets'),text('requirement_version_id',True),text('design_version_id',True),
         ref('requirement_version_id','research_requirement_versions'),ref('design_version_id','research_design_versions'),
         *bounded_json('content_json'),text('content_sha256'),*request(),check("content_sha256 ~ '^[0-9a-f]{64}$'"))
    make('research_figure_versions',*version_lineage('root_id','research_figure_versions'),*task_result('figure'),
         ref('root_id','research_figure_versions'),check('revision<>1 OR root_id=id'),
         *bounded_json('config_json'),text('config_sha256'),text('manifest_object_id',True),text('manifest_sha256',True),
         obj('manifest_object_id'),*request(),
         check("config_sha256 ~ '^[0-9a-f]{64}$' AND ((manifest_object_id IS NULL AND manifest_sha256 IS NULL) OR (manifest_object_id IS NOT NULL AND manifest_sha256 IS NOT NULL AND manifest_sha256 ~ '^[0-9a-f]{64}$'))"))
    make('research_report_versions',*version_lineage('root_id','research_report_versions'),*task_result('report'),
         ref('root_id','research_report_versions'),check('revision<>1 OR root_id=id'),
         text('finding_version_id'),ref('finding_version_id','research_finding_versions'),text('language'),
         *bounded_json('content_json'),text('content_sha256'),text('manifest_object_id',True),text('manifest_sha256',True),
         obj('manifest_object_id'),*request(),
         check("language IN ('zh-CN','en') AND content_sha256 ~ '^[0-9a-f]{64}$' AND ((manifest_object_id IS NULL AND manifest_sha256 IS NULL) OR (manifest_object_id IS NOT NULL AND manifest_sha256 IS NOT NULL AND manifest_sha256 ~ '^[0-9a-f]{64}$'))"))
    for table,parent,col in [('research_figure_members','research_figure_versions','figure_version_id'),
                             ('research_report_members','research_report_versions','report_version_id')]:
        make(table,text(col),ref(col,parent),text('key'),text('role'),text('format'),text('storage_object_id'),
             obj('storage_object_id'),text('sha256'),sa.Column('size_bytes',sa.BigInteger,nullable=False),
             *bounded_json('properties_json'),sa.UniqueConstraint(col,'key'),
             sa.UniqueConstraint('id',col,'project_id'),
             check("size_bytes>=0 AND sha256 ~ '^[0-9a-f]{64}$' AND key ~ '^[A-Za-z0-9_-]{1,100}$' AND length(role) BETWEEN 1 AND 100 AND length(format) BETWEEN 1 AND 20"))
    make('research_source_bindings',text('parent_kind'),text('finding_version_id',True),
         text('figure_version_id',True),text('report_version_id',True),
         ref('finding_version_id','research_finding_versions'),ref('figure_version_id','research_figure_versions'),
         ref('report_version_id','research_report_versions'),*source_fields(),
         *bounded_json('locator_json'),text('source_sha256'),text('role'),
         check("source_sha256 ~ '^[0-9a-f]{64}$' AND length(role) BETWEEN 1 AND 100"),
         check("num_nonnulls(finding_version_id,figure_version_id,report_version_id)=1 AND ((parent_kind='finding' AND finding_version_id IS NOT NULL) OR (parent_kind='figure' AND figure_version_id IS NOT NULL) OR (parent_kind='report' AND report_version_id IS NOT NULL))"))
    make('manuscript_research_sources',text('version_id'),
         fk(['version_id','project_id','user_id'],'manuscript_versions',['id','project_id','user_id']),
         *source_fields(),text('role'),*bounded_json('source_json'),text('sha256'),
         sa.UniqueConstraint('version_id','source_kind','source_id'),
         check("sha256 ~ '^[0-9a-f]{64}$' AND role IN ('methods','user_results','image_observation','computed_results')"))
    make('research_manuscript_candidates',text('delivery_id'),ref('delivery_id','research_deliveries'),
         text('manuscript_id',True),text('base_version_id',True),integer('expected_revision'),
         fk(['manuscript_id','project_id','user_id','delivery_id'],'manuscripts',['id','project_id','user_id','delivery_id']),
         fk(['base_version_id','manuscript_id','project_id','user_id','expected_revision'],'manuscript_versions',
            ['id','manuscript_id','project_id','user_id','revision']),
         *task_result('candidate'),*bounded_json('scope_json'),*bounded_json('candidate_json',True),
         text('candidate_sha256',True),text('published_version_id',True),text('publish_key',True),*request(),
         fk(['published_version_id','project_id','user_id'],'manuscript_versions',['id','project_id','user_id']),
         sa.UniqueConstraint('project_id','user_id','publish_key'),sa.UniqueConstraint('published_version_id'),
         check("((manuscript_id IS NULL AND base_version_id IS NULL AND expected_revision=0) OR (manuscript_id IS NOT NULL AND base_version_id IS NOT NULL AND expected_revision>=1)) AND ((candidate_json IS NULL AND candidate_sha256 IS NULL) OR (candidate_json IS NOT NULL AND candidate_sha256 IS NOT NULL AND candidate_sha256 ~ '^[0-9a-f]{64}$')) AND ((published_version_id IS NULL AND publish_key IS NULL) OR (published_version_id IS NOT NULL AND publish_key IS NOT NULL AND publish_key ~ '^[!-~]{1,128}$' AND candidate_json IS NOT NULL))"))
    for table in tables:
        for col in table.c:
            if col.name.endswith('_id') and col.name not in ('id','project_id','user_id'):
                sa.Index(table.name+'_'+col.name,col)
    return tuple(tables)

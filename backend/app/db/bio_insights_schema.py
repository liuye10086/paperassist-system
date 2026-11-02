"""CR-B04 owner scoped immutable resources, plans and published insights."""
import hashlib
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

TABLE_NAMES = ('bio_resource_versions', 'bio_resource_members', 'bio_insight_plans',
               'bio_insight_plan_versions', 'bio_insight_plan_sources', 'bio_insight_runs',
               'bio_insight_result_versions', 'bio_insight_result_members')
IMMUTABLE = ('bio_resource_members', 'bio_insight_plan_versions', 'bio_insight_plan_sources',
             'bio_insight_result_versions', 'bio_insight_result_members')
KINDS = "'comparison','result_import','ora','gsea_prerank','candidate','figure','feature_extract','integration'"
TASK_TYPES = ('bio_resource_import', 'bio_comparison', 'bio_result_import',
              'bio_enrichment', 'bio_candidate', 'bio_insight_figure','bio_feature_extract','bio_integration')
SOURCE_TARGETS = {
    'bio_processed_dataset_version': ('processed_version_id', 'bio_processed_dataset_versions'),
    'bio_observation_map_version': ('observation_map_version_id', 'bio_observation_map_versions'),
    'bio_annotation_version': ('annotation_version_id', 'bio_annotation_versions'),
    'research_design_version': ('design_version_id', 'research_design_versions'),
    'bio_resource_version': ('resource_version_id', 'bio_resource_versions'),
    'bio_insight_result_version': ('source_result_version_id', 'bio_insight_result_versions'),
    'original_file': ('file_id', 'files'),
    'external_evidence_version': ('external_evidence_version_id', 'external_evidence_versions'),
}


def define_bio_insights_tables(metadata):
    tables = []
    serial = [0]
    def text(name, nullable=False):
        return sa.Column(name, sa.Text, nullable=nullable)
    def integer(name, default=None):
        return sa.Column(name, sa.Integer, nullable=False, server_default=str(default) if default is not None else None)
    def check(expression):
        return sa.CheckConstraint(expression, name='b04_ck_' + hashlib.sha256(expression.encode()).hexdigest()[:16])
    def fk(cols, target, targets=None, **kw):
        serial[0] += 1
        return sa.ForeignKeyConstraint(cols, [target + '.' + c for c in (targets or ['id', 'project_id'])],
                                       name='b04_scope_fk_' + str(serial[0]), **kw)
    def ref(col, target, **kw):
        return fk([col, 'project_id'], target, **kw)
    def obj(col):
        return fk([col, 'project_id'], 'storage_references', ['object_id', 'project_id'])
    def json(name):
        return [sa.Column(name, JSONB(none_as_null=True), nullable=False),
                check(f"jsonb_typeof({name})='object' AND octet_length({name}::text)<=4194304")]
    def request():
        return [text('request_key'), text('request_digest'), sa.UniqueConstraint('project_id', 'user_id', 'request_key'),
                check("request_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$'")]
    def task():
        return [text('task_id'), text('task_type'),
                fk(['task_id','project_id','user_id','task_type'], 'tasks', ['id','project_id','user_id','task_type']),
                sa.UniqueConstraint('task_id'), sa.UniqueConstraint('id', 'task_id', 'project_id')]
    def make(name, *items):
        table = sa.Table(name, metadata, sa.Column('id', sa.Text, primary_key=True), text('project_id'), text('user_id'),
                        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), integer('schema_version', 1),
                        sa.UniqueConstraint('id', 'project_id'), sa.UniqueConstraint('id','project_id','user_id'),
                        fk(['project_id','user_id'], 'projects', ['id','owner_id']), check('schema_version=1'), *items)
        sa.Index(name+'_project_created', table.c.project_id, table.c.created_at.desc(), table.c.id)
        tables.append(table)
        return table
    def lineage(root, table):
        return [text(root), integer('version'), text('parent_id', True),
                sa.UniqueConstraint(root, 'version', 'project_id'), sa.UniqueConstraint('id',root,'project_id'),
                fk(['parent_id',root,'project_id'], table, ['id',root,'project_id']),
                check('version>=1 AND ((version=1 AND parent_id IS NULL) OR (version>1 AND parent_id IS NOT NULL))')]
    def manifest(nullable=False):
        return [text('manifest_object_id', nullable), text('manifest_sha256', nullable), obj('manifest_object_id'),
                check("(manifest_object_id IS NULL AND manifest_sha256 IS NULL) OR (manifest_object_id IS NOT NULL AND manifest_sha256 IS NOT NULL AND manifest_sha256 ~ '^[0-9a-f]{64}$')")]
    def member(name, col, parent, *extra):
        return make(name, text(col), ref(col, parent), text('key'), text('role'), text('format'),
                    text('storage_object_id'), obj('storage_object_id'), sa.Column('size_bytes',sa.BigInteger,nullable=False),
                    text('sha256'), *json('shape_json'), sa.UniqueConstraint(col,'key'),
                    sa.UniqueConstraint('id',col,'project_id'),
                    check("size_bytes>=0 AND sha256 ~ '^[0-9a-f]{64}$' AND key ~ '^[A-Za-z0-9_-]{1,100}$' AND length(role) BETWEEN 1 AND 100 AND length(format) BETWEEN 1 AND 20"), *extra)

    sa.UniqueConstraint(metadata.tables['tasks'].c.id, metadata.tables['tasks'].c.project_id,
                        metadata.tables['tasks'].c.user_id, metadata.tables['tasks'].c.task_type, name='b04_task_typed_scope_key')
    make('bio_resource_versions', *lineage('root_id','bio_resource_versions'), ref('root_id','bio_resource_versions'),
         check('version<>1 OR root_id=id'), text('kind'), text('title'), integer('species_taxon_id'), text('namespace'), text('release'),
         *json('source_json'), *json('usage_json'), *json('config_json'), text('config_sha256'), *task(),
         *manifest(True), *request(),
         check("kind IN ('gene_sets','id_mapping','feature_annotation','sequence','structure','sample_correspondence','object_correspondence') AND task_type='bio_resource_import' AND species_taxon_id>0 AND length(title) BETWEEN 1 AND 200 AND length(namespace) BETWEEN 1 AND 200 AND length(release) BETWEEN 1 AND 200 AND config_sha256 ~ '^[0-9a-f]{64}$'"))
    member('bio_resource_members','resource_version_id','bio_resource_versions', text('original_file_id',True),
           text('parse_version_id',True), ref('original_file_id','files'),
           fk(['parse_version_id','original_file_id'], 'file_parse_results',['id','file_id']),
           check('parse_version_id IS NULL OR original_file_id IS NOT NULL'))
    make('bio_insight_plans',text('kind'),text('name'),integer('revision',1),text('current_version_id',True),
         sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
         sa.UniqueConstraint('id','kind','project_id','user_id'),
         fk(['current_version_id','id','kind','project_id','user_id'],'bio_insight_plan_versions',
            ['id','plan_id','kind','project_id','user_id'],use_alter=True),
         check(f"kind IN ({KINDS}) AND revision>=1 AND length(name) BETWEEN 1 AND 200 AND updated_at>=created_at"))
    make('bio_insight_plan_versions',*lineage('plan_id','bio_insight_plan_versions'),text('kind'),text('decision'),
         *json('config_json'),text('config_sha256'),*json('design_checks_json'),text('confirmed_by',True),
         sa.Column('sources_transaction_id',sa.Text,nullable=False,server_default=sa.text('pg_current_xact_id()::text')),
         sa.Column('confirmed_at',sa.DateTime(timezone=True)),*request(),
         fk(['plan_id','kind','project_id','user_id'],'bio_insight_plans',['id','kind','project_id','user_id']),
         sa.UniqueConstraint('id','plan_id','kind','project_id','user_id'),
         sa.UniqueConstraint('id','kind','decision','project_id','user_id'),
         check(f"kind IN ({KINDS}) AND config_sha256 ~ '^[0-9a-f]{{64}}$' AND ((decision='draft' AND confirmed_by IS NULL AND confirmed_at IS NULL) OR (decision='confirmed' AND confirmed_by=user_id AND confirmed_at IS NOT NULL AND confirmed_at>=created_at))"))
    source_items = []
    for col, target in SOURCE_TARGETS.values():
        constraint=sa.ForeignKeyConstraint([col,'project_id'],[target+'.id',target+'.project_id'],name='b05_evidence_project_fk') if col=='external_evidence_version_id' else ref(col,target)
        source_items.extend([text(col,True),constraint])
    source_columns = ','.join(col for col,_ in SOURCE_TARGETS.values())
    source_choices = ' OR '.join(f"(source_kind='{kind}' AND {col} IS NOT NULL AND source_id={col})" for kind,(col,_) in SOURCE_TARGETS.items())
    make('bio_insight_plan_sources',text('plan_version_id'),ref('plan_version_id','bio_insight_plan_versions'),
         text('source_kind'),text('source_id'),text('role'),integer('ordinal'),text('source_sha256'),*json('locator_json'),
         *source_items,text('parse_version_id',True),
         fk(['parse_version_id','file_id'],'file_parse_results',['id','file_id']),
         sa.UniqueConstraint('plan_version_id','ordinal'),
         check(f'num_nonnulls({source_columns})=1 AND ({source_choices})'),
         check("ordinal>=0 AND ordinal<100 AND length(role) BETWEEN 1 AND 100 AND source_sha256 ~ '^[0-9a-f]{64}$' AND (parse_version_id IS NULL OR source_kind='original_file')"))
    kind_task = "((kind='comparison' AND task_type='bio_comparison') OR (kind='result_import' AND task_type='bio_result_import') OR (kind IN ('ora','gsea_prerank') AND task_type='bio_enrichment') OR (kind='candidate' AND task_type='bio_candidate') OR (kind='figure' AND task_type='bio_insight_figure') OR (kind='feature_extract' AND task_type='bio_feature_extract') OR (kind='integration' AND task_type='bio_integration'))"
    make('bio_insight_runs',text('plan_version_id'),text('kind'),text('decision'),*task(),text('source_digest'),
         text('execution_snapshot_object_id'),obj('execution_snapshot_object_id'),text('execution_snapshot_sha256'),
         integer('expected_plan_revision'),text('result_version_id',True),*request(),
         fk(['plan_version_id','kind','decision','project_id','user_id'],'bio_insight_plan_versions',['id','kind','decision','project_id','user_id']),
         sa.UniqueConstraint('id','task_id','plan_version_id','kind','project_id','user_id'),
         fk(['result_version_id','id','task_id','plan_version_id','kind','project_id','user_id'], 'bio_insight_result_versions',
            ['id','run_id','task_id','plan_version_id','kind','project_id','user_id'],use_alter=True),
         check("decision='confirmed' AND expected_plan_revision>=1 AND source_digest ~ '^[0-9a-f]{64}$' AND execution_snapshot_sha256 ~ '^[0-9a-f]{64}$' AND "+kind_task))
    make('bio_insight_result_versions',text('run_id'),text('task_id'),text('plan_version_id'),text('kind'),text('provenance'),
         text('inference_scope'),*manifest(),*json('summary_json'),*json('methods_json'),text('environment_digest'),text('code_digest'),
         fk(['run_id','task_id','plan_version_id','kind','project_id','user_id'],'bio_insight_runs',['id','task_id','plan_version_id','kind','project_id','user_id']),
         sa.UniqueConstraint('run_id'),sa.UniqueConstraint('task_id'),sa.UniqueConstraint('id','task_id','project_id'),
         sa.UniqueConstraint('id','run_id','task_id','plan_version_id','kind','project_id','user_id'),
         check(f"kind IN ({KINDS}) AND provenance IN ('system_computed','external_result') AND inference_scope IN ('spot_exploratory','donor_inference','sample_inference','sample_exploratory','external_result','derived','visualization') AND (kind<>'result_import' OR (provenance='external_result' AND inference_scope='external_result')) AND (kind<>'comparison' OR (provenance='system_computed' AND inference_scope IN ('spot_exploratory','donor_inference','sample_inference','sample_exploratory'))) AND environment_digest ~ '^[0-9a-f]{{64}}$' AND code_digest ~ '^[0-9a-f]{{64}}$'"))
    member('bio_insight_result_members','result_version_id','bio_insight_result_versions')
    for table in tables:
        for col in table.c:
            if col.name.endswith('_id') and col.name not in ('id','project_id','user_id','sources_transaction_id'):
                sa.Index(table.name+'_'+col.name,col)
    return tuple(tables)

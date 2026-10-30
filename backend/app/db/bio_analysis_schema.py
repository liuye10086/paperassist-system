"""Twelve normalized, owner/project-scoped spatial analysis tables."""
import sqlalchemy as sa
import hashlib
from sqlalchemy.dialects.postgresql import JSONB

TABLE_NAMES=('bio_observation_map_sets','bio_observation_map_versions','bio_analysis_setups',
 'bio_analysis_recipe_versions','bio_analysis_runs','bio_processed_dataset_versions','bio_analysis_artifacts',
 'bio_annotation_sets','bio_annotation_versions','bio_annotation_evidence','bio_figure_versions','bio_figure_members')
IMMUTABLE=('bio_observation_map_versions','bio_analysis_recipe_versions','bio_processed_dataset_versions',
 'bio_analysis_artifacts','bio_annotation_versions','bio_annotation_evidence','bio_figure_members')


def define_bio_analysis_tables(metadata):
    tables=[]
    sequence=[0]
    def text(name,nullable=False):return sa.Column(name,sa.Text,nullable=nullable)
    def json(name,default=None):return sa.Column(name,JSONB,nullable=False,server_default=sa.text(default) if default else None)
    def integer(name,default=None):return sa.Column(name,sa.Integer,nullable=False,server_default=str(default) if default is not None else None)
    def fk(cols,target,targets=None,**kwargs):
        sequence[0]+=1
        kwargs.setdefault('name','b02_scope_fk_'+str(sequence[0]))
        targets=targets or ['id','project_id']
        return sa.ForeignKeyConstraint(cols,[target+'.'+k for k in targets],**kwargs)
    def ref(col,target,**kwargs):return fk([col,'project_id'],target,**kwargs)
    def obj(col):return fk([col,'project_id'],'storage_references',['object_id','project_id'])
    def raw():return [text('raw_dataset_version_id'),ref('raw_dataset_version_id','bio_dataset_versions')]
    def request():return [text('request_key'),text('request_digest'),sa.UniqueConstraint('project_id','request_key')]
    def root(name,pointer,*extra):
        return make(name,*raw(),text('name'),integer('revision',1),text(pointer,True),*extra,
            sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
            sa.UniqueConstraint('id','raw_dataset_version_id','project_id'),
            sa.CheckConstraint("revision>=1 AND length(name) BETWEEN 1 AND 200"))
    def version(name,root_table,root_column,*extra):
        return make(name,text(root_column),integer('version'),text('parent_id',True),*raw(),*request(),*extra,
            sa.UniqueConstraint(root_column,'version'),sa.UniqueConstraint('id',root_column,'project_id'),
            sa.UniqueConstraint('id','raw_dataset_version_id','project_id'),
            fk([root_column,'raw_dataset_version_id','project_id'],root_table,['id','raw_dataset_version_id','project_id']),
            fk(['parent_id',root_column,'project_id'],name,['id',root_column,'project_id']),
            sa.CheckConstraint("version>=1 AND length(request_key) BETWEEN 1 AND 128 AND request_digest ~ '^[0-9a-f]{64}$'"))
    def make(name,*items):
        table=sa.Table(name,metadata,sa.Column('id',sa.Text,primary_key=True),text('project_id'),
            text('created_by'),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),integer('schema_version',1),
            sa.UniqueConstraint('id','project_id'),fk(['project_id','created_by'],'projects',['id','owner_id']),
            sa.CheckConstraint('schema_version=1'),*items)
        for constraint in table.constraints:
            if isinstance(constraint,sa.CheckConstraint) and constraint.name is None:
                constraint.name='b02_ck_'+hashlib.sha256(str(constraint.sqltext).encode()).hexdigest()[:16]
        sa.Index(name+'_project_created',table.c.project_id,table.c.created_at.desc(),table.c.id)
        tables.append(table);return table

    maps=root('bio_observation_map_sets','current_version_id',
        fk(['current_version_id','id','project_id'],'bio_observation_map_versions',['id','set_id','project_id'],use_alter=True))
    version('bio_observation_map_versions','bio_observation_map_sets','set_id',
        text('design_version_id',True),ref('design_version_id','research_design_versions'),
        text('mapping_object_id'),text('mapping_sha256'),obj('mapping_object_id'),json('counts_json'),
        text('table_source_file_id',True),ref('table_source_file_id','files'),
        sa.CheckConstraint("mapping_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(counts_json)='object'"))
    root('bio_analysis_setups','current_recipe_version_id',
        fk(['current_recipe_version_id','id','project_id'],'bio_analysis_recipe_versions',['id','setup_id','project_id'],use_alter=True))
    version('bio_analysis_recipe_versions','bio_analysis_setups','setup_id',
        text('observation_map_version_id',True),text('design_version_id',True),ref('design_version_id','research_design_versions'),
        fk(['observation_map_version_id','raw_dataset_version_id','project_id'],'bio_observation_map_versions',['id','raw_dataset_version_id','project_id']),
        text('recipe_code'),json('params_json'),json('default_figures_json'),text('engine_contract_version'),
        sa.CheckConstraint("recipe_code='visium_explore_v1' AND jsonb_typeof(params_json)='object' AND octet_length(params_json::text)<=4194304"))
    make('bio_analysis_runs',*raw(),text('recipe_version_id'),text('task_id'),text('source_digest'),
        text('execution_snapshot_object_id'),text('execution_snapshot_sha256'),integer('expected_setup_revision'),
        text('processed_dataset_version_id',True),*request(),
        obj('execution_snapshot_object_id'),sa.UniqueConstraint('task_id'),sa.UniqueConstraint('id','task_id','recipe_version_id','raw_dataset_version_id','project_id'),
        fk(['recipe_version_id','raw_dataset_version_id','project_id'],'bio_analysis_recipe_versions',['id','raw_dataset_version_id','project_id']),
        ref('task_id','tasks'),fk(['processed_dataset_version_id','id','project_id'],'bio_processed_dataset_versions',['id','run_id','project_id'],use_alter=True),
        sa.CheckConstraint("expected_setup_revision>=1 AND source_digest ~ '^[0-9a-f]{64}$' AND execution_snapshot_sha256 ~ '^[0-9a-f]{64}$'"))
    make('bio_processed_dataset_versions',*raw(),text('run_id'),text('task_id'),text('recipe_version_id'),
        text('manifest_object_id'),text('manifest_sha256'),obj('manifest_object_id'),json('shape_json'),json('steps_json'),
        text('environment_digest'),text('code_digest'),text('engine_version'),
        sa.UniqueConstraint('run_id'),sa.UniqueConstraint('task_id'),sa.UniqueConstraint('id','raw_dataset_version_id','project_id'),
        sa.UniqueConstraint('id','task_id','project_id'),sa.UniqueConstraint('id','run_id','project_id'),
        fk(['run_id','task_id','recipe_version_id','raw_dataset_version_id','project_id'],'bio_analysis_runs',['id','task_id','recipe_version_id','raw_dataset_version_id','project_id']),
        ref('task_id','tasks'),ref('recipe_version_id','bio_analysis_recipe_versions'),
        sa.CheckConstraint("manifest_sha256 ~ '^[0-9a-f]{64}$' AND environment_digest ~ '^[0-9a-f]{64}$' AND code_digest ~ '^[0-9a-f]{64}$'"))
    make('bio_analysis_artifacts',text('processed_dataset_version_id'),text('key'),text('role'),text('format'),
        text('storage_object_id'),sa.Column('size_bytes',sa.BigInteger,nullable=False),text('sha256'),json('shape_json',"'{}'::jsonb"),
        obj('storage_object_id'),ref('processed_dataset_version_id','bio_processed_dataset_versions'),
        sa.UniqueConstraint('processed_dataset_version_id','key'),sa.UniqueConstraint('id','processed_dataset_version_id','project_id'),
        sa.CheckConstraint("size_bytes>=0 AND sha256 ~ '^[0-9a-f]{64}$' AND key ~ '^[A-Za-z0-9_-]{1,100}$'"))
    root('bio_annotation_sets','current_version_id',text('processed_dataset_version_id',True),
        fk(['processed_dataset_version_id','raw_dataset_version_id','project_id'],'bio_processed_dataset_versions',['id','raw_dataset_version_id','project_id']),
        fk(['current_version_id','id','project_id'],'bio_annotation_versions',['id','set_id','project_id'],use_alter=True))
    version('bio_annotation_versions','bio_annotation_sets','set_id',
        text('processed_dataset_version_id',True),fk(['processed_dataset_version_id','raw_dataset_version_id','project_id'],'bio_processed_dataset_versions',['id','raw_dataset_version_id','project_id']),
        text('geometry_object_id'),text('geometry_sha256'),text('assignments_object_id'),text('assignments_sha256'),
        obj('geometry_object_id'),obj('assignments_object_id'),json('labels_json'),json('checks_json'),
        sa.CheckConstraint("geometry_sha256 ~ '^[0-9a-f]{64}$' AND assignments_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(labels_json)='array' AND jsonb_array_length(labels_json)<=100"))
    make('bio_annotation_evidence',text('annotation_version_id'),text('label_id'),text('kind'),
        text('analysis_artifact_id',True),text('file_id',True),text('note'),
        ref('annotation_version_id','bio_annotation_versions'),ref('analysis_artifact_id','bio_analysis_artifacts'),ref('file_id','files'),
        sa.CheckConstraint("(kind='marker' AND analysis_artifact_id IS NOT NULL AND file_id IS NULL) OR (kind='file' AND file_id IS NOT NULL AND analysis_artifact_id IS NULL)"),
        sa.CheckConstraint('length(note)<=4000'))
    make('bio_figure_versions',text('root_id'),integer('version'),text('parent_id',True),text('processed_dataset_version_id'),
        text('annotation_version_id',True),text('task_id'),json('config_json'),text('config_sha256'),text('renderer_version'),
        text('manifest_object_id',True),text('manifest_sha256',True),*request(),
        obj('manifest_object_id'),ref('processed_dataset_version_id','bio_processed_dataset_versions'),ref('annotation_version_id','bio_annotation_versions'),
        ref('task_id','tasks'),sa.UniqueConstraint('root_id','version'),sa.UniqueConstraint('id','root_id','project_id'),sa.UniqueConstraint('id','task_id','project_id'),
        fk(['parent_id','root_id','project_id'],'bio_figure_versions',['id','root_id','project_id']),
        sa.CheckConstraint("version>=1 AND config_sha256 ~ '^[0-9a-f]{64}$' AND ((manifest_object_id IS NULL AND manifest_sha256 IS NULL) OR (manifest_object_id IS NOT NULL AND manifest_sha256 ~ '^[0-9a-f]{64}$'))"))
    make('bio_figure_members',text('figure_version_id'),text('key'),text('format'),text('storage_object_id'),
        sa.Column('size_bytes',sa.BigInteger,nullable=False),text('sha256'),obj('storage_object_id'),ref('figure_version_id','bio_figure_versions'),
        sa.UniqueConstraint('figure_version_id','key'),
        sa.CheckConstraint("size_bytes>=0 AND sha256 ~ '^[0-9a-f]{64}$' AND key ~ '^[A-Za-z0-9_-]{1,100}$'"))
    return tuple(tables)

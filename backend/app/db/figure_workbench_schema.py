"""Only the figure workbench's new tables; shared metadata owns legacy changes."""
from sqlalchemy import Table,Column,Text,Integer,ForeignKey,UniqueConstraint,CheckConstraint,Index
from sqlalchemy.dialects.postgresql import JSONB,TIMESTAMP

def define_figure_workbench_tables(metadata):
    configurations=Table('figure_configurations',metadata,
        Column('id',Text,primary_key=True),Column('project_id',Text,ForeignKey('projects.id'),nullable=False),
        Column('analysis_run_id',Text,ForeignKey('analysis_runs.id'),nullable=False),Column('created_by',Text,ForeignKey('users.id'),nullable=False),
        Column('current_revision',Integer,nullable=False),Column('created_at',TIMESTAMP(timezone=True),nullable=False),
        CheckConstraint('current_revision>=1',name='figure_config_revision_positive'))
    versions=Table('figure_config_versions',metadata,
        Column('id',Text,primary_key=True),Column('configuration_id',Text,ForeignKey('figure_configurations.id'),nullable=False),
        Column('revision',Integer,nullable=False),Column('parent_version_id',Text,ForeignKey('figure_config_versions.id')),
        Column('created_by',Text,ForeignKey('users.id'),nullable=False),Column('created_at',TIMESTAMP(timezone=True),nullable=False),
        Column('sha256',Text,nullable=False),Column('config_json',JSONB,nullable=False),Column('source_json',JSONB,nullable=False),
        UniqueConstraint('configuration_id','revision',name='figure_config_versions_revision_key'),
        CheckConstraint('revision>=1',name='figure_version_revision_positive'))
    decisions=Table('figure_projection_decisions',metadata,
        Column('id',Text,primary_key=True),Column('config_version_id',Text,ForeignKey('figure_config_versions.id'),nullable=False,unique=True),
        Column('task_id',Text,ForeignKey('tasks.id'),unique=True),Column('approved_by',Text,ForeignKey('users.id'),nullable=False),
        Column('approved_at',TIMESTAMP(timezone=True),nullable=False),Column('input_sha256',Text,nullable=False),Column('decision_json',JSONB,nullable=False))
    projections=Table('figure_projection_results',metadata,
        Column('id',Text,primary_key=True),Column('config_version_id',Text,ForeignKey('figure_config_versions.id'),nullable=False),
        Column('decision_id',Text,ForeignKey('figure_projection_decisions.id')),Column('tool_version',Text,nullable=False),
        Column('sha256',Text,nullable=False),Column('result_json',JSONB,nullable=False),Column('created_at',TIMESTAMP(timezone=True),nullable=False),
        UniqueConstraint('config_version_id','tool_version',name='figure_projection_input_key'))
    Index('figure_configurations_project_run',configurations.c.project_id,configurations.c.analysis_run_id)
    return configurations,versions,decisions,projections

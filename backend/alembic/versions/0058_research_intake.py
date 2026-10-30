"""Research intake, delivery registration and immutable bio dataset sources."""
from uuid import UUID, uuid5
from alembic import op
import sqlalchemy as sa
INTAKE_TABLES=('research_intakes','research_deliveries','research_requirement_versions','research_design_versions','research_material_refs')
BIO_TABLES=('bio_datasets','bio_imports','bio_import_files','bio_dataset_versions','bio_dataset_members')

revision = '0058_research_intake'
down_revision = '0057_request_task_operation'
branch_labels = None
depends_on = None
NEW_TABLES = INTAKE_TABLES + BIO_TABLES
IMMUTABLE = ('research_requirement_versions','research_design_versions','research_material_refs',
             'bio_import_files','bio_dataset_versions','bio_dataset_members')
NAMESPACE = UUID('b9f6f346-4bb9-4f75-9426-4875b4939853')
OLD_TASK_TYPES = "'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx', 'school_template_parse', 'school_rule_suggestion', 'journal_recommendation', 'journal_format_check', 'journal_adaptation', 'review_round_plan', 'review_revision', 'review_document_export'"


# Immutable schema snapshot: future application models must not change this revision.
CREATE_TABLE_SQL=(
    """CREATE TABLE research_intakes (
	project_id TEXT NOT NULL,
	owner_id TEXT,
	revision INTEGER DEFAULT '1' NOT NULL,
	current_requirement_version_id TEXT,
	current_design_version_id TEXT,
	creation_request_key TEXT,
	creation_digest TEXT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (project_id),
	CONSTRAINT cr_ri_owner_fk FOREIGN KEY(project_id, owner_id) REFERENCES projects (id, owner_id),
	CONSTRAINT cr_ri_creation_key UNIQUE (owner_id, creation_request_key),
	CONSTRAINT cr_ri_revision_check CHECK (revision >= 1),
	CONSTRAINT cr_ri_creation_check CHECK ((creation_request_key IS NULL AND creation_digest IS NULL) OR (owner_id IS NOT NULL AND length(creation_request_key) BETWEEN 1 AND 128 AND creation_digest ~ '^[0-9a-f]{64}$')),
	FOREIGN KEY(project_id) REFERENCES projects (id)
)""",
    """CREATE TABLE research_deliveries (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	kind TEXT NOT NULL,
	name TEXT NOT NULL,
	origin TEXT NOT NULL,
	active BOOLEAN DEFAULT true NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	created_by TEXT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT cr_rd_scope_key UNIQUE (id, project_id),
	CONSTRAINT cr_rd_kind_key UNIQUE (project_id, kind),
	CONSTRAINT cr_rd_values_check CHECK (kind IN ('analysis','sci_draft','thesis_draft') AND origin IN ('user_selected','legacy_inferred') AND revision>=1 AND length(name) BETWEEN 1 AND 200),
	FOREIGN KEY(project_id) REFERENCES research_intakes (project_id),
	FOREIGN KEY(created_by) REFERENCES users (id)
)""",
    """CREATE TABLE research_requirement_versions (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	version INTEGER NOT NULL,
	parent_id TEXT,
	operation TEXT NOT NULL,
	content_json JSONB NOT NULL,
	sha256 TEXT NOT NULL,
	request_key TEXT NOT NULL,
	request_digest TEXT NOT NULL,
	created_by TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT rrv_scope_key UNIQUE (id, project_id),
	CONSTRAINT rrv_version_key UNIQUE (project_id, version),
	CONSTRAINT rrv_request_key UNIQUE (project_id, request_key),
	CONSTRAINT rrv_parent_fk FOREIGN KEY(parent_id, project_id) REFERENCES research_requirement_versions (id, project_id),
	CONSTRAINT rrv_values_check CHECK (version>=1 AND operation IN ('save','confirm') AND length(request_key) BETWEEN 1 AND 128 AND sha256 ~ '^[0-9a-f]{64}$' AND request_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT rrv_content_check CHECK ((jsonb_typeof(content_json)='object' AND content_json->'schema_version'='1'::jsonb) IS TRUE AND octet_length(content_json::text)<=4194304),
	FOREIGN KEY(project_id) REFERENCES research_intakes (project_id),
	FOREIGN KEY(created_by) REFERENCES users (id)
)""",
    """CREATE INDEX rrv_project_created ON research_requirement_versions (project_id, created_at DESC, id)""",
    """CREATE TABLE research_design_versions (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	version INTEGER NOT NULL,
	parent_id TEXT,
	operation TEXT NOT NULL,
	content_json JSONB NOT NULL,
	sha256 TEXT NOT NULL,
	request_key TEXT NOT NULL,
	request_digest TEXT NOT NULL,
	created_by TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT rdv_scope_key UNIQUE (id, project_id),
	CONSTRAINT rdv_version_key UNIQUE (project_id, version),
	CONSTRAINT rdv_request_key UNIQUE (project_id, request_key),
	CONSTRAINT rdv_parent_fk FOREIGN KEY(parent_id, project_id) REFERENCES research_design_versions (id, project_id),
	CONSTRAINT rdv_values_check CHECK (version>=1 AND operation IN ('save','confirm') AND length(request_key) BETWEEN 1 AND 128 AND sha256 ~ '^[0-9a-f]{64}$' AND request_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT rdv_content_check CHECK ((jsonb_typeof(content_json)='object' AND content_json->'schema_version'='1'::jsonb) IS TRUE AND octet_length(content_json::text)<=4194304),
	FOREIGN KEY(project_id) REFERENCES research_intakes (project_id),
	FOREIGN KEY(created_by) REFERENCES users (id)
)""",
    """CREATE INDEX rdv_project_created ON research_design_versions (project_id, created_at DESC, id)""",
    """CREATE TABLE bio_datasets (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	name TEXT NOT NULL,
	assay TEXT NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	current_version_id TEXT,
	created_by TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT cr_bd_scope_key UNIQUE (id, project_id),
	CONSTRAINT cr_bd_values_check CHECK (revision>=1 AND assay='visium' AND length(name) BETWEEN 1 AND 200),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(created_by) REFERENCES users (id)
)""",
    """CREATE INDEX cr_bd_project_created ON bio_datasets (project_id, created_at DESC, id)""",
    """CREATE TABLE bio_imports (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	dataset_id TEXT NOT NULL,
	task_id TEXT NOT NULL,
	request_key TEXT NOT NULL,
	request_digest TEXT NOT NULL,
	parser_version TEXT NOT NULL,
	input_sha256 TEXT NOT NULL,
	expected_dataset_revision INTEGER NOT NULL,
	settings_json JSONB NOT NULL,
	candidate_object_id TEXT,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT cr_bi_scope_key UNIQUE (id, project_id),
	CONSTRAINT cr_bi_dataset_scope_key UNIQUE (id, dataset_id, project_id),
	CONSTRAINT cr_bi_request_key UNIQUE (project_id, request_key),
	CONSTRAINT cr_bi_task_key UNIQUE (task_id),
	CONSTRAINT cr_bi_dataset_fk FOREIGN KEY(dataset_id, project_id) REFERENCES bio_datasets (id, project_id),
	CONSTRAINT cr_bi_task_fk FOREIGN KEY(task_id, project_id) REFERENCES tasks (id, project_id),
	CONSTRAINT cr_bi_values_check CHECK (expected_dataset_revision>=1 AND length(request_key) BETWEEN 1 AND 128 AND request_digest ~ '^[0-9a-f]{64}$' AND input_sha256 ~ '^[0-9a-f]{64}$' AND length(parser_version)>0),
	CONSTRAINT cr_bi_settings_check CHECK (jsonb_typeof(settings_json)='object' AND octet_length(settings_json::text)<=65536),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(candidate_object_id) REFERENCES storage_objects (id)
)""",
    """CREATE TABLE bio_import_files (
	import_id TEXT NOT NULL,
	file_id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	declared_role TEXT NOT NULL,
	source_sha256 TEXT NOT NULL,
	source_size_bytes BIGINT NOT NULL,
	PRIMARY KEY (import_id, file_id),
	CONSTRAINT cr_bif_import_fk FOREIGN KEY(import_id, project_id) REFERENCES bio_imports (id, project_id),
	CONSTRAINT cr_bif_file_fk FOREIGN KEY(file_id, project_id) REFERENCES files (id, project_id),
	CONSTRAINT cr_bif_values_check CHECK (source_sha256 ~ '^[0-9a-f]{64}$' AND source_size_bytes>=0 AND length(declared_role)>0),
	FOREIGN KEY(project_id) REFERENCES projects (id)
)""",
    """CREATE TABLE bio_dataset_versions (
	id TEXT NOT NULL,
	dataset_id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	version INTEGER NOT NULL,
	parent_id TEXT,
	import_id TEXT NOT NULL,
	task_id TEXT NOT NULL,
	manifest_object_id TEXT NOT NULL,
	manifest_sha256 TEXT NOT NULL,
	parser_version TEXT NOT NULL,
	shape_json JSONB NOT NULL,
	checks_json JSONB NOT NULL,
	created_by TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT cr_bdv_scope_key UNIQUE (id, project_id),
	CONSTRAINT cr_bdv_dataset_scope_key UNIQUE (id, dataset_id, project_id),
	CONSTRAINT cr_bdv_version_key UNIQUE (dataset_id, version),
	CONSTRAINT cr_bdv_import_key UNIQUE (import_id),
	CONSTRAINT cr_bdv_dataset_fk FOREIGN KEY(dataset_id, project_id) REFERENCES bio_datasets (id, project_id),
	CONSTRAINT cr_bdv_parent_fk FOREIGN KEY(parent_id, dataset_id, project_id) REFERENCES bio_dataset_versions (id, dataset_id, project_id),
	CONSTRAINT cr_bdv_import_fk FOREIGN KEY(import_id, dataset_id, project_id) REFERENCES bio_imports (id, dataset_id, project_id),
	CONSTRAINT cr_bdv_task_fk FOREIGN KEY(task_id, project_id) REFERENCES tasks (id, project_id),
	CONSTRAINT cr_bdv_manifest_fk FOREIGN KEY(manifest_object_id) REFERENCES storage_objects (id),
	CONSTRAINT cr_bdv_values_check CHECK (version>=1 AND manifest_sha256 ~ '^[0-9a-f]{64}$' AND length(parser_version)>0),
	CONSTRAINT cr_bdv_json_check CHECK (jsonb_typeof(shape_json)='object' AND jsonb_typeof(checks_json) IN ('object','array') AND octet_length(shape_json::text)<=65536 AND octet_length(checks_json::text)<=4194304),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(created_by) REFERENCES users (id)
)""",
    """CREATE TABLE bio_dataset_members (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	dataset_version_id TEXT NOT NULL,
	source_file_id TEXT NOT NULL,
	source_member_name TEXT NOT NULL,
	role TEXT NOT NULL,
	format TEXT NOT NULL,
	compression TEXT NOT NULL,
	verification_state TEXT NOT NULL,
	sha256 TEXT NOT NULL,
	object_id TEXT,
	size_bytes BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT cr_bdm_scope_key UNIQUE (id, project_id),
	CONSTRAINT cr_bdm_role_key UNIQUE (dataset_version_id, source_file_id, role, source_member_name),
	CONSTRAINT cr_bdm_version_fk FOREIGN KEY(dataset_version_id, project_id) REFERENCES bio_dataset_versions (id, project_id),
	CONSTRAINT cr_bdm_file_fk FOREIGN KEY(source_file_id, project_id) REFERENCES files (id, project_id),
	CONSTRAINT cr_bdm_values_check CHECK (sha256 ~ '^[0-9a-f]{64}$' AND size_bytes>=0 AND verification_state IN ('verified','not_checked','internal_not_checked','failed')),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(object_id) REFERENCES storage_objects (id)
)""",
    """CREATE TABLE research_material_refs (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	requirement_version_id TEXT,
	design_version_id TEXT,
	delivery_id TEXT,
	file_id TEXT,
	bio_dataset_version_id TEXT,
	locator TEXT,
	availability TEXT NOT NULL,
	purpose TEXT NOT NULL,
	note TEXT DEFAULT '' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT cr_rmr_requirement_fk FOREIGN KEY(requirement_version_id, project_id) REFERENCES research_requirement_versions (id, project_id),
	CONSTRAINT cr_rmr_design_fk FOREIGN KEY(design_version_id, project_id) REFERENCES research_design_versions (id, project_id),
	CONSTRAINT cr_rmr_delivery_fk FOREIGN KEY(delivery_id, project_id) REFERENCES research_deliveries (id, project_id),
	CONSTRAINT cr_rmr_file_fk FOREIGN KEY(file_id, project_id) REFERENCES files (id, project_id),
	CONSTRAINT cr_rmr_bio_fk FOREIGN KEY(bio_dataset_version_id, project_id) REFERENCES bio_dataset_versions (id, project_id),
	CONSTRAINT cr_rmr_source_check CHECK (num_nonnulls(requirement_version_id,design_version_id)=1 AND availability IN ('provided','pending','none') AND ((availability='provided' AND num_nonnulls(file_id,bio_dataset_version_id)=1) OR (availability<>'provided' AND num_nonnulls(file_id,bio_dataset_version_id)=0))),
	CONSTRAINT cr_rmr_text_check CHECK (length(purpose) BETWEEN 1 AND 200 AND length(note)<=4000 AND (locator IS NULL OR length(locator)<=4000)),
	FOREIGN KEY(project_id) REFERENCES research_intakes (project_id)
)""",
    """ALTER TABLE research_intakes ADD CONSTRAINT cr_ri_design_fk FOREIGN KEY(current_design_version_id, project_id) REFERENCES research_design_versions (id, project_id)""",
    """ALTER TABLE research_intakes ADD CONSTRAINT cr_ri_requirement_fk FOREIGN KEY(current_requirement_version_id, project_id) REFERENCES research_requirement_versions (id, project_id)""",
    """ALTER TABLE bio_datasets ADD CONSTRAINT cr_bd_current_fk FOREIGN KEY(current_version_id, id, project_id) REFERENCES bio_dataset_versions (id, dataset_id, project_id)""",
)


def _check(table, name, expression):
    op.drop_constraint(name, table, type_='check')
    op.create_check_constraint(name, table, expression)


def upgrade():
    op.execute("SET LOCAL lock_timeout='3s'")
    _check('projects','projects_project_type_check', "project_type IN ('sci','thesis','research')")
    _check('files','files_type_check', "file_type IN ('xlsx','docx','pdf','png','jpeg','bio_bundle','bio_component')")
    _check('files','files_parse_status_check', "parse_status IN ('queued','parsing','parsed','failed','stored')")
    _check('tasks','tasks_type_check', 'task_type IN ('+OLD_TASK_TYPES+", 'bio_import')")
    op.create_check_constraint('tasks_bio_snapshot_check','tasks', "task_type<>'bio_import' OR ((workflow_version='bio_import_v1' AND input_snapshot->'schema_version'='1'::jsonb AND input_snapshot->>'kind'='bio_import' AND input_snapshot->>'workflow_version'='bio_import_v1' AND input_snapshot->>'project_id'=project_id AND jsonb_typeof(input_snapshot->'files')='array' AND jsonb_array_length(input_snapshot->'files')>=1 AND jsonb_array_length(input_snapshot->'files')<=10 AND jsonb_typeof(input_snapshot->'settings')='object') IS TRUE)")
    _check('task_waits','task_waits_kind_check', "kind IN ('bio_import_confirmation','budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation','dataset_preparation_confirmation','ocr_review_confirmation','analysis_plan_confirmation','analysis_plan_input','figure_projection_confirmation','remote_observation','literature_configuration','literature_model_authorization','review_round_confirmation','review_round_input')")
    op.create_unique_constraint('tasks_project_scope_key','tasks',['id','project_id'])
    op.add_column('file_upload_batches', sa.Column('profile',sa.Text,nullable=False,server_default='documents'))
    op.create_check_constraint('file_batches_profile_check','file_upload_batches', "profile IN ('documents','bioinformatics_v1')")
    bind = op.get_bind()
    for statement in CREATE_TABLE_SQL:
        op.execute(sa.text(statement))
    op.add_column('tasks',sa.Column('result_bio_dataset_version_id',sa.Text))
    op.create_foreign_key('tasks_bio_result_fk','tasks','bio_dataset_versions',
                          ['result_bio_dataset_version_id','project_id'],['id','project_id'])
    op.execute("""CREATE FUNCTION research_snapshot_seal() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'Immutable research snapshot'; END $$""")
    for name in IMMUTABLE:
        op.execute(f'CREATE TRIGGER research_snapshot_seal BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION research_snapshot_seal()')
    op.execute("""CREATE FUNCTION bio_import_source_seal() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF TG_OP='UPDATE' AND (to_jsonb(OLD)-'candidate_object_id')=(to_jsonb(NEW)-'candidate_object_id')
        AND (OLD.candidate_object_id IS NULL OR OLD.candidate_object_id IS NOT DISTINCT FROM NEW.candidate_object_id)
        THEN RETURN NEW; END IF; RAISE EXCEPTION 'Immutable bio import source'; END $$""")
    op.execute('CREATE TRIGGER bio_import_source_seal BEFORE UPDATE OR DELETE ON bio_imports FOR EACH ROW EXECUTE FUNCTION bio_import_source_seal()')
    rows = bind.execute(sa.text('SELECT id,owner_id,project_type,created_at,updated_at FROM projects')).mappings()
    for row in rows:
        bind.execute(sa.text('''INSERT INTO research_intakes(project_id,owner_id,revision,created_at,updated_at)
            VALUES(:id,:owner_id,1,CAST(:created_at AS timestamptz),CAST(:updated_at AS timestamptz))'''),dict(row))
        kind = {'sci':'sci_draft','thesis':'thesis_draft'}.get(row['project_type'])
        if kind:
            bind.execute(sa.text('''INSERT INTO research_deliveries(id,project_id,kind,name,origin,active,revision,created_by,created_at,updated_at)
                VALUES(:delivery_id,:id,:kind,:kind,'legacy_inferred',true,1,:owner_id,CAST(:created_at AS timestamptz),CAST(:updated_at AS timestamptz))'''),
                {**dict(row),'kind':kind,'delivery_id':str(uuid5(NAMESPACE,f"delivery:{row['id']}:{kind}"))})
    # Install barriers for these producers only. Existing triggers are untouched.
    from app.db.storage_deletion_schema import install_research_barriers
    install_research_barriers(op.execute)


def downgrade():
    bind = op.get_bind()
    for table in ('research_requirement_versions','research_design_versions','research_material_refs',*BIO_TABLES):
        if bind.exec_driver_sql(f'SELECT EXISTS(SELECT 1 FROM {table})').scalar_one():
            raise RuntimeError('Research/bio business data exists; refusing destructive downgrade.')
    if bind.exec_driver_sql("SELECT EXISTS(SELECT 1 FROM projects WHERE project_type='research') OR EXISTS(SELECT 1 FROM files WHERE file_type IN ('bio_bundle','bio_component') OR parse_status='stored') OR EXISTS(SELECT 1 FROM tasks WHERE task_type='bio_import') OR EXISTS(SELECT 1 FROM research_deliveries WHERE origin<>'legacy_inferred') OR EXISTS(SELECT 1 FROM file_upload_batches WHERE profile<>'documents')").scalar_one():
        raise RuntimeError('Research/bio contracts are in use; refusing destructive downgrade.')
    op.drop_constraint('tasks_bio_result_fk','tasks',type_='foreignkey')
    op.drop_constraint('tasks_bio_snapshot_check','tasks',type_='check')
    op.drop_column('tasks','result_bio_dataset_version_id')
    for table, fk in [('research_intakes','cr_ri_requirement_fk'),('research_intakes','cr_ri_design_fk'),('bio_datasets','cr_bd_current_fk')]:
        op.drop_constraint(fk,table,type_='foreignkey')
    for table in ('research_material_refs','bio_dataset_members','bio_dataset_versions','bio_import_files','bio_imports','bio_datasets','research_design_versions','research_requirement_versions','research_deliveries','research_intakes'):
        op.drop_table(table)
        op.execute(f'DROP FUNCTION storage_guard_{table}()')
    op.execute('DROP FUNCTION research_snapshot_seal()')
    op.execute('DROP FUNCTION bio_import_source_seal()')
    op.drop_constraint('tasks_project_scope_key','tasks',type_='unique')
    op.drop_constraint('file_batches_profile_check','file_upload_batches',type_='check')
    op.drop_column('file_upload_batches','profile')
    _check('projects','projects_project_type_check', "project_type IN ('sci','thesis')")
    _check('files','files_type_check', "file_type IN ('xlsx','docx','pdf','png','jpeg')")
    _check('files','files_parse_status_check', "parse_status IN ('queued','parsing','parsed','failed')")
    _check('task_waits','task_waits_kind_check', "kind IN ('budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation','dataset_preparation_confirmation','ocr_review_confirmation','analysis_plan_confirmation','analysis_plan_input','figure_projection_confirmation','remote_observation','literature_configuration','literature_model_authorization','review_round_confirmation','review_round_input')")
    _check('tasks','tasks_type_check', 'task_type IN ('+OLD_TASK_TYPES+')')

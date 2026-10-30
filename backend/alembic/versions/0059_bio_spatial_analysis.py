"""Frozen CR-B02 spatial-analysis DDL; never imports application metadata."""
from alembic import op
import sqlalchemy as sa
revision='0059_bio_spatial_analysis'
down_revision='0058_research_intake'
branch_labels=None
depends_on=None
TABLE_NAMES=('bio_observation_map_sets', 'bio_observation_map_versions', 'bio_analysis_setups', 'bio_analysis_recipe_versions', 'bio_analysis_runs', 'bio_processed_dataset_versions', 'bio_analysis_artifacts', 'bio_annotation_sets', 'bio_annotation_versions', 'bio_annotation_evidence', 'bio_figure_versions', 'bio_figure_members')
IMMUTABLE=('bio_observation_map_versions', 'bio_analysis_recipe_versions', 'bio_processed_dataset_versions', 'bio_analysis_artifacts', 'bio_annotation_versions', 'bio_annotation_evidence', 'bio_figure_members')
CREATE_TABLE_SQL=(
    """CREATE TABLE bio_observation_map_sets (
	id TEXT NOT NULL, 
	project_id TEXT NOT NULL, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	schema_version INTEGER DEFAULT '1' NOT NULL, 
	raw_dataset_version_id TEXT NOT NULL, 
	name TEXT NOT NULL, 
	revision INTEGER DEFAULT '1' NOT NULL, 
	current_version_id TEXT, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT b02_scope_fk_2 FOREIGN KEY(raw_dataset_version_id, project_id) REFERENCES bio_dataset_versions (id, project_id), 
	UNIQUE (id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_ck_2b0cec09356104ce CHECK (revision>=1 AND length(name) BETWEEN 1 AND 200),
	UNIQUE (id, project_id), 
	CONSTRAINT b02_scope_fk_3 FOREIGN KEY(project_id, created_by) REFERENCES projects (id, owner_id), 
	CONSTRAINT b02_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX bio_observation_map_sets_project_created ON bio_observation_map_sets (project_id, created_at DESC, id)""",
    """CREATE TABLE bio_analysis_setups (
	id TEXT NOT NULL, 
	project_id TEXT NOT NULL, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	schema_version INTEGER DEFAULT '1' NOT NULL, 
	raw_dataset_version_id TEXT NOT NULL, 
	name TEXT NOT NULL, 
	revision INTEGER DEFAULT '1' NOT NULL, 
	current_recipe_version_id TEXT, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT b02_scope_fk_12 FOREIGN KEY(raw_dataset_version_id, project_id) REFERENCES bio_dataset_versions (id, project_id), 
	UNIQUE (id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_ck_2b0cec09356104ce CHECK (revision>=1 AND length(name) BETWEEN 1 AND 200),
	UNIQUE (id, project_id), 
	CONSTRAINT b02_scope_fk_13 FOREIGN KEY(project_id, created_by) REFERENCES projects (id, owner_id), 
	CONSTRAINT b02_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX bio_analysis_setups_project_created ON bio_analysis_setups (project_id, created_at DESC, id)""",
    """CREATE TABLE bio_observation_map_versions (
	id TEXT NOT NULL, 
	project_id TEXT NOT NULL, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	schema_version INTEGER DEFAULT '1' NOT NULL, 
	set_id TEXT NOT NULL, 
	version INTEGER NOT NULL, 
	parent_id TEXT, 
	raw_dataset_version_id TEXT NOT NULL, 
	request_key TEXT NOT NULL, 
	request_digest TEXT NOT NULL, 
	design_version_id TEXT, 
	mapping_object_id TEXT NOT NULL, 
	mapping_sha256 TEXT NOT NULL, 
	counts_json JSONB NOT NULL, 
	table_source_file_id TEXT, 
	PRIMARY KEY (id), 
	CONSTRAINT b02_scope_fk_4 FOREIGN KEY(design_version_id, project_id) REFERENCES research_design_versions (id, project_id), 
	CONSTRAINT b02_scope_fk_5 FOREIGN KEY(mapping_object_id, project_id) REFERENCES storage_references (object_id, project_id), 
	CONSTRAINT b02_scope_fk_6 FOREIGN KEY(table_source_file_id, project_id) REFERENCES files (id, project_id), 
	CONSTRAINT b02_ck_073b76a32925719e CHECK (mapping_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(counts_json)='object'),
	CONSTRAINT b02_scope_fk_7 FOREIGN KEY(raw_dataset_version_id, project_id) REFERENCES bio_dataset_versions (id, project_id), 
	UNIQUE (project_id, request_key), 
	UNIQUE (set_id, version), 
	UNIQUE (id, set_id, project_id), 
	UNIQUE (id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_scope_fk_8 FOREIGN KEY(set_id, raw_dataset_version_id, project_id) REFERENCES bio_observation_map_sets (id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_scope_fk_9 FOREIGN KEY(parent_id, set_id, project_id) REFERENCES bio_observation_map_versions (id, set_id, project_id), 
	CONSTRAINT b02_ck_1aba0250f466ab6c CHECK (version>=1 AND length(request_key) BETWEEN 1 AND 128 AND request_digest ~ '^[0-9a-f]{64}$'),
	UNIQUE (id, project_id), 
	CONSTRAINT b02_scope_fk_10 FOREIGN KEY(project_id, created_by) REFERENCES projects (id, owner_id), 
	CONSTRAINT b02_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX bio_observation_map_versions_project_created ON bio_observation_map_versions (project_id, created_at DESC, id)""",
    """CREATE TABLE bio_analysis_recipe_versions (
	id TEXT NOT NULL, 
	project_id TEXT NOT NULL, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	schema_version INTEGER DEFAULT '1' NOT NULL, 
	setup_id TEXT NOT NULL, 
	version INTEGER NOT NULL, 
	parent_id TEXT, 
	raw_dataset_version_id TEXT NOT NULL, 
	request_key TEXT NOT NULL, 
	request_digest TEXT NOT NULL, 
	observation_map_version_id TEXT, 
	design_version_id TEXT, 
	recipe_code TEXT NOT NULL, 
	params_json JSONB NOT NULL, 
	default_figures_json JSONB NOT NULL, 
	engine_contract_version TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT b02_scope_fk_14 FOREIGN KEY(design_version_id, project_id) REFERENCES research_design_versions (id, project_id), 
	CONSTRAINT b02_scope_fk_15 FOREIGN KEY(observation_map_version_id, raw_dataset_version_id, project_id) REFERENCES bio_observation_map_versions (id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_ck_5ee6000b8a24fd3a CHECK (recipe_code='visium_explore_v1' AND jsonb_typeof(params_json)='object' AND octet_length(params_json::text)<=4194304),
	CONSTRAINT b02_scope_fk_16 FOREIGN KEY(raw_dataset_version_id, project_id) REFERENCES bio_dataset_versions (id, project_id), 
	UNIQUE (project_id, request_key), 
	UNIQUE (setup_id, version), 
	UNIQUE (id, setup_id, project_id), 
	UNIQUE (id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_scope_fk_17 FOREIGN KEY(setup_id, raw_dataset_version_id, project_id) REFERENCES bio_analysis_setups (id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_scope_fk_18 FOREIGN KEY(parent_id, setup_id, project_id) REFERENCES bio_analysis_recipe_versions (id, setup_id, project_id), 
	CONSTRAINT b02_ck_1aba0250f466ab6c CHECK (version>=1 AND length(request_key) BETWEEN 1 AND 128 AND request_digest ~ '^[0-9a-f]{64}$'),
	UNIQUE (id, project_id), 
	CONSTRAINT b02_scope_fk_19 FOREIGN KEY(project_id, created_by) REFERENCES projects (id, owner_id), 
	CONSTRAINT b02_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX bio_analysis_recipe_versions_project_created ON bio_analysis_recipe_versions (project_id, created_at DESC, id)""",
    """CREATE TABLE bio_analysis_runs (
	id TEXT NOT NULL, 
	project_id TEXT NOT NULL, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	schema_version INTEGER DEFAULT '1' NOT NULL, 
	raw_dataset_version_id TEXT NOT NULL, 
	recipe_version_id TEXT NOT NULL, 
	task_id TEXT NOT NULL, 
	source_digest TEXT NOT NULL, 
	execution_snapshot_object_id TEXT NOT NULL, 
	execution_snapshot_sha256 TEXT NOT NULL, 
	expected_setup_revision INTEGER NOT NULL, 
	processed_dataset_version_id TEXT, 
	request_key TEXT NOT NULL, 
	request_digest TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT b02_scope_fk_20 FOREIGN KEY(raw_dataset_version_id, project_id) REFERENCES bio_dataset_versions (id, project_id), 
	UNIQUE (project_id, request_key), 
	CONSTRAINT b02_scope_fk_21 FOREIGN KEY(execution_snapshot_object_id, project_id) REFERENCES storage_references (object_id, project_id), 
	UNIQUE (task_id), 
	UNIQUE (id, task_id, recipe_version_id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_scope_fk_22 FOREIGN KEY(recipe_version_id, raw_dataset_version_id, project_id) REFERENCES bio_analysis_recipe_versions (id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_scope_fk_23 FOREIGN KEY(task_id, project_id) REFERENCES tasks (id, project_id), 
	CONSTRAINT b02_ck_35f8429f098707fd CHECK (expected_setup_revision>=1 AND source_digest ~ '^[0-9a-f]{64}$' AND execution_snapshot_sha256 ~ '^[0-9a-f]{64}$'),
	UNIQUE (id, project_id), 
	CONSTRAINT b02_scope_fk_25 FOREIGN KEY(project_id, created_by) REFERENCES projects (id, owner_id), 
	CONSTRAINT b02_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX bio_analysis_runs_project_created ON bio_analysis_runs (project_id, created_at DESC, id)""",
    """CREATE TABLE bio_processed_dataset_versions (
	id TEXT NOT NULL, 
	project_id TEXT NOT NULL, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	schema_version INTEGER DEFAULT '1' NOT NULL, 
	raw_dataset_version_id TEXT NOT NULL, 
	run_id TEXT NOT NULL, 
	task_id TEXT NOT NULL, 
	recipe_version_id TEXT NOT NULL, 
	manifest_object_id TEXT NOT NULL, 
	manifest_sha256 TEXT NOT NULL, 
	shape_json JSONB NOT NULL, 
	steps_json JSONB NOT NULL, 
	environment_digest TEXT NOT NULL, 
	code_digest TEXT NOT NULL, 
	engine_version TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT b02_scope_fk_26 FOREIGN KEY(raw_dataset_version_id, project_id) REFERENCES bio_dataset_versions (id, project_id), 
	CONSTRAINT b02_scope_fk_27 FOREIGN KEY(manifest_object_id, project_id) REFERENCES storage_references (object_id, project_id), 
	UNIQUE (run_id), 
	UNIQUE (task_id), 
	UNIQUE (id, raw_dataset_version_id, project_id), 
	UNIQUE (id, task_id, project_id), 
	UNIQUE (id, run_id, project_id), 
	CONSTRAINT b02_scope_fk_28 FOREIGN KEY(run_id, task_id, recipe_version_id, raw_dataset_version_id, project_id) REFERENCES bio_analysis_runs (id, task_id, recipe_version_id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_scope_fk_29 FOREIGN KEY(task_id, project_id) REFERENCES tasks (id, project_id), 
	CONSTRAINT b02_scope_fk_30 FOREIGN KEY(recipe_version_id, project_id) REFERENCES bio_analysis_recipe_versions (id, project_id), 
	CONSTRAINT b02_ck_2a69764f36ba264f CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$' AND environment_digest ~ '^[0-9a-f]{64}$' AND code_digest ~ '^[0-9a-f]{64}$'),
	UNIQUE (id, project_id), 
	CONSTRAINT b02_scope_fk_31 FOREIGN KEY(project_id, created_by) REFERENCES projects (id, owner_id), 
	CONSTRAINT b02_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX bio_processed_dataset_versions_project_created ON bio_processed_dataset_versions (project_id, created_at DESC, id)""",
    """CREATE TABLE bio_analysis_artifacts (
	id TEXT NOT NULL, 
	project_id TEXT NOT NULL, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	schema_version INTEGER DEFAULT '1' NOT NULL, 
	processed_dataset_version_id TEXT NOT NULL, 
	key TEXT NOT NULL, 
	role TEXT NOT NULL, 
	format TEXT NOT NULL, 
	storage_object_id TEXT NOT NULL, 
	size_bytes BIGINT NOT NULL, 
	sha256 TEXT NOT NULL, 
	shape_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT b02_scope_fk_32 FOREIGN KEY(storage_object_id, project_id) REFERENCES storage_references (object_id, project_id), 
	CONSTRAINT b02_scope_fk_33 FOREIGN KEY(processed_dataset_version_id, project_id) REFERENCES bio_processed_dataset_versions (id, project_id), 
	UNIQUE (processed_dataset_version_id, key), 
	UNIQUE (id, processed_dataset_version_id, project_id), 
	CONSTRAINT b02_ck_d719f1d74b5240e0 CHECK (size_bytes>=0 AND sha256 ~ '^[0-9a-f]{64}$' AND key ~ '^[A-Za-z0-9_-]{1,100}$'),
	UNIQUE (id, project_id), 
	CONSTRAINT b02_scope_fk_34 FOREIGN KEY(project_id, created_by) REFERENCES projects (id, owner_id), 
	CONSTRAINT b02_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX bio_analysis_artifacts_project_created ON bio_analysis_artifacts (project_id, created_at DESC, id)""",
    """CREATE TABLE bio_annotation_sets (
	id TEXT NOT NULL, 
	project_id TEXT NOT NULL, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	schema_version INTEGER DEFAULT '1' NOT NULL, 
	raw_dataset_version_id TEXT NOT NULL, 
	name TEXT NOT NULL, 
	revision INTEGER DEFAULT '1' NOT NULL, 
	current_version_id TEXT, 
	processed_dataset_version_id TEXT, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT b02_scope_fk_35 FOREIGN KEY(processed_dataset_version_id, raw_dataset_version_id, project_id) REFERENCES bio_processed_dataset_versions (id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_scope_fk_37 FOREIGN KEY(raw_dataset_version_id, project_id) REFERENCES bio_dataset_versions (id, project_id), 
	UNIQUE (id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_ck_2b0cec09356104ce CHECK (revision>=1 AND length(name) BETWEEN 1 AND 200),
	UNIQUE (id, project_id), 
	CONSTRAINT b02_scope_fk_38 FOREIGN KEY(project_id, created_by) REFERENCES projects (id, owner_id), 
	CONSTRAINT b02_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX bio_annotation_sets_project_created ON bio_annotation_sets (project_id, created_at DESC, id)""",
    """CREATE TABLE bio_annotation_versions (
	id TEXT NOT NULL, 
	project_id TEXT NOT NULL, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	schema_version INTEGER DEFAULT '1' NOT NULL, 
	set_id TEXT NOT NULL, 
	version INTEGER NOT NULL, 
	parent_id TEXT, 
	raw_dataset_version_id TEXT NOT NULL, 
	request_key TEXT NOT NULL, 
	request_digest TEXT NOT NULL, 
	processed_dataset_version_id TEXT, 
	geometry_object_id TEXT NOT NULL, 
	geometry_sha256 TEXT NOT NULL, 
	assignments_object_id TEXT NOT NULL, 
	assignments_sha256 TEXT NOT NULL, 
	labels_json JSONB NOT NULL, 
	checks_json JSONB NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT b02_scope_fk_39 FOREIGN KEY(processed_dataset_version_id, raw_dataset_version_id, project_id) REFERENCES bio_processed_dataset_versions (id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_scope_fk_40 FOREIGN KEY(geometry_object_id, project_id) REFERENCES storage_references (object_id, project_id), 
	CONSTRAINT b02_scope_fk_41 FOREIGN KEY(assignments_object_id, project_id) REFERENCES storage_references (object_id, project_id), 
	CONSTRAINT b02_ck_1232d356c4dc5e35 CHECK (geometry_sha256 ~ '^[0-9a-f]{64}$' AND assignments_sha256 ~ '^[0-9a-f]{64}$' AND jsonb_typeof(labels_json)='array' AND jsonb_array_length(labels_json)<=100),
	CONSTRAINT b02_scope_fk_42 FOREIGN KEY(raw_dataset_version_id, project_id) REFERENCES bio_dataset_versions (id, project_id), 
	UNIQUE (project_id, request_key), 
	UNIQUE (set_id, version), 
	UNIQUE (id, set_id, project_id), 
	UNIQUE (id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_scope_fk_43 FOREIGN KEY(set_id, raw_dataset_version_id, project_id) REFERENCES bio_annotation_sets (id, raw_dataset_version_id, project_id), 
	CONSTRAINT b02_scope_fk_44 FOREIGN KEY(parent_id, set_id, project_id) REFERENCES bio_annotation_versions (id, set_id, project_id), 
	CONSTRAINT b02_ck_1aba0250f466ab6c CHECK (version>=1 AND length(request_key) BETWEEN 1 AND 128 AND request_digest ~ '^[0-9a-f]{64}$'),
	UNIQUE (id, project_id), 
	CONSTRAINT b02_scope_fk_45 FOREIGN KEY(project_id, created_by) REFERENCES projects (id, owner_id), 
	CONSTRAINT b02_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX bio_annotation_versions_project_created ON bio_annotation_versions (project_id, created_at DESC, id)""",
    """CREATE TABLE bio_annotation_evidence (
	id TEXT NOT NULL, 
	project_id TEXT NOT NULL, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	schema_version INTEGER DEFAULT '1' NOT NULL, 
	annotation_version_id TEXT NOT NULL, 
	label_id TEXT NOT NULL, 
	kind TEXT NOT NULL, 
	analysis_artifact_id TEXT, 
	file_id TEXT, 
	note TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT b02_scope_fk_46 FOREIGN KEY(annotation_version_id, project_id) REFERENCES bio_annotation_versions (id, project_id), 
	CONSTRAINT b02_scope_fk_47 FOREIGN KEY(analysis_artifact_id, project_id) REFERENCES bio_analysis_artifacts (id, project_id), 
	CONSTRAINT b02_scope_fk_48 FOREIGN KEY(file_id, project_id) REFERENCES files (id, project_id), 
	CONSTRAINT b02_ck_76cbea31461c936b CHECK ((kind='marker' AND analysis_artifact_id IS NOT NULL AND file_id IS NULL) OR (kind='file' AND file_id IS NOT NULL AND analysis_artifact_id IS NULL)),
	CONSTRAINT b02_ck_90536362881f6f2b CHECK (length(note)<=4000),
	UNIQUE (id, project_id), 
	CONSTRAINT b02_scope_fk_49 FOREIGN KEY(project_id, created_by) REFERENCES projects (id, owner_id), 
	CONSTRAINT b02_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX bio_annotation_evidence_project_created ON bio_annotation_evidence (project_id, created_at DESC, id)""",
    """CREATE TABLE bio_figure_versions (
	id TEXT NOT NULL, 
	project_id TEXT NOT NULL, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	schema_version INTEGER DEFAULT '1' NOT NULL, 
	root_id TEXT NOT NULL, 
	version INTEGER NOT NULL, 
	parent_id TEXT, 
	processed_dataset_version_id TEXT NOT NULL, 
	annotation_version_id TEXT, 
	task_id TEXT NOT NULL, 
	config_json JSONB NOT NULL, 
	config_sha256 TEXT NOT NULL, 
	renderer_version TEXT NOT NULL, 
	manifest_object_id TEXT, 
	manifest_sha256 TEXT, 
	request_key TEXT NOT NULL, 
	request_digest TEXT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (project_id, request_key), 
	CONSTRAINT b02_scope_fk_50 FOREIGN KEY(manifest_object_id, project_id) REFERENCES storage_references (object_id, project_id), 
	CONSTRAINT b02_scope_fk_51 FOREIGN KEY(processed_dataset_version_id, project_id) REFERENCES bio_processed_dataset_versions (id, project_id), 
	CONSTRAINT b02_scope_fk_52 FOREIGN KEY(annotation_version_id, project_id) REFERENCES bio_annotation_versions (id, project_id), 
	CONSTRAINT b02_scope_fk_53 FOREIGN KEY(task_id, project_id) REFERENCES tasks (id, project_id), 
	UNIQUE (root_id, version), 
	UNIQUE (id, root_id, project_id), 
	UNIQUE (id, task_id, project_id), 
	CONSTRAINT b02_scope_fk_54 FOREIGN KEY(parent_id, root_id, project_id) REFERENCES bio_figure_versions (id, root_id, project_id), 
	CONSTRAINT b02_ck_35e11969701c3ce0 CHECK (version>=1 AND config_sha256 ~ '^[0-9a-f]{64}$' AND ((manifest_object_id IS NULL AND manifest_sha256 IS NULL) OR (manifest_object_id IS NOT NULL AND manifest_sha256 ~ '^[0-9a-f]{64}$'))),
	UNIQUE (id, project_id), 
	CONSTRAINT b02_scope_fk_55 FOREIGN KEY(project_id, created_by) REFERENCES projects (id, owner_id), 
	CONSTRAINT b02_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX bio_figure_versions_project_created ON bio_figure_versions (project_id, created_at DESC, id)""",
    """CREATE TABLE bio_figure_members (
	id TEXT NOT NULL, 
	project_id TEXT NOT NULL, 
	created_by TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	schema_version INTEGER DEFAULT '1' NOT NULL, 
	figure_version_id TEXT NOT NULL, 
	key TEXT NOT NULL, 
	format TEXT NOT NULL, 
	storage_object_id TEXT NOT NULL, 
	size_bytes BIGINT NOT NULL, 
	sha256 TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT b02_scope_fk_56 FOREIGN KEY(storage_object_id, project_id) REFERENCES storage_references (object_id, project_id), 
	CONSTRAINT b02_scope_fk_57 FOREIGN KEY(figure_version_id, project_id) REFERENCES bio_figure_versions (id, project_id), 
	UNIQUE (figure_version_id, key), 
	CONSTRAINT b02_ck_d719f1d74b5240e0 CHECK (size_bytes>=0 AND sha256 ~ '^[0-9a-f]{64}$' AND key ~ '^[A-Za-z0-9_-]{1,100}$'),
	UNIQUE (id, project_id), 
	CONSTRAINT b02_scope_fk_58 FOREIGN KEY(project_id, created_by) REFERENCES projects (id, owner_id), 
	CONSTRAINT b02_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX bio_figure_members_project_created ON bio_figure_members (project_id, created_at DESC, id)""",
    """ALTER TABLE bio_analysis_runs ADD CONSTRAINT b02_scope_fk_24 FOREIGN KEY(processed_dataset_version_id, id, project_id) REFERENCES bio_processed_dataset_versions (id, run_id, project_id)""",
    """ALTER TABLE bio_annotation_sets ADD CONSTRAINT b02_scope_fk_36 FOREIGN KEY(current_version_id, id, project_id) REFERENCES bio_annotation_versions (id, set_id, project_id)""",
    """ALTER TABLE bio_observation_map_sets ADD CONSTRAINT b02_scope_fk_1 FOREIGN KEY(current_version_id, id, project_id) REFERENCES bio_observation_map_versions (id, set_id, project_id)""",
    """ALTER TABLE bio_analysis_setups ADD CONSTRAINT b02_scope_fk_11 FOREIGN KEY(current_recipe_version_id, id, project_id) REFERENCES bio_analysis_recipe_versions (id, setup_id, project_id)""",
)
TASK_TYPES="'boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx', 'school_template_parse', 'school_rule_suggestion', 'journal_recommendation', 'journal_format_check', 'journal_adaptation', 'review_round_plan', 'review_revision', 'review_document_export', 'bio_import', 'bio_analysis', 'bio_figure'"
TASK_CHECKS={'tasks_bio_results_check': "(result_bio_processed_dataset_version_id IS NULL OR (task_type='bio_analysis' AND status='succeeded')) AND (result_bio_figure_version_id IS NULL OR (task_type='bio_figure' AND status='succeeded')) AND num_nonnulls(result_bio_processed_dataset_version_id,result_bio_figure_version_id)<=1 AND (num_nonnulls(result_bio_processed_dataset_version_id,result_bio_figure_version_id)=0 OR num_nonnulls(result_bio_dataset_version_id,result_analysis_run_id,result_report_id,result_explanation_id,result_figure_id)=0)", 'tasks_bio_analysis_snapshot_check': "(task_type<>'bio_analysis' AND task_type<>'bio_figure') OR ((workflow_version=task_type||'_v1' AND input_snapshot->'schema_version'='1'::jsonb AND input_snapshot->>'kind'=task_type AND input_snapshot->>'workflow_version'=workflow_version AND input_snapshot->>'project_id'=project_id AND input_snapshot->>'engine_version'='visium_explore_v1.0.0' AND (input_snapshot->>'environment_digest') ~ '^[0-9a-f]{64}$' AND (input_snapshot->>'code_digest') ~ '^[0-9a-f]{64}$' AND jsonb_typeof(input_snapshot->'limits')='object') IS TRUE)"}
WAIT_CHECK="kind IN ('bio_analysis_confirmation','bio_import_confirmation','budget_confirmation','submission_unknown','unsupported_input','unsupported_confirmation','dataset_preparation_confirmation','ocr_review_confirmation','analysis_plan_confirmation','analysis_plan_input','figure_projection_confirmation','remote_observation','literature_configuration','literature_model_authorization','review_round_confirmation','review_round_input')"

def upgrade():
    op.execute("SET LOCAL lock_timeout='3s'")
    for statement in CREATE_TABLE_SQL:
        op.execute(sa.text(statement))
    for column,table,name in [('result_bio_processed_dataset_version_id','bio_processed_dataset_versions','tasks_bio_processed_result_fk'),('result_bio_figure_version_id','bio_figure_versions','tasks_bio_figure_result_fk')]:
        op.add_column('tasks',sa.Column(column,sa.Text))
        op.create_foreign_key(name,'tasks',table,[column,'project_id'],['id','project_id'])
    op.drop_constraint('tasks_type_check','tasks',type_='check')
    op.create_check_constraint('tasks_type_check','tasks','task_type IN ('+TASK_TYPES+')')
    op.drop_constraint('tasks_bio_snapshot_check','tasks',type_='check')
    op.create_check_constraint('tasks_bio_snapshot_check','tasks',"task_type<>'bio_import' OR ((workflow_version IN ('bio_import_v1','bio_import_v2') AND input_snapshot->'schema_version'='1'::jsonb AND input_snapshot->>'kind'='bio_import' AND input_snapshot->>'workflow_version'=workflow_version AND (workflow_version='bio_import_v1' OR (input_snapshot->>'parser_version'='geo_visium_import_v2' AND input_snapshot->>'matrix_representation' IN ('mtx','10x_h5') AND input_snapshot->'compare_alternate' IN ('true'::jsonb,'false'::jsonb) AND jsonb_typeof(input_snapshot->'analysis_limits')='object' AND input_snapshot->>'engine_version'='visium_explore_v1.0.0' AND (input_snapshot->>'environment_digest') ~ '^[0-9a-f]{64}$' AND (input_snapshot->>'code_digest') ~ '^[0-9a-f]{64}$')) AND input_snapshot->>'project_id'=project_id AND jsonb_typeof(input_snapshot->'files')='array' AND jsonb_array_length(input_snapshot->'files')>=1 AND jsonb_array_length(input_snapshot->'files')<=10 AND jsonb_typeof(input_snapshot->'settings')='object') IS TRUE)")
    for name,expression in TASK_CHECKS.items():op.create_check_constraint(name,'tasks',expression)
    op.drop_constraint('task_waits_kind_check','task_waits',type_='check')
    op.create_check_constraint('task_waits_kind_check','task_waits',WAIT_CHECK)
    op.execute("""CREATE FUNCTION bio_analysis_snapshot_seal() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'Immutable bio analysis snapshot'; END $$""")
    for table in IMMUTABLE:
        op.execute(f'CREATE TRIGGER bio_analysis_snapshot_seal BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION bio_analysis_snapshot_seal()')
    op.execute("""CREATE FUNCTION bio_analysis_publish_seal() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Immutable bio publication'; END IF;
      IF TG_TABLE_NAME='bio_analysis_runs' THEN
        IF (to_jsonb(OLD)-'processed_dataset_version_id')=(to_jsonb(NEW)-'processed_dataset_version_id')
          AND (OLD.processed_dataset_version_id IS NULL OR OLD.processed_dataset_version_id IS NOT DISTINCT FROM NEW.processed_dataset_version_id)
          THEN RETURN NEW; END IF;
      ELSE
        IF (to_jsonb(OLD)-'manifest_object_id'-'manifest_sha256')=(to_jsonb(NEW)-'manifest_object_id'-'manifest_sha256')
          AND (OLD.manifest_object_id IS NULL OR (OLD.manifest_object_id IS NOT DISTINCT FROM NEW.manifest_object_id AND OLD.manifest_sha256 IS NOT DISTINCT FROM NEW.manifest_sha256))
          THEN RETURN NEW; END IF;
      END IF;
      RAISE EXCEPTION 'Immutable bio publication'; END $$""")
    for table in ('bio_analysis_runs','bio_figure_versions'):
        op.execute(f'CREATE TRIGGER bio_analysis_publish_seal BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION bio_analysis_publish_seal()')
    op.execute("""CREATE FUNCTION bio_annotation_evidence_scope() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE source bio_annotation_versions%ROWTYPE; artifact bio_analysis_artifacts%ROWTYPE;
      BEGIN SELECT * INTO source FROM bio_annotation_versions WHERE id=NEW.annotation_version_id AND project_id=NEW.project_id;
        IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(source.labels_json) l WHERE l->>'id'=NEW.label_id)
          OR (SELECT count(*) FROM bio_annotation_evidence WHERE annotation_version_id=NEW.annotation_version_id)>=200
          THEN RAISE EXCEPTION 'Invalid annotation evidence label'; END IF;
        IF NEW.kind='marker' THEN
          SELECT * INTO artifact FROM bio_analysis_artifacts WHERE id=NEW.analysis_artifact_id AND project_id=NEW.project_id;
          IF NOT FOUND OR source.processed_dataset_version_id IS DISTINCT FROM artifact.processed_dataset_version_id
            OR artifact.role<>'marker_table' THEN RAISE EXCEPTION 'Invalid annotation marker scope'; END IF;
        END IF;
        RETURN NEW;
      END $$""")
    op.execute('CREATE TRIGGER bio_annotation_evidence_scope BEFORE INSERT ON bio_annotation_evidence FOR EACH ROW EXECUTE FUNCTION bio_annotation_evidence_scope()')
    op.execute("""CREATE FUNCTION bio_analysis_root_seal() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Immutable bio root'; END IF;
        IF (NEW.revision<>OLD.revision+1 AND NOT (NEW.revision=OLD.revision AND COALESCE(to_jsonb(OLD)->>'current_version_id',to_jsonb(OLD)->>'current_recipe_version_id') IS NULL)) OR (to_jsonb(OLD)-'revision'-'name'-'current_version_id'-'current_recipe_version_id'-'updated_at')
          IS DISTINCT FROM (to_jsonb(NEW)-'revision'-'name'-'current_version_id'-'current_recipe_version_id'-'updated_at')
          THEN RAISE EXCEPTION 'Invalid bio root CAS'; END IF;
        RETURN NEW;
      END $$""")
    for table in ('bio_observation_map_sets','bio_analysis_setups','bio_annotation_sets'):
        op.execute(f'CREATE TRIGGER bio_analysis_root_seal BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION bio_analysis_root_seal()')
    # Direct project scope blocks producers while any incomplete deletion is active.
    # File references are additionally retained by normalized FKs and lifecycle reads.
    for table in TABLE_NAMES:
        op.execute(f'''CREATE FUNCTION storage_guard_{table}() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN IF EXISTS(SELECT 1 FROM storage_deletion_operations o WHERE o.project_id=NEW.project_id
            AND o.state<>'preview' AND (o.scope_kind='project' OR o.state IN ('running','partial_failed')
              OR EXISTS(SELECT 1 FROM storage_deletion_items i WHERE i.operation_id=o.id AND i.state NOT IN ('retained','deleted'))))
            THEN RAISE EXCEPTION USING ERRCODE='P7501',MESSAGE='storage_deletion_pending'; END IF;
          RETURN NEW; END $$''')
        op.execute(f'CREATE TRIGGER storage_deletion_guard BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION storage_guard_{table}()')


def downgrade():
    bind=op.get_bind()
    for table in TABLE_NAMES:
        if bind.exec_driver_sql(f'SELECT EXISTS(SELECT 1 FROM {table})').scalar_one():
            raise RuntimeError('Bio analysis data exists; refusing destructive downgrade.')
    if bind.exec_driver_sql("SELECT EXISTS(SELECT 1 FROM tasks WHERE task_type IN ('bio_analysis','bio_figure'))").scalar_one():
        raise RuntimeError('Bio analysis tasks exist; refusing destructive downgrade.')
    # Even empty tables may carry external audited FKs; require an explicit restore plan.
    raise RuntimeError('Bio analysis downgrade requires explicit reviewed database restore; tables preserved.')


"""Frozen CR-B03 bridge DDL; never imports mutable application metadata."""
from alembic import op
import sqlalchemy as sa
revision='0060_research_results_bridge'
down_revision='0059_bio_spatial_analysis'
branch_labels=None
depends_on=None
TABLE_NAMES=('research_finding_sets', 'research_finding_versions', 'research_figure_versions', 'research_figure_members', 'research_report_versions', 'research_report_members', 'research_source_bindings', 'manuscript_research_sources', 'research_manuscript_candidates')
IMMUTABLE=('research_finding_versions', 'research_figure_members', 'research_report_members', 'research_source_bindings', 'manuscript_research_sources')
CREATE_TABLE_SQL=(
    """CREATE TABLE research_finding_sets (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	user_id TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	schema_version INTEGER DEFAULT '1' NOT NULL,
	title TEXT NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	current_version_id TEXT,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT b03_ck_9f93d6a7936e15c7 CHECK (revision>=1 AND length(title) BETWEEN 1 AND 200 AND updated_at>=created_at),
	UNIQUE (id, project_id),
	UNIQUE (id, project_id, user_id),
	CONSTRAINT b03_scope_fk_2 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id),
	CONSTRAINT b03_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX research_finding_sets_current_version_id ON research_finding_sets (current_version_id)""",
    """CREATE INDEX research_finding_sets_project_created ON research_finding_sets (project_id, created_at DESC, id)""",
    """CREATE TABLE research_figure_versions (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	user_id TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	schema_version INTEGER DEFAULT '1' NOT NULL,
	root_id TEXT NOT NULL,
	revision INTEGER NOT NULL,
	parent_id TEXT,
	task_id TEXT NOT NULL,
	config_json JSONB NOT NULL,
	config_sha256 TEXT NOT NULL,
	manifest_object_id TEXT,
	manifest_sha256 TEXT,
	request_key TEXT NOT NULL,
	request_digest TEXT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (root_id, revision),
	UNIQUE (id, root_id, project_id),
	CONSTRAINT b03_scope_fk_8 FOREIGN KEY(parent_id, root_id, project_id) REFERENCES research_figure_versions (id, root_id, project_id),
	CONSTRAINT b03_ck_bf91c18482cf5c6f CHECK (revision>=1 AND ((revision=1 AND parent_id IS NULL) OR (revision>1 AND parent_id IS NOT NULL))),
	CONSTRAINT b03_scope_fk_9 FOREIGN KEY(task_id, project_id, user_id) REFERENCES tasks (id, project_id, user_id),
	UNIQUE (task_id),
	UNIQUE (id, task_id, project_id),
	CONSTRAINT b03_scope_fk_10 FOREIGN KEY(root_id, project_id) REFERENCES research_figure_versions (id, project_id),
	CONSTRAINT b03_ck_c9a04fb1a44305eb CHECK (revision<>1 OR root_id=id),
	CONSTRAINT b03_ck_ad44858aa6bd0f77 CHECK (jsonb_typeof(config_json)='object' AND octet_length(config_json::text)<=4194304),
	CONSTRAINT b03_scope_fk_11 FOREIGN KEY(manifest_object_id, project_id) REFERENCES storage_references (object_id, project_id),
	UNIQUE (project_id, user_id, request_key),
	CONSTRAINT b03_ck_62891f2d471e332a CHECK (request_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT b03_ck_5f4c1dfeba74bd27 CHECK (config_sha256 ~ '^[0-9a-f]{64}$' AND ((manifest_object_id IS NULL AND manifest_sha256 IS NULL) OR (manifest_object_id IS NOT NULL AND manifest_sha256 IS NOT NULL AND manifest_sha256 ~ '^[0-9a-f]{64}$'))),
	UNIQUE (id, project_id),
	UNIQUE (id, project_id, user_id),
	CONSTRAINT b03_scope_fk_12 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id),
	CONSTRAINT b03_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX research_figure_versions_manifest_object_id ON research_figure_versions (manifest_object_id)""",
    """CREATE INDEX research_figure_versions_parent_id ON research_figure_versions (parent_id)""",
    """CREATE INDEX research_figure_versions_project_created ON research_figure_versions (project_id, created_at DESC, id)""",
    """CREATE INDEX research_figure_versions_root_id ON research_figure_versions (root_id)""",
    """CREATE INDEX research_figure_versions_task_id ON research_figure_versions (task_id)""",
    """CREATE TABLE research_manuscript_candidates (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	user_id TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	schema_version INTEGER DEFAULT '1' NOT NULL,
	delivery_id TEXT NOT NULL,
	manuscript_id TEXT,
	base_version_id TEXT,
	expected_revision INTEGER NOT NULL,
	task_id TEXT NOT NULL,
	scope_json JSONB NOT NULL,
	candidate_json JSONB,
	candidate_sha256 TEXT,
	published_version_id TEXT,
	publish_key TEXT,
	request_key TEXT NOT NULL,
	request_digest TEXT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT b03_scope_fk_47 FOREIGN KEY(delivery_id, project_id) REFERENCES research_deliveries (id, project_id),
	CONSTRAINT b03_scope_fk_48 FOREIGN KEY(manuscript_id, project_id, user_id, delivery_id) REFERENCES manuscripts (id, project_id, user_id, delivery_id),
	CONSTRAINT b03_scope_fk_49 FOREIGN KEY(base_version_id, manuscript_id, project_id, user_id, expected_revision) REFERENCES manuscript_versions (id, manuscript_id, project_id, user_id, revision),
	CONSTRAINT b03_scope_fk_50 FOREIGN KEY(task_id, project_id, user_id) REFERENCES tasks (id, project_id, user_id),
	UNIQUE (task_id),
	UNIQUE (id, task_id, project_id),
	CONSTRAINT b03_ck_e7f26aea1a98e9a5 CHECK (jsonb_typeof(scope_json)='object' AND octet_length(scope_json::text)<=4194304),
	CONSTRAINT b03_ck_e12facbb0389efeb CHECK (candidate_json IS NULL OR (jsonb_typeof(candidate_json)='object' AND octet_length(candidate_json::text)<=4194304)),
	UNIQUE (project_id, user_id, request_key),
	CONSTRAINT b03_ck_62891f2d471e332a CHECK (request_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT b03_scope_fk_51 FOREIGN KEY(published_version_id, project_id, user_id) REFERENCES manuscript_versions (id, project_id, user_id),
	UNIQUE (project_id, user_id, publish_key),
	UNIQUE (published_version_id),
	CONSTRAINT b03_ck_9a745f43713c8941 CHECK (((manuscript_id IS NULL AND base_version_id IS NULL AND expected_revision=0) OR (manuscript_id IS NOT NULL AND base_version_id IS NOT NULL AND expected_revision>=1)) AND ((candidate_json IS NULL AND candidate_sha256 IS NULL) OR (candidate_json IS NOT NULL AND candidate_sha256 IS NOT NULL AND candidate_sha256 ~ '^[0-9a-f]{64}$')) AND ((published_version_id IS NULL AND publish_key IS NULL) OR (published_version_id IS NOT NULL AND publish_key IS NOT NULL AND publish_key ~ '^[!-~]{1,128}$' AND candidate_json IS NOT NULL))),
	UNIQUE (id, project_id),
	UNIQUE (id, project_id, user_id),
	CONSTRAINT b03_scope_fk_52 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id),
	CONSTRAINT b03_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX research_manuscript_candidates_base_version_id ON research_manuscript_candidates (base_version_id)""",
    """CREATE INDEX research_manuscript_candidates_delivery_id ON research_manuscript_candidates (delivery_id)""",
    """CREATE INDEX research_manuscript_candidates_manuscript_id ON research_manuscript_candidates (manuscript_id)""",
    """CREATE INDEX research_manuscript_candidates_project_created ON research_manuscript_candidates (project_id, created_at DESC, id)""",
    """CREATE INDEX research_manuscript_candidates_published_version_id ON research_manuscript_candidates (published_version_id)""",
    """CREATE INDEX research_manuscript_candidates_task_id ON research_manuscript_candidates (task_id)""",
    """CREATE TABLE research_finding_versions (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	user_id TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	schema_version INTEGER DEFAULT '1' NOT NULL,
	set_id TEXT NOT NULL,
	revision INTEGER NOT NULL,
	parent_id TEXT,
	requirement_version_id TEXT,
	design_version_id TEXT,
	content_json JSONB NOT NULL,
	content_sha256 TEXT NOT NULL,
	request_key TEXT NOT NULL,
	request_digest TEXT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (set_id, revision),
	UNIQUE (id, set_id, project_id),
	CONSTRAINT b03_scope_fk_3 FOREIGN KEY(parent_id, set_id, project_id) REFERENCES research_finding_versions (id, set_id, project_id),
	CONSTRAINT b03_ck_bf91c18482cf5c6f CHECK (revision>=1 AND ((revision=1 AND parent_id IS NULL) OR (revision>1 AND parent_id IS NOT NULL))),
	CONSTRAINT b03_scope_fk_4 FOREIGN KEY(set_id, project_id) REFERENCES research_finding_sets (id, project_id),
	CONSTRAINT b03_scope_fk_5 FOREIGN KEY(requirement_version_id, project_id) REFERENCES research_requirement_versions (id, project_id),
	CONSTRAINT b03_scope_fk_6 FOREIGN KEY(design_version_id, project_id) REFERENCES research_design_versions (id, project_id),
	CONSTRAINT b03_ck_676920f7af6c8cc4 CHECK (jsonb_typeof(content_json)='object' AND octet_length(content_json::text)<=4194304),
	UNIQUE (project_id, user_id, request_key),
	CONSTRAINT b03_ck_62891f2d471e332a CHECK (request_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT b03_ck_bd00c85db891f848 CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
	UNIQUE (id, project_id),
	UNIQUE (id, project_id, user_id),
	CONSTRAINT b03_scope_fk_7 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id),
	CONSTRAINT b03_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX research_finding_versions_design_version_id ON research_finding_versions (design_version_id)""",
    """CREATE INDEX research_finding_versions_parent_id ON research_finding_versions (parent_id)""",
    """CREATE INDEX research_finding_versions_project_created ON research_finding_versions (project_id, created_at DESC, id)""",
    """CREATE INDEX research_finding_versions_requirement_version_id ON research_finding_versions (requirement_version_id)""",
    """CREATE INDEX research_finding_versions_set_id ON research_finding_versions (set_id)""",
    """CREATE TABLE research_figure_members (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	user_id TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	schema_version INTEGER DEFAULT '1' NOT NULL,
	figure_version_id TEXT NOT NULL,
	key TEXT NOT NULL,
	role TEXT NOT NULL,
	format TEXT NOT NULL,
	storage_object_id TEXT NOT NULL,
	sha256 TEXT NOT NULL,
	size_bytes BIGINT NOT NULL,
	properties_json JSONB NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT b03_scope_fk_19 FOREIGN KEY(figure_version_id, project_id) REFERENCES research_figure_versions (id, project_id),
	CONSTRAINT b03_scope_fk_20 FOREIGN KEY(storage_object_id, project_id) REFERENCES storage_references (object_id, project_id),
	CONSTRAINT b03_ck_69d28c43bfb70fea CHECK (jsonb_typeof(properties_json)='object' AND octet_length(properties_json::text)<=4194304),
	UNIQUE (figure_version_id, key),
	UNIQUE (id, figure_version_id, project_id),
	CONSTRAINT b03_ck_d2cd3220ac58edd7 CHECK (size_bytes>=0 AND sha256 ~ '^[0-9a-f]{64}$' AND key ~ '^[A-Za-z0-9_-]{1,100}$' AND length(role) BETWEEN 1 AND 100 AND length(format) BETWEEN 1 AND 20),
	UNIQUE (id, project_id),
	UNIQUE (id, project_id, user_id),
	CONSTRAINT b03_scope_fk_21 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id),
	CONSTRAINT b03_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX research_figure_members_figure_version_id ON research_figure_members (figure_version_id)""",
    """CREATE INDEX research_figure_members_project_created ON research_figure_members (project_id, created_at DESC, id)""",
    """CREATE INDEX research_figure_members_storage_object_id ON research_figure_members (storage_object_id)""",
    """CREATE TABLE research_report_versions (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	user_id TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	schema_version INTEGER DEFAULT '1' NOT NULL,
	root_id TEXT NOT NULL,
	revision INTEGER NOT NULL,
	parent_id TEXT,
	task_id TEXT NOT NULL,
	finding_version_id TEXT NOT NULL,
	language TEXT NOT NULL,
	content_json JSONB NOT NULL,
	content_sha256 TEXT NOT NULL,
	manifest_object_id TEXT,
	manifest_sha256 TEXT,
	request_key TEXT NOT NULL,
	request_digest TEXT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (root_id, revision),
	UNIQUE (id, root_id, project_id),
	CONSTRAINT b03_scope_fk_13 FOREIGN KEY(parent_id, root_id, project_id) REFERENCES research_report_versions (id, root_id, project_id),
	CONSTRAINT b03_ck_bf91c18482cf5c6f CHECK (revision>=1 AND ((revision=1 AND parent_id IS NULL) OR (revision>1 AND parent_id IS NOT NULL))),
	CONSTRAINT b03_scope_fk_14 FOREIGN KEY(task_id, project_id, user_id) REFERENCES tasks (id, project_id, user_id),
	UNIQUE (task_id),
	UNIQUE (id, task_id, project_id),
	CONSTRAINT b03_scope_fk_15 FOREIGN KEY(root_id, project_id) REFERENCES research_report_versions (id, project_id),
	CONSTRAINT b03_ck_c9a04fb1a44305eb CHECK (revision<>1 OR root_id=id),
	CONSTRAINT b03_scope_fk_16 FOREIGN KEY(finding_version_id, project_id) REFERENCES research_finding_versions (id, project_id),
	CONSTRAINT b03_ck_676920f7af6c8cc4 CHECK (jsonb_typeof(content_json)='object' AND octet_length(content_json::text)<=4194304),
	CONSTRAINT b03_scope_fk_17 FOREIGN KEY(manifest_object_id, project_id) REFERENCES storage_references (object_id, project_id),
	UNIQUE (project_id, user_id, request_key),
	CONSTRAINT b03_ck_62891f2d471e332a CHECK (request_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT b03_ck_a01802eb6f6b312b CHECK (language IN ('zh-CN','en') AND content_sha256 ~ '^[0-9a-f]{64}$' AND ((manifest_object_id IS NULL AND manifest_sha256 IS NULL) OR (manifest_object_id IS NOT NULL AND manifest_sha256 IS NOT NULL AND manifest_sha256 ~ '^[0-9a-f]{64}$'))),
	UNIQUE (id, project_id),
	UNIQUE (id, project_id, user_id),
	CONSTRAINT b03_scope_fk_18 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id),
	CONSTRAINT b03_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX research_report_versions_finding_version_id ON research_report_versions (finding_version_id)""",
    """CREATE INDEX research_report_versions_manifest_object_id ON research_report_versions (manifest_object_id)""",
    """CREATE INDEX research_report_versions_parent_id ON research_report_versions (parent_id)""",
    """CREATE INDEX research_report_versions_project_created ON research_report_versions (project_id, created_at DESC, id)""",
    """CREATE INDEX research_report_versions_root_id ON research_report_versions (root_id)""",
    """CREATE INDEX research_report_versions_task_id ON research_report_versions (task_id)""",
    """CREATE TABLE research_report_members (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	user_id TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	schema_version INTEGER DEFAULT '1' NOT NULL,
	report_version_id TEXT NOT NULL,
	key TEXT NOT NULL,
	role TEXT NOT NULL,
	format TEXT NOT NULL,
	storage_object_id TEXT NOT NULL,
	sha256 TEXT NOT NULL,
	size_bytes BIGINT NOT NULL,
	properties_json JSONB NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT b03_scope_fk_22 FOREIGN KEY(report_version_id, project_id) REFERENCES research_report_versions (id, project_id),
	CONSTRAINT b03_scope_fk_23 FOREIGN KEY(storage_object_id, project_id) REFERENCES storage_references (object_id, project_id),
	CONSTRAINT b03_ck_69d28c43bfb70fea CHECK (jsonb_typeof(properties_json)='object' AND octet_length(properties_json::text)<=4194304),
	UNIQUE (report_version_id, key),
	UNIQUE (id, report_version_id, project_id),
	CONSTRAINT b03_ck_d2cd3220ac58edd7 CHECK (size_bytes>=0 AND sha256 ~ '^[0-9a-f]{64}$' AND key ~ '^[A-Za-z0-9_-]{1,100}$' AND length(role) BETWEEN 1 AND 100 AND length(format) BETWEEN 1 AND 20),
	UNIQUE (id, project_id),
	UNIQUE (id, project_id, user_id),
	CONSTRAINT b03_scope_fk_24 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id),
	CONSTRAINT b03_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX research_report_members_project_created ON research_report_members (project_id, created_at DESC, id)""",
    """CREATE INDEX research_report_members_report_version_id ON research_report_members (report_version_id)""",
    """CREATE INDEX research_report_members_storage_object_id ON research_report_members (storage_object_id)""",
    """CREATE TABLE research_source_bindings (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	user_id TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	schema_version INTEGER DEFAULT '1' NOT NULL,
	parent_kind TEXT NOT NULL,
	finding_version_id TEXT,
	figure_version_id TEXT,
	report_version_id TEXT,
	source_kind TEXT NOT NULL,
	source_id TEXT NOT NULL,
	processed_version_id TEXT,
	analysis_artifact_id TEXT,
	bio_figure_version_id TEXT,
	file_id TEXT,
	external_evidence_version_id TEXT,
	source_finding_version_id TEXT,
	research_figure_version_id TEXT,
	source_report_version_id TEXT,
	locator_json JSONB NOT NULL,
	source_sha256 TEXT NOT NULL,
	role TEXT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT b03_scope_fk_25 FOREIGN KEY(finding_version_id, project_id) REFERENCES research_finding_versions (id, project_id),
	CONSTRAINT b03_scope_fk_26 FOREIGN KEY(figure_version_id, project_id) REFERENCES research_figure_versions (id, project_id),
	CONSTRAINT b03_scope_fk_27 FOREIGN KEY(report_version_id, project_id) REFERENCES research_report_versions (id, project_id),
	CONSTRAINT b03_scope_fk_28 FOREIGN KEY(processed_version_id, project_id) REFERENCES bio_processed_dataset_versions (id, project_id),
	CONSTRAINT b03_scope_fk_29 FOREIGN KEY(analysis_artifact_id, project_id) REFERENCES bio_analysis_artifacts (id, project_id),
	CONSTRAINT b03_scope_fk_30 FOREIGN KEY(bio_figure_version_id, project_id) REFERENCES bio_figure_versions (id, project_id),
	CONSTRAINT b03_scope_fk_31 FOREIGN KEY(file_id, project_id) REFERENCES files (id, project_id),
	CONSTRAINT b03_scope_fk_32 FOREIGN KEY(external_evidence_version_id, project_id) REFERENCES external_evidence_versions (id, project_id),
	CONSTRAINT b03_scope_fk_33 FOREIGN KEY(source_finding_version_id, project_id) REFERENCES research_finding_versions (id, project_id),
	CONSTRAINT b03_scope_fk_34 FOREIGN KEY(research_figure_version_id, project_id) REFERENCES research_figure_versions (id, project_id),
	CONSTRAINT b03_scope_fk_35 FOREIGN KEY(source_report_version_id, project_id) REFERENCES research_report_versions (id, project_id),
	CONSTRAINT b03_ck_2be404256e3b67e4 CHECK (num_nonnulls(processed_version_id,analysis_artifact_id,bio_figure_version_id,file_id,external_evidence_version_id,source_finding_version_id,research_figure_version_id,source_report_version_id)=1 AND ((source_kind='bio_processed_dataset_version' AND processed_version_id IS NOT NULL AND source_id=processed_version_id) OR (source_kind='bio_analysis_artifact' AND analysis_artifact_id IS NOT NULL AND source_id=analysis_artifact_id) OR (source_kind='bio_figure_version' AND bio_figure_version_id IS NOT NULL AND source_id=bio_figure_version_id) OR (source_kind='original_file' AND file_id IS NOT NULL AND source_id=file_id) OR (source_kind='external_evidence_version' AND external_evidence_version_id IS NOT NULL AND source_id=external_evidence_version_id) OR (source_kind='research_finding_version' AND source_finding_version_id IS NOT NULL AND source_id=source_finding_version_id) OR (source_kind='research_figure_version' AND research_figure_version_id IS NOT NULL AND source_id=research_figure_version_id) OR (source_kind='research_report_version' AND source_report_version_id IS NOT NULL AND source_id=source_report_version_id))),
	CONSTRAINT b03_ck_3a5a7e8c34fb6647 CHECK (jsonb_typeof(locator_json)='object' AND octet_length(locator_json::text)<=4194304),
	CONSTRAINT b03_ck_551962bc0caf186a CHECK (source_sha256 ~ '^[0-9a-f]{64}$' AND length(role) BETWEEN 1 AND 100),
	CONSTRAINT b03_ck_2bcf7cb175833680 CHECK (num_nonnulls(finding_version_id,figure_version_id,report_version_id)=1 AND ((parent_kind='finding' AND finding_version_id IS NOT NULL) OR (parent_kind='figure' AND figure_version_id IS NOT NULL) OR (parent_kind='report' AND report_version_id IS NOT NULL))),
	UNIQUE (id, project_id),
	UNIQUE (id, project_id, user_id),
	CONSTRAINT b03_scope_fk_36 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id),
	CONSTRAINT b03_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX research_source_bindings_analysis_artifact_id ON research_source_bindings (analysis_artifact_id)""",
    """CREATE INDEX research_source_bindings_bio_figure_version_id ON research_source_bindings (bio_figure_version_id)""",
    """CREATE INDEX research_source_bindings_external_evidence_version_id ON research_source_bindings (external_evidence_version_id)""",
    """CREATE INDEX research_source_bindings_figure_version_id ON research_source_bindings (figure_version_id)""",
    """CREATE INDEX research_source_bindings_file_id ON research_source_bindings (file_id)""",
    """CREATE INDEX research_source_bindings_finding_version_id ON research_source_bindings (finding_version_id)""",
    """CREATE INDEX research_source_bindings_processed_version_id ON research_source_bindings (processed_version_id)""",
    """CREATE INDEX research_source_bindings_project_created ON research_source_bindings (project_id, created_at DESC, id)""",
    """CREATE INDEX research_source_bindings_report_version_id ON research_source_bindings (report_version_id)""",
    """CREATE INDEX research_source_bindings_research_figure_version_id ON research_source_bindings (research_figure_version_id)""",
    """CREATE INDEX research_source_bindings_source_finding_version_id ON research_source_bindings (source_finding_version_id)""",
    """CREATE INDEX research_source_bindings_source_id ON research_source_bindings (source_id)""",
    """CREATE INDEX research_source_bindings_source_report_version_id ON research_source_bindings (source_report_version_id)""",
    """CREATE TABLE manuscript_research_sources (
	id TEXT NOT NULL,
	project_id TEXT NOT NULL,
	user_id TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	schema_version INTEGER DEFAULT '1' NOT NULL,
	version_id TEXT NOT NULL,
	source_kind TEXT NOT NULL,
	source_id TEXT NOT NULL,
	processed_version_id TEXT,
	analysis_artifact_id TEXT,
	bio_figure_version_id TEXT,
	file_id TEXT,
	external_evidence_version_id TEXT,
	source_finding_version_id TEXT,
	research_figure_version_id TEXT,
	source_report_version_id TEXT,
	role TEXT NOT NULL,
	source_json JSONB NOT NULL,
	sha256 TEXT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT b03_scope_fk_37 FOREIGN KEY(version_id, project_id, user_id) REFERENCES manuscript_versions (id, project_id, user_id),
	CONSTRAINT b03_scope_fk_38 FOREIGN KEY(processed_version_id, project_id) REFERENCES bio_processed_dataset_versions (id, project_id),
	CONSTRAINT b03_scope_fk_39 FOREIGN KEY(analysis_artifact_id, project_id) REFERENCES bio_analysis_artifacts (id, project_id),
	CONSTRAINT b03_scope_fk_40 FOREIGN KEY(bio_figure_version_id, project_id) REFERENCES bio_figure_versions (id, project_id),
	CONSTRAINT b03_scope_fk_41 FOREIGN KEY(file_id, project_id) REFERENCES files (id, project_id),
	CONSTRAINT b03_scope_fk_42 FOREIGN KEY(external_evidence_version_id, project_id) REFERENCES external_evidence_versions (id, project_id),
	CONSTRAINT b03_scope_fk_43 FOREIGN KEY(source_finding_version_id, project_id) REFERENCES research_finding_versions (id, project_id),
	CONSTRAINT b03_scope_fk_44 FOREIGN KEY(research_figure_version_id, project_id) REFERENCES research_figure_versions (id, project_id),
	CONSTRAINT b03_scope_fk_45 FOREIGN KEY(source_report_version_id, project_id) REFERENCES research_report_versions (id, project_id),
	CONSTRAINT b03_ck_2be404256e3b67e4 CHECK (num_nonnulls(processed_version_id,analysis_artifact_id,bio_figure_version_id,file_id,external_evidence_version_id,source_finding_version_id,research_figure_version_id,source_report_version_id)=1 AND ((source_kind='bio_processed_dataset_version' AND processed_version_id IS NOT NULL AND source_id=processed_version_id) OR (source_kind='bio_analysis_artifact' AND analysis_artifact_id IS NOT NULL AND source_id=analysis_artifact_id) OR (source_kind='bio_figure_version' AND bio_figure_version_id IS NOT NULL AND source_id=bio_figure_version_id) OR (source_kind='original_file' AND file_id IS NOT NULL AND source_id=file_id) OR (source_kind='external_evidence_version' AND external_evidence_version_id IS NOT NULL AND source_id=external_evidence_version_id) OR (source_kind='research_finding_version' AND source_finding_version_id IS NOT NULL AND source_id=source_finding_version_id) OR (source_kind='research_figure_version' AND research_figure_version_id IS NOT NULL AND source_id=research_figure_version_id) OR (source_kind='research_report_version' AND source_report_version_id IS NOT NULL AND source_id=source_report_version_id))),
	CONSTRAINT b03_ck_a0356f9633bbe841 CHECK (jsonb_typeof(source_json)='object' AND octet_length(source_json::text)<=4194304),
	UNIQUE (version_id, source_kind, source_id),
	CONSTRAINT b03_ck_06aa40e531136913 CHECK (sha256 ~ '^[0-9a-f]{64}$' AND role IN ('methods','user_results','image_observation','computed_results')),
	UNIQUE (id, project_id),
	UNIQUE (id, project_id, user_id),
	CONSTRAINT b03_scope_fk_46 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id),
	CONSTRAINT b03_ck_69833c9624be0c21 CHECK (schema_version=1)
)""",
    """CREATE INDEX manuscript_research_sources_analysis_artifact_id ON manuscript_research_sources (analysis_artifact_id)""",
    """CREATE INDEX manuscript_research_sources_bio_figure_version_id ON manuscript_research_sources (bio_figure_version_id)""",
    """CREATE INDEX manuscript_research_sources_external_evidence_version_id ON manuscript_research_sources (external_evidence_version_id)""",
    """CREATE INDEX manuscript_research_sources_file_id ON manuscript_research_sources (file_id)""",
    """CREATE INDEX manuscript_research_sources_processed_version_id ON manuscript_research_sources (processed_version_id)""",
    """CREATE INDEX manuscript_research_sources_project_created ON manuscript_research_sources (project_id, created_at DESC, id)""",
    """CREATE INDEX manuscript_research_sources_research_figure_version_id ON manuscript_research_sources (research_figure_version_id)""",
    """CREATE INDEX manuscript_research_sources_source_finding_version_id ON manuscript_research_sources (source_finding_version_id)""",
    """CREATE INDEX manuscript_research_sources_source_id ON manuscript_research_sources (source_id)""",
    """CREATE INDEX manuscript_research_sources_source_report_version_id ON manuscript_research_sources (source_report_version_id)""",
    """CREATE INDEX manuscript_research_sources_version_id ON manuscript_research_sources (version_id)""",
    """ALTER TABLE research_finding_sets ADD CONSTRAINT b03_scope_fk_1 FOREIGN KEY(current_version_id, id, project_id) REFERENCES research_finding_versions (id, set_id, project_id)""",
)
PRE_SQL=(
    """ALTER TABLE manuscripts ADD COLUMN delivery_id TEXT""",
    """ALTER TABLE manuscripts ADD COLUMN document_kind TEXT""",
    """ALTER TABLE manuscripts ADD CONSTRAINT b03_manuscript_delivery_check CHECK ((delivery_id IS NULL AND document_kind IS NULL) OR (delivery_id IS NOT NULL AND document_kind IN ('sci','thesis')))""",
    """ALTER TABLE manuscripts ADD CONSTRAINT b03_manuscript_delivery_key UNIQUE (id, project_id, user_id, delivery_id)""",
    """ALTER TABLE manuscripts ADD CONSTRAINT b03_manuscript_delivery_fk FOREIGN KEY(delivery_id, project_id) REFERENCES research_deliveries (id, project_id)""",
    """ALTER TABLE manuscript_versions ADD CONSTRAINT b03_mv_scope_key UNIQUE (id, project_id, user_id)""",
    """ALTER TABLE manuscript_versions ADD CONSTRAINT b03_mv_revision_scope_key UNIQUE (id, manuscript_id, project_id, user_id, revision)""",
    """ALTER TABLE external_evidence_versions ADD CONSTRAINT b03_evidence_project_key UNIQUE (id, project_id)""",
)
POST_SQL=(
    """ALTER TABLE tasks ADD COLUMN result_research_figure_version_id TEXT""",
    """ALTER TABLE tasks ADD COLUMN result_research_report_version_id TEXT""",
    """ALTER TABLE tasks ADD COLUMN result_research_candidate_id TEXT""",
    """ALTER TABLE pdf_exports ADD COLUMN research_report_member_id TEXT""",
    """ALTER TABLE tasks ADD CONSTRAINT b03_tasks_result_research_candidate_id_fk FOREIGN KEY(result_research_candidate_id, id, project_id) REFERENCES research_manuscript_candidates (id, task_id, project_id)""",
    """ALTER TABLE tasks ADD CONSTRAINT b03_tasks_result_research_figure_version_id_fk FOREIGN KEY(result_research_figure_version_id, id, project_id) REFERENCES research_figure_versions (id, task_id, project_id)""",
    """ALTER TABLE tasks ADD CONSTRAINT b03_tasks_result_research_report_version_id_fk FOREIGN KEY(result_research_report_version_id, id, project_id) REFERENCES research_report_versions (id, task_id, project_id)""",
    """ALTER TABLE tasks ADD CONSTRAINT b03_tasks_results_check CHECK ((result_research_figure_version_id IS NULL OR (task_type='research_figure' AND status='succeeded')) AND (result_research_report_version_id IS NULL OR (task_type='research_report' AND status='succeeded')) AND (result_research_candidate_id IS NULL OR (task_type='research_fact_draft' AND status='succeeded')) AND num_nonnulls(result_research_figure_version_id,result_research_report_version_id,result_research_candidate_id)<=1 AND (num_nonnulls(result_research_figure_version_id,result_research_report_version_id,result_research_candidate_id)=0 OR num_nonnulls(result_bio_dataset_version_id,result_bio_processed_dataset_version_id,result_bio_figure_version_id,result_analysis_run_id,result_report_id,result_explanation_id,result_figure_id)=0))""",
    """ALTER TABLE tasks ADD CONSTRAINT b03_tasks_snapshot_check CHECK ((task_type<>'research_figure' AND task_type<>'research_report' AND task_type<>'research_fact_draft') OR ((((task_type='research_fact_draft' AND workflow_version='research_results_methods_v1') OR ((task_type='research_figure' OR task_type='research_report') AND workflow_version=task_type||'_v1')) AND input_snapshot->'schema_version'='1'::jsonb AND input_snapshot->>'kind'=task_type AND input_snapshot->>'project_id'=project_id AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb) IS TRUE))""",
    """ALTER TABLE pdf_exports ADD CONSTRAINT b03_pdf_research_report_fk FOREIGN KEY(research_report_member_id, project_id, user_id) REFERENCES research_report_members (id, project_id, user_id)""",
    """ALTER TABLE tasks DROP CONSTRAINT tasks_type_check""",
    """ALTER TABLE tasks ADD CONSTRAINT tasks_type_check CHECK (task_type IN ('boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx', 'school_template_parse', 'school_rule_suggestion', 'journal_recommendation', 'journal_format_check', 'journal_adaptation', 'review_round_plan', 'review_revision', 'review_document_export', 'bio_import', 'bio_analysis', 'bio_figure', 'research_figure', 'research_report', 'research_fact_draft'))""",
    """ALTER TABLE pdf_exports DROP CONSTRAINT pdf_typed_source_check""",
    """ALTER TABLE pdf_exports ADD CONSTRAINT pdf_typed_source_check CHECK (num_nonnulls(report_id,collection_report_id,manuscript_export_id,layout_export_id,review_document_export_id,research_report_member_id)=1 AND ((source_kind='report' AND report_id IS NOT NULL AND source_id=report_id) OR (source_kind='collection_report' AND collection_report_id IS NOT NULL AND source_id=collection_report_id) OR (source_kind='manuscript_export' AND manuscript_export_id IS NOT NULL AND source_id=manuscript_export_id) OR (source_kind='layout_export' AND layout_export_id IS NOT NULL AND source_id=layout_export_id) OR (source_kind='research_report' AND research_report_member_id IS NOT NULL AND source_id=research_report_member_id) OR (source_kind='review_document_export' AND review_document_export_id IS NOT NULL AND source_id=review_document_export_id)))""",
)


def upgrade():
    op.execute("SET LOCAL lock_timeout='3s'")
    for statement in (*PRE_SQL,*CREATE_TABLE_SQL,*POST_SQL):
        op.execute(sa.text(statement))
    op.execute("""CREATE FUNCTION b03_snapshot_seal() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'Immutable research snapshot'; END $$""")
    for table in IMMUTABLE:
        op.execute(f'CREATE TRIGGER b03_snapshot_seal BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION b03_snapshot_seal()')
    op.execute("""CREATE FUNCTION b03_publication_seal() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Immutable research publication'; END IF;
        IF TG_TABLE_NAME='research_manuscript_candidates' THEN
          IF (to_jsonb(OLD)-'candidate_json'-'candidate_sha256'-'published_version_id'-'publish_key')
             IS DISTINCT FROM (to_jsonb(NEW)-'candidate_json'-'candidate_sha256'-'published_version_id'-'publish_key')
             OR (OLD.candidate_json IS NOT NULL AND (OLD.candidate_json IS DISTINCT FROM NEW.candidate_json OR OLD.candidate_sha256 IS DISTINCT FROM NEW.candidate_sha256))
             OR (OLD.published_version_id IS NOT NULL AND (OLD.published_version_id IS DISTINCT FROM NEW.published_version_id OR OLD.publish_key IS DISTINCT FROM NEW.publish_key))
            THEN RAISE EXCEPTION 'Immutable research candidate'; END IF;
        ELSE
          IF (to_jsonb(OLD)-'manifest_object_id'-'manifest_sha256') IS DISTINCT FROM (to_jsonb(NEW)-'manifest_object_id'-'manifest_sha256')
             OR (OLD.manifest_object_id IS NOT NULL AND (OLD.manifest_object_id IS DISTINCT FROM NEW.manifest_object_id OR OLD.manifest_sha256 IS DISTINCT FROM NEW.manifest_sha256))
            THEN RAISE EXCEPTION 'Immutable research publication'; END IF;
        END IF;
        RETURN NEW;
      END $$""")
    for table in ('research_figure_versions','research_report_versions','research_manuscript_candidates'):
        op.execute(f'CREATE TRIGGER b03_publication_seal BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION b03_publication_seal()')
    op.execute("""CREATE FUNCTION b03_finding_root_seal() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Immutable finding root'; END IF;
        IF (to_jsonb(OLD)-'title'-'revision'-'current_version_id'-'updated_at') IS DISTINCT FROM (to_jsonb(NEW)-'title'-'revision'-'current_version_id'-'updated_at')
           OR NOT (NEW.revision=OLD.revision+1 OR (OLD.current_version_id IS NULL AND NEW.revision=OLD.revision))
          THEN RAISE EXCEPTION 'Invalid finding root CAS'; END IF;
        IF NEW.current_version_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM research_finding_versions v WHERE v.id=NEW.current_version_id AND v.set_id=NEW.id AND v.revision=NEW.revision)
          THEN RAISE EXCEPTION 'Invalid finding root revision'; END IF;
        RETURN NEW;
      END $$""")
    op.execute('CREATE TRIGGER b03_finding_root_seal BEFORE UPDATE OR DELETE ON research_finding_sets FOR EACH ROW EXECUTE FUNCTION b03_finding_root_seal()')
    op.execute("""CREATE FUNCTION b03_version_lineage() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE parent_revision integer;
      BEGIN
        IF NEW.parent_id IS NOT NULL THEN
          EXECUTE format('SELECT revision FROM %I WHERE id=$1 AND project_id=$2',TG_TABLE_NAME) INTO parent_revision USING NEW.parent_id,NEW.project_id;
          IF parent_revision IS NULL OR NEW.revision<>parent_revision+1 THEN RAISE EXCEPTION 'Invalid research version lineage'; END IF;
        END IF;
        RETURN NEW;
      END $$""")
    for table in ('research_finding_versions','research_figure_versions','research_report_versions'):
        op.execute(f'CREATE TRIGGER b03_version_lineage BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION b03_version_lineage()')
    op.execute("""CREATE FUNCTION b03_manuscript_delivery_scope() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE project_kind text; delivery_kind text;
      BEGIN
        SELECT project_type INTO project_kind FROM projects WHERE id=NEW.project_id;
        IF project_kind='research' AND NEW.delivery_id IS NULL THEN RAISE EXCEPTION 'Research manuscript requires delivery'; END IF;
        IF NEW.delivery_id IS NOT NULL THEN
          SELECT kind INTO delivery_kind FROM research_deliveries WHERE id=NEW.delivery_id AND project_id=NEW.project_id;
          IF (NEW.document_kind='sci' AND delivery_kind='sci_draft') OR (NEW.document_kind='thesis' AND delivery_kind='thesis_draft') THEN NULL;
          ELSE RAISE EXCEPTION 'Invalid manuscript delivery kind'; END IF;
        END IF;
        IF TG_OP='UPDATE' AND (OLD.delivery_id IS DISTINCT FROM NEW.delivery_id OR OLD.document_kind IS DISTINCT FROM NEW.document_kind)
          THEN RAISE EXCEPTION 'Manuscript delivery is immutable'; END IF;
        RETURN NEW;
      END $$""")
    op.execute('CREATE TRIGGER b03_manuscript_delivery_scope BEFORE INSERT OR UPDATE ON manuscripts FOR EACH ROW EXECUTE FUNCTION b03_manuscript_delivery_scope()')
    op.execute("""CREATE FUNCTION b03_candidate_publication_scope() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NEW.published_version_id IS NOT NULL AND NOT EXISTS(
          SELECT 1 FROM manuscript_versions v JOIN manuscripts m ON m.id=v.manuscript_id
          WHERE v.id=NEW.published_version_id AND v.project_id=NEW.project_id AND v.user_id=NEW.user_id
            AND m.delivery_id=NEW.delivery_id AND v.revision=NEW.expected_revision+1
            AND v.parent_version_id IS NOT DISTINCT FROM NEW.base_version_id
            AND (NEW.manuscript_id IS NULL OR v.manuscript_id=NEW.manuscript_id))
          THEN RAISE EXCEPTION 'Invalid research publication scope'; END IF;
        RETURN NEW;
      END $$""")
    op.execute('CREATE TRIGGER b03_candidate_publication_scope BEFORE INSERT OR UPDATE ON research_manuscript_candidates FOR EACH ROW EXECUTE FUNCTION b03_candidate_publication_scope()')
    op.execute("""CREATE FUNCTION b03_report_pdf_scope() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF NEW.source_kind='research_report' AND NOT EXISTS(SELECT 1 FROM research_report_members m
        JOIN research_report_versions r ON r.id=m.report_version_id JOIN tasks t ON t.id=r.task_id
        WHERE m.id=NEW.research_report_member_id AND m.project_id=NEW.project_id AND m.user_id=NEW.user_id
          AND m.role='docx' AND m.format='docx' AND m.sha256=NEW.source_sha256 AND t.status='succeeded'
          AND t.result_research_report_version_id=r.id)
        THEN RAISE EXCEPTION 'Invalid research report DOCX source'; END IF;
        RETURN NEW;
      END $$""")
    op.execute('CREATE TRIGGER b03_report_pdf_scope BEFORE INSERT OR UPDATE ON pdf_exports FOR EACH ROW EXECUTE FUNCTION b03_report_pdf_scope()')
    for table in TABLE_NAMES:
        op.execute(f"""CREATE FUNCTION storage_guard_{table}() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN IF EXISTS(SELECT 1 FROM storage_deletion_operations o WHERE o.project_id=NEW.project_id
            AND o.state<>'preview' AND (o.scope_kind='project' OR o.state IN ('running','partial_failed')
              OR EXISTS(SELECT 1 FROM storage_deletion_items i WHERE i.operation_id=o.id AND i.state NOT IN ('retained','deleted'))))
            THEN RAISE EXCEPTION USING ERRCODE='P7501',MESSAGE='storage_deletion_pending'; END IF;
          RETURN NEW; END $$""")
        op.execute(f'CREATE TRIGGER storage_deletion_guard BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION storage_guard_{table}()')


def downgrade():
    raise RuntimeError('Research results downgrade requires explicit reviewed restore; existing tables and snapshots preserved.')

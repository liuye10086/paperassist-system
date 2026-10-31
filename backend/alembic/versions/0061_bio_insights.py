"""Frozen CR-B04 DDL. This migration never imports application metadata."""
from alembic import op
import sqlalchemy as sa
revision = '0061_bio_insights'
down_revision = '0060_research_results_bridge'
branch_labels = None
depends_on = None
TABLE_NAMES = ('bio_resource_versions', 'bio_resource_members', 'bio_insight_plans', 'bio_insight_plan_versions', 'bio_insight_plan_sources', 'bio_insight_runs', 'bio_insight_result_versions', 'bio_insight_result_members')
IMMUTABLE = ('bio_resource_members', 'bio_insight_plan_versions', 'bio_insight_plan_sources', 'bio_insight_result_versions', 'bio_insight_result_members')
PRE_SQL = (
    'ALTER TABLE tasks ADD CONSTRAINT b04_task_typed_scope_key UNIQUE (id, project_id, user_id, task_type)',
)
CREATE_TABLE_SQL = (
    "CREATE TABLE bio_resource_versions (\n\tid TEXT NOT NULL, \n\tproject_id TEXT NOT NULL, \n\tuser_id TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tschema_version INTEGER DEFAULT '1' NOT NULL, \n\troot_id TEXT NOT NULL, \n\tversion INTEGER NOT NULL, \n\tparent_id TEXT, \n\tkind TEXT NOT NULL, \n\ttitle TEXT NOT NULL, \n\tspecies_taxon_id INTEGER NOT NULL, \n\tnamespace TEXT NOT NULL, \n\trelease TEXT NOT NULL, \n\tsource_json JSONB NOT NULL, \n\tusage_json JSONB NOT NULL, \n\tconfig_json JSONB NOT NULL, \n\tconfig_sha256 TEXT NOT NULL, \n\ttask_id TEXT NOT NULL, \n\ttask_type TEXT NOT NULL, \n\tmanifest_object_id TEXT, \n\tmanifest_sha256 TEXT, \n\trequest_key TEXT NOT NULL, \n\trequest_digest TEXT NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (root_id, version, project_id), \n\tUNIQUE (id, root_id, project_id), \n\tCONSTRAINT b04_scope_fk_1 FOREIGN KEY(parent_id, root_id, project_id) REFERENCES bio_resource_versions (id, root_id, project_id), \n\tCONSTRAINT b04_ck_80587a148246c77d CHECK (version>=1 AND ((version=1 AND parent_id IS NULL) OR (version>1 AND parent_id IS NOT NULL))), \n\tCONSTRAINT b04_scope_fk_2 FOREIGN KEY(root_id, project_id) REFERENCES bio_resource_versions (id, project_id), \n\tCONSTRAINT b04_ck_f1582f018cdb5830 CHECK (version<>1 OR root_id=id), \n\tCONSTRAINT b04_ck_a0356f9633bbe841 CHECK (jsonb_typeof(source_json)='object' AND octet_length(source_json::text)<=4194304), \n\tCONSTRAINT b04_ck_07b9fb4c1c2fea10 CHECK (jsonb_typeof(usage_json)='object' AND octet_length(usage_json::text)<=4194304), \n\tCONSTRAINT b04_ck_ad44858aa6bd0f77 CHECK (jsonb_typeof(config_json)='object' AND octet_length(config_json::text)<=4194304), \n\tCONSTRAINT b04_scope_fk_3 FOREIGN KEY(task_id, project_id, user_id, task_type) REFERENCES tasks (id, project_id, user_id, task_type), \n\tUNIQUE (task_id), \n\tUNIQUE (id, task_id, project_id), \n\tCONSTRAINT b04_scope_fk_4 FOREIGN KEY(manifest_object_id, project_id) REFERENCES storage_references (object_id, project_id), \n\tCONSTRAINT b04_ck_aaf596193034c5c7 CHECK ((manifest_object_id IS NULL AND manifest_sha256 IS NULL) OR (manifest_object_id IS NOT NULL AND manifest_sha256 IS NOT NULL AND manifest_sha256 ~ '^[0-9a-f]{64}$')), \n\tUNIQUE (project_id, user_id, request_key), \n\tCONSTRAINT b04_ck_62891f2d471e332a CHECK (request_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT b04_ck_534afae69eeba7fe CHECK (kind IN ('gene_sets','id_mapping','feature_annotation') AND task_type='bio_resource_import' AND species_taxon_id>0 AND length(title) BETWEEN 1 AND 200 AND length(namespace) BETWEEN 1 AND 200 AND length(release) BETWEEN 1 AND 200 AND config_sha256 ~ '^[0-9a-f]{64}$'), \n\tUNIQUE (id, project_id), \n\tUNIQUE (id, project_id, user_id), \n\tCONSTRAINT b04_scope_fk_5 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id), \n\tCONSTRAINT b04_ck_69833c9624be0c21 CHECK (schema_version=1)\n)",
    'CREATE INDEX bio_resource_versions_manifest_object_id ON bio_resource_versions (manifest_object_id)',
    'CREATE INDEX bio_resource_versions_parent_id ON bio_resource_versions (parent_id)',
    'CREATE INDEX bio_resource_versions_project_created ON bio_resource_versions (project_id, created_at DESC, id)',
    'CREATE INDEX bio_resource_versions_root_id ON bio_resource_versions (root_id)',
    'CREATE INDEX bio_resource_versions_species_taxon_id ON bio_resource_versions (species_taxon_id)',
    'CREATE INDEX bio_resource_versions_task_id ON bio_resource_versions (task_id)',
    "CREATE TABLE bio_insight_plans (\n\tid TEXT NOT NULL, \n\tproject_id TEXT NOT NULL, \n\tuser_id TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tschema_version INTEGER DEFAULT '1' NOT NULL, \n\tkind TEXT NOT NULL, \n\tname TEXT NOT NULL, \n\trevision INTEGER DEFAULT '1' NOT NULL, \n\tcurrent_version_id TEXT, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (id, kind, project_id, user_id), \n\tCONSTRAINT b04_ck_b53dd4e10751be87 CHECK (kind IN ('comparison','result_import','ora','gsea_prerank','candidate','figure') AND revision>=1 AND length(name) BETWEEN 1 AND 200 AND updated_at>=created_at), \n\tUNIQUE (id, project_id), \n\tUNIQUE (id, project_id, user_id), \n\tCONSTRAINT b04_scope_fk_12 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id), \n\tCONSTRAINT b04_ck_69833c9624be0c21 CHECK (schema_version=1)\n)",
    'CREATE INDEX bio_insight_plans_current_version_id ON bio_insight_plans (current_version_id)',
    'CREATE INDEX bio_insight_plans_project_created ON bio_insight_plans (project_id, created_at DESC, id)',
    "CREATE TABLE bio_resource_members (\n\tid TEXT NOT NULL, \n\tproject_id TEXT NOT NULL, \n\tuser_id TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tschema_version INTEGER DEFAULT '1' NOT NULL, \n\tresource_version_id TEXT NOT NULL, \n\tkey TEXT NOT NULL, \n\trole TEXT NOT NULL, \n\tformat TEXT NOT NULL, \n\tstorage_object_id TEXT NOT NULL, \n\tsize_bytes BIGINT NOT NULL, \n\tsha256 TEXT NOT NULL, \n\tshape_json JSONB NOT NULL, \n\toriginal_file_id TEXT, \n\tparse_version_id TEXT, \n\tPRIMARY KEY (id), \n\tCONSTRAINT b04_scope_fk_6 FOREIGN KEY(original_file_id, project_id) REFERENCES files (id, project_id), \n\tCONSTRAINT b04_scope_fk_7 FOREIGN KEY(parse_version_id, original_file_id) REFERENCES file_parse_results (id, file_id), \n\tCONSTRAINT b04_ck_4da61671281ad9d3 CHECK (parse_version_id IS NULL OR original_file_id IS NOT NULL), \n\tCONSTRAINT b04_scope_fk_8 FOREIGN KEY(resource_version_id, project_id) REFERENCES bio_resource_versions (id, project_id), \n\tCONSTRAINT b04_scope_fk_9 FOREIGN KEY(storage_object_id, project_id) REFERENCES storage_references (object_id, project_id), \n\tCONSTRAINT b04_ck_ee73b4a46e18427a CHECK (jsonb_typeof(shape_json)='object' AND octet_length(shape_json::text)<=4194304), \n\tUNIQUE (resource_version_id, key), \n\tUNIQUE (id, resource_version_id, project_id), \n\tCONSTRAINT b04_ck_d2cd3220ac58edd7 CHECK (size_bytes>=0 AND sha256 ~ '^[0-9a-f]{64}$' AND key ~ '^[A-Za-z0-9_-]{1,100}$' AND length(role) BETWEEN 1 AND 100 AND length(format) BETWEEN 1 AND 20), \n\tUNIQUE (id, project_id), \n\tUNIQUE (id, project_id, user_id), \n\tCONSTRAINT b04_scope_fk_10 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id), \n\tCONSTRAINT b04_ck_69833c9624be0c21 CHECK (schema_version=1)\n)",
    'CREATE INDEX bio_resource_members_original_file_id ON bio_resource_members (original_file_id)',
    'CREATE INDEX bio_resource_members_parse_version_id ON bio_resource_members (parse_version_id)',
    'CREATE INDEX bio_resource_members_project_created ON bio_resource_members (project_id, created_at DESC, id)',
    'CREATE INDEX bio_resource_members_resource_version_id ON bio_resource_members (resource_version_id)',
    'CREATE INDEX bio_resource_members_storage_object_id ON bio_resource_members (storage_object_id)',
    "CREATE TABLE bio_insight_plan_versions (\n\tid TEXT NOT NULL, \n\tproject_id TEXT NOT NULL, \n\tuser_id TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tschema_version INTEGER DEFAULT '1' NOT NULL, \n\tplan_id TEXT NOT NULL, \n\tversion INTEGER NOT NULL, \n\tparent_id TEXT, \n\tkind TEXT NOT NULL, \n\tdecision TEXT NOT NULL, \n\tconfig_json JSONB NOT NULL, \n\tconfig_sha256 TEXT NOT NULL, \n\tdesign_checks_json JSONB NOT NULL, \n\tconfirmed_by TEXT, \n\tsources_transaction_id TEXT DEFAULT pg_current_xact_id()::text NOT NULL,\n\tconfirmed_at TIMESTAMP WITH TIME ZONE, \n\trequest_key TEXT NOT NULL, \n\trequest_digest TEXT NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (plan_id, version, project_id), \n\tUNIQUE (id, plan_id, project_id), \n\tCONSTRAINT b04_scope_fk_13 FOREIGN KEY(parent_id, plan_id, project_id) REFERENCES bio_insight_plan_versions (id, plan_id, project_id), \n\tCONSTRAINT b04_ck_80587a148246c77d CHECK (version>=1 AND ((version=1 AND parent_id IS NULL) OR (version>1 AND parent_id IS NOT NULL))), \n\tCONSTRAINT b04_ck_ad44858aa6bd0f77 CHECK (jsonb_typeof(config_json)='object' AND octet_length(config_json::text)<=4194304), \n\tCONSTRAINT b04_ck_8ac4ff271338e31d CHECK (jsonb_typeof(design_checks_json)='object' AND octet_length(design_checks_json::text)<=4194304), \n\tUNIQUE (project_id, user_id, request_key), \n\tCONSTRAINT b04_ck_62891f2d471e332a CHECK (request_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT b04_scope_fk_14 FOREIGN KEY(plan_id, kind, project_id, user_id) REFERENCES bio_insight_plans (id, kind, project_id, user_id), \n\tUNIQUE (id, plan_id, kind, project_id, user_id), \n\tUNIQUE (id, kind, decision, project_id, user_id), \n\tCONSTRAINT b04_ck_006677e0253b24dc CHECK (kind IN ('comparison','result_import','ora','gsea_prerank','candidate','figure') AND config_sha256 ~ '^[0-9a-f]{64}$' AND ((decision='draft' AND confirmed_by IS NULL AND confirmed_at IS NULL) OR (decision='confirmed' AND confirmed_by=user_id AND confirmed_at IS NOT NULL AND confirmed_at>=created_at))), \n\tUNIQUE (id, project_id), \n\tUNIQUE (id, project_id, user_id), \n\tCONSTRAINT b04_scope_fk_15 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id), \n\tCONSTRAINT b04_ck_69833c9624be0c21 CHECK (schema_version=1)\n)",
    'CREATE INDEX bio_insight_plan_versions_parent_id ON bio_insight_plan_versions (parent_id)',
    'CREATE INDEX bio_insight_plan_versions_plan_id ON bio_insight_plan_versions (plan_id)',
    'CREATE INDEX bio_insight_plan_versions_project_created ON bio_insight_plan_versions (project_id, created_at DESC, id)',
    "CREATE TABLE bio_insight_runs (\n\tid TEXT NOT NULL, \n\tproject_id TEXT NOT NULL, \n\tuser_id TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tschema_version INTEGER DEFAULT '1' NOT NULL, \n\tplan_version_id TEXT NOT NULL, \n\tkind TEXT NOT NULL, \n\tdecision TEXT NOT NULL, \n\ttask_id TEXT NOT NULL, \n\ttask_type TEXT NOT NULL, \n\tsource_digest TEXT NOT NULL, \n\texecution_snapshot_object_id TEXT NOT NULL, \n\texecution_snapshot_sha256 TEXT NOT NULL, \n\texpected_plan_revision INTEGER NOT NULL, \n\tresult_version_id TEXT, \n\trequest_key TEXT NOT NULL, \n\trequest_digest TEXT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT b04_scope_fk_26 FOREIGN KEY(task_id, project_id, user_id, task_type) REFERENCES tasks (id, project_id, user_id, task_type), \n\tUNIQUE (task_id), \n\tUNIQUE (id, task_id, project_id), \n\tCONSTRAINT b04_scope_fk_27 FOREIGN KEY(execution_snapshot_object_id, project_id) REFERENCES storage_references (object_id, project_id), \n\tUNIQUE (project_id, user_id, request_key), \n\tCONSTRAINT b04_ck_62891f2d471e332a CHECK (request_key ~ '^[!-~]{1,128}$' AND request_digest ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT b04_scope_fk_28 FOREIGN KEY(plan_version_id, kind, decision, project_id, user_id) REFERENCES bio_insight_plan_versions (id, kind, decision, project_id, user_id), \n\tUNIQUE (id, task_id, plan_version_id, kind, project_id, user_id), \n\tCONSTRAINT b04_ck_1f6d081d26c33b8b CHECK (decision='confirmed' AND expected_plan_revision>=1 AND source_digest ~ '^[0-9a-f]{64}$' AND execution_snapshot_sha256 ~ '^[0-9a-f]{64}$' AND ((kind='comparison' AND task_type='bio_comparison') OR (kind='result_import' AND task_type='bio_result_import') OR (kind IN ('ora','gsea_prerank') AND task_type='bio_enrichment') OR (kind='candidate' AND task_type='bio_candidate') OR (kind='figure' AND task_type='bio_insight_figure'))), \n\tUNIQUE (id, project_id), \n\tUNIQUE (id, project_id, user_id), \n\tCONSTRAINT b04_scope_fk_30 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id), \n\tCONSTRAINT b04_ck_69833c9624be0c21 CHECK (schema_version=1)\n)",
    'CREATE INDEX bio_insight_runs_execution_snapshot_object_id ON bio_insight_runs (execution_snapshot_object_id)',
    'CREATE INDEX bio_insight_runs_plan_version_id ON bio_insight_runs (plan_version_id)',
    'CREATE INDEX bio_insight_runs_project_created ON bio_insight_runs (project_id, created_at DESC, id)',
    'CREATE INDEX bio_insight_runs_result_version_id ON bio_insight_runs (result_version_id)',
    'CREATE INDEX bio_insight_runs_task_id ON bio_insight_runs (task_id)',
    "CREATE TABLE bio_insight_result_versions (\n\tid TEXT NOT NULL, \n\tproject_id TEXT NOT NULL, \n\tuser_id TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tschema_version INTEGER DEFAULT '1' NOT NULL, \n\trun_id TEXT NOT NULL, \n\ttask_id TEXT NOT NULL, \n\tplan_version_id TEXT NOT NULL, \n\tkind TEXT NOT NULL, \n\tprovenance TEXT NOT NULL, \n\tinference_scope TEXT NOT NULL, \n\tmanifest_object_id TEXT NOT NULL, \n\tmanifest_sha256 TEXT NOT NULL, \n\tsummary_json JSONB NOT NULL, \n\tmethods_json JSONB NOT NULL, \n\tenvironment_digest TEXT NOT NULL, \n\tcode_digest TEXT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT b04_scope_fk_31 FOREIGN KEY(manifest_object_id, project_id) REFERENCES storage_references (object_id, project_id), \n\tCONSTRAINT b04_ck_aaf596193034c5c7 CHECK ((manifest_object_id IS NULL AND manifest_sha256 IS NULL) OR (manifest_object_id IS NOT NULL AND manifest_sha256 IS NOT NULL AND manifest_sha256 ~ '^[0-9a-f]{64}$')), \n\tCONSTRAINT b04_ck_b59a8607eb598e76 CHECK (jsonb_typeof(summary_json)='object' AND octet_length(summary_json::text)<=4194304), \n\tCONSTRAINT b04_ck_9731f6f388fa913a CHECK (jsonb_typeof(methods_json)='object' AND octet_length(methods_json::text)<=4194304), \n\tCONSTRAINT b04_scope_fk_32 FOREIGN KEY(run_id, task_id, plan_version_id, kind, project_id, user_id) REFERENCES bio_insight_runs (id, task_id, plan_version_id, kind, project_id, user_id), \n\tUNIQUE (run_id), \n\tUNIQUE (task_id), \n\tUNIQUE (id, task_id, project_id), \n\tUNIQUE (id, run_id, task_id, plan_version_id, kind, project_id, user_id), \n\tCONSTRAINT b04_ck_99296239b4abe8d2 CHECK (kind IN ('comparison','result_import','ora','gsea_prerank','candidate','figure') AND provenance IN ('system_computed','external_result') AND inference_scope IN ('spot_exploratory','donor_inference','external_result','derived','visualization') AND (kind<>'result_import' OR (provenance='external_result' AND inference_scope='external_result')) AND (kind<>'comparison' OR (provenance='system_computed' AND inference_scope IN ('spot_exploratory','donor_inference'))) AND environment_digest ~ '^[0-9a-f]{64}$' AND code_digest ~ '^[0-9a-f]{64}$'), \n\tUNIQUE (id, project_id), \n\tUNIQUE (id, project_id, user_id), \n\tCONSTRAINT b04_scope_fk_33 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id), \n\tCONSTRAINT b04_ck_69833c9624be0c21 CHECK (schema_version=1)\n)",
    'CREATE INDEX bio_insight_result_versions_manifest_object_id ON bio_insight_result_versions (manifest_object_id)',
    'CREATE INDEX bio_insight_result_versions_plan_version_id ON bio_insight_result_versions (plan_version_id)',
    'CREATE INDEX bio_insight_result_versions_project_created ON bio_insight_result_versions (project_id, created_at DESC, id)',
    'CREATE INDEX bio_insight_result_versions_run_id ON bio_insight_result_versions (run_id)',
    'CREATE INDEX bio_insight_result_versions_task_id ON bio_insight_result_versions (task_id)',
    "CREATE TABLE bio_insight_plan_sources (\n\tid TEXT NOT NULL, \n\tproject_id TEXT NOT NULL, \n\tuser_id TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tschema_version INTEGER DEFAULT '1' NOT NULL, \n\tplan_version_id TEXT NOT NULL, \n\tsource_kind TEXT NOT NULL, \n\tsource_id TEXT NOT NULL, \n\trole TEXT NOT NULL, \n\tordinal INTEGER NOT NULL, \n\tsource_sha256 TEXT NOT NULL, \n\tlocator_json JSONB NOT NULL, \n\tprocessed_version_id TEXT, \n\tobservation_map_version_id TEXT, \n\tannotation_version_id TEXT, \n\tdesign_version_id TEXT, \n\tresource_version_id TEXT, \n\tsource_result_version_id TEXT, \n\tfile_id TEXT, \n\tparse_version_id TEXT, \n\tPRIMARY KEY (id), \n\tCONSTRAINT b04_scope_fk_16 FOREIGN KEY(processed_version_id, project_id) REFERENCES bio_processed_dataset_versions (id, project_id), \n\tCONSTRAINT b04_scope_fk_17 FOREIGN KEY(observation_map_version_id, project_id) REFERENCES bio_observation_map_versions (id, project_id), \n\tCONSTRAINT b04_scope_fk_18 FOREIGN KEY(annotation_version_id, project_id) REFERENCES bio_annotation_versions (id, project_id), \n\tCONSTRAINT b04_scope_fk_19 FOREIGN KEY(design_version_id, project_id) REFERENCES research_design_versions (id, project_id), \n\tCONSTRAINT b04_scope_fk_20 FOREIGN KEY(resource_version_id, project_id) REFERENCES bio_resource_versions (id, project_id), \n\tCONSTRAINT b04_scope_fk_21 FOREIGN KEY(source_result_version_id, project_id) REFERENCES bio_insight_result_versions (id, project_id), \n\tCONSTRAINT b04_scope_fk_22 FOREIGN KEY(file_id, project_id) REFERENCES files (id, project_id), \n\tCONSTRAINT b04_scope_fk_23 FOREIGN KEY(plan_version_id, project_id) REFERENCES bio_insight_plan_versions (id, project_id), \n\tCONSTRAINT b04_ck_3a5a7e8c34fb6647 CHECK (jsonb_typeof(locator_json)='object' AND octet_length(locator_json::text)<=4194304), \n\tCONSTRAINT b04_scope_fk_24 FOREIGN KEY(parse_version_id, file_id) REFERENCES file_parse_results (id, file_id), \n\tUNIQUE (plan_version_id, ordinal), \n\tCONSTRAINT b04_ck_d58e7e56786d52a1 CHECK (num_nonnulls(processed_version_id,observation_map_version_id,annotation_version_id,design_version_id,resource_version_id,source_result_version_id,file_id)=1 AND ((source_kind='bio_processed_dataset_version' AND processed_version_id IS NOT NULL AND source_id=processed_version_id) OR (source_kind='bio_observation_map_version' AND observation_map_version_id IS NOT NULL AND source_id=observation_map_version_id) OR (source_kind='bio_annotation_version' AND annotation_version_id IS NOT NULL AND source_id=annotation_version_id) OR (source_kind='research_design_version' AND design_version_id IS NOT NULL AND source_id=design_version_id) OR (source_kind='bio_resource_version' AND resource_version_id IS NOT NULL AND source_id=resource_version_id) OR (source_kind='bio_insight_result_version' AND source_result_version_id IS NOT NULL AND source_id=source_result_version_id) OR (source_kind='original_file' AND file_id IS NOT NULL AND source_id=file_id))), \n\tCONSTRAINT b04_ck_d0f75acaba9715f6 CHECK (ordinal>=0 AND ordinal<100 AND length(role) BETWEEN 1 AND 100 AND source_sha256 ~ '^[0-9a-f]{64}$' AND (parse_version_id IS NULL OR source_kind='original_file')), \n\tUNIQUE (id, project_id), \n\tUNIQUE (id, project_id, user_id), \n\tCONSTRAINT b04_scope_fk_25 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id), \n\tCONSTRAINT b04_ck_69833c9624be0c21 CHECK (schema_version=1)\n)",
    'CREATE INDEX bio_insight_plan_sources_annotation_version_id ON bio_insight_plan_sources (annotation_version_id)',
    'CREATE INDEX bio_insight_plan_sources_design_version_id ON bio_insight_plan_sources (design_version_id)',
    'CREATE INDEX bio_insight_plan_sources_file_id ON bio_insight_plan_sources (file_id)',
    'CREATE INDEX bio_insight_plan_sources_observation_map_version_id ON bio_insight_plan_sources (observation_map_version_id)',
    'CREATE INDEX bio_insight_plan_sources_parse_version_id ON bio_insight_plan_sources (parse_version_id)',
    'CREATE INDEX bio_insight_plan_sources_plan_version_id ON bio_insight_plan_sources (plan_version_id)',
    'CREATE INDEX bio_insight_plan_sources_processed_version_id ON bio_insight_plan_sources (processed_version_id)',
    'CREATE INDEX bio_insight_plan_sources_project_created ON bio_insight_plan_sources (project_id, created_at DESC, id)',
    'CREATE INDEX bio_insight_plan_sources_resource_version_id ON bio_insight_plan_sources (resource_version_id)',
    'CREATE INDEX bio_insight_plan_sources_source_id ON bio_insight_plan_sources (source_id)',
    'CREATE INDEX bio_insight_plan_sources_source_result_version_id ON bio_insight_plan_sources (source_result_version_id)',
    "CREATE TABLE bio_insight_result_members (\n\tid TEXT NOT NULL, \n\tproject_id TEXT NOT NULL, \n\tuser_id TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tschema_version INTEGER DEFAULT '1' NOT NULL, \n\tresult_version_id TEXT NOT NULL, \n\tkey TEXT NOT NULL, \n\trole TEXT NOT NULL, \n\tformat TEXT NOT NULL, \n\tstorage_object_id TEXT NOT NULL, \n\tsize_bytes BIGINT NOT NULL, \n\tsha256 TEXT NOT NULL, \n\tshape_json JSONB NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT b04_scope_fk_34 FOREIGN KEY(result_version_id, project_id) REFERENCES bio_insight_result_versions (id, project_id), \n\tCONSTRAINT b04_scope_fk_35 FOREIGN KEY(storage_object_id, project_id) REFERENCES storage_references (object_id, project_id), \n\tCONSTRAINT b04_ck_ee73b4a46e18427a CHECK (jsonb_typeof(shape_json)='object' AND octet_length(shape_json::text)<=4194304), \n\tUNIQUE (result_version_id, key), \n\tUNIQUE (id, result_version_id, project_id), \n\tCONSTRAINT b04_ck_d2cd3220ac58edd7 CHECK (size_bytes>=0 AND sha256 ~ '^[0-9a-f]{64}$' AND key ~ '^[A-Za-z0-9_-]{1,100}$' AND length(role) BETWEEN 1 AND 100 AND length(format) BETWEEN 1 AND 20), \n\tUNIQUE (id, project_id), \n\tUNIQUE (id, project_id, user_id), \n\tCONSTRAINT b04_scope_fk_36 FOREIGN KEY(project_id, user_id) REFERENCES projects (id, owner_id), \n\tCONSTRAINT b04_ck_69833c9624be0c21 CHECK (schema_version=1)\n)",
    'CREATE INDEX bio_insight_result_members_project_created ON bio_insight_result_members (project_id, created_at DESC, id)',
    'CREATE INDEX bio_insight_result_members_result_version_id ON bio_insight_result_members (result_version_id)',
    'CREATE INDEX bio_insight_result_members_storage_object_id ON bio_insight_result_members (storage_object_id)',
    'ALTER TABLE bio_insight_plans ADD CONSTRAINT b04_scope_fk_11 FOREIGN KEY(current_version_id, id, kind, project_id, user_id) REFERENCES bio_insight_plan_versions (id, plan_id, kind, project_id, user_id)',
    'ALTER TABLE bio_insight_runs ADD CONSTRAINT b04_scope_fk_29 FOREIGN KEY(result_version_id, id, task_id, plan_version_id, kind, project_id, user_id) REFERENCES bio_insight_result_versions (id, run_id, task_id, plan_version_id, kind, project_id, user_id)',
)
POST_SQL = (
    'ALTER TABLE tasks ADD COLUMN result_bio_resource_version_id TEXT',
    'ALTER TABLE tasks ADD COLUMN result_bio_insight_result_version_id TEXT',
    'ALTER TABLE tasks ADD CONSTRAINT b04_tasks_insight_result_fk FOREIGN KEY(result_bio_insight_result_version_id, id, project_id) REFERENCES bio_insight_result_versions (id, task_id, project_id)',
    'ALTER TABLE tasks ADD CONSTRAINT b04_tasks_resource_result_fk FOREIGN KEY(result_bio_resource_version_id, id, project_id) REFERENCES bio_resource_versions (id, task_id, project_id)',
    "ALTER TABLE tasks ADD CONSTRAINT b04_tasks_results_check CHECK ((result_bio_resource_version_id IS NULL OR (task_type='bio_resource_import' AND status='succeeded')) AND (result_bio_insight_result_version_id IS NULL OR (task_type IN ('bio_comparison','bio_result_import','bio_enrichment','bio_candidate','bio_insight_figure') AND status='succeeded')) AND num_nonnulls(result_bio_resource_version_id,result_bio_insight_result_version_id)<=1 AND (num_nonnulls(result_bio_resource_version_id,result_bio_insight_result_version_id)=0 OR num_nonnulls(result_research_figure_version_id,result_research_report_version_id,result_research_candidate_id,result_bio_dataset_version_id,result_bio_processed_dataset_version_id,result_bio_figure_version_id,result_analysis_run_id,result_report_id,result_explanation_id,result_figure_id)=0))",
    "ALTER TABLE tasks ADD CONSTRAINT b04_tasks_snapshot_check CHECK ((task_type<>'bio_resource_import' AND task_type<>'bio_comparison' AND task_type<>'bio_result_import' AND task_type<>'bio_enrichment' AND task_type<>'bio_candidate' AND task_type<>'bio_insight_figure') OR ((workflow_version=task_type||'_v1' AND input_snapshot->'schema_version'='1'::jsonb AND input_snapshot->>'kind'=task_type AND input_snapshot->>'workflow_version'=workflow_version AND input_snapshot->>'project_id'=project_id AND input_snapshot->>'output_language' IN ('zh-CN','en') AND input_snapshot->'real_model_calls'='false'::jsonb AND input_snapshot->'real_network_calls'='false'::jsonb AND ((task_type='bio_resource_import' AND length(input_snapshot->>'resource_version_id')>0) OR (task_type<>'bio_resource_import' AND length(input_snapshot->>'plan_version_id')>0 AND length(input_snapshot->>'run_id')>0 AND input_snapshot->>'source_digest' ~ '^[0-9a-f]{64}$'))) IS TRUE))",
    'ALTER TABLE tasks DROP CONSTRAINT tasks_type_check',
    "ALTER TABLE tasks ADD CONSTRAINT tasks_type_check CHECK (task_type IN ('boxplot', 'explanation', 'word_report', 'parse_file', 'extract_dataset', 'prepare_dataset', 'review_ocr', 'analysis_plan', 'analysis_recommendation', 'figure_projection', 'figure_workbench', 'figure_explanation', 'collection_word_report', 'statistics_compute', 'literature_search', 'literature_assistance', 'manuscript_draft', 'manuscript_docx', 'pdf_export', 'manuscript_writing', 'layout_docx', 'school_template_parse', 'school_rule_suggestion', 'journal_recommendation', 'journal_format_check', 'journal_adaptation', 'review_round_plan', 'review_revision', 'review_document_export', 'bio_import', 'bio_analysis', 'bio_figure', 'research_figure', 'research_report', 'research_fact_draft', 'bio_resource_import', 'bio_comparison', 'bio_result_import', 'bio_enrichment', 'bio_candidate', 'bio_insight_figure'))",
    'ALTER TABLE research_source_bindings ADD COLUMN bio_insight_result_version_id TEXT',
    'ALTER TABLE research_source_bindings ADD COLUMN bio_insight_result_member_id TEXT',
    'ALTER TABLE research_source_bindings DROP CONSTRAINT b03_ck_2be404256e3b67e4',
    "ALTER TABLE research_source_bindings ADD CONSTRAINT b03_ck_82ffaec630d174e6 CHECK (num_nonnulls(processed_version_id,analysis_artifact_id,bio_figure_version_id,file_id,external_evidence_version_id,source_finding_version_id,research_figure_version_id,source_report_version_id,bio_insight_result_version_id,bio_insight_result_member_id)=1 AND ((source_kind='bio_processed_dataset_version' AND processed_version_id IS NOT NULL AND source_id=processed_version_id) OR (source_kind='bio_analysis_artifact' AND analysis_artifact_id IS NOT NULL AND source_id=analysis_artifact_id) OR (source_kind='bio_figure_version' AND bio_figure_version_id IS NOT NULL AND source_id=bio_figure_version_id) OR (source_kind='original_file' AND file_id IS NOT NULL AND source_id=file_id) OR (source_kind='external_evidence_version' AND external_evidence_version_id IS NOT NULL AND source_id=external_evidence_version_id) OR (source_kind='research_finding_version' AND source_finding_version_id IS NOT NULL AND source_id=source_finding_version_id) OR (source_kind='research_figure_version' AND research_figure_version_id IS NOT NULL AND source_id=research_figure_version_id) OR (source_kind='research_report_version' AND source_report_version_id IS NOT NULL AND source_id=source_report_version_id) OR (source_kind='bio_insight_result_version' AND bio_insight_result_version_id IS NOT NULL AND source_id=bio_insight_result_version_id) OR (source_kind='bio_insight_result_member' AND bio_insight_result_member_id IS NOT NULL AND source_id=bio_insight_result_member_id)))",
    'ALTER TABLE research_source_bindings ADD CONSTRAINT b04_research_bio_insight_result_member_id_fk FOREIGN KEY(bio_insight_result_member_id, project_id) REFERENCES bio_insight_result_members (id, project_id)',
    'ALTER TABLE research_source_bindings ADD CONSTRAINT b04_research_bio_insight_result_version_id_fk FOREIGN KEY(bio_insight_result_version_id, project_id) REFERENCES bio_insight_result_versions (id, project_id)',
    'CREATE INDEX research_source_bindings_bio_insight_result_member_id ON research_source_bindings (bio_insight_result_member_id)',
    'CREATE INDEX research_source_bindings_bio_insight_result_version_id ON research_source_bindings (bio_insight_result_version_id)',
    'ALTER TABLE manuscript_research_sources ADD COLUMN bio_insight_result_version_id TEXT',
    'ALTER TABLE manuscript_research_sources ADD COLUMN bio_insight_result_member_id TEXT',
    'ALTER TABLE manuscript_research_sources DROP CONSTRAINT b03_ck_2be404256e3b67e4',
    "ALTER TABLE manuscript_research_sources ADD CONSTRAINT b03_ck_82ffaec630d174e6 CHECK (num_nonnulls(processed_version_id,analysis_artifact_id,bio_figure_version_id,file_id,external_evidence_version_id,source_finding_version_id,research_figure_version_id,source_report_version_id,bio_insight_result_version_id,bio_insight_result_member_id)=1 AND ((source_kind='bio_processed_dataset_version' AND processed_version_id IS NOT NULL AND source_id=processed_version_id) OR (source_kind='bio_analysis_artifact' AND analysis_artifact_id IS NOT NULL AND source_id=analysis_artifact_id) OR (source_kind='bio_figure_version' AND bio_figure_version_id IS NOT NULL AND source_id=bio_figure_version_id) OR (source_kind='original_file' AND file_id IS NOT NULL AND source_id=file_id) OR (source_kind='external_evidence_version' AND external_evidence_version_id IS NOT NULL AND source_id=external_evidence_version_id) OR (source_kind='research_finding_version' AND source_finding_version_id IS NOT NULL AND source_id=source_finding_version_id) OR (source_kind='research_figure_version' AND research_figure_version_id IS NOT NULL AND source_id=research_figure_version_id) OR (source_kind='research_report_version' AND source_report_version_id IS NOT NULL AND source_id=source_report_version_id) OR (source_kind='bio_insight_result_version' AND bio_insight_result_version_id IS NOT NULL AND source_id=bio_insight_result_version_id) OR (source_kind='bio_insight_result_member' AND bio_insight_result_member_id IS NOT NULL AND source_id=bio_insight_result_member_id)))",
    'ALTER TABLE manuscript_research_sources ADD CONSTRAINT b04_research_bio_insight_result_member_id_fk FOREIGN KEY(bio_insight_result_member_id, project_id) REFERENCES bio_insight_result_members (id, project_id)',
    'ALTER TABLE manuscript_research_sources ADD CONSTRAINT b04_research_bio_insight_result_version_id_fk FOREIGN KEY(bio_insight_result_version_id, project_id) REFERENCES bio_insight_result_versions (id, project_id)',
    'CREATE INDEX manuscript_research_sources_bio_insight_result_member_id ON manuscript_research_sources (bio_insight_result_member_id)',
    'CREATE INDEX manuscript_research_sources_bio_insight_result_version_id ON manuscript_research_sources (bio_insight_result_version_id)',
)


def upgrade():
    op.execute("SET LOCAL lock_timeout='3s'")
    for statement in (*PRE_SQL, *CREATE_TABLE_SQL, *POST_SQL):
        op.execute(sa.text(statement))
    _install_triggers()


def downgrade():
    raise RuntimeError('Bio insights downgrade requires a reviewed restore; snapshots preserved.')


def _install_triggers():
    op.execute("""CREATE FUNCTION b04_snapshot_seal() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'Immutable bio insight snapshot'; END $$""")
    for table in IMMUTABLE:
        op.execute(f'CREATE TRIGGER b04_snapshot_seal BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION b04_snapshot_seal()')
    op.execute("""CREATE FUNCTION b04_publication_seal() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Immutable bio insight publication'; END IF;
        IF TG_TABLE_NAME='bio_insight_runs' THEN
          IF (to_jsonb(OLD)-'result_version_id') IS DISTINCT FROM (to_jsonb(NEW)-'result_version_id')
            OR (OLD.result_version_id IS NOT NULL AND OLD.result_version_id IS DISTINCT FROM NEW.result_version_id)
            THEN RAISE EXCEPTION 'Immutable bio insight run'; END IF;
        ELSE
          IF (to_jsonb(OLD)-'manifest_object_id'-'manifest_sha256') IS DISTINCT FROM (to_jsonb(NEW)-'manifest_object_id'-'manifest_sha256')
            OR (OLD.manifest_object_id IS NOT NULL AND (OLD.manifest_object_id IS DISTINCT FROM NEW.manifest_object_id OR OLD.manifest_sha256 IS DISTINCT FROM NEW.manifest_sha256))
            THEN RAISE EXCEPTION 'Immutable bio resource'; END IF;
        END IF;
        RETURN NEW;
      END $$""")
    for table in ('bio_resource_versions','bio_insight_runs'):
        op.execute(f'CREATE TRIGGER b04_publication_seal BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION b04_publication_seal()')
    op.execute("""CREATE FUNCTION b04_version_lineage() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE parent_version integer;
      BEGIN
        IF TG_TABLE_NAME='bio_insight_plan_versions' THEN
          NEW.sources_transaction_id := pg_current_xact_id()::text;
        END IF;
        IF NEW.parent_id IS NOT NULL THEN
          EXECUTE format('SELECT version FROM %I WHERE id=$1 AND project_id=$2',TG_TABLE_NAME)
            INTO parent_version USING NEW.parent_id,NEW.project_id;
          IF parent_version IS NULL OR NEW.version<>parent_version+1 THEN RAISE EXCEPTION 'Invalid bio insight lineage'; END IF;
        END IF;
        RETURN NEW;
      END $$""")
    for table in ('bio_resource_versions','bio_insight_plan_versions'):
        op.execute(f'CREATE TRIGGER b04_version_lineage BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION b04_version_lineage()')
    op.execute("""CREATE FUNCTION b04_plan_root_seal() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Immutable bio insight plan root'; END IF;
        IF (to_jsonb(OLD)-'name'-'revision'-'current_version_id'-'updated_at') IS DISTINCT FROM (to_jsonb(NEW)-'name'-'revision'-'current_version_id'-'updated_at')
          OR NOT (NEW.revision=OLD.revision+1 OR (OLD.current_version_id IS NULL AND NEW.revision=OLD.revision))
          THEN RAISE EXCEPTION 'Invalid bio insight plan CAS'; END IF;
        IF NEW.current_version_id IS NULL OR NOT EXISTS(SELECT 1 FROM bio_insight_plan_versions v
          WHERE v.id=NEW.current_version_id AND v.plan_id=NEW.id AND v.version=NEW.revision)
          THEN RAISE EXCEPTION 'Invalid bio insight plan revision'; END IF;
        RETURN NEW;
      END $$""")
    op.execute('CREATE TRIGGER b04_plan_root_seal BEFORE UPDATE OR DELETE ON bio_insight_plans FOR EACH ROW EXECUTE FUNCTION b04_plan_root_seal()')
    op.execute("""CREATE FUNCTION b04_task_input_scope() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE snapshot jsonb;
      BEGIN
        SELECT input_snapshot INTO snapshot FROM tasks WHERE id=NEW.task_id AND project_id=NEW.project_id AND user_id=NEW.user_id;
        IF TG_TABLE_NAME='bio_resource_versions' THEN
          IF (snapshot->>'resource_version_id'=NEW.id) IS NOT TRUE THEN RAISE EXCEPTION 'Invalid bio resource task input'; END IF;
        ELSE
          IF (snapshot->>'run_id'=NEW.id AND snapshot->>'plan_version_id'=NEW.plan_version_id
              AND snapshot->>'source_digest'=NEW.source_digest) IS NOT TRUE THEN RAISE EXCEPTION 'Invalid bio insight task input'; END IF;
        END IF;
        RETURN NEW;
      END $$""")
    for table in ('bio_resource_versions','bio_insight_runs'):
        op.execute(f'CREATE TRIGGER b04_task_input_scope BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION b04_task_input_scope()')
    op.execute("""CREATE FUNCTION b04_bound_task_input_seal() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF OLD.task_type IN ('bio_resource_import','bio_comparison','bio_result_import','bio_enrichment','bio_candidate','bio_insight_figure') THEN
          IF ROW(OLD.id,OLD.project_id,OLD.user_id,OLD.task_type,OLD.idempotency_key,OLD.input_digest,OLD.input_snapshot,OLD.workflow_version,OLD.created_at)
            IS DISTINCT FROM ROW(NEW.id,NEW.project_id,NEW.user_id,NEW.task_type,NEW.idempotency_key,NEW.input_digest,NEW.input_snapshot,NEW.workflow_version,NEW.created_at)
            THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Immutable bio insight task input'; END IF;
        END IF;
        RETURN NEW;
      END $$""")
    op.execute('CREATE TRIGGER b04_bound_task_input_seal BEFORE UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION b04_bound_task_input_seal()')
    op.execute("""CREATE FUNCTION b04_child_publication_scope() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_TABLE_NAME='bio_resource_members' THEN
          IF EXISTS(SELECT 1 FROM bio_resource_versions v WHERE v.id=NEW.resource_version_id AND v.manifest_object_id IS NOT NULL)
            THEN RAISE EXCEPTION 'Bio resource already published'; END IF;
        ELSIF TG_TABLE_NAME='bio_insight_plan_sources' THEN
          IF NOT EXISTS(SELECT 1 FROM bio_insight_plan_versions v WHERE v.id=NEW.plan_version_id
            AND v.project_id=NEW.project_id AND v.user_id=NEW.user_id
            AND v.sources_transaction_id=pg_current_xact_id()::text)
            THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Bio insight sources require the version creation transaction'; END IF;
          IF EXISTS(SELECT 1 FROM bio_insight_runs r WHERE r.plan_version_id=NEW.plan_version_id)
            THEN RAISE EXCEPTION 'Bio insight plan already executed'; END IF;
        ELSE
          IF EXISTS(SELECT 1 FROM bio_insight_result_versions v JOIN tasks t ON t.id=v.task_id WHERE v.id=NEW.result_version_id AND t.status='succeeded')
            THEN RAISE EXCEPTION 'Bio insight result already published'; END IF;
        END IF;
        RETURN NEW;
      END $$""")
    for table in ('bio_resource_members','bio_insight_plan_sources','bio_insight_result_members'):
        op.execute(f'CREATE TRIGGER b04_child_publication_scope BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION b04_child_publication_scope()')
    for table in TABLE_NAMES:
        op.execute(f"""CREATE FUNCTION storage_guard_{table}() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN IF EXISTS(SELECT 1 FROM storage_deletion_operations o WHERE o.project_id=NEW.project_id
            AND o.state<>'preview' AND (o.scope_kind='project' OR o.state IN ('running','partial_failed')
              OR EXISTS(SELECT 1 FROM storage_deletion_items i WHERE i.operation_id=o.id AND i.state NOT IN ('retained','deleted'))))
            THEN RAISE EXCEPTION USING ERRCODE='P7501',MESSAGE='storage_deletion_pending'; END IF;
          RETURN NEW; END $$""")
        op.execute(f'CREATE TRIGGER storage_deletion_guard BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION storage_guard_{table}()')

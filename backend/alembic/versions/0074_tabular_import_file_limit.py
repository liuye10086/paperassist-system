"""Admit v3 input tables and their optional upstream quality reports."""

from alembic import op

revision = '0074_tabular_import_file_limit'
down_revision = '0073_analysis_request_receipts'
branch_labels = depends_on = None


def _replace_file_limit(max_files):
    op.drop_constraint('tasks_bio_snapshot_check', 'tasks', type_='check')
    op.create_check_constraint('tasks_bio_snapshot_check', 'tasks', f"""
        (
            task_type<>'bio_import'
            OR (
                workflow_version IN ('bio_import_v1','bio_import_v2')
                AND input_snapshot->'schema_version'='1'::jsonb
                AND input_snapshot->>'kind'='bio_import'
                AND input_snapshot->>'workflow_version'=workflow_version
                AND (
                    workflow_version='bio_import_v1'
                    OR (
                        input_snapshot->>'parser_version'='geo_visium_import_v2'
                        AND input_snapshot->>'matrix_representation' IN ('mtx','10x_h5')
                        AND input_snapshot->'compare_alternate' IN ('true'::jsonb,'false'::jsonb)
                        AND jsonb_typeof(input_snapshot->'analysis_limits')='object'
                        AND input_snapshot->>'engine_version'='visium_explore_v1.0.0'
                        AND input_snapshot->>'environment_digest' ~ '^[0-9a-f]{{64}}$'
                        AND input_snapshot->>'code_digest' ~ '^[0-9a-f]{{64}}$'
                    )
                )
                AND input_snapshot->>'project_id'=project_id
                AND jsonb_typeof(input_snapshot->'files')='array'
                AND jsonb_array_length(input_snapshot->'files')>=1
                AND jsonb_array_length(input_snapshot->'files')<=10
                AND jsonb_typeof(input_snapshot->'settings')='object'
            ) IS TRUE
        )
        OR (
            task_type='bio_import'
            AND workflow_version='bio_import_v3'
            AND input_snapshot->'schema_version'='1'::jsonb
            AND input_snapshot->>'kind'='bio_import'
            AND input_snapshot->>'workflow_version'=workflow_version
            AND input_snapshot->>'project_id'=project_id
            AND input_snapshot->>'parser_version'='tabular_assay_import_v1'
            AND input_snapshot->>'engine_version'='tabular_quantitative_v1.0.0'
            AND input_snapshot->>'assay' IN ('bulk_rna_counts','normalized_expression','proteomics','metabolomics','microbiome')
            AND jsonb_typeof(input_snapshot->'tabular_config')='object'
            AND jsonb_typeof(input_snapshot->'files')='array'
            AND jsonb_array_length(input_snapshot->'files') BETWEEN 2 AND {max_files}
            AND jsonb_typeof(input_snapshot->'settings')='object'
            AND input_snapshot->>'environment_digest' ~ '^[0-9a-f]{{64}}$'
            AND input_snapshot->>'code_digest' ~ '^[0-9a-f]{{64}}$'
        ) IS TRUE
        OR (
            task_type='bio_import'
            AND workflow_version='bio_import_v4'
            AND input_snapshot->'schema_version'='1'::jsonb
            AND input_snapshot->>'kind'='bio_import'
            AND input_snapshot->>'workflow_version'=workflow_version
            AND input_snapshot->>'project_id'=project_id
            AND input_snapshot->>'assay'='single_cell'
            AND input_snapshot->>'parser_version'='single_cell_import_v1'
            AND input_snapshot->>'engine_version'='visium_explore_v1.0.0'
            AND jsonb_typeof(input_snapshot->'single_cell_config')='object'
            AND jsonb_typeof(input_snapshot->'analysis_limits')='object'
            AND jsonb_typeof(input_snapshot->'files')='array'
            AND jsonb_array_length(input_snapshot->'files') BETWEEN 1 AND 10
            AND jsonb_typeof(input_snapshot->'settings')='object'
            AND input_snapshot->>'environment_digest' ~ '^[0-9a-f]{{64}}$'
            AND input_snapshot->>'code_digest' ~ '^[0-9a-f]{{64}}$'
        ) IS TRUE
    """)


def upgrade():
    _replace_file_limit(5)


def downgrade():
    # PostgreSQL rejects the downgrade transaction if retained tasks need the wider limit.
    _replace_file_limit(3)

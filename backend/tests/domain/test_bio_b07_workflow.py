import csv
import io

import pytest

from tests.domain.test_bio_b05_selection import saved_row


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def write_table(path, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, rows[0].keys(), delimiter='\t')
        writer.writeheader()
        writer.writerows(rows)


def test_sensitivity_accounts_for_absent_excluded_and_uncomputable_rows(tmp_path):
    from app.domain.bio_insights.bulk_sensitivity import compare_gene_tables
    from app.domain.bio_insights.contracts import BulkSelection

    before, after = tmp_path / 'before.tsv', tmp_path / 'after.tsv'
    write_table(before, [
        saved_row('g1', '2', '0'),
        saved_row('g2', '-2', '0'),
        saved_row('g3', '2', '0'),
        saved_row('g4', '2', '0'),
        saved_row('g5', '1', 'NA'),
        saved_row('g6', '1', '0.20'),
    ])
    write_table(after, [
        saved_row('g1', '2', '0.03'),
        saved_row('g2', '2', '0.01'),
        saved_row('g3', '', '', tested='False', test_status='excluded'),
        saved_row('g5', '', '', test_status='not_computable'),
        saved_row('g6', '-1', '0.05'),
        saved_row('g7', '-2', '0'),
    ])
    selection = BulkSelection(contrast_id='ab')
    output = io.StringIO()
    result = compare_gene_tables(before, after, selection, selection, ('A', 'B'),
                                 page=2, page_size=2, change_stream=output)

    assert result['total'] == 7
    assert result['counts'] == dict(stable_up=1, stable_down=0, changed_direction=1,
                                    gained=1, lost=0, unchanged=0, ineligible=4)
    assert [(row['feature_id'], row['baseline_class'], row['scenario_class']) for row in result['items']] == [
        ('g3', 'up', 'excluded'), ('g4', 'up', 'absent'),
    ]
    rows = list(csv.DictReader(io.StringIO(output.getvalue()), delimiter='\t'))
    assert [row['feature_id'] for row in rows] == [f'g{i}' for i in range(1, 8)]
    assert rows[0]['baseline_q'] == '0.0'
    assert rows[4]['scenario_class'] == 'not_computable'


def test_frozen_threshold_scenario_uses_selected_q_column_and_direction(tmp_path):
    from app.domain.bio_insights.bulk_sensitivity import compare_gene_tables
    from app.domain.bio_insights.contracts import BulkSelection

    table = tmp_path / 'fixed.tsv'
    write_table(table, [saved_row('a', '2', '0.05'), saved_row('b', '-2', '0.05')])
    baseline = BulkSelection(contrast_id='ab')
    scenario = BulkSelection(contrast_id='ab', q_column='q_global_family', q_threshold=0.2, direction='up')
    result = compare_gene_tables(table, table, baseline, scenario, ('A', 'B'))

    assert result['items'][0]['baseline_q'] == 0.05
    assert result['items'][0]['scenario_q'] == 0.2
    assert result['items'][1]['scenario_class'] == 'direction_not_selected'
    assert result['counts']['lost'] == 1


def test_sensitivity_rejects_ambiguous_feature_rows(tmp_path):
    from app.domain.bio_insights.bulk_sensitivity import compare_gene_tables
    from app.domain.bio_insights.contracts import BulkSelection

    table = tmp_path / 'duplicate.tsv'
    write_table(table, [saved_row('g1', '2', '0'), saved_row('g1', '-2', '0')])
    selection = BulkSelection(contrast_id='ab')
    with pytest.raises(ValueError, match='bulk_comparison_row_invalid'):
        compare_gene_tables(table, table, selection, selection, ('A', 'B'))


def test_sensitivity_sample_identity_keeps_distinct_raw_versions():
    from app.domain.bio_insights.bulk_sensitivity import _sample_changes

    sample = dict(dataset_id='dataset', dataset_version_id='raw-v1', sample_id='same-label',
                  processed_version_id='original-processed', condition='A')
    before = [sample, dict(sample, dataset_version_id='raw-v2', processed_version_id='processed-v2')]
    after = [dict(sample, processed_version_id='new-processed'),
             dict(sample, dataset_version_id='raw-v3', processed_version_id='processed-v3')]
    assert _sample_changes(before, after) == {
        'added': ['same-label'], 'removed': ['same-label'], 'shared': 1,
        'reassigned': [], 'metadata_changed': [], 'identity_basis': 'dataset_version_id_and_sample_id',
    }


def workflow_records():
    cohort = dict(contrast_id='ab', name='A versus B', groups=[dict(label='A'), dict(label='B')])
    config = dict(mode='bulk_counts', bulk_model='shared_wald_v1', contrasts=[cohort],
                  method='deseq2_wald', minimum_total_counts=10)
    return dict(
        datasets=[dict(id='dataset', name='Counts', current_version_id='raw', updated_at='2026-11-10T00:00:01')],
        imports=[dict(id='import', dataset_id='dataset', dataset_version_id='raw', status='succeeded',
                      task_id='import-task', created_at='2026-11-10T00:00:01', config={}, files=[])],
        designs=[],
        maps=[],
        recipes=[
            dict(id='recipe', setup_id='setup', name='QC', current_version_id='display-recipe',
                 raw_dataset_version_id='raw', created_at='2026-11-10T00:00:02', params_json={'exclude_samples': []}),
            dict(id='display-recipe', setup_id='setup', name='QC', current_version_id='display-recipe',
                 raw_dataset_version_id='raw', created_at='2026-11-10T00:00:06',
                 params_json={'exclude_samples': [], 'normalization': 'vst', 'pca_components': 6,
                              'output_language': 'en'}),
        ],
        analysis_runs=[dict(id='qc', raw_dataset_version_id='raw', recipe_version_id='recipe',
                            processed_version_id='processed', task_id='qc-task', status='succeeded',
                            created_at='2026-11-10T00:00:03', steps=[])],
        plans=[
            dict(id='plan-v1', plan_id='plan', name='Differential', current_version_id='plan-v2',
                 kind='comparison', decision='confirmed', config_json=config, created_at='2026-11-10T00:00:04'),
            dict(id='plan-v2', plan_id='plan', name='New title', current_version_id='plan-v2',
                 kind='comparison', decision='draft',
                 config_json=config | {'output_language': 'en', 'contrasts': [cohort | {'name': 'Updated title'}]},
                 created_at='2026-11-10T00:00:07'),
            dict(id='ora-plan', plan_id='ora', name='ORA', current_version_id='ora-plan',
                 kind='ora', decision='confirmed', config_json={'bulk_enrichment': {}}, created_at='2026-11-10T00:00:08'),
            dict(id='figure-plan', plan_id='figure', name='ORA figure', current_version_id='figure-plan',
                 kind='figure', decision='confirmed', config_json={'figure_type': 'enrichment'},
                 created_at='2026-11-10T00:00:10'),
        ],
        bindings=[
            dict(plan_version_id=plan_id, source_kind='bio_processed_dataset_version', source_id='processed')
            for plan_id in ('plan-v1', 'plan-v2')
        ] + [
            dict(plan_version_id='ora-plan', source_kind='bio_insight_result_version', source_id='result'),
            dict(plan_version_id='figure-plan', source_kind='bio_insight_result_version', source_id='ora-result'),
        ],
        insight_runs=[
            dict(id='run', plan_version_id='plan-v1', result_version_id='result', task_id='compare-task',
                 status='succeeded', created_at='2026-11-10T00:00:05'),
            dict(id='ora-run', plan_version_id='ora-plan', result_version_id='ora-result', task_id='ora-task',
                 status='succeeded', outcome='not_applicable', reason='empty_foreground', created_at='2026-11-10T00:00:09'),
            dict(id='figure-run', plan_version_id='figure-plan', result_version_id=None, task_id='figure-task',
                 status='failed', created_at='2026-11-10T00:00:11'),
        ],
        resources=[],
    )


def test_display_revisions_keep_fixed_comparison_and_report_ready():
    from app.domain.bio_insights.bulk_workflow import project_workflow

    view = project_workflow('project', workflow_records())
    stages = {item['key']: item for item in view['stages']}
    assert stages['qc']['status'] == 'ready'
    assert stages['qc']['refs']['recipe_version_id'] == 'display-recipe'
    assert stages['qc']['reusable_processed_refs'] == {
        'dataset_id': 'dataset', 'dataset_version_id': 'raw', 'import_id': 'import', 'setup_id': 'setup',
        'recipe_version_id': 'recipe', 'analysis_run_id': 'qc', 'processed_version_id': 'processed',
        'task_id': 'qc-task',
    }
    assert stages['qc']['items'][1]['stale']
    assert stages['differential']['status'] == 'succeeded'
    assert stages['differential']['refs']['result_version_id'] == 'result'
    assert not stages['differential']['stale']
    assert stages['delivery']['status'] == 'ready'
    assert view['comparisons'][0]['processed_version_ids'] == ['processed']
    assert stages['functional']['status'] == 'not_applicable'
    assert stages['functional']['reason'] == 'empty_foreground'
    assert stages['functional']['refs']['task_id'] == 'ora-task'
    assert stages['functional']['items'][0]['status'] == 'failed'
    assert view['descendants'][0]['direct_comparison_version_ids'] == ['result']


def test_changed_sample_inclusion_blocks_current_differential_and_preserves_fixed_history():
    from app.domain.bio_insights.bulk_workflow import project_workflow

    records = workflow_records()
    records['recipes'][1]['params_json']['exclude_samples'] = ['excluded-sample']
    # A completed, independent setup for the same raw data must not satisfy the selected recipe.
    records['recipes'].append(dict(records['recipes'][0], id='separate-recipe', setup_id='separate-setup',
                                   current_version_id='separate-recipe'))
    records['analysis_runs'].append(dict(records['analysis_runs'][0], id='separate-qc',
                                        recipe_version_id='separate-recipe', processed_version_id='separate-processed'))

    view = project_workflow('project', records)
    stages = {item['key']: item for item in view['stages']}
    assert stages['qc']['refs']['recipe_version_id'] == 'display-recipe'
    assert 'reusable_processed_refs' not in stages['qc']
    assert stages['differential']['status'] == 'dependency_blocked'
    assert stages['differential']['stale']
    comparison, = view['comparisons']
    assert comparison['status'] == 'succeeded'
    assert comparison['stale_reasons'] == [
        dict(kind='recipe_version', version_id='recipe', current_version_id='display-recipe'),
    ]


def test_rebinding_same_exclusions_to_display_only_processed_version_preserves_comparison():
    from app.domain.bio_insights.bulk_workflow import project_workflow

    records = workflow_records()
    records['analysis_runs'].append(dict(records['analysis_runs'][0], id='display-qc',
                                        recipe_version_id='display-recipe', processed_version_id='display-processed'))
    for index, version in enumerate(('processed', 'display-processed')):
        records['bindings'][index]['source_id'] = version
        records['plans'][index]['config_json']['excluded_samples'] = [
            dict(processed_version_id=version, sample_id='held-out', reason='Prespecified exclusion'),
        ]

    view = project_workflow('project', records)
    comparison, = view['comparisons']
    assert comparison['refs']['result_version_id'] == 'result'
    assert not comparison['stale']
    assert view['stages'][3]['refs']['result_version_id'] == 'result'


def test_changed_model_marks_only_exact_descendants_stale_and_preserves_status():
    from app.domain.bio_insights.bulk_workflow import project_workflow

    records = workflow_records()
    records['plans'][1]['config_json']['minimum_total_counts'] = 25
    view = project_workflow('project', records)
    stages = {item['key']: item for item in view['stages']}
    assert stages['differential']['status'] == 'waiting_confirmation'
    assert stages['delivery']['status'] == 'dependency_blocked'
    assert view['comparisons'][0]['status'] == 'succeeded'
    assert view['comparisons'][0]['stale_reasons'] == [
        dict(kind='plan_version', version_id='plan-v1', current_version_id='plan-v2'),
    ]
    assert view['descendants'][0]['stale']
    assert view['descendants'][0]['status'] == 'not_applicable'
    assert view['descendants'][0]['comparison_version_ids'] == ['result']


def test_saved_design_finishes_the_step_and_keeps_recorded_operation():
    from app.domain.bio_insights.bulk_workflow import project_workflow

    records = workflow_records()
    records['designs'] = [
        dict(id='design-confirm', current_version_id='design-save', operation='confirm', content_json={},
             created_at='2026-11-10T00:00:00'),
        dict(id='design-save', current_version_id='design-save', operation='save', content_json={},
             created_at='2026-11-10T00:00:01'),
    ]
    design = project_workflow('project', records)['stages'][0]
    assert design['status'] == 'succeeded'
    assert design['refs']['design_version_id'] == 'design-save'
    assert design['operation'] == 'save'
    assert [item['operation'] for item in design['items']] == ['save', 'confirm']


def test_delivery_eligibility_marks_only_native_frozen_bulk_attachments():
    from app.domain.bio_insights.bulk_workflow import project_workflow

    records = workflow_records()
    records['bindings'].append(dict(plan_version_id='ora-plan', source_kind='bio_resource_version',
                                    source_id='fixed-resource'))
    records['plans'][3]['config_json']['bulk_enrichment_render'] = True
    records['insight_runs'][2].update(status='succeeded', result_version_id='ora-figure')
    records['plans'].append(dict(id='generic-figure', plan_id='generic', current_version_id='generic-figure',
                                 name='Generic plot', kind='figure', decision='confirmed',
                                 config_json={'figure_type': 'volcano'}, created_at='2026-11-10T00:00:10'))
    records['bindings'].append(dict(plan_version_id='generic-figure', source_kind='bio_insight_result_version',
                                    source_id='result'))
    records['insight_runs'].append(dict(id='generic-run', plan_version_id='generic-figure',
                                        result_version_id='generic-result', task_id='generic-task',
                                        status='succeeded', created_at='2026-11-10T00:00:11'))

    view = project_workflow('project', records)
    eligible = {item['refs']['result_version_id']: item['delivery_eligible'] for item in view['descendants']}
    assert eligible == {'ora-figure': True, 'ora-result': True, 'generic-result': False}

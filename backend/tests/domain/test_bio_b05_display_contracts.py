import pytest
from pydantic import ValidationError

from app.domain.bio_insights.contracts import CandidateConfig, FigureConfig, InsightPlanRequest


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def selection(**changes):
    return {'contrast_id': 'A_B', 'q_column': 'original_method_adjustment'} | changes


def source(kind='bio_insight_result_version', role='result', identifier='version'):
    return dict(source_kind=kind, source_id=identifier, role=role, sha256='a' * 64, locator={'kind': 'object'})


def plan(config, sources):
    return InsightPlanRequest.model_validate(dict(name='B05', kind=config['kind'], expected_revision=0,
                                                   sources=sources, config=config))


def test_bulk_heatmap_freezes_threshold_and_display_scaling_and_requires_fixed_result():
    config = dict(kind='figure', result_source_id='version', figure_type='bulk_heatmap',
                  bulk_selection=selection(), z_score=True, top_n=20)
    frozen = plan(config, [source()]).config.model_dump(mode='json')
    assert frozen['bulk_selection'] == selection(q_threshold=.05, minimum_absolute_effect=1.0, direction='both')
    assert frozen['z_score'] is True
    assert FigureConfig.model_validate(frozen).model_dump(mode='json') == frozen
    with pytest.raises(ValidationError):
        plan(config, [source('bio_processed_dataset_version', 'processed')])
    with pytest.raises(ValidationError):
        plan(config, [source(), source(identifier='unreferenced')])
    with pytest.raises(ValidationError):
        FigureConfig.model_validate(config | {'top_n': 101})


def test_processed_pca_rejects_a_comparison_or_new_transform():
    config = dict(kind='figure', result_source_id='version', figure_type='bulk_pca', bulk_panel='pca_scores')
    frozen = plan(config, [source('bio_processed_dataset_version', 'processed')]).config
    assert frozen.bulk_panel == 'pca_scores'
    with pytest.raises(ValidationError):
        plan(config, [source()])
    for invalid in (dict(z_score=True), dict(bulk_panel='qc_expression'), dict(bulk_selection=selection())):
        with pytest.raises(ValidationError):
            FigureConfig.model_validate(config | invalid)


def test_bulk_expression_accepts_a_tabular_feature_id_as_data():
    cfg = dict(kind='figure', result_source_id='version', figure_type='bulk_expression', bulk_selection=selection())
    assert FigureConfig.model_validate(cfg | {'feature_ids': ['gene/isoform']}).feature_ids == ['gene/isoform']
    with pytest.raises(ValidationError):
        FigureConfig.model_validate(cfg | {'feature_ids': ['gene\nisoform']})
    with pytest.raises(ValidationError):
        FigureConfig(result_source_id='version', figure_type='qpcr_samples', contrast_id='A_B', feature_ids=['gene/isoform'])


def test_bulk_candidate_top_n_is_separate_from_threshold_and_frozen_contrast():
    config = dict(kind='candidate', result_source_ids=['version'], primary_result_source_id='version',
                  source_contrasts={'version': 'A_B'}, steps=[], bulk_selection=selection(direction='down'), bulk_top_n=100)
    frozen = plan(config, [source()]).config.model_dump(mode='json')
    assert frozen['bulk_top_n'] == 100 and frozen['bulk_selection']['direction'] == 'down'
    assert frozen['steps'] == []
    for invalid in (dict(bulk_top_n=0), dict(source_contrasts={'version': 'B_A'}), dict(bulk_selection=None)):
        with pytest.raises(ValidationError):
            CandidateConfig.model_validate(config | invalid)


def test_historical_volcano_candidate_and_enrichment_wire_preserves_legacy_defaults():
    volcano = FigureConfig(result_source_id='version', figure_type='volcano').model_dump(mode='json')
    assert not {'bulk_selection', 'bulk_panel', 'enrichment_order'} & volcano.keys()
    assert not {'sample_groups', 'analysis_layer', 'feature_ids', 'z_score'} & volcano.keys()
    candidate = CandidateConfig.model_validate(dict(result_source_ids=['version'], primary_result_source_id='version',
        source_contrasts={'version': 'A_B'}, steps=[{'operation': 'union', 'source_ids': ['version']}])).model_dump(mode='json')
    assert not {'bulk_selection', 'bulk_top_n'} & candidate.keys()
    opt_in = volcano | {'figure_type': 'enrichment', 'enrichment_order': 'adjusted_metric_term_id'}
    assert FigureConfig.model_validate(opt_in).model_dump(mode='json')['enrichment_order'] == 'adjusted_metric_term_id'
    with pytest.raises(ValidationError):
        FigureConfig.model_validate(opt_in | {'figure_type': 'volcano'})


def test_bulk_plot_preview_checks_reviewed_result_contrast_and_saved_values():
    from app.domain.bio_insights.service import BioInsightsService

    config = FigureConfig.model_validate(dict(result_source_id='version', figure_type='bulk_heatmap',
        bulk_selection=selection()))
    resolved = dict(source_id='version', source_kind='bio_insight_result_version', metadata={'kind': 'comparison',
        'plan_config': {'schema_version': 2, 'mode': 'bulk_counts', 'bulk_model': 'shared_wald_v1',
                        'contrasts': [{'contrast_id': 'A_B'}]}},
        members={name: {} for name in ('comparison_results', 'model_normalized_counts',
                                       'model_sample_metadata', 'comparison_design')})
    check = lambda current: BioInsightsService._design(None, config, [current])
    assert check(resolved).executable
    assert not check(resolved | {'members': {'comparison_results': {}}}).executable
    assert not check(resolved | {'metadata': {'kind': 'comparison', 'plan_config': {'mode': 'continuous'}}}).executable
    other_contrast = config.model_copy(update={'bulk_selection': config.bulk_selection.model_copy(update={'contrast_id': 'B_A'})})
    assert not BioInsightsService._design(None, other_contrast, [resolved]).executable


def test_pca_redraw_preview_only_accepts_saved_bulk_pca_source():
    from app.domain.bio_insights.service import BioInsightsService

    config = FigureConfig(result_source_id='version', figure_type='bulk_pca', bulk_panel='pca_scores')
    meta = dict(assay='bulk_rna_counts', observation_level='sample', manifest={'schema_version': 2})
    resolved = dict(source_id='version', source_kind='bio_processed_dataset_version',
                    metadata=meta, members={'pca_scores': {}, 'pca_variance_ratio': {}, 'pca_data': {}})
    assert BioInsightsService._design(None, config, [resolved]).executable
    assert not BioInsightsService._design(None, config, [resolved | {'members': {}}]).executable
    wrong = resolved | {'metadata': meta | {'assay': 'single_cell'}}
    assert not BioInsightsService._design(None, config, [wrong]).executable


def test_display_probe_does_not_admit_statistical_tasks(tmp_path, monkeypatch):
    import json
    from app.domain.bio_insights import settings

    proof = tmp_path / 'display.json'
    for key in ('PAPERASSIST_BULK_DISPLAY_RUNTIME_MANIFEST', settings.BULK_MODEL_MANIFEST_ENV,
                settings.RUNTIME_MANIFEST_ENV):
        monkeypatch.setenv(key, str(proof))
    isolation = {key: 'denied' for key in ('network', 'file', 'fork', 'subprocess')}
    report = dict(schema_version=1, status='passed', profile='bulk_display', engine_version='bio_insights_v1.0.0',
        interpreter=settings.INTERPRETER, numeric_threads=1, lock_sha256=settings.engine_lock_digest(),
        code_digest=settings.engine_code_digest(), packages={'pydeseq2': '0.5.4', 'gseapy': '1.3.1'},
        isolation=isolation, checks={'bulk_saved_values_render': True}, peak_rss_kib=100,
        limits=settings.BioInsightsLimits().model_dump(), bulk_limits=settings.BioLimits().model_dump(),
        python='test', native_libraries=[])
    proof.write_text(json.dumps(report), encoding='utf-8')
    assert settings.runtime_identity(bulk_display=True)['available']
    assert not settings.runtime_identity()['available']
    assert not settings.runtime_identity(bulk_model=True)['available']
    proof.write_text(json.dumps(report | {'isolation': isolation | {'network': 'allowed'}}), encoding='utf-8')
    assert not settings.runtime_identity(bulk_display=True)['available']

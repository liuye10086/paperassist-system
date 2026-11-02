import pytest
from app.adapters.research_method_text import present_method


@pytest.fixture(autouse=True)
def postgres_schema():yield None


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_v2_method_body_keeps_sample_units_layer_actual_n_and_model_parameters(language):
    config=dict(kind='comparison',schema_version=2,mode='bulk_counts',design='paired',analysis_layer='raw_counts',method='deseq2_wald',
        contrasts=[dict(contrast_id='c',groups=[dict(label=g,sample_keys=[{'processed_version_id':'p','sample_id':'s'}]) for g in ('B','A')])],
        inference_unit='biological',inference_goal='inference',pairing_field='pair_id',size_factor_method='ratio')
    method=dict(id='insight-method-x',executed=True,source=dict(source_kind='bio_insight_result_member',source_id='x',sha256='a'*64),
        parameters=dict(frozen_config=config,layer={'unit':'counts','transform':'none'},biological_n_by_contrast={'c':4},model_diagnostics=[dict(contrast_id='c',formula='~ donor + condition',rank=5,residual_degrees_freedom=3,parameters={'refit_cooks':False})]))
    text='\n'.join(present_method(method,language,reference='methods.json')['paragraphs'])
    assert 'spots_numerator' not in text and 'selected_spots' not in text
    for value in ['n_numerator','n_pairs','selected_samples','raw_counts','ratio','biological_n_by_contrast','refit_cooks','~ donor + condition']:assert value in text


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_sample_heatmap_method_never_claims_group_mean_log1p(language):
    config=dict(kind='figure',figure_type='heatmap',sample_groups=[dict(label='A',sample_keys=[{'sample_id':'s'}])],analysis_layer='analysis',z_score=True,feature_ids=['f'])
    method=dict(id='insight-method-x',executed=True,source=dict(source_kind='bio_insight_result_member',source_id='x',sha256='a'*64),parameters=dict(frozen_config=config))
    text='\n'.join(present_method(method,language,reference='methods.json')['paragraphs'])
    assert 'mean log1p' not in text and 'selected_spots' not in text
    assert 'selected_samples' in text and 'z_score: true' in text

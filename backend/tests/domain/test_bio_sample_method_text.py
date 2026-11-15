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


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_v2_reader_method_describes_sample_direction_and_effective_counts_without_internal_fields(language):
    config=dict(kind='comparison',schema_version=2,mode='tabular',design='paired',
        contrasts=[dict(contrast_id='treated-control',groups=[dict(label=label,
            sample_keys=[dict(processed_version_id='p',sample_id='s')]) for label in ('Treated','Control')])])
    method=dict(id='insight-method-reader',executed=True,
        source=dict(source_kind='bio_insight_result_member',source_id='x',sha256='a'*64),
        parameters=dict(frozen_config=config))
    text='\n'.join(present_method(method,language,reader=True)['paragraphs'])
    for key in ('groups[0]','groups[1]','n_numerator','n_denominator','n_pairs',
                'selected_samples','spots_numerator','comparison_results','feature_sample_counts'):
        assert key not in text
    assert 'Treated' in text and 'Control' in text
    for phrase in (('sample','first group relative to the second group','per-feature','complete pairs','results workbook')
                   if language=='en' else ('样本','第一组相对第二组','每个特征','完整配对数','结果工作簿')):
        assert phrase in text


@pytest.mark.parametrize('language',['en','zh-CN'])
@pytest.mark.parametrize('config,parameters,forbidden,expected',[
    ({'kind':'ora'}, {}, ('ora_sets',), ('gene-set results','基因集结果')),
    ({'kind':'figure','sample_groups':[{'label':'A','sample_keys':[]}],'z_score':True}, {},
     ('z_score','true'), ('standardization','标准化')),
    ({'kind':'result_import'}, {'system_recomputed_q':{'recomputed':False}},
     ('recomputed: false',), ('not recomputed','未重算')),
    ({'kind':'candidate','ranking_mode':'weighted'}, {},
     ('score_status','score DESC'), ('complete evidence','完整证据')),
    ({'kind':'comparison','schema_version':1,'mode':'spot_exploratory'}, {},
     ('comparison_results','spots_numerator','donors_numerator'), ('results workbook','结果工作簿')),
])
def test_reader_science_paragraphs_avoid_internal_table_and_sort_names(language,config,parameters,forbidden,expected):
    method=dict(id='insight-method-prose',executed=True,
        source=dict(source_kind='bio_insight_result_member',source_id='x',sha256='a'*64),
        parameters=dict(frozen_config=config,**parameters))
    text='\n'.join(present_method(method,language,reader=True)['paragraphs'])
    for key in forbidden:
        assert key not in text
    assert expected[language=='zh-CN'] in text.lower()


@pytest.mark.parametrize('language',['en','zh-CN'])
@pytest.mark.parametrize('mode,single',[('descriptive',True),('descriptive',False),('donor_unpaired',False),('donor_paired',False)])
def test_composition_reader_preserves_cell_denominator_and_actual_inference_scope(language,mode,single):
    from app.domain.bio_insights.single_cell_composition_contracts import SingleCellCompositionConfig
    config=SingleCellCompositionConfig(processed_source_id='p',annotation_source_id='a',label_ids=['T'],
        numerator='Control' if single else 'Treated',denominator='Control',mode=mode).model_dump()
    method=dict(id='insight-method-composition',executed=True,
        source=dict(source_kind='bio_insight_result_member',source_id='x',sha256='a'*64),
        parameters=dict(frozen_config=config,inference_status='not_requested' if mode=='descriptive' else 'not_computable'))
    text='\n'.join(present_method(method,language,reader=True)['paragraphs'])
    for wrong in ('spatial','spot','空间点','comparison_results','composition_counts','composition_units','composition_assignments','composition_results'):
        assert wrong not in text
    for required in (('all retained cells','donor × condition','unknown','results workbook') if language=='en' else
                     ('全部保留细胞','供体 × 条件','未知','结果工作簿')):
        assert required in text
    if single:
        assert ('Single-condition description' if language=='en' else '单条件组成描述') in text
        assert ('relative to' if language=='en' else '相对') not in text
    if mode=='descriptive':
        assert ('No inferential test was requested' if language=='en' else '未请求推断检验') in text
    else:
        assert ('donors as the inference unit' if language=='en' else '以供体为推断单位') in text
        assert ('not computable' if language=='en' else '无法计算') in text.lower()
        assert ('paired donors' if language=='en' else '供体配对') in text if mode=='donor_paired' else True
    # The change is reader-only; archived machine-facing text remains stable.
    raw='\n'.join(present_method(method,language)['paragraphs'])
    assert 'spots_numerator' in raw


@pytest.mark.parametrize('language',['en','zh-CN'])
@pytest.mark.parametrize('weighted',[False,True])
def test_candidate_reader_translates_saved_ranking_directions(language,weighted):
    ranking='same-direction dependency-group support DESC, conflict ASC, primary q ASC, abs primary effect DESC, stable ID ASC; unknown last'
    method=dict(id='insight-method-ranking',executed=True,
        source=dict(source_kind='bio_insight_result_member',source_id='x',sha256='a'*64),
        parameters=dict(frozen_config=dict(kind='candidate',ranking_mode='weighted' if weighted else 'default'),ranking=ranking))
    text='\n'.join(present_method(method,language,reader=True)['paragraphs'])
    assert ' ASC' not in text and ' DESC' not in text
    for phrase in (('ascending','descending','unknown last') if language=='en' else ('升序','降序','未知值最后')):
        assert phrase in text
    assert ranking in '\n'.join(present_method(method,language)['paragraphs'])

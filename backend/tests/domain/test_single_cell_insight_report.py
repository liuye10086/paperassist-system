import io

import pytest
from docx import Document


def text_of(content):
    document=Document(io.BytesIO(content))
    return '\n'.join(p.text for p in document.paragraphs)+'\n'+'\n'.join(c.text for t in document.tables for row in t.rows for c in row.cells)


@pytest.mark.parametrize('language,heading',[('zh-CN','供者单位与组成分母'),('en','Donor units and composition denominators')])
def test_composition_word_preserves_unknown_denominator_and_no_inference(language,heading):
    from app.adapters.single_cell_insight_report import build_single_cell_insight_report
    config=dict(kind='comparison',schema_version=5,method='single_cell_composition',mode='descriptive',output_language=language,label_basis='Published author labels; not experimentally validated here')
    manifest=dict(summary=dict(total_cells=12),methods=dict(name='descriptive',warnings=['donor_missing']),inference_scope='sample_exploratory',source_bindings=[])
    tables={'composition_counts':[dict(unit_id='sample-1',condition='control',label='unknown',count=3,total=12,proportion=.25)]}
    content=build_single_cell_insight_report('result1','a'*64,config,manifest,tables,[])
    text=text_of(content)
    assert heading in text and 'unknown' in text and '0.25' in text and '12' in text
    assert 'donor_missing' in text and 'Published author labels' in text
    assert ('No inferential test was performed' if language=='en' else '未执行推断检验') in text


def test_pseudobulk_word_records_pairs_counts_and_exact_na_zero():
    from app.adapters.single_cell_insight_report import build_single_cell_insight_report
    config=dict(kind='comparison',mode='donor_paired',output_language='en',independence_basis='Eight donor pairs; capture and condition are confounded',minimum_total_counts=10)
    manifest=dict(summary=dict(actual_units=[dict(contrast_id='stim-control',n_numerator=8,n_denominator=8,complete_pairs=8)]),
        methods=dict(name='PyDESeq2_0.5.4_Wald',parameters={'independent_filter':False}),inference_scope='donor_inference',source_bindings=[])
    tables={'comparison_results':[dict(feature_id='ENSG1',effect_value=1.25,p_value=0,q_within_contrast=None)]}
    text=text_of(build_single_cell_insight_report('result2','b'*64,config,manifest,tables,[]))
    assert 'Eight donor pairs' in text and 'complete_pairs' in text and '8' in text
    assert 'Original integer counts' in text and 'ENSG1' in text and '1.25' in text and 'NA' in text
    assert 'PyDESeq2_0.5.4_Wald' in text


@pytest.mark.parametrize('kind',['ora','gsea_prerank'])
def test_empty_enrichment_word_uses_saved_background_without_claiming_enrichment(kind):
    from app.adapters.single_cell_insight_report import build_single_cell_insight_report
    config=dict(kind=kind,output_language='zh-CN')
    manifest=dict(summary={'row_count':0,'tested_background':1729},methods={'name':kind},inference_scope='derived',source_bindings=[dict(source_kind='bio_resource_version',source_id='resource-frozen',sha256='c'*64)])
    text=text_of(build_single_cell_insight_report('empty','d'*64,config,manifest,{'enrichment_results':[]},[]))
    assert 'resource-frozen' in text and '1729' in text
    assert '无结果行' in text and '不能解释为不存在生物学效应' in text


def test_report_table_excerpt_is_explicit_and_does_not_change_saved_rows():
    from app.adapters.single_cell_insight_report import build_single_cell_insight_report
    rows=[dict(feature_id='gene'+str(i),p_value=i/100) for i in range(31)]
    text=text_of(build_single_cell_insight_report('x','e'*64,dict(kind='comparison',mode='donor_unpaired',output_language='en'),dict(summary={},methods={},source_bindings=[],inference_scope='donor_inference'),{'comparison_results':rows},[]))
    assert '20 / 31' in text and 'gene19' in text and 'gene20' not in text
    assert len(rows)==31


def test_saved_composition_status_and_donor_counts_are_not_lost():
    from app.adapters.single_cell_insight_report import build_single_cell_insight_report
    config=dict(kind='comparison',method='single_cell_composition',mode='donor_paired',output_language='en')
    tables={'composition_results':[dict(category='uncertain',label_id=None,proportion_difference=0,p_value=None,p_adjust=None,inference_status='not_computable',reason='no_variation')],
        'aggregation_units':[dict(unit_id='d1-stim',donor='d1',condition='stim',spot_count=137,library_counts=56789)]}
    text=text_of(build_single_cell_insight_report('x','e'*64,config,dict(summary={},methods={},source_bindings=[]),tables,[]))
    assert all(s in text for s in ('uncertain','not_computable','no_variation','137','56789'))


def test_word_numeric_display_keeps_sign_zero_na_and_full_saved_values():
    from app.adapters.single_cell_insight_report import build_single_cell_insight_report
    row=dict(category='label',label_id='CD8_T',proportion_difference='-0.0123456789012345',
        proportion_ratio='0',p_value='1.234567890123e-12',p_adjust=None)
    before=dict(row)
    text=text_of(build_single_cell_insight_report('x','e'*64,
        dict(kind='comparison',method='single_cell_composition',mode='donor_paired',output_language='en'),
        dict(summary={},methods={},source_bindings=[]),{'composition_results':[row]},[]))
    assert '-0.0123457' in text and '1.23457e-12' in text
    assert '6 significant digits' in text and 'full precision' in text
    assert '\n0\n' in text and '\nNA' in text and row==before


def test_word_numeric_looking_identifiers_and_versions_remain_verbatim():
    from app.adapters.single_cell_insight_report import build_single_cell_insight_report
    text=text_of(build_single_cell_insight_report('x','e'*64,
        dict(kind='comparison',method='single_cell_composition',reference_version='1.0',output_language='en'),
        dict(summary={},methods={},source_bindings=[]),
        {'composition_units':[dict(unit_id='1e5',donor='001.20',condition='2.0',cell_count=10)]},[]))
    assert all('\n'+v+'\n' in text for v in ('1e5','001.20','2.0','1.0'))

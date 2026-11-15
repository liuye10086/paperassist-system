"""Readable method prose keeps exact frozen evidence and legacy composition."""
from copy import deepcopy
import io
import json
import zipfile

import pytest
from docx import Document

VERSION = 'bio_insight_readable_v1'


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def method(kind='comparison'):
    config = dict(kind=kind, mode='spot_exploratory', species_taxon_id=9606,
                  namespace='Ensembl', reference_version='GRCh38_release95',
                  data_driven_grouping=True,
                  contrasts=[dict(contrast_id='cluster_vs_rest', numerator=dict(label='cluster 0',
                     observation_keys=[dict(processed_version_id='fixed-data', barcode=f'NUM_{i:04}') for i in range(379)]),
                     denominator=dict(label='other fixed clusters', observation_keys=[
                         dict(processed_version_id='fixed-data', barcode=f'DEN_{i:04}') for i in range(783)]))])
    return dict(id='insight-method-fixed', title='差异与功能分析方法 / Differential and functional methods',
                description=json.dumps(config), source=dict(source_kind='bio_insight_result_version',
                source_id='result-fixed', sha256='a' * 64), executed=True,
                parameters=dict(name='two_sided_rank_sum_normal_tie_corrected',
                    correction='BH_predeclared_tests_NA_internal_one', direction='numerator_relative_to_denominator',
                    parameters=dict(continuity_correction=False, effect_pseudocount=1e-9),
                    family_contrast_ids=['cluster_vs_rest'], inference_scope='spot_exploratory',
                    source_inference_scopes=['spot_exploratory'], source_data_driven_grouping=True,
                    provenance='system_computed', frozen_config=config),
                software=dict(engine_version='bio_insights_v1.0.0', code_digest='b' * 64))


def snapshot(methods, language='en', modern=True):
    value = dict(title='Fixed report', language=language, finding=dict(id='finding', sha256='c' * 64,
        content=dict(sources=[], facts=[], methods=methods, claims=[], conflicts=[], gaps=[], limitations=[], warnings=[])),
        figures=[], tables=[], real_model_calls=0)
    if modern:
        value['method_presentation_version'] = VERSION
    return value


def payload(methods, language='en', modern=True):
    source = dict(id='finding',kind='research_finding_version',content=dict(facts=[],methods=methods,
        claims=[],conflicts=[],gaps=[],warnings=[],limitations=[]))
    value = dict(project_id='project', output_language=language,base_snapshot=None,sources=[source],
        selected_source_ids=['finding'],thesis_context=None,sections=['results','materials_and_methods'],
        document_context=dict(delivery_id='delivery',document_kind='sci'),manual_notes='')
    if modern:
        value['method_presentation_version'] = VERSION
    return value


TOPIC_EXPECTATIONS = {
    'slingshot': (('Slingshot', 'Harmony-adjusted PCA', 'root cluster', 'FIXED_ROOT', '4', 'pseudotime', 'elapsed time'),
                  ('Slingshot', '经 Harmony 校正的 PCA', '根分群', 'FIXED_ROOT', '4', '拟时序', '真实时间')),
    'genie3': (('GENIE3', 'unintegrated log1p', 'TF_EXAMPLE', '31, 43', '75', 'predictive importance', 'external replication'),
               ('GENIE3', '未整合的 log1p', 'TF_EXAMPLE', '31, 43', '75', '预测重要性', '独立重复')),
    'per_donor': (('CellChat', 'donor × condition', 'literature', 'CC BY 4.0', 'cell permutations', 'no donor-level comparison'),
                  ('CellChat', '供体 × 条件', '文献', 'CC BY 4.0', '细胞置换', '未请求供体层比较')),
    'paired': (('CellChat', 'paired t test', 'complete donor pairs', 'STIM − BASE', 'Benjamini–Hochberg', 'not computable'),
               ('CellChat', '配对 t 检验', '完整供体配对', 'STIM − BASE', 'Benjamini–Hochberg', '无法计算')),
    'unpaired': (('CellChat', 'Welch t test', 'independent donors', 'STIM − BASE', 'Benjamini–Hochberg', 'not computable'),
                 ('CellChat', 'Welch t 检验', '独立供体', 'STIM − BASE', 'Benjamini–Hochberg', '无法计算')),
}


def fixed_topic(case):
    algorithm = case if case in ('slingshot', 'genie3') else 'cellchat'
    config = dict(kind='integration', schema_version=2, method=algorithm, cluster_ids=['C0', 'C1'],
                  condition_values=['BASE', 'STIM'], label_ids=['X', 'Y'], label_basis='Frozen labels',
                  processed_source_id='d'*64)
    parameters = dict(name=algorithm, frozen_config=config, label_names={'X':'B cells','Y':'T cells'},
                      exclusions={'not_selected':2})
    if algorithm == 'slingshot':
        config.update(representation='pca_harmony', n_components=10, root_cluster='FIXED_ROOT',
                      root_basis='Saved biological basis', seed=17)
        parameters.update(input_layer='pca_harmony', actual_components=4, lineage_clusters=[['C0','C1']])
    elif algorithm == 'genie3':
        config.update(gene_ids=['TF_EXAMPLE','GX'], tf_ids=['TF_EXAMPLE'], tf_basis='Saved TF list',
                      n_trees=75, seed=31, stability_seed=43)
        parameters.update(input_layer='unintegrated_log1p', parameters=dict(n_trees=75,seeds=[31,43]),
                          tf_ids=['TF_EXAMPLE'], gene_ids=['TF_EXAMPLE','GX'], tf_basis='Saved TF list')
    else:
        config.update(communication_mode=case, lr_resource_id='human-demo-literature-v1', n_boot=37,
                      min_cells=12, seed=17)
        parameters.update(input_layer='unintegrated_log1p',
            donor_test={'per_donor':'not_requested','paired':'paired_t','unpaired':'welch_t'}[case],
            resource=dict(resource_id='human-demo-literature-v1',license='CC BY 4.0'),
            parameters=dict(n_boot=37,min_cells_exclusive=12,seed=17,lr_ids=['CXCL12_CXCR4']))
    return dict(method('integration'), id='insight-method-'+case,description=json.dumps(parameters),parameters=parameters)


@pytest.mark.parametrize('language',['en','zh-CN'])
@pytest.mark.parametrize('case',TOPIC_EXPECTATIONS)
def test_single_cell_topic_exports_keep_only_the_recorded_scientific_method(language,case,tmp_path):
    from app.adapters.research_report_render import render_report
    from openpyxl import load_workbook

    fixed=fixed_topic(case)
    snap=snapshot([fixed],language)
    before=deepcopy(snap)
    render_report(dict(snapshot=snap,tables=[],figures=[],package_files=[]),tmp_path)
    doc=Document(tmp_path/'analysis.docx')
    book=load_workbook(tmp_path/'results.xlsx',read_only=True)
    try:
        text_parts=(
            '\n'.join(p.text for p in doc.paragraphs),
            '\n'.join(str(cell) for row in book['Methods'].values for cell in row),
            (tmp_path/'methods.txt').read_text(encoding='utf-8'),
        )
    finally:book.close()
    for text in text_parts:
        assert all(value in text for value in TOPIC_EXPECTATIONS[case][language=='zh-CN']), (case,text)
        assert all(value not in text for value in ('Frozen cross-data integration','冻结对应与跨数据整合',
            'coefficients only','只计算系数','predeclared pairs','预声明特征对','unintegrated_log1p',
            'pca_harmony','d'*64,'condition_values['))
    with zipfile.ZipFile(tmp_path/'analysis_package.zip') as archive:
        assert json.loads(archive.read('parameters.json'))==[fixed['parameters']]
        assert json.loads(archive.read('report_snapshot.json'))==before
    assert snap==before


@pytest.mark.parametrize(('language','technical_sha','model_sha'),[
    ('en','2b9d7383ca729ecac7203d6768a7226f687d21e65677b18bc54e01a2c8eba776',
     '18b1a20e8d189f9b37760df64e769e2f3af6f7c233e7006b6032b6caf26efa5d'),
    ('zh-CN','490f71fc1eeef6387cafbf856545e6ddca99aec9403c964daf2241a1a956ab07',
     'c7ad201930c0c1a04f271bcad84fca3cbc47e481ae9a72d6649387bb67680a56'),
])
def test_topic_reader_fix_preserves_technical_and_model_golden(language,technical_sha,model_sha):
    from hashlib import sha256
    from app.adapters.research_method_text import present_method
    from app.domain.reader_reports.content import canonical, make_material

    cross_data=dict(method('integration'),description='',
        parameters={'frozen_config':{'kind':'integration','schema_version':1,'metric':'pearson'}})
    methods=[fixed_topic(case) for case in TOPIC_EXPECTATIONS]+[cross_data]
    technical=[present_method(m,language,reader=False,reference='frozen source') for m in methods]
    assert sha256(canonical(technical).encode()).hexdigest()==technical_sha
    assert sha256(canonical(make_material(snapshot(methods,language),[])).encode()).hexdigest()==model_sha
    title = present_method(cross_data,language,reader=True)['title']
    assert title==('Frozen cross-data integration' if language=='en' else '冻结对应与跨数据整合')


@pytest.mark.parametrize('language',['zh-CN','en'])
def test_report_and_fact_prose_summarize_large_fixed_groups_without_mutating_evidence(language):
    from app.adapters.research_report_docx import build_report
    from app.domain.research_results.fact_draft import compose
    fixed = method(); snap = snapshot([fixed],language); request = payload([fixed],language)
    before = deepcopy((snap,request))
    document = Document(io.BytesIO(build_report(snap,[])))
    prose = '\n'.join(p.text for p in document.paragraphs)
    candidate = compose(request); text = candidate['methods'][0]['text']
    for rendered in (prose,text):
        assert 'NUM_0000' not in rendered and 'DEN_0000' not in rendered
        assert 'observation_keys' not in rendered and 'frozen_config' not in rendered
        assert len(rendered) < 14000
        for kept in ('379','783','cluster 0','other fixed clusters','1e-09'):
            assert kept in rendered
        assert ('not independent donors' in rendered) if language=='en' else ('不等于独立供体' in rendered)
    assert 'result-fixed' in text and 'a'*64 in text
    for raw in ('BH_predeclared_tests_NA_internal_one','two_sided_rank_sum_normal_tie_corrected','false'):
        assert raw in text
        assert raw not in prose
    assert 'Benjamini–Hochberg' in prose
    assert ('tie correction' if language=='en' else '校正并列秩') in prose
    assert all(value not in prose for value in ('result-fixed','a'*64,'bio_insights_v1.0.0'))
    assert candidate['methods'][0]['research_method'] == fixed
    assert (snap,request)==before


def test_legacy_payload_and_report_snapshot_keep_their_original_text():
    from app.adapters.research_report_docx import build_report
    from app.domain.research_results.fact_draft import compose
    fixed=method(); request=payload([fixed],modern=False)
    expected=fixed['title']+': '+fixed['description']+' '+json.dumps(fixed['parameters'],ensure_ascii=False,sort_keys=True,separators=(',',':'))+' bio_insights_v1.0.0'
    assert compose(request)['methods'][0]['text']==expected
    doc=Document(io.BytesIO(build_report(snapshot([fixed],modern=False),[])))
    assert all('observation_keys' not in p.text and 'NUM_0000' not in p.text for p in doc.paragraphs)


def test_duplicate_method_prose_references_the_prior_block_but_keeps_each_full_metadata():
    from app.domain.research_results.fact_draft import compose
    fixed=method(); duplicate=deepcopy(fixed);duplicate['id']='insight-method-member'
    duplicate['source']=dict(fixed['source'],source_kind='bio_insight_result_member',source_id='member-fixed',sha256='d'*64)
    result=compose(payload([fixed,duplicate]))
    assert len(result['methods'])==2
    assert len(result['methods'][1]['text']) < 700
    assert 'method block 1' in result['methods'][1]['text']
    assert result['methods'][1]['research_method']==duplicate
    assert 'member-fixed' in result['methods'][1]['text'] and 'd'*64 in result['methods'][1]['text']


@pytest.mark.parametrize('language',['zh-CN','en'])
def test_gsea_and_external_zero_false_missing_and_resource_details_are_explicit(language):
    from app.domain.research_results.fact_draft import compose
    gsea=method('gsea_prerank');gsea['id']='insight-method-gsea'
    config=dict(kind='gsea_prerank',contrast_id='cluster_vs_rest',complete_ranking=True,signed_ranking=True,
                ranking_column='statistic',permutation_num=1000,seed=0,weight=1.0,min_size=15,max_size=500)
    gsea['parameters']=dict(name='GSEApy_1.3.1_prerank',inference_scope='derived',source_inference_scopes=['spot_exploratory'],
        correction='GSEA_joint_null_FDR_not_BH',frozen_config=config,seed=0,ascending=None,
        resources=[dict(resource_id='go-version',release='EBI-GOEX-2026-06-16',namespace='UniProtKB',species_taxon_id=9606)],
        mapping=dict(source_namespace='Ensembl',target_namespace='UniProtKB',strip_ensembl_version=True),
        tied_rank_fraction=0.0,zero_empirical_p_note='Preserved as zero; not evidence of infinite significance.')
    external=method('result_import');external['id']='insight-method-import'
    external['parameters']=dict(name='external_result_import',inference_scope='external_result',provenance='external_result',
        original_method='declared external method',original_correction_scope='declared q',
        system_recomputed_q=dict(recomputed=False,method=None,valid_p_values=0),
        frozen_config=dict(kind='result_import',na_values=['','NOT_MEASURED'],recompute_q=False,complete_tested_universe=False))
    result=compose(payload([gsea,external],language))
    text='\n'.join(p['text'] for p in result['methods'])
    for value in ('GSEApy_1.3.1_prerank','GSEA_joint_null_FDR_not_BH','1000','0','EBI-GOEX-2026-06-16','Ensembl',
                  'UniProtKB','false','NOT_MEASURED','declared external method','declared q'):
        assert value in text
    assert 'observation_keys' not in text
    assert ('not recomputed' in text) if language=='en' else ('未重算' in text)


def test_heatmap_is_mean_log1p_not_zscore_and_old_non_b04_method_is_unchanged():
    from app.domain.research_results.fact_draft import compose
    heat=method('figure');config=heat['parameters']['frozen_config'];config['figure_type']='heatmap'
    config['expression_groups']=[config['contrasts'][0]['numerator'],config['contrasts'][0]['denominator']]
    heat['parameters']['actual_figure_type']='heatmap'
    legacy=dict(id='method-old',title='Legacy method',description='Original narrative',source=heat['source'],
                parameters={'seed':0},software={},executed=False)
    result=compose(payload([heat,legacy]))
    assert 'mean log1p' in result['methods'][0]['text'] and 'no row z-score' in result['methods'][0]['text']
    assert result['methods'][1]['text']=='Not executed: Legacy method: Original narrative {"seed":0}'


def test_report_package_contains_helper_and_full_parameters_for_offline_rebuild(tmp_path):
    from app.adapters.research_report_render import render_report
    from app.adapters import research_method_text
    from openpyxl import load_workbook
    import hashlib,subprocess,sys
    from pathlib import Path
    snap=snapshot([method()]); out=tmp_path/'out';out.mkdir()
    raw=b'feature_id\tvalue\n=GENE1\t0\nGENE2\tNA\nGENE3\t\nGENE4\t0.0000000000000000123\n'
    source=tmp_path/'table.tsv';source.write_bytes(raw)
    table=dict(key='fixed_values',columns=['feature_id','value'],expected_rows=4,sha256=hashlib.sha256(raw).hexdigest())
    snap['tables']=[table]
    render_report(dict(snapshot=snap,tables=[dict(table,path=str(source))],figures=[],package_files=[]),out)
    with zipfile.ZipFile(out/'analysis_package.zip') as archive:
        assert 'rebuild_support/research_method_text.py' in archive.namelist()
        assert archive.read('rebuild_support/research_method_text.py')==Path(research_method_text.__file__).read_bytes()
        params=json.loads(archive.read('parameters.json')); index=json.loads(archive.read('method_index.json'))
        assert params[0]==snap['finding']['content']['methods'][0]['parameters']
        assert index==[dict(method_id='insight-method-fixed',parameters_index=0,
            parameters_sha256=hashlib.sha256(research_method_text.canonical(params[0]).encode()).hexdigest())]
        assert archive.read('tables/table_000.tsv')==raw
        assert json.loads(archive.read('report_snapshot.json'))==snap
        archive.extractall(tmp_path/'package')
    for script in ('verify_package.py','rebuild_report.py'):
        run=subprocess.run([sys.executable,str(tmp_path/'package'/script)],capture_output=True,text=True)
        assert run.returncode==0,run.stderr
    for name in ('analysis.docx','results.xlsx'):
        with zipfile.ZipFile(out/name) as before,zipfile.ZipFile(tmp_path/'package/rebuilt'/name) as after:
            key='word/document.xml' if name.endswith('docx') else 'xl/worksheets/sheet6.xml'
            assert before.read(key)==after.read(key)
    book=load_workbook(out/'results.xlsx',read_only=True,data_only=False)
    assert list(book['fixed_values'].values)==[('feature_id','value'),('=GENE1','0'),('GENE2','NA'),('GENE3',None),('GENE4','0.0000000000000000123')]
    assert book['fixed_values']['A2'].data_type=='s'
    assert all('NUM_0000' not in str(row) for row in book['Methods'].values)
    book.close()


def test_large_legacy_source_is_readable_and_renderer_identity_covers_helper():
    from app.adapters.research_results_xlsx import build_workbook
    from app.adapters.research_report_render import renderer_identity
    from app.adapters import research_report_render
    from pathlib import Path
    import hashlib
    from openpyxl import load_workbook
    content,_=build_workbook(snapshot([method()],modern=False),[])
    with io.BytesIO(content) as stream:
        book=load_workbook(stream,read_only=True,data_only=False)
        assert all('NUM_0000' not in str(row) and 'a'*64 not in str(row) for row in book['Methods'].values)
        book.close()
    root=Path(research_report_render.__file__).parent
    names=('research_report_render.py','research_report_child.py','research_report_docx.py','research_results_xlsx.py',
        'research_report_images.py','research_method_text.py','reader_report_presentation.py')
    paths=[root/name for name in names]+[root.parent/'domain/research_results/report_package.py']
    assert renderer_identity()['code_digest']==hashlib.sha256(b''.join(p.read_bytes() for p in paths)).hexdigest()


def test_school_section_uses_same_versioned_method_text_without_changing_source_metadata():
    from app.domain.research_results.fact_draft import compose
    for modern in (False,True):
        request=payload([method()],modern=modern)
        request['document_context']['document_kind']='thesis'
        chapters=[dict(id='methods',purpose='materials_and_methods',title='Methods',level=1,output_language='en',result_group_ids=[]),
                  dict(id='results',purpose='results',title='Results',level=1,output_language='en',result_group_ids=['research-results'])]
        request['thesis_context']=dict(chapters=chapters,confirmation=dict(chapters=chapters))
        candidate=compose(request)
        assert candidate['sections'][0]['paragraphs']==candidate['methods']
        assert candidate['methods'][0]['research_method']==request['sources'][0]['content']['methods'][0]
        assert ('NUM_0000' in candidate['methods'][0]['text']) is not modern


def test_unknown_presentation_version_fails_closed_and_different_scientific_parameters_do_not_deduplicate():
    from app.domain.research_results.fact_draft import compose
    request=payload([method()]);request['method_presentation_version']='future'
    with pytest.raises(ValueError,match='presentation version'):compose(request)
    first=method();second=deepcopy(first);second['id']='insight-method-second'
    second['parameters']['parameters']['continuity_correction']=True
    candidate=compose(payload([first,second]))
    assert 'method block 1' not in candidate['methods'][1]['text']
    assert 'continuity_correction: true' in candidate['methods'][1]['text']


def test_long_resource_descriptions_stay_in_full_metadata_while_releases_are_readable():
    from app.adapters.research_results_xlsx import build_workbook
    from openpyxl import load_workbook
    fixed=method('ora')
    fixed['parameters']['resources']=[dict(resource_id=f'resource-{i}',release=f'release-{i}',
        source=dict(description=f'description-{i}-'+'x'*3990)) for i in range(10)]
    before=deepcopy(fixed)
    raw,_=build_workbook(snapshot([fixed]),[])
    book=load_workbook(io.BytesIO(raw),read_only=True,data_only=False)
    text='\n'.join(str(row[2]) for row in list(book['Methods'].values)[1:])
    for i in range(10):
        assert f'release-{i}' in text
        assert f'description-{i}-' not in text
    assert fixed==before
    book.close()


def test_methods_are_scientific_summaries_not_internal_or_inapplicable_parameter_dumps():
    from app.domain.research_results.fact_draft import compose
    gsea=method('gsea_prerank');gsea['parameters'].update(estimated_work_units=201530000,
        estimated_working_bytes=951203696,seed=0,permutation_num=1000,complete_input_universe=True)
    heat=method('figure');heat['parameters']['frozen_config'].update(figure_type='heatmap',intersection_k=None,term_row_key=None)
    candidate=method('candidate');candidate['parameters']['frozen_config']['ranking_mode']='lexicographic'
    candidate['parameters'].update(ranking='support DESC, q ASC',dependencies={'independence_verified':False},
        weighted_components={'unused_weight_component':'NOT_APPLICABLE'})
    request=payload([gsea,heat,candidate]);before=deepcopy(request)
    text='\n'.join(x['text'] for x in compose(request)['methods'])
    for field in ('estimated_work_units','estimated_working_bytes','intersection_k','term_row_key','weighted_components','NOT_APPLICABLE'):
        assert field not in text
    for value in ('seed: 0','permutation_num: 1000','support DESC, q ASC','independence_verified: false','mean log1p'):
        assert value in text
    assert request==before


def test_mode_specific_summaries_cover_donors_explicit_background_weighting_and_external_recomputed_q():
    from app.domain.research_results.fact_draft import compose
    donor=method();donor['parameters']['frozen_config'].update(mode='donor_paired',independence_confirmed=True,
        mapping_confirmed=True,batch_adjustment=False,independence_basis='confirmed donor mapping')
    donor['parameters'].update(name='PyDESeq2_0.5.4_Wald',parameters=dict(cooks_filter=True,independent_filter=False,
        lfc_shrinkage=False,minimum_total_counts=10,refit_cooks=False,size_factors_fit_type='poscounts'),
        model_diagnostics=[dict(formula='~ donor + condition',fit_type_requested='parametric',fit_type_effective='mean',residual_degrees_freedom=2)])
    ora=method('ora');ora['parameters']['frozen_config'].update(background_source_id='explicit-background',background_member_key='background',foreground_member_key='foreground')
    candidate=method('candidate');candidate['parameters']['frozen_config'].update(ranking_mode='weighted',
        weights=[dict(item='support_fraction',weight=1.0,required=False)],steps=[dict(operation='annotation',annotation_field='known',annotation_operator='eq',annotation_value=False)])
    candidate['parameters'].update(weighted_components={'support_fraction':'known / selected'},weighted_unknown='required missing => null')
    external=method('result_import');external['parameters']['system_recomputed_q']=dict(recomputed=True,method='BH',family_size=7,valid_p_values=6,na_p_values=1)
    text='\n'.join(m['text'] for m in compose(payload([donor,ora,candidate,external]))['methods'])
    for required in ('~ donor + condition','fit_type_effective: mean','independent_filter: false','independence_confirmed: true',
                     'explicit-background','foreground','weight: 1.0','required: false','annotation_value: false','known / selected',
                     'recomputed: true','valid_p_values: 6'):
        assert required in text


@pytest.mark.parametrize('kind,config,expected',[
    ('venn',dict(intersection_mode='at_least_k',intersection_k=2,selected_sets=[dict(label='up genes',q_threshold=0.05,direction='up')]),'intersection_k: 2'),
    ('upset',dict(intersection_mode='exclusive',selected_sets=[dict(label='down genes',q_threshold=0.01,direction='down')]),'intersection_mode: exclusive'),
    ('gsea',dict(term_row_key='selected-term',member_key='gsea_results'),'term_row_key: selected-term'),
    ('enrichment',dict(enrichment_style='bar',q_column='q_global_family'),'enrichment_style: bar')])
def test_figure_summaries_select_actual_scientific_mode(kind,config,expected):
    from app.domain.research_results.fact_draft import compose
    fixed=method('figure');fixed['parameters']['frozen_config'].update(figure_type=kind,**config)
    fixed['parameters'].update(actual_figure_type=kind,empty_result=False,analysis_recomputed=False,zero_q_display_floor=1e-300)
    text=compose(payload([fixed]))['methods'][0]['text']
    assert expected in text and 'empty_result: false' in text and 'analysis_recomputed: false' in text
    if kind in ('venn','upset'):assert 'q_threshold:' in text


@pytest.mark.parametrize('language',['zh-CN','en'])
def test_weighted_candidate_status_then_score_then_frozen_tie_break(language):
    from app.domain.research_results.fact_draft import compose
    fixed=method('candidate');fixed['parameters']['frozen_config']['ranking_mode']='weighted'
    fixed['parameters']['ranking']='support DESC, conflict ASC, primary q ASC, stable ID ASC'
    text=compose(payload([fixed],language))['methods'][0]['text']
    assert 'complete → partial → unavailable' in text
    assert 'score DESC' in text
    assert ('tie-break' in text if language=='en' else '同层同分' in text)
    assert 'tie_break: support DESC, conflict ASC, primary q ASC, stable ID ASC' in text

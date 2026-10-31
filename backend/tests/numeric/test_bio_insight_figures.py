import hashlib
import json
from pathlib import Path
import pytest


def member(root,key,fmt,content):
    path=root/(key+'.'+fmt);path.write_bytes(content)
    return dict(path=str(path),sha256=hashlib.sha256(content).hexdigest(),size_bytes=len(content),format=fmt,role='table')


def fixture(tmp_path,kind='volcano'):
    from app.domain.bio_insights.contracts import FigureConfig
    source=dict(source_id='r',source_kind='bio_insight_result_version',role='result',sha256='a'*64,
        metadata=dict(kind='comparison',species_taxon_id=9606,namespace='Ensembl',reference_version='fixture',inference_scope='spot_exploratory'),
        members={'comparison_results':member(tmp_path,'comparison_results','tsv',
            b'row_key\tfeature_id\tcontrast_id\tnumerator\tdenominator\teffect_value\teffect_name\teffect_unit\tq_within_contrast\tinference_scope\n1\tG1\tc\tA\tB\t2\teffect_log2_normalized\tlog2 ratio\t0\tspot_exploratory\n2\tG2\tc\tA\tB\t-2\teffect_log2_normalized\tlog2 ratio\t0.01\tspot_exploratory\n3\tG3\tc\tA\tB\t\teffect_log2_normalized\tlog2 ratio\t\tspot_exploratory\n')})
    config=FigureConfig(figure_type=kind,result_source_id='r',contrast_id='c',width_inches=4.,height_inches=3.,dpi=100).model_dump(mode='json')
    return dict(schema_version=1,kind='bio_insight_figure',identity={'source_digest':'b'*64},config=config,sources=[source])


def test_volcano_writes_all_formats_and_keeps_original_zero_na(tmp_path):
    from app.adapters.bio_insights_engine.figures import run_figure
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_insights_process import validate_artifacts
    payload=fixture(tmp_path);output=tmp_path/'out';output.mkdir();writer=Writer(output)
    result=run_figure(payload,writer)
    assert result['inference_scope']=='visualization' and result['methods']['upstream_inference_scope']=='spot_exploratory'
    assert {'png','tiff','svg','pdf'}<={r['format'] for r in writer.artifacts}
    data=json.loads((output/'plot_data.json').read_text())
    assert data['rows'][0]['q_value']==0 and data['rows'][0]['display_neg_log10_q']==300
    assert any(r['feature_id']=='G3' and r['q_value'] is None for r in data['rows'])
    validate_artifacts(writer.artifacts,output)


def test_gsea_curve_rebuild_matches_es_and_rejects_wrong_identity():
    from app.adapters.bio_insights_engine.figures import running_enrichment
    values=[4.,3.,2.,1.,-1.,-2.]
    result=running_enrichment(values,[0,1],1.,1.)
    assert result[-1]==pytest.approx(0) and max(result)==pytest.approx(1)
    with pytest.raises(ValueError):running_enrichment(values,[0,1],1.,0.2)


def test_intersection_counts_are_explicit_not_estimated_from_venn_areas():
    from app.adapters.bio_insights_engine.figures import intersections
    sets=[{'a','b','c'},{'b','c','d'},{'c'}]
    values=intersections(sets)
    assert next(r for r in values if r['membership']==[True,True,True])['exclusive_count']==1
    assert next(r for r in values if r['membership']==[True,True,False])['inclusive_count']==2
    assert sum(r['exclusive_count'] for r in values)==4


def test_figure_rejects_configured_axes_it_does_not_execute(tmp_path):
    from app.adapters.bio_insights_engine.figures import run_figure
    from app.adapters.bio_engine.manifest import Writer
    payload=fixture(tmp_path);payload['config']['x_column']='statistic'
    output=tmp_path/'out';output.mkdir()
    with pytest.raises(ValueError,match='figure_axis_contract_mismatch'):run_figure(payload,Writer(output))


@pytest.mark.parametrize('kind',['enrichment','gsea','venn','upset','candidate_evidence'])
def test_other_figures_use_real_members_and_preserve_inherited_scope(tmp_path,kind):
    from app.adapters.bio_insights_engine.figures import run_figure
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_insights_process import validate_artifacts
    payload=fixture(tmp_path);source=payload['sources'][0];c=payload['config'];c.update(figure_type=kind)
    source['metadata'].update(upstream_inference_scopes=['spot_exploratory'],data_driven_grouping=True)
    if kind=='enrichment':
        source['metadata'].update(kind='ora',inference_scope='derived')
        source['members']['enrichment_results']=member(tmp_path,'enrichment_results','tsv',b'row_key\tterm_id\tterm_name\tcontrast_id\tgene_ratio\tq_value\tk\nT1\tGO:1\tTest term\tc\t0.2\t0.5\t2\n')
    elif kind=='gsea':
        source['metadata'].update(kind='gsea_prerank',inference_scope='derived');c['term_row_key']='T1'
        source['members']['gsea_ranking']=member(tmp_path,'gsea_ranking','tsv',b'rank\tfeature_id\tstatistic\n0\tG1\t3\n1\tG2\t2\n2\tG3\t-1\n3\tG4\t-2\n')
        source['members']['gsea_curves']=member(tmp_path,'gsea_curves','json',json.dumps(dict(rank_zero_based=True,rank_member_key='gsea_ranking',terms=[dict(row_key='T1',term_id='GO:1',hit_indices=[0,1],weight=1,es=1,nes=1.5,fdr_q_value=.1)])).encode())
    elif kind in ('venn','upset'):
        import copy
        second=copy.deepcopy(source);second['source_id']='r2';payload['sources'].append(second)
        c['result_source_ids']=['r','r2'];c['intersection_mode']='all'
        c['selected_sets']=[dict(result_source_id=sid,contrast_id='c',label=label,q_column='q_within_contrast',q_threshold=.05,minimum_absolute_effect=1,direction=direction) for sid,label,direction in [('r','Up','up'),('r2','Both','both')]]
    else:
        source['metadata'].update(kind='candidate',inference_scope='derived')
        source['members']['candidate_results']=member(tmp_path,'candidate_results','tsv',b'feature_id\nG1\nG2\n')
        source['members']['candidate_evidence']=member(tmp_path,'candidate_evidence','tsv',b'feature_id\tsource_id\tsupported\tmissing\tdirection\nG1\tA\tTrue\tFalse\t1\nG1\tB\tFalse\tTrue\t\nG2\tA\tTrue\tFalse\t\nG2\tB\tFalse\tFalse\t0\n')
    output=tmp_path/'out';output.mkdir();writer=Writer(output);result=run_figure(payload,writer)
    validate_artifacts(writer.artifacts,output)
    assert result['methods']['upstream_inference_scopes']==['spot_exploratory']
    assert result['methods']['data_driven_grouping'] is True
    assert result['methods']['axes'] and result['methods']['input_member']
    if kind in ('venn','upset'):assert result['methods']['actual_figure_type']=='upset'


def test_heatmap_uses_actual_retained_expression_means(tmp_path):
    from app.adapters.bio_insights_engine.figures import run_figure
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_insights_process import validate_artifacts
    from bio_insights_fixtures import source as processed_source
    import numpy as np
    payload=fixture(tmp_path);payload['config'].update(figure_type='heatmap',processed_source_id='p1',top_n=2,
        expression_groups=[dict(label='A',observation_keys=[dict(processed_version_id='p1',barcode='b0')]),
                           dict(label='B',observation_keys=[dict(processed_version_id='p1',barcode='b1')])])
    processed=processed_source(tmp_path,[[1,3,0],[3,1,0]],ids=['G1','G2','G3'])
    processed['metadata'].update(namespace='Ensembl',reference_version='fixture');payload['sources'].append(processed)
    output=tmp_path/'out';output.mkdir();writer=Writer(output);run_figure(payload,writer)
    validate_artifacts(writer.artifacts,output)
    data=json.loads((output/'plot_data.json').read_text())
    values={(r['feature_id'],r['group']):r['mean_log1p'] for r in data['rows']}
    assert values[('G1','A')]==pytest.approx(np.log1p(2500))
    assert values[('G1','B')]==pytest.approx(np.log1p(7500))


@pytest.mark.parametrize('marker',['NA','NOT_MEASURED'])
def test_external_heatmap_missing_q_sorts_last_and_volcano_keeps_null(tmp_path,marker):
    from app.adapters.bio_insights_engine.figures import run_figure
    from app.adapters.bio_engine.manifest import Writer
    from bio_insights_fixtures import source as processed_source
    payload=fixture(tmp_path);source=payload['sources'][0]
    source['metadata'].update(provenance='external_result',plan_config={'kind':'result_import','na_values':['',marker]})
    raw=('row_key\tfeature_id\tcontrast_id\teffect_value\toriginal_q\n1\tG1\tc\t2\t'+marker+'\n2\tG2\tc\t2\t0\n3\tG3\tc\t2\t0.02\n').encode()
    source['members']['comparison_results']=member(tmp_path,'comparison_results','tsv',raw)
    payload['config'].update(formats=['png'],figure_type='heatmap',processed_source_id='p1',top_n=2,expression_groups=[dict(label='A',observation_keys=[dict(processed_version_id='p1',barcode='b0')])])
    processed=processed_source(tmp_path,[[1,3,2],[3,1,2]],ids=['G1','G2','G3']);processed['metadata'].update(namespace='Ensembl',reference_version='fixture');payload['sources'].append(processed)
    output=tmp_path/'heat';output.mkdir();run_figure(payload,Writer(output))
    data=json.loads((output/'plot_data.json').read_text())
    assert [row['feature_id'] for row in data['rows']]==['G2','G3']
    payload['config'].update(figure_type='volcano')
    output=tmp_path/'volcano';output.mkdir();run_figure(payload,Writer(output))
    data=json.loads((output/'plot_data.json').read_text())
    assert data['rows'][0]['q_value'] is None and data['rows'][1]['q_value']==0
    assert source['members']['comparison_results']['sha256']==hashlib.sha256(raw).hexdigest()

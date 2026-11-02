import hashlib
import json
from pathlib import Path
import numpy as np
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():yield None


def comparison_payload(tmp_path,monkeypatch,assay='proteomics',technical=False,scale_kind=None):
    from app.adapters.bio_engine import tabular_assays as engine
    from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3
    monkeypatch.setattr(engine,'_figure',lambda *args:None)
    samples=['B0','B1','B2','B3','A0','A1','A2','A3']
    files=[]
    for role,body in [('quantitative_matrix','feature_id,'+','.join(samples)+'\nf1,6,8,9,13,1,2,4,5\nf2,10,11,NA,15,1,3,5,7\nf3,1,1,1,1,1,1,1,1\n'),
                      ('sample_metadata','sample_id,condition,biological_unit_id,pair_id,sample_role\n'+''.join(f'{s},{s[0]},{"" if technical else s},pair{s[1]},{"technical" if technical else "biological"}\n' for s in samples))]:
        if assay=='bulk_rna_counts':body=body.replace('NA','12')
        path=tmp_path/(role+'.csv');path.write_text(body,encoding='utf-8')
        files.append(dict(id=role,role=role,path=str(path),filename=path.name,size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    cfg=BioImportRequestV3(workflow_version='bio_import_v3',file_ids=[f['id'] for f in files],name='sample test',assay=assay,expected_dataset_revision=0,
        tables=[dict(file_id=f['id'],role=f['role'],format='csv') for f in files],feature_id_column='feature_id',sample_columns=samples,
        scale=dict(kind=scale_kind or ('raw_counts' if assay=='bulk_rna_counts' else 'intensity'),unit='AU',upstream_method='measured',namespace='protein_label',reference_version='fixed')).model_dump()
    rawdir=tmp_path/'raw';rawdir.mkdir();raw=engine.import_tabular(dict(config=cfg,files=files,output_directory=str(rawdir)))
    raw=dict(manifest=raw['manifest'],members={m['key']:m for m in raw['outputs']})
    processed=tmp_path/'processed';processed.mkdir()
    result=engine.run_tabular(dict(raw=raw,config={},identity={'code_digest':'a'*64},mode='compute',output_directory=str(processed)))
    members={m['key']:m for m in result['outputs']}
    observations=[{**r,'processed_version_id':'p','retained':r['kept']=='True'} for r in engine._rows(members['samples'])]
    source=dict(source_kind='bio_processed_dataset_version',source_id='p',sha256='d'*64,role='processed',project_id='project',locator={'kind':'object'},raw=raw,members=members,
        metadata=dict(canonical_dataset_id='raw-p',observation_level='sample',assay=assay,namespace='protein_label',reference_version='fixed',species_taxon_id=None,
            feature_ids=['f1','f2','f3'],retained_feature_ids=['f1','f2','f3'],layers=result['manifest']['layers'],manifest=result['manifest'],observations=observations,scale=cfg['scale']))
    config=dict(kind='comparison',schema_version=2,mode='continuous',design='independent',method='welch_t',analysis_layer='analysis',
        contrasts=[dict(contrast_id='B_A',name='B/A',groups=[dict(label=g,sample_keys=[dict(processed_version_id='p',sample_id=s) for s in samples if s[0]==g]) for g in ('B','A')])],
        family_contrast_ids=['B_A'],namespace='protein_label',reference_version='fixed',species_taxon_id=None,inference_unit='biological',
        independence_confirmed=True,independence_basis='independent samples',design_basis='prespecified',inference_goal='inference',data_driven_grouping=False)
    return dict(schema_version=1,kind='bio_comparison',identity=dict(plan_version_id='plan'),config=config,sources=[source])


@pytest.mark.parametrize('scale',['intensity','log10'])
def test_explicit_technical_replicate_qc_preserves_all_features_missing_and_cv_applicability(tmp_path,monkeypatch,scale):
    import csv,io,math
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_process import validate_result
    from app.adapters.bio_engine.tabular_assays import _rows
    from app.core.exceptions import StorageError
    from test_bio_tabular_validation import rehash_result
    p=comparison_payload(tmp_path,monkeypatch,technical=True,scale_kind=scale)
    p['config'].update(inference_unit='technical',inference_goal='exploratory',technical_exploration_confirmed=True,independence_confirmed=False)
    out=tmp_path/'comparison';out.mkdir();p['output_directory']=str(out);result=run(p)
    member=next(m for m in result['outputs'] if m['key']=='technical_replicate_qc');rows=_rows(member)
    assert len(rows)==6 and {r['feature_id'] for r in rows}=={'f1','f2','f3'}
    assert len({r['row_key'] for r in rows})==len(rows)
    selected=next(r for r in rows if r['feature_id']=='f2' and r['group']=='B')
    assert selected['n_total']=='4' and selected['n_measured']=='3' and selected['n_missing']=='1' and selected['biological_n']=='0'
    assert float(selected['mean'])==12. and np.isclose(float(selected['sample_sd']),math.sqrt(7.))
    if scale=='intensity':assert np.isclose(float(selected['coefficient_of_variation']),math.sqrt(7.)/12.) and selected['cv_reason']==''
    else:assert selected['coefficient_of_variation']=='' and selected['cv_reason']=='nonlinear_scale'
    validate_result(result,out,p)
    selected['n_measured']='4';stream=io.StringIO();writer=csv.DictWriter(stream,list(rows[0]),delimiter='\t',lineterminator='\n');writer.writeheader();writer.writerows(rows)
    rehash_result(result,'technical_replicate_qc',stream.getvalue())
    with pytest.raises(StorageError):validate_result(result,out,p)


def test_continuous_complete_cases_direction_and_full_na_rows(tmp_path,monkeypatch):
    from app.adapters.bio_insights_engine.quantitative import run_quantitative
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_engine.tabular_assays import _rows
    from scipy.stats import ttest_ind
    p=comparison_payload(tmp_path,monkeypatch);out=tmp_path/'comparison';out.mkdir();writer=Writer(out)
    result=run_quantitative(p,writer);rows=_rows(next(m for m in writer.artifacts if m['key']=='comparison_results'))
    assert [r['feature_id'] for r in rows]==['f1','f2','f3']
    first=rows[0];expected=ttest_ind([6,8,9,13],[1,2,4,5],equal_var=False)
    assert float(first['effect_value'])==6.0 and np.isclose(float(first['p_value']),expected.pvalue)
    assert rows[1]['n_numerator']=='3' and rows[1]['n_denominator']=='4'
    assert rows[2]['p_value']=='' and rows[2]['reason']=='comparison_constant'
    assert result['inference_scope']=='sample_inference' and 'spots_numerator' not in first


def test_paired_complete_pairs_keep_direction_and_do_not_impute(tmp_path,monkeypatch):
    from app.adapters.bio_insights_engine.quantitative import run_quantitative
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_engine.tabular_assays import _rows
    from scipy.stats import ttest_rel
    p=comparison_payload(tmp_path,monkeypatch);p['config'].update(design='paired',method='paired_t')
    out=tmp_path/'comparison';out.mkdir();writer=Writer(out);run_quantitative(p,writer)
    rows=_rows(next(m for m in writer.artifacts if m['key']=='comparison_results'))
    assert rows[1]['n_pairs']=='3'
    assert np.isclose(float(rows[1]['p_value']),ttest_rel([10,11,15],[1,3,7]).pvalue)
    assert float(rows[1]['effect_value'])>0


def test_predeclared_bh_known_vector():
    from app.adapters.bio_insights_engine.comparison import adjust_families
    rows=[dict(tested=True,contrast_id='c',p_value=p) for p in [.01,.04,.03]]
    adjust_families(rows,['c'])
    assert np.allclose([r['q_global_family'] for r in rows],[.03,.04,.04])


def test_transport_retains_tabular_scale_and_masks(tmp_path,monkeypatch):
    from app.adapters.bio_insights_engine.transport import project_transport_payload
    p=comparison_payload(tmp_path,monkeypatch);transport=project_transport_payload(p)
    assert transport['sources'][0]['raw']['manifest']['schema_version']==3
    assert transport['sources'][0]['metadata']['layers']==p['sources'][0]['metadata']['layers']


def test_v2_pipeline_parent_binds_frozen_method_and_complete_tables(tmp_path,monkeypatch):
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_process import validate_result
    from app.core.exceptions import StorageError
    p=comparison_payload(tmp_path,monkeypatch);out=tmp_path/'comparison';out.mkdir();p['output_directory']=str(out)
    result=run(p);validate_result(result,out,p)
    p['config']['method']='mann_whitney_u'
    with pytest.raises(StorageError):validate_result(result,out,p)


@pytest.mark.parametrize('field,change,accepted',[
    ('p_value','ulp',True),('q_global_family','ulp',True),('effect_value','ulp',True),
    ('p_value','0.5',False),('n_numerator','5',False),('effect_value','-6.0',False),
    ('q_global_family','NA',False),('p_value','0',False),
])
def test_continuous_parent_distinguishes_float_roundoff_from_changed_science(tmp_path,monkeypatch,field,change,accepted):
    import csv,io
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_process import validate_result
    from app.core.exceptions import StorageError
    from test_bio_tabular_validation import rehash_result
    p=comparison_payload(tmp_path,monkeypatch);out=tmp_path/'result';out.mkdir();p['output_directory']=str(out);result=run(p)
    leaf=next(m for m in result['outputs'] if m['key']=='comparison_results')
    with Path(leaf['path']).open(encoding='utf-8',newline='') as stream:
        reader=csv.DictReader(stream,delimiter='\t');fields=reader.fieldnames;rows=list(reader)
    rows[0][field]=str(np.nextafter(float(rows[0][field]),np.inf)) if change=='ulp' else change
    stream=io.StringIO();writer=csv.DictWriter(stream,fields,delimiter='\t',lineterminator='\n');writer.writeheader();writer.writerows(rows)
    rehash_result(result,'comparison_results',stream.getvalue())
    if accepted:validate_result(result,out,p)
    else:
        with pytest.raises(StorageError):validate_result(result,out,p)


@pytest.mark.parametrize('field,expected,actual,accepted',[
    ('p_value',1.,'1.0000000000001',False),('q_global_family',1.,'1.0000000000001',False),
    ('p_value',1e-250,'2e-250',False),('p_value',1e-250,'1.0000000000000002e-250',True),
    ('effect_value',0.,'1e-300',False),('effect_value',None,'0',False),('statistic',1.,'1.01',False),
])
def test_continuous_float_boundary_preserves_probabilities_tiny_p_zero_and_na(tmp_path,field,expected,actual,accepted):
    from app.adapters.bio_quantitative_validation import _ContinuousReconciliationWriter
    path=tmp_path/'table.tsv';path.write_bytes((field+'\n'+actual+'\n').encode())
    writer=_ContinuousReconciliationWriter({'comparison_results':{'path':str(path)}})
    if accepted:writer.table('comparison_results',[{field:expected}])
    else:
        with pytest.raises(ValueError):writer.table('comparison_results',[{field:expected}])


def test_sample_figure_data_keeps_every_sample_missing_and_unit(tmp_path,monkeypatch):
    from app.domain.bio_insights.contracts import FigureConfig
    from app.adapters.bio_insights_engine.quantitative_figures import sample_plot_data
    p=comparison_payload(tmp_path,monkeypatch)
    cfg=FigureConfig(kind='figure',figure_type='distribution',result_source_id='result',processed_source_id='p',
        sample_groups=p['config']['contrasts'][0]['groups'],feature_ids=['f2'],analysis_layer='analysis')
    data=sample_plot_data(p['sources'][0],cfg,['f2'])
    assert len(data['rows'])==8 and sum(r['value'] is None for r in data['rows'])==1
    assert data['groups'][0]['measured_n']==3 and data['groups'][0]['missing_n']==1
    assert data['layer']['unit']=='AU' and data['z_score'] is False
    assert data['rows'][0]['sample_id']=='B0' and data['rows'][0]['value']==10


def test_parent_sample_plot_rejects_changed_values_and_missing_counts(tmp_path,monkeypatch):
    from app.domain.bio_insights.contracts import FigureConfig
    from app.adapters.bio_insights_engine.quantitative_figures import sample_plot_data,validate_sample_plot
    p=comparison_payload(tmp_path,monkeypatch)
    cfg=FigureConfig(kind='figure',figure_type='distribution',result_source_id='r',processed_source_id='p',
        sample_groups=p['config']['contrasts'][0]['groups'],feature_ids=['f2'])
    result_source=dict(source_id='r',metadata={})
    payload=dict(config=cfg.model_dump(),sources=[*p['sources'],result_source])
    data=sample_plot_data(p['sources'][0],cfg,['f2']);validate_sample_plot(payload,data)
    data['rows'][0]['value']=100
    with pytest.raises(ValueError,match='sample_plot_data_mismatch'):validate_sample_plot(payload,data)


def test_unknown_species_protein_labels_allow_exact_candidates_not_gene_mapping(tmp_path,monkeypatch):
    from app.adapters.bio_insights_engine.pipeline import run
    p=comparison_payload(tmp_path,monkeypatch);out=tmp_path/'comparison';out.mkdir();p['output_directory']=str(out);result=run(p)
    source=dict(source_kind='bio_insight_result_version',source_id='r',sha256='e'*64,members={m['key']:m for m in result['outputs']},
        metadata=dict(species_taxon_id=None,namespace='protein_label',reference_version='fixed',canonical_dataset_ids=['raw-p'],kind='comparison',
            provenance='system_computed',inference_scope='sample_inference',upstream_inference_scopes=['sample_inference']))
    dest=tmp_path/'candidate';dest.mkdir()
    candidate=run(dict(schema_version=1,kind='bio_candidate',identity={'source_digest':'f'*64},sources=[source],output_directory=str(dest),config=dict(kind='candidate',result_source_ids=['r'],
        source_contrasts={'r':'B_A'},primary_result_source_id='r',steps=[dict(operation='threshold',source_ids=['r'],q_column='q_within_contrast',q_threshold=1.,minimum_absolute_effect=0.)])))
    assert candidate['summary']['candidate_count']==2
    assert candidate['methods']['upstream_inference_scopes']==['sample_inference']


def test_sample_result_with_explicit_gene_identity_can_feed_existing_enrichment_reader(tmp_path,monkeypatch):
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_engine.evidence import load_result
    p=comparison_payload(tmp_path,monkeypatch)
    p['config'].update(species_taxon_id=9606,namespace='Ensembl')
    p['sources'][0]['metadata'].update(species_taxon_id=9606,namespace='Ensembl')
    out=tmp_path/'result';out.mkdir();p['output_directory']=str(out);result=run(p)
    source=dict(source_kind='bio_insight_result_version',metadata=dict(plan_config=p['config'],inference_scope='sample_inference'),members={m['key']:m for m in result['outputs']})
    assert len(load_result(source)['rows'])==3


@pytest.mark.parametrize('member,field,value',[
    ('model_sample_metadata','batch','FORGED'),('model_counts','feature_id','FORGED'),
    ('size_factors','factor','99'),('comparison_results','n_numerator','99'),
    ('comparison_results','q_global_family','0.01'),('model_convergence','_LFC_converged','False'),
    ('model_diagnostics','rank',1),('model_diagnostics','parameters',{}),
])
def test_counts_parent_rejects_rehashed_model_contract_tampering(tmp_path,monkeypatch,member,field,value):
    """Algebraic validation fixture only; actual model accuracy is the independent R test."""
    import csv,io
    from app.adapters.bio_insights_engine import counts_model
    from app.adapters.bio_insights_engine.comparison import _identity
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_process import validate_result
    from app.core.exceptions import StorageError
    from test_bio_tabular_validation import rehash_result
    def fixture_fit(values,features,contrast,groups,group_keys,by_key,config):
        order=[(k,i,label) for side in (1,0) for k,i in zip(group_keys[side],groups[side]) for label in [contrast.groups[side].label]]
        matrix=values[[i for _,i,_ in order]];tested=matrix.sum(0)>=config.minimum_total_counts
        logs=np.log(matrix[:,tested]);sf=np.exp(np.median(logs-logs.mean(0),axis=1));ids=['s'+_identity(k)[:24] for k,_,_ in order];cid=contrast.contrast_id
        rows=[];convergence=[]
        for j,f in enumerate(features):
            yes=bool(tested[j]);rows.append(dict(effect_name='effect_log2fc',effect_value=0. if yes else None,effect_unit='log2 count fold change',effect_reason=None if yes else 'not_computable',base_mean=float((matrix[:,j]/sf).mean()) if yes else None,lfc_se=1. if yes else None,statistic=0. if yes else None,wald_statistic=0. if yes else None,p_value=1. if yes else None,original_method_adjustment=1. if yes else None,tested=yes,test_status='tested' if yes else 'excluded',reason=None if yes else 'minimum_total_counts',p_value_underflow=False))
            convergence.append(dict(contrast_id=cid,feature_id=f,tested=yes,_LFC_converged=True if yes else None,_genewise_converged=True if yes else None,_MAP_converged=True if yes else None))
        model=dict(diagnostics=dict(contrast_id=cid,formula='~ condition',rank=2,residual_degrees_freedom=len(order)-2,parameters=counts_model.frozen_parameters(config),design_columns=['Intercept','condition[T.B]'],design_matrix=[[1.,float(label=='B')] for _,_,label in order],sample_unit_ids=ids,warnings=[],fit_type_requested='parametric',fit_type_effective='parametric'),
            model_sample_metadata=[dict(contrast_id=cid,unit_id=uid,processed_version_id=k[0],sample_id=k[1],condition=label,donor=by_key[k]['pair_id'],batch='',biological_unit_id=k[1]) for uid,(k,_,label) in zip(ids,order)],model_convergence=convergence,
            size_factors=[dict(contrast_id=cid,unit_id=uid,processed_version_id=k[0],sample_id=k[1],factor=float(factor),method='ratio') for uid,(k,_,_),factor in zip(ids,order,sf)],
            model_counts=[dict(contrast_id=cid,unit_id=uid,feature_id=f,counts=int(matrix[i,j])) for i,uid in enumerate(ids) for j,f in enumerate(features)],
            model_normalized_counts=[dict(contrast_id=cid,unit_id=uid,feature_id=f,normalized_counts=float(matrix[i,j]/sf[i])) for i,uid in enumerate(ids) for j,f in enumerate(features)])
        return rows,model
    monkeypatch.setattr(counts_model,'fit_counts',fixture_fit)
    p=comparison_payload(tmp_path,monkeypatch,'bulk_rna_counts');p['config'].update(mode='bulk_counts',method='deseq2_wald',analysis_layer='raw_counts')
    out=tmp_path/'comparison';out.mkdir();p['output_directory']=str(out);result=run(p);validate_result(result,out,p)
    item=next(m for m in result['outputs'] if m['key']==member)
    if member=='model_diagnostics':
        data=json.loads(Path(item['path']).read_bytes());data[0][field]=value;body=json.dumps(data)
    else:
        with Path(item['path']).open(encoding='utf-8',newline='') as stream:
            reader=csv.DictReader(stream,delimiter='\t');fields=reader.fieldnames;data=list(reader)
        data[0][field]=value;stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=fields,delimiter='\t',lineterminator='\n');writer.writeheader();writer.writerows(data);body=stream.getvalue()
    rehash_result(result,member,body)
    with pytest.raises(StorageError):validate_result(result,out,p)

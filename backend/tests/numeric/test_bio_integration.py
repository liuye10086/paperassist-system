import pytest
from app.domain.bio_insights.integration_matching import match_samples
from app.adapters.bio_insights_engine.integration import correlate_pairs, classify_concordance

def sample(ds,obs,g,donor=None):
    return dict(dataset_version=ds,observation_id=obs,match_group=g,donor_id=donor,independent_unit_verified=bool(donor),relationship='same_sample',tissue='',time='',basis='fixture')

def test_matching_order_partial_and_duplicate_units():
    rows=[sample('a','a2','2','d2'),sample('b','b1','1','d1'),sample('a','a1','1','d1'),sample('b','b2','2','d2')]
    matches,audit=match_samples(rows,'a','b',['a1','a2','a3'],['b2','b1'],inference=True)
    assert [(x['left_observation_id'],x['right_observation_id']) for x in matches]==[('a1','b1'),('a2','b2')]
    assert any(r['observation_id']=='a3' and r['reason']=='unmapped_observation' for r in audit)
    rows[0]['donor_id']='d1';rows[3]['donor_id']='d1'
    assert match_samples(rows,'a','b',['a1','a2'],['b1','b2'],inference=True)[0]==[]

def test_bridge_oracle_and_na_family():
    data=[dict(pair_id='p1',values=[[1.,2.],[2.,4.],[3.,6.]],included=['1','2','3'],excluded=[]),dict(pair_id='p2',values=[[1.,2.],[1.,3.],[1.,4.]],included=['1','2','3'],excluded=[])]
    result=correlate_pairs(data,method='pearson',inference=False)
    assert result[0]['coefficient']==pytest.approx(1.,abs=1e-8,rel=1e-6)
    assert result[0]['p_value'] is None and result[0]['q_value'] is None and result[0]['independent_n'] is None
    assert result[1]['coefficient'] is None and result[1]['reason']=='correlation_constant'
    from app.adapters.bio_insights_engine.comparison import adjust_families
    family=[dict(contrast_id='c',tested=True,p_value=p) for p in [.01,.04,.03]]
    adjust_families(family,['c'])
    assert [r['q_global_family'] for r in family]==pytest.approx([.03,.04,.04],abs=1e-8,rel=1e-6)
    family.append(dict(contrast_id='c',tested=True,p_value=None))
    adjust_families(family,['c'])
    assert family[-1]['q_global_family'] is None

def test_concordance_states():
    assert classify_concordance(1.,-2.,.01,.01,alignment='reverse')=='support'
    assert classify_concordance(1.,-2.,.01,.01)=='conflict'
    assert classify_concordance(1.,2.,.2,.01)=='below_threshold'
    assert classify_concordance(None,2.,None,.01)=='unknown'
    assert classify_concordance(1.,2.,.01,.01,comparable=False)=='incomparable'


def test_native_pipeline_resources_parent_and_fixed_graphs(tmp_path):
    import json
    from pathlib import Path
    from app.adapters.bio_insights_engine.integration_probe import fixture_sources,fixture_config
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_insights_process import validate_result
    from app.domain.bio_insights.contracts import ResourceImportRequest,FigureConfig
    from app.domain.bio_insights.integration_contracts import SAMPLE_COLUMNS,OBJECT_COLUMNS
    sources=fixture_sources(tmp_path);raw=tmp_path/'raw';raw.mkdir();writer=Writer(raw)
    identity=dict(project_id='integration-fixture',task_id='task',plan_version_id='plan',source_digest='a'*64,engine_version='bio_insights_v1.0.0',code_digest='b'*64,environment_digest='c'*64,lock_sha256='d'*64)
    rows=[dict(dataset_version=sid,observation_id=prefix+str(i),donor_id='d'+str(i),tissue='fixed',time='fixed',match_group=str(i),relationship='same_sample',basis='synthetic exact match',independent_unit_verified=True) for sid,prefix in [('left','a'),('right','b')] for i in (1,2,3)]
    objects=[dict(source_dataset_version='left',source_id='g',source_namespace='symbol',source_species=9606,source_version='fixture1',target_dataset_version='right',target_id='g',target_namespace='symbol',target_species=9606,target_version='fixture1',relationship='same_feature',basis='fixture source labels',ambiguity='none',decision='include')]
    def execute(kind,config,inputs,name):
        dest=tmp_path/name;dest.mkdir();payload=dict(schema_version=1,kind=kind,config=config,sources=inputs,identity=identity,output_directory=str(dest));result=run(payload);validate_result(result,dest,payload);return result
    for name,kind,items,cols in [('sample','sample_correspondence',rows,SAMPLE_COLUMNS),('object','object_correspondence',objects,OBJECT_COLUMNS)]:
        member=writer.table(name,items,cols);s=dict(source_kind='original_file',source_id=name+'-file',project_id='integration-fixture',sha256=member['sha256'],role=kind,locator={'kind':'object'},metadata={},members={'original_file':member})
        cfg=ResourceImportRequest(kind=kind,title=name,species_taxon_id=9606,namespace='symbol',release='fixture1',source=dict(institution='synthetic',name=name,description='test'),usage=dict(basis='test',redistribution_allowed=True,scope='project'),files=[dict(file_id=name+'-file',sha256=member['sha256'],role=kind,format='tsv')])
        r=execute('bio_resource_import',cfg.model_dump(mode='json'),[s],name+'-import')
        sources.append(dict(source_kind='bio_resource_version',source_id=name,project_id='integration-fixture',sha256='c'*64,role='sample_mapping' if name=='sample' else 'object_mapping',locator={'kind':'object'},metadata={'kind':kind},members={m['key']:m for m in r['outputs']}))
    cfg=fixture_config();r=execute('bio_integration',cfg.model_dump(mode='json'),sources,'integration')
    data=json.loads(next(Path(m['path']).read_bytes() for m in r['outputs'] if m['key']=='integration_data'))
    assert data['correlations'][0]['coefficient']==pytest.approx(1.,abs=1e-8,rel=1e-6)
    assert data['correlations'][0]['independent_n']==3
    assert [c['status'] for c in data['concordances']]==['support','conflict','below_threshold','unknown']
    assert len(data['dependency_groups']['groups'])==1
    assert len(data['nodes'])==19 and len(data['edges'])==28
    assert any(e['locator'].get('basis')=='fixture source labels' for e in data['edges'])
    upstream=dict(source_kind='bio_insight_result_version',source_id='integrated',project_id='integration-fixture',sha256='d'*64,role='result',locator={'kind':'object'},metadata=dict(kind='integration',inference_scope='derived',provenance='system_computed'),members={m['key']:m for m in r['outputs']})
    for name in ('network','flow'):
        fc=FigureConfig(result_source_id='integrated',figure_type='integration_'+name,formats=['png'])
        figure=execute('bio_insight_figure',fc.model_dump(mode='json'),[upstream],name)
        plot=json.loads(next(Path(m['path']).read_bytes() for m in figure['outputs'] if m['key']=='plot_data'))
        assert plot['nodes']==data['nodes'] and plot['edges']==data['edges'] and plot['analysis_recomputed'] is False
        assert all(not e['directed'] for e in plot['edges'] if e['edge_type']=='correlation')
    from app.domain.bio_insights.integration_matching import object_decision
    pair=cfg.pairs[0];meta=sources[0]['metadata'];duplicate={**objects[0],'target_id':'other','ambiguity':'one_to_many'}
    assert object_decision(objects+[duplicate],pair,meta,meta,inference=True)[1]=='ambiguous_mapping_inference_excluded'
    foreign={**objects[0],'target_species':10090}
    assert object_decision([foreign],pair,meta,meta,inference=False)[1]=='different_species_incomparable'

def test_descriptive_spearman_never_enters_inference(monkeypatch):
    from app.adapters.bio_insights_engine import integration
    original=integration.compute_correlation;calls=[]
    def observed(rows,**kwargs):calls.append(kwargs['mode']);return original(rows,**kwargs)
    monkeypatch.setattr(integration,'compute_correlation',observed)
    entry=dict(pair_id='p',values=[[1.,2.],[2.,4.],[3.,6.]],included=['1','2','3'],excluded=[])
    descriptive=correlate_pairs([entry],method='spearman',inference=False)
    assert calls==['matrix'] and descriptive[0]['p_value'] is None
    inferential=correlate_pairs([entry],method='spearman',inference=True)
    assert inferential[0]['p_value']==pytest.approx(2/6,abs=1e-8,rel=1e-6)
    assert inferential[0]['confidence_interval']['reason']=='spearman_interval_not_implemented'


def test_saved_pathway_graph_keeps_ora_hits_and_gsea_nonleading_members(tmp_path):
    import json
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_insights_engine.inputs import document,iter_table
    from app.adapters.bio_insights_engine.integration import run_integration
    from app.domain.bio_insights.contracts import FigureConfig
    from app.domain.bio_insights.integration_graph import integration_plot_data
    sources=[]
    for sid,kind,extra in [('ora','ora',dict(hits=['ORA-hit'],q_value=.01)),('gsea','gsea_prerank',dict(leading_edge=['GSEA-leading'],hit_indices=[0,2],nes=1.5,fdr_q_value=.01))]:
        root=tmp_path/sid;root.mkdir();w=Writer(root)
        w.table('enrichment_results',[dict(row_key=sid+'-term-row',contrast_id='c',term_id='term',**extra)])
        w.json('methods',{'resources':[{'resource_id':'fixed-collection'}]})
        if kind=='gsea_prerank':
            # Physical row order differs from rank; hit indices address the saved rank column.
            w.table('gsea_ranking',[dict(rank=rank,feature_id=fid,statistic=3-rank,source_feature_id='original-'+fid,source_row_key='upstream-'+fid) for rank,fid in [(2,'GSEA-tail'),(1,'not-a-member'),(0,'GSEA-leading')]])
        sources.append(dict(source_id=sid,source_kind='bio_insight_result_version',sha256='a'*64,metadata=dict(kind=kind,species_taxon_id=9606,namespace='symbol',reference_version='fixed',summary_json={'eligible_term_family_complete':True}),members={m['key']:m for m in w.artifacts}))
    root=tmp_path/'integration';root.mkdir();w=Writer(root)
    config=dict(mapping_confirmed=True,concordances=[dict(concordance_id='pathway',left_result_source_id='ora',right_result_source_id='gsea',left_contrast_id='c',right_contrast_id='c',object_ids=['term'],direction_alignment='same',comparison_basis='saved pathway membership',q_column='q_value')])
    run_integration(dict(config=config,sources=sources,identity={'plan_version_id':'plan'}),w)
    members={m['key']:m for m in w.artifacts};data=document(members['integration_data'])
    nodes={n['node_id']:n for n in data['nodes']}
    expected={'object:ora:ORA-hit','object:gsea:GSEA-leading','object:gsea:GSEA-tail'}
    assert expected<=nodes.keys()
    assert 'object:gsea:not-a-member' not in nodes
    edges={e['target_node_id']:e for e in data['edges'] if e['edge_type']=='saved_pathway_member'}
    assert set(edges)==expected
    ora_locator=dict(source_id='ora',member_key='enrichment_results',row_key='ora-term-row',field='hits',element_index=0,membership_semantics='ora_foreground_hit')
    assert edges['object:ora:ORA-hit']['locator']==ora_locator
    assert nodes['object:ora:ORA-hit']['locator']==ora_locator
    tail_locator=dict(source_id='gsea',member_key='enrichment_results',row_key='gsea-term-row',field='hit_indices',element_index=1,membership_semantics='gsea_ranked_set_member',is_leading_edge=False,ranking_locator=dict(source_id='gsea',member_key='gsea_ranking',row_number=2,rank=2,feature_id='GSEA-tail',source_feature_id='original-GSEA-tail',source_row_key='upstream-GSEA-tail'))
    assert edges['object:gsea:GSEA-tail']['locator']==tail_locator
    assert nodes['object:gsea:GSEA-tail']['locator']==tail_locator
    assert edges['object:gsea:GSEA-leading']['locator']['is_leading_edge'] is True
    assert data['concordances'][0]['status']=='incomparable'
    assert data['concordances'][0]['reason']=='ordinary_ORA_unsigned'
    exported_nodes={r['node_id'] for _,r in iter_table(members['integration_nodes'],format='tsv')}
    exported_edges={r['target_node_id']:json.loads(r['locator']) for _,r in iter_table(members['integration_edges'],format='tsv') if r['edge_type']=='saved_pathway_member'}
    assert expected<=exported_nodes and exported_edges['object:gsea:GSEA-tail']==tail_locator
    source=dict(metadata={'kind':'integration'},members=members)
    plot=integration_plot_data(source,FigureConfig(result_source_id='integrated',figure_type='integration_network',top_n=2))
    assert plot['nodes']==data['nodes'] and plot['edges']==data['edges']
    assert len(plot['display_nodes'])==2 and len(plot['nodes'])>2

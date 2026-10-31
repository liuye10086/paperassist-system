import importlib.util
import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def contracts():
    assert importlib.util.find_spec('app.domain.bio_insights'), 'bio insight contracts missing'
    return __import__('app.domain.bio_insights.contracts', fromlist=['InsightPlanRequest'])


def test_sources_are_typed_frozen_and_reject_paths():
    c = contracts()
    data = dict(source_kind='original_file', source_id='f', project_id='p', sha256='a'*64)
    source = c.FrozenInsightSource.model_validate(data)
    with pytest.raises(ValidationError):
        source.sha256 = 'b'*64
    for patch in ({'source_kind':'bio_figure_version'}, {'sha256':'A'*64}, {'path':'/secret'},
                  {'locator':{'kind':'row','row_key':{}}}):
        with pytest.raises(ValidationError):
            c.FrozenInsightSource.model_validate({**data, **patch})


def test_plan_discriminator_bounds_and_external_top_table_q_recalculation():
    c = contracts()
    config = dict(kind='result_import', file_source_id='f', parse_version_id='parse',
                  species_taxon_id=9606,namespace='Ensembl',reference_version='declared-v1',
                  columns={'feature_id':'Gene','p_value':'P'}, contrast_id='c',numerator='A',denominator='B',
                  original_method='external tool',original_correction_scope='unknown')
    payload = dict(name='import',kind='result_import',decision='draft',expected_revision=0,
                   sources=[{'source_kind':'original_file','source_id':'f','sha256':'a'*64}],config=config)
    assert c.InsightPlanRequest.model_validate(payload).config.complete_tested_universe is False
    for patch in ({'kind':'comparison'}, {'config':{**config,'recompute_q':True}},
                  {'config':{**config,'columns':{'feature_id':'Gene','unknown':'X'}}}):
        with pytest.raises(ValidationError):
            c.InsightPlanRequest.model_validate({**payload,**patch})


def test_resource_has_existing_file_identity_and_usage_metadata():
    c = contracts()
    payload = dict(kind='gene_sets',title='GO',species_taxon_id=9606,namespace='ensembl_gene',release='2026-01',
                   source={'institution':'GO','name':'GO basic','description':'official release','url':'https://geneontology.org'},
                   usage={'basis':'public resource','redistribution_allowed':False,'scope':'project'},
                   files=[{'file_id':'f','sha256':'a'*64,'role':'gmt','format':'gmt'}])
    resource = c.ResourceImportRequest.model_validate(payload)
    assert resource.usage.redistribution_allowed is False
    for patch in ({'propagation_relations':['has_part']},{'files':[{'path':'/tmp/file','role':'gmt','format':'gmt'}]},
                  {'species_taxon_id':'9606'}):
        with pytest.raises(ValidationError):
            c.ResourceImportRequest.model_validate({**payload,**patch})


def test_task_input_identity_checks_digest_kind_workflow_and_source_digest():
    contracts()
    t = __import__('app.domain.bio_insights.task_contracts',fromlist=['input_version'])
    from app.domain.bioinformatics.contracts import digest
    snapshot = dict(kind='bio_comparison',schema_version=1,workflow_version='bio_comparison_v1',project_id='p',
                    plan_version_id='v',run_id='r',source_digest='a'*64,output_language='zh-CN',
                    real_model_calls=False,real_network_calls=False)
    task = dict(task_type='bio_comparison',project_id='p',workflow_version='bio_comparison_v1',
                input_snapshot=snapshot,input_digest=digest(snapshot))
    result = t.input_version(task)
    assert result['source_sha256']==task['input_digest']
    assert result['source_digest']=='a'*64
    for patch in ({'input_digest':'b'*64},{'workflow_version':'bio_comparison_v2'},{'task_type':'bio_result_import'}):
        with pytest.raises(ValueError):
            t.input_version({**task,**patch})


def test_config_references_are_real_selected_sources_with_correct_kind_and_role():
    c=contracts()
    payload=dict(name='ORA',kind='ora',expected_revision=0,sources=[
        {'source_kind':'bio_insight_result_version','source_id':'r','role':'result','sha256':'a'*64},
        {'source_kind':'bio_resource_version','source_id':'g','role':'gene_sets','sha256':'b'*64}],
        config={'kind':'ora','result_source_ids':['r'],'resource_source_ids':['g'],'contrast_ids':['c'],'output_language':'en'})
    assert c.InsightPlanRequest.model_validate(payload).config.output_language=='en'
    for patch in ({'resource_source_ids':['missing']},{'result_source_ids':['g']},{'resource_source_ids':['g','g']}):
        with pytest.raises(ValidationError):
            c.InsightPlanRequest.model_validate({**payload,'config':{**payload['config'],**patch}})


def test_resource_gzip_is_bounded_and_tabular_mappings_are_explicit():
    c=contracts()
    c.ResourceFile.model_validate(dict(file_id='f',sha256='a'*64,role='gaf',format='gaf.gz',max_uncompressed_bytes=1000))
    for data in (dict(role='term_gene',format='tsv'),dict(role='gmt',format='zip'),
                 dict(role='gaf',format='gaf.gz',expected_uncompressed_size_bytes=2000,max_uncompressed_bytes=1000),
                 dict(role='id_mapping',format='csv',columns={'source_id':'old'})):
        with pytest.raises(ValidationError):
            c.ResourceFile.model_validate(dict(file_id='f',sha256='a'*64,**data))


def test_heatmap_requires_real_expression_and_venn_requires_multiple_fixed_sets():
    c=contracts()
    with pytest.raises(ValidationError):
        c.FigureConfig.model_validate(dict(result_source_id='r',figure_type='heatmap'))
    with pytest.raises(ValidationError):
        c.FigureConfig.model_validate(dict(result_source_id='r',figure_type='venn'))
    c.FigureConfig.model_validate(dict(result_source_id='r',figure_type='heatmap',processed_source_id='p',
        expression_groups=[{'label':'A','observation_keys':[{'processed_version_id':'p','barcode':'b'}]}]))
    c.FigureConfig.model_validate(dict(result_source_id='r',figure_type='venn',result_source_ids=['r','r2'],
        selected_sets=[{'result_source_id':'r','contrast_id':'c','label':'A'},
                       {'result_source_id':'r2','contrast_id':'c','label':'B'}],intersection_mode='all'))


def test_local_resource_does_not_need_fabricated_url_but_source_explanation_is_required():
    c=contracts()
    source=dict(institution='project laboratory',name='existing feature annotations',description='provided annotation table')
    assert c.ResourceSource.model_validate(source).url is None
    for patch in ({'url':'file:///secret'},{'url':'javascript:run()'},{'description':''}):
        with pytest.raises(ValidationError):
            c.ResourceSource.model_validate({**source,**patch})


@pytest.mark.parametrize('kind',['bio_resource_import','bio_comparison','bio_result_import','bio_enrichment','bio_candidate','bio_insight_figure'])
def test_all_six_task_snapshots_require_explicit_sql_identity(kind):
    contracts()
    t=__import__('app.domain.bio_insights.task_contracts',fromlist=['input_version'])
    from app.domain.bioinformatics.contracts import digest
    snapshot=dict(kind=kind,schema_version=1,workflow_version=kind+'_v1',project_id='p',source_digest='a'*64,
                  output_language='en',real_model_calls=False,real_network_calls=False)
    if kind=='bio_resource_import':snapshot['resource_version_id']='resource'
    else:snapshot.update(plan_version_id='plan',run_id='run')
    def task(value):
        return dict(task_type=kind,workflow_version=kind+'_v1',project_id='p',input_snapshot=value,input_digest=digest(value))
    assert t.input_version(task(snapshot))['kind']==kind
    for missing in ('schema_version','output_language'):
        incomplete={key:value for key,value in snapshot.items() if key!=missing}
        with pytest.raises(ValueError):t.input_version(task(incomplete))


def test_mapping_namespaces_are_explicit_and_comparisons_are_bounded_to_ten():
    c=contracts()
    common=dict(kind='id_mapping',title='IDs',species_taxon_id=9606,namespace='Ensembl',release='v1',
                source={'institution':'lab','name':'mapping','description':'provided mapping'},
                usage={'basis':'project permission','redistribution_allowed':False,'scope':'project'},
                files=[{'file_id':'f','sha256':'a'*64,'role':'id_mapping','format':'tsv','columns':{'source_id':'old','target_id':'new'}}])
    with pytest.raises(ValidationError):c.ResourceImportRequest.model_validate(common)
    value=c.ResourceImportRequest.model_validate({**common,'mapping_source_namespace':'Ensembl','mapping_target_namespace':'UniProtKB'})
    assert value.mapping_target_namespace=='UniProtKB'
    contrast={'name':'A/B','numerator':{'label':'A'},'denominator':{'label':'B'}}
    config=dict(mode='spot_exploratory',species_taxon_id=9606,namespace='Ensembl',reference_version='v1',
                contrasts=[{**contrast,'contrast_id':str(i)} for i in range(11)],family_contrast_ids=[str(i) for i in range(11)])
    with pytest.raises(ValidationError):c.ComparisonConfig.model_validate(config)


def test_external_import_requires_explicit_taxon_namespace_and_reference_version():
    c=contracts()
    data=dict(file_source_id='f',parse_version_id='parse',columns={'feature_id':'id'},contrast_id='c',numerator='A',denominator='B',
              original_method='external',original_correction_scope='unknown')
    with pytest.raises(ValidationError):c.ResultImportConfig.model_validate(data)


def test_candidates_freeze_one_contrast_per_source_and_only_known_weight_items():
    c=contracts()
    data=dict(result_source_ids=['r'],primary_result_source_id='r',steps=[{'operation':'union'}])
    with pytest.raises(ValidationError):c.CandidateConfig.model_validate(data)
    c.CandidateConfig.model_validate({**data,'source_contrasts':{'r':'c'}})
    with pytest.raises(ValidationError):c.CandidateConfig.model_validate({**data,'source_contrasts':{'different':'c'}})
    with pytest.raises(ValidationError):c.EvidenceWeight.model_validate({'item':'model_success_probability','weight':1.0})


def test_gsea_figure_requires_selected_term_and_enrichment_style_is_explicit():
    c=contracts()
    with pytest.raises(ValidationError):c.FigureConfig.model_validate(dict(result_source_id='r',figure_type='gsea'))
    assert c.FigureConfig.model_validate(dict(result_source_id='r',figure_type='gsea',term_row_key='term-row')).term_row_key=='term-row'
    assert c.FigureConfig.model_validate(dict(result_source_id='r',figure_type='enrichment',enrichment_style='bar')).enrichment_style=='bar'


def test_gsea_figure_preflight_requires_real_selected_term_row(tmp_path):
    from app.domain.bio_insights.service import BioInsightsService
    c=contracts();service=object.__new__(BioInsightsService)
    path=tmp_path/'terms.tsv';path.write_text('row_key\tterm_id\nt1\tGO:1\n',encoding='utf-8')
    source=dict(source_kind='bio_insight_result_version',source_id='r',metadata={'kind':'gsea_prerank'},
                members={'enrichment_results':{'path':str(path),'format':'tsv','size_bytes':path.stat().st_size}})
    good=c.FigureConfig(result_source_id='r',figure_type='gsea',term_row_key='t1')
    assert service._design(good,[source]).executable
    bad=c.FigureConfig(result_source_id='r',figure_type='gsea',term_row_key='missing')
    assert 'term_not_found' in {r.code for r in service._design(bad,[source]).blocking_reasons}


def test_figure_pixel_budget_and_heatmap_feature_limit_are_enforced_before_task_creation():
    c=contracts()
    with pytest.raises(ValidationError):c.FigureConfig.model_validate(dict(result_source_id='r',figure_type='volcano',width_inches=20.0,dpi=300))
    with pytest.raises(ValidationError):c.FigureConfig.model_validate(dict(result_source_id='r',figure_type='volcano',width_inches=13.5,height_inches=13.5,dpi=300))
    with pytest.raises(ValidationError):c.FigureConfig.model_validate(dict(result_source_id='r',figure_type='heatmap',top_n=101,
        processed_source_id='p',expression_groups=[{'label':'A','observation_keys':[{'processed_version_id':'p','barcode':'b'}]}]))

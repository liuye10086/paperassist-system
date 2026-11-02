import copy,json
import pytest

def typed(**patch):
    return dict(evidence_type='mutation_literature',object_id='ERBB2',namespace='gene_symbol',species_taxon_id=9606,tissue='breast',cell_type=None,condition='metastatic cancer',dose=None,time=None,measurement_scale='ctDNA',reference_version='hg19',variant_id='p.V777L',disease_id=None,disease_scope='direct',study_id='Yi2020',cohort_id='Yi2020',dependency_group='Yi2020',shared_dataset_ids=['Yi2020'],shared_donor_ids=None,obtained_date='2026-11-01',license='CC BY 4.0',locators=[dict(kind='xml_id',value='Par6',quote='ERBB2 HER2 V777L 13/105')],statement='13/105 source reported',effect_direction=None,result_status='reported',human_review_status='reviewed',independence_basis=None,**patch)

def test_typed_source_locator_and_human_review_never_upgrade():
    from app.domain.external_evidence.typed import TypedEvidence,verify_locators
    model=TypedEvidence.model_validate(typed())
    matched=verify_locators(b'<article><p id="Par6">ERBB2 HER2 V777L 13/105</p></article>','source.xml',model)
    assert matched['locator_verified'] and matched['biological_claim_status']=='source_reported'
    with pytest.raises(ValueError):verify_locators(b'<article><p id="other">ERBB2 HER2 V777L 13/105</p></article>','source.xml',model)
    with pytest.raises(ValueError):verify_locators(b'<article>','source.xml',model)
    with pytest.raises(ValueError):TypedEvidence.model_validate({**typed(),'independent_data_support':True})

def test_complete_matrix_preserves_missing_context_dependencies_and_unknown():
    from app.domain.bio_insights.external_matrix import build_matrix
    candidates=[dict(object_id='ERBB2',source_id='p',feature_id='HER2',namespace='label',species_taxon_id=9606,reference_version='unknown',condition='primary tumor'),dict(object_id='STAT5A',source_id='m',feature_id='STAT5A',namespace='symbol',species_taxon_id=9606,reference_version='unknown',condition='primary tumor')]
    evidence=[dict(source_id='e1',sha256='a'*64,metadata={'typed_evidence':typed(),'locator_verification':{'locator_verified':True}}),dict(source_id='e2',sha256='b'*64,metadata={'typed_evidence':{**typed(),'evidence_type':'disease_literature'},'locator_verification':{'locator_verified':True}}),dict(source_id='e3',sha256='c'*64,metadata={'typed_evidence':{**typed(),'evidence_type':'expression_atlas','study_id':'HPA','dependency_group':'HPA','cohort_id':None,'shared_dataset_ids':['HPA'],'condition':'normal breast'},'locator_verification':{'locator_verified':True}})]
    result=build_matrix(candidates,evidence,[])
    assert len(result['matrix'])==6 and len(result['dependency_groups'])==2
    assert [r['status'] for r in result['matrix']]==['context','context','context','missing','missing','missing']
    assert all(r['independent_data_support'] is False for r in result['matrix'])
    assert all(r['system_verified'] is False for r in result['matrix'])
    assert result['matrix'][0]['human_review_status']=='reviewed'
    assert result['matrix'][0]['locators'][0]['value']=='Par6'

def test_independence_requires_fixed_run_design_materials_row_and_overlap():
    from app.domain.bio_insights.external_matrix import independent_support
    c=dict(object_id='ERBB2',source_id='primary',feature_id='HER2',species_taxon_id=9606,condition='tumor')
    e={**typed(),'condition':'tumor','evidence_type':'public_validation','object_id':'ERBB2'}
    # A checkbox or different accessions never supplies an executed fixed run.
    assert independent_support(c,e,{},[])['supported'] is False
    assert independent_support(c,e,{'independent_data_support':True,'run_id':'fake'},[])['supported'] is False

@pytest.fixture
def bound_inputs(tmp_path):
    identity=dict(species_taxon_id=9606,namespace='gene_symbol',reference_version='hg19')
    candidate=dict(object_id='ERBB2',feature_id='ERBB2',source_id='primary',condition='tumor',expected_direction='up',**identity)
    evidence=dict(object_id='ERBB2',condition='tumor',**identity)
    observations=[dict(processed_version_id='validation',barcode=label[0]+str(i),donor='D'+str(i+offset),condition=label,retained=True) for label,offset in [('tumor',2),('normal',5)] for i in range(3)]
    primary=dict(source_id='primary',source_kind='bio_processed_dataset_version',sha256='a'*64,metadata=dict(canonical_dataset_id='A',observations=[dict(donor='D1',retained=True)],**identity))
    material=dict(source_id='validation',source_kind='bio_processed_dataset_version',sha256='b'*64,metadata=dict(canonical_dataset_id='B',observations=observations,feature_ids=['ERBB2'],**identity))
    from app.domain.bio_insights.contracts import ComparisonConfig
    plan=ComparisonConfig.model_validate(dict(kind='comparison',mode='donor_unpaired',family_contrast_ids=['c'],contrasts=[dict(contrast_id='c',name='tumor vs normal',**{side:dict(label=label,observation_keys=[dict(processed_version_id='validation',barcode=o['barcode']) for o in observations if o['condition']==label]) for side,label in [('numerator','tumor'),('denominator','normal')]})],**identity)).model_dump(mode='json')
    table=tmp_path/'result.tsv'
    table.write_text('row_key\tfeature_id\tcontrast_id\tnumerator\tdenominator\ttested\tq_within_contrast\teffect_value\nrow\tERBB2\tc\ttumor\tnormal\tTrue\t0.01\t2\n')
    result=dict(source_id='result',source_kind='bio_insight_result_version',metadata=dict(kind='comparison',run_id='fixed-run',task_status='succeeded',provenance='system_computed',canonical_dataset_ids=['B'],plan_config=plan,comparison_inputs=[copy.deepcopy(material)],**identity),members={'comparison_results':{'path':str(table)}})
    request=dict(evidence_source_id='e',candidate_object_id='ERBB2',result_source_id='result',result_row_key='row',material_source_ids=['validation'],design_source_id='design',overlap_audit_source_id='audit',numerator='tumor',denominator='normal')
    design=dict(schema='independent_validation_design_v1',material_source_ids=['validation'],object_id='ERBB2',species_taxon_id=9606,condition='tumor',numerator='tumor',denominator='normal')
    audit=dict(schema='donor_overlap_audit_v1',primary_donor_ids=['D1'],validation_donor_ids=['D'+str(i) for i in range(2,8)],identity_basis='fixed synthetic identities, not accession inequality',reviewer='engineering fixture')
    def original(sid,doc):
        path=tmp_path/(sid+'.json');path.write_text(json.dumps(doc))
        return dict(source_id=sid,source_kind='original_file',members={'original_file':{'path':str(path)}})
    sources=[primary,material,result,original('design',design),original('audit',audit),dict(source_id='e',metadata={'locator_verification':{'locator_verified':True}})]
    return candidate,evidence,request,sources


def test_positive_independent_engineering_gate_checks_fixed_artifacts(bound_inputs):
    from app.domain.bio_insights.external_matrix import independent_support
    c,e,request,sources=bound_inputs
    assert independent_support(c,e,request,sources)['supported'] is True
    unverified=copy.deepcopy(sources);unverified[-1]['metadata']['locator_verification']['locator_verified']=False;assert not independent_support(c,e,request,unverified)['supported']
    for key,value in [('canonical_dataset_id','A'),('observations',[dict(donor=None)]),('observations',[dict(donor='D1')])]:
        altered=copy.deepcopy(sources);altered[1]['metadata'][key]=value
        assert independent_support(c,e,request,altered)['supported'] is False
    altered=copy.deepcopy(sources);altered[2]['metadata']['task_status']='failed';assert not independent_support(c,e,request,altered)['supported']
    assert not independent_support(c,e,{**request,'result_row_key':'absent'},sources)['supported']


def test_candidate_v2_contract_and_source_scope():
    from app.domain.bio_insights.contracts import InsightPlanRequest,FigureConfig
    from app.domain.external_evidence.contracts import EvidenceRequest
    old=EvidenceRequest(file_id='f',source_kind='original',title='t',intended_use='reference',original_data='unknown').model_dump(mode='json')
    assert 'typed_evidence' not in old
    config=dict(kind='candidate',schema_version=2,candidates=[dict(object_id='STAT5A',source_id='p',feature_id='STAT5A',namespace='symbol',reference_version='unknown')],evidence_source_ids=['e'])
    sources=[dict(source_kind='bio_processed_dataset_version',source_id='p',role='processed',sha256='a'*64),dict(source_kind='external_evidence_version',source_id='e',role='external_evidence',sha256='b'*64)]
    body=dict(name='typed',kind='candidate',decision='draft',expected_revision=0,config=config,sources=sources)
    assert InsightPlanRequest.model_validate(body).config.schema_version==2
    with pytest.raises(ValueError):InsightPlanRequest.model_validate({**body,'sources':sources[:1]})
    with pytest.raises(ValueError):FigureConfig(result_source_id='r',figure_type='evidence_matrix',contrast_id='fake')

def test_support_documents_reject_generic_json_and_method_keeps_source_boundary():
    from app.domain.bio_insights.evidence_contracts import validate_support_document
    from app.adapters.research_method_text import present_method
    with pytest.raises(ValueError):validate_support_document(b'{"schema":"arbitrary"}')
    assert validate_support_document(json.dumps(dict(schema='donor_overlap_audit_v1',primary_donor_ids=['A'],validation_donor_ids=['B'],identity_basis='fixed IDs',reviewer='fixture')).encode()).reviewer=='fixture'
    method=dict(id='insight-method-c',source=dict(source_kind='bio_insight_result_version',source_id='r',sha256='a'*64),executed=True,parameters={'frozen_config':dict(kind='candidate',schema_version=2,candidates=[],evidence_source_ids=[]),'dependency_groups':{'g':['e']},'gaps':['没有真实KO']})
    shown=present_method(method,'zh-CN',reference='methods.json')
    assert '类型化外部证据' in shown['title'] and '不升级' in ''.join(shown['paragraphs'])

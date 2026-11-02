"""New qPCR identity and scientific prerequisites; no database or runtime."""
import pytest
from pydantic import ValidationError

@pytest.fixture(autouse=True)
def postgres_schema():yield None

def config():
    return dict(kind='comparison',schema_version=3,mode='qpcr',recipe='qpcr_relative_quantification_v1',
        file_source_id='f',parse_version_id='parse',columns={k:k for k in ('plate_id','well','sample_id','biological_unit_id','target_id','cq','detection_status','technical_replicate','condition')},
        targets=['T'],references=['R1','R2'],reference_basis='Validated stable references',calibrator_conditions=['control'],
        quantification='delta_delta_cq',equal_efficiency_confirmed=True,equal_efficiency_basis='Validated equal efficiency',
        independence_confirmed=True,independence_basis='Independent organisms',cross_plate='separate',
        contrasts=[dict(contrast_id='treated_control',name='treated/control',numerator='treated',denominator='control')],
        family_contrast_ids=['treated_control'],namespace='assay_label',reference_version='assays-v1')

def test_qpcr_plan_keeps_original_file_and_exact_parse():
    from app.domain.bio_insights.contracts import InsightPlanRequest
    from app.domain.bio_insights.task_contracts import InsightTaskSnapshot
    body=dict(name='qPCR',kind='comparison',expected_revision=0,config=config(),sources=[dict(source_kind='original_file',source_id='f',role='table',sha256='a'*64,locator=dict(parse_version_id='parse'))])
    plan=InsightPlanRequest.model_validate(body)
    assert plan.config.schema_version==3 and plan.config.recipe=='qpcr_relative_quantification_v1'
    task=InsightTaskSnapshot(kind='bio_comparison',workflow_version='bio_comparison_qpcr_v1',project_id='p',plan_version_id='v',run_id='r',source_digest='a'*64)
    assert task.workflow_version=='bio_comparison_qpcr_v1'
    body['sources'][0]['locator']['parse_version_id']='other'
    with pytest.raises(ValidationError):InsightPlanRequest.model_validate(body)

@pytest.mark.parametrize('change',[{'equal_efficiency_confirmed':False},{'references':['T']},{'family_contrast_ids':[]},{'cross_plate':'comparable','cross_plate_basis':''},{'quantification':'efficiency','efficiencies':{}},{'design':'paired','method':'welch_t'}])
def test_scientific_prerequisites_are_explicit(change):
    from app.domain.bio_insights.qpcr_contracts import QpcrConfig
    with pytest.raises(ValidationError):QpcrConfig.model_validate({**config(),**change})

def test_efficiency_representation_and_original_report_unit_are_not_guessed():
    from app.domain.bio_insights.qpcr_contracts import QpcrEfficiency,QpcrConfig
    assert QpcrEfficiency(value=100.,representation='percent',source='measured').factor==2
    assert QpcrEfficiency(value=1.,representation='fraction',source='measured').factor==2
    assert QpcrEfficiency(value=100.,representation='amplification_factor',source='measured').factor==100
    assert QpcrEfficiency(value=2.05,representation='amplification_factor',source='measured; investigate inhibition').factor==2.05
    for value in (float('inf'),float('nan'),1.):
        with pytest.raises(ValidationError):QpcrEfficiency(value=value,representation='amplification_factor',source='measured')
    c=config();c['original_checks']=[dict(sample_id='s',plate_id='p',target_id='T',metric='relative_quantity',original_value=1.,unit='Cq',tolerance=.1,precision_basis='precision',original_report_source='original')]
    with pytest.raises(ValidationError):QpcrConfig.model_validate(c)

def test_qpcr_gate_does_not_accept_only_general_or_partial_proof(monkeypatch,tmp_path):
    import json
    from app.domain.bio_insights import settings
    path=tmp_path/'gate.json';monkeypatch.setenv(settings.RUNTIME_MANIFEST_ENV,str(path));monkeypatch.setattr(settings,'runtime_identity',lambda:dict(available=True,code_digest='current'))
    path.write_text(json.dumps(dict(checks={})),encoding='utf-8')
    assert settings.qpcr_runtime_identity()['available'] is False
    path.write_text(json.dumps(dict(checks=dict(qpcr_relative_quantification=True,qpcr_paired_figure=True,qpcr_parent_validation=True))),encoding='utf-8')
    assert settings.qpcr_runtime_identity()['available'] is True

def test_reproduction_retains_reused_gate_provenance_without_changing_old_proof(monkeypatch,tmp_path):
    import json
    from app.domain.bio_insights import settings
    from app.domain.bio_insights.reproducibility import environment_proof
    from app.domain.bioinformatics.contracts import digest
    environment=dict(python='fixed',packages={},native_libraries=[],lock_sha256='a'*64,limits={})
    identity=dict(engine_version='fixed',code_digest='b'*64,lock_sha256='a'*64,environment_digest=digest(environment))
    monkeypatch.setattr(settings,'runtime_identity',lambda:dict(available=True,**identity));path=tmp_path/'proof.json';monkeypatch.setenv(settings.RUNTIME_MANIFEST_ENV,str(path))
    report=dict(**environment,checks=dict(qpcr_relative_quantification=True),isolation=dict(network='denied'))
    path.write_text(json.dumps(report),encoding='utf-8');old=environment_proof(identity)
    assert old['evidence_scope']=='actual_locked_runtime_gate' and 'reuse_provenance' not in old
    report.update(reused_checks=['gsea'],reuse_provenance=dict(image_digest='accepted-image',path_sha_verified=True),validation_scope='new qPCR actual gate plus exact accepted source checks')
    path.write_text(json.dumps(report),encoding='utf-8');proof=environment_proof(identity)
    assert proof['evidence_scope']=='accepted_checks_reused_with_actual_qpcr_gate'
    assert proof['reuse_provenance']==report['reuse_provenance'] and proof['reused_checks']==['gsea']

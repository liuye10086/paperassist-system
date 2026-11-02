"""Independent qPCR arithmetic, biological weighting, missingness and publication."""
import csv
import hashlib
import json
import math
import pytest
from tests.domain.test_qpcr_contracts import config

@pytest.fixture(autouse=True)
def postgres_schema():yield None

def payload(tmp_path, *, efficiency=False, unequal=False, changed_reference=False, fmt='csv'):
    cfg=config()
    if efficiency:cfg.update(quantification='efficiency',efficiencies={a:dict(value=e,representation='amplification_factor',source='fixed independent arithmetic') for a,e in [('T',1.9),('R1',2.),('R2',1.8)]})
    rows=[]
    for sample,condition,t,rep in [('c1','control',24 if unequal else 25,1),('c2','control',26 if unequal else 25,3 if unequal else 1),('s','treated',23,1)]:
        for assay,cq in [('T',t),('R1',19 if changed_reference and sample=='s' else 20),('R2',24 if changed_reference and sample=='s' else 22)]:
            for j in range(rep):rows.append(dict(plate_id='p1',well=f'A{len(rows)+1}',sample_id=sample,biological_unit_id=sample,target_id=assay,cq=str(cq),detection_status='detected',technical_replicate=str(j+1),condition=condition))
    path=tmp_path/('cq.'+fmt)
    if fmt=='xlsx':
        from openpyxl import Workbook
        wb=Workbook();ws=wb.active;ws.title='Cq';ws.append(list(rows[0]));[ws.append(list(r.values())) for r in rows];wb.save(path);cfg['sheet']='Cq'
    else:
        with path.open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]),delimiter='\t' if fmt=='tsv' else ',');writer.writeheader();writer.writerows(rows)
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    member=dict(path=str(path),sha256=sha,size_bytes=path.stat().st_size,format=fmt,role='original_file')
    source=dict(source_kind='original_file',source_id='f',sha256=sha,project_id='project',role='table',locator=dict(kind='object',parse_version_id='parse'),metadata=dict(parse_version_id='parse',parser_version='bio_insight_table_v1',sheet=cfg.get('sheet')),members=dict(original_file=member))
    return dict(schema_version=1,kind='bio_comparison',config=cfg,identity=dict(project_id='project',plan_version_id='plan'),sources=[source]),rows

def calculate(p):
    from app.domain.bio_insights.qpcr_design import prepare_qpcr
    return prepare_qpcr(p['config'],p['sources'])

def replace_rows(p,rows):
    from pathlib import Path
    member=p['sources'][0]['members']['original_file'];path=Path(member['path'])
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    member.update(size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest());p['sources'][0]['sha256']=member['sha256']

def paired_payload(tmp_path):
    p,base=payload(tmp_path);rows=[]
    p['config'].update(design='paired',method='paired_t',paired_plate_policy='within_plate_differences',paired_plate_basis='Each induction batch was assayed as a same-plate pair.')
    p['config']['columns']['pair_id']='pair_id'
    for i,difference in enumerate([1.,2.,3.,4.]):
        for condition,t in [('control',25+i*2),('treated',25+i*2-difference)]:
            for target,cq in [('T',t),('R1',20+i),('R2',22+i)]:
                rows.append(dict(plate_id='p'+str(i),well='A'+str(len(rows)+1),sample_id=condition+str(i),biological_unit_id='batch'+str(i),target_id=target,cq=str(cq),detection_status='detected',technical_replicate='1',condition=condition,pair_id='batch'+str(i)))
    replace_rows(p,rows);return p,rows

def test_same_plate_pair_differences_do_not_require_cross_plate_calibrator(tmp_path):
    from app.adapters.bio_insights_engine.qpcr import run_qpcr
    from app.adapters.bio_engine.manifest import Writer
    from app.domain.bio_insights.qpcr_design import validate_qpcr_design
    p,rows=paired_payload(tmp_path);assert validate_qpcr_design(p['config'],p['sources']).executable
    out=tmp_path/'paired';out.mkdir();run_qpcr(p,Writer(out))
    with (out/'comparison_results.tsv').open(encoding='utf-8') as stream:result=list(csv.DictReader(stream,delimiter='\t'))
    assert len(result)==1 and int(result[0]['n_pairs'])==4
    assert float(result[0]['effect_value'])==pytest.approx(2.5)
    assert float(result[0]['ci_fold_low'])==pytest.approx(2**float(result[0]['ci_log2_low']))
    assert float(result[0]['ci_fold_high'])==pytest.approx(2**float(result[0]['ci_log2_high']))
    assert float(result[0]['ci_fold_low'])<float(result[0]['fold_change'])<float(result[0]['ci_fold_high'])
    assert float(result[0]['statistical_effect_value'])==-2.5
    rows[0]['plate_id']='other';replace_rows(p,rows)
    assert not validate_qpcr_design(p['config'],p['sources']).executable

@pytest.mark.parametrize('boundary',['plate_conflict','nondetected','missing_calibrator','missing_pair','duplicate_time','original_difference'])
def test_input_boundaries_preserve_na_and_explicit_reasons(tmp_path,boundary):
    p,rows=payload(tmp_path)
    if boundary=='plate_conflict':rows[1]['well']=rows[0]['well']
    elif boundary=='nondetected':rows[-1].update(cq='Undetermined',detection_status='undetermined')
    elif boundary=='missing_calibrator':p['config']['calibrator_conditions']=['absent']
    elif boundary=='missing_pair':p['config'].update(design='paired',method='paired_t');p['config']['columns']['pair_id']='pair_id';rows=[{**r,'pair_id':r['sample_id']} for r in rows]
    elif boundary=='duplicate_time':rows[-1]['biological_unit_id']='c1';rows[-1]['condition']='control'
    else:p['config']['original_checks']=[dict(sample_id='s',plate_id='p1',target_id='T',metric='relative_quantity',original_value=3.,unit='fold',tolerance=.01,precision_basis='two decimal places',original_report_source='original report table 1')]
    replace_rows(p,rows)
    if boundary in ('plate_conflict','duplicate_time'):
        with pytest.raises(ValueError):calculate(p)
    elif boundary=='missing_pair':
        from app.domain.bio_insights.qpcr_design import validate_qpcr_design
        assert not validate_qpcr_design(p['config'],p['sources']).executable
    elif boundary=='original_difference':
        check=calculate(p)['original_checks'][0];assert check['difference']==1 and check['decision']=='difference'
    else:
        sample=next(r for r in calculate(p)['samples'] if r['sample_id']=='s')
        assert sample['relative_quantity'] is None and sample['reason'] is not None

def test_explicitly_excluded_control_preserves_missing_biological_identity(tmp_path):
    p,rows=payload(tmp_path)
    rows.append({**rows[-1],'well':'NTC1','sample_id':'','biological_unit_id':'','condition':'','cq':'not available','detection_status':'control','technical_replicate':''})
    p['config']['excluded_wells']=[dict(plate_id='p1',well='NTC1',reason='NTC control; no biological sample identity')]
    replace_rows(p,rows);data=calculate(p)
    assert len(data['audit'])==10 and len(data['samples'])==3
    assert data['audit'][-1]['biological_unit_id']=='' and data['audit'][-1]['parsed_cq'] is None
    assert data['audit'][-1]['reason'].startswith('explicit_exclusion:')

def test_partial_explicit_calibrator_missing_blocks_but_global_per_plate_subsets_are_valid(tmp_path):
    from app.domain.bio_insights.qpcr_design import validate_qpcr_design
    p,_=payload(tmp_path);p['config'].update(calibrator_conditions=[],calibrator_sample_ids=['c1','absent'])
    preview=validate_qpcr_design(p['config'],p['sources'])
    assert not preview.executable and any('absent' in reason.message for reason in preview.blocking_reasons)
    with pytest.raises(ValueError,match='qpcr_calibrator_sample_ids_missing:absent'):calculate(p)
    p,_=paired_payload(tmp_path);p['config'].update(calibrator_conditions=[],calibrator_sample_ids=['control'+str(i) for i in range(4)])
    data=calculate(p);assert validate_qpcr_design(p['config'],p['sources']).executable
    assert all(row['calibrator_n']==1 and row['relative_quantity'] is not None for row in data['samples'])

def test_efficiency_above_two_is_frozen_unclamped_and_warned(tmp_path):
    from app.domain.bio_insights.qpcr_design import validate_qpcr_design
    p,_=payload(tmp_path,efficiency=True)
    p['config']['efficiencies']['T'].update(value=2.05,source='Measured amplification factor above theoretical doubling; retained for review')
    data=calculate(p);preview=validate_qpcr_design(p['config'],p['sources'])
    assert preview.executable and any('T' in warning and '2.05' in warning for warning in preview.warnings)
    assert data['config'].efficiencies['T'].value==2.05
    assert next(r for r in data['samples'] if r['sample_id']=='s')['relative_quantity']==pytest.approx(2.05**2)

def test_qpcr_figure_uses_every_biological_point_and_pair_without_refit(tmp_path):
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_insights_engine.qpcr import run_qpcr
    from app.adapters.bio_insights_engine.qpcr_figures import qpcr_plot_data
    from app.domain.bio_insights.contracts import FigureConfig
    p,_=paired_payload(tmp_path);out=tmp_path/'figure_source';out.mkdir();writer=Writer(out);run_qpcr(p,writer)
    source=dict(source_id='result',metadata=dict(plan_config=p['config']),members={r['key']:r for r in writer.artifacts})
    cfg=FigureConfig(result_source_id='result',figure_type='qpcr_samples',feature_ids=['T'],contrast_id='treated_control',figure_stratum='within_plate_pairs')
    data=qpcr_plot_data(source,cfg)
    assert len(data['points'])==8 and len(data['pairs'])==4
    assert data['analysis_recomputed'] is False and data['error_type']=='none; biological sample points'
    assert {point['plate_id'] for point in data['points']}=={'p0','p1','p2','p3'}

@pytest.mark.parametrize('fmt',['csv','tsv','xlsx'])
def test_equal_efficiency_and_calibrator_biological_weight(tmp_path,fmt):
    p,_=payload(tmp_path,unequal=True,fmt=fmt);data=calculate(p)
    sample=next(r for r in data['samples'] if r['sample_id']=='s')
    assert sample['delta_delta_cq']==-2 and sample['relative_quantity']==4
    assert sample['calibrator_n']==2 and len(data['samples'])==3
    assert all(r['biological_n']==1 for r in data['samples'])
    assert data['audit'][0]['source_locations']['sample_id']['cell']=='C2'

@pytest.mark.parametrize('changed_reference',[False,True])
def test_efficiency_geometric_reference_denominator(tmp_path,changed_reference):
    p,_=payload(tmp_path,efficiency=True,changed_reference=changed_reference);sample=next(r for r in calculate(p)['samples'] if r['sample_id']=='s')
    expected=3.61/math.sqrt(2**1*1.8**-2) if changed_reference else 3.61
    assert sample['relative_quantity']==pytest.approx(expected,rel=1e-12)
    assert sample['log2_quantity']==pytest.approx(math.log2(expected))

def test_missing_reference_is_na_not_zero_and_plate_conflict_blocks(tmp_path):
    p,_=payload(tmp_path)
    p['config']['excluded_wells']=[dict(plate_id='p1',well='A9',reason='confirmed assay exclusion')]
    sample=next(r for r in calculate(p)['samples'] if r['sample_id']=='s')
    assert sample['relative_quantity'] is None and sample['reason']=='reference_missing:R2'
    p['config']['columns']['well']='plate_id'
    with pytest.raises(ValueError):calculate(p)

def test_pipeline_publishes_full_members_and_rejects_tamper(tmp_path):
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_process import validate_result
    p,_=payload(tmp_path);out=tmp_path/'out';out.mkdir();p['output_directory']=str(out)
    result=run(p)
    keys={m['key'] for m in result['outputs']}
    assert {'qpcr_well_audit','qpcr_technical_summary','qpcr_sample_quantities','comparison_results','correction_families','qpcr_original_checks','qpcr_plot_data','methods','recipe','manifest'}<=keys
    assert result['methods']['statistical_scale']=='delta_cq' and result['summary']['biological_units']==3
    validate_result(result,out,p)
    result['summary']['biological_units']=9
    with pytest.raises(Exception):validate_result(result,out,p)

def test_parent_reconciles_quantities_even_when_all_artifact_hashes_are_updated(tmp_path):
    from pathlib import Path
    from app.adapters.bio_insights_engine.pipeline import run
    from app.adapters.bio_insights_process import validate_result
    from app.adapters.bio_engine.manifest import canonical
    p,_=payload(tmp_path);out=tmp_path/'tampered';out.mkdir();p['output_directory']=str(out);result=run(p)
    member=next(m for m in result['outputs'] if m['key']=='qpcr_sample_quantities');path=Path(member['path'])
    with path.open(encoding='utf-8',newline='') as stream:
        reader=csv.DictReader(stream,delimiter='\t');fields=reader.fieldnames;records=list(reader)
    records[-1]['relative_quantity']='999'
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,delimiter='\t',lineterminator='\n');writer.writeheader();writer.writerows(records)
    member.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size_bytes=path.stat().st_size)
    result['manifest']['members']=[{k:v for k,v in m.items() if k!='path'} for m in result['outputs'] if m['key']!='manifest']
    manifest=next(m for m in result['outputs'] if m['key']=='manifest');content=canonical(result['manifest']);Path(manifest['path']).write_bytes(content);manifest.update(sha256=hashlib.sha256(content).hexdigest(),size_bytes=len(content))
    with pytest.raises(Exception) as error:validate_result(result,out,p)
    assert 'qpcr_full_member_mismatch:qpcr_sample_quantities' in str(error.value.__cause__)

"""Narrow actual isolated qPCR arithmetic/paired-figure gate; no old model fits."""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys

NAMES=('delta-delta-cq','efficiency','efficiency-reference-change','paired-figure')

def exercise(root):
    from .worker import actual_identity, warm_render_environment
    from .probe_transport import monitored_run
    from app.adapters.bio_insights_process import validate_result
    from app.domain.bio_insights.qpcr_contracts import QpcrConfig
    from app.domain.bio_insights.contracts import FigureConfig
    root=Path(root);root.mkdir(parents=True,exist_ok=True);warm=root/'warm';warm.mkdir();warm_render_environment(warm)
    runtime=actual_identity();identity={k:runtime[k] for k in ('engine_version','code_digest','environment_digest','lock_sha256')}
    identity.update(project_id='synthetic-qpcr-gate',task_id='synthetic-qpcr-task',plan_version_id='synthetic-qpcr-plan',source_digest='f'*64)
    def child(kind,config,sources,name):
        dest=root/name;dest.mkdir();request=dict(schema_version=1,kind=kind,config=config,sources=sources,identity=identity,output_directory=str(dest),_runtime_identity=runtime)
        body=json.dumps(request,allow_nan=False).encode()
        process=monitored_run([sys.executable,'-I','-B',str(Path(__file__).with_name('worker.py')),str(os.getpid())],struct.pack('!I',len(body))+body,timeout=180)
        (root/(name+'-stderr.txt')).write_bytes(process.stderr)
        if process.returncode or not process.stdout.startswith(b'READY\n'):raise RuntimeError('qpcr_child_transport_failed')
        answer=json.loads(process.stdout[6:])
        if 'result' not in answer:raise RuntimeError('qpcr_child_failed:'+json.dumps(answer))
        result=answer['result'];validate_result(result,dest,request)
        (root/(name+'-request.json')).write_text(json.dumps(request,allow_nan=False),encoding='utf-8')
        (root/(name+'-result.json')).write_text(json.dumps(result,allow_nan=False),encoding='utf-8')
        return result
    reference=None
    for mode in NAMES[:3]:
        rows=[]
        for i,difference in enumerate([2.,1.,3.,4.]):
            for condition,t in [('control',25+i),('treated',25+i-difference)]:
                for assay,cq in [('T',t),('R1',19 if mode.endswith('change') and condition=='treated' else 20),('R2',24 if mode.endswith('change') and condition=='treated' else 22)]:
                    rows.append(dict(plate_id='p'+str(i),well='A'+str(len(rows)+1),sample_id=condition+str(i),biological_unit_id='batch'+str(i),target_id=assay,cq=cq,detection_status='detected',technical_replicate='1',condition=condition,pair_id='batch'+str(i)))
        path=root/(mode+'.csv')
        with path.open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        sha=hashlib.sha256(path.read_bytes()).hexdigest();member=dict(path=str(path),sha256=sha,size_bytes=path.stat().st_size,format='csv',role='original_file')
        source=dict(source_kind='original_file',source_id='raw',sha256=sha,role='table',project_id=identity['project_id'],locator=dict(kind='object',parse_version_id='parse'),
            members=dict(original_file=member),metadata=dict(parse_version_id='parse',parser_version='bio_insight_table_v1',sheet=None))
        cfg=QpcrConfig(file_source_id='raw',parse_version_id='parse',columns={k:k for k in rows[0]},targets=['T'],references=['R1','R2'],reference_basis='synthetic gate only',
            calibrator_conditions=['control'],equal_efficiency_confirmed=True,equal_efficiency_basis='synthetic gate only',
            quantification='delta_delta_cq' if mode=='delta-delta-cq' else 'efficiency',
            efficiencies={} if mode=='delta-delta-cq' else {a:dict(value=e,representation='amplification_factor',source='synthetic independent arithmetic') for a,e in [('T',1.9),('R1',2.),('R2',1.8)]},
            design='paired',method='paired_t',independence_confirmed=True,independence_basis='synthetic batches',paired_plate_policy='within_plate_differences',paired_plate_basis='synthetic same-plate pairs',
            contrasts=[dict(contrast_id='B_A',name='B/A',numerator='treated',denominator='control')],family_contrast_ids=['B_A'],namespace='synthetic_assay',reference_version='fixed')
        result=child('bio_comparison',cfg.model_dump(mode='json'),[source],mode)
        quantities=next(m for m in result['outputs'] if m['key']=='qpcr_sample_quantities')
        with Path(quantities['path']).open(encoding='utf-8',newline='') as stream:actual=next(r for r in csv.DictReader(stream,delimiter='\t') if r['sample_id']=='treated0')
        expected=4. if mode=='delta-delta-cq' else 3.61/math.sqrt(2*1.8**-2) if mode.endswith('change') else 3.61
        assert math.isclose(float(actual['relative_quantity']),expected,rel_tol=1e-12)
        if mode=='delta-delta-cq':reference=(cfg,result)
    cfg,result=reference
    upstream=dict(source_kind='bio_insight_result_version',source_id='result',sha256='b'*64,role='result',project_id=identity['project_id'],locator=dict(kind='object'),
        members={m['key']:m for m in result['outputs']},metadata=dict(kind='comparison',plan_config=cfg.model_dump(mode='json'),inference_scope='sample_inference',provenance='system_computed'))
    figure=FigureConfig(result_source_id='result',figure_type='qpcr_samples',feature_ids=['T'],contrast_id='B_A',figure_stratum='within_plate_pairs',formats=['png','tiff','svg'])
    plotted=child('bio_insight_figure',figure.model_dump(mode='json'),[upstream],'paired-figure')
    plot=json.loads(Path(next(m for m in plotted['outputs'] if m['key']=='plot_data')['path']).read_bytes())
    assert len(plot['points'])==8 and len(plot['pairs'])==4 and len([m for m in plotted['outputs'] if m['role']=='figure'])==3
    return dict(runtime_identity=runtime,checks=dict(qpcr_relative_quantification=True,qpcr_paired_figure=True),evidence_scope='synthetic_qpcr_actual_isolated_children_only')

def validate_parent(root):
    from app.adapters.bio_insights_process import validate_result
    root=Path(root)
    for name in NAMES:
        request=json.loads((root/(name+'-request.json')).read_bytes());result=json.loads((root/(name+'-result.json')).read_bytes())
        validate_result(result,root/name,request)
    return dict(checks=dict(qpcr_parent_validation=True),validated_names=NAMES)

if __name__=='__main__':
    answer=validate_parent(sys.argv[2]) if sys.argv[1]=='--validate-parent' else exercise(sys.argv[1])
    print(json.dumps(answer,sort_keys=True))

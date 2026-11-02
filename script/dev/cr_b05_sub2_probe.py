"""Run only new qPCR probes; inherit accepted checks with explicit code/environment evidence."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime,timezone

os.environ['PAPERASSIST_CR_B05_SUBPACKAGE']='2'
import cr_b05_runner as control
from cr_b05_probe import image_identity,save


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def inherited_report(old,baseline,actual,parent,tabular_digest,image,provenance):
    if old['status']!='passed' or old['code_digest']!=baseline['insight_code_digest'] or old['lock_sha256']!=baseline['insight_lock_digest']:
        raise ValueError('Accepted report and image baseline differ')
    environment={k:old[k] for k in ('python','packages','native_libraries','lock_sha256','limits')}
    runtime=actual['runtime_identity']
    if runtime.get('available') is not True or runtime['environment_digest']!=digest(environment) or runtime['lock_sha256']!=old['lock_sha256']:
        raise ValueError('Scientific environment differs; inherited checks cannot be reused')
    if actual['checks']!={'qpcr_relative_quantification':True,'qpcr_paired_figure':True} or parent['checks']!={'qpcr_parent_validation':True}:
        raise ValueError('New actual qPCR checks incomplete')
    expected=['delta-delta-cq','efficiency','efficiency-reference-change','paired-figure']
    if sorted(parent['validated_names'])!=sorted(expected):raise ValueError('Parent validation coverage differs')
    value={**old,'code_digest':runtime['code_digest'],'tabular_code_digest':tabular_digest,'image_digest':image,
        'checks':{**old['checks'],**actual['checks'],**parent['checks']},
        'validation_scope':'accepted checks reused; only new qPCR actual isolated children and parent checks executed',
        'reused_checks':list(old['checks']),'reuse_provenance':provenance,
        'qpcr_probe_evidence':actual['evidence_scope'],'verified_at':datetime.now(timezone.utc).isoformat()}
    return value


def run():
    state=control.read_state();control.configure(state)
    olddir=control.ROOT/'script/.runtime/client-requirements-b05'
    baseline=json.loads((control.RUNTIME/'accepted-engine-baseline.json').read_bytes())
    old=json.loads((olddir/'runtime-gate.json').read_bytes())
    oldbio=json.loads((olddir/'bio-runtime-gate.json').read_bytes())
    image=control.worker_stack.docker(['image','inspect','--format','{{.Id}}',control.WORKER_IMAGE]).strip()
    inspected=json.loads(control.worker_stack.docker(['image','inspect',control.BASE_IMAGE_ID,image]))
    base_layers,new_layers=[x['RootFS']['Layers'] for x in inspected]
    if new_layers[:len(base_layers)]!=base_layers or len(new_layers)!=len(base_layers)+1:
        raise ValueError('Expected retained dependency layers plus one app-only layer')
    dockerfile=(control.RUNTIME/'Dockerfile.worker').read_text(encoding='utf-8')
    if dockerfile!='FROM '+control.BASE_IMAGE+'\nCOPY backend/app /app/app\n':raise ValueError('Only app source changes may inherit environment checks')
    identity=image_identity(image)
    if identity['bio_code_digest']!=oldbio['code_digest'] or identity['bio_lock_digest']!=oldbio['lock_sha256']:
        raise ValueError('Visium executable code changed; cannot inherit unchanged-code proof')
    changed={}
    for name,content in baseline['files'].items():
        current=(control.ROOT/'backend/app'/name).read_text(encoding='utf-8')
        if current!=content:changed[name]=hashlib.sha256(current.encode()).hexdigest()
    # Old numerical kernels must stay byte-for-byte equal. Dispatch/config additions are reviewed separately.
    expected={'adapters/bio_insights_engine/figures.py','adapters/bio_insights_engine/pipeline.py',
        'adapters/bio_insights_engine/worker.py','domain/bio_insights/contracts.py','domain/bio_insights/settings.py'}
    if set(changed)-expected:raise ValueError('An accepted scientific path changed outside the qPCR integration scope: '+str(set(changed)-expected))
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    evidence=control.RUNTIME/('qpcr-probe-'+stamp);evidence.mkdir()
    interpreter='/opt/paperassist-bio-insights/bin/python'
    common=['docker','run','--network','none','--read-only','--memory','2g','--cpus','1','--pids-limit','64',
        '--tmpfs','/tmp:rw,size=512m','--mount','type=bind,source='+str(evidence)+',target=/probe']
    def execute(label,entry,args):
        command=common+['--name','pa-b05-sub2-'+stamp.lower()+'-'+label,'--entrypoint',entry,image,'-B','-m','app.adapters.bio_insights_engine.qpcr_probe',*args]
        save(evidence/(label+'-request.json'),{'command':command})
        with (evidence/(label+'-stdout.json')).open('wb') as out,(evidence/(label+'-stderr.txt')).open('wb') as err:
            result=subprocess.run(command,cwd=control.ROOT,stdout=out,stderr=err,timeout=600)
        save(evidence/(label+'-completion.json'),{'exit_code':result.returncode,'container_retained':True})
        if result.returncode:raise RuntimeError('New qPCR '+label+' failed; evidence retained at '+str(evidence))
        return json.loads((evidence/(label+'-stdout.json')).read_bytes())
    actual=execute('child',interpreter,['/probe/work'])
    parent=execute('parent','python',['--validate-parent','/probe/work'])
    from app.domain.bioinformatics.tabular_settings import engine_code_digest
    provenance=dict(source_image=control.BASE_IMAGE_ID,source_report=str(olddir/'runtime-gate.json'),
        source_report_sha256=hashlib.sha256((olddir/'runtime-gate.json').read_bytes()).hexdigest(),
        retained_dependency_layers=base_layers,changed_integration_files=changed,unchanged_science_files=len(baseline['files'])-len(changed),
        actual_new_evidence=str(evidence),old_scientific_checks_executed=False)
    report=inherited_report(old,baseline,actual,parent,engine_code_digest(),image,provenance)
    # Final source identity check prevents publishing a gate for a concurrently edited checkout.
    image_identity(image)
    save(control.GATE,report)
    save(control.BIO_GATE,{**oldbio,'image_digest':image})
    save(control.RUNTIME/'bio-gate-reuse.json',dict(source_image=control.BASE_IMAGE_ID,source_report=str(olddir/'bio-runtime-gate.json'),
        target_image=image,validation_scope='unchanged code and retained dependency layers; accepted checks reused'))
    from app.domain.bio_insights.settings import qpcr_runtime_identity
    if not qpcr_runtime_identity().get('available'):raise ValueError('New qPCR gate not available')
    generation='r'+image[7:19]
    state.update(worker_image_id=image,service_generation=generation,network_profile=dict(profile='sub2-explicit-ipam',generation=generation,image_digest=image))
    control.worker_stack.private_write(control.STATE,json.dumps(control.validate_state(state),indent=2))
    return dict(image=image,available=True,evidence=str(evidence),reused_checks=list(old['checks']),new_checks=list(actual['checks'])+list(parent['checks']))

def rebind_unchanged_science(network_profile='sub2-explicit-ipam'):
    """An application-only fix can reuse the completed exact scientific-code gate."""
    if network_profile not in ('sub2-explicit-ipam','sub2-refresh-ipam'):raise ValueError('Unknown subpackage-two network profile')
    state=control.read_state();control.configure(state)
    image=control.worker_stack.docker(['image','inspect','--format','{{.Id}}',control.WORKER_IMAGE]).strip()
    image_identity(image)
    report=json.loads(control.GATE.read_bytes());bio=json.loads(control.BIO_GATE.read_bytes())
    from app.domain.bio_insights.settings import engine_code_digest,engine_lock_digest
    from app.domain.bioinformatics.tabular_settings import engine_code_digest as tabular_digest
    from app.domain.bioinformatics.analysis_settings import engine_code_digest as bio_digest
    if report['code_digest']!=engine_code_digest() or report['lock_sha256']!=engine_lock_digest() or report['tabular_code_digest']!=tabular_digest() or bio['code_digest']!=bio_digest():
        raise ValueError('Scientific code changed; an application-only rebind cannot be used')
    image_record=json.loads(control.worker_stack.docker(['image','inspect',image]))[0]
    retained_layers=report['reuse_provenance']['retained_dependency_layers']
    if image_record['RootFS']['Layers'][:-1]!=retained_layers:raise ValueError('Dependency layers changed')
    expected='FROM '+control.BASE_IMAGE+'\nCOPY backend/app /app/app\n'
    if (control.RUNTIME/'Dockerfile.worker').read_text(encoding='utf-8')!=expected:raise ValueError('Expected app-only Dockerfile')
    history=control.RUNTIME/'gate-history';history.mkdir(exist_ok=True)
    previous=report['image_digest']
    save(history/('before-app-rebind-'+previous[7:19]+'.json'),report)
    report['image_digest']=image;bio['image_digest']=image
    report['reuse_provenance']['application_only_rebind']=dict(from_image=previous,to_image=image,scientific_code_unchanged=True,dependency_layers_unchanged=True,probe_repeated=False)
    save(control.GATE,report);save(control.BIO_GATE,bio)
    generation='r'+image[7:19]
    state.update(worker_image_id=image,service_generation=generation,network_profile=dict(profile=network_profile,generation=generation,image_digest=image))
    control.worker_stack.private_write(control.STATE,json.dumps(control.validate_state(state),indent=2))
    return dict(image=image,scientific_gate_reused=True,probe_repeated=False)


def parse_args(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rebind-unchanged-science',action='store_true')
    parser.add_argument('--network-profile',choices=['sub2-explicit-ipam','sub2-refresh-ipam'])
    args=parser.parse_args(argv)
    if args.network_profile and not args.rebind_unchanged_science:parser.error('--network-profile requires --rebind-unchanged-science')
    return args


if __name__=='__main__':
    args=parse_args()
    print(json.dumps(rebind_unchanged_science(args.network_profile or 'sub2-explicit-ipam') if args.rebind_unchanged_science else run()))

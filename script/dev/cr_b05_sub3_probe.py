"""Bind incremental checks to explicitly reused accepted scientific evidence."""
import base64
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
os.environ['PAPERASSIST_CR_B05_SUBPACKAGE']='3'
import cr_b05_runner as control
from cr_b05_probe import image_identity,save

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_bytes())
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def reuse_evidence(image,inventory):
    baseline_path=control.RUNTIME/'accepted-final-engine-baseline.json';baseline=read(baseline_path)
    compatibility=read(control.RUNTIME/'dependencies/compatibility.json')
    assert baseline['source_image']==compatibility['base_image']==control.BASE_IMAGE_ID
    inspected=json.loads(control.worker_stack.docker(['image','inspect',control.BASE_IMAGE_ID,compatibility['dependency_image'],image]))
    accepted,deps,final=[v['RootFS']['Layers'] for v in inspected]
    assert deps[:len(accepted)]==accepted and final[:len(deps)]==deps
    packages=inventory['packages'];old_packages=baseline['packages']['paperassist-bio-insights']
    assert all(packages.get(k)==v for k,v in old_packages.items())
    assert {k:v for k,v in packages.items() if k not in old_packages}==compatibility['added']
    old_lock=base64.b64decode(baseline['locks']['requirements-bio-insights.lock.txt']['base64'])
    new_lock=(control.ROOT/'backend/requirements-bio-insights.lock.txt').read_bytes()
    old_lines=[v for v in old_lock.splitlines() if v.strip()];new_lines=[v for v in new_lock.splitlines() if v.strip()]
    assert new_lines[:len(old_lines)]==old_lines
    assert sha(control.ROOT/'backend/requirements-bio.lock.txt')==baseline['locks']['requirements-bio.lock.txt']['sha256']
    bio=['embedding','errors','figure','manifest','markers','plots','preprocess','qc','runtime_probe','sandbox','tabular_probe','tabular_worker']
    insight=['candidates','comparison','counts_model','enrichment','evidence','figure_data','mapping','probe_transport','qpcr','qpcr_figures','qpcr_probe','quantitative','quantitative_figures','quantitative_inputs','quantitative_probe','resources','result_import','runtime_probe','sandbox','tables','transport']
    expected=['adapters/bio_engine/'+v+'.py' for v in bio]+['adapters/bio_insights_engine/'+v+'.py' for v in insight]
    expected+=['domain/comparison/kernel.py','domain/bio_insights/design.py','domain/bio_insights/quantitative_contracts.py','domain/bio_insights/quantitative_design.py','domain/bio_insights/qpcr_contracts.py','domain/bio_insights/qpcr_design.py','adapters/excel_sandbox.py']
    actual={name:sha(control.ROOT/'backend/app'/name) for name in expected}
    changed=[name for name,value in actual.items() if baseline['files'].get(name)!=value]
    if changed:raise ValueError('Accepted numerical implementation changed: '+str(changed))
    return dict(source_image=control.BASE_IMAGE_ID,target_image=image,baseline_sha256=sha(baseline_path),unchanged_science_files=actual,accepted_layers=accepted,dependency_layers=deps,existing_package_versions_changed={},added_packages=compatibility['added'],old_lock_entries_unchanged=True,whole_lock_bytes_unchanged=False,old_scientific_checks_executed=False)

def bind(inventory_path,micro_path,parent_path,cell_path=None):
    state=control.read_state();control.configure(state)
    image=control.worker_stack.docker(['image','inspect','--format','{{.Id}}',control.WORKER_IMAGE]).strip();identity=image_identity(image)
    inventory=read(inventory_path);micro=read(micro_path);parent=read(parent_path)
    provenance=reuse_evidence(image,inventory)
    from app.domain.bio_insights.settings import engine_code_digest,engine_lock_digest,BioInsightsLimits
    from app.domain.bioinformatics.tabular_settings import engine_code_digest as tabular_digest
    environment={k:inventory[k] for k in ('python','packages','native_libraries','lock_sha256','limits')}
    runtime=dict(available=True,engine_version='bio_insights_v1.0.0',code_digest=engine_code_digest(),lock_sha256=engine_lock_digest(),environment_digest=digest(environment))
    assert inventory['runtime_identity']==runtime and inventory['limits']==BioInsightsLimits().model_dump()
    assert micro['runtime_identity']==runtime
    assert micro['checks']==dict(microbiome_diversity=True,microbiome_beta=True,microbiome_figures=True) and all(type(v) is bool for v in micro['checks'].values())
    assert parent['checks']==dict(microbiome_parent_validation=True) and all(type(v) is bool for v in parent['checks'].values())
    assert sorted(parent['validated_names'])==['alpha','composition','diversity','pcoa']
    cell_dir=Path(cell_path) if cell_path else control.RUNTIME/'cell-actual-worker';cell=read(cell_dir/'stdout.json');cell_identity=read(cell_dir/'source-identity.json')
    assert read(cell_dir/'completion.json')['exit_code']==0 and cell['checks']==dict(actual_single_cell_import=True,actual_nonspatial_qc=True)
    cell_paths={k:v for k,v in cell_identity['files'].items() if Path(k).name not in ('tabular_assays.py','tabular_probe.py','tabular_worker.py')}
    assert all(sha(control.ROOT/k)==v for k,v in cell_paths.items())
    olddir=control.ROOT/'script/.runtime/client-requirements-b05-sub2';old=read(olddir/'runtime-gate.json');bio=read(olddir/'bio-runtime-gate.json')
    assert old['status']=='passed' and bio['gate_status']=='passed'
    provenance.update(source_report=str(olddir/'runtime-gate.json'),source_report_sha256=sha(olddir/'runtime-gate.json'),new_evidence={str(p):sha(p) for p in (Path(inventory_path),Path(micro_path),Path(parent_path),cell_dir/'stdout.json')},cell_evidence_scope='production worker on unchanged bio environment and exact new cell source; reused after byte checks',reused_checks=list(old['checks']),not_reexecuted=['accepted bulk/protein/metabolome/qPCR/DESeq2/GSEA full numerical validation'])
    stamp=datetime.now(timezone.utc).isoformat()
    report={**old,**environment,'code_digest':runtime['code_digest'],'tabular_code_digest':tabular_digest(),'image_digest':image,'checks':{**old['checks'],**micro['checks'],**parent['checks']},'verified_at':stamp,'validation_scope':'incremental: accepted numerical evidence reused; new microbiome workers and cell integration checked','reused_checks':list(old['checks']),'reuse_provenance':provenance,'resource_observation_source':'legacy peak_rss_kib/counter fields are accepted baseline observations; new worker metrics are in actual_delta_evidence','actual_delta_evidence':dict(microbiome=micro,parent=parent,single_cell=cell)}
    bio={**bio,'code_digest':identity['bio_code_digest'],'image_digest':image,'verified_at':stamp}
    single={k:bio[k] for k in ('schema_version','gate_status','engine_version','environment_digest','code_digest')}
    single['checks']=dict(h5ad_axes=True,counts_equivalence=True,cell_aggregation=True,nonspatial_dispatch=True)
    save(control.RUNTIME/'bio-gate-reuse.json',{**provenance,'source_report':str(olddir/'bio-runtime-gate.json'),'source_report_sha256':sha(olddir/'bio-runtime-gate.json'),'local_cell_reference_logs':{p.name:sha(p) for p in [control.RUNTIME/'task-a-h5ad-green.log',control.RUNTIME/'task-a-standard-formats.log',control.RUNTIME/'task-a-fix-green-final.log',control.RUNTIME/'task-a-visium-compat.log']}})
    save(control.GATE,report);save(control.BIO_GATE,bio);save(control.SINGLE_CELL_GATE,single)
    generation='r'+image[7:19];state.update(worker_image_id=image,service_generation=generation,network_profile=dict(profile='sub3-identity-ipam' if cell_path else 'sub3-explicit-ipam',generation=generation,image_digest=image))
    save(control.STATE,control.validate_state(state))
    return dict(image=image,new_checks=list(micro['checks'])+list(parent['checks']),reused_checks=list(old['checks']))

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('inventory');parser.add_argument('microbiome');parser.add_argument('parent');parser.add_argument('--cell-evidence');args=parser.parse_args()
    print(json.dumps(bind(args.inventory,args.microbiome,args.parent,args.cell_evidence)))

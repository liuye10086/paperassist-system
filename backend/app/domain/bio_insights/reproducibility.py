"""Owner-authorized portable B04 inputs, resources, code and formal results."""
import copy
import json
import os
from pathlib import Path

from app.adapters.bio_insights_store import BioInsightsStore,invalid
from app.adapters.bio_insights_reproduction import ReproductionArchive
from app.adapters.bio_analysis_store import scoped_object
from app.core.exceptions import StorageError
from app.domain.bioinformatics.contracts import digest
from .bulk_reproduction_environment import archived_environment
from .service import BioInsightsService
from .results import checked_members


def environment_proof(identity, *, bulk_model=False, bulk_display=False, bulk_enrichment=False):
    from .settings import runtime_identity, RUNTIME_MANIFEST_ENV, BULK_MODEL_MANIFEST_ENV, BULK_DISPLAY_MANIFEST_ENV
    if bulk_display or bulk_enrichment:
        env_name, actual = BULK_DISPLAY_MANIFEST_ENV, runtime_identity(bulk_display=True, bulk_enrichment=bulk_enrichment)
    elif bulk_model:
        env_name, actual = BULK_MODEL_MANIFEST_ENV, runtime_identity(bulk_model=True)
    else:
        env_name, actual = RUNTIME_MANIFEST_ENV, runtime_identity()
    if not actual.get('available') or any(actual.get(key)!=identity.get(key) for key in ('engine_version','code_digest','environment_digest','lock_sha256')):
        raise invalid('bio_insights_environment_unavailable',422)
    path=Path(os.environ[env_name]);report=json.loads(path.read_bytes())
    environment={key:report[key] for key in ('python','packages','native_libraries','lock_sha256','limits')}
    if digest(environment)!=identity['environment_digest']:raise invalid('bio_insights_environment_unavailable',422)
    proof=dict(environment=environment,runtime_identity=actual,gate_checks=report['checks'],isolation=report['isolation'],
               evidence_scope='actual_locked_runtime_gate')
    if report.get('reuse_provenance'):
        proof.update({key:report[key] for key in ('reused_checks','reuse_provenance','validation_scope') if key in report})
        proof['evidence_scope']='accepted_checks_reused_with_actual_qpcr_gate'
    return proof


def synthetic_status(payload):
    # No currently validated input contract authenticates biological origin.
    # Preserve original hints for a reviewer; do not derive truth from donor,
    # section, filename, accession, sample counts or fixture-like identifiers.
    hints=[]
    for source in payload['sources']:
        meta=source.get('metadata',{})
        for field in ('synthetic','is_synthetic','data_origin'):
            if field in meta:hints.append(dict(source_kind=source['source_kind'],source_id=source['source_id'],field=field,raw_value=meta[field]))
    return dict(status='unknown',basis='No authenticated biological-origin field in the existing frozen input contract',
                original_metadata_hints=hints,donor_or_filename_inference=False)


def _add_environment(archive, payload, app_root, *, allow_data_only):
    from .settings import (INTERPRETER, engine_code_digest, engine_code_files, engine_lock_digest,
                           uses_bulk_display_runtime, uses_bulk_enrichment_runtime)

    config, identity = payload['config'], payload['identity']
    if uses_bulk_enrichment_runtime(config):
        profile = 'bulk_enrichment'
    elif uses_bulk_display_runtime(config):
        profile = 'bulk_display'
    elif config.get('bulk_model'):
        profile = 'bulk_model'
    else:
        profile = 'standard'
    try:
        proof = environment_proof(identity, **({profile: True} if profile != 'standard' else {}))
        if engine_code_digest() != identity['code_digest'] or engine_lock_digest() != identity['lock_sha256']:
            raise invalid('bio_insights_environment_unavailable', 422)
    except StorageError as error:
        if error.code != 'bio_insights_environment_unavailable':
            raise
        historical = archived_environment(identity, profile)
        if historical is None:
            if allow_data_only:
                return None, [], None
            raise
        proof, code, lock, interpreter = historical.proof, historical.code, historical.lock, historical.interpreter
        for name, content in historical.programs:
            archive.add_bytes(name, content)
    else:
        code = [(path.relative_to(app_root).as_posix(), path.read_bytes()) for path in engine_code_files()]
        lock = (app_root.parent / 'requirements-bio-insights.lock.txt').read_bytes()
        interpreter = INTERPRETER
        archive.add_reproduction_programs(app_root)

    code_files = []
    for relative, content in code:
        name = 'code/app/' + relative
        archive.add_bytes(name, content)
        code_files.append(dict(relative_name=relative, path=name))
    for directory in ('app', 'app/adapters', 'app/domain'):
        name = 'code/' + directory + '/__init__.py'
        if name not in archive.records:
            archive.add_bytes(name, b'')
    archive.add_bytes('code/requirements-bio-insights.lock.txt', lock)
    archive.add_json('environment/runtime-proof.json', proof)
    return proof, code_files, interpreter


class BioInsightReproductionService(BioInsightsStore):
    def _tabular_originals(self,db,project,source,archive):
        from .sources import InsightSourceReader
        if source.get('raw',{}).get('manifest',{}).get('schema_version')!=3:return []
        reader=InsightSourceReader(self.assets);records=[]
        for original in source['raw']['manifest']['source_files']:
            file,metadata,members=reader.original(db,project,original['id'])
            if file['sha256']!=original['sha256'] or file['size_bytes']!=original['size_bytes']:raise invalid()
            member=members['original_file'];name='input/originals/'+file['sha256']+'.bin'
            archive.add_file(name,member['path'],member)
            records.append(dict(processed_version_id=source['source_id'],file_id=file['id'],filename=metadata['filename'],
                role=original['role'],path=name,sha256=file['sha256'],size_bytes=file['size_bytes']))
        return records

    def _processed_source_proof(self,db,project,source,archive):
        from app.adapters.bio_analysis_store import BioAnalysisStore
        bio=BioAnalysisStore(self.assets)
        row,manifest,_=bio.processed_record(db,project,source['source_id'])
        obj=scoped_object(db,project,self.store.user_id,row['manifest_object_id'])
        if obj['sha256']!=source['sha256'] or manifest!=source['metadata']['manifest']:raise invalid()
        name='provenance/'+source['sha256']+'.json'
        archive.add_file(name,bio.objects.path(obj['object_key']),obj)
        # The scientific member named "manifest" may be an inner engine
        # artifact. The source identity is the separately stored formal parent
        # manifest; preserve both exact byte identities without substitution.
        return dict(source_kind=source['source_kind'],source_id=source['source_id'],sha256=source['sha256'],path=name,proof='formal_manifest_bytes')

    def export(self,project,identifier,*,resource=False,allow_data_only=False):
        archive=ReproductionArchive()
        try:
            with self.store.connection() as db:
                row=self.require(db,'bio_resource_versions' if resource else 'bio_insight_result_versions',project,identifier)
                task=self.store.require_task(db,row['task_id'])
                if task['status']!='succeeded' or not row['manifest_object_id']:raise invalid('bio_insight_not_ready',422)
                service=BioInsightsService(self.assets);payload=service.require_sources(db,task,runtime=False)
                formal_manifest,members=checked_members(self,db,project,row,resource=resource)
                app_root = Path(__file__).resolve().parents[2]
                proof, code_files, interpreter = _add_environment(archive, payload, app_root, allow_data_only=allow_data_only)
                current=copy.deepcopy(payload);required={};source_proofs=[];tabular_originals=[]

                def external(member,reason,role,source_id):
                    name='required-resources/'+member['sha256']+'.bin'
                    record=required.setdefault(member['sha256'],dict(path=name,sha256=member['sha256'],size_bytes=member['size_bytes'],roles=[],references=[]))
                    if record['size_bytes']!=member['size_bytes']:raise invalid()
                    if role not in record['roles']:record['roles'].append(role)
                    record['references'].append(dict(source_id=source_id,member_role=member.get('role'),reason=reason))
                    return name

                resource_restricted=resource and row['usage_json']['redistribution_allowed'] is not True
                for source in current['sources']:
                    restricted=resource_restricted or source['source_kind']=='bio_resource_version' and source['metadata']['usage_json']['redistribution_allowed'] is not True
                    for group in (source,source.get('raw',{})):
                        for key,member in group.get('members',{}).items():
                            original=member['path']
                            if restricted:
                                name=external(member,'resource redistribution is not permitted',source['role'],source['source_id'])
                            else:
                                name='input/objects/'+member['sha256']+'.bin'
                                archive.add_file(name,original,member,fmt=member['format'],
                                    table_header='declared' if group is source else 'uninterpreted')
                            member['path']=name
                    if source['source_kind'] in ('bio_resource_version','bio_insight_result_version'):
                        upstream=self.require(db,'bio_resource_versions' if source['source_kind']=='bio_resource_version' else 'bio_insight_result_versions',project,source['source_id'])
                        obj=scoped_object(db,project,self.store.user_id,upstream['manifest_object_id'])
                        if obj['sha256']!=source['sha256']:raise invalid()
                        name='provenance/'+source['sha256']+'.json';archive.add_file(name,self.objects.path(obj['object_key']),obj)
                        source_proofs.append(dict(source_kind=source['source_kind'],source_id=source['source_id'],sha256=source['sha256'],path=name,proof='formal_manifest_bytes'))
                    elif source['source_kind']=='bio_processed_dataset_version':
                        source_proofs.append(self._processed_source_proof(db,project,source,archive))
                        tabular_originals.extend(self._tabular_originals(db,project,source,archive))
                    elif source['source_kind']=='original_file':
                        source_proofs.append(dict(source_kind=source['source_kind'],source_id=source['source_id'],sha256=source['sha256'],path=source['members']['original_file']['path'],proof='original_bytes'))
                    elif source['source_kind']=='external_evidence_version':
                        snapshot=source['metadata']['evidence_snapshot']
                        if digest(snapshot)!=source['sha256']:raise invalid()
                        name='provenance/'+source['sha256']+'.json';archive.add_json(name,snapshot)
                        source_proofs.append(dict(source_kind=source['source_kind'],source_id=source['source_id'],sha256=source['sha256'],path=name,proof='canonical_metadata'))
                    elif source['source_kind']=='research_design_version':
                        if digest(source['metadata'])!=source['sha256']:raise invalid()
                        name='provenance/'+source['sha256']+'.json';archive.add_json(name,source['metadata'])
                        source_proofs.append(dict(source_kind=source['source_kind'],source_id=source['source_id'],sha256=source['sha256'],path=name,proof='canonical_metadata'))
                    elif source['source_kind']=='bio_observation_map_version':
                        source_proofs.append(dict(source_kind=source['source_kind'],source_id=source['source_id'],sha256=source['sha256'],path=source['members']['observation_map']['path'],proof='formal_mapping_bytes'))
                    elif source['source_kind']=='bio_annotation_version':
                        hashes={key+'_sha256':source['members'][key]['sha256'] for key in ('geometry','assignments')}
                        if digest(hashes)!=source['sha256']:raise invalid()
                        source_proofs.append(dict(source_kind=source['source_kind'],source_id=source['source_id'],sha256=source['sha256'],proof='canonical_member_hashes',member_hashes=hashes))
                baseline=[];baseline_source_members={}
                for member in members:
                    if member['role']=='input_snapshot':continue
                    name='result/'+member['key']+'.'+member['format']
                    obj=scoped_object(db,project,self.store.user_id,member['storage_object_id'])
                    path=Path(self.assets.directory)/obj['object_key']
                    if resource_restricted and member['key'] not in ('manifest','methods','recipe'):
                        name=external(member,'resource output redistribution is not permitted',member['role'],identifier)
                    else:archive.add_file(name,path,member,fmt=member['format'])
                    baseline.append({key:member[key] for key in ('key','role','format','sha256','size_bytes')}|{'path':name})
                    baseline_source_members[member['key']]=dict(path=name,**{key:member[key] for key in ('role','format','sha256','size_bytes')})
                archive.add_json('input/payload.json',current)
                if tabular_originals:archive.add_json('input/tabular-originals.json',tabular_originals)
                archive.add_json('provenance/task-input.json',task['input_snapshot'])
                archive.add_json('provenance/formal-manifest.json',formal_manifest)
                render=dict(supported=not resource,exact_original_figure=not resource and row['kind']=='figure')
                if payload['kind']=='bio_candidate' and payload['config'].get('schema_version')==2:
                    render.update(figure_types=['evidence_matrix','evidence_network','evidence_flow'],source_semantics='complete frozen candidate by external evidence cross product; source statements not recomputed; seed1729')
                if payload['kind']=='bio_integration' and payload['config'].get('schema_version')==2:
                    render.update(supported=True,figure_types=['topic_'+payload['config']['method']],source_semantics='immutable topic_plot_data; display only; no scientific recomputation')
                elif payload['kind']=='bio_integration':
                    render.update(figure_types=['integration_network','integration_flow'],source_semantics='complete frozen integration_data nodes and edges; layout seed1729; display-only filter; no statistics recomputation')
                if payload['kind']=='bio_feature_extract':
                    render.update(figure_types=['feature_distribution','feature_scatter'],source_semantics='exact frozen feature_data rows; no sequence or structure re-extraction on render')
                if payload['config'].get('schema_version')==4:
                    render.update(figure_types=['microbiome_composition','microbiome_alpha','microbiome_pcoa'],source_semantics='versioned microbiome raw assay, original count/fraction/percent and complete taxonomy/sample tables',permdisp=dict(center='median',method='eigh',dimensions=0))
                if not resource and proof is not None:
                    if row['kind']=='figure':render_payload=copy.deepcopy(current)
                    else:
                        from .sources import InsightSourceReader
                        fixed=InsightSourceReader(self.assets).resolve(db,project,dict(source_kind='bio_insight_result_version',source_id=identifier,sha256=row['manifest_sha256'],role='result'))
                        fixed['members']=baseline_source_members
                        render_payload=dict(schema_version=1,kind='bio_insight_figure',config=None,identity={**payload['identity'],'offline_render_source_result_id':identifier},
                            sources=[fixed,*copy.deepcopy(current['sources'])])
                    archive.add_json('input/render-payload.json',render_payload)
                package=dict(schema_version=1,kind='bio_insights_reproduction' if proof else 'bio_insights_fixed_data',
                    identity={**payload['identity'],('resource_version_id' if resource else 'result_version_id'):identifier},
                    formal_manifest_sha256=row['manifest_sha256'],task_input_sha256=task['input_digest'],frozen_config_sha256=digest(payload['config']),source_proofs=source_proofs,
                    environment_proof=proof,runtime_identity=proof['runtime_identity'] if proof else None,engine_code_files=code_files,
                    lock_path='code/requirements-bio-insights.lock.txt' if proof else None,interpreter=interpreter,
                    baseline=baseline,render=render if proof else dict(supported=False,exact_original_figure=False),
                    required_resources=list(required.values()),analysis_inputs_self_contained=not bool(required),fully_self_contained=False,
                    external_locked_runtime_required=True,synthetic_status=synthetic_status(payload),real_model_calls=False,real_network_calls=False)
                archive.add_json('required-resources.json',dict(schema_version=1,resources=list(required.values())))
                text=(
                    '# Bio insights offline reproduction / 离线复现\n\n'
                    'verify checks immutable input/output SHA, complete table row counts, code and lock/environment identity; it never computes.\n'
                    'recompute invokes the frozen scientific worker in an independent restricted child. render invokes only the figure renderer; no model fit or enrichment.\n'
                    'Use the matching fixed Linux interpreter/environment recorded in package.json; installing dependencies and supplying restricted resources are manual prerequisites. No network download occurs.\n'
                    'This package does not bundle the interpreter/native runtime and is not claimed fully self-contained. Missing required-resources fail verification/recompute.\n'
                    'Provide each missing file explicitly: --resource SHA256=/absolute/matching/file. Do not replace a resource release or mapping.\n'
                    'Commands (run beside reproduce.py):\n\n'
                    'python reproduce.py verify --manifest-sha256 <response X-Reproducibility-Manifest-SHA256>\n'
                    'python reproduce.py recompute --output /new/empty/attempt\n'
                    'python reproduce.py render --output /new/empty/figures --config /chosen/FigureConfig.json\n\n'
                    'For an exported figure task, render defaults to its exact original config. Other result kinds require explicit result/contrast/term selection. Resource imports have no plot operation.\n'
                    'Outputs must be new directories outside this immutable package. Failed logs and numeric differences remain in that attempt.\n'
                    'For tabular V3 sources, input/tabular-originals.json maps each exact uploaded original to its SHA-verified package path. Prepared matrix/metadata members in input/payload.json are the executable comparison inputs.\n'
                    'P/q absolute tolerance <=1e-10; effect/ES/NES <=1e-8. IDs/direction/counts/NA reasons/original external text are exact.\n'
                    'Synthetic origin is unknown unless authenticated input metadata establishes it; donor labels never establish real biological replication.\n'
                    'Code/tests, successful engineering reproduction and biological validation/user acceptance are distinct.\n')
                if proof is None:
                    text = ('# Frozen scientific data / 固定科学数据\n\n'
                            'The exact execution environment for this version is currently unavailable. '
                            'This ZIP preserves the fixed inputs, results, recipe and recorded code, environment '
                            'and lock hashes. The SHA-256 records in package.json cover the supplied files. '
                            'Use an operator-retained matching runtime to export the executable reproduction package.\n')
                archive.add_bytes('README.md',text.encode('utf-8'))
                handle,manifest_sha=archive.finish(package)
            return dict(file=handle,filename='bio-insights-'+identifier+'-reproduction.zip',manifest_sha256=manifest_sha,
                        analysis_inputs_self_contained=not bool(required),
                        reproduction_state='matched_environment' if proof else 'fixed_data_only')
        except BaseException:
            archive.close();raise

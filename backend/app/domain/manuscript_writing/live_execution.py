"""Frozen-wire v2 execution; raw candidates remain pending and cannot publish."""
from copy import deepcopy
import json
from psycopg.types.json import Jsonb
from app.adapters.task_store import TaskStore, source_conflict
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.service import append_checkpoint
from app.domain.literature.service import digest
from app.domain.model_usage.contracts import CallRequest, ModelPolicy
from app.domain.model_usage.gateway import ModelGateway, ModelGatewayError
from app.domain.model_usage.service import ModelUsageService
from app.domain.report_collections.service import scoped_store
from .authorization import LiveWritingService
from .bundle import validate_bundle
from .context import normalize_sections, NUMBER
from .live_contracts import PreviewRequest, LiveWritingRequest, LiveOutput, WORKFLOW
from .policy import POLICY_VERSION, policy, capabilities
from .live_notice import COMPOSITION_VERSION, update_notice

def require_live_snapshot(task):
    snap=task['input_snapshot']
    try:
        if (set(snap)!={'schema_version','project_id','workflow_version','input','execution','base_snapshot','base_version_id','manuscript_id','prompt_version','policy_version','request_id'}
            or task['task_type']!='manuscript_writing' or task['workflow_version']!=WORKFLOW or snap['workflow_version']!=WORKFLOW
            or type(snap['schema_version']) is not int or snap['schema_version']!=2 or digest(snap)!=task['input_digest']
            or snap['project_id']!=task['project_id'] or snap['request_id']!=task['id'] or snap['policy_version']!=POLICY_VERSION or snap['prompt_version']!='sci-writing-v2'
            or PreviewRequest.model_validate(snap['input']).model_dump(mode='json')!=snap['input']
            or LiveWritingRequest.model_validate(snap['execution']).model_dump(mode='json')!=snap['execution']): raise ValueError()
    except (ValueError,TypeError,KeyError): raise source_conflict() from None
    return snap

def compose_live_candidate(output,snapshot,bundle,call_id,provenance,*,composition_version=COMPOSITION_VERSION):
    if type(composition_version) is not int or composition_version not in (1,COMPOSITION_VERSION):
        raise ValueError('Unsupported candidate composition version')
    output=LiveOutput.model_validate(output).model_dump(mode='json')
    expected=[snapshot['input']['target_section']] if snapshot['input']['mode']=='rewrite_section' else ['title','abstract','introduction','results','discussion','materials_and_methods']
    if [s['id'] for s in output['sections']]!=expected: raise ValueError('Wrong output sections')
    local=bundle['local_manifest'];payload=json.loads(json.loads(bundle['wire_json'])['input'])
    facts={s['alias']:{(f['fact_path'],f['value']) for f in s['facts']} for s in payload['sources']}
    candidate=deepcopy(snapshot['base_snapshot']);sections=normalize_sections(candidate);new={};seen=set()
    for section in output['sections']:
        paragraphs=[]
        if not section['paragraphs'] or section['id']=='title' and len(section['paragraphs'])!=1: raise ValueError('Empty section or invalid title')
        for p in section['paragraphs']:
            if p['id'] in seen: raise ValueError('Duplicate paragraph id')
            seen.add(p['id'])
            if (len(set(p['source_aliases']))!=len(p['source_aliases']) or not set(p['source_aliases'])<=local['sources'].keys()
                or len(set(p['evidence_aliases']))!=len(p['evidence_aliases']) or not set(p['evidence_aliases'])<=local['evidence'].keys()): raise ValueError('Unknown alias')
            for b in p['study_numeric_bindings']:
                if b['source_alias'] not in p['source_aliases'] or (b['fact_path'],b['value']) not in facts[b['source_alias']]: raise ValueError('Unknown exact study fact')
            from app.domain.manuscripts.illustrations import BODY_REFERENCE, check_references, rendered_groups
            reference_issues=check_references(rendered_groups(snapshot['base_snapshot'],[dict(id=p['id'],text=p['text'],origin='model_generated')]),snapshot['input']['output_language'])
            if any(issue['field']==p['id'] for issue in reference_issues): raise ValueError('Unknown figure or table identity')
            # Literature numbers are deliberately pending until exact new-claim evidence review.
            if not p['evidence_aliases']:
                if set(NUMBER.findall(BODY_REFERENCE.sub('',p['text'])))!={b['value'] for b in p['study_numeric_bindings']}: raise ValueError('Unbound study number')
            paragraphs.append(dict(id=p['id'],text=p['text'],origin='model_generated',source_ids=[local['sources'][a] for a in p['source_aliases']],
                citations=[],numeric_bindings=[],suggested_source_aliases=p['source_aliases'],suggested_evidence_aliases=p['evidence_aliases'],study_numeric_bindings=p['study_numeric_bindings'],verification_status='pending'))
        new[section['id']]=dict(id=section['id'],paragraphs=paragraphs)
    candidate['sections']=[new.get(s['id'],s) for s in sections]
    paragraph_ids=[p['id'] for s in candidate['sections'] for p in s['paragraphs']]
    if len(paragraph_ids)!=len(set(paragraph_ids)): raise ValueError('Duplicate paragraph identity across candidate')
    candidate['title']=candidate['sections'][0]['paragraphs'][0]['text']
    candidate['output_language']=snapshot['input']['output_language']
    if snapshot['input']['mode']=='full_draft':
        candidate['keywords']=deepcopy(snapshot['input']['keywords'])
        candidate['acknowledgements']=snapshot['input']['acknowledgements']
    if candidate.get('review_provenance'):
        candidate.setdefault('review_history',[]).append(dict(provenance=candidate.pop('review_provenance'),
            review=candidate.pop('review'),applies_to_current_text=False,status='historical_requires_recheck'))
    candidate['writing_provenance']=dict(schema_version=2,request_id=snapshot['request_id'],bundle_id=bundle['id'],bundle_sha256=bundle['bundle_sha256'],
        model_call_id=call_id,provider_provenance=provenance,verification_status='pending',raw_output=output,raw_output_sha256=digest(output),
        required_reviews=['scientific_claims','study_numeric_facts','complete_language'],base_version_id=snapshot['base_version_id'])
    if composition_version==COMPOSITION_VERSION:
        candidate['writing_provenance']['composition_version']=COMPOSITION_VERSION
        update_notice(candidate,snapshot['input'])
    return candidate

def validate_live_candidate(candidate,snapshot,bundle):
    p=candidate['writing_provenance']
    if p['provider_provenance'] not in ('synthetic_fixture','openai_live'): raise ValueError('Invalid provenance')
    if candidate!=compose_live_candidate(p['raw_output'],snapshot,bundle,p['model_call_id'],p['provider_provenance'],composition_version=p.get('composition_version',1)): raise ValueError('Candidate mismatch')

def parse(response,snapshot,bundle,call_id,provenance):
    if not isinstance(response,dict) or response.get('status')!='completed': raise ValueError('Not completed')
    outputs=response['output']
    if not isinstance(outputs,list) or any(not isinstance(o,dict) or o.get('type') not in ('reasoning','message') for o in outputs): raise ValueError('Invalid output')
    messages=[o for o in outputs if o['type']=='message']
    if len(messages)!=1 or len(messages[0]['content'])!=1: raise ValueError('One output required')
    item=messages[0]['content'][0]
    if item['type']!='output_text' or not isinstance(item['text'],str) or len(item['text'].encode())>250000: raise ValueError('Invalid output text')
    def pairs(items):
        value={}
        for k,v in items:
            if k in value: raise ValueError('Duplicate key')
            value[k]=v
        return value
    return compose_live_candidate(json.loads(item['text'],object_pairs_hook=pairs),snapshot,bundle,call_id,provenance)

def create_production_provider():
    """Read a protected key only at execution time using the established resolver."""
    if not capabilities()['real_calls_enabled']:
        raise StorageError('manuscript_writing_not_authorized','真实写作开关和密钥必须同时配置。',409)
    from app.domain.explanation_policy import explanation_api_key
    from app.adapters.models.openai_responses import OpenAIResponsesProvider
    try: key=explanation_api_key()
    except StorageError:
        raise StorageError('manuscript_writing_not_authorized','真实写作密钥尚未正确配置。',409) from None
    return OpenAIResponsesProvider(api_key=key)

def execute_live(repository,lease,provider):
    from .execution import wait
    from .service import checkpoint
    from app.domain.literature_assistance.service import last_call
    from app.domain.tasks.errors import classify_read_error
    with repository.connection() as db:
        task=repository.require_lease(db,lease);repository.require_owner(db,task);snapshot=require_live_snapshot(task)
        service=LiveWritingService(scoped_store(task['user_id'],repository.config,repository.assets.directory))
        checkpoint(db,task);call=last_call(db,task['id'])
        if call and (call.get('provider_response_id') or call['status'] in ('submitting','submission_unknown')):
            # A changed base blocks publication, but cannot strand an already
            # submitted response or its held budget. Keep the original identity.
            service.writing.row(db,task['project_id'],snapshot['manuscript_id'],task['id'])
        else: service.writing.assert_current(db,task)
        bundle=service.bundle(db,task['project_id'],snapshot['execution']['bundle_id'])
    if call and not call.get('provider_response_id') and call['status'] in ('submitting','submission_unknown'):
        return wait(repository,lease,'submission_unknown','model_submission_unknown')
    provenance='synthetic_fixture' if repository.config.environment=='test' else 'openai_live'
    owned=False
    if provider is None:
        if repository.config.environment=='test' or not capabilities()['real_calls_enabled']:
            return wait(repository,lease,'confirmation_required','manuscript_writing_not_authorized')
        provider=create_production_provider();owned=True
    gateway=ModelGateway(ModelUsageService(task['user_id'],repository.config),provider)
    try:
        if call and call.get('provider_response_id'): output=gateway.refresh(call['id'])
        else:
            request=CallRequest(task_id=task['id'],expected_task_revision=task['revision'],call_key='manuscript-writing-v2',input_digest=bundle['gateway_digest'],policy=ModelPolicy.model_validate(bundle['policy_json']),input_token_allowance=bundle['input_token_allowance'])
            output=gateway.submit_frozen_writing(request,wire_json=bundle['wire_json'],execution_lease=lease)
    except ModelGatewayError as exc:
        with repository.connection() as db: call=last_call(db,task['id'])
        if call and not call.get('provider_response_id') and call['status'] in ('submitting','submission_unknown'): return wait(repository,lease,'submission_unknown','model_submission_unknown')
        if exc.code=='model_receipt_persistence_failed': return None
        return repository.retry_failure(lease,classify_read_error(exc.code,exc.status_code))
    finally:
        if owned: provider.close()
    call,response=output['call'],output.get('response')
    if not call.get('provider_response_id'): return wait(repository,lease,'submission_unknown','model_submission_unknown')
    if isinstance(response,dict) and response.get('status') in ('queued','in_progress'): return repository.defer(lease)
    with repository.connection() as db:
        mismatched=db.execute("SELECT 1 FROM usage_events WHERE call_id=%s AND reason_code='model_mismatch' LIMIT 1",(call['id'],)).fetchone()
    if mismatched: return repository.fail(lease,'manuscript_writing_invalid')
    try: candidate=parse(response,snapshot,bundle,call['id'],provenance)
    except (ValueError,KeyError,TypeError): return repository.fail(lease,'manuscript_writing_invalid')
    with repository.connection(write=True) as db:
        task=repository.require_lease(db,lease);repository.require_owner(db,task);service.writing.assert_current(db,task)
        previous=checkpoint(db,task)
        if previous['next_node'] not in ('check','await_confirmation'): raise source_conflict()
        changed=db.execute('UPDATE manuscript_writing_requests SET candidate_json=%s,candidate_sha256=%s,updated_at=%s WHERE task_id=%s AND candidate_json IS NULL',(Jsonb(candidate),digest(candidate),repository.now(db),task['id']))
        if changed.rowcount!=1: raise source_conflict()
        append_checkpoint(db,task,'done','done',previous['state_json'],previous);repository._finish(db,task,'succeeded',None)
        return TaskStore.public_task(task)

"""Deterministic offline evidence, reused only with identical dependency basis."""
from uuid import uuid4
from psycopg.types.json import Jsonb

from app.domain.admin_configuration import catalog
from app.domain.model_usage.contracts import ModelPolicy
from app.core.exceptions import StorageError

DEPENDENCIES={'models':('prompts',),'prompts':('models',)}


def domain_errors(domain,bundle):
    value=bundle[domain];errors=[]
    baseline,_=catalog.defaults()
    if domain=='models':
        from app.domain.explanation_policy import validate_execution_policy as explanation
        from app.domain.analysis_recommendation.policy import validate_execution_policy as recommendation
        from app.domain.plot_policy import validate_execution_policy as plot
        for name in ('explanation','recommendation','plot','writing','literature'):
            entry=value[name]
            if entry is None:continue
            execution=entry['execution'];policy=execution['policy']
            if policy['model'] not in catalog.INSTALLED_MODELS:errors.append(name+'_model_not_installed')
            try:
                parsed=ModelPolicy.model_validate(policy)
                if name in ('explanation','recommendation','plot'):
                    {'explanation':explanation,'recommendation':recommendation,'plot':plot}[name](execution)
                elif name=='writing':
                    if (parsed.model!='gpt-5.4-2026-03-05' or parsed.tools or parsed.prompt_version!='sci-writing-v2'
                            or parsed.output_format!='manuscript_writing_v2'):
                        raise ValueError('Unsupported writing wire contract')
                elif (parsed.model!='gpt-6.1-sol' or parsed.tools or parsed.prompt_version!='literature_assistance_v1'
                        or parsed.output_format!='text'):
                    raise ValueError('Unsupported literature contract')
            except (ValueError,TypeError,StorageError):
                errors.append(name+'_incompatible_policy')
            ceiling=baseline['models'][name]
            if name=='literature' and ceiling and policy!=ceiling['execution']['policy']:
                errors.append('literature_fixed_provider_policy')
            if ceiling:
                for field in ('input_token_allowance','task_limit_micro_usd'):
                    if execution[field]>ceiling['execution'][field]:errors.append(name+'_'+field+'_exceeds_deployment')
                if policy['max_output_tokens']>ceiling['execution']['policy']['max_output_tokens']:
                    errors.append(name+'_output_exceeds_deployment')
            elif name!='literature':
                # No deployed policy means no evidence for raising a previously absent budget.
                errors.append(name+'_deployment_policy_missing')
            if entry['price_status']=='synthetic' and entry['price_source']!='synthetic_fixture':errors.append(name+'_price_provenance_mismatch')
            if entry['price_status']=='unverified' and entry['price_verified_on'] is not None:errors.append(name+'_unverified_price_date')
        if value['credential']!=baseline['models']['credential']:errors.append('credential_not_registered')
    elif domain=='ncbi':
        if value['identity']!=baseline['ncbi']['identity']:errors.append('identity_not_registered')
    elif domain=='basic':
        from app.workers.config import concurrency_ceiling
        for field in value:
            ceiling=concurrency_ceiling() if field=='worker_concurrency' else baseline[domain][field]
            if value[field]>ceiling:errors.append(field+'_exceeds_deployment')
    elif domain=='journals':
        if value['default_count']>value['max_count']:errors.append('default_count_exceeds_max_count')
    elif domain=='schools':
        labels=[alias['text'].casefold() for alias in value['heading_aliases']]
        if len(labels)!=len(set(labels)):errors.append('duplicate_heading_alias')
    return errors


def validate(db,version,user_id):
    capability=catalog.capability_version();domains={}
    for domain in catalog.DOMAINS:
        scope=(domain,)+DEPENDENCIES.get(domain,())
        basis=catalog.digest({name:version['bundle'][name] for name in scope})
        previous=db.execute('''SELECT id,result FROM admin_configuration_validations
            WHERE validator_version=%s AND capability_version=%s
              AND result->'domains'->%s->>'basis_sha256'=%s
              AND result->'domains'->%s->>'status'='passed'
            ORDER BY created_at DESC,id DESC LIMIT 1''',
            (catalog.VALIDATOR_VERSION,capability,domain,basis,domain)).fetchone()
        errors=[] if previous else domain_errors(domain,version['bundle'])
        domains[domain]=dict(status='failed' if errors else 'passed',errors=errors,
            mode='reused' if previous else 'validated',basis_sha256=basis,
            reused_validation_id=previous['id'] if previous else None,scope=list(scope))
    result=dict(id=str(uuid4()),version_id=version['id'],sha256=version['sha256'],
        validator_version=catalog.VALIDATOR_VERSION,capability_version=capability,
        status='failed' if any(row['errors'] for row in domains.values()) else 'passed',
        domains=domains,real_connectivity='not_tested',
        checked=['closed_schema','installed_capabilities','business_policy_compatibility','bounded_limits'],
        not_checked=['network','provider_output','official_price_verification','real_material_acceptance'])
    db.execute('''INSERT INTO admin_configuration_validations
        (id,version_id,sha256,validator_version,capability_version,status,result,created_by)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',
        (result['id'],version['id'],version['sha256'],catalog.VALIDATOR_VERSION,capability,result['status'],Jsonb(result),user_id))
    return result

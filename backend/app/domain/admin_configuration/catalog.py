"""Installed defaults and safe provenance; never expose paths or credential values."""
import hashlib
import json

from app.core.config import ExcelSettings, local_config
from app.core.paths import BACKEND_ROOT
from app.domain.admin_configuration.contracts import Basic, Bundle, CATEGORIES, Entry, PlotEntry, parse_bundle

VALIDATOR_VERSION = 'admin-config-validator-v1'
DOMAINS = ('models','prompts','ncbi','basic','journals','schools','review')
INSTALLED_MODELS = ('gpt-5.4-2026-03-05','gpt-5.6-sol','gpt-6.1-sol')


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def digest(value): return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def defaults():
    from app.domain.manuscript_writing.policy import installed_policy as policy, MAX_INPUT, TASK_CAP
    from app.domain.literature_live.batch06 import MODEL_POLICY
    from app.domain.review_rounds.planning import propose
    from app.domain.explanation_policy import _small_text
    config=local_config()
    models={'writing':dict(execution=dict(policy=policy().model_dump(mode='json'),
        input_token_allowance=MAX_INPUT,task_limit_micro_usd=TASK_CAP),price_source='installed_code')}
    models['literature']=dict(execution=dict(policy=MODEL_POLICY,input_token_allowance=12000,
        task_limit_micro_usd=250000),price_source='installed_code')
    sources={domain:'installed_code' for domain in DOMAINS}
    # Only deployment-selected known files, never user-provided paths; allowlist parse before storage.
    for name,key in [('explanation','PAPERASSIST_EXPLANATION_POLICY_FILE'),
                     ('recommendation','PAPERASSIST_ANALYSIS_RECOMMENDATION_POLICY_FILE'),
                     ('plot','PAPERASSIST_PLOT_POLICY_FILE')]:
        if not config.get(key): continue
        try:
            raw=json.loads(_small_text(config[key],65536))
            entry=(PlotEntry if name=='plot' else Entry).model_validate(dict(execution=raw,price_source='deployment_policy'))
            models[name]=entry.model_dump(mode='json')
            sources['models']='installed_code_and_filtered_deployment'
        except (OSError,ValueError,TypeError):
            # Invalid deployment data stays unconfigured; never persist or echo it.
            continue
    if config.get('OPENAI_API_KEY') or config.get('OPENAI_API_KEY_FILE'):
        models['credential']=dict(alias='openai-default',revision='deployment-v1')
    basic=Basic().model_dump()
    # Deployment-only baseline; request/task getters may consume an active bundle.
    current=ExcelSettings(**{name:config['EXCEL_'+name.upper()] for name in ExcelSettings.model_fields
                             if 'EXCEL_'+name.upper() in config}).model_dump()
    for key,value in current.items():basic[key]=min(basic[key],value)
    if any(basic[k]!=Basic().model_dump()[k] for k in current):sources['basic']='filtered_deployment'
    ncbi={}
    if config.get('PAPERASSIST_NCBI_CONFIG_FILE') or config.get('PAPERASSIST_NCBI_EMAIL'):
        ncbi['identity']=dict(alias='ncbi-default',revision='deployment-v1')
    words=[['experiment','实验','试验'],['statistic','统计','p value','sample size'],['figure','table','图','表'],
        ['method','方法'],['reference','citation','文献','引用'],['format','格式'],
        ['structure','结构','section order','before results'],['wording','grammar','措辞','语法','压缩','局限性'],[]]
    notes={key:propose({'id':'catalog'},1,{'text':(keywords[0] if keywords else 'unknown'),'original_number':'','location':{}})['plan']
           for key,keywords in zip(CATEGORIES,words)}
    bundle=Bundle.model_validate(dict(models=models,prompts={},ncbi=ncbi,basic=basic,journals={},schools={},
        review=dict(category_order=CATEGORIES,keywords=dict(zip(CATEGORIES,words)),handling_notes=notes))).model_dump(mode='json')
    return parse_bundle(bundle),sources


def capabilities():
    # Changes to installed rules invalidate evidence; deployment capabilities have safe identity only.
    baseline,_=defaults()
    from app.workers.config import concurrency_ceiling
    basic_ceiling={**baseline['basic'],'worker_concurrency':concurrency_ceiling()}
    installed_files=('domain/admin_configuration/contracts.py','domain/admin_configuration/validation.py',
        'domain/admin_configuration/catalog.py','domain/literature_live/batch06.py',
        'domain/explanation_policy.py','domain/analysis_recommendation/policy.py','domain/manuscript_writing/policy.py',
        'domain/manuscript_writing/bundle.py','domain/plot_policy.py','domain/literature_assistance/execution.py',
        'domain/journals/recommendation.py','domain/journals/format_rules.py','domain/review_rounds/planning.py',
        'adapters/school_template_parser.py','domain/school_templates/service.py',
        'core/config.py','adapters/ncbi.py','domain/literature/service.py','domain/literature/execution.py',
        'domain/file_batches.py','domain/datasets/service.py','domain/admin_configuration/legacy.py','domain/tasks/waits.py',
        'api/upload_limit.py','api/excel.py','api/projects.py','api/file_batches.py',
        'domain/admin_configuration/model_consumption.py','domain/manuscript_writing/frozen.py',
        'domain/manuscript_writing/authorization.py','domain/manuscript_writing/live_execution.py',
        'domain/tasks/service.py','domain/tasks/explanation_execution.py','domain/tasks/boxplot_execution.py',
        'domain/tasks/recommendation_execution.py','domain/analysis_recommendation/service.py',
        'domain/figure_workbench/tasks.py','domain/figure_workbench/execution.py',
        'domain/figure_workbench/prompts.py','domain/figure_workbench/explanations.py',
        'domain/external_material.py','domain/literature_assistance/service.py','domain/model_usage/gateway.py',
        'adapters/models/openai_responses.py',
        'domain/admin_configuration/rule_consumption.py','domain/admin_configuration/rule_legacy.py',
        'domain/journals/configuration.py','domain/journals/service.py','domain/journals/contracts.py',
        'domain/journals/execution.py','domain/journals/guides.py','domain/journals/format_service.py',
        'domain/journals/adaptation_service.py','domain/school_templates/execution.py',
        'adapters/school_template_process.py','adapters/school_template_process_child.py',
        'domain/review_rounds/service.py','domain/review_rounds/execution.py','domain/review_rounds/grounded.py',
        'domain/review_rounds/revisions.py','domain/review_rounds/documents.py','domain/review_rounds/document_contracts.py',
        'domain/review_rounds/document_exports.py','domain/manuscripts/service.py','domain/pdf_exports/service.py',
        'domain/manuscripts/school_changes.py','domain/journals/display.py','adapters/review_docx.py')
    installed_sources={name:hashlib.sha256((BACKEND_ROOT/'app'/name).read_bytes()).hexdigest() for name in installed_files}
    return dict(contract='admin-configuration-v1',models=list(INSTALLED_MODELS),tools=['code_interpreter'],
        installed_sources=installed_sources,
        # Every business validator ceiling and cross-business budget default participates.
        # This includes installed writing/literature policies, not just deployment files.
        model_baseline=baseline['models'],
        ncbi_identity=baseline['ncbi']['identity'],basic_ceiling=basic_ceiling)


def capability_version(): return digest(capabilities())


def metadata():
    bundle,sources=defaults()
    from app.domain.journals.configuration import source_directory
    from app.workers.config import concurrency_ceiling
    return dict(default_bundle=bundle,sources=sources,schema=Bundle.model_json_schema(),
        capability_version=capability_version(),validator_version=VALIDATOR_VERSION,
        effects=dict(models='new_task',prompts='new_task',ncbi='new_task',basic='new_task',journals='new_task',schools='new_task',review='new_round'),
        field_effects={'basic.max_upload_bytes':'new_request','basic.worker_concurrency':'worker_restart',
                      'models.real_calls_enabled':'readonly','ncbi.enabled':'readonly','prompts.writing_instruction':'new_preview_bundle'},
        restart_required={'basic.worker_concurrency':True,**{'basic.'+field:False for field in ExcelSettings.model_fields},
                          **{'ncbi.'+field:False for field in ('identity','interval_seconds','cache_ttl_seconds','timeout_seconds')}},
        field_readonly={'basic.worker_concurrency':False,'ncbi.enabled':True,'models.literature.execution.policy':True},
        effective_ranges={'basic.worker_concurrency':{'minimum':1,'maximum':concurrency_ceiling(),'unit':'processes'},**{'basic.'+field:{'minimum':1,'maximum':bundle['basic'][field],
            'unit':{'max_upload_bytes':'bytes','max_uncompressed_bytes':'bytes','max_sheets':'sheets',
                    'max_rows':'rows','max_columns':'columns','max_cells':'cells'}[field]}
            for field in ExcelSettings.model_fields}},
        limit_policy={'basic':'min(active, deployment, tested_ceiling) for new requests/tasks; frozen tasks keep snapshots',
                      'worker_concurrency':{'default':1,'ceiling':concurrency_ceiling(),'editable':True,'effect':'worker_restart'},
                      'ncbi_enabled':'deployment gate first; bound enabled=false blocks real transport'},
        installed=dict(models=list(INSTALLED_MODELS),tools=['code_interpreter'],school_formats=['docx'],
            journal_sources=source_directory(),journal_rules=['journal_recommendation_v1','journal-format-v1'],
            review_documents=['review-documents-v1'],school_parsers=['school-template-openxml-v1'],
            workflows=[dict(id='installed-v1',editable=False,nodes=['material','policy','authorization','admission','provider','validation'])],
            templates=['sci-writing-v1','sci-writing-v2','literature_assistance_v1',
                       'analysis_explanation_v1-v4','analysis_recommendation_v1-v5','openai_figure_workbench_v1-v3','figure_explanation_v1-v4'],
            business_constraints={'recommendation':{'model':'gpt-5.6-sol','task_limit_micro_usd':500000,'tools':[]},
                'writing':{'model':'gpt-5.4-2026-03-05','prompt_version':'sci-writing-v2','output_format':'manuscript_writing_v2','tools':[]},
                'literature':{'model':'gpt-6.1-sol','prompt_version':'literature_assistance_v1','output_format':'text','tools':[],
                              'real_provider_policy':'fixed_batch06_manifest','policy_editable':False,
                              'instruction_effect':'new_task_exact_manifest_required','real_connectivity':'not_tested'},
                'plot':{'tools':['code_interpreter'],'output_format':'text'},'explanation':{'tools':[]}},
            school_quality_rules=['source_preservation','conflict_confirmation','unsupported_visible'],
            supported_schools=[],school_support_status='requires_real_material_acceptance'),
        real_connectivity='not_tested')

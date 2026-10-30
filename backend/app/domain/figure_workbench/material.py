"""Minimal independent plotting input and local expected-answer separation."""
from copy import deepcopy
import re
import math
from app.domain.external_processing import digest
from app.domain.figure_workbench.contracts import FigureConfig,RENDERER
from app.core.exceptions import StorageError

NAMES={'zh-CN':{'line':'折线图','bar':'柱状图','violin':'小提琴图'},'en':{'line':'Line plot','bar':'Bar chart','violin':'Violin plot'}}

def projection_material(config,rows,projection,fields=None,*,figure_contract=1):
    from app.domain.figure_workbench.presentation import contract_version
    contract_version({'figure_contract':figure_contract})
    config=FigureConfig.model_validate(config).model_dump(); kind=config['figure_kind'];style=config['style']; rules=config['projection']; zh=config['language']=='zh-CN'
    fields=fields or {};aliases=style['aliases']
    def field(column):
        info=fields.get(column,{})
        name=aliases.get(column,info.get('name',column or ''))
        unit=info.get('unit','')
        if isinstance(unit,dict): unit=unit.get('value') or ''
        return name+(' ('+unit+')' if unit else '')
    audit=projection['audit'];n=audit['valid_n'];excluded=audit['excluded_n']
    caption=(f'描述性投影：有效记录 {n}，排除 {excluded}；记录不等于独立人数。' if zh else f'Descriptive projection: {n} valid records, {excluded} excluded; records need not be independent participants. ')
    if kind=='line': caption+=('已知时点缺失值断线，不插值；重复值规则：'+rules['aggregation'] if zh else 'Known missing values break lines; no interpolation. Duplicate rule: '+rules['aggregation'])
    elif kind=='bar': caption+=('比例分母为确认类别范围内的组内有效记录；均值误差线仅为样本SD。' if zh else 'Proportions use valid within-group records in confirmed categories; mean error bars only show sample SD.')
    else: caption+=('等权高斯核密度、Scott带宽；截于观测范围且不重归一，各组共用密度宽度比例。' if zh else 'Equal-weight Gaussian KDE, Scott bandwidth; truncated to observed range without renormalization; shared density-to-width scale.')
    if figure_contract == 4:
        # The audit clause belongs to material; method/limitation clauses belong
        # to presentation v3. Historical captions above remain byte-for-byte.
        caption=(f'描述性投影：有效记录 {n}，排除 {excluded}。' if zh else f'Descriptive projection: {n} valid records, {excluded} excluded.')
    labels={'title':style['title'] or NAMES[config['language']][kind],'x_label':field(rules['x_column'] or rules['category_column'] or rules['group_column']),'y_label':field(rules['y_column']),'caption':caption+(' '+style['caption'] if style['caption'] else '')}
    # Local source row identity and local computed answers are deliberately absent.
    observations=[]
    for row in rows:
        item={'group':row.get('group')}
        keys=('x','y') if kind=='line' else ('category','y') if rules['bar_stat']=='mean' and kind=='bar' else ('category',) if kind=='bar' else ('y',)
        item.update({key:row.get(key) for key in keys})
        if rules.get('group_column') and item['group'] is None and rules['missing_group']=='exclude': continue
        observations.append(item)
    public_rules={k:v for k,v in rules.items() if not k.endswith('_column')}
    public_rules['grouped']=bool(rules.get('group_column'))
    base={'schema_version':5,'figure_kind':kind,'language':config['language'],'plot_config':{'rules':public_rules,'style':{k:v for k,v in style.items() if k not in ('title','caption','aliases')},'numbering_mode':'external'}}
    payload={**base,'labels':labels,'observations':observations}
    expected={**deepcopy(base),**labels,'statistics':{'series':deepcopy(projection['series'])}}
    return payload,expected


def display_labels(snapshot, aliases, *, figure_contract=1):
    """Resolve UI column aliases without changing frozen v1/v2 label semantics."""
    from app.domain.external_processing import default_labels
    labels = default_labels(snapshot, 'boxplot')
    for key in labels:
        if key in aliases: labels[key] = aliases[key]
        elif key.startswith('field:') and key[6:] in aliases: labels[key] = aliases[key[6:]]
    if figure_contract >= 3:
        result = snapshot['result']
        for key, role in (('numeric_name', 'numeric_column'), ('group_name', 'group_column')):
            column = result['selection'].get(role)
            if key in labels and key not in aliases and column in aliases:
                labels[key] = aliases[column]
        if result.get('result_type') == 'regression':
            for i, coefficient in enumerate(result['statistics']['coefficients']):
                key, column = f'effect:{i}', coefficient['column']
                if column in aliases and key not in aliases:
                    labels[key] = aliases[column] + (': ' + coefficient['level']['value'] +
                        ' / reference ' + coefficient['reference']['value'] if coefficient['level'] is not None else '')
    return labels


def legacy_material(assets,project_id,file_id,result,sheet,config,*,saved_expected=None,figure_contract=1):
    from app.domain.external_processing import disclosure_version,freeze_confirmation,source_digest
    from app.domain.artifact_contracts import figure_kind
    kind=figure_kind(result); wanted=config['figure_kind']
    if wanted!=kind and not (wanted=='boxplot' and kind in ('group_boxplot','paired_connected')):
        raise StorageError('task_input_invalid','该图型与已确认统计方法不匹配。',422)
    snapshot={'result':result,'file':assets.file(project_id,file_id),'source':result['source'],'figure':None,'versions':{},'output_language':config['language']}
    labels=display_labels(snapshot,config['style']['aliases'],figure_contract=figure_contract)
    external=freeze_confirmation(snapshot,'boxplot',assets.owner_id,{'version':disclosure_version(snapshot),'confirmed':True,'source_digest':source_digest(snapshot,'boxplot',assets.owner_id),'labels':labels})
    if result.get('result_type')=='correlation':
        from app.domain.correlation.service import load_correlation_input
        from app.domain.correlation_material import build_material
        rows=load_correlation_input(assets,project_id,file_id,result)['rows']; payload,expected=build_material(result,rows,external=external)
    elif result.get('result_type')=='group_comparison':
        from app.domain.comparison.service import load_comparison_input
        from app.domain.comparison_material import build_material
        payload,expected=build_material(result,load_comparison_input(assets,project_id,file_id,result)['groups'],external=external,saved_expected=saved_expected)
    elif result.get('result_type') in ('regression','roc','survival'):
        from app.domain.modeling_material import load_input,build_material
        payload,expected=build_material(result,load_input(assets,project_id,file_id,result)['rows'],external=external)
    else:
        from app.domain.boxplot_material import build_material
        payload,expected=build_material(result,assets.file(project_id,file_id),None,None,external=external,dataset_sheet=sheet,saved_expected=saved_expected)
    for key in ('title','caption'):
        text=re.sub(r'^(?:图\s*1[.．、]?\s*|Figure\s+1[.．]?\s*)','',expected[key])
        if config['style'][key]: text=config['style'][key] if key=='title' else text+' '+config['style'][key]
        payload['labels'][key]=expected[key]=text
    payload['schema_version']=expected['schema_version']=5
    payload['legacy_contract']=2 if result.get('result_type')=='correlation' else 3 if result.get('result_type')=='group_comparison' else 4 if result.get('result_type') in ('regression','roc','survival') else 1
    expected['legacy_contract']=payload['legacy_contract']
    payload['plot_config']=expected['plot_config']={**expected.get('plot_config',{}),'style':{k:v for k,v in config['style'].items() if k not in ('title','caption','aliases')},'numbering_mode':'external'}
    payload.setdefault('language',config['language']);expected.setdefault('language',config['language'])
    payload.setdefault('figure_kind',kind);expected.setdefault('figure_kind',kind)
    # Old descriptive labels may contain local provenance: remove it from both contracts.
    for key in ('analysis_run_id','source_sha256'):payload.pop(key,None);expected.pop(key,None)
    return payload,expected


def verify_manifest(manifest,expected):
    from app.adapters.openai_plot import plot_differences
    from app.domain.plot_response import PlotVerificationError,bounded_manifest
    def compare(actual,wanted,**kwargs):
        try:return plot_differences(actual,wanted,**kwargs)
        except (OverflowError,RecursionError):
            return [{'path':'','expected':'[bounded finite manifest]','actual':'[numeric or depth limit]','reason':'resource_limit'}]
    legacy=expected.get('legacy_contract')
    # Schema 5 wraps, but does not weaken, the original method's numerical contract.
    if legacy in (1,2,3,4):
        actual={**manifest,'schema_version':legacy} if isinstance(manifest,dict) else manifest
        wanted={**expected,'schema_version':legacy}
        differences=compare(actual,wanted,legacy=legacy==1,strict_manifest=True)
        if not isinstance(manifest,dict) or type(manifest.get('schema_version')) is not int or manifest['schema_version']!=5:
            differences.append({'path':'schema_version','expected':5,'actual':None,'reason':'value'})
    else:differences=compare(manifest,expected,strict_manifest=True)
    kind=expected.get('figure_kind');rules=expected.get('plot_config',{}).get('rules',{})
    derived_fields=({'y'} if rules.get('aggregation')=='mean' else set()) if kind=='line' else (
        {'value','sd'} if kind=='bar' and rules.get('bar_stat') in ('mean','proportion') else
        {'bandwidth','grid','density','q1','median','q3'} if kind=='violin' else set())
    def semantic_numbers(actual,wanted,path=()):
        if len(differences)>=100:return
        if isinstance(wanted,dict) and isinstance(actual,dict):
            for key in wanted.keys() & actual.keys():semantic_numbers(actual[key],wanted[key],(*path,key))
        elif isinstance(wanted,list) and isinstance(actual,list):
            for index,(a,b) in enumerate(zip(actual,wanted)):semantic_numbers(a,b,(*path,str(index)))
        elif type(wanted) in (int,float):
            # Identity values and copied configuration never use floating tolerances.
            if legacy and path[0] not in ('plot_config','display_groups'):return
            metric=next((part for part in reversed(path) if not part.isdigit()),'')
            derived=not legacy and path[:2]==('statistics','series') and metric in derived_fields
            try:
                if derived and type(wanted) is float:
                    valid=type(actual) in (int,float) and math.isfinite(actual) and math.isclose(actual,wanted,rel_tol=1e-10,abs_tol=0.)
                else:valid=type(actual) is type(wanted) and actual==wanted
            except (OverflowError,ValueError):valid=False
            if not valid:differences.append({'path':'.'.join(path),'expected':'[exact identity or relative numerical value]','actual':'[different value]','reason':'identity_or_number'})
    semantic_numbers(manifest,expected)
    if differences: raise PlotVerificationError(differences,bounded_manifest(manifest),{})

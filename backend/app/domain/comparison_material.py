"""One comparison figure from provenance-checked local numeric observations."""
from copy import deepcopy
import math

from app.core.exceptions import StorageError
from app.domain.artifact_contracts import artifact_language, figure_kind
from app.domain.descriptive import summarize


def build_material(result, groups, *, external=None, saved_expected=None):
    from app.domain.external_material import contract_labels
    from app.domain.boxplot import plot_data
    if external is None:
        raise StorageError('task_source_conflict', '比较绘图必须先确认本次外发标签与必要数值范围。', 409)
    labels=contract_labels(result,None,external,'boxplot')
    statistics=result['statistics']
    if (not isinstance(groups,list) or len(groups)!=len(result['groups'])
            or [len(group) if isinstance(group,list) else -1 for group in groups]!=statistics['sample_sizes']
            or any(len(group)<3 or any(type(value) not in (int,float) or not math.isfinite(value) for value in group) for group in groups)
            or (len(groups[0]) if statistics['design']=='paired' else sum(map(len,groups)))>10000):
        raise StorageError('result_mismatch','比较绘图数值与已保存结果不一致。',409)
    from app.domain.statistics_execution.verification import should_recompute
    if not should_recompute() and saved_expected is None:
        raise StorageError('task_source_conflict','数值投影必须由隔离 Worker 准备。',409)
    summaries=[summarize(group) for group in groups] if should_recompute() else [item['statistics'] for item in result['groups']]
    from app.domain.comparison.service import statistics_match
    recomputed=[{'label':saved['label'],'statistics':summary} for summary,saved in zip(summaries,result['groups'])]
    if not statistics_match(result['groups'],recomputed,summaries=True):
        raise StorageError('result_mismatch','比较绘图分组汇总与已保存结果不一致。',409)
    # Local verification accepts only the same declared platform tolerance, and
    # drawing expectations retain the original frozen result values.
    summaries=[saved['statistics'] for saved in result['groups']]
    variables=[{**variable,'name':labels['field:'+variable['column']],'unit':labels['unit:'+variable['column']]}
               for variable in result['variables']]
    language,kind=artifact_language(result),figure_kind(result)
    paired=kind=='paired_connected'
    if paired and (len(groups)!=2 or len(groups[0])!=len(groups[1]) or variables[0]['unit']!=variables[1]['unit']):
        raise StorageError('task_source_conflict','配对图的两次测量必须同单位并保持完整对。',409)
    names=[labels[f'group:{index}'] for index in range(len(groups))]
    unit=variables[0]['unit'] or ('单位未填写' if language=='zh-CN' else 'unit not specified')
    count=statistics['sample_sizes'][0] if paired else result['check']['valid_count']; excluded=result['check']['excluded_count']
    if language=='en':
        title='Figure 1. '+('Paired measurements' if paired else variables[0]['name']+' group comparison')
        caption=(f'Figure 1. {count} complete pairs; {excluded} excluded source rows. '
            'Each anonymous connection links the same complete pair in the confirmed measurement order. '
            f'Difference direction: {names[0]} - {names[1]}. ' if paired else
            f'Figure 1. {count} included observations; {excluded} excluded source rows. '
            'Groups retain confirmed order. Boxes show Q1-Q3 and median; quantiles use (n-1)p linear interpolation. '
            'Whiskers reach extreme observed values within inclusive 1.5*IQR fences; hollow points are outliers. ')
        caption+='No imputation, deduplication or outlier removal. n is counted independently from plotting values. Inferential results are recorded locally and are not displayed in this figure.'
        text={'title':title,'x_label':'Measurement' if paired else 'Group','y_label':f'{variables[0]["name"]} ({unit})','caption':caption}
    else:
        title='图 1. '+('两次配对测量连接图' if paired else variables[0]['name']+'组间箱线图')
        caption=(f'图 1. 纳入 {count} 个完整对，排除 {excluded} 行原始记录。每条匿名连接线对应同一完整对，保持已确认测量顺序；差值方向：{names[0]} − {names[1]}。' if paired else
            f'图 1. 纳入 {count} 条观察，排除 {excluded} 行原始记录；分组按已确认顺序展示。箱体为 Q1–Q3，中线为中位数；分位数按 (n−1)p 线性插值，须端为含边界的 1.5×IQR 范围内最远实际观测，空心点为范围外观测。')
        caption+='未插补、去重或剔除离群值。n 根据绘图数值独立计数；推断结果由本地保存，本图不显示推断标记。'
        text={'title':title,'x_label':'测量顺序' if paired else '分组','y_label':f'{variables[0]["name"]}（{unit}）','caption':caption}
    config={'inference_displayed':False,'outliers_removed':False,'group_order':'confirmed'}
    if paired: config.update(paired_direction='before_minus_after',connection_basis='anonymous_complete_pairs')
    else: config.update(whisker_iqr_multiplier=1.5,quantile_method='linear_inclusive')
    base={'schema_version':3,'figure_kind':kind,'language':language,'variables':variables,'plot_config':config}
    metrics=('n','mean','std','min','q1','median','q3','max','iqr')
    expected={**deepcopy(base),**text,'statistics':{'sample_sizes':[len(group) for group in groups]},
              'groups':[{'label':name,'statistics':{key:summary[key] for key in metrics}} for name,summary in zip(names,summaries)]}
    payload={**deepcopy(base),'labels':text}
    if paired:
        payload.update(groups=[{'label':name} for name in names],paired_values=[[left,right] for left,right in zip(*groups)])
        difference=summarize([left-right for left,right in zip(*groups)]) if should_recompute() else saved_expected['paired_summary']['difference']
        expected['paired_summary']={'n_pairs':len(groups[0]),'difference':{key:difference[key] for key in metrics}}
    else:
        payload['groups']=[{'label':name,'values':deepcopy(values)} for name,values in zip(names,groups)]
        # Reuse the frozen inclusive box calculation, with only confirmed labels.
        synthetic={**{key:result[key] for key in ('id','file_id','source_sha256','setup_revision')},
                   'numeric_name':variables[0]['name'],'group_name':'Group','selection':{'unit':unit,'sheet_name':''},'check':result['check']}
        expected['series']=plot_data(synthetic,[value for group in groups for value in group],dict(zip(names,groups)))['series'] if should_recompute() else saved_expected['series']
    return payload,expected


def _check_published_figure(assets, project_id, run_id, figure):
    """Compare the stored metadata with the independent copy sealed at publication."""
    from app.adapters.storage import _storage_connection
    from app.domain.storage_governance.service import NAMESPACE
    from app.domain.storage_governance.candidates import read_descriptor

    figure_id = figure['id']
    with _storage_connection(config=assets.db_config) as db:
        row = db.execute('''SELECT t.id,t.project_id,t.user_id,t.task_type,t.input_digest,
                                   r.state,r.candidate_json
            FROM storage_reservations r JOIN tasks t ON t.id=r.task_id
            WHERE r.namespace=%s AND r.project_id=%s AND r.object_key=%s
              AND t.project_id=r.project_id AND t.user_id=r.owner_id
              AND t.task_type='boxplot' AND t.result_figure_id=%s AND t.input_snapshot->'result'->>'id'=%s
              AND r.operation_key='figure-task:' || t.id''',
            (NAMESPACE, project_id, 'figures/' + figure_id + '.png', figure_id, run_id)).fetchone()
    if row is None:
        # Historical figures published before governed storage have no descriptor.
        return
    if row['state'] != 'settled' or row['candidate_json']['source_identity'] != row['input_digest']:
        raise ValueError('Comparison figure publication does not match its task.')
    document = read_descriptor(assets.directory, row)
    if (any(document[key] != row[key] for key in ('id', 'project_id', 'user_id', 'task_type', 'input_digest'))
            or document['candidate']['figure'] != figure):
        raise ValueError('Comparison figure descriptor does not match its task.')


def validate_figure_source(assets,project_id,file_id,result,figure):
    """Check the published drawing and its source without running numeric workers on reads."""
    from app.domain.comparison.service import load_comparison_input
    from app.adapters.openai_plot import plot_differences
    from app.domain.statistics_execution.verification import should_recompute
    try:
        data=load_comparison_input(assets,project_id,file_id,result)
        if not should_recompute():
            _check_published_figure(assets, project_id, result['id'], figure)
        _,expected=build_material(result,data['groups'],external=figure.get('external_processing'),saved_expected=figure)
        expected.update(method={'id':result['statistics']['method'],'design':result['statistics']['design'],'inference_displayed':False},
            engine={'id':'openai_comparison_plot_v3','provider':'openai_code_interpreter'},figure_number=1,
            plan_sha256=result['analysis_plan']['sha256'],verification={'status':'matched'})
        if plot_differences(figure,expected):
            raise ValueError('Comparison drawing summaries changed.')
    except (KeyError,TypeError,ValueError,StorageError) as exc:
        raise StorageError('source_conflict','比较图表与冻结数值或已确认标签不一致。',409) from exc

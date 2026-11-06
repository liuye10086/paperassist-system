"""Bounded counts and explicit axes for the original speckle implementation."""
import numpy as np


def validate_input(counts,samples,labels,conditions,donors,batches,mode,transform,adjust,numerator,denominator):
    values=np.asarray(counts)
    if values.ndim!=2 or values.shape!=(len(samples),len(labels)) or len(labels)<2 or len(set(samples))!=len(samples) or len(set(labels))!=len(labels):
        raise ValueError('propeller_counts_axis_invalid')
    if values.dtype.kind not in 'iu' or np.any(values<0):raise ValueError('propeller_counts_integer_required')
    if sum(map(int,values.ravel()))>20000 or np.any(values.sum(axis=1)==0):raise ValueError('propeller_cell_count_limit')
    if any(not isinstance(x,str) or not x for axis in (samples,labels,conditions,donors) for x in axis) or len(conditions)!=len(samples) or len(donors)!=len(samples):
        raise ValueError('propeller_metadata_axis_invalid')
    levels=list(dict.fromkeys(conditions))
    if len(levels)!=2:raise ValueError('propeller_two_conditions_required')
    denominator=levels[0] if denominator is None else denominator
    numerator=levels[1] if numerator is None else numerator
    if numerator==denominator or set((numerator,denominator))!=set(levels):raise ValueError('propeller_contrast_invalid')
    mode={'donor_paired':'paired','donor_unpaired':'unpaired'}.get(mode,mode)
    if mode not in ('paired','unpaired') or transform not in ('asin','logit'):raise ValueError('propeller_parameters_invalid')
    if batches is not None and (len(batches)!=len(samples) or any(not isinstance(x,str) for x in batches)):raise ValueError('propeller_batch_axis_invalid')
    if adjust and (not batches or any(not x for x in batches) or len(set(batches))<2):raise ValueError('propeller_batch_required')
    if mode=='unpaired':
        if len(set(donors))!=len(donors):raise ValueError('propeller_independent_donors_required')
        if any(conditions.count(c)<3 for c in levels):raise ValueError('propeller_three_donors_required')
    else:
        units=list(dict.fromkeys(donors))
        if len(units)<3 or any(sorted(conditions[i] for i,d in enumerate(donors) if d==u)!=sorted(levels) for u in units):
            raise ValueError('propeller_three_complete_pairs_required')
    return values,mode,numerator,denominator


def decode_result(result,samples,labels):
    answer=dict(status=str(result.rx2('status')[0]),reason=str(result.rx2('reason')[0]) or None,logs=list(map(str,result.rx2('logs'))),rows=[],sample_ids=list(samples),label_ids=list(labels))
    if 'design' not in result.names:return answer
    for key in ('design','contrast','proportions','transformed'):
        array=np.array(result.rx2(key),dtype='float64',copy=True)
        if not np.isfinite(array).all():raise ValueError('propeller_nonfinite_output')
        answer[key]=array.tolist()
    answer['design_columns']=list(map(str,result.rx2('design_columns')))
    if np.asarray(answer['proportions']).shape!=(len(samples),len(labels)) or np.asarray(answer['transformed']).shape!=(len(samples),len(labels)):
        raise ValueError('propeller_result_axis_invalid')
    if answer['status']!='completed':return answer
    answer['robust_effective']=bool(result.rx2('robust_effective')[0])
    statistics=np.asarray(result.rx2('statistics'),dtype='float64')
    testable=np.asarray(result.rx2('testable'),dtype=bool)
    if statistics.shape!=(len(labels),6) or testable.shape!=(len(labels),):raise ValueError('propeller_result_axis_invalid')
    names=['mean_proportion_denominator','mean_proportion_numerator','proportion_ratio','t_statistic','p_value','p_adjust']
    for index,label in enumerate(labels):
        row={'label_id':label,'status':'completed' if testable[index] else 'not_computable','reason':None if testable[index] else 'no_testable_variation'}
        row.update({key:float(value) if np.isfinite(value) else None for key,value in zip(names,statistics[index])})
        row['proportion_difference']=row['mean_proportion_numerator']-row['mean_proportion_denominator']
        row['ratio_status']='finite' if row['proportion_ratio'] is not None else 'undefined_zero_denominator'
        if testable[index] and (any(row[k] is None for k in ('t_statistic','p_value','p_adjust')) or not 0<=row['p_value']<=1 or not 0<=row['p_adjust']<=1):
            raise ValueError('propeller_statistics_invalid')
        answer['rows'].append(row)
    return answer

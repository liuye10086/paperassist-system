"""Local readable missing-metric diagnostics, separate from cloud plotting input."""


def projection_diagnostics(projection,language):
    en=language=='en'
    reasons={
        'insufficient_n_for_sd':'Sample SD is unavailable: fewer than 2 valid records.' if en else '有效记录少于2条，无法计算样本SD。',
        'no_valid_values':'The mean and SD are unavailable: no valid values.' if en else '没有有效数值，无法计算均值或SD。',
    }
    items=[]
    for series in projection.get('series',[]):
        for point in series.get('points',[]):
            if point.get('reason') in reasons:
                parts=[]
                if series.get('group') is not None:parts.append(('Group: ' if en else '组：')+str(series['group']))
                if point.get('category') is not None:parts.append(('Category: ' if en else '类别：')+str(point['category']))
                items.append({'label':' · '.join(parts) or ('All records' if en else '全部记录'),'reason':reasons[point['reason']]})
    return items

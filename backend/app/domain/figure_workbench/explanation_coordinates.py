"""Program-owned complete coordinate spans; no model arithmetic or hidden fields."""
from copy import deepcopy
import json


def line_payload(bundle):
    figure=bundle['figure'];projection=bundle['projection']['result'];zh=figure['language']=='zh-CN'
    facts={}
    def add(key,label,raw,value=None):
        facts[key]={'label':label,'raw':deepcopy(raw),'value':str(raw) if value is None else value}
    add('figure.title','图标题' if zh else 'Figure title',figure['title'])
    add('method.summary','方法与局限' if zh else 'Method and limitations',figure['caption'])
    for name,value in dict(total=projection['audit']['population_n'],valid=projection['audit']['valid_n'],
                           excluded=projection['audit']['excluded_n'],original_n=bundle['result']['check']['valid_count']).items():
        labels={'total':('投影人群记录','Projection population records'),'valid':('投影有效记录','Projection valid records'),
                'excluded':('投影排除记录','Projection excluded records'),'original_n':('原统计有效记录','Original statistical records')}
        add('data.'+name,labels[name][0 if zh else 1],value)
    axes=figure['presentation']['axes']
    def axis(name):
        label=axes[name]['label'];unit=axes[name].get('unit')
        if unit and not label.endswith((' ('+unit+')','（'+unit+'）')):label+=' ('+unit+')'
        return label
    def scalar(value):
        if value is None:return '缺失（断线）' if zh else 'missing (gap)'
        return json.dumps(value,ensure_ascii=False,allow_nan=False) if isinstance(value,str) else str(value)
    groups=[series.get('group') for series in projection['series']]
    def group_label(value):
        if value is None:return '未分组' if zh else 'Ungrouped'
        label=str(value)
        if sum(str(group)==label for group in groups)>1:
            kind=('布尔值' if zh else 'boolean') if type(value) is bool else ('数值' if zh else 'number') if type(value) in (int,float) else ('文本' if zh else 'text')
            label+=' ['+kind+']'
        return label
    separator='；' if zh else '; '
    columns=separator.join([axis('x'),axis('y'),'有效记录数' if zh else 'valid records','缺失记录数' if zh else 'missing records'])
    required=[]
    for index,series in enumerate(projection['series']):
        # Project only already-approved public fields. Internal hashes/IDs never leave the process.
        raw={'group':deepcopy(series.get('group')),'points':[
            {name:deepcopy(point[name]) for name in ('x','y','n','missing')} for point in series['points']]}
        coordinates=' '.join('('+separator.join(scalar(point[name]) for name in ('x','y','n','missing'))+')' for point in raw['points'])
        group=group_label(raw['group'])
        value=(f'分组：{group}；完整有序记录（{columns}）：{coordinates}' if zh else
               f'Group: {group}; complete ordered records ({columns}): {coordinates}')
        key=f'projection.{index}.coordinates';required.append(key)
        add(key,'完整分组坐标事实' if zh else 'Complete grouped coordinate facts',raw,value)
    return {'schema_version':2,'language':figure['language'],'facts':facts,'required_references':{
        'purpose':['figure.title'],'data':['data.total','data.valid','data.excluded','data.original_n'],
        'methods':['method.summary'],'results':required or ['data.valid'],'interpretation':['method.summary'],
        'paper_text':['figure.title','data.valid']}}

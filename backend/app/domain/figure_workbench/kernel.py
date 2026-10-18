"""Bounded descriptive projections. Source coordinates stay in the local audit."""
from datetime import datetime
import math
import statistics
import numpy as np
from scipy.stats import gaussian_kde

TOOL_VERSION='figure_projection_v1'

class ProjectionError(ValueError):
    pass


def _number(value):
    try:valid=type(value) in (int,float) and math.isfinite(value)
    except OverflowError:valid=False
    if not valid:
        raise ProjectionError('invalid_numeric')
    return float(value)


def _category(value):
    if value is None or value=='': return None
    if type(value) not in (str,int,float,bool) or type(value) is str and len(value)>160:
        raise ProjectionError('invalid_category')
    if type(value) in (int,float):return _number(value)
    return value


def _key(value):
    return (type(value).__name__,value)


def _order(values):
    return sorted(values,key=lambda v:(type(v).__name__,str(v)))


def _datetime(value):
    if type(value) is not str or len(value)>160:raise ProjectionError('invalid_datetime')
    try:
        parsed=datetime.fromisoformat(value)
        if parsed.tzinfo is not None:raise ValueError()
    except ValueError:raise ProjectionError('invalid_datetime') from None
    return parsed.isoformat()


def validate_rule_values(rules):
    """The persisted config and the numerical kernel share the same bounded vocabulary."""
    xtype=rules.get('x_type','numeric')
    if xtype not in ('numeric','datetime','ordered'):raise ProjectionError('invalid_x_type')
    for name,limit in (('x_order',100),('expected_x',2000),('included_categories',100)):
        values=rules.get(name,[])
        if not isinstance(values,list) or len(values)>limit:raise ProjectionError('projection_limit')
        keys=set()
        for value in values:
            if name=='expected_x' and xtype=='numeric':value=_number(value)
            elif name=='expected_x' and xtype=='datetime':value=_datetime(value)
            elif _category(value) is None:raise ProjectionError('invalid_category')
            key=_key(value)
            if key in keys:raise ProjectionError('invalid_rule')
            keys.add(key)
    if xtype=='ordered' and any(_key(_category(x)) not in {_key(_category(v)) for v in rules.get('x_order',[])} for x in rules.get('expected_x',[])):
        raise ProjectionError('ordered_x_required')


def compute_projection(kind, rows, rules):
    if kind not in ('line','bar','violin'): raise ProjectionError('unsupported_projection')
    if not isinstance(rows,list) or not 1<=len(rows)<=10000: raise ProjectionError('projection_limit')
    rules={'aggregation':'unique','bar_stat':'count','error_bars':'none','missing_group':'block','x_type':'numeric',**rules}
    validate_rule_values(rules)
    # Spreadsheet CellKind has one numeric kind. Browser JSON may spell the same
    # number as an int; canonicalize only the working rules, never saved config.
    category_rules=(('x_order','expected_x') if kind=='line' and rules['x_type']=='ordered' else ()) + (('included_categories',) if kind=='bar' else ())
    for key in category_rules:rules[key]=[_category(value) for value in rules.get(key,[])]
    validate_rule_values(rules)
    if rules['aggregation'] not in ('unique','mean') or rules['bar_stat'] not in ('count','proportion','mean') or rules['error_bars'] not in ('none','sd') or rules['missing_group'] not in ('block','exclude'): raise ProjectionError('invalid_rule')
    selected=[]; excluded=[]; missing_y=0
    groups={}; all_categories={}
    for row in rows:
        if type(row.get('row')) is not int: raise ProjectionError('invalid_row')
        try:
            if row.get('_group_invalid'):raise ProjectionError('invalid_group')
            group=_category(row.get('group')) if rules.get('group_column') else None
        except ProjectionError:
            if rules['missing_group']=='block':raise ProjectionError('invalid_group') from None
            excluded.append({'row':row['row'],'reason':'invalid_group'});continue
        if rules.get('group_column') and group is None:
            if rules['missing_group']=='block': raise ProjectionError('missing_group')
            excluded.append({'row':row['row'],'reason':'missing_group'}); continue
        current={**row,'group':group}
        if kind=='line':
            x=row.get('x')
            if x is None or x=='': excluded.append({'row':row['row'],'reason':'missing_x'}); continue
            if rules['x_type']=='numeric': x=_number(x)
            elif rules['x_type']=='datetime':
                x=_datetime(x)
            elif rules['x_type']=='ordered':
                order=rules.get('x_order',[])
                x=_category(x)
                if not order or _key(x) not in {_key(v) for v in order}: raise ProjectionError('ordered_x_required')
            else: raise ProjectionError('invalid_x_type')
            current['x']=x
        if kind=='bar':
            category=_category(row.get('category'))
            if category is None: excluded.append({'row':row['row'],'reason':'missing_category'}); continue
            included=rules.get('included_categories',[])
            if included and _key(category) not in {_key(v) for v in included}:
                excluded.append({'row':row['row'],'reason':'category_population_filter'}); continue
            current['category']=category; all_categories[_key(category)]=category
        groups[_key(group)]=group
        if kind!='bar' or rules['bar_stat']=='mean':
            y=row.get('y')
            if y is None:
                missing_y+=1
                if kind!='line': excluded.append({'row':row['row'],'reason':'missing_y'}); continue
            else: current['y']=_number(y)
        selected.append(current); groups[_key(group)]=group
    if not selected and not groups: raise ProjectionError('projection_empty')
    if len(groups)>20 or len(all_categories)>100: raise ProjectionError('projection_limit')
    method={'id':TOOL_VERSION,'kind':kind,'inferential':False,'record_unit':'included_record',**rules}
    output=[]
    for group in _order(list(groups.values())):
        own=[r for r in selected if _key(r['group'])==_key(group)]
        if kind=='line':
            buckets={};x_values={}
            for row in own:
                key=_key(row['x']);x_values[key]=row['x'];buckets.setdefault(key,[]).append(row.get('y'))
            for x in rules.get('expected_x',[]):
                if rules['x_type']=='numeric': x=_number(x)
                elif rules['x_type']=='datetime': x=_datetime(x)
                else:
                    x=_category(x)
                    if _key(x) not in {_key(v) for v in rules.get('x_order',[])}: raise ProjectionError('ordered_x_required')
                key=_key(x);x_values[key]=x;buckets.setdefault(key,[])
            if len(buckets)>2000: raise ProjectionError('projection_limit')
            positions={_key(x):i for i,x in enumerate(rules.get('x_order',[]))}
            order=sorted(buckets,key=(lambda key:positions[key]) if rules['x_type']=='ordered' else lambda key:x_values[key])
            points=[]
            for key in order:
                x=x_values[key];values=buckets[key]; valid=[v for v in values if v is not None]
                if len(values)>1 and rules['aggregation']=='unique': raise ProjectionError('duplicate_x')
                y=statistics.mean(valid) if valid else None
                if y is not None: _number(y)
                points.append({'x':x,'y':y,'n':len(valid),'missing':len(values)-len(valid)})
            output.append({'group':group,'points':points})
        elif kind=='bar':
            points=[]; categories=_order(list(all_categories.values()))
            for category in categories:
                bucket=[r for r in own if _key(r['category'])==_key(category)]
                n=len(bucket); stat=rules['bar_stat']; sd=None; reason=None
                value=n if stat=='count' else n/len(own) if stat=='proportion' else statistics.mean(r['y'] for r in bucket) if n else None
                if stat=='mean' and rules['error_bars']=='sd':
                    sd=statistics.stdev(r['y'] for r in bucket) if n>1 else None
                    if n<2: reason='insufficient_n_for_sd'
                if stat=='mean' and n==0: reason='no_valid_values'
                if value is not None: _number(value)
                if sd is not None: _number(sd)
                points.append({'category':category,'n':n,'denominator':len(own) if stat=='proportion' else None,'value':value,'sd':sd,'reason':reason})
            output.append({'group':group,'points':points})
        else:
            values=[r['y'] for r in own]
            if len(values)<3 or len(set(values))<2: raise ProjectionError('violin_unsupported_group')
            try:
                kde=gaussian_kde(values,bw_method='scott'); grid=np.linspace(min(values),max(values),256)
                density=kde(grid); bandwidth=float(np.sqrt(kde.covariance[0,0])); q1,median,q3=np.quantile(values,[.25,.5,.75],method='linear')
                if not np.isfinite(density).all() or not np.isfinite(grid).all() or not math.isfinite(bandwidth) or bandwidth<=0: raise ValueError()
            except (ValueError,OverflowError,np.linalg.LinAlgError): raise ProjectionError('violin_numeric_range') from None
            output.append({'group':group,'n':len(values),'bandwidth':bandwidth,'min':min(values),'max':max(values),'grid':grid.tolist(),'density':density.tolist(),'q1':float(q1),'median':float(median),'q3':float(q3)})
    if kind=='violin': method.update(kernel='gaussian',bandwidth='scott',grid_points=256,width_scale='shared_density',truncate='observed_range',renormalize=False)
    audit={'population_n':len(rows),'valid_n':sum(r.get('y') is not None for r in selected) if kind!='bar' or rules['bar_stat']=='mean' else len(selected),'excluded_n':len(excluded),'missing_y_n':missing_y,'excluded':excluded,'included_rows':[r['row'] for r in selected]}
    return {'schema_version':1,'tool_version':TOOL_VERSION,'method':method,'audit':audit,'series':output}

"""Parent reconciles full source-derived tables and observed beta statistics."""
import csv,json,math
from pathlib import Path
import numpy as np
from .bio_tabular_process import _ReconciliationWriter

class MicrobiomeWriter(_ReconciliationWriter):
    def __init__(self,items):super().__init__();self.items=items
    def table(self,key,rows,fields=None):
        from itertools import zip_longest
        from app.adapters.bio_engine.manifest import clean
        rows=list(rows);columns=fields or (list(rows[0]) if rows else ['reason'])
        actual=self.items.get(key)
        if not actual or actual['format']!='tsv':raise ValueError('microbiome_table_missing:'+key)
        with Path(actual['path']).open(encoding='utf-8',newline='') as stream:
            reader=csv.DictReader(stream,delimiter='\t')
            if reader.fieldnames!=columns:raise ValueError('microbiome_columns_mismatch:'+key)
            for expected,observed in zip_longest(rows,reader):
                if expected is None or observed is None:raise ValueError('microbiome_row_count:'+key)
                for column in columns:
                    value=clean(expected.get(column));text='' if value is None else json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else str(value)
                    if observed[column]==text:continue
                    if type(value) is not float:raise ValueError('microbiome_cell_mismatch:'+key+':'+column)
                    try:number=float(observed[column])
                    except (ValueError,TypeError):raise ValueError('microbiome_numeric_invalid')
                    if not math.isfinite(number) or not math.isclose(value,number,rel_tol=1e-10,abs_tol=1e-12):raise ValueError('microbiome_numeric_mismatch:'+key+':'+column)
        return super().table(key,rows,fields)

def validate_microbiome(result,items,payload):
    from .bio_insights_engine.microbiome import run_microbiome,distances_ordination
    from app.domain.bio_insights.microbiome_design import prepare_microbiome,key
    from app.domain.bio_insights.microbiome_contracts import MicrobiomeConfig
    config=MicrobiomeConfig.model_validate(payload['config']);beta=None
    if config.beta_inference:
        from scipy.optimize import minimize
        from scipy.stats import f_oneway
        data=prepare_microbiome(config,payload['sources']);distance,eig,coords,positive,total,negative=distances_ordination(data['relative'])
        groups=[data['metadata'][s][config.group_column] for s in data['included']];labels=sorted(set(groups));n=len(groups);k=len(labels)
        indexes=[np.flatnonzero(np.asarray(groups)==g) for g in labels]
        ss_total=float(np.sum(distance**2)/(2*n));ss_within=sum(float(np.sum(distance[np.ix_(idx,idx)]**2)/(2*len(idx))) for idx in indexes)
        perma=(ss_total-ss_within)/(k-1)/(ss_within/(n-k)) if ss_within else None
        dispersion=[]
        for idx in indexes:
            x=coords[idx]
            if x.shape[1]==0:dispersion.append(np.zeros(len(x)));continue
            objective=lambda center:np.linalg.norm(x-center,axis=1).sum()
            solved=minimize(objective,np.median(x,axis=0),method='BFGS',options={'gtol':1e-9})
            dispersion.append(np.linalg.norm(x-solved.x,axis=1))
        disp=float(f_oneway(*dispersion).statistic)
        with Path(items['microbiome_beta']['path']).open(encoding='utf-8',newline='') as stream:raw=list(csv.DictReader(stream,delimiter='\t'))
        if len(raw)!=2:raise ValueError('microbiome_beta_rows')
        beta=[]
        for row,name,purpose,expected in zip(raw,['PERMANOVA','PERMDISP'],['between_group_structure','dispersion_diagnostic'],[perma,disp]):
            stat=float(row['statistic']) if row['statistic'] else None;p=float(row['p_value']) if row['p_value'] else None
            if row['method']!=name or row['purpose']!=purpose or int(row['permutations'])!=config.permutations or int(row['seed'])!=config.seed or int(row['sample_count'])!=n or int(row['group_count'])!=k:raise ValueError('microbiome_beta_contract')
            finite=expected is not None and math.isfinite(expected)
            if finite and (stat is None or not math.isclose(stat,expected,rel_tol=1e-4,abs_tol=1e-5)):raise ValueError('microbiome_beta_statistic_mismatch:'+name)
            if not finite and stat is not None:raise ValueError('microbiome_beta_degenerate_statistic')
            if config.permutations and finite:
                resolution=1/(config.permutations+1)
                if p is None or not resolution<=p<=1 or abs(p/resolution-round(p/resolution))>1e-8:raise ValueError('microbiome_permutation_resolution')
            elif p is not None:raise ValueError('microbiome_unexpected_beta_p')
            beta.append(dict(row_key=key(['beta',name]),method=name,purpose=purpose,status='tested' if finite else 'not_computable',reason=None if finite else 'degenerate_distance_or_dispersion',statistic=stat,p_value=p,permutations=config.permutations,seed=config.seed,minimum_p_resolution=1/(config.permutations+1) if config.permutations else None,sample_count=n,group_count=k,center='median' if name=='PERMDISP' else None,ordination_method='eigh' if name=='PERMDISP' else None))
    writer=MicrobiomeWriter(items);expected=run_microbiome(payload,writer,_validated_beta=beta)
    for member in writer.artifacts:
        if member['format']!='tsv' and any(items[member['key']][k]!=member[k] for k in ('format','size_bytes','sha256')):raise ValueError('microbiome_document_mismatch:'+member['key'])
    if expected['summary']!=result['summary'] or any(result['methods'].get(k)!=v for k,v in expected['methods'].items()):raise ValueError('microbiome_summary_methods_mismatch')

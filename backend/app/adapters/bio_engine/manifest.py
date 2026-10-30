import csv
import hashlib
import io
import json
from pathlib import Path
import numpy as np
from scipy import sparse


def clean(value):
    if isinstance(value,np.ndarray): return clean(value.tolist())
    if isinstance(value,np.generic): return clean(value.item())
    if isinstance(value,float) and not np.isfinite(value): return None
    if isinstance(value,dict): return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [clean(v) for v in value]
    return value


def canonical(value):
    return json.dumps(clean(value),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


class Writer:
    def __init__(self,root): self.root=Path(root);self.artifacts=[]
    def add(self,key,content,fmt,role=None):
        if not key.replace('_','').replace('-','').isalnum(): raise ValueError('invalid_artifact_key')
        path=self.root/(key+'.'+fmt)
        if path.exists(): raise ValueError('output_exists')
        if len(content)>256*1024**2 or len(self.artifacts)>=255 or sum(a['size_bytes'] for a in self.artifacts)+len(content)>512*1024**2:
            raise ValueError('output_budget_exceeded')
        path.write_bytes(content)
        item={'key':key,'path':str(path),'role':role or key,'format':fmt,'size_bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}
        self.artifacts.append(item); return item
    def json(self,key,value): return self.add(key,canonical(value),'json')
    def existing(self,key,path,fmt,role=None):
        path=Path(path)
        if path.parent!=self.root or path.is_symlink() or not path.is_file():raise ValueError('invalid_output_path')
        size=path.stat().st_size
        if size>256*1024**2 or len(self.artifacts)>=255 or sum(a['size_bytes'] for a in self.artifacts)+size>512*1024**2:raise ValueError('output_budget_exceeded')
        digest=hashlib.sha256()
        with path.open('rb') as handle:
            while chunk:=handle.read(1024**2):digest.update(chunk)
        item={'key':key,'path':str(path),'role':role or key,'format':fmt,'size_bytes':size,'sha256':digest.hexdigest()}
        self.artifacts.append(item);return item
    def array(self,key,value):
        if value.dtype.kind=='O' or value.dtype.kind in 'fc' and not np.isfinite(value).all():raise ValueError('invalid_output_array')
        stream=io.BytesIO();np.save(stream,value,allow_pickle=False);return self.add(key,stream.getvalue(),'npy')
    def matrix(self,key,value):
        if not np.isfinite(value.data).all():raise ValueError('nonfinite_output_matrix')
        for suffix,array in [('data',value.data),('indices',value.indices),('indptr',value.indptr)]: self.array(key+'_'+suffix,array)
        self.json(key+'_shape',{'shape':list(value.shape),'dtype':str(value.dtype),'nnz':int(value.nnz)})
    def table(self,key,rows,fields=None):
        stream=io.StringIO(newline=''); rows=list(rows); fields=fields or (list(rows[0]) if rows else ['reason'])
        writer=csv.DictWriter(stream,fields,delimiter='\t',lineterminator='\n');writer.writeheader()
        for row in rows:
            writer.writerow({k:('' if clean(row.get(k)) is None else json.dumps(clean(row[k]),ensure_ascii=False) if isinstance(row.get(k),(dict,list)) else clean(row.get(k))) for k in fields})
        return self.add(key,stream.getvalue().encode(),'tsv','marker_table' if key in {'markers','markers_top'} else 'table')

"""Frozen-statistics projection reproduction; no old model or test is recomputed."""
import hashlib,inspect,json
from . import statistics_projection as projection

def statistics_reproduction_files(sources):
    selected={}
    def visit(source):
        if source.get('source_kind')=='analysis_run':selected[source['source_id']]=source
        for child in source.get('content',{}).get('sources',[]):visit(child)
        for child in source.get('content',{}).get('finding',{}).get('content',{}).get('sources',[]):visit(child)
    for source in sources:visit(source)
    files=[]
    for identifier,source in sorted(selected.items()):
        name='statistics/'+hashlib.sha256(identifier.encode()).hexdigest()[:16]+'/'
        script='import csv,io,json,hashlib\nfrom pathlib import Path\nfrom types import SimpleNamespace\n'
        script+='\n\n'.join(inspect.getsource(f) for f in (projection.leaves,projection.metric_unit,projection.statistics_tables))
        script+='''
root=Path(__file__).resolve().parent
source=json.loads((root/'frozen_source.json').read_text(encoding='utf-8'))
result=source['content']['result']
raw=json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
if hashlib.sha256(raw).hexdigest()!=source['sha256']:raise ValueError('Frozen result SHA differs')
tables,raws=statistics_tables(SimpleNamespace(**source))
output=root/'rebuilt';output.mkdir(exist_ok=True)
for table,raw in zip(tables,raws):
    if hashlib.sha256(raw).hexdigest()!=table['sha256']:raise ValueError('Table SHA differs')
    (output/(table['key']+'.tsv')).write_bytes(raw)
(output/'table_index.json').write_text(json.dumps(tables,ensure_ascii=False,sort_keys=True,indent=2),encoding='utf-8')
print('Verified frozen result and rebuilt '+str(len(tables))+' complete projection tables; no statistical refitting.')
'''
        values={'frozen_source.json':json.dumps(source,ensure_ascii=False,sort_keys=True,indent=2).encode(),
            'result.json':json.dumps(source['content']['result'],ensure_ascii=False,sort_keys=True,indent=2).encode(),
            'rebuild_projection.py':script.encode(),
            'README.txt':('运行 python rebuild_projection.py 可校验冻结结果 SHA，并逐项重建全部结果表/曲线表/审计表。\n此脚本仅复现保存数值的投影，不重新拟合原模型或补造检验/区间。原始XLSX及已确认整理版本以来源SHA和版本ID定位，计算环境/方法/假设保留在result与Methods中。\nRun with Python 3, standard library only. This reproduces saved-result projection, not independent numerical or biological validation.\n').encode('utf8')}
        files.extend(dict(name=name+key,raw=raw) for key,raw in values.items())
    return files

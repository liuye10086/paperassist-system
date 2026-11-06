"""Parent verification of the bounded offline single-cell probe receipt."""
from app.core.exceptions import StorageError


def validate_annotation_result(result,payload):
    """Model similarities are candidates; verify their entire cell/label axes."""
    import csv
    import json
    import math
    from pathlib import Path
    import numpy as np
    try:
        members=payload['processed']['members'];records={m['key']:m for m in result['outputs']}
        axes=json.loads(Path(members['raw_axes']['path']).read_bytes())
        mask=np.load(members['observation_mask']['path'],allow_pickle=False)
        if mask.dtype.kind!='b' or mask.shape!=(len(axes['barcodes']),):raise ValueError()
        cells=[b for b,keep in zip(axes['barcodes'],mask) if keep]
        if not cells or len(cells)>20000 or len(set(cells))!=len(cells):raise ValueError()
        with Path(records['annotation_candidates']['path']).open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream,delimiter='\t'))
        with Path(records['annotation_scores']['path']).open(encoding='utf-8',newline='') as stream:
            reader=csv.DictReader(stream,delimiter='\t');columns=reader.fieldnames;scores=list(reader)
        labels=result['summary']['score_labels']
        if (result['summary']['cells']!=len(cells) or not 1<=len(labels)<=100 or len(set(labels))!=len(labels)
            or columns!=['barcode',*labels] or [r['barcode'] for r in rows]!=cells or [r['barcode'] for r in scores]!=cells):raise ValueError()
        for row,score in zip(rows,scores):
            if (row['candidate_label'] not in labels and row['candidate_label']!='unknown') or (row['pruned_label'] not in labels and row['pruned_label']!='unknown'):raise ValueError()
            if row['pruned_label']!='unknown' and row['pruned_label']!=row['candidate_label']:raise ValueError()
            if not all(math.isfinite(float(row[k])) for k in ('delta_next','delta_median')):raise ValueError()
            if not all(math.isfinite(float(score[label])) for label in labels):raise ValueError()
        return dict(cells=len(cells),labels=len(labels),candidate_only=True)
    except (KeyError,ValueError,TypeError,OSError,IndexError):
        raise StorageError('bio_output_invalid','参考注释输出与父细胞或候选分数轴不一致。',422) from None


def validate_single_cell_probe(value):
    try:
        if (type(value) is not dict or set(value)!={'schema_version','checks','counts','raw_axis_features'} or type(value['schema_version']) is not int or value['schema_version']!=1 or value['checks']!={'h5ad_axes':True,'counts_equivalence':True,'cell_aggregation':True,'nonspatial_dispatch':True} or any(type(v) is not bool for v in value['checks'].values()) or value['counts']!={'cells':4,'features':3,'counts_total':18,'donors':2} or value['raw_axis_features']!=['raw1','raw2']):raise ValueError()
        return value
    except (KeyError,ValueError,TypeError):raise StorageError('bio_environment_unavailable','单细胞最小探针未通过。',409) from None

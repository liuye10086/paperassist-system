"""Parent verification of the bounded offline single-cell probe receipt."""
from app.core.exceptions import StorageError


def validate_single_cell_probe(value):
    try:
        if (type(value) is not dict or set(value)!={'schema_version','checks','counts','raw_axis_features'} or type(value['schema_version']) is not int or value['schema_version']!=1 or value['checks']!={'h5ad_axes':True,'counts_equivalence':True,'cell_aggregation':True,'nonspatial_dispatch':True} or any(type(v) is not bool for v in value['checks'].values()) or value['counts']!={'cells':4,'features':3,'counts_total':18,'donors':2} or value['raw_axis_features']!=['raw1','raw2']):raise ValueError()
        return value
    except (KeyError,ValueError,TypeError):raise StorageError('bio_environment_unavailable','单细胞最小探针未通过。',409) from None

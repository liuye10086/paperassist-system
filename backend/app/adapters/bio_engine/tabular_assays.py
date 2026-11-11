"""Bounded quantitative matrices with explicit sample axes and missing masks."""
import csv
import hashlib
import json
from decimal import Decimal, InvalidOperation
from itertools import chain
from pathlib import Path
from zipfile import ZipFile
import numpy as np
from scipy.cluster.hierarchy import linkage, leaves_list
from scipy.spatial.distance import pdist, squareform
from .manifest import clean, canonical
from .tabular_writer import TabularWriter
from app.domain.bioinformatics.tabular_contracts import BioImportRequestV3, TabularRecipeParameters, TabularSampleMetadataMapping, validate_recipe, ENGINE_VERSION, PARSER_VERSION
from app.domain.bioinformatics.settings import BioLimits, MAX_BULK_METADATA_CELLS
from app.adapters.bio_insights_engine.tables import iter_table
from app.adapters.bio_insights_engine.inputs import verify_member

LIMITS = BioLimits()
MAX_CELLS = LIMITS.max_bulk_matrix_cells
SHARED_LAYER_LAYOUT = 'bulk_shared_layers_v1'
ECDF_DISPLAY_POINTS = 1024


def _id(value):
    if not isinstance(value,str) or not value or len(value)>200 or any(ord(c)<32 for c in value):raise ValueError('tabular_identifier_invalid')
    return value


def _error(code, **context):
    details=':'.join(f'{key}={value}' for key,value in context.items() if value is not None)
    return ValueError(code + ((':'+details) if details else ''))


def import_tabular(payload, *, _writer=None):
    config=BioImportRequestV3.model_validate(payload['config']);files={f['id']:f for f in payload['files']}
    if len(files)!=len(payload['files']) or set(files)!=set(config.file_ids):raise ValueError('tabular_source_identity_mismatch')
    specs = {spec.role: spec for spec in config.tables}
    cells = 0
    bulk = config.assay == 'bulk_rna_counts'
    microbiome = config.assay == 'microbiome'
    metadata_cells = 0
    matrix_columns = {config.feature_id_column, *config.sample_columns}
    file_limit = LIMITS.max_tabular_file_bytes if bulk else 10 * 1024**2
    expanded_limit = LIMITS.max_tabular_expanded_bytes if bulk else 64 * 1024**2
    observation_limit = LIMITS.max_bulk_observations + 1 if bulk else 501 if microbiome else 256
    row_limit = 10_000 if microbiome else LIMITS.max_features
    matrix_limit = LIMITS.max_bulk_matrix_cells if bulk else 5_000_000 if microbiome else 1_000_000
    matrix_row_limit = min(row_limit, matrix_limit // len(config.sample_columns))
    cell_limit = 5_100_000 if microbiome else 1_000_000

    def checked_rows(spec, limit):
        nonlocal cells, metadata_cells
        file = files[spec.file_id]
        if file['role'] != spec.role:
            raise ValueError('tabular_source_role_mismatch')
        if file['size_bytes'] > file_limit:
            raise ValueError('tabular_file_limit')
        is_matrix = spec.role == 'quantitative_matrix'
        rows = iter_table(
            file, format=spec.format, sheet=spec.sheet, encoding=spec.encoding, delimiter=spec.delimiter,
            header_row=spec.header_row, max_uncompressed_bytes=expanded_limit,
        )
        count = 0
        for count, (number, row) in enumerate(rows, 1):
            if is_matrix and row.keys() != matrix_columns:
                raise _error('matrix_columns_mismatch', file=file['filename'], row=number,
                             columns=','.join(sorted(row.keys() ^ matrix_columns)))
            if len(row) > observation_limit or count > limit:
                raise ValueError('tabular_cell_limit')
            cells += len(row)
            if bulk and not is_matrix:
                metadata_cells += len(row)
                if metadata_cells > MAX_BULK_METADATA_CELLS:
                    raise ValueError('tabular_cell_limit')
            elif not bulk and cells > cell_limit:
                raise ValueError('tabular_cell_limit')
            if any(len(str(value or '')) > 4000 for value in row.values()):
                raise ValueError('tabular_cell_text_limit')
            yield number, row
        if not count:
            raise ValueError('tabular_table_empty')

    sample_spec = specs['sample_metadata']
    sample_rows = checked_rows(sample_spec, row_limit)
    first_sample = next(sample_rows)
    samples = {}
    mapping=config.sample_metadata_mapping or (TabularSampleMetadataMapping() if config.assay=='bulk_rna_counts' else TabularSampleMetadataMapping(condition=None,biological_unit_id=None))
    first_columns = first_sample[1].keys()
    mapped_fields={key:value for key,value in mapping.model_dump().items() if value}
    required_fields={'sample_id'}|({'condition','biological_unit_id'} if config.assay=='bulk_rna_counts' else set())
    missing_columns = {field for field in required_fields if field not in mapped_fields}
    missing_columns.update(column for column in mapped_fields.values() if column not in first_columns)
    if missing_columns:
        raise _error('sample_metadata_columns_missing',file=files[sample_spec.file_id]['filename'],columns=','.join(sorted(missing_columns)))
    for number,row in chain((first_sample,), sample_rows):
        canonical_row=dict(row)
        for field,source_column in mapped_fields.items():
            canonical_row[field]=row.get(source_column)
        sid=_id(canonical_row.get('sample_id'))
        if sid in samples:raise _error('duplicate_sample_id',file=files[sample_spec.file_id]['filename'],row=number,sample_id=sid)
        for field in required_fields-{'sample_id'}:
            if not str(canonical_row.get(field) or '').strip():
                raise _error('sample_metadata_missing_value',file=files[sample_spec.file_id]['filename'],row=number,column=mapped_fields[field],sample_id=sid)
        if canonical_row.get('sample_role') and canonical_row['sample_role'] not in ('biological','technical'):
            raise _error('sample_metadata_invalid_value',file=files[sample_spec.file_id]['filename'],row=number,column=mapped_fields.get('sample_role','sample_role'),sample_id=sid)
        samples[sid]={**canonical_row,'source_row':number}
    actual=set(samples);expected=set(config.sample_columns)
    if actual!=expected:
        raise _error('sample_axis_mismatch',file=files[sample_spec.file_id]['filename'],missing=','.join(sorted(expected-actual)),extra=','.join(sorted(actual-expected)))
    annotations = {}
    if 'feature_metadata' in specs:
        for number,row in checked_rows(specs['feature_metadata'], row_limit):
            fid=_id(row.get('feature_id'))
            if fid in annotations:raise ValueError('duplicate_feature_annotation')
            annotations[fid]={**row,'annotation_source_row':number}
    matrix_spec = specs['quantitative_matrix']
    matrix_file = files[matrix_spec.file_id]
    ids = []
    seen = set()
    feature_rows = []
    counts = bulk or microbiome and config.scale.kind == 'raw_counts'
    shape = (len(config.sample_columns), matrix_row_limit)
    matrix = np.empty(shape, dtype=np.int64 if counts else np.float64)
    missing = np.empty(shape, dtype=bool)
    max_count = np.iinfo(np.int64).max
    na_values = set(config.na_values)
    for column, (number, row) in enumerate(checked_rows(matrix_spec, matrix_row_limit)):
        fid=_id(row.get(config.feature_id_column))
        if fid in seen:raise _error('duplicate_feature_id',file=matrix_file['filename'],row=number,feature_id=fid)
        seen.add(fid);ids.append(fid);data=[];mask=[]
        for sample in config.sample_columns:
            raw=row[sample];absent=raw is None or raw in na_values
            if absent:
                if counts and config.assay!='microbiome':raise _error('counts_missing',file=matrix_file['filename'],row=number,column=sample,sample_id=sample,feature_id=fid)
                data.append(0.);mask.append(True);continue
            try:value=Decimal(raw)
            except (InvalidOperation,TypeError):raise _error('matrix_non_numeric',file=matrix_file['filename'],row=number,column=sample,sample_id=sample,feature_id=fid) from None
            if not value.is_finite():raise _error('matrix_nonfinite',file=matrix_file['filename'],row=number,column=sample,sample_id=sample,feature_id=fid)
            if counts and (value<0 or value!=value.to_integral_value() or value>max_count):raise _error('counts_invalid',file=matrix_file['filename'],row=number,column=sample,sample_id=sample,feature_id=fid)
            numeric=int(value) if counts else float(value)
            if not np.isfinite(numeric):raise ValueError('matrix_nonfinite')
            if config.scale.kind not in ('log2','ln','log10','normalized') and numeric<0:raise _error('negative_unlogged_intensity',file=matrix_file['filename'],row=number,column=sample,sample_id=sample,feature_id=fid)
            data.append(numeric);mask.append(False)
        matrix[:, column] = data
        missing[:, column] = mask
        annotation = annotations.pop(fid, {})
        feature_rows.append({'feature_id':fid,'display_name':annotation.get('display_name') or fid,
            'feature_kind':{'bulk_rna_counts':'gene','normalized_expression':'gene','proteomics':'protein_group','metabolomics':'peak','microbiome':'microbial_taxon'}[config.assay],
            **annotation,'source_row':number})
    if annotations:raise ValueError('feature_annotation_axis_mismatch')
    matrix = matrix[:, :len(ids)]
    mask = missing[:, :len(ids)]
    writer=_writer if _writer is not None else TabularWriter(payload['output_directory']);writer.array('matrix_values',matrix);writer.array('matrix_missing',mask)
    writer.json('samples_index',{'sample_ids':config.sample_columns})
    writer.json('sample_mapping',{'version':'bulk_sample_mapping_v1' if config.assay=='bulk_rna_counts' else 'tabular_sample_mapping_v1',
        'sample_ids':config.sample_columns,'mapping':mapped_fields,'source':{'file_id':sample_spec.file_id,'sheet':sample_spec.sheet,'header_row':sample_spec.header_row},
        'rows':[{'sample_id':samples[s]['sample_id'],'source_row':samples[s]['source_row'],'source_file_id':sample_spec.file_id} for s in config.sample_columns]})
    writer.json('features_index',{'feature_ids':ids,'display_names':[r['display_name'] for r in feature_rows],'feature_kinds':[r['feature_kind'] for r in feature_rows]})
    writer.table('samples',[samples[s] for s in config.sample_columns])
    fields=list(dict.fromkeys(k for row in feature_rows for k in row));writer.table('features',feature_rows,fields)
    writer.json('input_scale',config.scale.model_dump())
    writer.table('import_audit',[dict(check='sample_axis_exact',status='passed',value=len(samples)),dict(check='missing_preserved',status='passed',value=int(mask.sum())),dict(check='cells',status='passed',value=cells)])
    for item in writer.artifacts:
        source=sample_spec if item['key'] in ('samples','samples_index','sample_mapping') else matrix_spec
        file=files[source.file_id]
        item.update(role=item['key'],compression='none',verification_state='verified',source_file_id=source.file_id,source_member_name=file['filename'])
    manifest=dict(schema_version=3,parser_version=PARSER_VERSION,assay=config.assay,observation_level='sample',
        storage_format='dense_mask_npy_v1',matrix_orientation='samples_by_features',input_shape={'features':len(ids),'observations':len(samples)},
        stored_entries=int(matrix.size),scale=config.scale.model_dump(),import_config=config.model_dump(),
        source_files=[{k:v for k,v in file.items() if k!='path'} for file in payload['files']],
        checks={'sample_axis_exact':True,'missing_count':int(mask.sum()),'counts_valid':counts,
            'sample_mapping':{'version':'bulk_sample_mapping_v1' if config.assay=='bulk_rna_counts' else 'tabular_sample_mapping_v1','source_file_id':sample_spec.file_id,'sample_count':len(samples),'columns':mapped_fields},
            'quality_reports':config.model_dump().get('quality_reports') or []},
        members=[{k:v for k,v in item.items() if k!='path'} for item in writer.artifacts])
    return dict(parser_version=PARSER_VERSION,manifest=manifest,outputs=writer.artifacts,n_features=len(ids),n_observations=len(samples),entry_count=int(matrix.size),checks=manifest['checks'])


def load_tabular(raw):
    members=raw['members'];manifest=raw['manifest']
    for member in members.values():verify_member(member)
    def document(key):return json.loads(Path(members[key]['path']).read_bytes())
    values=np.load(members['matrix_values']['path'],allow_pickle=False,mmap_mode='r')
    missing=np.load(members['matrix_missing']['path'],allow_pickle=False,mmap_mode='r')
    samples=document('samples_index')['sample_ids'];features=document('features_index')
    if (manifest.get('schema_version')!=3 or values.ndim!=2 or values.shape!=missing.shape or missing.dtype.kind!='b'
        or values.dtype.kind not in 'if' or values.size>(5_000_000 if manifest['assay']=='microbiome' else MAX_CELLS)
        or values.shape!=(len(samples),len(features['feature_ids'])) or len(samples)!=len(set(samples))
        or len(features['feature_ids'])!=len(set(features['feature_ids']))):
        raise ValueError('tabular_matrix_invalid')
    raw_counts = manifest['assay'] == 'bulk_rna_counts'
    if raw_counts and values.dtype != np.dtype('int64'):
        raise ValueError('counts_invalid')
    for row, mask in zip(values, missing, strict=True):
        if raw_counts:
            if mask.any() or (row < 0).any():
                raise ValueError('counts_invalid')
        elif not np.isfinite(row).all() or (row[mask] != 0).any():
            raise ValueError('tabular_matrix_invalid')
    return values,missing,samples,features


def transformed(values,missing,params,manifest):
    params=validate_recipe(params,manifest);result=values.astype('float64',copy=True);valid=~missing;factors=np.ones(len(result))
    if params.normalization in ('median','display_library_size','vst'):
        if params.normalization=='median':
            if np.any(result[valid]<=0):raise ValueError('median_requires_positive_values')
            medians=np.array([np.median(row[ok]) if ok.any() else np.nan for row,ok in zip(result,valid)])
            if not np.isfinite(medians).all() or np.any(medians<=0):raise ValueError('median_not_computable')
            factors=medians/np.median(medians)
        else:
            totals=result.sum(axis=1)
            if np.any(totals<=0):raise ValueError('empty_count_library')
            factors=totals/np.median(totals)
        result=result/factors[:,None]
        if params.normalization=='vst':
            # Anscombe-style variance stabilization for non-negative raw counts.
            if np.any(result[valid]<0):raise ValueError('vst_requires_nonnegative_counts')
            result[valid]=2*np.sqrt(result[valid] + 3/8)
    if params.transform!='none':
        if params.transform=='log1p':
            if np.any(result[valid]<0):raise ValueError('log1p_requires_nonnegative_counts')
            result[valid]=np.log1p(result[valid])
        else:
            if np.any(result[valid]<=0):raise ValueError('log_requires_positive_values')
            result[valid]={'log2':np.log2,'ln':np.log,'log10':np.log10}[params.transform](result[valid])
    result[missing]=0
    if not np.isfinite(result).all():raise ValueError('transform_nonfinite')
    return result,factors


def _iter_rows(member):
    with Path(member['path']).open(encoding='utf-8', newline='') as stream:
        yield from csv.DictReader(stream, delimiter='\t', strict=True)


def _rows(member):
    return list(_iter_rows(member))


def filtered_matrix(values, observations, features):
    if observations.all() and features.all():
        return values
    return values[np.ix_(np.flatnonzero(observations), np.flatnonzero(features))]


def inclusion_rows(rows, mask, reason):
    for row, kept in zip(rows, mask, strict=True):
        yield dict(row, kept=bool(kept), exclusion_reason='' if kept else reason)


def layer_scale(params, manifest):
    """Describe stored values separately from the immutable upstream scale."""
    params=validate_recipe(params,manifest)
    scale=manifest['scale']['kind'];unit=manifest['scale']['unit']
    if params.normalization=='display_library_size':
        scale='normalized';unit='library_size_normalized_counts'
    elif params.normalization=='vst':
        scale='vst';unit='variance_stabilized_counts'
    elif params.normalization=='median':
        scale='normalized';unit=f'median_normalized({unit})'
    if params.transform!='none':
        scale=params.transform;unit=f'{params.transform}({unit})'
    result=dict(input_scale=manifest['scale'],normalization=params.normalization,transform=params.transform,
                scale=scale,unit=unit,is_raw_integer_counts=manifest['assay']=='bulk_rna_counts' and scale=='raw_counts')
    if params.transform=='log1p':result.update(transform_offset=params.log1p_offset,transform_formula='ln(1+x)')
    return result


def layer_layout(params, manifest, raw_shape, filtered_shape, *, shared=False):
    raw_counts = manifest['assay'] == 'bulk_rna_counts'
    full_axis = shared and raw_shape == filtered_shape
    shared_missing = 'raw_missing' if full_axis else 'filtered_missing'
    normalized_mask = shared_missing if shared else 'normalized_missing'
    analysis_key = 'analysis_values'
    if shared and params.transform == 'none':
        analysis_key = {'display_library_size': 'normalized_values', 'vst': 'vst_values'}.get(params.normalization, analysis_key)
    shape = list(filtered_shape)
    analysis = dict(values=analysis_key, missing=shared_missing if shared else 'analysis_missing',
                    shape=shape, **layer_scale(params, manifest))
    display = analysis.copy() if shared else dict(analysis, values='display_values', missing='display_missing')
    value_layers = {
        'raw': dict(values='raw_values', missing='raw_missing', shape=list(raw_shape), axis='raw',
                    semantic='raw_counts' if raw_counts else manifest['scale']['kind']),
        'filtered': dict(values='raw_values' if full_axis else 'filtered_values', missing=shared_missing, shape=shape, axis='filtered',
                         semantic='filtered_counts' if raw_counts else 'filtered_input'),
        'normalized': dict(values='normalized_values', missing=normalized_mask, shape=shape, axis='filtered',
                           semantic='normalized_counts' if raw_counts else 'normalized_input'),
    }
    if raw_counts:
        value_layers['vst'] = dict(values='vst_values', missing=shared_missing if shared else 'vst_missing',
                                  shape=shape, semantic='variance_stabilized_expression', axis='filtered',
                                  formula='2*sqrt(normalized_counts + 3/8)')
    return {'analysis': analysis, 'display': display}, value_layers


_OBJECT_FORMATS = {version: f'paperassist_tabular_analysis_object_npz_v{version}' for version in (1, 2, 3)}
_OBJECT_ALIASES = {'raw': 'filtered'}


def _object_binding(spec):
    keys = ('identity', 'params')
    if spec['schema_version'] >= 2:
        keys += ('object_sha256', 'sample_ids', 'feature_ids', 'arrays', 'metadata')
    if spec['schema_version'] == 3:
        keys += ('aliases',)
    return hashlib.sha256(canonical({key: spec[key] for key in keys})).hexdigest()


def _analysis_object_spec(object_path, manifest_path, expected_identity, expected_params):
    spec = json.loads(Path(manifest_path).read_bytes())
    version = spec.get('schema_version')
    if type(version) is not int or version not in _OBJECT_FORMATS or spec.get('format') != _OBJECT_FORMATS[version]:
        raise ValueError('analysis_object_invalid')
    if version >= 2:
        with Path(object_path).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != spec.get('object_sha256'):
                raise ValueError('analysis_object_digest_invalid')
    identity=spec.get('identity',{});params=spec.get('params',{})
    if expected_identity is not None and identity!=expected_identity:raise ValueError('analysis_object_identity_invalid')
    if expected_params is not None and params!=expected_params:raise ValueError('analysis_object_params_invalid')
    if spec.get('manifest_identity_sha256')!=_object_binding(spec):raise ValueError('analysis_object_identity_digest_invalid')
    return spec


def _object_arrays(object_path, spec, expected_layers=None):
    shape = (len(spec['sample_ids']), len(spec['feature_ids']))
    shared = spec['schema_version'] == 3
    if shared and spec.get('aliases') != _OBJECT_ALIASES:
        raise ValueError('analysis_object_members_invalid')
    required = {'filtered', 'normalized'} if shared else {'raw', 'filtered', 'normalized'}
    names = set(spec['arrays'])
    if (len(names) != len(spec['arrays']) or not required <= names <= required | {'vst'}
            or expected_layers is not None and names | ({'raw'} if shared else set()) != expected_layers.keys()):
        raise ValueError('analysis_object_members_invalid')
    if shared and expected_layers is not None:
        with ZipFile(object_path) as archive:
            if sorted(archive.namelist()) != sorted(f'{name}.npy' for name in names):
                raise ValueError('analysis_object_members_invalid')
            for name in sorted(names):
                member = archive.getinfo(f'{name}.npy')
                expected = Path(expected_layers[name])
                if member.file_size != expected.stat().st_size:
                    raise ValueError('analysis_object_layer_mismatch')
                with archive.open(member) as observed, expected.open('rb') as source:
                    while block := source.read(1024**2):
                        if observed.read(len(block)) != block:
                            raise ValueError('analysis_object_layer_mismatch')
                    if observed.read(1):
                        raise ValueError('analysis_object_layer_mismatch')
        return {}
    values = {}
    with np.load(object_path,allow_pickle=False) as archive:
        if sorted(archive.files) != sorted(names):
            raise ValueError('analysis_object_members_invalid')
        for name in sorted(names):
            value = archive[name]
            if value.shape != shape or value.dtype.kind not in 'if':
                raise ValueError('analysis_object_shape_invalid')
            if expected_layers is None:
                values[name] = value
            else:
                expected = np.load(expected_layers[name], allow_pickle=False, mmap_mode='r')
                if value.shape != expected.shape or value.dtype != expected.dtype:
                    raise ValueError('analysis_object_layer_mismatch')
                rows_per_block = max(1, 1024**2 // max(1, shape[1] * value.itemsize))
                for start in range(0, shape[0], rows_per_block):
                    block = slice(start, start + rows_per_block)
                    if not np.array_equal(value[block], expected[block]):
                        raise ValueError('analysis_object_layer_mismatch')
                del expected
            del value
    if shared:
        values['raw'] = values['filtered']
    return values


def load_analysis_object(object_path, manifest_path, *, expected_identity=None, expected_params=None):
    """Read an old or hash-bound portable object with its declared axes."""
    spec = _analysis_object_spec(object_path, manifest_path, expected_identity, expected_params)
    return dict(sample_ids=list(spec['sample_ids']), feature_ids=list(spec['feature_ids']),
                layers=_object_arrays(object_path, spec), metadata=spec.get('metadata', {}),
                identity=spec['identity'], params=spec['params'], manifest_identity_sha256=spec['manifest_identity_sha256'])


def verify_analysis_object(object_path, manifest_path, *, identity, params, sample_ids, feature_ids, layers):
    spec = _analysis_object_spec(object_path, manifest_path, identity, params)
    if spec['sample_ids'] != sample_ids or spec['feature_ids'] != feature_ids:
        raise ValueError('analysis_object_axis_invalid')
    _object_arrays(object_path, spec, layers)
    return spec['format']


def _analysis_object(writer, *, filtered, normalized, vst=None, sample_ids, feature_ids, params, identity, metadata):
    shared = vst is not None
    version = 3 if shared else 2
    arrays=dict(filtered=filtered,normalized=normalized)
    if vst is not None:arrays['vst']=vst
    if not shared:arrays['raw']=filtered
    path = writer.root / 'analysis_object.npz'
    with path.open('xb') as stream:
        np.savez(stream,**arrays)
    member = writer.existing('analysis_object',path,'npz','analysis_object')
    spec = dict(schema_version=version,format=_OBJECT_FORMATS[version],
        object_sha256=member['sha256'],arrays=sorted(arrays),sample_ids=list(sample_ids),feature_ids=list(feature_ids),
        params=params,identity=identity,metadata=metadata)
    if shared:
        spec['aliases'] = _OBJECT_ALIASES
    writer.json('analysis_object_manifest', spec | {'manifest_identity_sha256': _object_binding(spec)})
    return spec['format']


def _figure(writer,key,title,plot,data,params,data_member=None,matrix_rows=None):
    import matplotlib
    matplotlib.use('Agg',force=True)
    from matplotlib import pyplot as plt
    from matplotlib.font_manager import FontProperties
    font=Path('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc')
    if font.is_file():plt.rcParams.update({'font.family':FontProperties(fname=str(font)).get_name(),'axes.unicode_minus':False})
    fig,ax=plt.subplots(figsize=(6,4));plot(ax)
    ax.set_title(title,fontproperties=FontProperties(fname=str(font)) if font.is_file() else None)
    fig.tight_layout()
    for fmt in ('png','tiff','svg'):
        path=writer.root/(key+'_'+fmt+'.'+fmt);fig.savefig(path,format=fmt,dpi=150,metadata={'Date':None} if fmt=='svg' else None)
        writer.existing(key+'_'+fmt,path,fmt,'figure')
    plt.close(fig)
    if data_member is None:
        data_member = key + '_data'
        if matrix_rows is None:
            writer.json(data_member,data)
        else:
            writer.matrix_json(data_member,data,matrix_rows)
    writer.json(key+'_manifest',dict(schema_version=2,kind='quantitative_figure',observation_level='sample',title=title,
        config={'kind':key,'output_language':params.output_language},data_member=data_member,formats=['png','tiff','svg'],
        caption='Sample-level quantitative measurements; processing is not biological validation.',dpi=150,width_inches=float(fig.get_figwidth()),height_inches=float(fig.get_figheight())))


def run_tabular(payload):
    raw=payload['raw'];values,missing,samples,features=load_tabular(raw);params=validate_recipe(payload.get('config',{}),raw['manifest'])
    ids=features['feature_ids']
    excluded_samples, excluded_features = set(params.exclude_samples), set(params.exclude_features)
    if not excluded_samples<=set(samples) or not excluded_features<=set(ids):raise ValueError('unknown_exclusion')
    om=np.array([s not in excluded_samples for s in samples]);fm=np.array([f not in excluded_features for f in ids])
    if not om.any() or not fm.any():raise ValueError('all_observations_or_features_excluded')
    writer=TabularWriter(payload['output_directory']);writer.array('observation_mask',om);writer.array('feature_mask',fm)
    writer.json('raw_axes',{'sample_ids':samples,'feature_ids':ids,'display_names':features['display_names'],'feature_kinds':features['feature_kinds']})
    sample_rows=list(inclusion_rows(_iter_rows(raw['members']['samples']),om,'explicit_sample_exclusion'))
    writer.table('samples',sample_rows)
    writer.table('features',inclusion_rows(_iter_rows(raw['members']['features']),fm,'explicit_feature_exclusion'))
    selected_samples=[sample for sample,keep in zip(samples,om) if keep]
    selected_feature_ids=[feature for feature,keep in zip(ids,fm) if keep]
    sample_metadata={row.get('sample_id',''):row for row in sample_rows}
    raw_counts=raw['manifest']['assay']=='bulk_rna_counts'
    qc=[]
    for i,s in enumerate(samples):
        valid=~missing[i];measured=values[i][valid]
        total_counts=float(np.sum(measured)) if raw_counts else None
        detected=int(np.count_nonzero(measured>0))
        zero_fraction=float(np.count_nonzero(measured==0)/len(measured)) if len(measured) else None
        distribution=dict(min=float(np.min(measured)) if len(measured) else None,
                          q1=float(np.quantile(measured,.25)) if len(measured) else None,
                          median=float(np.median(measured)) if len(measured) else None,
                          q3=float(np.quantile(measured,.75)) if len(measured) else None,
                          max=float(np.max(measured)) if len(measured) else None)
        metadata=sample_metadata.get(s,{})
        qc.append(dict(sample_id=s,condition=metadata.get('condition',''),batch=metadata.get('batch',''),
            donor=metadata.get('donor',''),biological_unit_id=metadata.get('biological_unit_id',''),
            missing_count=int(missing[i].sum()),zero_count=int(((values[i]==0)&~missing[i]).sum()),
            measured_features=int(valid.sum()),detected_features=detected,zero_fraction=zero_fraction,
            total_counts=total_counts,library_size=total_counts if raw_counts else None,
            expression_distribution=distribution,kept=bool(om[i]),
            exclusion_reason='' if om[i] else 'manual_exclusion',outlier_advisory=''))
    if raw_counts and qc:
        totals=np.asarray([row['total_counts'] for row in qc],dtype=float)
        center=float(np.median(totals));mad=float(np.median(np.abs(totals-center)))
        if mad>0:
            for row in qc:
                score=abs(row['total_counts']-center)/(1.4826*mad)
                if score>3:row['outlier_advisory']=f'library_size_robust_z>{score:.2f}'
    writer.table('sample_qc',qc)
    writer.table('feature_qc',(dict(feature_id=f,missing_count=int(missing[:,j].sum()),measured_samples=int((~missing[:,j]).sum()),
        detected_samples=int(np.count_nonzero(values[:,j]>0)),zero_fraction=float(np.count_nonzero(values[:,j]==0)/len(values[:,j])),
        kept=bool(fm[j]),exclusion_reason='' if fm[j] else 'manual_exclusion') for j,f in enumerate(ids)))
    writer.json('filtered_axes',{'sample_ids':selected_samples,'feature_ids':selected_feature_ids,
        'display_names':[name for name,keep in zip(features['display_names'],fm) if keep],
        'feature_kinds':[kind for kind,keep in zip(features['feature_kinds'],fm) if keep]})
    zh=params.output_language=='zh-CN'
    def qc_plot(ax):
        ax.bar(range(len(samples)),missing.mean(1));ax.set_ylim(0,1)
        ax.set_xlabel('样本' if zh else 'Sample');ax.set_ylabel('缺失比例' if zh else 'Missing fraction')
        if len(samples)<=30:ax.set_xticks(range(len(samples)),samples,rotation=60,ha='right',fontsize=7)
    _figure(writer,'qc_missing','样本缺失比例' if zh else 'Missing fraction by sample',qc_plot,{'sample_ids':samples,'missing_fraction':missing.mean(1).tolist()},params)
    def distribution_plot(ax):
        for i,s in enumerate(samples):
            measured=values[i][~missing[i]]
            if not len(measured):
                continue
            ordered = np.sort(measured)
            if raw_counts and len(ordered) > ECDF_DISPLAY_POINTS:
                positions = np.linspace(0, len(ordered)-1, ECDF_DISPLAY_POINTS, dtype=np.intp)
                ax.plot(ordered[positions], positions / (len(ordered)-1), label=s)
            else:
                ax.plot(ordered,np.linspace(0,1,len(ordered)),label=s)
        ax.set_xlabel('表达值' if zh else 'Expression value');ax.set_ylabel('经验累计比例' if zh else 'Empirical cumulative fraction')
        if len(samples)<=12:ax.legend(fontsize=7,frameon=False)
    distribution_data = {'sample_ids':samples,'quantiles':{s:row['expression_distribution'] for s,row in zip(samples,qc)}}
    if raw_counts:
        distribution_data['display_sampling'] = dict(rule='uniform_sorted_ranks_including_endpoints',
                                                      max_points_per_sample=ECDF_DISPLAY_POINTS)
    _figure(writer,'expression_distribution','表达分布' if zh else 'Expression distribution',distribution_plot,
        distribution_data,params)
    steps=[dict(key='qc',status='completed',reason=None),dict(key='filter',status='completed',reason=None)]
    summary=dict(raw_observations=len(samples),retained_observations=int(om.sum()),excluded_observations=int((~om).sum()),
        raw_features=len(ids),retained_features=int(fm.sum()),excluded_features=int((~fm).sum()),shape=[int(om.sum()),int(fm.sum())],observation_level='sample',missing_values=int(missing.sum()))
    filter_rules={'sample':{'manual_exclusion_only':True,'automatic_exclusion':False,'rule':'exclude_samples from immutable recipe'},
        'feature':{'manual_exclusion_only':True,'automatic_exclusion':False,'rule':'exclude_features from immutable recipe'}}
    outlier_advisories=[dict(sample_id=row['sample_id'],advisory=row['outlier_advisory'],basis='library_size_robust_z') for row in qc if row['outlier_advisory']]
    if raw_counts:
        summary['sample_qc_table'] = 'sample_qc'
    else:
        summary['qc_metrics'] = {
            metric: {row['sample_id']: row[metric] for row in qc}
            for metric in ('total_counts', 'detected_features', 'zero_fraction', 'expression_distribution')
        }
    summary['outlier_advisories']=outlier_advisories
    summary['filter_rules']=filter_rules
    summary['manual_exclusion_only']=True
    layers={}
    if payload['mode']=='compute':
        sub=filtered_matrix(values,om,fm);mask=filtered_matrix(missing,om,fm)
        layers,value_layers=layer_layout(params,raw['manifest'],values.shape,sub.shape,shared=raw_counts)
        if raw_counts:
            normalized=sub.astype('float64')
            totals=np.sum(normalized,axis=1)
            if np.any(totals<=0):raise ValueError('empty_count_library')
            library_factors=totals/np.median(totals)
            normalized/=library_factors[:,None]
            vst=normalized+3/8
            np.sqrt(vst,out=vst)
            vst*=2
            if layers['analysis']['values'] == 'vst_values':
                analysis,factors=vst,library_factors
            elif layers['analysis']['values'] == 'normalized_values':
                analysis,factors=normalized,library_factors
            else:
                analysis,factors=transformed(sub,mask,params,raw['manifest'])
        else:
            analysis,factors=transformed(sub,mask,params,raw['manifest'])
            normalized=analysis
            vst=None
        writer.array('raw_values',values);writer.array('raw_missing',missing)
        if value_layers['filtered']['values'] == 'filtered_values':
            writer.array('filtered_values',sub);writer.array('filtered_missing',mask)
        writer.array('normalized_values',normalized)
        if raw_counts:
            writer.array('vst_values',vst)
        else:
            writer.array('normalized_missing',mask)
        # The portable object is aligned to the filtered analysis axis. The full
        # immutable axis remains available through raw_values/raw_axes members.
        object_format=_analysis_object(writer,filtered=sub,normalized=normalized,vst=vst,
            sample_ids=selected_samples,feature_ids=selected_feature_ids,
            params=params.model_dump(),identity=payload['identity'],
            metadata={'assay':raw['manifest']['assay'],'source_scale':raw['manifest']['scale'],'manual_exclusion_only':True,
                'raw_axis':'filtered_analysis','full_raw_member_ref':{'values':'raw_values','missing':'raw_missing','axes':'raw_axes'}})
        del sub, normalized
        if raw_counts:
            if layers['analysis']['values']=='analysis_values':
                writer.array('analysis_values',analysis)
        else:
            for prefix in ('analysis','display'):
                writer.array(prefix+'_values',analysis);writer.array(prefix+'_missing',mask)
        summary['layers']={'raw':'raw_counts' if raw_counts else raw['manifest']['scale']['kind'],
            'filtered':'filtered_counts' if raw_counts else 'filtered_input','normalized':'normalized_counts' if raw_counts else 'normalized_input',
            'analysis':layers['analysis']['scale'],'display':layers['display']['scale']}
        if raw_counts:summary['layers']['vst']='variance_stabilized_expression'
        summary['analysis_object']={'format':object_format,'round_trip':'verified_by_loader'}
        writer.table('normalization_factors',(dict(sample_id=s,factor=float(f)) for s,f in zip(selected_samples,factors)))
        complete=~mask.any(axis=0);pca_mask=complete & (np.var(analysis,axis=0)>0);writer.array('pca_feature_mask',pca_mask)
        writer.table('pca_feature_selection',(dict(feature_id=f,included=bool(pca_mask[j]),reason='' if pca_mask[j] else 'missing_values' if not complete[j] else 'constant') for j,f in enumerate(selected_feature_ids)))
        n=int(om.sum());status='completed' if n>=3 and pca_mask.sum()>=2 else 'not_computable';reason=None if status=='completed' else 'insufficient_complete_nonconstant_features_or_samples'
        steps.extend([dict(key='transform',status='completed',reason=None),dict(key='pca',status=status,reason=reason),dict(key='sample_clustering',status=status,reason=reason)])
        if status=='completed':
            x=analysis[:,pca_mask];x-=x.mean(0)
            if params.scaling=='unit_variance':x/=np.std(x,axis=0,ddof=1)
            u,s,v=np.linalg.svd(x,full_matrices=False);k=min(params.pca_components,n-1,x.shape[1]);scores=u[:,:k]*s[:k];loads=v[:k].T.copy()
            del u,v
            for j in range(k):
                sign=1 if loads[np.argmax(abs(loads[:,j])),j]>=0 else -1;scores[:,j]*=sign;loads[:,j]*=sign
            variance=s[:k]**2/np.sum(s**2);selected_features=[feature for feature,keep in zip(selected_feature_ids,pca_mask) if keep]
            writer.table('pca_scores',[dict(sample_id=s,**{f'pc{j+1}':float(v) for j,v in enumerate(score)}) for s,score in zip(selected_samples,scores)])
            writer.table('pca_loadings',(dict(feature_id=f,**{f'pc{j+1}':float(v) for j,v in enumerate(row)}) for f,row in zip(selected_features,loads)))
            writer.table('pca_variance_ratio',[dict(component=j+1,variance_ratio=float(v)) for j,v in enumerate(variance)])
            linked=linkage(x,method='average',metric='euclidean');order=leaves_list(linked)
            writer.table('sample_clustering',[dict(order=i,sample_id=selected_samples[j]) for i,j in enumerate(order)])
            writer.array('sample_linkage',linked)
            def pca_plot(ax):
                from matplotlib import pyplot as plt
                import textwrap
                columns=max(1,int(np.ceil(len(selected_samples)/30)))
                labels=[textwrap.fill(label,24) for label in selected_samples]
                rows=int(np.ceil(len(labels)/columns));lines=max(label.count('\n')+1 for label in labels)
                ax.figure.set_size_inches(min(26,6+2.2*columns),min(26,max(4.5,1.5+.18*rows*lines)))
                markers=('o','s','^','v','D','P','X','<','>','h','*','p','8')
                for i,(label,point) in enumerate(zip(labels,scores)):
                    ax.scatter(point[0],point[1],label=label,color=plt.get_cmap('tab20')(i%20),marker=markers[(i//20)%len(markers)],s=30,edgecolors='black',linewidths=.3)
                ax.set_xlabel(f'PC1 ({variance[0]:.1%})');ax.set_ylabel(f'PC2 ({variance[1]:.1%})')
                ax.legend(loc='upper left',bbox_to_anchor=(1.02,1),ncol=columns,fontsize=7,title='样本身份' if zh else 'Sample identity',title_fontsize=8,frameon=False,borderaxespad=0)
            def cluster_plot(ax):
                import textwrap
                image=ax.imshow(x[order],aspect='auto',cmap='viridis');ax.set_xlabel('完整且非恒定特征' if zh else 'Complete nonconstant features');ax.set_ylabel('样本' if zh else 'Samples')
                ticks=np.unique(np.linspace(0,len(selected_features)-1,min(20,len(selected_features)),dtype=int))
                ax.set_xticks(ticks,[selected_features[j] for j in ticks],rotation=60,ha='right',fontsize=7)
                if len(selected_features)>20:ax.set_xlabel('完整且非恒定特征（刻度抽稀；完整轴见图数据）' if zh else 'Complete nonconstant features (ticks sampled; complete axis in plot data)')
                ax.figure.set_size_inches(max(6,min(12,4+len(ticks)/3)),max(4.5,min(9,2+len(selected_samples)*.15)))
                if len(selected_samples)<=30:ax.set_yticks(range(len(order)),[selected_samples[j] for j in order],fontsize=7)
                unit=layers['analysis']['unit']
                label=(f'中心化 / 样本标准差（无量纲；输入单位：{unit}）' if zh else f'Centered / sample SD (dimensionless; input unit: {unit})') if params.scaling=='unit_variance' else (f'中心化值（单位：{unit}）' if zh else f'Centered {unit}')
                ax.figure.colorbar(image,ax=ax,label=textwrap.fill(label,50))
            selected_meta=[sample_metadata.get(s,{}) for s in selected_samples]
            _figure(writer,'pca','样本 PCA' if zh else 'Sample PCA',pca_plot,{'sample_ids':selected_samples,'scores':scores.tolist(),'variance_ratio':variance.tolist(),
                'condition':[m.get('condition','') for m in selected_meta],'batch':[m.get('batch','') for m in selected_meta],
                'layer':'analysis','semantic':layers['analysis']['scale']},params)
            _figure(writer,'sample_clustering','样本聚类' if zh else 'Sample clustering',cluster_plot,{'sample_ids':[selected_samples[j] for j in order],'feature_ids':selected_features,
                'condition':[selected_meta[j].get('condition','') for j in order],'batch':[selected_meta[j].get('batch','') for j in order],
                'method':'average_euclidean','layer':'analysis','semantic':layers['analysis']['scale']},params,None,(x[j] for j in order))
            del x, loads
            summary['pca_components']=k
        else:
            for key,field in [('pca_scores','sample_id'),('pca_loadings','feature_id'),('pca_variance_ratio','component'),('sample_clustering','sample_id')]:writer.table(key,[],[field,'reason'])
        heat=analysis if not raw_counts else vst
        heat_complete=~mask.any(axis=0)
        if int(heat_complete.sum())>=1 and len(heat)>=2:
            h=heat if heat_complete.all() else heat[:,heat_complete]
            if h.shape[1] == 1:
                correlation = np.full((len(h), len(h)), np.nan)
            else:
                with np.errstate(invalid='ignore', divide='ignore'):
                    correlation = np.corrcoef(h)
                constant = np.ptp(h, axis=1) == 0
                correlation[constant, :] = np.nan
                correlation[:, constant] = np.nan
                valid = np.flatnonzero(np.isfinite(np.diag(correlation)))
                correlation[valid, valid] = 1.0
            can_correlate = np.count_nonzero(np.isfinite(np.diag(correlation))) >= 2
            distance=squareform(pdist(h,metric='euclidean'))
            selected_meta=[sample_metadata.get(s,{}) for s in selected_samples]
            sample_ids_selected=selected_samples
            heat_layer='vst' if raw_counts else 'analysis';heat_semantic='variance_stabilized_expression' if raw_counts else layers['analysis']['scale']
            corr_payload=dict(sample_ids=sample_ids_selected,values=correlation.tolist(),condition=[m.get('condition','') for m in selected_meta],batch=[m.get('batch','') for m in selected_meta],method='pearson_complete_features',layer=heat_layer,semantic=heat_semantic)
            if not can_correlate:
                corr_payload.update(status='not_computable', reason='insufficient_variable_samples_or_features')
            dist_payload=dict(sample_ids=sample_ids_selected,values=distance.tolist(),condition=[m.get('condition','') for m in selected_meta],batch=[m.get('batch','') for m in selected_meta],method='euclidean_complete_features',layer=heat_layer,semantic=heat_semantic)
            writer.json('sample_correlation',corr_payload);writer.json('sample_distance',dist_payload)
            def corr_plot(ax):
                from matplotlib import colormaps

                palette = colormaps['coolwarm'].with_extremes(bad='#cbd5e1')
                image=ax.imshow(np.ma.masked_invalid(correlation),vmin=-1,vmax=1,cmap=palette);ax.set_xticks(range(len(sample_ids_selected)),sample_ids_selected,rotation=60,ha='right',fontsize=7);ax.set_yticks(range(len(sample_ids_selected)),sample_ids_selected,fontsize=7);ax.figure.colorbar(image,ax=ax,label='相关系数' if zh else 'Pearson correlation')
            def dist_plot(ax):
                image=ax.imshow(distance,cmap='viridis');ax.set_xticks(range(len(sample_ids_selected)),sample_ids_selected,rotation=60,ha='right',fontsize=7);ax.set_yticks(range(len(sample_ids_selected)),sample_ids_selected,fontsize=7);ax.figure.colorbar(image,ax=ax,label='距离' if zh else 'Euclidean distance')
            if can_correlate:
                _figure(writer,'correlation_heatmap','样本相关性热图' if zh else 'Sample correlation heatmap',corr_plot,corr_payload,params,'sample_correlation' if raw_counts else None)
            _figure(writer,'distance_heatmap','样本距离热图' if zh else 'Sample distance heatmap',dist_plot,dist_payload,params,'sample_distance' if raw_counts else None)
        else:
            writer.json('sample_correlation',dict(status='not_computable',reason='no_complete_features_or_insufficient_samples'))
            writer.json('sample_distance',dict(status='not_computable',reason='no_complete_features_or_insufficient_samples'))
    elif payload['mode']!='qc':raise ValueError('unsupported_tabular_mode')
    methods=dict(name='tabular_quantitative_v1',assay=raw['manifest']['assay'],observation_level='sample',input_scale=raw['manifest']['scale'],
        transform_formula='ln(1+x)' if params.transform=='log1p' else params.transform,transform_offset=params.log1p_offset if params.transform=='log1p' else 0,
        params=params.model_dump(),steps=steps,missing='preserved; PCA uses complete nonconstant features; no imputation',
        statistical_inference='not_performed',replicates='sample identity does not establish independent biological replication',
        pca='centered SVD; optional sample-SD feature scaling; canonical loading signs; no DEG prefilter',clustering='average linkage Euclidean on exact PCA feature matrix',
        layers='raw, filtered, normalized and variance-stabilized layers retain explicit axes; analysis object is portable NPZ+JSON',
        outlier_policy='advisory only; no automatic sample exclusion')
    methods['description_zh']=f"以样本为观测单位；输入尺度为 {raw['manifest']['scale']['kind']}，单位 {raw['manifest']['scale']['unit']}。标准化 {params.normalization}，变换 {params.transform}；缺失保持，不插补。PCA与样本聚类仅使用完整且非恒定特征，缩放 {params.scaling} 仅作用于PCA/聚类；本步骤未作组间检验或独立生物学重复验证。"
    methods['description_en']=f"Observations are samples; input scale {raw['manifest']['scale']['kind']} ({raw['manifest']['scale']['unit']}). Normalization {params.normalization}; transform {params.transform}. Missing values are preserved without imputation. PCA and sample clustering use complete nonconstant features; scaling {params.scaling} applies only to PCA/clustering. No group tests or biological independence validation were performed."
    writer.json('methods',methods);writer.json('recipe',params.model_dump())
    writer.add('reproduce',b'# Use the fixed /opt/paperassist-bio-insights/bin/python environment and exported verified raw members.\nimport json,sys\nfrom app.adapters.bio_engine.tabular_assays import run_tabular\nrun_tabular(json.load(open(sys.argv[1],encoding="utf-8")))\n','py')
    if payload.get('_trusted_lock'):writer.add('requirements_bio_lock',payload['_trusted_lock'],'lock')
    manifest=dict(schema_version=2,engine_version=ENGINE_VERSION,identity=payload['identity'],raw_source=payload['identity'].get('raw_source'),
        environment_digest=payload['identity'].get('environment_digest'),code_digest=payload['identity'].get('code_digest'),assay=raw['manifest']['assay'],observation_level='sample',
        scale=raw['manifest']['scale'],params=params.model_dump(),summary=summary,steps=steps,layers=layers,value_layers=value_layers if payload['mode']=='compute' else {},
        filter_rules=filter_rules,outlier_advisories=outlier_advisories,methods=methods,
        tables=[dict(key=m['key'],label=m['key'],status=next((s['status'] for s in steps if s['key']=='pca'),'not_requested') if m['key'] in ('pca_scores','pca_loadings','pca_variance_ratio','sample_clustering') else 'completed',reason=next((s['reason'] for s in steps if s['key']=='pca'),None) if m['key'] in ('pca_scores','pca_loadings','pca_variance_ratio','sample_clustering') else None) for m in writer.artifacts if m['format']=='tsv'],
        members=[{k:v for k,v in m.items() if k!='path'} for m in writer.artifacts])
    if raw_counts and payload['mode']=='compute':
        manifest['layer_layout'] = SHARED_LAYER_LAYOUT
    writer.json('manifest',manifest)
    return clean(dict(status='completed',engine_version=ENGINE_VERSION,outputs=writer.artifacts,manifest=manifest,summary=summary,steps=steps,checks={},effective_params=params.model_dump()))

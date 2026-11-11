"""Bounded Linux science transport and independent parent-side output checks."""
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import struct
import sys
from threading import Event, Thread

import numpy as np
from PIL import Image

from app.core.exceptions import StorageError


ENGINE_VERSION = 'visium_explore_v1.0.0'
MAX_LEAF = 256 * 1024**2
MAX_OUTPUT = 512 * 1024**2
MAX_JSON = 2 * 1024**2
MAX_RSS = 2 * 1024**3
FORMATS = {'npy', 'json', 'tsv', 'csv', 'png', 'h5ad', 'txt', 'py', 'lock'}


def _run_child(*args, **kwargs):
    # Parent transport needs the application environment; pure output validators
    # also run in the locked numerical environment without Web/Excel packages.
    from app.adapters.excel_process import _run_child as transport
    return transport(*args, **kwargs)


def invalid(code='bio_output_invalid'):
    return StorageError(code, '生信计算环境、输入或输出未通过完整性检查。', 422)


def _plain_json(content):
    def reject(value):
        raise ValueError('Nonfinite JSON')
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON identity')
            result[key] = value
        return result
    return json.loads(content, parse_constant=reject, object_pairs_hook=object_pairs)


def validate_artifacts(outputs, output_directory, *, formats=None,max_output_bytes=MAX_OUTPUT,json_validators=None):
    """No unregistered bytes or pickle-capable arrays may enter object storage."""
    directory = Path(output_directory).absolute()
    try:
        if type(max_output_bytes) is not int or not 1<=max_output_bytes<=1024**3:raise ValueError()
        if directory.is_symlink() or not directory.is_dir() or type(outputs) is not list or not 1 <= len(outputs) <= 256:
            raise ValueError()
        expected, keys, total = set(), set(), 0
        for item in outputs:
            key, fmt, size = item['key'], item['format'], item['size_bytes']
            path = Path(item['path'])
            if (type(key) is not str or not re.fullmatch(r'[a-z][a-z0-9_-]{0,100}', key) or key in keys
                    or fmt not in (formats or FORMATS) or type(size) is not int or not 0 < size <= MAX_LEAF
                    or type(item['sha256']) is not str or not re.fullmatch(r'[a-f0-9]{64}', item['sha256'])
                    or type(item['role']) is not str or not item['role'] or len(item['role']) > 100
                    or not path.is_absolute() or path.is_symlink() or not path.is_file()
                    or path.resolve().parent != directory.resolve() or path.name != key + '.' + fmt
                    or path.stat().st_size != size):
                raise ValueError()
            sha = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(65536), b''):
                    sha.update(block)
            if sha.hexdigest() != item['sha256']:
                raise ValueError()
            if fmt == 'npy':
                array = np.load(path, allow_pickle=False, mmap_mode='r')
                if (not isinstance(array, np.ndarray) or array.dtype.kind not in 'biuf'
                        or array.ndim > 2 or array.size > 20_000_000):
                    raise ValueError()
                if array.dtype.kind == 'f':
                    blocks = np.nditer(array, flags=['external_loop', 'buffered', 'zerosize_ok'], buffersize=131072)
                    if any(not np.isfinite(block).all() for block in blocks):
                        raise ValueError()
                    del blocks
                del array
            elif fmt == 'json':
                # Only the transport is 2MiB. Full axis/map members are bounded
                # leaves, and may legitimately exceed that with 100k features.
                validator = (json_validators or {}).get(key)
                if validator is None:
                    _plain_json(path.read_bytes())
                else:
                    validator(path, _plain_json)
            elif fmt in ('png','tiff'):
                with Image.open(path) as image:
                    if image.format != fmt.upper() or max(image.size) > 4096 or image.width * image.height > 16_000_000:
                        raise ValueError()
                    image.verify()
            elif fmt=='svg':
                from defusedxml.ElementTree import fromstring
                tree=fromstring(path.read_bytes())
                if tree.tag.rsplit('}',1)[-1]!='svg':raise ValueError()
                for node in tree.iter():
                    if node.tag.rsplit('}',1)[-1] in ('script','foreignObject','iframe','animate','set'):raise ValueError()
                    for name,value in node.attrib.items():
                        name=name.rsplit('}',1)[-1]
                        if name.lower().startswith('on') or name in ('href','src') and not value.startswith(('#','data:image/png;base64,')):raise ValueError()
            elif fmt == 'h5ad':
                with path.open('rb') as stream:
                    magic = stream.read(8)
                if magic != b'\x89HDF\r\n\x1a\n':
                    raise ValueError()
            total += size
            if total > max_output_bytes:
                raise ValueError()
            expected.add(path.resolve())
            keys.add(key)
        if {p.resolve() for p in directory.iterdir()} != expected:
            raise ValueError()
        return outputs
    except (KeyError, TypeError, ValueError, OSError, OverflowError) as exc:
        raise invalid() from exc


def validate_engine_result(result, directory, *, mode,max_output_bytes=MAX_OUTPUT):
    try:
        if (type(result) is not dict or result['engine_version'] != ENGINE_VERSION
                or result['status'] != 'completed' or type(result['manifest']) is not dict
                or type(result['summary']) is not dict or type(result['steps']) is not list):
            raise ValueError()
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(encoded) > MAX_JSON:
            raise ValueError()
        outputs = validate_artifacts(result['outputs'], directory,max_output_bytes=max_output_bytes)
        keys = {item['key'] for item in outputs}
        if mode in {'qc', 'compute'}:
            if not {'observation_mask', 'feature_mask', 'raw_axes', 'observations', 'features', 'methods', 'recipe', 'manifest'} <= keys:
                raise ValueError()
        if mode == 'compute' and not {'counts_data', 'counts_indices', 'counts_indptr', 'normalized_data', 'log1p_data', 'pca', 'umap', 'processed', 'markers'} <= keys:
            raise ValueError()
        for step in result['steps']:
            allowed={'completed','not_computable','not_requested'}
            if step.get('key') in {'scdblfinder','decontx'}:allowed|={'partial','failed'}
            if step.get('key') in {'technical_covariates','harmony'}:allowed.add('failed')
            if step['status'] not in allowed:
                raise ValueError()
        return result
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise invalid() from exc


def validate_processed_arrays(outputs, *, target_sum=10000.):
    """Reconcile raw axes, masks, CSR layers and embeddings independently."""
    records = {item['key']: item for item in outputs}
    opened = []
    try:
        def array(key):
            value = np.load(records[key]['path'], allow_pickle=False, mmap_mode='r')
            opened.append(value)
            return value
        axes = _plain_json(Path(records['raw_axes']['path']).read_bytes())
        observations, features = array('observation_mask'), array('feature_mask')
        if (observations.dtype.kind != 'b' or features.dtype.kind != 'b'
                or observations.ndim != 1 or features.ndim != 1
                or len(axes['barcodes']) != len(observations) or len(set(axes['barcodes'])) != len(observations)
                or len(axes['feature_ids']) != len(features) or len(set(axes['feature_ids'])) != len(features)
                or len(axes['feature_symbols']) != len(features) or len(axes['feature_types']) != len(features)):
            raise ValueError()
        n, f = int(observations.sum()), int(features.sum())
        if not 5 <= n <= 20000 or not 3 <= f <= 100000 or not np.isfinite(target_sum) or target_sum <= 0:
            raise ValueError()
        layers = {}
        names=['counts','normalized','log1p']
        if any(key.startswith('decontx_counts_') for key in records):names.append('decontx_counts')
        for name in names:
            data, indices, ptr = (array(name + '_' + suffix) for suffix in ['data', 'indices', 'indptr'])
            if (data.ndim != 1 or indices.ndim != 1 or ptr.ndim != 1 or ptr.shape != (n + 1,)
                    or ptr.dtype.kind not in 'iu' or indices.dtype.kind not in 'iu'
                    or ptr[0] != 0 or ptr[-1] != len(data) or np.any(ptr[1:] < ptr[:-1])
                    or len(indices) != len(data) or len(data) > 10_000_000
                    or np.any(indices < 0) or np.any(indices >= f) or np.any(data < 0)
                    or not np.isfinite(data).all() or (name == 'counts' and data.dtype.kind not in 'iu')
                    or (name != 'counts' and data.dtype.kind != 'f')):
                raise ValueError()
            layers[name] = (data, indices, ptr)
        counts, indices, ptr = layers['counts']
        for name in ['normalized', 'log1p']:
            if not np.array_equal(layers[name][1], indices) or not np.array_equal(layers[name][2], ptr):
                raise ValueError()
        normalized, logged = layers['normalized'][0], layers['log1p'][0]
        if 'decontx_counts' in layers:
            corrected,ci,cp=layers['decontx_counts']
            shape=_plain_json(Path(records['decontx_counts_shape']['path']).read_bytes())
            if shape.get('shape')!=[n,f] or shape.get('dtype')!=str(corrected.dtype) or shape.get('nnz')!=len(corrected):raise ValueError()
            for row,(start,end) in enumerate(zip(cp[:-1],cp[1:])):
                current=ci[start:end];values=corrected[start:end]
                if len(current)>1 and np.any(current[1:]<=current[:-1]):raise ValueError()
                original_i=indices[ptr[row]:ptr[row+1]];original_x=counts[ptr[row]:ptr[row+1]]
                locations=np.searchsorted(original_i,current)
                if np.any(locations>=len(original_i)) or not np.array_equal(original_i[locations],current) or np.any(values>original_x[locations]+1e-7):raise ValueError()
        for start, end in zip(ptr[:-1], ptr[1:]):
            if end <= start or (end - start > 1 and np.any(indices[start + 1:end] <= indices[start:end - 1])):
                raise ValueError()
            total = counts[start:end].sum(dtype=np.float64)
            if total <= 0 or not np.allclose(normalized[start:end], counts[start:end] * (target_sum / total), rtol=1e-5, atol=1e-6):
                raise ValueError()
        for start in range(0, len(logged), 1_000_000):
            section = slice(start, start + 1_000_000)
            if not np.allclose(logged[section], np.log1p(normalized[section]), rtol=1e-5, atol=1e-6):
                raise ValueError()
        pca, umap, hvg = array('pca'), array('umap'), array('hvg_mask')
        if (pca.ndim != 2 or pca.shape[0] != n or not 2 <= pca.shape[1] < min(n, f)
                or umap.shape != (n, 2) or hvg.dtype.kind != 'b' or hvg.shape != (f,)
                or not np.isfinite(pca).all() or not np.isfinite(umap).all()):
            raise ValueError()
        return {'observations': n, 'features': f, 'nnz': len(counts)}
    except (KeyError, TypeError, ValueError, OSError, OverflowError, IndexError) as exc:
        raise invalid() from exc
    finally:
        opened.clear()


def _input_records(value):
    if isinstance(value, dict):
        if 'path' in value:
            yield value
        for nested in value.values():
            yield from _input_records(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _input_records(nested)


def execute_bio_analysis(payload, output_directory, *, mode='compute', settings=None, cancel_event=None):
    """A fixed interpreter and script, never a user-selected command or code."""
    from app.adapters.bio_child_cancel import require_not_revoked,terminate_revoked_child
    require_not_revoked(cancel_event)
    if sys.platform != 'linux':
        raise invalid('bio_environment_unavailable')
    tabular=mode=='import_v3' or payload.get('raw',{}).get('manifest',{}).get('schema_version')==3
    from app.domain.bioinformatics.single_cell_resources import memory_bounds,analysis_limits_for,SingleCellRAnalysisLimits
    selected_limits=SingleCellRAnalysisLimits() if mode=='annotation' else analysis_limits_for(single_cell=mode in {'qc','compute'} and not tabular and payload.get('raw',{}).get('manifest',{}).get('assay')=='single_cell',params=payload.get('config',{}))
    bounds=memory_bounds(selected_limits)
    interpreter = Path('/opt/paperassist-bio-insights/bin/python' if tabular else '/opt/paperassist-bio/bin/python')
    output = Path(output_directory).absolute()
    if not interpreter.is_file() or output.is_symlink() or mode not in {'qc', 'compute', 'figure','annotation', 'h5_check', 'import_v2','import_v3','import_single_cell'}:
        raise invalid('bio_environment_unavailable')
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise invalid()
    try:
        if tabular:
            from app.domain.bioinformatics.tabular_settings import runtime_identity
            runtime=runtime_identity()
            if not runtime['available']:raise invalid('bio_environment_unavailable')
            payload={**payload,'_runtime_identity':runtime}
        for record in _input_records(payload):
            path, size = Path(record['path']), record['size_bytes']
            if (not path.is_absolute() or path.is_symlink() or not path.is_file() or path.resolve().is_relative_to(output.resolve())
                    or type(size) is not int or not 0 < size <= MAX_LEAF or path.stat().st_size != size):
                raise ValueError()
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != record['sha256']:
                    raise ValueError()
        request = {**payload, 'mode': mode, 'output_directory': str(output)}
        if tabular:
            from app.adapters.bio_engine.tabular_transport import stage_request
            transport = stage_request(request, output)
        else:
            data = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
            if len(data) > MAX_JSON:
                raise ValueError()
            transport = nullcontext(data)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise invalid('bio_input_integrity_changed') from exc
    stopped, exceeded = Event(), Event()
    monitors, peak = [], [0]

    def started(pid):
        status_path = Path(f'/proc/{pid}/status')
        stat_path = Path(f'/proc/{pid}/stat')
        birth = stat_path.read_text().rsplit(')', 1)[1].split()[19]

        def monitor():
            while not stopped.wait(.1):
                try:
                    if stat_path.read_text().rsplit(')', 1)[1].split()[19] != birth:
                        return
                    if terminate_revoked_child(pid,birth,cancel_event):return
                    match = re.search(r'^VmRSS:\s+(\d+) kB$', status_path.read_text(), re.M)
                    rss = int(match.group(1)) * 1024 if match else 0
                    peak[0] = max(peak[0], rss)
                    if rss > bounds['rss_limit_bytes']:
                        exceeded.set()
                        os.kill(pid, signal.SIGKILL)
                        return
                except (OSError, ValueError, IndexError):
                    return
        thread = Thread(target=monitor, name='bio-analysis-rss', daemon=True)
        monitors.append(thread)
        thread.start()

    command = [str(interpreter), '-I', '-B', str(Path(__file__).with_name('bio_engine') / ('tabular_worker.py' if tabular else 'worker.py')), str(os.getpid())]
    try:
        with transport as data:
            require_not_revoked(cancel_event)
            response = _run_child(command, struct.pack('!I', len(data)) + data,
                                  timeout_seconds=1380, max_output_bytes=MAX_JSON, on_started=started)
    except StorageError as exc:
        require_not_revoked(cancel_event)
        code = 'bio_resource_exceeded' if exceeded.is_set() or exc.code == 'parse_resource_limit' else (
            'bio_analysis_timeout' if exc.code == 'parse_timeout' else 'bio_environment_unavailable')
        raise invalid(code) from exc
    except ValueError as exc:
        raise invalid('bio_input_limit') from exc
    except OSError as exc:
        raise invalid('bio_environment_unavailable') from exc
    finally:
        stopped.set()
        for thread in monitors:
            thread.join(timeout=1)
    require_not_revoked(cancel_event)
    if type(response) is not dict:
        raise invalid()
    if set(response) == {'error'}:
        safe = {'bio_environment_unavailable', 'bio_isolation_unavailable', 'bio_resource_exceeded',
                'bio_recipe_invalid', 'bio_input_integrity_changed', 'bio_h5_unsupported',
                'bio_h5_matrix_mismatch', 'bio_insufficient_observations', 'bio_output_invalid'}
        if mode in {'import_v2','import_single_cell'}:
            from app.adapters.bio_parse_process import _ERRORS
            safe |= _ERRORS
        code = response['error'].get('code') if isinstance(response['error'], dict) else None
        raise invalid(code if code in safe else 'bio_output_invalid')
    if set(response) != {'result'}:
        raise invalid()
    if tabular:
        from app.adapters.bio_tabular_process import validate_tabular_result
        result=validate_tabular_result(response['result'],output,payload,mode)
    elif mode in {'import_v2','import_single_cell'}:
        from app.adapters.bio_parse_process import validate_parser_result
        from app.domain.bioinformatics.settings import BioLimits
        result = validate_parser_result(response['result'], output, BioLimits.model_validate(payload['settings']),
                  {item['id'] for item in payload['files']}, expected_parser_version='single_cell_import_v1' if mode=='import_single_cell' else 'geo_visium_import_v2')
    else:
        result = validate_engine_result(response['result'], output, mode=mode,max_output_bytes=selected_limits.max_output_bytes)
    if mode == 'compute' and not tabular:
        validate_processed_arrays(result['outputs'], target_sum=payload.get('config', {}).get('target_sum', 10000.))
    if mode=='annotation':
        from app.adapters.bio_single_cell_validation import validate_annotation_result
        validate_annotation_result(result,payload)
    result.setdefault('resources', {})['parent_peak_rss_bytes'] = peak[0]
    result['resources'].update(bounds)
    result['resources'].update(max_output_bytes=selected_limits.max_output_bytes,max_member_bytes=selected_limits.max_member_bytes)
    return result

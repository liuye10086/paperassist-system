"""Bounded Linux science transport and independent parent-side output checks."""
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

from app.adapters.excel_process import _run_child
from app.core.exceptions import StorageError


ENGINE_VERSION = 'visium_explore_v1.0.0'
MAX_LEAF = 256 * 1024**2
MAX_OUTPUT = 512 * 1024**2
MAX_JSON = 2 * 1024**2
MAX_RSS = 2 * 1024**3
FORMATS = {'npy', 'json', 'tsv', 'csv', 'png', 'pdf', 'h5ad', 'txt', 'py', 'lock'}


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


def validate_artifacts(outputs, output_directory):
    """No unregistered bytes or pickle-capable arrays may enter object storage."""
    directory = Path(output_directory).absolute()
    try:
        if directory.is_symlink() or not directory.is_dir() or type(outputs) is not list or not 1 <= len(outputs) <= 256:
            raise ValueError()
        expected, keys, total = set(), set(), 0
        for item in outputs:
            key, fmt, size = item['key'], item['format'], item['size_bytes']
            path = Path(item['path'])
            if (type(key) is not str or not re.fullmatch(r'[a-z][a-z0-9_-]{0,100}', key) or key in keys
                    or fmt not in FORMATS or type(size) is not int or not 0 < size <= MAX_LEAF
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
                        or array.ndim > 2 or array.size > 20_000_000 or not np.isfinite(array).all()):
                    raise ValueError()
                del array
            elif fmt == 'json':
                # Only the transport is 2MiB. Full axis/map members are bounded
                # leaves, and may legitimately exceed that with 100k features.
                _plain_json(path.read_bytes())
            elif fmt == 'png':
                with Image.open(path) as image:
                    if image.format != 'PNG' or max(image.size) > 4096 or image.width * image.height > 16_000_000:
                        raise ValueError()
                    image.verify()
            elif fmt in {'pdf', 'h5ad'}:
                with path.open('rb') as stream:
                    magic = stream.read(8)
                if fmt == 'pdf' and not magic.startswith(b'%PDF-') or fmt == 'h5ad' and magic != b'\x89HDF\r\n\x1a\n':
                    raise ValueError()
            total += size
            if total > MAX_OUTPUT:
                raise ValueError()
            expected.add(path.resolve())
            keys.add(key)
        if {p.resolve() for p in directory.iterdir()} != expected:
            raise ValueError()
        return outputs
    except (KeyError, TypeError, ValueError, OSError, OverflowError) as exc:
        raise invalid() from exc


def validate_engine_result(result, directory, *, mode):
    try:
        if (type(result) is not dict or result['engine_version'] != ENGINE_VERSION
                or result['status'] != 'completed' or type(result['manifest']) is not dict
                or type(result['summary']) is not dict or type(result['steps']) is not list):
            raise ValueError()
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(encoded) > MAX_JSON:
            raise ValueError()
        outputs = validate_artifacts(result['outputs'], directory)
        keys = {item['key'] for item in outputs}
        if mode in {'qc', 'compute'}:
            if not {'observation_mask', 'feature_mask', 'raw_axes', 'observations', 'features', 'methods', 'recipe', 'manifest'} <= keys:
                raise ValueError()
        if mode == 'compute' and not {'counts_data', 'counts_indices', 'counts_indptr', 'normalized_data', 'log1p_data', 'pca', 'umap', 'processed', 'markers'} <= keys:
            raise ValueError()
        for step in result['steps']:
            if step['status'] not in {'completed', 'not_computable', 'not_requested'}:
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
        for name in ['counts', 'normalized', 'log1p']:
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


def execute_bio_analysis(payload, output_directory, *, mode='compute', settings=None):
    """A fixed interpreter and script, never a user-selected command or code."""
    if sys.platform != 'linux':
        raise invalid('bio_environment_unavailable')
    interpreter = Path('/opt/paperassist-bio/bin/python')
    output = Path(output_directory).absolute()
    if not interpreter.is_file() or output.is_symlink() or mode not in {'qc', 'compute', 'figure', 'h5_check', 'import_v2'}:
        raise invalid('bio_environment_unavailable')
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise invalid()
    try:
        for record in _input_records(payload):
            path, size = Path(record['path']), record['size_bytes']
            if (not path.is_absolute() or path.is_symlink() or not path.is_file() or path.resolve().is_relative_to(output.resolve())
                    or type(size) is not int or not 0 < size <= MAX_LEAF or path.stat().st_size != size
                    or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']):
                raise ValueError()
        data = json.dumps({**payload, 'mode': mode, 'output_directory': str(output)}, ensure_ascii=False,
                          allow_nan=False, separators=(',', ':')).encode('utf-8')
        if len(data) > MAX_JSON:
            raise ValueError()
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
                    match = re.search(r'^VmRSS:\s+(\d+) kB$', status_path.read_text(), re.M)
                    rss = int(match.group(1)) * 1024 if match else 0
                    peak[0] = max(peak[0], rss)
                    if rss > MAX_RSS:
                        exceeded.set()
                        os.kill(pid, signal.SIGKILL)
                        return
                except (OSError, ValueError, IndexError):
                    return
        thread = Thread(target=monitor, name='bio-analysis-rss', daemon=True)
        monitors.append(thread)
        thread.start()

    command = [str(interpreter), '-I', '-B', str(Path(__file__).with_name('bio_engine') / 'worker.py'), str(os.getpid())]
    try:
        response = _run_child(command, struct.pack('!I', len(data)) + data,
                              timeout_seconds=1380, max_output_bytes=MAX_JSON, on_started=started)
    except StorageError as exc:
        code = 'bio_resource_exceeded' if exceeded.is_set() or exc.code == 'parse_resource_limit' else (
            'bio_analysis_timeout' if exc.code == 'parse_timeout' else 'bio_environment_unavailable')
        raise invalid(code) from exc
    except OSError as exc:
        raise invalid('bio_environment_unavailable') from exc
    finally:
        stopped.set()
        for thread in monitors:
            thread.join(timeout=1)
    if type(response) is not dict:
        raise invalid()
    if set(response) == {'error'}:
        safe = {'bio_environment_unavailable', 'bio_isolation_unavailable', 'bio_resource_exceeded',
                'bio_recipe_invalid', 'bio_input_integrity_changed', 'bio_h5_unsupported',
                'bio_h5_matrix_mismatch', 'bio_insufficient_observations', 'bio_output_invalid'}
        if mode == 'import_v2':
            from app.adapters.bio_parse_process import _ERRORS
            safe |= _ERRORS
        code = response['error'].get('code') if isinstance(response['error'], dict) else None
        raise invalid(code if code in safe else 'bio_output_invalid')
    if set(response) != {'result'}:
        raise invalid()
    if mode == 'import_v2':
        from app.adapters.bio_parse_process import validate_parser_result
        from app.domain.bioinformatics.settings import BioLimits
        result = validate_parser_result(response['result'], output, BioLimits.model_validate(payload['settings']),
                  {item['id'] for item in payload['files']}, expected_parser_version='geo_visium_import_v2')
    else:
        result = validate_engine_result(response['result'], output, mode=mode)
    if mode == 'compute':
        validate_processed_arrays(result['outputs'], target_sum=payload.get('config', {}).get('target_sum', 10000.))
    result.setdefault('resources', {})['parent_peak_rss_bytes'] = peak[0]
    return result

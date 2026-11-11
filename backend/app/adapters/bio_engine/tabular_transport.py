"""Small tabular worker frames referencing bounded, verified attempt files."""

from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile

from app.domain.bioinformatics.settings import BioLimits


MAX_FRAME_BYTES = BioLimits().max_output_json_bytes
MAX_METADATA_BYTES = BioLimits().max_upload_bytes
IMPORT_MANIFEST = '.tabular-import-manifest.json'
_REQUEST_PREFIX = 'tabular-request-'
_ENCODER = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _write_reference(stream, value):
    sha256 = hashlib.sha256()
    size = 0
    for part in _ENCODER.iterencode(value):
        block = part.encode('utf-8')
        size += len(block)
        if size > MAX_METADATA_BYTES:
            raise ValueError('tabular_metadata_limit')
        stream.write(block)
        sha256.update(block)
    return {'path': str(stream.name), 'size_bytes': size, 'sha256': sha256.hexdigest()}


def _read_reference(reference, path):
    size = reference['size_bytes']
    if path.is_symlink() or type(size) is not int or not 0 < size <= MAX_METADATA_BYTES:
        raise ValueError('tabular_request_integrity')
    with path.open('rb') as stream:
        if os.fstat(stream.fileno()).st_size != size:
            raise ValueError('tabular_request_integrity')
        if hashlib.file_digest(stream, 'sha256').hexdigest() != reference['sha256']:
            raise ValueError('tabular_request_integrity')
        stream.seek(0)
        with io.TextIOWrapper(stream, encoding='utf-8') as text:
            return json.load(text)


@contextmanager
def stage_request(request, output):
    """Place large recipes beside the empty output directory for this attempt."""
    output = Path(output).absolute()
    stream = tempfile.NamedTemporaryFile(mode='wb', dir=output.parent, prefix=_REQUEST_PREFIX, suffix='.json', delete=False)
    path = Path(stream.name)
    try:
        with stream:
            reference = _write_reference(stream, request)
        yield _ENCODER.encode({'output_directory': str(output), 'request_ref': reference}).encode('utf-8')
    finally:
        path.unlink(missing_ok=True)


def read_request(frame):
    envelope = json.loads(frame)
    if not isinstance(envelope, dict) or set(envelope) != {'output_directory', 'request_ref'}:
        raise ValueError('tabular_request_integrity')
    output = Path(envelope['output_directory'])
    reference = envelope['request_ref']
    path = Path(reference['path'])
    if (not output.is_absolute() or output.is_symlink() or not output.is_dir()
            or not path.is_absolute() or not path.is_file() or not path.name.startswith(_REQUEST_PREFIX)
            or path.suffix != '.json' or path.resolve().parent != output.resolve().parent):
        raise ValueError('tabular_request_integrity')
    payload = _read_reference(reference, path)
    if payload['output_directory'] != str(output):
        raise ValueError('tabular_request_integrity')
    return payload


def response_result(result, mode):
    if mode == 'import_v3':
        directory = Path(result['outputs'][0]['path']).parent
        with (directory / IMPORT_MANIFEST).open('xb') as stream:
            reference = _write_reference(stream, result['manifest'])
        return {key: value for key, value in result.items() if key != 'manifest'} | {'transport_manifest': reference}
    # Processed results already emit the canonical manifest. Do not send it,
    # its summary or the effective recipe again through stdout.
    return {key: result[key] for key in ('status', 'engine_version', 'outputs', 'checks', 'resources') if key in result} | {
        'manifest_ref': 'manifest',
    }


def take_import_manifest(reference, directory):
    path = Path(directory).absolute() / IMPORT_MANIFEST
    if Path(reference['path']) != path or path.resolve().parent != path.parent.resolve():
        raise ValueError('tabular_request_integrity')
    manifest = _read_reference(reference, path)
    path.unlink()
    return manifest

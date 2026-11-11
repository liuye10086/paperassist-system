"""Bounded serialization shared by tabular output and parent reconciliation."""
from contextlib import contextmanager
import csv
import hashlib
from itertools import chain
import json
import math

import numpy as np

from .manifest import Writer, canonical, clean


_MATRIX_JSON_HEADER = b'{"values":[\n'


def validate_matrix_json(path, parse_json):
    """Validate wide figure JSON in rows. Preexisting compact JSON still loads."""
    with path.open('rb') as stream:
        if stream.read(len(_MATRIX_JSON_HEADER)) != _MATRIX_JSON_HEADER:
            stream.seek(0)
            parse_json(stream.read())
            return
        rows = 0
        width = None
        while True:
            line = stream.readline(4 * 1024**2 + 1)
            if not line.endswith(b'\n'):
                raise ValueError('invalid_matrix_json')
            continues = line.endswith(b',\n')
            row = parse_json(line[:-2] if continues else line[:-1])
            if (not isinstance(row, list) or not row or width not in (None, len(row))
                    or len(row) > 100000 or any(type(value) not in (int, float) or not math.isfinite(value) for value in row)):
                raise ValueError('invalid_matrix_json')
            width = len(row)
            rows += 1
            if rows > 512:
                raise ValueError('invalid_matrix_json')
            if not continues:
                break
        if stream.read(3) != b'],\n':
            raise ValueError('invalid_matrix_json')
        metadata = parse_json(b'{' + stream.read())
        if ('values' in metadata or len(metadata['sample_ids']) != rows or len(metadata['feature_ids']) != width):
            raise ValueError('invalid_matrix_json')


class ArtifactSink:
    def __init__(self, target, limit):
        self.target = target
        self.limit = limit
        self.size = 0
        self.digest = hashlib.sha256()

    def write(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        size = len(data)
        if self.size + size > self.limit:
            raise ValueError('output_budget_exceeded')
        if self.target is not None:
            self.target.write(data)
        self.size += size
        self.digest.update(data)
        return size

    def record(self, key, fmt, role):
        return dict(key=key, role=role or key, format=fmt, size_bytes=self.size, sha256=self.digest.hexdigest())


class TabularWriter(Writer):
    @contextmanager
    def _sink(self, key, fmt, role):
        if not key.replace('_', '').replace('-', '').isalnum():
            raise ValueError('invalid_artifact_key')
        if len(self.artifacts) >= 255:
            raise ValueError('output_budget_exceeded')
        remaining = self.max_output_bytes - sum(leaf['size_bytes'] for leaf in self.artifacts)
        path = self.root / (key + '.' + fmt)
        with path.open('xb') as stream:
            sink = ArtifactSink(stream, min(remaining, 256 * 1024**2))
            yield sink
        self.artifacts.append(dict(sink.record(key, fmt, role), path=str(path)))

    def array(self, key, value):
        if value.dtype.kind == 'O':
            raise ValueError('invalid_output_array')
        if value.dtype.kind in 'fc':
            blocks = np.nditer(value, flags=['external_loop', 'buffered', 'zerosize_ok'], buffersize=131072)
            if any(not np.isfinite(block).all() for block in blocks):
                raise ValueError('invalid_output_array')
        with self._sink(key, 'npy', None) as sink:
            np.save(sink, value, allow_pickle=False)
        return self.artifacts[-1]

    def table(self, key, rows, fields=None):
        rows = iter(rows)
        if not fields:
            first = next(rows, None)
            fields = ['reason'] if first is None else list(first)
            if first is not None:
                rows = chain((first,), rows)
        role = 'marker_table' if key in ('markers', 'markers_top') else 'table'
        with self._sink(key, 'tsv', role) as sink:
            writer = csv.DictWriter(sink, fields, delimiter='\t', lineterminator='\n')
            writer.writeheader()
            for row in rows:
                values = {}
                for field in fields:
                    original = row.get(field)
                    value = clean(original)
                    values[field] = json.dumps(value, ensure_ascii=False) if isinstance(original, (dict, list)) else value
                writer.writerow(values)
        return self.artifacts[-1]

    def matrix_json(self, key, metadata, rows):
        """Serialize the existing figure-data contract one numeric row at a time."""
        if 'values' in metadata:
            raise ValueError('duplicate_matrix_values')
        with self._sink(key, 'json', None) as sink:
            sink.write(_MATRIX_JSON_HEADER)
            for position, row in enumerate(rows):
                if position:
                    sink.write(b',\n')
                sink.write(canonical(row))
            sink.write(b'\n],\n')
            sink.write(canonical(metadata)[1:])
        return self.artifacts[-1]

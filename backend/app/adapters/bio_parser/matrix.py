"""Integer MatrixMarket -> canonical observation-by-feature CSR arrays."""
import io
import re

import numpy as np

from app.domain.bioinformatics.parser_contracts import BioParseError

_INTEGER = re.compile(rb"[0-9]+\Z")


def _integers(line, count):
    values = line.split()
    if len(values) != count or any(not _INTEGER.fullmatch(v) or len(v) > 19 for v in values):
        raise BioParseError("bio_matrix_invalid", "integer_record")
    return tuple(int(v) for v in values)


def parse_matrix(content, n_features, n_observations, limits):
    stream = io.BytesIO(content)
    if stream.readline().strip() != b"%%MatrixMarket matrix coordinate integer general":
        raise BioParseError("bio_matrix_invalid", "matrix_market_header")
    line = stream.readline()
    while line.startswith(b"%"):
        line = stream.readline()
    features, observations, count = _integers(line, 3)
    if not features or not observations:
        raise BioParseError("bio_matrix_invalid", "empty_dimensions")
    if features > limits.max_features or observations > limits.max_observations or count > limits.max_entries:
        raise BioParseError("bio_input_limit", "matrix_dimensions")
    if (features, observations) != (n_features, n_observations):
        raise BioParseError("bio_components_mismatch", "matrix_axis_lengths")
    # Packed row-major coordinates bound memory and detect duplicate coordinates
    # before any sparse constructor could silently sum them.
    keys, counts = np.empty(count, dtype=np.int64), np.empty(count, dtype=np.int64)
    index = 0
    for line in stream:
        if not line.strip() or line.startswith(b"%"):
            continue
        if index >= count:
            raise BioParseError("bio_matrix_invalid", "entry_count")
        feature, observation, value = _integers(line, 3)
        if not 1 <= feature <= features or not 1 <= observation <= observations or value > np.iinfo(np.int64).max:
            raise BioParseError("bio_matrix_invalid", "entry_bounds")
        keys[index] = (observation - 1) * features + feature - 1
        counts[index] = value
        index += 1
    if index != count:
        raise BioParseError("bio_matrix_invalid", "entry_count")
    order = np.argsort(keys, kind="stable")
    keys = keys[order]
    if count > 1 and np.any(keys[1:] == keys[:-1]):
        raise BioParseError("bio_duplicate_coordinate", "duplicate_matrix_coordinate")
    data = counts[order]
    indices = (keys % features).astype(np.int32)
    row_counts = np.bincount(keys // features, minlength=observations)
    indptr = np.zeros(observations + 1, dtype=np.int64)
    np.cumsum(row_counts, out=indptr[1:])
    return data, indices, indptr

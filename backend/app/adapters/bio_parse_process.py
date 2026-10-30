"""Supervised Linux parser transport; Windows has no unsafe fallback."""
import hashlib
import os
from pathlib import Path
import re
import struct
import sys

import numpy as np

from app.adapters.bio_parser.visium import canonical_json
from app.adapters.excel_process import _run_child
from app.core.exceptions import StorageError
from app.domain.bioinformatics.parser_contracts import BioParseError, PARSER_VERSION
from app.domain.bioinformatics.settings import BioLimits

_ERRORS = {"bio_environment_unavailable", "bio_parse_resource_limit", "bio_parse_timeout", "bio_input_limit",
           "bio_archive_invalid", "bio_matrix_invalid", "bio_duplicate_coordinate", "bio_components_mismatch",
           "bio_source_changed", "bio_format_unsupported"}


def _validate_input(manifest, output, limits):
    if type(manifest) is not dict or manifest.get("parser_version") != PARSER_VERSION:
        raise BioParseError("bio_format_unsupported", "parser_version")
    files = manifest.get("files")
    if type(files) is not list or not 1 <= len(files) <= 10:
        raise BioParseError("bio_input_limit", "input_files")
    ids = set()
    for item in files:
        if type(item) is not dict or not {"id", "filename", "path", "sha256", "size_bytes"} <= item.keys():
            raise BioParseError("bio_source_changed", "input_snapshot")
        if (type(item["id"]) is not str or not item["id"] or item["id"] in ids
                or type(item["filename"]) is not str or not item["filename"]
                or type(item["sha256"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
                or type(item["size_bytes"]) is not int or not 0 < item["size_bytes"] <= limits.max_upload_bytes):
            raise BioParseError("bio_source_changed", "input_snapshot")
        path = Path(item["path"])
        if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.resolve() == output:
            raise BioParseError("bio_source_changed", "input_path")
        ids.add(item["id"])
    if output.is_symlink() or not output.is_absolute():
        raise BioParseError("bio_environment_unavailable", "output_directory")


def validate_parser_result(result, output_directory, limits, source_ids, *, expected_parser_version=PARSER_VERSION):
    """Recheck every leaf in the parent before storage may admit a candidate."""
    output = Path(output_directory).resolve()
    try:
        if type(result) is not dict or len(canonical_json(result)) > limits.max_output_json_bytes:
            raise ValueError()
        manifest, entries = result["manifest"], result["outputs"]
        if (result["parser_version"] != expected_parser_version or manifest["parser_version"] != expected_parser_version
                or manifest["schema_version"] != 1 or manifest["storage_format"] != "csr_npy_v1"
                or manifest["matrix_orientation"] != "observations_by_features"
                or type(entries) is not list or not 6 <= len(entries) <= limits.max_members + 6):
            raise ValueError()
        shape = manifest["input_shape"]
        f, o, n = shape["features"], shape["observations"], manifest["stored_entries"]
        if (any(type(v) is not int for v in (f, o, n)) or not 0 < f <= limits.max_features
                or not 0 < o <= limits.max_observations or not 0 <= n <= limits.max_entries
                or (result["n_features"], result["n_observations"], result["entry_count"]) != (f, o, n)):
            raise ValueError()
        keys, actual, total = set(), set(), 0
        for entry in entries:
            key, path = entry["key"], Path(entry["path"])
            if (type(key) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,80}", key) or key in keys
                    or not path.is_absolute() or path.is_symlink() or path.resolve().parent != output
                    or not path.is_file() or path.name != key + "." + entry["format"]
                    or entry["compression"] != "none" or entry["source_file_id"] not in source_ids | {None}
                    or type(entry["size_bytes"]) is not int or not 0 <= entry["size_bytes"] <= limits.max_member_bytes
                    or path.stat().st_size != entry["size_bytes"]):
                raise ValueError()
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(65536), b""):
                    digest.update(block)
            if digest.hexdigest() != entry["sha256"]:
                raise ValueError()
            total += entry["size_bytes"]
            keys.add(key)
            actual.add(path.resolve())
        if total > limits.max_expanded_bytes or {p.resolve() for p in output.iterdir()} != actual:
            raise ValueError()
        if manifest["members"] != [{k: v for k, v in entry.items() if k != "path"} for entry in entries]:
            raise ValueError()
        arrays = {entry["key"]: np.load(entry["path"], allow_pickle=False, mmap_mode="r")
                  for entry in entries if entry["key"] in {"matrix_data", "matrix_indices", "matrix_indptr"}}
        data, indices, indptr = (arrays[k] for k in ("matrix_data", "matrix_indices", "matrix_indptr"))
        if (data.shape != (n,) or indices.shape != (n,) or indptr.shape != (o + 1,)
                or data.dtype != np.dtype("int64") or indices.dtype != np.dtype("int32")
                or indptr.dtype != np.dtype("int64") or indptr[0] != 0 or indptr[-1] != n
                or np.any(indptr[1:] < indptr[:-1]) or np.any(data < 0)
                or np.any(indices < 0) or np.any(indices >= f)):
            raise ValueError()
        for start, end in zip(indptr[:-1], indptr[1:]):
            if np.any(indices[start + 1:end] <= indices[start:end - 1]) if end - start > 1 else False:
                raise ValueError()
        return result
    except (KeyError, TypeError, ValueError, OSError, OverflowError):
        raise BioParseError("bio_source_changed", "parser_output_invalid") from None


def parse_bio_isolated(input_manifest, output_directory, settings):
    if sys.platform != "linux":
        raise BioParseError("bio_environment_unavailable")
    limits = settings if isinstance(settings, BioLimits) else BioLimits.model_validate(settings)
    output = Path(output_directory).absolute()
    _validate_input(input_manifest, output, limits)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise BioParseError("bio_environment_unavailable", "output_must_be_empty")
    payload = canonical_json({"input_manifest": input_manifest, "output_directory": str(output),
                              "settings": limits.model_dump()})
    if len(payload) > 65536:
        raise BioParseError("bio_input_limit", "input_manifest")
    command = [sys.executable, "-I", "-B", str(Path(__file__).with_name("bio_parser") / "worker.py"), str(os.getpid())]
    try:
        response = _run_child(command, struct.pack("!I", len(payload)) + payload,
                              timeout_seconds=limits.timeout_seconds, max_output_bytes=limits.max_output_json_bytes)
    except StorageError as exc:
        mapping = {"parse_timeout": "bio_parse_timeout", "parse_resource_limit": "bio_parse_resource_limit",
                   "parse_environment_unavailable": "bio_environment_unavailable"}
        raise BioParseError(mapping.get(exc.code, "bio_environment_unavailable")) from None
    except OSError:
        raise BioParseError("bio_environment_unavailable") from None
    if type(response) is dict and set(response) == {"error"}:
        code = response["error"].get("code") if type(response["error"]) is dict else None
        raise BioParseError(code if code in _ERRORS else "bio_environment_unavailable")
    if type(response) is not dict or set(response) != {"result"}:
        raise BioParseError("bio_source_changed", "parser_output_invalid")
    return validate_parser_result(response["result"], output, limits, {item["id"] for item in input_manifest["files"]})

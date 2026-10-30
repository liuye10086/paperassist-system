"""Fixed CR-B01 single-GSM Visium structural parser. No scientific processing."""
from collections import Counter
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re

import numpy as np
import PIL
import pydantic

from app.adapters.bio_parser.archive import Budget, unpack
from app.adapters.bio_parser.geo import parse_geo
from app.adapters.bio_parser.images import check_image_bounds, inspect_image
from app.adapters.bio_parser.matrix import parse_matrix
from app.domain.bioinformatics.parser_contracts import BioParseError, BioParseResult, PARSER_VERSION
from app.domain.bioinformatics.settings import BioLimits

POSITION_COLUMNS = ["barcode", "in_tissue", "array_row", "array_col", "pxl_row_in_fullres", "pxl_col_in_fullres"]
SCALE_FIELDS = {"tissue_hires_scalef", "tissue_lowres_scalef", "spot_diameter_fullres", "fiducial_diameter_fullres"}
COMPONENT_ROLES = {"matrix", "features", "barcodes", "positions", "scalefactors", "tissue_image", "qc_image",
                   "alternate_matrix", "geo_metadata", "package_listing", "supplementary"}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def strict_json(content):
    return json.loads(content, object_pairs_hook=_strict_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))


def _text(content):
    try:
        return content.decode("utf-8-sig")
    except UnicodeError:
        raise BioParseError("bio_components_mismatch", "text_encoding") from None


def _role(member):
    if member.declared_role is not None:
        return member.declared_role
    name = re.sub(r"\.gz$", "", member.name.lower())
    if member.content.startswith(b"%%MatrixMarket") or name.endswith(".mtx"):
        return "matrix"
    if name.endswith(("features.tsv", "genes.tsv")):
        return "features"
    if name.endswith("barcodes.tsv"):
        return "barcodes"
    if name.endswith(("tissue_positions_list.csv", "tissue_positions.csv")):
        return "positions"
    if name.endswith(("scalefactors_json.json", "scalefactors.json")):
        return "scalefactors"
    if member.content.startswith(b"\x89HDF\r\n\x1a\n"):
        return "alternate_matrix"
    if name.endswith((".h5", ".hdf5")):
        raise BioParseError("bio_components_mismatch", "hdf5_magic")
    if name.endswith((".png", ".jpg", ".jpeg")):
        return "tissue_image" if "tissue_" in name else "qc_image"
    if (name.endswith((".soft", ".xml")) or "series_matrix" in name
            or member.content.lstrip().startswith((b"^DATABASE", b"^SERIES", b"^SAMPLE", b"!Series_", b"<?xml"))):
        return "geo_metadata"
    if "filelist" in name:
        return "package_listing"
    return "supplementary"


def _features(member, limits):
    rows = []
    try:
        for row in csv.reader(io.StringIO(_text(member.content)), delimiter="\t"):
            if len(rows) >= limits.max_features:
                raise BioParseError("bio_input_limit", "features")
            rows.append(row)
    except csv.Error:
        raise BioParseError("bio_components_mismatch", "feature_columns") from None
    if not rows or any(len(row) not in (2, 3) or not row[0] or not row[1] for row in rows):
        raise BioParseError("bio_components_mismatch", "feature_columns")
    ids, symbols = [r[0] for r in rows], [r[1] for r in rows]
    if len(ids) != len(set(ids)):
        raise BioParseError("bio_components_mismatch", "duplicate_feature_id")
    return ids, symbols, [r[2] if len(r) == 3 else None for r in rows]


def _barcodes(member, limits):
    rows = []
    try:
        for row in csv.reader(io.StringIO(_text(member.content)), delimiter="\t"):
            if len(rows) >= limits.max_observations:
                raise BioParseError("bio_input_limit", "observations")
            rows.append(row)
    except csv.Error:
        raise BioParseError("bio_components_mismatch", "barcode_columns") from None
    if not rows or any(len(row) != 1 or not row[0] for row in rows):
        raise BioParseError("bio_components_mismatch", "barcode_columns")
    barcodes = [r[0] for r in rows]
    if len(barcodes) != len(set(barcodes)):
        raise BioParseError("bio_components_mismatch", "duplicate_barcode")
    return barcodes


def _positions(member, limits):
    rows = csv.reader(io.StringIO(_text(member.content)))
    first = next(rows, None)
    if first is None:
        raise BioParseError("bio_components_mismatch", "positions_empty")
    if first[0] == "barcode":
        if first != POSITION_COLUMNS:
            raise BioParseError("bio_components_mismatch", "position_columns")
        source = rows
    else:
        import itertools
        source = itertools.chain([first], rows)
    positions, seen = [], set()
    for row in source:
        if len(positions) >= limits.max_observations:
            raise BioParseError("bio_input_limit", "positions")
        if len(row) != 6 or not row[0] or row[0] in seen:
            raise BioParseError("bio_components_mismatch", "position_barcodes")
        try:
            values = [int(value) for value in row[1:]]
        except ValueError:
            raise BioParseError("bio_components_mismatch", "position_values") from None
        if values[0] not in (0, 1) or any(value < 0 for value in values):
            raise BioParseError("bio_components_mismatch", "position_values")
        seen.add(row[0])
        positions.append(dict(zip(POSITION_COLUMNS, [row[0], *values])))
    return positions


def _scales(member):
    try:
        value = strict_json(member.content)
        if type(value) is not dict or not value or set(value) - SCALE_FIELDS:
            raise ValueError()
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in value.values()):
            raise ValueError()
        return value
    except (ValueError, UnicodeError, OverflowError):
        raise BioParseError("bio_components_mismatch", "scalefactors") from None


def parser_fingerprint():
    digest = hashlib.sha256()
    for filename in ("archive.py", "geo.py", "images.py", "matrix.py", "visium.py", "sandbox.py", "worker.py"):
        digest.update(filename.encode())
        digest.update(Path(__file__).with_name(filename).read_bytes())
    return digest.hexdigest()


# Trusted source is fingerprinted at preload, before filesystem sandbox entry.
_PARSER_FINGERPRINT = parser_fingerprint()


def parse_registered_files(files, destination: Path, limits: BioLimits):
    """Trusted worker helper, not an HTTP path API. Every snapshot is rehashed."""
    budget, members, inputs = Budget(limits), [], []
    if not files or len(files) > 10:
        raise BioParseError("bio_input_limit", "input_files")
    for item in files:
        path = Path(item["path"])
        if path.is_symlink() or not path.is_file() or path.stat().st_size != item["size_bytes"]:
            raise BioParseError("bio_source_changed", "source_size")
        if item["size_bytes"] > limits.max_upload_bytes:
            raise BioParseError("bio_input_limit", "upload_bytes")
        with path.open("rb") as stream:
            content = stream.read(limits.max_upload_bytes + 1)
        if len(content) != item["size_bytes"]:
            raise BioParseError("bio_source_changed", "source_size")
        if hashlib.sha256(content).hexdigest() != item["sha256"]:
            raise BioParseError("bio_source_changed", "source_sha256")
        declared = item.get("role", "auto")
        if declared not in COMPONENT_ROLES | {"auto", "archive"}:
            raise BioParseError("bio_format_unsupported", "declared_role")
        container = item["filename"].lower().endswith((".tar", ".tar.gz", ".tgz")) or (len(content) >= 262 and content[257:262] == b"ustar")
        if (container and declared not in {"auto", "archive"}) or (declared == "archive" and not container):
            raise BioParseError("bio_components_mismatch", "archive_role")
        unpacked = unpack(content, item["filename"], budget, item["id"])
        if declared in COMPONENT_ROLES:
            if len(unpacked) != 1:
                raise BioParseError("bio_components_mismatch", "component_role")
            unpacked[0].declared_role = declared
        members.extend(unpacked)
        inputs.append({k: item[k] for k in ("id", "filename", "size_bytes", "sha256")})
    return _parse_members(members, Path(destination), limits, budget, inputs)


def parse_visium_bundle(bundle: bytes, destination: Path, limits: BioLimits) -> BioParseResult:
    budget = Budget(limits)
    return _parse_members(unpack(bundle, "input.tar", budget), Path(destination), limits, budget, [])


def _parse_members(members, destination, limits, budget, inputs):
    grouped, resolved, accessions = {}, [], {"gse": set(), "gsm": set()}
    metadata, empty_series = [], False
    for member in members:
        role = _role(member)
        if role == "alternate_matrix" and not member.content.startswith(b"\x89HDF\r\n\x1a\n"):
            raise BioParseError("bio_components_mismatch", "hdf5_magic")
        # Pair only components from a single GSM. Metadata may include GEO URLs
        # but never creates an additional biological sample.
        if role in {"matrix", "features", "barcodes", "positions", "scalefactors", "alternate_matrix", "tissue_image"}:
            accessions["gsm"].update(re.findall(r"\bGSM[0-9]+(?=[_./-]|$)", member.name))
        if role == "geo_metadata":
            entry = parse_geo(member.content, re.sub(r"\.gz$", "", member.name, flags=re.I))
            metadata.append(entry)
            for key, values in entry["accessions"].items():
                accessions[key].update(values)
            empty_series |= entry["empty_series_matrix"]
        # Images are independent roles keyed by their declared resolution/name.
        slot = role if role not in {"tissue_image", "qc_image", "geo_metadata", "package_listing", "supplementary", "alternate_matrix"} else role + ":" + re.sub(r"^GSM[0-9]+[_-]", "", member.name.rsplit("/", 1)[-1])
        if slot in grouped:
            if grouped[slot].content != member.content:
                raise BioParseError("bio_components_mismatch", "conflicting_role")
        else:
            grouped[slot] = member
        resolved.append((role, member))
    if len(accessions["gsm"]) > 1 or len(accessions["gse"]) > 1:
        raise BioParseError("bio_components_mismatch", "multiple_accessions")
    if any(role not in grouped for role in ("matrix", "features", "barcodes", "positions", "scalefactors")):
        raise BioParseError("bio_components_mismatch", "missing_visium_components")
    ids, symbols, feature_types = _features(grouped["features"], limits)
    barcodes = _barcodes(grouped["barcodes"], limits)
    data, indices, indptr = parse_matrix(grouped["matrix"].content, len(ids), len(barcodes), limits)
    positions, scales = _positions(grouped["positions"], limits), _scales(grouped["scalefactors"])
    position_barcodes = {p["barcode"] for p in positions}
    if not set(barcodes) <= position_barcodes:
        raise BioParseError("bio_components_mismatch", "missing_matrix_positions")
    in_tissue = [p["barcode"] for p in positions if p["in_tissue"] == 1]
    image_info = []
    for role, member in resolved:
        if role not in {"tissue_image", "qc_image"}:
            continue
        info = inspect_image(member.content, limits, budget)
        scale_key = "tissue_hires_scalef" if "hires" in member.name else "tissue_lowres_scalef" if "lowres" in member.name else None
        if role == "tissue_image" and scale_key:
            if scale_key not in scales:
                raise BioParseError("bio_components_mismatch", "missing_image_scale")
            check_image_bounds(positions, scales[scale_key], info)
        image_info.append({"source_member_name": member.name, **info, "scale_field": scale_key})
    if not any(role == "tissue_image" for role, _ in resolved):
        raise BioParseError("bio_components_mismatch", "missing_tissue_image")
    source_accessions = {key: next(iter(values), None) for key, values in accessions.items()}
    duplicate_groups = sum(count > 1 for count in Counter(symbols).values())
    alternate_h5 = "internal_not_checked" if any(r == "alternate_matrix" for r, _ in resolved) else "not_provided"
    checks = {"structure": "checked", "duplicate_symbol_groups": duplicate_groups,
              "positions_count": len(positions), "in_tissue_count": len(in_tissue),
              "matrix_matches_in_tissue": set(barcodes) == set(in_tissue),
              "matrix_barcodes_in_positions": True, "alternate_h5": alternate_h5,
              "empty_series_matrix": empty_series, "source_accessions": source_accessions,
              "warnings": (["duplicate_feature_symbols_preserved"] if duplicate_groups else []) +
                          (["matrix_barcodes_differ_from_in_tissue"] if set(barcodes) != set(in_tissue) else [])}
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise BioParseError("bio_archive_invalid", "output_directory")
    outputs = []

    def write(key, content, role, fmt, source=None, state="verified"):
        suffix = "." + fmt
        path = destination / (key + suffix)
        # Refuse preexisting symlinks; workers always receive a fresh directory.
        if path.is_symlink():
            raise BioParseError("bio_archive_invalid", "output_symlink")
        path.write_bytes(content)
        outputs.append({"key": key, "role": role, "format": fmt, "compression": "none",
                        "verification_state": state, "path": str(path.resolve()),
                        "source_file_id": source.source_file_id if source else None,
                        "source_member_name": source.name if source else None,
                        "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)})

    for key, array in (("matrix_data", data), ("matrix_indices", indices), ("matrix_indptr", indptr)):
        stream = io.BytesIO()
        np.save(stream, array, allow_pickle=False)
        write(key, stream.getvalue(), key, "npy", grouped["matrix"])
    write("features_index", canonical_json({"feature_ids": ids, "feature_symbols": symbols,
                                            "feature_types": feature_types}), "features_index", "json", grouped["features"])
    write("barcodes_index", canonical_json({"barcodes": barcodes}), "barcodes_index", "json", grouped["barcodes"])
    write("positions_index", canonical_json(positions), "positions_index", "json", grouped["positions"])
    for ordinal, (role, member) in enumerate(sorted(resolved, key=lambda x: (x[0], x[1].source_file_id or "", x[1].name))):
        # Keep every representation and original decoded member bytes, including
        # H5 and metadata; none is silently promoted to an expression source.
        fmt = "mtx" if role == "matrix" else "h5" if role == "alternate_matrix" else "json" if role == "scalefactors" else "png" if member.content.startswith(b"\x89PNG") else "jpeg" if member.content.startswith(b"\xff\xd8") else "tsv" if role in {"features", "barcodes"} else "csv" if role == "positions" else "txt"
        write(f"source_{ordinal:03d}", member.content, role, fmt, member,
              "internal_not_checked" if role == "alternate_matrix" else "verified" if role != "supplementary" else "not_checked")
    manifest = {"schema_version": 1, "parser_version": PARSER_VERSION,
        "parser_fingerprint": _PARSER_FINGERPRINT, "assay": "visium",
        "source_accessions": source_accessions, "input_shape": {"features": len(ids), "observations": len(barcodes)},
        "input_orientation": "features_by_observations", "matrix_orientation": "observations_by_features",
        "transposed": True, "stored_entries": int(data.size), "storage_format": "csr_npy_v1",
        "matrix_dtypes": {"data": "int64", "indices": "int32", "indptr": "int64"},
        "processing": {"normalized": False, "filtered_by_this_system": False},
        "verification": {"structure": "checked", "alternate_h5": alternate_h5, "study_design": "pending"},
        "source_files": inputs, "members": [{k: v for k, v in out.items() if k != "path"} for out in outputs],
        "spatial": {"columns": POSITION_COLUMNS, "coordinate_transform": {"x": "pxl_col_in_fullres*image_scalef", "y": "pxl_row_in_fullres*image_scalef"},
                    "scalefactors": scales, "images": image_info, "positions_count": len(positions),
                    "in_tissue_count": len(in_tissue), "matrix_matches_in_tissue": checks["matrix_matches_in_tissue"]},
        "checks": checks, "parse_settings": limits.model_dump(), "metadata": metadata,
        "tools": {"numpy": np.__version__, "pillow": PIL.__version__, "pydantic": pydantic.__version__}}
    return BioParseResult(len(ids), len(barcodes), int(data.size), ids, symbols, barcodes, in_tissue, checks, outputs, manifest)

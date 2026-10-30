import gzip
import hashlib
import io
import json
import sys
import tarfile

import numpy as np
import pytest

from tests.helpers.bio_fixtures import bundle_from_parts, visium_bundle_bytes, visium_parts


def parse(bundle, tmp_path, **overrides):
    from app.adapters.bio_parser.visium import parse_visium_bundle
    from app.domain.bioinformatics.settings import BioLimits
    return parse_visium_bundle(bundle, tmp_path, BioLimits(**overrides))


def test_preserves_counts_axes_and_duplicate_symbols(tmp_path):
    result = parse(visium_bundle_bytes(), tmp_path)
    assert (result.n_features, result.n_observations, result.entry_count) == (3, 2, 4)
    assert result.feature_ids == ["ENSG_TEST_1", "ENSG_TEST_2", "ENSG_TEST_3"]
    assert result.feature_symbols == ["G1", "SAME", "SAME"]
    assert result.barcodes == ["AA-1", "BB-1"]
    assert result.in_tissue_barcodes == ["AA-1", "BB-1"]
    assert result.checks["duplicate_symbol_groups"] == 1
    assert result.checks["positions_count"] == 3
    arrays = {o["key"]: np.load(o["path"], allow_pickle=False, mmap_mode="r")
              for o in result.outputs if o["key"].startswith("matrix_")}
    assert arrays["matrix_data"].tolist() == [5, 2, 1, 4]
    assert arrays["matrix_indices"].tolist() == [0, 1, 0, 2]
    assert arrays["matrix_indptr"].tolist() == [0, 2, 4]
    assert arrays["matrix_data"].dtype == np.dtype("int64")


@pytest.mark.parametrize("kwargs,code", [
    ({"unsafe_name": "../outside"}, "bio_archive_invalid"),
    ({"unsafe_name": "C:/outside"}, "bio_archive_invalid"),
    ({"unsafe_name": "/outside"}, "bio_archive_invalid"),
    ({"duplicate_coordinate": True}, "bio_duplicate_coordinate"),
    ({"missing_barcode": True}, "bio_components_mismatch"),
    ({"changes": {"features.tsv": b"a\tA\na\tB\nc\tC\n"}}, "bio_components_mismatch"),
    ({"changes": {"barcodes.tsv": b"AA-1\nAA-1\n"}}, "bio_components_mismatch"),
    ({"changes": {"tissue_positions_list.csv": b"AA-1,1,0,0,2,2\n"}}, "bio_components_mismatch"),
    ({"changes": {"matrix.mtx": b"%%MatrixMarket matrix coordinate real general\n3 2 0\n"}}, "bio_matrix_invalid"),
    ({"changes": {"matrix.mtx": b"%%MatrixMarket matrix coordinate integer general\n3 2 1\n1 1 -1\n"}}, "bio_matrix_invalid"),
    ({"changes": {"matrix.mtx": b"%%MatrixMarket matrix coordinate integer general\n3 2 1\n4 1 1\n"}}, "bio_matrix_invalid"),
    ({"changes": {"matrix.mtx": b"%%MatrixMarket matrix coordinate integer general\n3 2 2\n1 1 1\n"}}, "bio_matrix_invalid"),
    ({"changes": {"matrix.mtx": None}}, "bio_components_mismatch"),
    ({"changes": {"scalefactors_json.json": b'{"tissue_hires_scalef":NaN}'}}, "bio_components_mismatch"),
    ({"changes": {"scalefactors_json.json": b'{"unknown":1}'}}, "bio_components_mismatch"),
    ({"changes": {"tissue_hires_image.png": b"not a PNG"}}, "bio_components_mismatch"),
])
def test_rejects_invalid_inputs(tmp_path, kwargs, code):
    from app.domain.bioinformatics.parser_contracts import BioParseError
    with pytest.raises(BioParseError) as caught:
        parse(visium_bundle_bytes(**kwargs), tmp_path)
    assert caught.value.code == code


@pytest.mark.parametrize("limits", [{"max_upload_bytes": 30}, {"max_members": 1},
    {"max_member_bytes": 40}, {"max_expanded_bytes": 200}, {"max_entries": 3},
    {"max_features": 2}, {"max_observations": 1}, {"max_image_pixels": 20}])
def test_limits_checked_before_allocation(tmp_path, limits):
    from app.domain.bioinformatics.parser_contracts import BioParseError
    with pytest.raises(BioParseError) as caught:
        parse(visium_bundle_bytes(), tmp_path, **limits)
    assert caught.value.code == "bio_input_limit"


def test_rejects_links_normalized_duplicates_and_crc(tmp_path):
    from app.domain.bioinformatics.parser_contracts import BioParseError
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        link = tarfile.TarInfo("link")
        link.type, link.linkname = tarfile.SYMTYPE, "outside"
        archive.addfile(link)
    invalids = [output.getvalue(), bundle_from_parts({"a/b": b"1", "a\\b": b"2"}),
                bundle_from_parts({"a.txt.gz": gzip.compress(b"x")[:-2] + b"xx"}),
                bundle_from_parts({"a.gz": gzip.compress(gzip.compress(gzip.compress(b"x")))})]
    for bundle in invalids:
        with pytest.raises(BioParseError) as caught:
            parse(bundle, tmp_path)
        assert caught.value.code == "bio_archive_invalid"


def test_new_positions_header_and_h5_are_preserved_without_reading(tmp_path):
    result = parse(visium_bundle_bytes(changes={
        "tissue_positions_list.csv": None,
        "tissue_positions.csv": b"barcode,in_tissue,array_row,array_col,pxl_row_in_fullres,pxl_col_in_fullres\nAA-1,1,0,0,2,3\nBB-1,1,1,1,4,5\nCC-1,0,2,2,6,7\n",
        "filtered_feature_bc_matrix.h5": b"\x89HDF\r\n\x1a\nnot-an-internally-validated-H5",
    }), tmp_path)
    assert result.checks["alternate_h5"] == "internal_not_checked"
    h5 = next(o for o in result.outputs if o["role"] == "alternate_matrix")
    assert h5["verification_state"] == "internal_not_checked"
    index = next(o for o in result.outputs if o["key"] == "positions_index")
    assert json.loads(open(index["path"], encoding="utf-8").read())[0]["pxl_col_in_fullres"] == 3


def test_metadata_empty_matrix_and_single_gsm(tmp_path):
    from app.domain.bioinformatics.parser_contracts import BioParseError
    parts = visium_parts()
    parts["series_matrix.txt"] = b'!Series_geo_accession = "GSE9999999"\n!Sample_geo_accession = "GSM9999999"\n!series_matrix_table_begin\n"ID_REF"\t"GSM9999999"\n!series_matrix_table_end\n'
    bundle = bundle_from_parts({"GSM9999999_" + k: v for k, v in parts.items()})
    result = parse(bundle, tmp_path)
    assert result.checks["source_accessions"] == {"gse": "GSE9999999", "gsm": "GSM9999999"}
    assert result.checks["empty_series_matrix"] is True
    with pytest.raises(BioParseError) as caught:
        parse(bundle_from_parts({"GSM1111111_matrix.mtx": parts["matrix.mtx"],
                                 "GSM2222222_features.tsv": parts["features.tsv"]}), tmp_path)
    assert caught.value.code == "bio_components_mismatch"


def test_isolated_entry_fails_closed_on_windows(tmp_path):
    from app.adapters.bio_parse_process import parse_bio_isolated
    from app.domain.bioinformatics.parser_contracts import BioParseError
    from app.domain.bioinformatics.settings import BioLimits
    if sys.platform == "linux":
        pytest.skip("Windows fail-closed assertion")
    with pytest.raises(BioParseError) as caught:
        parse_bio_isolated({"files": []}, tmp_path, BioLimits())
    assert caught.value.code == "bio_environment_unavailable"


def test_registered_files_verify_identity_and_equivalent_metadata(tmp_path):
    from app.adapters.bio_parser.visium import parse_registered_files
    from app.domain.bioinformatics.settings import BioLimits
    from app.domain.bioinformatics.parser_contracts import BioParseError
    metadata = b'^SERIES = GSE9999999\n^SAMPLE = GSM9999999\n'
    inputs = []
    for filename, content in [("RAW.tar", visium_bundle_bytes()), ("family.soft", metadata),
                              ("family.soft.gz", gzip.compress(metadata, mtime=0))]:
        path = tmp_path / filename
        path.write_bytes(content)
        inputs.append({"id": filename, "filename": filename, "path": str(path),
                       "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)})
    result = parse_registered_files(inputs, tmp_path / "result", BioLimits())
    assert result.manifest["source_accessions"] == {"gse": "GSE9999999", "gsm": "GSM9999999"}
    assert len(result.manifest["source_files"]) == 3
    assert {o["source_file_id"] for o in result.outputs} == {"RAW.tar", "family.soft", "family.soft.gz"}
    assert any(o["source_member_name"].endswith("matrix.mtx.gz") for o in result.outputs)
    (tmp_path / "family.soft").write_bytes(b"x" * len(metadata))
    with pytest.raises(BioParseError) as caught:
        parse_registered_files(inputs, tmp_path / "changed", BioLimits())
    assert caught.value.code == "bio_source_changed"


def test_rejects_entity_xml_and_conflicting_roles(tmp_path):
    from app.domain.bioinformatics.parser_contracts import BioParseError
    for changes in [{"family.xml": b'<!DOCTYPE a [<!ENTITY b "bad">]><a>&b;</a>'},
                    {"other/features.tsv": b"different\tX\n"}]:
        with pytest.raises(BioParseError) as caught:
            parse(visium_bundle_bytes(changes=changes), tmp_path)
        assert caught.value.code in {"bio_archive_invalid", "bio_components_mismatch"}


def test_zero_entries_remain_stored_and_axis_order_is_preserved(tmp_path):
    result = parse(visium_bundle_bytes(changes={"matrix.mtx": b"%%MatrixMarket matrix coordinate integer general\n3 2 3\n3 2 0\n1 2 2\n2 1 6\n"}), tmp_path)
    arrays = {o["key"]: np.load(o["path"], allow_pickle=False) for o in result.outputs if o["key"].startswith("matrix_")}
    assert result.entry_count == 3
    assert arrays["matrix_data"].tolist() == [6, 2, 0]
    assert arrays["matrix_indices"].tolist() == [1, 0, 2]


def test_report_records_parser_fingerprint(tmp_path):
    result = parse(visium_bundle_bytes(), tmp_path)
    assert len(result.manifest["parser_fingerprint"]) == 64


def test_worker_preloads_codec_before_filesystem_isolation():
    import subprocess
    process = subprocess.run([sys.executable, "-c",
        "import sys; from app.adapters.bio_parser.worker import preload_runtime; preload_runtime(); "
        "assert 'encodings.utf_8_sig' in sys.modules"], capture_output=True, text=True)
    assert process.returncode == 0, process.stderr


def test_registered_roles_are_honored_or_rejected_explicitly(tmp_path):
    from app.adapters.bio_parser.visium import parse_registered_files
    from app.domain.bioinformatics.settings import BioLimits
    from app.domain.bioinformatics.parser_contracts import BioParseError
    content = visium_bundle_bytes()
    path = tmp_path / "input.tar"
    path.write_bytes(content)
    source = dict(id="raw", filename="input.tar", path=str(path), sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content))
    for role in ("invented_role", "matrix"):
        with pytest.raises(BioParseError):
            parse_registered_files([{**source, "role": role}], tmp_path / role, BioLimits())
    result = parse_registered_files([{**source, "role": "archive"}], tmp_path / "archive", BioLimits())
    assert result.entry_count == 4
    files = []
    for ordinal, (name, body) in enumerate(visium_parts().items()):
        renamed = "counts.bin" if name == "matrix.mtx" else name
        component = tmp_path / renamed
        component.write_bytes(body)
        files.append(dict(id=str(ordinal), filename=renamed, path=str(component),
                          sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body),
                          role="matrix" if renamed == "counts.bin" else "auto"))
    assert parse_registered_files(files, tmp_path / "components", BioLimits()).entry_count == 4


@pytest.mark.skipif(sys.platform != "linux", reason="requires actual Linux sandbox")
def test_linux_isolated_structural_fixture(tmp_path):
    from app.adapters.bio_parse_process import parse_bio_isolated
    from app.domain.bioinformatics.settings import BioLimits
    content = visium_bundle_bytes()
    path = tmp_path / "source.tar"
    path.write_bytes(content)
    result = parse_bio_isolated({"parser_version": "geo_visium_import_v1", "files": [dict(
        id="source", filename="source.tar", path=str(path), sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content), role="archive")]}, tmp_path / "output", BioLimits())
    assert (result["n_features"], result["n_observations"], result["entry_count"]) == (3, 2, 4)
    assert result["manifest"]["processing"]["normalized"] is False

import hashlib
import json

from tests.helpers.bio_fixtures import visium_bundle_bytes


def test_outputs_are_deterministic_and_manifest_does_not_leak_paths(tmp_path):
    from app.adapters.bio_parser.visium import parse_visium_bundle
    from app.domain.bioinformatics.settings import BioLimits
    first = parse_visium_bundle(visium_bundle_bytes(), tmp_path / "one", BioLimits())
    second = parse_visium_bundle(visium_bundle_bytes(), tmp_path / "two", BioLimits())
    assert first.manifest == second.manifest
    assert first.manifest["matrix_orientation"] == "observations_by_features"
    assert first.manifest["processing"] == {"normalized": False, "filtered_by_this_system": False}
    assert first.manifest["input_shape"] == {"features": 3, "observations": 2}
    assert first.manifest["stored_entries"] == 4
    assert str(tmp_path) not in json.dumps(first.manifest)
    assert [(o["key"], o["sha256"]) for o in first.outputs] == [(o["key"], o["sha256"]) for o in second.outputs]
    for output in first.outputs:
        data = open(output["path"], "rb").read()
        assert output["size_bytes"] == len(data)
        assert output["sha256"] == hashlib.sha256(data).hexdigest()


def test_frozen_limits_are_strict_and_only_tightenable():
    import pytest
    from pydantic import ValidationError
    from app.domain.bioinformatics.settings import BioLimits
    for value in ({"max_features": "2"}, {"max_features": True}, {"max_features": 100001}, {"extra": 1}):
        with pytest.raises(ValidationError):
            BioLimits(**value)
    with pytest.raises(ValidationError):
        BioLimits().max_features = 2


def test_parent_rechecks_outputs_and_detects_tampering(tmp_path):
    import copy
    import pytest
    from app.adapters.bio_parse_process import validate_parser_result
    from app.adapters.bio_parser.visium import parse_visium_bundle
    from app.domain.bioinformatics.parser_contracts import BioParseError
    from app.domain.bioinformatics.settings import BioLimits
    result = parse_visium_bundle(visium_bundle_bytes(), tmp_path, BioLimits()).summary()
    assert validate_parser_result(result, tmp_path, BioLimits(), set()) == result
    for modify in (lambda r: r["outputs"][0].update(path=str(tmp_path.parent / "escape.npy")),
                   lambda r: r["outputs"][0].update(sha256="0" * 64),
                   lambda r: r["manifest"].update(stored_entries=999)):
        tampered = copy.deepcopy(result)
        modify(tampered)
        with pytest.raises(BioParseError) as caught:
            validate_parser_result(tampered, tmp_path, BioLimits(), set())
        assert caught.value.code == "bio_source_changed"
    (tmp_path / "extra").write_bytes(b"unreported")
    with pytest.raises(BioParseError):
        validate_parser_result(result, tmp_path, BioLimits(), set())

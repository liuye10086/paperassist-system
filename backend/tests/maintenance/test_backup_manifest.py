"""Small offline fixtures; never connect to a source database or start PostgreSQL."""
import json
from uuid import uuid4
import pytest
from app.maintenance import recovery_drill as drill


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def module():
    from app.maintenance import backup_manifest
    return backup_manifest


def test_manifest_preserves_hidden_evidence_and_rejects_changed_missing_duplicate_and_unsafe(tmp_path):
    m = module()
    (tmp_path / '.storage-intents').mkdir()
    path = tmp_path / '.storage-intents' / 'one.complete.json'
    path.write_bytes(b'original immutable receipt')
    entries = m.file_manifest(tmp_path)
    assert entries[0]['path'] == '.storage-intents/one.complete.json'
    assert m.validate_files(tmp_path, entries) == entries
    for bad in ([*entries, *entries], [{**entries[0], 'path': '../escape'}], [{**entries[0], 'sha256': 'a' * 64}]):
        with pytest.raises(drill.DrillError):
            m.validate_files(tmp_path, bad)
    path.unlink()
    with pytest.raises(drill.DrillError):
        m.validate_files(tmp_path, entries)


def test_receipt_is_whitelisted_and_wrong_source_or_invalid_is_unknown(tmp_path):
    m = module()
    schema = 'pa_test_' + uuid4().hex
    path = tmp_path / 'status.json'
    assert m.status_summary(path, schema)['status'] == 'unavailable'
    value = m.result_summary(schema)
    value['secret'] = 'private-path-and-password'
    path.write_text(json.dumps(value))
    safe = m.status_summary(path, schema)
    assert safe['status'] == 'available' and 'secret' not in safe
    assert 'private-path' not in json.dumps(safe)
    assert m.status_summary(path, 'pa_test_' + uuid4().hex)['status'] == 'unavailable'
    value['restore']['status'] = 'success-with-secret'
    path.write_text(json.dumps(value))
    assert m.status_summary(path, schema)['restore']['status'] == 'unknown'


def test_archive_rejects_other_schema_and_current_target_reuse(tmp_path):
    m = module()
    schema = 'pa_test_' + uuid4().hex
    m.validate_archive(f'1; 2615 22 SCHEMA - {schema} owner\n2; 1259 33 TABLE {schema} users owner', schema)
    with pytest.raises(drill.DrillError):
        m.validate_archive(f'1; 2615 22 SCHEMA - public owner', schema)
    with pytest.raises(drill.DrillError):
        drill.new_run_directory(tmp_path)


def test_archive_sequence_owned_by_keeps_the_actual_namespace_check():
    m = module()
    schema = 'pa_test_c417a97aa52946e1baf4483f150f5145'
    # Actual pg_restore --list entries from the retained batch03 backup.
    entries = [
        f'21073; 0 0 SEQUENCE OWNED BY {schema} admin_configuration_pointer_id_seq paperassist_test',
        f'21074; 0 0 SEQUENCE OWNED BY {schema} operational_collection_id_seq paperassist_test',
        f'21075; 0 0 SEQUENCE OWNED BY {schema} storage_inventory_scans_id_seq paperassist_test',
    ]
    listing = f'65; 2615 79897607 SCHEMA - {schema} paperassist_test\n' + '\n'.join(entries)
    m.validate_archive(listing, schema)
    foreign = listing.replace('SEQUENCE OWNED BY ' + schema, 'SEQUENCE OWNED BY public', 1)
    with pytest.raises(drill.DrillError, match='archive_other_schema'):
        m.validate_archive(foreign, schema)


def test_post_http_only_explicit_auth_and_operational_tables_can_change():
    m = module()
    before = {name: {'sha256': 'a', 'rows': 1} for name in ('users', 'sessions', 'tasks', 'storage_objects', 'model_calls')}
    after = {**before, 'sessions': {'sha256': 'b', 'rows': 2}}
    assert m.business_unchanged(before, after) == ['sessions']
    for table in ('users', 'tasks', 'storage_objects', 'model_calls'):
        with pytest.raises(drill.DrillError):
            m.business_unchanged(before, {**after, table: {'sha256': 'b', 'rows': 1}})


def test_sealed_backup_validates_dirty_code_and_dump(tmp_path):
    from app.db.database import SCHEMA_HEAD
    m = module()
    schema = 'pa_test_' + uuid4().hex
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / '.complete').write_bytes(b'original')
    (tmp_path / 'code' / 'backend' / 'app').mkdir(parents=True)
    source = tmp_path / 'code' / 'backend' / 'app' / 'dirty.py'
    source.write_text('approved = True')
    (tmp_path / 'database.dump').write_bytes(b'fixture dump')
    values = {'asset-manifest.json': m.file_manifest(tmp_path / 'assets'), 'code-manifest.json': m.file_manifest(tmp_path / 'code'),
              'before-fingerprints.json': {}, 'sequences.json': {}, 'expected-api.json': dict(source_schema=schema)}
    for name, value in values.items():
        drill.write_json(tmp_path / name, value)
    evidence = {name: dict(bytes=(tmp_path / name).stat().st_size, sha256=drill.sha(tmp_path / name))
                for name in [*values, 'database.dump']}
    drill.write_json(tmp_path / 'manifest.json', dict(format_version=1, synthetic_only=True, schema_revision=SCHEMA_HEAD,
                     source_schema=schema, consistency_id=str(uuid4()), evidence=evidence))
    drill.write_json(tmp_path / 'manifest-receipt.json', dict(sha256=drill.sha(tmp_path / 'manifest.json')))
    assert m.validate_backup(tmp_path)['source_schema'] == schema
    source.write_text('unapproved = True')
    with pytest.raises(drill.DrillError):
        m.validate_backup(tmp_path)
    source.write_text('approved = True')
    (tmp_path / 'database.dump').unlink()
    with pytest.raises(drill.DrillError, match='evidence_mismatch'):
        m.validate_backup(tmp_path)

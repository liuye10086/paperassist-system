"""Private per-transaction byte proofs; real isolated SQL transactions, no science."""
from hashlib import sha256
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def phase_type():
    assert importlib.util.find_spec('app.domain.source_byte_verification'), 'explicit byte phase is not implemented'
    from app.domain.source_byte_verification import VerificationPhase
    return VerificationPhase


def material(tmp_path, raw=b'row_key\tvalue\ng1\t0\ng2\tNA\n'):
    from app.adapters.bio_objects import BioObjects
    objects = BioObjects(tmp_path)
    record = objects.describe('00000000-0000-0000-0000-000000000001', raw)
    objects.write(record, raw)
    assets = SimpleNamespace(directory=tmp_path, owner_id='owner')
    return assets, objects, record, raw


def test_phase_hash_once_next_phase_rehashes_and_consumer_is_fresh(tmp_path):
    from app.db.database import database_connection
    from app.core.exceptions import StorageError
    assets, objects, record, raw = material(tmp_path)
    Phase = phase_type()
    with database_connection() as db:
        with Phase(db, assets, 'project') as phase:
            phase.verify_object(db, assets, 'project', objects, record)
            path = objects.path(record['object_key']); stamp = path.stat()
            path.write_bytes(raw.replace(b'NA', b'99'))
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            phase.verify_object(db, assets, 'project', objects, record)
            assert phase.receipt()['full_reads'] == 1
            assert phase.receipt()['proof_hits'] == 1
            # No capture or permit is returned. All consumers keep their full hash.
            with pytest.raises(StorageError):objects.read(record)
        with Phase(db, assets, 'project') as again:
            with pytest.raises(StorageError):again.verify_object(db, assets, 'project', objects, record)
        with pytest.raises(StorageError):phase.check(db, assets, 'project')


def test_descriptor_cap_falls_back_to_full_hash_without_reducing_input_capacity(tmp_path):
    from app.db.database import database_connection
    assets, objects, record, raw = material(tmp_path)
    with database_connection() as db:
        with phase_type()(db, assets, 'project', descriptor_cap=1) as phase:
            for _ in range(2):phase.verify_object(db, assets, 'project', objects, record)
            assert phase.receipt()['full_reads'] == 1
            second = objects.describe('00000000-0000-0000-0000-000000000002', b'other')
            objects.write(second, b'other')
            for _ in range(2):phase.verify_object(db, assets, 'project', objects, second)
            result = phase.receipt()
            assert result['full_reads'] == 3 and result['retained_bytes'] == 0
            assert result['descriptors'] == 1 and result['fallback_reads'] == 2


@pytest.mark.parametrize('change', ['delete', 'truncate', 'symlink', 'windows_reparse_bit'])
def test_hit_checks_current_availability(tmp_path, monkeypatch, change):
    from app.db.database import database_connection
    from app.core.exceptions import StorageError
    assets, objects, record, raw = material(tmp_path)
    with database_connection() as db:
        with phase_type()(db, assets, 'project') as phase:
            phase.verify_object(db, assets, 'project', objects, record)
            path = objects.path(record['object_key'])
            if change == 'windows_reparse_bit':
                original = Path.lstat
                def reparse(candidate, *args, **kwargs):
                    value = original(candidate, *args, **kwargs)
                    return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=0x400) if candidate==path else value
                monkeypatch.setattr(Path, 'lstat', reparse)
            elif change == 'truncate':path.write_bytes(raw[:-1])
            else:
                path.unlink()
                if change == 'symlink':
                    target = tmp_path/'elsewhere'; target.write_bytes(raw)
                    try:path.symlink_to(target)
                    except OSError:pytest.skip('OS symlink permission unavailable')
            with pytest.raises(StorageError):phase.verify_object(db, assets, 'project', objects, record)


def test_scope_rejects_other_transaction_connection_identity_and_closed(tmp_path):
    from app.db.database import database_connection
    from app.core.exceptions import StorageError
    assets, _, _, _ = material(tmp_path)
    Phase = phase_type()
    with database_connection() as db, database_connection() as other:
        for args in [(other, assets, 'project'), (db, assets, 'other'),
                         (db, SimpleNamespace(directory=tmp_path, owner_id='other'), 'project'),
                         (db, SimpleNamespace(directory=tmp_path/'other', owner_id='owner'), 'project')]:
            with Phase(db, assets, 'project') as phase:
                phase.check(db, assets, 'project')
                with pytest.raises(StorageError):phase.check(*args)
    # An unmanaged real SQLAlchemy connection permits commit/begin between phases.
    from app.db.database import DatabaseConnection, get_database_config, get_engine
    config = get_database_config()
    with get_engine(config).connect() as connection:
        transaction = connection.begin()
        db = DatabaseConnection(connection, config)
        with Phase(db, assets, 'project') as phase:
            transaction.commit()
            transaction = connection.begin()
            with pytest.raises(StorageError):phase.check(db, assets, 'project')
        transaction.rollback()


def test_cancelled_hash_invalidates_phase_and_has_no_successful_proof(tmp_path):
    from app.db.database import database_connection
    from app.adapters.task_execution_store import LeaseLost
    from app.core.exceptions import StorageError
    assets, objects, record, _ = material(tmp_path, b'x'*1048577)
    with database_connection() as db:
        other = objects.describe('00000000-0000-0000-0000-000000000002', b'earlier leaf')
        objects.write(other, b'earlier leaf')
        for mode in ('cold_chunk', 'warm_other_chunk', 'warm_hit'):
            with phase_type()(db, assets, 'project') as phase:
                if mode != 'cold_chunk':
                    phase.verify_object(db, assets, 'project', objects, other if mode=='warm_other_chunk' else record)
                    assert phase.receipt()['descriptors']==1
                ticks = []
                def cancel():
                    ticks.append(True)
                    if mode=='warm_hit' or len(ticks)==2:raise LeaseLost()
                with pytest.raises(LeaseLost):phase.verify_object(db, assets, 'project', objects, record, progress=cancel)
                assert len(ticks)==(1 if mode=='warm_hit' else 2)
                assert phase.receipt()['descriptors'] == 0
                with pytest.raises(StorageError):phase.check(db, assets, 'project')


def test_large_lineage_proof_retains_no_bytes_and_does_not_mutate_record(tmp_path):
    from app.db.database import database_connection
    assets, objects, record, raw = material(tmp_path, b'x'*2097153)
    original = dict(record)
    with database_connection() as db:
        with phase_type()(db, assets, 'project') as phase:
            for _ in range(5):phase.verify_object(db, assets, 'project', objects, record)
            stats = phase.receipt()
            assert stats['full_reads'] == 1 and stats['verified_bytes'] == len(raw)
            assert stats['proof_hits'] == 4 and stats['retained_bytes'] == 0
    assert record == original

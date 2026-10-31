"""Lineage optimization never caches DB/source nodes or changes consumer bytes."""
from copy import deepcopy
import os

import pytest
from tests.integration.test_bio_analysis_setup import client, raw_source


def stores(project):
    from app.adapters.storage import ProjectStore
    from app.adapters.bio_analysis_store import BioAnalysisStore
    from app.core.config import get_data_dir
    from app.db.database import database_connection
    with database_connection() as db:
        owner = db.execute('SELECT owner_id FROM projects WHERE id=%s', (project,)).fetchone()['owner_id']
    assets = ProjectStore(get_data_dir(), owner_id=owner)
    return assets, BioAnalysisStore(assets)


def test_lineage_diamond_keeps_db_validation_and_fresh_public_calls(client, monkeypatch):
    base, source = raw_source(client); project = base.rsplit('/', 1)[-1]
    assets, store = stores(project)
    assert hasattr(store, '_raw_lineage_in_phase'), 'explicit lineage path is absent'
    from app.domain.source_byte_verification import VerificationPhase
    from app.domain.bioinformatics.service import BioDatasetService
    with store.store.connection() as db:
        before = store.raw(db, project, source)
        queries = []
        original = db.execute
        def observed(sql, parameters=()):
            queries.append(sql)
            return original(sql, parameters)
        monkeypatch.setattr(db, 'execute', observed)
        legacy_counts = []
        for _ in range(3):
            start = len(queries);store.raw(db, project, source);legacy_counts.append(len(queries)-start)
        with VerificationPhase(db, assets, project) as phase:
            for _ in range(3):
                start = len(queries)
                actual = store._raw_lineage_in_phase(db, project, source, phase=phase)
                assert actual == before
                assert len(queries)-start == legacy_counts[0]
            stats = phase.receipt()
            # Three raw matrix leaves plus original bundle; manifests/axes stay legacy reads.
            assert stats['full_reads'] == 4 and stats['proof_hits'] == 8
            assert stats['retained_bytes'] == 0
            task = store.store.require_task(db, before[0]['task_id'])
            file = db.execute('SELECT * FROM files WHERE id=%s', (source['source_file_ids'][0],)).fetchone()
            path = assets.directory / file['object_key'];raw = path.read_bytes();stamp = path.stat()
            path.write_bytes(bytes([raw[0]^1])+raw[1:]);os.utime(path, ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            # Same phase lineage proof is not permission to consume an original.
            store._raw_lineage_in_phase(db, project, source, phase=phase)
            from app.core.exceptions import StorageError
            with pytest.raises(StorageError):BioDatasetService(assets).require_sources(db, task)
        with VerificationPhase(db, assets, project) as fresh:
            with pytest.raises(StorageError):store._raw_lineage_in_phase(db, project, source, phase=fresh)


@pytest.mark.parametrize('mutation', ['state', 'binding', 'config', 'owner'])
def test_warm_lineage_still_checks_visible_db_mutation(client, mutation):
    from app.core.exceptions import StorageError
    base, source = raw_source(client);project = base.rsplit('/', 1)[-1]
    assets, store = stores(project)
    assert hasattr(store, '_raw_lineage_in_phase'), 'explicit lineage path is absent'
    from app.domain.source_byte_verification import VerificationPhase
    from app.db.database import migration_connection
    with migration_connection(write=True) as db:
        with VerificationPhase(db, assets, project) as phase:
            row, _, members = store._raw_lineage_in_phase(db, project, source, phase=phase)
            if mutation == 'state':
                db.execute("UPDATE storage_objects SET state='changed' WHERE object_key=%s", (members[0]['object_key'],))
            elif mutation == 'binding':
                # Fault injection in this test's isolated schema only; validators
                # must reject corrupted bindings independently of the DB seal.
                db.execute('ALTER TABLE bio_import_files DISABLE TRIGGER USER')
                db.execute("UPDATE bio_import_files SET source_sha256=%s WHERE import_id=(SELECT id FROM bio_imports WHERE task_id=%s)", ('0'*64,row['task_id']))
            elif mutation == 'config':
                db.execute('ALTER TABLE bio_imports DISABLE TRIGGER USER')
                db.execute("UPDATE bio_imports SET settings_json='{}'::jsonb WHERE task_id=%s", (row['task_id'],))
            else:db.execute('UPDATE users SET active=false WHERE id=%s', (assets.owner_id,))
            with pytest.raises(StorageError):store._raw_lineage_in_phase(db, project, source, phase=phase)
            with pytest.raises(StorageError):phase.check(db, assets, project)

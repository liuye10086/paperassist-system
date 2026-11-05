"""A19 ancestry reuses byte proofs; scientific consumers still read afresh."""
from collections import Counter
from hashlib import sha256
from pathlib import Path

import pytest

from tests.api.test_projects import client


def test_alternate_raw_members_are_read_once_per_lineage_phase(client, monkeypatch):
    from tests.helpers.bio_fixtures import visium_bundle_bytes
    from tests.integration.test_bio_analysis_setup import raw_source
    from tests.integration.test_source_byte_lineage import stores
    from app.domain.source_byte_verification import VerificationPhase
    from app.core.exceptions import StorageError

    monkeypatch.setattr('tests.integration.test_bio_import_publication.visium_bundle_bytes',
        lambda: visium_bundle_bytes(changes={'notes.txt': b'unconsumed source representation'}))
    base, source = raw_source(client); project = base.rsplit('/', 1)[-1]
    assets, store = stores(project)
    with store.store.connection() as db:
        expected = store.raw(db, project, source)
        record = next(m for m in expected[2] if m['role'] == 'supplementary')
        path = store.raw_store.objects.path(record['object_key'])
        opens = []; original = Path.open
        def observed(candidate, *args, **kwargs):
            if candidate == path and args and args[0] == 'rb': opens.append(candidate)
            return original(candidate, *args, **kwargs)
        monkeypatch.setattr(Path, 'open', observed)
        with VerificationPhase(db, assets, project) as phase:
            for _ in range(3):
                assert store._raw_lineage_in_phase(db, project, source, phase=phase) == expected
            assert len(opens) == 1
            # Reading the actual member is independent of the ancestry proof.
            raw = path.read_bytes(); path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            with pytest.raises(StorageError): store.raw_store.objects.read(record)
        with VerificationPhase(db, assets, project) as fresh:
            with pytest.raises(StorageError): store._raw_lineage_in_phase(db, project, source, phase=fresh)


def test_processed_binary_lineage_reuses_proof_but_runtime_rehashes(client, monkeypatch, tmp_path):
    from tests.integration.test_bio_analysis_wait import create, run, confirm, payload_engine
    from tests.integration.test_research_validation_efficiency import report_service
    from app.domain.bio_insights.sources import InsightSourceReader
    from app.domain.source_byte_verification import VerificationPhase
    from app.core.exceptions import StorageError

    def engine(payload, output, mode):
        result = payload_engine(payload, output, mode)
        for key, fmt in [('processed', 'h5ad'), ('counts_data', 'npy')]:
            raw = ('synthetic persistence bytes: ' + key).encode()
            path = Path(output) / (key + '.' + fmt); path.write_bytes(raw)
            result['outputs'].append(dict(key=key, role=key, format=fmt, path=str(path),
                size_bytes=len(raw), sha256=sha256(raw).hexdigest()))
        return result
    base, created, staging, _ = create(client, monkeypatch, tmp_path)
    assert run(created['task'], staging, engine)['status'] == 'waiting_confirmation'
    queued = confirm(client, base, created, client.get(base+'/bio-analysis-runs/'+created['id']).json())
    assert queued.status_code == 202, queued.text
    done = run(queued.json(), staging, engine); assert done['status'] == 'succeeded'
    value = client.get(base+'/bio-processed-datasets/'+done['result_bio_processed_dataset_version_id']).json()
    project = base.rsplit('/', 1)[-1]; assets = report_service(project).assets
    reader = InsightSourceReader(assets)
    selection = dict(source_kind='bio_processed_dataset_version', source_id=value['id'],
        sha256=value['manifest_sha256'], role='processed')
    with reader.store.connection() as db:
        _, _, records = reader.bio.processed_record(db, project, value['id'])
        paths = {reader.bio.objects.path(m['object_key']) for m in records if m['format'] in ('h5ad', 'npy')}
        opens = Counter(); original = Path.open
        def observed(path, *args, **kwargs):
            if path in paths and args and args[0] == 'rb': opens[path] += 1
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'open', observed)
        with VerificationPhase(db, assets, project) as phase:
            first = reader._resolve_in_phase(db, project, selection, phase=phase, lineage_only=True)
            assert reader._resolve_in_phase(db, project, selection, phase=phase, lineage_only=True) == first
            assert all(opens[p] == 1 for p in paths)
            assert reader._resolve_in_phase(db, project, selection, phase=phase, lineage_only=False) == first
            assert all(opens[p] == 2 for p in paths)
            path = next(iter(paths)); raw = path.read_bytes(); path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            with pytest.raises(StorageError): reader._resolve_in_phase(db, project, selection, phase=phase, lineage_only=False)
        with VerificationPhase(db, assets, project) as fresh:
            with pytest.raises(StorageError): reader._resolve_in_phase(db, project, selection, phase=fresh, lineage_only=True)

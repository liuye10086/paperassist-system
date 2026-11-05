"""Private, transaction-bound proofs for unconsumed source lineage only.

No bytes, paths or reusable permission are returned. Actual consumers must keep
their independent complete read/hash. Nothing here caches a database decision.
"""
import hashlib
from functools import wraps
from pathlib import Path
import re
import stat

from app.core.exceptions import StorageError
from app.domain.bioinformatics.contracts import conflict


RAW_MATRIX_KEYS = frozenset(('matrix_data', 'matrix_indices', 'matrix_indptr'))
# Retained source representations are not consumed when checking ancestry.
RAW_REPRESENTATION_ROLES = frozenset(('supplementary', 'derived_representation', 'alternate_matrix'))


def phase_guard(function):
    """An internal validation failure invalidates all proofs, even if caught."""
    @wraps(function)
    def guarded(*args, **kwargs):
        phase = kwargs.get('phase')
        try:
            return function(*args, **kwargs)
        except BaseException:
            if type(phase) is VerificationPhase:phase.close()
            raise
    return guarded


def require_phase(phase, db, assets, project):
    if type(phase) is not VerificationPhase:
        raise conflict('bio_input_integrity_changed')
    phase.check(db, assets, project)
    return phase


class VerificationPhase:
    """A bounded set of successful whole-file proofs, never a node/DAG cache."""
    def __init__(self, db, assets, project, *, descriptor_cap=2048):
        from app.db.database import DatabaseConnection
        if not isinstance(db, DatabaseConnection) or type(descriptor_cap) is not int or not 0 <= descriptor_cap <= 2048:
            raise conflict('bio_input_integrity_changed')
        self._db = db
        self._connection = db.raw_connection
        self._transaction = self._connection.get_transaction()
        self._owner = assets.owner_id
        self._project = project
        self._root = Path(assets.directory).resolve()
        self._closed = False
        self._proofs = set()
        self._descriptor_cap = descriptor_cap
        self._descriptor_bytes = 0
        self._stats = dict(full_reads=0, verified_bytes=0, proof_hits=0, fallback_reads=0,
                           max_chunk_bytes=0, retained_bytes=0)
        self.check(db, assets, project)

    def check(self, db, assets, project):
        connection = self._connection
        if (self._closed or db is not self._db or db.raw_connection is not connection
                or self._transaction is None or not self._transaction.is_active
                or connection.closed or connection.invalidated
                or connection.get_transaction() is not self._transaction
                or assets.owner_id != self._owner or project != self._project
                or Path(assets.directory).resolve() != self._root):
            self.close()
            raise conflict('bio_input_integrity_changed')

    def close(self):
        self._closed = True
        self._proofs.clear()
        self._descriptor_bytes = 0

    def __enter__(self):
        if self._closed:raise conflict('bio_input_integrity_changed')
        return self

    def __exit__(self, *args):
        self.close()

    def receipt(self):
        # Diagnostic copy only; never serialized into a source or task payload.
        return dict(self._stats, descriptors=len(self._proofs), descriptor_bytes=self._descriptor_bytes)

    def _available(self, path, size, failure):
        path = Path(path)
        if not path.is_absolute() or not path.is_relative_to(self._root):raise failure()
        current = self._root
        for part in (None, *path.relative_to(self._root).parts):
            if part is not None:current = current / part
            info = current.lstat()
            # Python 3.11 on Windows has no Path.is_junction(). Check reparse bit.
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise failure()
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size != size or path.resolve() != path:
            raise failure()

    def _verify(self, db, assets, project, record, *, namespace, path_for_key,
                maximum, minimum, failure, io_failure, progress):
        try:
            self.check(db, assets, project)
            if progress is not None:progress()
            size, sha, key = record['size_bytes'], record['sha256'], record['object_key']
            if (type(size) is not int or not minimum <= size <= maximum
                    or not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha)):
                raise failure()
            path = path_for_key(key)
            self._available(path, size, failure)
            proof = (namespace, key, size, sha)
            if proof in self._proofs:
                if progress is not None:progress()
                self.check(db, assets, project)
                self._stats['proof_hits'] += 1
                return
            descriptor_size = len(namespace.encode()) + len(key.encode()) + 128
            retain = (len(self._proofs) < self._descriptor_cap
                      and self._descriptor_bytes + descriptor_size <= 2 * 1024 * 1024)
            if not retain:self._stats['fallback_reads'] += 1
            self._stats['full_reads'] += 1
            hashed = hashlib.sha256(); count = 0
            with path.open('rb') as stream:
                while chunk := stream.read(min(1024 * 1024, size + 1 - count)):
                    count += len(chunk); hashed.update(chunk)
                    self._stats['max_chunk_bytes'] = max(self._stats['max_chunk_bytes'], len(chunk))
                    if progress is not None:progress()
                    if count > size:break
            if count != size or hashed.hexdigest() != sha:raise failure()
            self._available(path_for_key(key), size, failure)
            if progress is not None:progress()
            self.check(db, assets, project)
            self._stats['verified_bytes'] += count
            if retain:
                self._proofs.add(proof)
                self._descriptor_bytes += descriptor_size
        except (OSError, RuntimeError) as exc:
            self.close()
            raise io_failure(exc) from exc
        except BaseException:
            # Cancellation/LeaseLost must not leave earlier proofs reusable.
            self.close()
            raise

    def verify_object(self, db, assets, project, objects, record, *, progress=None):
        if Path(objects.root).resolve() != self._root:
            self.close();raise conflict('bio_input_integrity_changed')
        self._verify(db, assets, project, record, namespace='local:assets-v1:'+objects.prefix,
            path_for_key=objects.path, minimum=1, maximum=268435456,
            failure=conflict, io_failure=lambda exc: conflict(), progress=progress)

    def verify_original(self, db, assets, project, record, *, progress=None):
        from app.adapters.object_storage import LocalObjectStorage, changed
        from app.adapters.file_objects import MAX_RECORD_BYTES
        from app.adapters.task_store import DatasetTaskAssets
        self.check(db, assets, project)
        # Worker assets construct LocalFileObjects inside original(); they do
        # not expose ProjectStore.objects. Only that exact known adapter opts in.
        port = (LocalObjectStorage(assets.directory) if type(assets) is DatasetTaskAssets
                else getattr(getattr(assets, 'objects', None), 'port', None))
        if type(port) is not LocalObjectStorage:
            # Custom providers retain their own full read/hash contract.
            try:
                assets.original(record)
                if progress is not None:progress()
                self.check(db, assets, project)
            except BaseException:
                self.close();raise
            return
        if record.get('storage_backend', 'local') != port.backend_name or Path(port.root).resolve() != self._root:
            self.close();raise changed()
        def io_failure(exc):
            if isinstance(exc, FileNotFoundError):
                return StorageError('file_missing', '原始文件已缺失，请恢复数据目录或重新上传。', 410)
            return StorageError('storage_unavailable', '无法读取原始文件，请检查目录权限后重试。')
        self._verify(db, assets, project, record, namespace='local:original:'+str(record['id']),
            path_for_key=port._path, minimum=0, maximum=MAX_RECORD_BYTES,
            failure=changed, io_failure=io_failure, progress=progress)

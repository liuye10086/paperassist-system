"""Shared immutable original-file contract; local wrapper remains compatible."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import BinaryIO
from uuid import UUID, uuid5

from app.core.exceptions import StorageError
from app.adapters.object_storage import LocalObjectStorage, ObjectStoragePort, changed, validate_key

# A stored PostgreSQL bigint length plus the one-byte integrity probe must fit
# the port's signed 64-bit bound. Upload limits belong to business entry points.
MAX_RECORD_BYTES = 2**63 - 2
FILE_TYPES = frozenset({'xlsx', 'docx', 'pdf', 'png', 'jpeg', 'bio_bundle', 'bio_component'})


def original_digest(content: bytes) -> str:
    if type(content) is not bytes or not 0 < len(content) <= MAX_RECORD_BYTES:
        raise changed()
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class OriginalDescriptor:
    id: str
    file_type: str
    storage_backend: str
    object_key: str
    size_bytes: int
    sha256: str


class FileObjects:
    def __init__(self, port: ObjectStoragePort):
        self.port = port

    def put_original(self, project_id: str, operation_id: str, file_type: str,
                     content: bytes, *, item_id: str | None = None, db=None, operation_key=None) -> OriginalDescriptor:
        digest = original_digest(content)
        descriptor = self._describe_original(project_id, operation_id, file_type, item_id, len(content), digest)
        with self._publication(db, project_id, operation_key, descriptor):
            self.port.put_immutable(descriptor.object_key, content)
        return descriptor

    def put_original_stream(self, project_id: str, operation_id: str, file_type: str,
                            source: BinaryIO, size: int, digest: str, *,
                            item_id: str, db=None) -> OriginalDescriptor:
        if (type(size) is not int or not 0 < size <= MAX_RECORD_BYTES
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)):
            raise changed()
        descriptor = self._describe_original(project_id, operation_id, file_type, item_id, size, digest)
        with self._publication(db, project_id, None, descriptor):
            self.port.put_immutable_stream(descriptor.object_key, source, size, digest)
        return descriptor

    def _describe_original(self, project_id, operation_id, file_type, item_id, size, digest):
        # Ownership is checked by services before supplying these identities.
        # Only the adapter constructs an object key and file identity.
        try:
            if not isinstance(project_id, str) or not project_id or '\x00' in project_id:
                raise ValueError('Persisted project identity required')
            for value in (operation_id, *(() if item_id is None else (item_id,))):
                if not isinstance(value, str) or str(UUID(value)) != value:
                    raise ValueError('Canonical operation identity required')
            if file_type not in FILE_TYPES:
                raise ValueError('Unsupported file type')
            # Imported projects retain Text IDs. Hash their complete UTF-8
            # identity rather than placing legacy text in a filesystem key.
            # Keep canonical UUID projects' existing retry identities and keys.
            try:
                canonical_project = str(UUID(project_id)) == project_id
            except ValueError:
                canonical_project = False
            project_identity = (project_id if canonical_project else
                                hashlib.sha256(project_id.encode('utf-8')).hexdigest())
        except (ValueError, TypeError, AttributeError) as exc:
            raise changed() from exc
        identifier = str(uuid5(UUID(operation_id), f'{project_identity}:{item_id or ""}:{file_type}:{digest}'))
        # Synchronous public records omit object_key; preserve their UUID fallback.
        key = (f'files/{identifier}.{file_type}' if item_id is None else
               f'files/upload-{project_identity}-{operation_id}-{item_id}-{digest}.{file_type}')
        return OriginalDescriptor(identifier, file_type, self.port.backend_name, key, size, digest)

    @contextmanager
    def _publication(self, db, project_id, operation_key, descriptor):
        try:
            if db is None:
                yield
            else:
                from app.domain.storage_governance.service import publication_identity
                root = self.port.root
                with publication_identity(db, root, project_id, operation_key or 'original:' + descriptor.id,
                                          root / descriptor.object_key, descriptor.size_bytes, descriptor.sha256,
                                          kind='original', recover=True):
                    yield
        except (OSError, RuntimeError) as exc:
            raise StorageError('storage_unavailable', '无法保存文件原件，请稍后重试。') from exc

    def _original_identity(self, record):
        try:
            if record.get('storage_backend', 'local') != self.port.backend_name:
                raise changed()
            size, digest = record['size_bytes'], record['sha256']
            if (type(size) is not int or not 0 <= size <= MAX_RECORD_BYTES
                    or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)):
                raise changed()
            key = record.get('object_key')
            if key is None:
                identifier = record.get('id')
                if (self.port.backend_name != 'local' or record.get('file_type') != 'xlsx'
                        or not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', identifier)):
                    raise changed()
                key = f'files/{identifier}.xlsx'
            validate_key(key)
        except (KeyError, TypeError, AttributeError) as exc:
            raise changed() from exc
        return key, size, digest

    @contextmanager
    def _reading_original(self, record):
        identity = self._original_identity(record)
        try:
            yield identity
        except FileNotFoundError as exc:
            raise StorageError('file_missing', '原始文件已缺失，请恢复数据目录或重新上传。', 410) from exc
        except (OSError, RuntimeError) as exc:
            raise StorageError('storage_unavailable', '无法读取原始文件，请检查目录权限后重试。') from exc
    def original(self, record: dict) -> bytes:
        with self._reading_original(record) as (key, size, digest):
            content = self.port.read(key, size + 1)
            if type(content) is not bytes or len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                raise changed()
            return content

    def verify_original(self, record: dict) -> None:
        with self._reading_original(record) as (key, size, digest):
            self.port.verify(key, size, digest)


class LocalFileObjects(FileObjects):
    def __init__(self, directory: Path):
        port = LocalObjectStorage(directory)
        self.root = port.root
        super().__init__(port)

"""Private byte-store port and the production local implementation.

A future private provider must implement these semantics. No private provider is
configured by this module; keys are private server-owned references, never URLs.
"""
import hashlib
import os
from pathlib import Path
import stat
from typing import BinaryIO, Protocol
from uuid import uuid4

from app.core.exceptions import StorageError


CHUNK_BYTES = 64 * 1024


def changed() -> StorageError:
    return StorageError('file_changed', '原始文件对象引用或内容无效，请恢复原文件或重新上传。', 409)


def validate_key(key: str) -> str:
    if (not isinstance(key, str) or not key or '\\' in key or ':' in key or '\x00' in key
            or key.startswith('/') or any(part in ('', '.', '..') for part in key.split('/'))
            or key.split('/')[0] != 'files'):
        raise changed()
    return key


def stream_digest(source: BinaryIO, size: int, *, destination: BinaryIO | None = None) -> str:
    """Hash exactly the declared bytes and detect either truncation or surplus."""
    if type(size) is not int or size < 0:
        raise changed()
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        block = source.read(min(CHUNK_BYTES, remaining))
        if not block or len(block) > remaining:
            raise changed()
        remaining -= len(block)
        digest.update(block)
        if destination is not None:
            destination.write(block)
    if source.read(1):
        raise changed()
    return digest.hexdigest()


class ObjectStoragePort(Protocol):
    """Immutable private bytes. IO failures use FileNotFoundError/OSError.

    put_immutable must atomically publish absent bytes, accept identical replay,
    and raise file_changed/409 for different bytes without replacing anything.
    put_immutable_stream enforces the same contract with declared size and SHA256.
    read returns at most max_bytes; absence raises FileNotFoundError.
    No path, URL, or deletion API is exposed to the business layer.
    """
    backend_name: str

    def put_immutable(self, key: str, content: bytes) -> None: ...

    def put_immutable_stream(self, key: str, source: BinaryIO, size: int, digest: str) -> None: ...

    def read(self, key: str, max_bytes: int) -> bytes: ...

    def verify(self, key: str, size: int, digest: str) -> None: ...


class LocalObjectStorage:
    backend_name = 'local'

    def __init__(self, directory: Path):
        self.root = Path(directory).resolve()

    def _path(self, key: str) -> Path:
        path = self.root / validate_key(key)
        # Inspect every ancestor, including Windows junction aliases.
        candidates = [self.root]
        candidate = self.root
        for part in path.relative_to(self.root).parts:
            candidate = candidate / part
            candidates.append(candidate)
        for candidate in candidates:
            if (candidate.is_symlink()
                    or (hasattr(candidate, 'is_junction') and candidate.is_junction())
                    or candidate.resolve() != candidate.absolute()):
                raise changed()
        if not path.resolve().is_relative_to(self.root):
            raise changed()
        return path

    def read(self, key: str, max_bytes: int) -> bytes:
        path = self._path(key)
        with path.open('rb') as stream:
            chunks = bytearray()
            while len(chunks) < max_bytes:
                chunk = stream.read(min(CHUNK_BYTES, max_bytes - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
            return bytes(chunks)

    def put_immutable(self, key: str, content: bytes) -> None:
        def verify_existing(_source_written):
            if self.read(key, len(content) + 1) != content:
                raise changed()

        self._put_immutable(key, lambda destination: destination.write(content), verify_existing)

    def put_immutable_stream(self, key: str, source: BinaryIO, size: int, digest: str) -> None:
        def verify_source(destination=None):
            if stream_digest(source, size, destination=destination) != digest:
                raise changed()

        def verify_existing(source_written):
            if not source_written:
                verify_source()
            self.verify(key, size, digest)

        self._put_immutable(key, verify_source, verify_existing)

    def verify(self, key: str, size: int, digest: str) -> None:
        path = self._path(key)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size != size:
            raise changed()
        with path.open('rb') as source:
            if stream_digest(source, size) != digest:
                raise changed()

    def _put_immutable(self, key, write_source, verify_existing):
        temporary = None
        created = False
        try:
            target = self._path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target = self._path(key)
            if target.exists():
                verify_existing(False)
                return
            # Full UUID entropy without separators keeps the longest legacy
            # SHA256 project-key temporary filename below Windows' 255 limit.
            temporary_key = key + '.' + uuid4().hex + '.part'
            temporary = self._path(temporary_key)
            with temporary.open('xb') as stream:
                created = True
                write_source(stream)
                stream.flush()
                os.fsync(stream.fileno())
            self._path(temporary_key)
            target = self._path(key)
            try:
                # link is an atomic no-overwrite publish on Windows and Linux.
                os.link(temporary, target)
            except FileExistsError:
                verify_existing(True)
        except (OSError, RuntimeError) as exc:
            raise StorageError('storage_unavailable', '无法保存文件原件，请检查目录权限和磁盘空间。') from exc
        finally:
            if created and temporary is not None:
                try:
                    # Remove only the unpublished name owned by this call.
                    self._path(temporary_key).unlink(missing_ok=True)
                except (OSError, RuntimeError, StorageError):
                    pass

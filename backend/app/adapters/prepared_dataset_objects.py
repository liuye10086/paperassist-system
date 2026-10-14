"""Bounded, immutable candidate JSON objects, atomically published without replace."""
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import UUID, uuid4
from app.core.exceptions import StorageError
from app.domain.dataset_preparation.contracts import MAX_OBJECT_BYTES, PreparedDatasetObject


def changed(message='整理数据对象合同或完整性核验失败。'):
    return StorageError('dataset_changed', message, 409)


class PreparedDatasetObjects:
    def __init__(self, directory):
        self.root = Path(directory).resolve()

    def path(self, key):
        if not isinstance(key, str) or not re.fullmatch(r'prepared-datasets/[0-9a-f-]{36}/[0-9a-f]{64}\.json', key):
            raise changed('整理数据对象引用无效。')
        try:
            if str(UUID(key.split('/')[1])) != key.split('/')[1]:
                raise ValueError('Invalid UUID')
        except ValueError as exc:
            raise changed('整理数据对象引用无效。') from exc
        path = self.root / key
        for candidate in [self.root, self.root / 'prepared-datasets', path.parent, path]:
            if candidate.is_symlink() or (hasattr(candidate, 'is_junction') and candidate.is_junction()):
                raise changed('整理数据对象引用无效。')
            if candidate.exists() and candidate.resolve() != candidate.absolute():
                raise changed('整理数据对象引用无效。')
        if not path.resolve().is_relative_to(self.root):
            raise changed('整理数据对象引用无效。')
        return path

    def _validate_content(self, content):
        if type(content) is not bytes or not 0 < len(content) <= MAX_OBJECT_BYTES:
            raise changed('整理数据对象为空或超过大小限制。')
        try:
            return PreparedDatasetObject.model_validate(json.loads(content))
        except (ValueError, TypeError, RecursionError) as exc:
            raise changed() from exc

    def save(self, dataset_id, content):
        self._validate_content(content)
        digest = hashlib.sha256(content).hexdigest()
        key = f'prepared-datasets/{dataset_id}/{digest}.json'
        record = dict(object_key=key, sha256=digest, size_bytes=len(content))
        target = self.path(key)
        partial = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target = self.path(key)
            if target.exists():
                self.read(record)
                return record
            partial = target.with_name(target.name + '.' + str(uuid4()) + '.part')
            with partial.open('xb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(partial, target)
            except FileExistsError:
                self.read(record)
        except OSError as exc:
            raise StorageError('storage_unavailable', '无法保存整理数据对象，请检查目录权限。') from exc
        finally:
            if partial is not None:
                partial.unlink(missing_ok=True)
        return record

    def read(self, record):
        try:
            size, key, digest = record['size_bytes'], record['object_key'], record['sha256']
            if type(size) is not int or not 0 < size <= MAX_OBJECT_BYTES or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                raise ValueError('Invalid record size or hash')
            if 'id' in record and key != f"prepared-datasets/{record['id']}/{digest}.json":
                raise ValueError('Object and version identities differ')
            if not isinstance(key, str) or key.rsplit('/', 1)[-1] != digest + '.json':
                raise ValueError('Object key and digest differ')
            path = self.path(key)
            with path.open('rb') as stream:
                content = stream.read(size + 1)
        except FileNotFoundError as exc:
            raise StorageError('dataset_missing', '整理数据对象已缺失。', 410) from exc
        except OSError as exc:
            raise StorageError('storage_unavailable', '无法读取整理数据对象，请检查目录权限。') from exc
        except (KeyError, ValueError, TypeError) as exc:
            raise changed() from exc
        if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
            raise changed()
        return content, self._validate_content(content)

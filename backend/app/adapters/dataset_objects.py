"""Bounded, immutable, hash-verified local raw sheet objects."""
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4
from pydantic import BaseModel, ConfigDict
from typing import Literal
from app.domain.datasets.contracts import SheetStructure
from app.core.exceptions import StorageError


class DatasetObject(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    schema_version: Literal[1]
    epoch: Literal['1900','1904']
    sheet: SheetStructure


class DatasetObjects:
    def __init__(self, directory):
        self.root = Path(directory).resolve()

    def path(self, key):
        invalid = StorageError('dataset_changed','数据版本对象引用无效。',409)
        if not isinstance(key,str) or not re.fullmatch(r'datasets/[0-9a-f-]{36}/[0-9a-f]{64}\.json',key):
            raise invalid
        path = self.root / key
        for ancestor in [self.root, *path.relative_to(self.root).parents][:-1]:
            candidate = ancestor if ancestor.is_absolute() else self.root / ancestor
            if candidate.is_symlink() or (hasattr(candidate,'is_junction') and candidate.is_junction()):
                raise invalid
            if candidate.exists() and candidate.resolve() != candidate.absolute():
                raise invalid
        if path.is_symlink() or (path.exists() and path.resolve() != path.absolute()) or not path.resolve().is_relative_to(self.root):
            raise invalid
        return path

    @staticmethod
    def describe(dataset_id, content):
        digest = hashlib.sha256(content).hexdigest()
        key = f'datasets/{dataset_id}/{digest}.json'
        return dict(object_key=key,size_bytes=len(content),sha256=digest)

    def save(self, dataset_id, content):
        record = self.describe(dataset_id, content)
        key = record['object_key']
        target = self.path(key)
        target.parent.mkdir(parents=True,exist_ok=True)
        target = self.path(key)
        if target.exists():
            self.read(record)
            return record
        partial = target.with_name(target.name+'.'+str(uuid4())+'.part')
        try:
            with partial.open('xb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            # Atomic no-replace publication. A racing identical object is checked.
            try:
                os.link(partial,target)
            except FileExistsError:
                self.read(record)
        finally:
            partial.unlink(missing_ok=True)
        return record

    def read(self, record):
        if 'id' in record and record.get('object_key') != f"datasets/{record['id']}/{record.get('sha256')}.json":
            raise StorageError('dataset_changed','原始数据对象与版本身份不一致。',409)
        try:
            if type(record['size_bytes']) is not int or not 0 < record['size_bytes'] <= 4194304:
                raise ValueError('Invalid size')
            path = self.path(record['object_key'])
            with path.open('rb') as stream:
                content = stream.read(record['size_bytes']+1)
        except FileNotFoundError as exc:
            raise StorageError('dataset_missing','原始数据对象已缺失。',410) from exc
        except OSError as exc:
            raise StorageError('storage_unavailable','无法读取数据版本，请检查目录权限。') from exc
        if len(content)!=record['size_bytes'] or hashlib.sha256(content).hexdigest()!=record['sha256']:
            raise StorageError('dataset_changed','原始数据对象完整性核验失败。',409)
        try:
            obj = DatasetObject.model_validate(json.loads(content))
        except (ValueError,TypeError) as exc:
            raise StorageError('dataset_changed','原始数据对象合同无效。',409) from exc
        return content,obj

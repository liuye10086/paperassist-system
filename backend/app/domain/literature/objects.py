"""Immutable retrieval bytes inside the existing project asset directory."""
import hashlib
from pathlib import Path
import re
from uuid import uuid4

from app.core.config import get_data_dir
from app.core.exceptions import StorageError


class LiteratureObjects:
    def __init__(self, directory=None):
        self.directory = Path(directory if directory is not None else get_data_dir()).resolve()

    def path(self, key):
        if not isinstance(key, str) or not re.fullmatch(r'literature/[0-9a-f-]{36}/[0-9a-f]{64}\.(xml|json)', key):
            raise StorageError('literature_source_conflict', '文献来源对象不一致。', 409)
        path = (self.directory / key).resolve()
        if not path.is_relative_to(self.directory):
            raise StorageError('literature_source_conflict', '文献来源对象不一致。', 409)
        return path

    def save(self, raw, operation):
        if not isinstance(raw, bytes) or not (0 if operation == 'pmc_oai' else 1) <= len(raw) <= 8 * 1024 * 1024 or operation not in ('esearch', 'efetch', 'pmc_oai'):
            raise StorageError('ncbi_response_invalid', '检索接口返回格式不正确。', 502)
        digest = hashlib.sha256(raw).hexdigest()
        key = f'literature/{uuid4()}/{digest}.' + ('json' if operation == 'esearch' else 'xml')
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # The unique path is never reused. An interrupted unregistered object is
        # retained; this module does not delete or replace historical evidence.
        with path.open('xb') as stream:
            stream.write(raw)
        result = dict(object_key=key, sha256=digest, size_bytes=len(raw))
        if operation == 'pmc_oai': result['operation'] = operation
        return result

    def read(self, receipt):
        path = self.path(receipt['object_key'])
        try:
            if path.stat().st_size != receipt['size_bytes'] or not (0 if receipt.get('operation') == 'pmc_oai' else 1) <= receipt['size_bytes'] <= 8 * 1024 * 1024:
                raise ValueError()
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != receipt['sha256']:
                raise ValueError()
            return raw
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise StorageError('literature_source_conflict', '保存的文献来源缺失或已变化。', 409) from exc

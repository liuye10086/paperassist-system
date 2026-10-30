"""Content-addressed, bounded bio objects with no client-selected paths."""
import hashlib
import json
import re
import os
from pathlib import Path
from uuid import UUID, uuid4
from app.domain.bioinformatics.contracts import conflict


class BioObjects:
    prefix = 'bio-datasets'

    def __init__(self, directory):
        self.root = Path(directory).resolve()

    def path(self, key):
        if not isinstance(key, str) or not re.fullmatch(re.escape(self.prefix)+r'/[0-9a-f-]{36}/[0-9a-f]{64}\.(json|bin)', key):
            raise conflict()
        if str(UUID(key.split('/')[1])) != key.split('/')[1]:
            raise conflict()
        target = self.root / key
        for part in (self.root, target.parent.parent, target.parent, target):
            if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
                raise conflict()
        if not target.resolve().is_relative_to(self.root):
            raise conflict()
        return target

    def describe(self, import_id, content, *, json=False):
        sha = hashlib.sha256(content).hexdigest()
        record = {'object_key': f'{self.prefix}/{import_id}/{sha}.{"json" if json else "bin"}',
                  'sha256': sha, 'size_bytes': len(content)}
        self.path(record['object_key'])
        if not 0 < len(content) <= (2097152 if json else 268435456):
            raise conflict('bio_limit_exceeded')
        return record

    def write(self, record, content):
        if len(content) != record['size_bytes'] or hashlib.sha256(content).hexdigest() != record['sha256']:
            raise conflict()
        target = self.path(record['object_key'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target = self.path(record['object_key'])
        if target.exists():
            self.read(record)
            return
        temporary = target.with_name(target.name + '.' + uuid4().hex + '.part')
        try:
            with temporary.open('xb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self.path(record['object_key']))
            except FileExistsError:
                self.read(record)
        finally:
            temporary.unlink(missing_ok=True)
        self.read(record)

    def read(self, record):
        path = self.path(record['object_key'])
        try:
            size = record['size_bytes']
            if not 0 < size <= 268435456 or path.stat().st_size != size:
                raise conflict()
            with path.open('rb') as stream:
                content = stream.read(size + 1)
            if len(content) != size or hashlib.sha256(content).hexdigest() != record['sha256']:
                raise conflict()
            return content
        except OSError as exc:
            raise conflict() from exc

    def read_json(self, record):
        if record['size_bytes'] > 2097152 or not record['object_key'].endswith('.json'):
            raise conflict()
        try:
            return json.loads(self.read(record))
        except (ValueError, RecursionError) as exc:
            raise conflict() from exc


class BioAnalysisObjects(BioObjects):
    prefix='bio-analysis'


class BioMappingObjects(BioObjects):
    prefix='bio-mappings'


class BioAnnotationObjects(BioObjects):
    prefix='bio-annotations'


class BioFigureObjects(BioObjects):
    prefix='bio-figures'

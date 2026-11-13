"""Bounded disposable artifacts; callers hold the PostgreSQL heavy slot."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import time
from uuid import uuid4

from app.adapters.bio_insights_store import BioInsightsStore, invalid
from app.domain.bioinformatics.contracts import digest

_active = ContextVar('bulk_heavy_slot', default=None)
_KEY = re.compile(r'[a-f0-9]{64}')
_GENERATION = re.compile(r'[a-f0-9]{64}-[a-f0-9]{32}')


@lru_cache(maxsize=8)
def _slot_engine(url):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    return create_engine(url, poolclass=NullPool, hide_parameters=True, connect_args={'connect_timeout': 10})


def project_slot_key(config, project):
    scope = f'bulk-delivery-project:{config.url.database}:{config.schema}:{project}'
    return int.from_bytes(hashlib.sha256(scope.encode()).digest()[:8], 'big', signed=True)


@contextmanager
def heavy_slot(assets, project):
    service = BioInsightsStore(assets)
    config = assets.db_config
    identity = (str(config.url.database), config.schema)
    if _active.get() == identity:
        yield
        return
    with service.store.connection() as db:
        service.store.require_project(db, project)
    # Waiters must not exhaust the business pool needed by the current holder.
    with _slot_engine(config.url).connect() as connection, connection.begin():
        key = int.from_bytes(hashlib.sha256(('bulk-delivery:' + ':'.join(identity)).encode()).digest()[:8], 'big', signed=True)
        connection.exec_driver_sql('SELECT pg_catalog.pg_advisory_xact_lock(%s)', (key,))
        connection.exec_driver_sql('SELECT pg_catalog.pg_advisory_xact_lock(%s)', (project_slot_key(config, project),))
        # A request queued for the slot may have lost access while it waited.
        with service.store.connection() as db:
            service.store.require_project(db, project)
        token = _active.set(identity)
        try:
            yield
        finally:
            _active.reset(token)


def cache_pool(directory, config):
    schema = digest([str(Path(directory).resolve()), getattr(config.url, 'host', ''),
                     getattr(config.url, 'port', None), str(config.url.database), config.schema])
    return Path(tempfile.gettempdir()) / 'paperassist-bulk-delivery-v2' / schema


def cache_scope(owner_id, project, kind):
    return digest([owner_id, project, kind])


def cache_for(assets, project, kind):
    pool = cache_pool(assets.directory, assets.db_config)
    return ArtifactCache(pool / cache_scope(assets.owner_id, project, kind), pool=pool)


def file_digest(path):
    hashed = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            hashed.update(chunk)
    return hashed.hexdigest()


class ArtifactCache:
    def __init__(self, root, *, pool=None, ttl=1800, budget=2 * 1024**3):
        self.root = Path(root).absolute()
        self.pool = Path(pool).absolute() if pool is not None else self.root
        self.ttl, self.budget = ttl, budget
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, key):
        if not _KEY.fullmatch(key):
            raise invalid('bio_insight_not_found', 404)
        return self.root / (key + '.json')

    def read(self, key):
        try:
            generation = self._path(key).read_text(encoding='ascii')
            if not _GENERATION.fullmatch(generation) or not generation.startswith(key + '-'):
                return None
            path = self.root / generation
            if path.is_symlink():
                return None
            manifest = json.loads((path / 'complete.json').read_text(encoding='utf-8'))
            if (not isinstance(manifest, dict) or manifest.pop('manifest_sha256', None) != digest(manifest)
                    or not isinstance(manifest.get('metadata'), dict) or not isinstance(manifest.get('files'), dict)):
                return None
            if time.time() - manifest['created'] >= self.ttl:
                return None
            for name, expected in manifest['files'].items():
                if Path(name).name != name or name == 'complete.json':
                    return None
                file = path / name
                if file.is_symlink() or file.stat().st_size != expected['size'] or file_digest(file) != expected['sha256']:
                    return None
            return dict(path=path, metadata=manifest['metadata'])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def prune(self, *, keep=None, needed=0):
        entries = []
        scopes = ([self.root] if self.pool == self.root else
                  [p for p in self.pool.iterdir() if p.is_dir() and not p.is_symlink() and _KEY.fullmatch(p.name)])
        for path in (p for scope in scopes for p in scope.iterdir()):
            if not path.is_dir() or path.is_symlink():
                continue
            if not needed and path.name.startswith('building-') and time.time() - path.stat().st_mtime >= max(60, self.ttl):
                self._remove(path)
            if not _GENERATION.fullmatch(path.name):
                continue
            try:
                size = sum(p.stat().st_size for p in path.iterdir() if p.is_file())
                entries.append((path.stat().st_mtime, size, path))
            except OSError:
                continue
        total = sum(size for _, size, _ in entries)
        for created, size, path in sorted(entries):
            if path.name != keep and (time.time() - created >= self.ttl or total + needed > self.budget or len(entries) >= 32):
                self._remove(path)
                if not path.exists():
                    total -= size
                    entries = [entry for entry in entries if entry[2] != path]
        for scope in scopes:
            for pointer in scope.glob('*.json'):
                if pointer.is_symlink() or not _KEY.fullmatch(pointer.stem):
                    continue
                try:
                    name = pointer.read_text(encoding='ascii')
                    if not _GENERATION.fullmatch(name) or not (scope / name).exists():
                        pointer.unlink(missing_ok=True)
                except (OSError, ValueError):
                    continue
        # Windows may retain files held by an active response; count them until closed.
        return total

    def _remove(self, path):
        # Never follow a cache-directory junction or leave the private derived pool.
        path = path.absolute()
        if path.is_symlink() or not path.resolve().is_relative_to(self.pool.resolve()):
            return
        if getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            return
        shutil.rmtree(path, ignore_errors=True)

    def obtain(self, key, build):
        found = self.read(key)
        if found:
            return found
        self.prune()
        pointer = self._path(key)
        target = self.root / (key + '-' + uuid4().hex)
        folder = Path(tempfile.mkdtemp(prefix='building-', dir=self.root))
        try:
            metadata = build(folder)
            files = {p.name: dict(size=p.stat().st_size, sha256=file_digest(p)) for p in folder.iterdir() if p.is_file()}
            manifest = dict(created=time.time(), metadata=metadata, files=files)
            manifest_bytes = json.dumps(manifest | {'manifest_sha256': digest(manifest)}).encode('utf-8')
            size = sum(item['size'] for item in files.values()) + len(manifest_bytes)
            if self.prune(needed=size) + size > self.budget:
                raise invalid('bio_insight_limit_exceeded', 422)
            (folder / 'complete.json').write_bytes(manifest_bytes)
            folder.replace(target)
            temporary = self.root / ('pointer-' + uuid4().hex)
            try:
                temporary.write_text(target.name, encoding='ascii')
                temporary.replace(pointer)
            finally:
                temporary.unlink(missing_ok=True)
            return dict(path=target, metadata=metadata)
        finally:
            if folder.exists():
                self._remove(folder)

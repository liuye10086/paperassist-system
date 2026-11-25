"""Discover and verify a bounded, read-only release of PaperAssist skills."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from itertools import islice
from pathlib import Path, PureWindowsPath
from tempfile import NamedTemporaryFile
from typing import Annotated, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from app.domain.model_usage.contracts import StrictContract

MANIFEST_FILENAME = 'manifest.json'
MAX_SKILLS = 32
MAX_FILES = 32
MAX_FILE_BYTES = 256 * 1024
MAX_PACK_BYTES = 4 * 1024 * 1024
MAX_HEADER_BYTES = 8 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
MAX_HISTORY = 512
NAME_PATTERN = r'^[a-z0-9]+(?:-[a-z0-9]+)*$'
_COMPONENT = r'(?:0|[1-9][0-9]{0,7})'
VERSION_PATTERN = rf'^{_COMPONENT}\.{_COMPONENT}\.{_COMPONENT}$'
HASH_PATTERN = r'^[0-9a-f]{64}$'
_PATH_PART = re.compile(r'[a-z0-9]+(?:[-_][a-z0-9]+)*')
_TEXT_TYPES = {'.md', '.txt', '.json', '.csv', '.tsv'}
_ASSET_TYPES = _TEXT_TYPES | {'.png', '.jpg', '.jpeg'}

Name = Annotated[str, Field(min_length=1, max_length=64, pattern=NAME_PATTERN)]
Version = Annotated[str, Field(pattern=VERSION_PATTERN)]
Sha256 = Annotated[str, Field(pattern=HASH_PATTERN)]
MetadataValue = Annotated[str, Field(max_length=1024)]


class SkillError(ValueError):
    """An installation or release error with a message safe for operator logs."""


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise SkillError('duplicate manifest key')
        result[key] = value
    return result


def _name_ok(value: str) -> bool:
    return len(value) <= 64 and bool(re.fullmatch(NAME_PATTERN, value)) and not PureWindowsPath(value).is_reserved()


def valid_file(value: str, *, body=True) -> bool:
    if value == 'SKILL.md':
        return body
    parts = value.split('/')
    if len(parts) < 2 or len(parts) > 4 or parts[0] not in ('references', 'assets'):
        return False
    stem, dot, extension = parts[-1].rpartition('.')
    if not dot or ('.' + extension) not in (_TEXT_TYPES if parts[0] == 'references' else _ASSET_TYPES):
        return False
    return all(
        len(part) <= 64 and _PATH_PART.fullmatch(part) and not PureWindowsPath(part).is_reserved()
        for part in (*parts[1:-1], stem)
    )


class SkillHeader(StrictContract):
    name: Name
    description: str = Field(min_length=1, max_length=1024)
    metadata: dict[Name, MetadataValue] = Field(max_length=16)
    license: MetadataValue | None = None
    compatibility: str | None = Field(default=None, max_length=500)
    allowed_tools: MetadataValue | None = Field(default=None, alias='allowed-tools')

    @model_validator(mode='after')
    def require_metadata(self):
        if (not self.description.strip()
                or not re.fullmatch(NAME_PATTERN, self.metadata.get('category', ''))
                or not re.fullmatch(VERSION_PATTERN, self.metadata.get('version', ''))):
            raise ValueError('skill description, category or version is invalid')
        return self


class FileDigest(StrictContract):
    sha256: Sha256
    size: int = Field(ge=1, le=MAX_FILE_BYTES)


class SkillEntry(StrictContract):
    header: SkillHeader
    files: dict[str, FileDigest] = Field(min_length=1, max_length=MAX_FILES)

    @model_validator(mode='after')
    def require_paths(self):
        if 'SKILL.md' not in self.files or not all(valid_file(path) for path in self.files):
            raise ValueError('illegal skill resource path')
        return self

    @property
    def version(self) -> str:
        return self.header.metadata['version']

    @property
    def digest(self) -> str:
        return sha256(_json_bytes(self.model_dump(mode='json', by_alias=True, exclude_none=True)))


class Manifest(StrictContract):
    schema_version: Literal[1]
    skills: dict[Name, SkillEntry] = Field(min_length=1, max_length=MAX_SKILLS)
    history: dict[str, Sha256] = Field(max_length=MAX_HISTORY)

    @model_validator(mode='after')
    def require_consistency(self):
        for name, entry in self.skills.items():
            if not _name_ok(name) or name != entry.header.name:
                raise ValueError('skill name and directory differ')
            previous = self.history.get(f'{name}@{entry.version}')
            if previous is not None and previous != entry.digest:
                raise ValueError('immutable skill version changed')
        for key in self.history:
            name, _, version = key.partition('@')
            if not _name_ok(name) or not re.fullmatch(VERSION_PATTERN, version):
                raise ValueError('invalid historical skill version')
        if sum(file.size for entry in self.skills.values() for file in entry.files.values()) > MAX_PACK_BYTES:
            raise ValueError('skill pack size exceeds limit')
        return self

    def serialize(self) -> bytes:
        return _json_bytes(self.model_dump(mode='json', by_alias=True, exclude_none=True)) + b'\n'


class _HeaderLoader(yaml.SafeLoader):
    def __init__(self, value: str):
        super().__init__(value)
        self.depth = 0

    def compose_node(self, parent, index):
        event = self.peek_event()
        if self.depth >= 4 or isinstance(event, yaml.AliasEvent) or event.anchor or event.tag:
            raise SkillError('unsupported skill YAML construct')
        self.depth += 1
        try:
            node = super().compose_node(parent, index)
            if node.tag not in ('tag:yaml.org,2002:map', 'tag:yaml.org,2002:str'):
                raise SkillError('skill frontmatter requires string values and mappings')
            return node
        finally:
            self.depth -= 1

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in mapping:
                raise SkillError('non-string or duplicate skill YAML key')
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _document(data: bytes) -> tuple[SkillHeader, str]:
    if not data.startswith(b'---\n'):
        raise SkillError('missing skill frontmatter')
    frontmatter, end, body = data[4:].partition(b'\n---\n')
    if not end or len(frontmatter) > MAX_HEADER_BYTES:
        raise SkillError('missing or oversized skill frontmatter')
    try:
        header = SkillHeader.model_validate(yaml.load(frontmatter.decode('utf-8'), Loader=_HeaderLoader))
        instructions = body.decode('utf-8').strip()
    except (yaml.YAMLError, UnicodeError, ValidationError):
        raise SkillError('invalid skill frontmatter or text') from None
    if not instructions or '\x00' in instructions:
        raise SkillError('invalid skill body')
    return header, instructions


def _kind(path: Path) -> int:
    try:
        details = path.lstat()
    except OSError:
        raise SkillError('skill package or resource is missing or unreadable') from None
    attributes = getattr(details, 'st_file_attributes', 0)
    if stat.S_ISLNK(details.st_mode) or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise SkillError('skill package contains a symbolic link or reparse point')
    return stat.S_IFMT(details.st_mode)


def _children(directory: Path, limit: int) -> list[Path]:
    if _kind(directory) != stat.S_IFDIR:
        raise SkillError('skill path is not a directory')
    try:
        entries = list(islice(directory.iterdir(), limit + 1))
    except OSError:
        raise SkillError('skill directory is unreadable') from None
    if len(entries) > limit:
        raise SkillError('skill directory entry limit exceeded')
    return sorted(entries, key=lambda path: path.name)


def _read(path: Path, maximum: int) -> bytes:
    if _kind(path) != stat.S_IFREG:
        raise SkillError('skill resource is not a regular file')
    text = path.suffix in _TEXT_TYPES
    try:
        with path.open('rb') as stream:
            data = stream.read(maximum * (2 if text else 1) + 1)
    except OSError:
        raise SkillError('skill resource is unreadable') from None
    if text:
        data = data.replace(b'\r\n', b'\n')
        if b'\r' in data:
            raise SkillError('unsupported skill text line ending')
    if not 0 < len(data) <= maximum:
        raise SkillError('skill resource size exceeds limit or is empty')
    return data


def _skill_files(directory: Path, prefix=''):
    for path in _children(directory, MAX_FILES):
        relative = prefix + path.name
        kind = _kind(path)
        if kind == stat.S_IFDIR and (
                relative in ('references', 'assets')
                or prefix and relative.count('/') < 3 and _PATH_PART.fullmatch(path.name)
                and len(path.name) <= 64 and not PureWindowsPath(path.name).is_reserved()):
            yield relative + '/', path
            yield from _skill_files(path, relative + '/')
        elif kind == stat.S_IFREG and valid_file(relative):
            yield relative, path
        else:
            raise SkillError('illegal skill resource or directory')


def discover(root: Path) -> dict[str, SkillEntry]:
    skills = {}
    remaining = MAX_PACK_BYTES
    for directory in _children(root, MAX_SKILLS + 1):
        kind = _kind(directory)
        name = directory.name
        if name == MANIFEST_FILENAME and kind == stat.S_IFREG:
            continue
        if kind != stat.S_IFDIR or not _name_ok(name) or len(skills) >= MAX_SKILLS:
            raise SkillError('illegal skill name or package entry')
        header = None
        files = {}
        for index, (relative, path) in enumerate(_skill_files(directory)):
            if index >= MAX_FILES + 2 or len(files) >= MAX_FILES:
                raise SkillError('skill resource count exceeds limit')
            if relative.endswith('/'):
                continue
            data = _read(path, min(MAX_FILE_BYTES, remaining))
            remaining -= len(data)
            files[relative] = FileDigest(sha256=sha256(data), size=len(data))
            if relative == 'SKILL.md':
                header, _ = _document(data)
        if header is None or header.name != name or header.name in skills:
            raise SkillError('missing or duplicate skill name or directory mismatch')
        skills[name] = SkillEntry(header=header, files=files)
    return skills


class Release:
    def __init__(self, root: Path, manifest: Manifest):
        self.root = root
        self.manifest = manifest
        self.sha256 = sha256(manifest.serialize())

    def _entry(self, skill: str) -> SkillEntry:
        result = self.manifest.skills.get(skill)
        if result is None:
            raise SkillError('required skill is missing')
        return result

    def resource(self, skill: str, relative: str) -> tuple[bytes, FileDigest]:
        expected = self._entry(skill).files.get(relative)
        if not valid_file(relative) or expected is None:
            raise SkillError('resource is outside the skill release')
        path = self.root
        parts = (skill, *relative.split('/'))
        for part in parts[:-1]:
            path = path / part
            if _kind(path) != stat.S_IFDIR:
                raise SkillError('skill resource parent is not a directory')
        value = _read(path / parts[-1], expected.size)
        if len(value) != expected.size or sha256(value) != expected.sha256:
            raise SkillError('skill resource digest mismatch')
        return value, expected

    def instructions(self, skill: str) -> str:
        value, _ = self.resource(skill, 'SKILL.md')
        header, instructions = _document(value)
        if header != self._entry(skill).header:
            raise SkillError('skill header differs from its manifest')
        return instructions


def open_release(root: Path, *, expected_sha256: str | None = None) -> Release:
    if _kind(root) != stat.S_IFDIR:
        raise SkillError('skill package root is not a directory')
    raw = _read(root / MANIFEST_FILENAME, MAX_MANIFEST_BYTES)
    try:
        manifest = Manifest.model_validate(json.loads(raw, object_pairs_hook=_pairs))
        canonical = manifest.serialize()
    except SkillError:
        raise
    except (ValueError, RecursionError):
        raise SkillError('skill release manifest is invalid') from None
    if raw != canonical:
        raise SkillError('skill release manifest is not canonical')
    release = Release(root, manifest)
    if expected_sha256 is not None and release.sha256 != expected_sha256:
        raise SkillError('skill release manifest pin differs')
    return release


def check_release(root: Path, *, expected_sha256: str | None = None) -> Release:
    release = open_release(root, expected_sha256=expected_sha256)
    if discover(root) != release.manifest.skills:
        raise SkillError('skill release digest differs from its files')
    return release


def publish(root: Path, *, verify=None) -> Release:
    """Freeze the discovered files while retaining prior version identities."""
    skills = discover(root)
    path = root / MANIFEST_FILENAME
    history = {}
    if path.exists():
        previous = open_release(root).manifest
        history.update(previous.history)
        for name, entry in previous.skills.items():
            if name not in skills or entry.version != skills[name].version:
                history[f'{name}@{entry.version}'] = entry.digest
            elif entry.digest != skills[name].digest:
                raise SkillError('immutable skill version changed')
    try:
        manifest = Manifest(schema_version=1, skills=skills, history=history)
    except ValidationError:
        raise SkillError('invalid or changed immutable skill release') from None
    raw = manifest.serialize()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise SkillError('skill manifest size exceeds limit')
    release = Release(root, manifest)
    if verify is not None:
        verify(release)
    with NamedTemporaryFile(dir=root, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(raw)
            stream.close()
            temporary.chmod(0o644)
            temporary.replace(path)
        finally:
            stream.close()
            temporary.unlink(missing_ok=True)
    return release

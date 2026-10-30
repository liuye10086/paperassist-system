"""Bounded container reading; archive names are identities, never OS paths."""
from dataclasses import dataclass
import gzip
import io
import re
import tarfile
import unicodedata

from app.domain.bioinformatics.parser_contracts import BioParseError


@dataclass
class Member:
    name: str
    content: bytes
    source_file_id: str | None = None
    declared_role: str | None = None


class Budget:
    def __init__(self, limits):
        self.limits, self.expanded, self.members = limits, 0, 0

    def read(self, stream):
        result = bytearray()
        while True:
            block = stream.read(min(65536, self.limits.max_member_bytes - len(result) + 1))
            if not block:
                break
            result.extend(block)
            self.expanded += len(block)
            if len(result) > self.limits.max_member_bytes or self.expanded > self.limits.max_expanded_bytes:
                raise BioParseError("bio_input_limit", "expanded_bytes")
        return bytes(result)


def normalized_name(name):
    if not isinstance(name, str) or not name or "\x00" in name or len(name) > 1024:
        raise BioParseError("bio_archive_invalid", "member_name")
    name = unicodedata.normalize("NFC", name.replace("\\", "/"))
    pieces = name.split("/")
    if name.startswith("/") or any(p == ".." or ":" in p for p in pieces):
        raise BioParseError("bio_archive_invalid", "member_path")
    clean = "/".join(p for p in pieces if p and p != ".")
    if not clean:
        raise BioParseError("bio_archive_invalid", "member_path")
    return clean


def unpack(content, filename, budget, source_file_id=None):
    if type(content) is not bytes or not content or len(content) > budget.limits.max_upload_bytes:
        raise BioParseError("bio_input_limit", "upload_bytes")
    seen, result = set(), []

    def walk(data, name, depth, archive_hint=False, original_name=None):
        if depth > 2:
            raise BioParseError("bio_archive_invalid", "container_depth")
        is_gzip = data.startswith(b"\x1f\x8b")
        if is_gzip:
            if depth >= 2:
                raise BioParseError("bio_archive_invalid", "container_depth")
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                    expanded = budget.read(stream)
            except (OSError, EOFError, ValueError):
                raise BioParseError("bio_archive_invalid", "gzip_integrity") from None
            stripped = re.sub(r"\.(?:gz|tgz)$", ".tar" if name.lower().endswith(".tgz") else "", name, flags=re.I)
            # tar.gz is one archive container; contained gzip is the second.
            tar_gzip = name.lower().endswith((".tar.gz", ".tgz"))
            walk(expanded, stripped, depth if tar_gzip else depth + 1,
                 archive_hint=tar_gzip, original_name=original_name or name)
            return
        looks_tar = archive_hint or name.lower().endswith(".tar") or (len(data) >= 262 and data[257:262] == b"ustar")
        if looks_tar:
            if depth >= 2:
                raise BioParseError("bio_archive_invalid", "container_depth")
            try:
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
                    for ordinal, item in enumerate(archive):
                        if ordinal > budget.limits.max_members * 4:
                            raise BioParseError("bio_input_limit", "archive_members")
                        identity = normalized_name(item.name)
                        if identity.casefold() in seen:
                            raise BioParseError("bio_archive_invalid", "duplicate_member_path")
                        seen.add(identity.casefold())
                        if item.isdir():
                            continue
                        if not item.isfile() or item.issparse() or item.pax_headers.get("GNU.sparse.map"):
                            raise BioParseError("bio_archive_invalid", "non_regular_member")
                        budget.members += 1
                        if budget.members > budget.limits.max_members or item.size > budget.limits.max_member_bytes:
                            raise BioParseError("bio_input_limit", "archive_member")
                        stream = archive.extractfile(item)
                        if stream is None:
                            raise BioParseError("bio_archive_invalid", "missing_member")
                        with stream:
                            member_data = budget.read(stream)
                        walk(member_data, identity, depth + 1)
            except (tarfile.TarError, OSError, EOFError, ValueError):
                raise BioParseError("bio_archive_invalid", "tar_integrity") from None
            return
        if data.startswith(b"\x1f\x8b"):
            raise BioParseError("bio_archive_invalid", "container_depth")
        if len(data) > budget.limits.max_member_bytes:
            raise BioParseError("bio_input_limit", "member_bytes")
        # Keep the compressed archive member identity for provenance.
        result.append(Member(original_name or name, data, source_file_id))

    try:
        walk(content, normalized_name(filename), 0)
    except RecursionError:
        raise BioParseError("bio_archive_invalid", "container_depth") from None
    return result

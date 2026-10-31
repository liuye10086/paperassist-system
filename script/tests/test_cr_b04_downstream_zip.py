"""Acceptance downloads one formal ZIP and proves each sibling member identity."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest


def module():
    path = Path(__file__).resolve().parents[1] / 'dev/cr_b04_downstream.py'
    spec = importlib.util.spec_from_file_location('cr_b04_downstream_zip_test', path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def fixture_package(mod):
    from openpyxl import Workbook
    from app.domain.research_results.report_package import make_package
    table = b'row_key\tvalue\nfirst\t0\nsecond\tNA\n'
    book = Workbook()
    sheet = book.active
    sheet.title = 'results'
    sheet.append(['row_key', 'value'])
    sheet.append(['first', '0'])
    sheet.append(['second', 'NA'])
    buffer = io.BytesIO()
    book.save(buffer)
    book.close()
    files = {'analysis.docx': b'fixture-docx-exact-bytes', 'results.xlsx': buffer.getvalue(),
             'methods.txt': b'fixture exact methods\n', 'tables/table_000.tsv': table}
    raw, manifest = make_package(files, {'finding_version_id': 'finding'})
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files['manifest.json'] = archive.read('manifest.json')
    raws = dict(docx=files['analysis.docx'], xlsx=files['results.xlsx'], methods=files['methods.txt'],
                manifest=files['manifest.json'], zip=raw)
    count = dict(source={'source_id': 'table-id'}, sha256=mod.sha(table), rows=2, sheets=['results'])
    base = '/api/v1/projects/project'
    pairs = {'docx': ('analysis', 'docx'), 'xlsx': ('results', 'xlsx'), 'methods': ('methods', 'txt'),
             'manifest': ('manifest', 'json'), 'zip': ('analysis_package', 'zip')}
    members = [dict(id=role + '-id', role=role, key=pair[0], format=pair[1], sha256=mod.sha(raws[role]),
                    size_bytes=len(raws[role]), download_url=base + '/research-reports/report/members/' + role + '-id/download')
               for role, pair in pairs.items()]
    report = dict(id='report', root_id='report', revision=1, task_id='task', members=members,
                  manifest={'row_counts': {'tables': [count]}}, content={'tables': [{'sha256': mod.sha(table)}]})
    sources = {'table-id': dict(columns=['row_key', 'value'], rows=[['first', '0'], ['second', 'NA']], sha256=mod.sha(table))}
    return report, raws, sources


class ReachedPdf(Exception):
    pass


def acceptance(mod, tmp_path, report, raws, sources):
    value = object.__new__(mod.Acceptance)
    value.base = '/api/v1/projects/project'
    value.output = tmp_path
    value.source_tables = sources
    value.post = lambda *args, **kwargs: report
    value.wait = lambda task_id: None
    value.get = lambda path: report
    calls = []
    downloads = {member['download_url']: raws.get(member['role'], b'unknown-role-fixture') for member in report['members']}

    def get(path):
        calls.append(path)
        return SimpleNamespace(status_code=200, content=downloads[path])

    value.client = SimpleNamespace(get=get)

    def pdf(label, kind, identity, sha, folder):
        assert (label, kind, identity, sha) == ('report-pdf-en', 'research_report', 'docx-id', mod.sha(raws['docx']))
        raise ReachedPdf()

    value.pdf = pdf
    return value, calls, downloads


def test_report_downloads_one_zip_and_saves_identical_formal_bytes(tmp_path):
    mod = module()
    report, raws, sources = fixture_package(mod)
    run, calls, _ = acceptance(mod, tmp_path, report, raws, sources)
    with pytest.raises(ReachedPdf):
        run.report('en', {'id': 'finding'}, None)
    for member in report['members']:
        target = tmp_path / 'en' / (member['key'] + '.' + member['format'])
        assert target.read_bytes() == raws[member['role']]
    assert calls == [next(m['download_url'] for m in report['members'] if m['role'] == 'zip')]
    receipt = json.loads((tmp_path / 'en/acquisition.json').read_text())
    assert receipt['method'] == 'verified_formal_report_zip'
    assert receipt['standalone_member_endpoints_exercised'] is False
    assert len(receipt['derived_members']) == 4
    before = {p.name: p.read_bytes() for p in (tmp_path / 'en').iterdir()}
    calls.clear()
    with pytest.raises(ReachedPdf):
        run.report('en', {'id': 'finding'}, None)
    assert calls == []
    assert {p.name: p.read_bytes() for p in (tmp_path / 'en').iterdir()} == before


def repackage(report, raws, edit):
    with zipfile.ZipFile(io.BytesIO(raws['zip'])) as original:
        entries = [(i.filename, original.read(i)) for i in original.infolist()]
    entries = edit(entries)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in entries:
            archive.writestr(name, raw)
    raws['zip'] = stream.getvalue()
    member = next(m for m in report['members'] if m['role'] == 'zip')
    member.update(sha256=hashlib.sha256(raws['zip']).hexdigest(), size_bytes=len(raws['zip']))


@pytest.mark.parametrize('case', ['missing_member', 'corrupt_zip_sha', 'corrupt_zip_size', 'formal_sibling_sha',
                                 'formal_sibling_size', 'duplicate_entry', 'traversal', 'backslash', 'absolute',
                                 'manifest_hash', 'duplicate_manifest', 'bad_checksums', 'extra_role', 'duplicate_role',
                                 'duplicate_json_key', 'bool_formal_size', 'bool_manifest_size', 'directory', 'symlink',
                                 'directory_mode', 'directory_dos', 'member_budget', 'missing_role', 'duplicate_id', 'foreign_report_url'])
def test_invalid_package_or_formal_records_are_rejected_without_saved_outputs(tmp_path, case):
    mod = module()
    report, raws, sources = fixture_package(mod)
    if case == 'missing_member':
        repackage(report, raws, lambda es: [(n, b) for n, b in es if n != 'methods.txt'])
    elif case == 'duplicate_entry':
        with pytest.warns(UserWarning, match='Duplicate name'):
            repackage(report, raws, lambda es: es + [('methods.txt', b'collision')])
    elif case in ('traversal', 'backslash', 'absolute'):
        name = {'traversal': '../escape.txt', 'backslash': 'folder\\escape.txt', 'absolute': '/escape.txt'}[case]
        repackage(report, raws, lambda es: es + [(name, b'bad')])
    elif case == 'manifest_hash':
        repackage(report, raws, lambda es: [(n, b + b'changed' if n == 'methods.txt' else b) for n, b in es])
    elif case == 'duplicate_manifest':
        def edit(es):
            result = []
            for name, raw in es:
                if name == 'manifest.json':
                    manifest = json.loads(raw)
                    manifest['members'].append(deepcopy(manifest['members'][0]))
                    raw = json.dumps(manifest).encode()
                result.append((name, raw))
            return result
        repackage(report, raws, edit)
    elif case == 'duplicate_json_key':
        repackage(report, raws, lambda es: [(n, b'{"schema_version":1,' + b[1:] if n == 'manifest.json' else b) for n, b in es])
    elif case == 'bool_manifest_size':
        def edit(es):
            result = []
            for name, raw in es:
                if name == 'manifest.json':
                    manifest = json.loads(raw)
                    manifest['members'][0]['size_bytes'] = True
                    raw = json.dumps(manifest).encode()
                result.append((name, raw))
            return result
        repackage(report, raws, edit)
    elif case == 'bool_formal_size':
        report['members'][0]['size_bytes'] = True
    elif case == 'directory':
        repackage(report, raws, lambda es: es + [('empty/', b'')])
    elif case in ('directory_mode', 'directory_dos'):
        info = zipfile.ZipInfo('empty-directory-without-slash')
        info.external_attr = (0o40755 << 16) if case == 'directory_mode' else 0x10
        repackage(report, raws, lambda es: es + [(info, b'')])
    elif case == 'symlink':
        info = zipfile.ZipInfo('unsafe-link')
        info.create_system = 3
        info.external_attr = (0o120777 << 16)
        repackage(report, raws, lambda es: es + [(info, b'outside')])
    elif case == 'member_budget':
        repackage(report, raws, lambda es: es + [('extras/' + str(i), b'') for i in range(256)])
    elif case == 'missing_role':
        report['members'] = [m for m in report['members'] if m['role'] != 'methods']
    elif case == 'duplicate_id':
        report['members'][1]['id'] = report['members'][0]['id']
    elif case == 'foreign_report_url':
        report['members'][0]['download_url'] = report['members'][0]['download_url'].replace('/report/', '/other/')
    elif case == 'bad_checksums':
        repackage(report, raws, lambda es: [(n, b'bad' if n == 'SHA256SUMS.txt' else b) for n, b in es])
    elif case in ('extra_role', 'duplicate_role'):
        extra = deepcopy(report['members'][0])
        if case == 'extra_role':
            extra['role'] = 'unknown'
        report['members'].append(extra)
    else:
        role = 'zip' if case.startswith('corrupt_zip') else 'docx'
        member = next(m for m in report['members'] if m['role'] == role)
        if case.endswith('sha'):
            member['sha256'] = '0' * 64
        else:
            member['size_bytes'] += 1
    run, _, _ = acceptance(mod, tmp_path, report, raws, sources)
    with pytest.raises((ValueError, AssertionError, zipfile.BadZipFile)):
        run.report('en', {'id': 'finding'}, None)
    assert not list(tmp_path.rglob('*.*')), 'Rejected package must not create partial evidence'


@pytest.mark.parametrize('filename', ['methods.txt', 'analysis_package.zip', 'analysis.docx'])
def test_existing_file_conflict_is_preserved_and_not_overwritten(tmp_path, filename):
    mod = module()
    report, raws, sources = fixture_package(mod)
    folder = tmp_path / 'en'
    folder.mkdir()
    original = b'protected prior methods'
    (folder / filename).write_bytes(original)
    run, _, _ = acceptance(mod, tmp_path, report, raws, sources)
    with pytest.raises(ValueError):
        run.report('en', {'id': 'finding'}, None)
    assert (folder / filename).read_bytes() == original
    assert [p.name for p in folder.iterdir()] == [filename]


def test_zip_byte_budget_is_enforced_before_writing(tmp_path, monkeypatch):
    mod = module()
    report, raws, sources = fixture_package(mod)
    monkeypatch.setattr(mod, 'REPORT_ZIP_MAX_BYTES', 100, raising=False)
    run, _, _ = acceptance(mod, tmp_path, report, raws, sources)
    with pytest.raises(ValueError):
        run.report('en', {'id': 'finding'}, None)
    assert not list(tmp_path.rglob('*.*'))


def test_retained_zip_alone_recovers_missing_siblings_without_any_download(tmp_path):
    mod = module()
    report, raws, sources = fixture_package(mod)
    folder = tmp_path / 'en'
    folder.mkdir()
    (folder / 'analysis_package.zip').write_bytes(raws['zip'])
    run, calls, _ = acceptance(mod, tmp_path, report, raws, sources)
    with pytest.raises(ReachedPdf):
        run.report('en', {'id': 'finding'}, None)
    assert calls == []
    for member in report['members']:
        assert (folder / (member['key'] + '.' + member['format'])).read_bytes() == raws[member['role']]
